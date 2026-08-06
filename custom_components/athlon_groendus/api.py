from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import json
import time
from typing import Any

import aiohttp
import boto3
from botocore import UNSIGNED
from botocore.config import Config as BotoConfig
from warrant_lite import ForceChangePasswordException, WarrantLite

from .const import (
    APPSYNC_GRAPHQL_URL,
    CLIENT_GROUP,
    COGNITO_CLIENT_ID,
    COGNITO_REGION,
    COGNITO_USER_POOL_ID,
    DEFAULT_LABEL,
    DEFAULT_PORTAL_URL,
)


class AthlonGroendusAuthError(Exception):
    """Authentication failed."""


class AthlonGroendusLabelError(AthlonGroendusAuthError):
    """The credentials are fine but the account is not part of the configured label."""


class AthlonGroendusApiError(Exception):
    """API request failed."""

_LOGGER = logging.getLogger(__name__)


@dataclass
class Tokens:
    id_token: str
    access_token: str
    refresh_token: str | None
    expires_in: int


@dataclass
class PortalConfig:
    """AWS backend config as published by the portal at /api/config."""

    user_pool_id: str = COGNITO_USER_POOL_ID
    client_id: str = COGNITO_CLIENT_ID
    region: str = COGNITO_REGION
    graphql_url: str = APPSYNC_GRAPHQL_URL

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "PortalConfig":
        cognito = data.get("cognito") or {}
        appsync = data.get("appSync") or {}
        return cls(
            user_pool_id=cognito.get("userPoolId") or COGNITO_USER_POOL_ID,
            client_id=cognito.get("clientId") or COGNITO_CLIENT_ID,
            region=data.get("region") or COGNITO_REGION,
            graphql_url=appsync.get("url") or APPSYNC_GRAPHQL_URL,
        )


QUERY_BOOTSTRAP = """
query bootstrap {
  getDriver {
    id
    firstName
    lastName
    email
    iban
    installationState
    chargepoints {
      id
      chargepointId
      isPublic
      currentTariff {
        id
        currency
        ... on SimpleTariff {
          energyPrice
        }
      }
      evses {
        id
        evseId
        status
      }
    }
  }
}
"""


QUERY_TRANSACTIONS = """
query TransactionListPage($page: PageInput, $filter: FilterInput) {
  listTransactions(page: $page, filter: $filter) {
    totalCount
    page {
      page
      size
      sort
    }
    items {
      id
      type
      chargepointId
      visualNumber
      tariff
      startDateTime
      endDateTime
      totalEnergy
      totalCost
      status
      errorCode
      invoicePeriod
    }
  }
}
"""


class AthlonGroendusClient:
    """Athlon Groendus AppSync GraphQL client."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        *,
        portal_url: str = DEFAULT_PORTAL_URL,
        label: str = DEFAULT_LABEL,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._portal_url = portal_url if portal_url.endswith("/") else f"{portal_url}/"
        self._label = label
        self._config: PortalConfig | None = None
        self._tokens: Tokens | None = None
        self._token_expires_at: float | None = None
        self._auth_lock = asyncio.Lock()

    async def async_get_config(self) -> PortalConfig:
        """Fetch the portal's AWS config, falling back to the bundled defaults."""
        if self._config is not None:
            return self._config

        url = f"{self._portal_url}api/config"
        try:
            async with self._session.get(
                url,
                # The portal's WAF answers 502 unless the request carries a
                # Referer, which the browser sends automatically for the
                # frontend's own XHR to /api/config.
                headers={"Accept": "application/json", "Referer": self._portal_url},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
            self._config = PortalConfig.from_api(data)
            _LOGGER.debug(
                "Discovered portal config from %s: pool=%s graphql=%s",
                url,
                self._config.user_pool_id,
                self._config.graphql_url,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Could not fetch portal config from %s (%s); using bundled defaults", url, err
            )
            self._config = PortalConfig()

        return self._config

    def _token_is_valid(self) -> bool:
        """Return True when we have a token that is not about to expire."""
        if self._tokens is None or self._token_expires_at is None:
            return False
        # Refresh a bit early to avoid edge cases.
        return time.time() < (self._token_expires_at - 60)

    async def _ensure_authenticated(self) -> None:
        """Ensure we have a valid token, re-authenticating if needed."""
        if self._token_is_valid():
            return
        async with self._auth_lock:
            # Another waiter may already have refreshed.
            if self._token_is_valid():
                return
            await self.authenticate()

    async def authenticate(self) -> None:
        """Authenticate via Cognito SRP and store tokens."""

        config = await self.async_get_config()

        client_metadata: dict[str, str] = {
            # Matches the web portal (see getClientMetadata() in the frontend bundle)
            "client": CLIENT_GROUP,
            "label": self._label,
            "portalUrl": self._portal_url,
        }

        class _WarrantLiteWithClientMetadata(WarrantLite):
            """WarrantLite variant that forwards ClientMetadata required by Cognito triggers."""

            def __init__(self, *args: Any, client_metadata: dict[str, str] | None = None, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                self._client_metadata = client_metadata or {}

            def authenticate_user(self, client: Any = None) -> Any:  # type: ignore[override]
                boto_client = self.client or client
                auth_params = self.get_auth_params()
                response = boto_client.initiate_auth(
                    AuthFlow="USER_SRP_AUTH",
                    AuthParameters=auth_params,
                    ClientId=self.client_id,
                    ClientMetadata=self._client_metadata,
                )

                if response["ChallengeName"] == self.PASSWORD_VERIFIER_CHALLENGE:
                    challenge_response = self.process_challenge(response["ChallengeParameters"])
                    challenge_response["USERNAME"] = self.username
                    tokens = boto_client.respond_to_auth_challenge(
                        ClientId=self.client_id,
                        ChallengeName=self.PASSWORD_VERIFIER_CHALLENGE,
                        ChallengeResponses=challenge_response,
                        ClientMetadata=self._client_metadata,
                    )

                    if tokens.get("ChallengeName") == self.NEW_PASSWORD_REQUIRED_CHALLENGE:
                        raise ForceChangePasswordException("Change password before authenticating")

                    return tokens

                raise NotImplementedError(f"The {response['ChallengeName']} challenge is not supported")

        def _do_auth() -> Tokens:
            client = boto3.client(
                "cognito-idp",
                region_name=config.region,
                # Cognito User Pool auth APIs (InitiateAuth / RespondToAuthChallenge)
                # are public and must be called unsigned (no AWS credentials required).
                config=BotoConfig(signature_version=UNSIGNED),
            )
            aws = _WarrantLiteWithClientMetadata(
                username=self._email,
                password=self._password,
                pool_id=config.user_pool_id,
                client_id=config.client_id,
                client=client,
                client_metadata=client_metadata,
            )
            tokens = aws.authenticate_user()
            auth = tokens.get("AuthenticationResult") or {}
            id_token = auth.get("IdToken")
            access_token = auth.get("AccessToken")
            if not id_token or not access_token:
                raise AthlonGroendusAuthError("Missing Cognito tokens")
            return Tokens(
                id_token=id_token,
                access_token=access_token,
                refresh_token=auth.get("RefreshToken"),
                expires_in=int(auth.get("ExpiresIn", 3600)),
            )

        try:
            self._tokens = await asyncio.get_running_loop().run_in_executor(None, _do_auth)
            self._token_expires_at = time.time() + int(self._tokens.expires_in or 3600)
        except Exception as err:  # noqa: BLE001 (HA uses broad handling here)
            _LOGGER.exception("Authentication failed (%s): %s", type(err).__name__, err)
            # The PreAuthentication Lambda rejects accounts that belong to a
            # different tenant. Surface that as its own error so the user knows
            # to change the label/portal URL rather than their password.
            if "is not part of the" in str(err):
                raise AthlonGroendusLabelError(
                    f"Account is not part of the '{self._label}' label "
                    f"(portal {self._portal_url}): {err}"
                ) from err
            raise AthlonGroendusAuthError(str(err)) from err

    async def _graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        # (Re)authenticate if needed before calling AppSync.
        await self._ensure_authenticated()
        graphql_url = (await self.async_get_config()).graphql_url

        payload: dict[str, Any] = {"query": query}
        if variables is not None:
            payload["variables"] = variables

        # Retry once on auth errors (expired token, etc.)
        for attempt in (1, 2):
            headers = {
                "Authorization": self._tokens.id_token if self._tokens else "empty",
                "Content-Type": "application/json",
            }

            try:
                async with self._session.post(
                    graphql_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    data = await resp.json()
            except aiohttp.ClientResponseError as err:
                # If AppSync returns 401/403, refresh token and retry once.
                if attempt == 1 and err.status in (401, 403):
                    _LOGGER.info("AppSync returned %s, refreshing token and retrying", err.status)
                    self._tokens = None
                    self._token_expires_at = None
                    await self._ensure_authenticated()
                    continue
                raise

            errors = data.get("errors")
            if errors:
                # Detect auth-related GraphQL errors and retry once.
                err_str = str(errors)
                if attempt == 1 and ("Unauthorized" in err_str or "NotAuthorized" in err_str):
                    _LOGGER.info("AppSync unauthorized, refreshing token and retrying")
                    self._tokens = None
                    self._token_expires_at = None
                    await self._ensure_authenticated()
                    continue
                raise AthlonGroendusApiError(err_str)

            return data.get("data") or {}

        raise AthlonGroendusApiError("GraphQL request failed after retry")

    async def get_driver_and_chargepoints(self) -> dict[str, Any]:
        data = await self._graphql(QUERY_BOOTSTRAP)
        return data.get("getDriver") or {}

    async def list_transactions(
        self,
        *,
        page: int = 1,
        size: int = 50,
        # AppSync schema defines PageInput.sort as AWSJSON -> must be a JSON-encoded string.
        # The portal uses: {"startDateTime":"DESC"} (stringified).
        sort: dict[str, str] | str | None = None,
        filter_: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sort_json: str
        if sort is None:
            sort_json = json.dumps({"startDateTime": "DESC"})
        elif isinstance(sort, str):
            sort_json = sort
        else:
            sort_json = json.dumps(sort)

        variables: dict[str, Any] = {
            "page": {"page": page, "size": size, "sort": sort_json},
            "filter": filter_,
        }
        data = await self._graphql(QUERY_TRANSACTIONS, variables=variables)
        return data.get("listTransactions") or {}


