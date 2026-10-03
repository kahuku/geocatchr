import json
from typing import Any, Dict, Optional, Tuple

from botocore.exceptions import ClientError

# Shared duel-processing core (bundled into this function's deploy zip at build
# time — see build.sh). Owns the player-map DynamoDB table handle.
from duel_core import save_shop_claim_snapshot


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    POST /shop-claim-credentials

    Called by the Chrome extension right after it observes the user
    successfully click GeoGuessr's daily shop-claim button. Stores the
    cookies/headers/browser info needed to replay that request later,
    keyed by the authenticated GeoCatchr user (Cognito sub).

    This handler only saves data — it does not itself call GeoGuessr's API.
    """

    try:
        cognito_sub = get_authenticated_user(event)
        if not cognito_sub:
            return response(401, {"error": "Unauthorized: missing Cognito subject claim"})

        body = parse_json_body(event)

        cookies = body.get("cookies")
        if not cookies or not isinstance(cookies, dict):
            return response(400, {"error": "Missing or invalid cookies in request body"})

        request_headers = body.get("requestHeaders") or {}
        navigator_info = body.get("navigatorInfo") or {}
        captured_at = body.get("capturedAt") or ""

        save_shop_claim_snapshot(
            cognito_sub=cognito_sub,
            cookies=cookies,
            request_headers=request_headers,
            navigator_info=navigator_info,
            captured_at=captured_at,
        )

        return response(
            200,
            {
                "ok": True,
                "message": "Shop-claim credentials saved",
                "user_id": cognito_sub,
                "cookie_count": len(cookies),
            },
        )

    except ValueError as e:
        return response(400, {"error": str(e)})
    except ClientError as e:
        print("AWS ClientError:", str(e))
        return response(500, {"error": "AWS operation failed", "detail": str(e)})
    except Exception as e:
        print("Unhandled exception:", str(e))
        return response(500, {"error": "Internal server error", "detail": str(e)})


# ---------------------------------------------------------------------------
# Auth / parsing helpers
# ---------------------------------------------------------------------------

def get_authenticated_user(event: Dict[str, Any]) -> Optional[str]:
    """Reads validated JWT claims from API Gateway HTTP API event."""
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    return claims.get("sub")


def parse_json_body(event: Dict[str, Any]) -> Dict[str, Any]:
    body = event.get("body")
    if not body:
        raise ValueError("Missing request body")

    if event.get("isBase64Encoded"):
        raise ValueError("Base64-encoded bodies are not supported in this handler")

    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON body: {str(e)}")


# ---------------------------------------------------------------------------
# Response helper
# ---------------------------------------------------------------------------

def response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }
