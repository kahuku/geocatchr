import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")

STATS_TABLE_NAME = os.environ["STATS_TABLE_NAME"]
PLAYER_MAP_TABLE_NAME = os.environ["PLAYER_MAP_TABLE_NAME"]
RAW_BUCKET_NAME = os.environ["RAW_BUCKET_NAME"]

stats_table = dynamodb.Table(STATS_TABLE_NAME)
player_map_table = dynamodb.Table(PLAYER_MAP_TABLE_NAME)


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

        opponent_player = get_first_player(opponent_team) if opponent_team else None

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

        round_rows = build_round_rows(
            cognito_sub=cognito_sub,
            duel_id=duel_id,
            user_team=user_team,
            opponent_team=opponent_team,
            user_player=user_player,
            opponent_player=opponent_player,
            rounds=rounds,
            game_won=did_user_team_win(state, user_team),
        )

        print(f"round_rows count: {len(round_rows)}")

        if not round_rows:
            return response(400, {"error": "No round data could be extracted from payload"})

        for row in round_rows:
            update_country_stats(row)

        print("all country stats updated")

        return response(
            200,
            {
                "ok": True,
                "message": "Duel ingested successfully",
                "user_id": cognito_sub,
                "geoguessr_player_id": geoguessr_player_id,
                "duel_id": duel_id,
                "rounds_ingested": len(round_rows),
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
# Player / team resolution
# ---------------------------------------------------------------------------

def find_user_player_and_teams(
    teams: List[Dict[str, Any]],
    geoguessr_player_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Searches all teams for the player whose playerId matches geoguessr_player_id.

    Returns (user_player, user_team, opponent_team).
    opponent_team is the first team that is not the user's team (None if only one team).
    """
    for team in teams:
        for player in team.get("players") or []:
            if player.get("playerId") == geoguessr_player_id:
                opponent_team = next((t for t in teams if t is not team), None)
                return player, team, opponent_team

    return None, None, None


def get_first_player(team: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    players = team.get("players") or []
    return players[0] if players else None


def did_user_team_win(state: Dict[str, Any], user_team: Dict[str, Any]) -> bool:
    result = state.get("result") or {}
    winning_team_id = result.get("winningTeamId")
    return bool(winning_team_id and winning_team_id == user_team.get("id"))


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
    Stores one raw JSON object per ingest request.

    Example key:
    raw/year=2026/month=03/day=12/player=<cognito_sub>/duel=<duel_id>.json
    """
    now = datetime.now(timezone.utc)
    key = (
        f"raw/year={now:%Y}/month={now:%m}/day={now:%d}/"
        f"player={cognito_sub}/duel={duel_id}.json"
    )

    s3.put_object(
        Bucket=bucket_name,
        Key=key,
        Body=json.dumps(request_body).encode("utf-8"),
        ContentType="application/json",
    )
    return key


# ---------------------------------------------------------------------------
# DynamoDB writes
# ---------------------------------------------------------------------------

def upsert_player_mapping(
    cognito_sub: str,
    cognito_username: Optional[str],
    geoguessr_player_id: str,
) -> None:
    """
    Stores a simple user mapping row in a separate table.

    Table keys:
    - PK (string): COGNITO#<sub>
    - SK (string): PROFILE
    """
    player_map_table.put_item(
        Item={
            "PK": f"COGNITO#{cognito_sub}",
            "SK": "PROFILE",
            "cognito_sub": cognito_sub,
            "cognito_username": cognito_username or "",
            "geoguessr_player_id": geoguessr_player_id,
        }
    )


def update_country_stats(row: Dict[str, Any]) -> None:
    """
    Updates one country summary row.

    Table keys:
    - PK (string): USER#<cognito_sub>
    - SK (string): COUNTRY#<country_code>
    """
    stats_table.update_item(
        Key={
            "PK": f"USER#{row['user_id']}",
            "SK": f"COUNTRY#{row['real_country']}",
        },
        UpdateExpression=(
            "SET user_id = :user_id, "
            "geoguessr_player_id = :geoguessr_player_id, "
            "real_country = :real_country "
            "ADD rounds_played :one, "
            "total_points :points, "
            "total_damage_taken :damage, "
            "total_distance :distance, "
            "rounds_won :round_won"
        ),
        ExpressionAttributeValues={
            ":user_id": row["user_id"],
            ":geoguessr_player_id": row["geoguessr_player_id"],
            ":real_country": row["real_country"],
            ":one": Decimal("1"),
            ":points": Decimal(str(row["points"])),
            ":damage": Decimal(str(row["damage"])),
            ":distance": Decimal(str(row["distance"])),
            ":round_won": Decimal(str(row["round_won"])),
        },
    )


# ---------------------------------------------------------------------------
# Round-level data extraction
# ---------------------------------------------------------------------------

def build_round_rows(
    cognito_sub: str,
    duel_id: str,
    user_team: Dict[str, Any],
    opponent_team: Optional[Dict[str, Any]],
    user_player: Dict[str, Any],
    opponent_player: Optional[Dict[str, Any]],
    rounds: List[Dict[str, Any]],
    game_won: bool,
) -> List[Dict[str, Any]]:
    """
    Produces one normalized row per round for the authenticated user.

    Multiplier note: each team's roundResults entry carries its own multiplier
    reflecting what was active when that team dealt damage. We normalize each
    side's raw damageDealt by *their own* multiplier so the values are
    comparable across rounds with different multiplier tiers.

    Row shape:
    {
        user_id, duel_id, round_num, real_country,
        points, damage, user_multiplier, distance, round_won, game_won,
        geoguessr_player_id
    }
    """

    user_guesses = {
        guess["roundNumber"]: guess
        for guess in (user_player.get("guesses") or [])
        if "roundNumber" in guess
    }
    opponent_guesses = {
        guess["roundNumber"]: guess
        for guess in ((opponent_player or {}).get("guesses") or [])
        if "roundNumber" in guess
    }

    user_round_results = {
        rr["roundNumber"]: rr
        for rr in (user_team.get("roundResults") or [])
        if "roundNumber" in rr
    }
    opp_round_results = {
        rr["roundNumber"]: rr
        for rr in ((opponent_team or {}).get("roundResults") or [])
        if "roundNumber" in rr
    }

    rows: List[Dict[str, Any]] = []

    for round_obj in rounds:
        round_num = round_obj.get("roundNumber")
        if round_num is None:
            continue

        pano = round_obj.get("panorama") or {}
        user_guess = user_guesses.get(round_num) or {}
        opp_guess = opponent_guesses.get(round_num) or {}
        user_result = user_round_results.get(round_num) or {}
        opp_result = opp_round_results.get(round_num) or {}

        real_country = pano.get("countryCode") or "unknown"

        points = int(
            user_result.get("score")
            if user_result.get("score") is not None
            else user_guess.get("score", 0)
        )
        opp_points = int(
            opp_result.get("score")
            if opp_result.get("score") is not None
            else opp_guess.get("score", 0)
        )

        # Raw damage values — each sourced from the dealing team's roundResults.
        outgoing_damage_raw = float(user_result.get("damageDealt", 0))
        incoming_damage_raw = float(opp_result.get("damageDealt", 0))

        # Each team's multiplier comes from their own roundResults entry for this
        # round. Using the dealing team's multiplier as the divisor gives the true
        # base-score equivalent of each damage number, making rounds with different
        # multiplier tiers directly comparable.
        user_multiplier = float(user_result.get("multiplier") or 1.0)
        opp_multiplier = float(opp_result.get("multiplier") or 1.0)

        normalized_outgoing = (
            outgoing_damage_raw / user_multiplier if user_multiplier > 0 else outgoing_damage_raw
        )
        normalized_incoming = (
            incoming_damage_raw / opp_multiplier if opp_multiplier > 0 else incoming_damage_raw
        )

        # Positive = net damage taken (bad), negative = net damage dealt (good).
        net_damage = normalized_incoming - normalized_outgoing

        distance = float(user_guess.get("distance", 0.0))
        round_won = 1 if points > opp_points else 0

        print(
            f"  Round {round_num:>2} | country={real_country} | "
            f"pts={points} opp_pts={opp_points} | "
            f"out_dmg={outgoing_damage_raw:.0f} (x{user_multiplier}) "
            f"in_dmg={incoming_damage_raw:.0f} (x{opp_multiplier}) | "
            f"net_dmg={net_damage:.2f} | "
            f"dist={distance:.0f}m | "
            f"won={round_won}"
        )

        row = {
            "user_id": cognito_sub,
            "geoguessr_player_id": user_player.get("playerId"),
            "duel_id": duel_id,
            "round_num": int(round_num),
            "real_country": real_country,
            "points": points,
            "damage": net_damage,
            "user_multiplier": user_multiplier,
            "distance": distance,
            "round_won": round_won,
            "game_won": 1 if game_won else 0,
        }
        rows.append(row)

    return rows


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