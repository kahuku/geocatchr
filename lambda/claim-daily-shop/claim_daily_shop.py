"""
Daily shop-claim replay Lambda.

Replays GeoGuessr's daily-shop-claim POST using the cookies/headers/browser
fingerprint captured by the Chrome extension (see
lambda/shop-claim-credentials/) and stored on each user's player-map profile
row (PK=COGNITO#<sub>, SK=PROFILE, attributes shop_claim_*).

This talks to GeoGuessr's own API directly over HTTPS — it does not go
through API Gateway, JWT auth, or any GeoCatchr endpoint. There's no reason
to import lambda/common/duel_core.py here: that module also requires
STATS_TABLE_NAME and RAW_BUCKET_NAME env vars at import time (for the
duel-stats Lambdas), which this function has no use for and shouldn't need
to configure just to run.

Not yet wired to a schedule — for now, invoke manually from the console
Test tab. Wiring an EventBridge daily(1am) rule to this is future work.

Invoke (AWS console "Test" tab)
--------------------------------
Claim for every user with stored credentials:

    { "dry_run": true }
    { "dry_run": false }

Restrict to one user (e.g. to test with your own account first):

    { "cognito_sub": "<sub>", "dry_run": false }

Required env vars:
    PLAYER_MAP_TABLE_NAME
"""

import json
import os
from typing import Any, Dict, List, Tuple
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

import boto3
from boto3.dynamodb.conditions import Attr

dynamodb = boto3.resource("dynamodb")
PLAYER_MAP_TABLE_NAME = os.environ["PLAYER_MAP_TABLE_NAME"]
player_map_table = dynamodb.Table(PLAYER_MAP_TABLE_NAME)

GEOGUESSR_CLAIM_URL = "https://www.geoguessr.com/api/v4/webshop/daily-shop-claim"
REQUEST_TIMEOUT_SECONDS = 15


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    event = event or {}
    dry_run = bool(event.get("dry_run", True))  # safe default: dry run
    only_sub = event.get("cognito_sub")  # optional: restrict to one user

    targets = [only_sub] if only_sub else list_users_with_credentials()

    counts: Dict[str, int] = {}
    results: List[Dict[str, Any]] = []

    for cognito_sub in targets:
        result = claim_for_user(cognito_sub, dry_run)
        counts[result["status"]] = counts.get(result["status"], 0) + 1
        results.append(result)
        print(f"[{result['status']}] {cognito_sub} :: {result['message']}")

    summary = {
        "dry_run": dry_run,
        "processed": len(results),
        "counts": counts,
        "results": results,
    }
    print("SUMMARY:", json.dumps(counts))
    return summary


# ---------------------------------------------------------------------------
# Per-user claim
# ---------------------------------------------------------------------------

def list_users_with_credentials() -> List[str]:
    """Scans the player-map table for every profile row with stored cookies."""
    subs: List[str] = []
    scan_kwargs: Dict[str, Any] = {
        "FilterExpression": Attr("shop_claim_cookies").exists(),
        "ProjectionExpression": "cognito_sub",
    }

    while True:
        resp = player_map_table.scan(**scan_kwargs)
        subs.extend(item["cognito_sub"] for item in resp.get("Items", []) if item.get("cognito_sub"))
        if "LastEvaluatedKey" not in resp:
            break
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    return subs


def claim_for_user(cognito_sub: str, dry_run: bool) -> Dict[str, Any]:
    item = player_map_table.get_item(Key={"PK": f"COGNITO#{cognito_sub}", "SK": "PROFILE"}).get("Item")
    if not item:
        return {"cognito_sub": cognito_sub, "status": "failed", "message": "No player-map profile row found"}

    cookies = item.get("shop_claim_cookies") or {}
    if not cookies:
        return {"cognito_sub": cognito_sub, "status": "skipped", "message": "No stored shop-claim cookies"}

    headers = build_replay_headers(
        request_headers=item.get("shop_claim_request_headers") or {},
        navigator_info=item.get("shop_claim_navigator_info") or {},
        cookies=cookies,
    )

    if dry_run:
        return {
            "cognito_sub": cognito_sub,
            "status": "dry_run",
            "message": f"Would POST to {GEOGUESSR_CLAIM_URL} with {len(cookies)} cookie(s)",
        }

    try:
        status_code, body = post_daily_shop_claim(headers)
    except URLError as e:
        return {"cognito_sub": cognito_sub, "status": "failed", "message": f"Request error: {e}"}

    status = "claimed" if 200 <= status_code < 300 else "failed"
    return {"cognito_sub": cognito_sub, "status": status, "message": f"HTTP {status_code}: {body[:200]}"}


# ---------------------------------------------------------------------------
# Request construction / replay
# ---------------------------------------------------------------------------

def build_replay_headers(
    request_headers: Dict[str, str],
    navigator_info: Dict[str, Any],
    cookies: Dict[str, str],
) -> Dict[str, str]:
    """
    Reconstructs the headers GeoGuessr's own frontend would send.

    `request_headers` holds what the page's own JS set explicitly on the
    fetch call (x-client, sentry-trace, baggage, content-type — captured
    verbatim by the extension, since those aren't visible via `navigator`).
    `navigator_info` holds the browser fingerprint (user-agent, client
    hints) Chrome injects itself, captured separately at the same time.
    """
    headers = {
        "accept": "*/*",
        "content-type": request_headers.get("Content-Type") or request_headers.get("content-type") or "application/json",
        "origin": "https://www.geoguessr.com",
        "referer": "https://www.geoguessr.com/shop/avatar",
        "cookie": "; ".join(f"{name}={value}" for name, value in cookies.items()),
    }

    user_agent = navigator_info.get("userAgent")
    if user_agent:
        headers["user-agent"] = user_agent

    language = navigator_info.get("language")
    if language:
        headers["accept-language"] = language

    for source_key, header_name in (
        ("X-Client", "x-client"),
        ("X-Locale", "x-locale"),
        ("sentry-trace", "sentry-trace"),
        ("baggage", "baggage"),
    ):
        value = request_headers.get(source_key) or request_headers.get(header_name)
        if value:
            headers[header_name] = value

    return headers


def post_daily_shop_claim(headers: Dict[str, str]) -> Tuple[int, str]:
    req = urllib_request.Request(
        GEOGUESSR_CLAIM_URL,
        data=b"{}",
        headers=headers,
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
