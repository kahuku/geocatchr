import json
import os
from decimal import Decimal
from typing import Any, Dict, List
import pycountry

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")

STATS_TABLE_NAME = os.environ["STATS_TABLE_NAME"]
stats_table = dynamodb.Table(STATS_TABLE_NAME)

def get_country_name(code: str) -> str:
    try:
        return pycountry.countries.get(alpha_2=code.upper()).name
    except:
        return code.upper()

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        cognito_sub = get_cognito_sub(event)
        if not cognito_sub:
            return response(401, {"error": "Unauthorized: missing Cognito subject claim"})

        pk = f"USER#{cognito_sub}"

        country_items = query_all_country_items(pk)
        game_items = query_all_game_items(pk)

        countries = []
        for item in country_items:
            rounds_played = int(item.get("rounds_played", 0) or 0)
            total_distance = float(item.get("total_distance", 0) or 0)
            total_damage_taken = float(item.get("total_damage_taken", 0) or 0)

            avg_distance = total_distance / rounds_played if rounds_played > 0 else 0
            avg_damage = total_damage_taken / rounds_played if rounds_played > 0 else 0

            country_code = item.get("real_country", "unknown")

            countries.append({
                "countryCode": country_code,
                "countryName": get_country_name(country_code),
                "totalRounds": rounds_played,
                "avgDistance": round(avg_distance, 2),
                "avgDamage": round(avg_damage, 2),
            })

        # Sort countries by average damage (lowest first = best countries first)
        countries.sort(key=lambda x: x["avgDamage"])

        games = compute_games_summary(game_items)

        return response(200, {
            "ok": True,
            "countries": countries,
            "games": games,
        })

    except Exception as e:
        print("Unhandled exception:", str(e))
        return response(500, {"error": "Internal server error", "detail": str(e)})


def get_cognito_sub(event: Dict[str, Any]) -> str | None:
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    return claims.get("sub")


def query_all_country_items(pk: str) -> List[Dict[str, Any]]:
    return _query_all(pk, "COUNTRY#")


def query_all_game_items(pk: str) -> List[Dict[str, Any]]:
    return _query_all(pk, "GAME#")


def _query_all(pk: str, sk_prefix: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    query_kwargs = {
        "KeyConditionExpression": Key("PK").eq(pk) & Key("SK").begins_with(sk_prefix)
    }

    while True:
        result = stats_table.query(**query_kwargs)
        items.extend(result.get("Items", []))

        last_evaluated_key = result.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break

        query_kwargs["ExclusiveStartKey"] = last_evaluated_key

    return items


def compute_games_summary(game_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Returns total wins/losses plus the current streak.

    Game rows are keyed by SK = GAME#<duel_id>, so the natural query order is
    alphabetical on duel_id rather than chronological. We sort by the
    `played_at` attribute (ISO-8601 string set on first ingest) so the streak
    walk reflects actual play order. Items without played_at sort to the end —
    the empty-string fallback only matters for legacy rows written before this
    field existed and won't bias the streak in any meaningful way.
    """
    if not game_items:
        return {
            "totalWon": 0,
            "totalLost": 0,
            "currentStreak": {"count": 0, "type": "none"},
        }

    sorted_games = sorted(
        game_items,
        key=lambda g: str(g.get("played_at") or ""),
    )

    won = sum(1 for g in sorted_games if int(g.get("game_won", 0) or 0) == 1)
    lost = len(sorted_games) - won

    # Walk backward from the most recent game; count consecutive matches.
    last_outcome = int(sorted_games[-1].get("game_won", 0) or 0)
    streak_count = 0
    for game in reversed(sorted_games):
        if int(game.get("game_won", 0) or 0) == last_outcome:
            streak_count += 1
        else:
            break

    return {
        "totalWon": won,
        "totalLost": lost,
        "currentStreak": {
            "count": streak_count,
            "type": "win" if last_outcome == 1 else "loss",
        },
    }


def response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body, default=decimal_to_json)
    }


def decimal_to_json(value):
    if isinstance(value, Decimal):
        # Convert Dynamo decimals cleanly for JSON serialization
        if value % 1 == 0:
            return int(value)
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
