import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

# Shared duel-processing core (bundled into this function's deploy zip at build
# time — see build.sh). Both ingest and rehydrate import it so their stats math
# is identical. It also owns the DynamoDB table handles.
from duel_core import (
    STATS_TABLE_NAME,
    PLAYER_MAP_TABLE_NAME,
    build_round_rows,
    did_user_team_win,
    find_user_player_and_teams,
    record_game,
    update_country_stats,
    upsert_player_mapping,
)

s3 = boto3.client("s3")

RAW_BUCKET_NAME = os.environ["RAW_BUCKET_NAME"]


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    POST /ingest-duel

    Assumptions:
    - API Gateway HTTP API uses a JWT authorizer backed by Cognito.
    - Cognito user identity is read from requestContext.authorizer.jwt.claims.sub.
    - The caller (Chrome extension) passes geoguessr_player_id in the request body.
      This ID is captured from the outbound SubscribeToLobby WebSocket message
      when a new duel lobby is joined, making it the authoritative source of truth
      for which player belongs to the authenticated user — regardless of team colour
      or position.
    - We archive the raw request body to S3.
    - We update one DynamoDB stats row per (user, real_country).
    - We also record one row per duel for game-level W/L and streak tracking.
    """

    try:
        cognito_sub, cognito_username = get_authenticated_user(event)
        if not cognito_sub:
            return response(401, {"error": "Unauthorized: missing Cognito subject claim"})

        body = parse_json_body(event)
        payload = body.get("payload") or {}
        duel = payload.get("duel") or {}
        state = duel.get("state") or {}

        duel_id = payload.get("gameId") or state.get("gameId")
        if not duel_id:
            return response(400, {"error": "Missing duel/game ID in payload"})

        teams = state.get("teams") or []
        rounds = state.get("rounds") or []
        if not teams or not rounds:
            return response(400, {"error": "Missing teams or rounds in payload"})

        # The extension captures this from the outbound SubscribeToLobby WS message
        # and passes it along so we don't have to guess based on team colour.
        geoguessr_player_id = body.get("geoguessr_player_id")
        if not geoguessr_player_id:
            return response(400, {"error": "Missing geoguessr_player_id in request body"})

        user_player, user_team, opponent_team = find_user_player_and_teams(
            teams, geoguessr_player_id
        )
        if not user_player or not user_team:
            return response(
                400,
                {
                    "error": (
                        f"Player '{geoguessr_player_id}' not found in any team. "
                        "The cached player ID may be stale — rejoining a lobby should refresh it."
                    )
                },
            )

        # 1) Archive raw request JSON in S3
        raw_s3_key = archive_raw_request(
            bucket_name=RAW_BUCKET_NAME,
            cognito_sub=cognito_sub,
            duel_id=duel_id,
            request_body=body,
        )

        print("STATS_TABLE_NAME:", STATS_TABLE_NAME)
        print("PLAYER_MAP_TABLE_NAME:", PLAYER_MAP_TABLE_NAME)
        print("RAW_BUCKET_NAME:", RAW_BUCKET_NAME)
        print("cognito_sub:", cognito_sub)
        print("duel_id:", duel_id)
        print("teams found:", len(teams))
        print("rounds found:", len(rounds))
        print("user team name:", user_team.get("name"))
        print("opponent team name:", opponent_team.get("name") if opponent_team else None)
        print("user player id:", geoguessr_player_id)

        upsert_player_mapping(
            cognito_sub=cognito_sub,
            cognito_username=cognito_username,
            geoguessr_player_id=geoguessr_player_id,
        )
        print("player mapping upserted")

        # Compute once and reuse for both the per-round rows and the per-game record.
        game_won = did_user_team_win(state, user_team)

        round_rows = build_round_rows(
            cognito_sub=cognito_sub,
            duel_id=duel_id,
            user_team=user_team,
            opponent_team=opponent_team,
            user_player=user_player,
            rounds=rounds,
            game_won=game_won,
        )

        print(f"round_rows count: {len(round_rows)}")

        if not round_rows:
            return response(400, {"error": "No round data could be extracted from payload"})

        for row in round_rows:
            update_country_stats(row)

        print("all country stats updated")

        # 2) Record one row per duel — used by summary endpoint for game-level
        # W/L totals and current streak. Idempotent on duel_id.
        record_game(
            cognito_sub=cognito_sub,
            geoguessr_player_id=geoguessr_player_id,
            duel_id=duel_id,
            game_won=game_won,
            round_rows=round_rows,
        )
        print("game record stored")

        return response(
            200,
            {
                "ok": True,
                "message": "Duel ingested successfully",
                "user_id": cognito_sub,
                "geoguessr_player_id": geoguessr_player_id,
                "duel_id": duel_id,
                "rounds_ingested": len(round_rows),
                "game_won": game_won,
                "raw_s3_key": raw_s3_key,
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

def get_authenticated_user(event: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Reads validated JWT claims from API Gateway HTTP API event."""
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    cognito_sub = claims.get("sub")
    cognito_username = claims.get("username")
    return cognito_sub, cognito_username


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
# S3 archiving
# ---------------------------------------------------------------------------

def archive_raw_request(
    bucket_name: str,
    cognito_sub: str,
    duel_id: str,
    request_body: Dict[str, Any],
) -> str:
    """
    Stores one raw JSON object per duel.

    The date partition is derived from the request's own `receivedAt`
    timestamp rather than ingestion time, so replaying an already-archived
    duel (e.g. via the rehydrate scripts) resolves to the same S3 key and
    overwrites in place instead of creating a second copy under today's date.

    Example key:
    raw/year=2026/month=03/day=12/player=<cognito_sub>/duel=<duel_id>.json
    """
    event_time = parse_received_at(request_body.get("receivedAt")) or datetime.now(timezone.utc)
    key = (
        f"raw/year={event_time:%Y}/month={event_time:%m}/day={event_time:%d}/"
        f"player={cognito_sub}/duel={duel_id}.json"
    )

    s3.put_object(
        Bucket=bucket_name,
        Key=key,
        Body=json.dumps(request_body).encode("utf-8"),
        ContentType="application/json",
    )
    return key


def parse_received_at(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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
