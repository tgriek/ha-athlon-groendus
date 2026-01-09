#!/usr/bin/env python3
"""
Standalone verifier for Athlon Groendus.

Purpose:
- Validate Cognito SRP authentication
- Validate AppSync GraphQL queries (bootstrap + listTransactions)

This script does NOT depend on Home Assistant and is useful for debugging.

Usage:
  python tools/verify_standalone.py

Env:
  ATHLON_GROENDUS_EMAIL
  ATHLON_GROENDUS_PASSWORD
"""

from __future__ import annotations

import os
from typing import Any

import aiohttp
import boto3
from botocore import UNSIGNED
from botocore.config import Config as BotoConfig
from dotenv import load_dotenv
from warrant_lite import WarrantLite

# Reverse engineered constants
COGNITO_USER_POOL_ID = "eu-central-1_8IPEVy8kc"
COGNITO_CLIENT_ID = "387nbhei8uvf13f7ck4c5ivaa2"
COGNITO_REGION = "eu-central-1"
APPSYNC_GRAPHQL_URL = "https://kylqo4g6gres3lmw4rtqaoftke.appsync-api.eu-central-1.amazonaws.com/graphql"

# Required by Cognito PreAuthentication trigger in this tenant
CLIENT_METADATA = {
    "client": "Portal",
    "label": "athlon",
    "portalUrl": "https://athlon.groendus.nl/",
}

QUERY_BOOTSTRAP = """
query bootstrap {
  getDriver {
    id
    firstName
    lastName
    email
    installationState
    chargepoints { chargepointId isPublic }
  }
}
"""

QUERY_TRANSACTIONS = """
query TransactionListPage($page: PageInput, $filter: FilterInput) {
  listTransactions(page: $page, filter: $filter) {
    totalCount
    page { page size sort }
    items {
      id
      chargepointId
      startDateTime
      endDateTime
      totalEnergy
      totalCost
      status
    }
  }
}
"""


class _WarrantLiteWithClientMetadata(WarrantLite):
    def authenticate_user(self, client: Any = None) -> Any:  # type: ignore[override]
        boto_client = self.client or client
        auth_params = self.get_auth_params()
        response = boto_client.initiate_auth(
            AuthFlow="USER_SRP_AUTH",
            AuthParameters=auth_params,
            ClientId=self.client_id,
            ClientMetadata=CLIENT_METADATA,
        )
        if response["ChallengeName"] != self.PASSWORD_VERIFIER_CHALLENGE:
            raise RuntimeError(f"Unsupported challenge: {response.get('ChallengeName')}")

        challenge_response = self.process_challenge(response["ChallengeParameters"])
        challenge_response["USERNAME"] = self.username
        return boto_client.respond_to_auth_challenge(
            ClientId=self.client_id,
            ChallengeName=self.PASSWORD_VERIFIER_CHALLENGE,
            ChallengeResponses=challenge_response,
            ClientMetadata=CLIENT_METADATA,
        )


def get_id_token(email: str, password: str) -> str:
    client = boto3.client(
        "cognito-idp",
        region_name=COGNITO_REGION,
        config=BotoConfig(signature_version=UNSIGNED),
    )
    wl = _WarrantLiteWithClientMetadata(
        username=email,
        password=password,
        pool_id=COGNITO_USER_POOL_ID,
        client_id=COGNITO_CLIENT_ID,
        client=client,
    )
    tokens = wl.authenticate_user()
    return tokens["AuthenticationResult"]["IdToken"]


async def gql(id_token: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {"Authorization": id_token, "Content-Type": "application/json"}
    payload: dict[str, Any] = {"query": query}
    if variables is not None:
        payload["variables"] = variables
    async with aiohttp.ClientSession() as s:
        async with s.post(APPSYNC_GRAPHQL_URL, json=payload, headers=headers, timeout=30) as r:
            return await r.json()


async def main() -> None:
    load_dotenv()
    email = os.getenv("ATHLON_GROENDUS_EMAIL") or ""
    password = os.getenv("ATHLON_GROENDUS_PASSWORD") or ""
    if not email or not password:
        raise SystemExit("Missing ATHLON_GROENDUS_EMAIL / ATHLON_GROENDUS_PASSWORD in environment/.env")

    print("Authenticating with Cognito…")
    id_token = get_id_token(email, password)
    print("Auth OK.")

    print("Fetching driver/chargepoints (bootstrap)…")
    boot = await gql(id_token, QUERY_BOOTSTRAP)
    if "errors" in boot:
        raise SystemExit(f"Bootstrap failed: {boot['errors']}")
    driver = (boot.get("data") or {}).get("getDriver") or {}
    cps = driver.get("chargepoints") or []
    print(f"Driver: {driver.get('firstName')} {driver.get('lastName')} ({driver.get('email')})")
    print(f"Chargepoints: {len(cps)}")
    for cp in cps[:5]:
        print(f" - {cp.get('chargepointId')} (public={cp.get('isPublic')})")

    print("Fetching transactions (no sort)…")
    txs = await gql(id_token, QUERY_TRANSACTIONS, variables={"page": {"page": 1, "size": 10}, "filter": None})
    if "errors" in txs:
        raise SystemExit(f"Transactions failed: {txs['errors']}")
    lt = (txs.get("data") or {}).get("listTransactions") or {}
    items = lt.get("items") or []
    print(f"Transactions returned: {len(items)} (totalCount={lt.get('totalCount')})")
    if items:
        print(f"Newest start: {items[0].get('startDateTime')} (id={items[0].get('id')})")
        print(f"Oldest start: {items[-1].get('startDateTime')} (id={items[-1].get('id')})")

    print("OK.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())


