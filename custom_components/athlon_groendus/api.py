from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import aiohttp
import boto3
from botocore.config import Config as BotoConfig
from warrant_lite import WarrantLite

from .const import (
    APPSYNC_GRAPHQL_URL,
    COGNITO_CLIENT_ID,
    COGNITO_REGION,
    COGNITO_USER_POOL_ID,
)


class AthlonGroendusAuthError(Exception):
    """Authentication failed."""


class AthlonGroendusApiError(Exception):
    """API request failed."""


@dataclass
class Tokens:
    id_token: str
    access_token: str
    refresh_token: str | None
    expires_in: int


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

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._tokens: Tokens | None = None

    async def authenticate(self) -> None:
        """Authenticate via Cognito SRP and store tokens."""

        def _do_auth() -> Tokens:
            client = boto3.client(
                "cognito-idp",
                region_name=COGNITO_REGION,
                config=BotoConfig(signature_version="v4"),
            )
            aws = WarrantLite(
                username=self._email,
                password=self._password,
                pool_id=COGNITO_USER_POOL_ID,
                client_id=COGNITO_CLIENT_ID,
                client=client,
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
        except Exception as err:  # noqa: BLE001 (HA uses broad handling here)
            raise AthlonGroendusAuthError(str(err)) from err

    async def _graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._tokens is None:
            await self.authenticate()

        payload: dict[str, Any] = {"query": query}
        if variables is not None:
            payload["variables"] = variables

        headers = {
            "Authorization": self._tokens.id_token,
            "Content-Type": "application/json",
        }

        async with self._session.post(
            APPSYNC_GRAPHQL_URL,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            data = await resp.json()

        if "errors" in data:
            raise AthlonGroendusApiError(str(data["errors"]))
        return data.get("data") or {}

    async def get_driver_and_chargepoints(self) -> dict[str, Any]:
        data = await self._graphql(QUERY_BOOTSTRAP)
        return data.get("getDriver") or {}

    async def list_transactions(
        self,
        *,
        page: int = 1,
        size: int = 50,
        sort: str = "startDateTime:DESC",
        filter_: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        variables: dict[str, Any] = {
            "page": {"page": page, "size": size, "sort": sort},
            "filter": filter_,
        }
        data = await self._graphql(QUERY_TRANSACTIONS, variables=variables)
        return data.get("listTransactions") or {}


