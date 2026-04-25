import json
import os
from decimal import Decimal
from typing import Any, Dict, List

import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")

STATS_TABLE_NAME = os.environ["STATS_TABLE_NAME"]
stats_table = dynamodb.Table(STATS_TABLE_NAME)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        cognito_sub = get_cognito_sub(event)
        if not cognito_sub:
            return response(401, {"error": "Unauthorized: missing Cognito subject claim"})

        pk = f"USER#{cognito_sub}"

        items = query_all_country_items(pk)

        countries = []
        for item in items:
            rounds_played = int(item.get("rounds_played", 0) or 0)
            total_distance = float(item.get("total_distance", 0) or 0)
            total_damage_taken = float(item.get("total_damage_taken", 0) or 0)

            avg_distance = total_distance / rounds_played if rounds_played > 0 else 0
            avg_damage = total_damage_taken / rounds_played if rounds_played > 0 else 0

            countries.append({
                "country": item.get("real_country", "unknown"),
                "totalRounds": rounds_played,
                "avgDistance": round(avg_distance, 2),
                "avgDamage": round(avg_damage, 2),
            })

        # Sort countries by average damage (lowest first = best countries first)
        countries.sort(key=lambda x: x["avgDamage"])

        return response(200, {
            "ok": True,
            "countries": countries
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
    items: List[Dict[str, Any]] = []

    query_kwargs = {
        "KeyConditionExpression": Key("PK").eq(pk) & Key("SK").begins_with("COUNTRY#")
    }

    while True:
        result = stats_table.query(**query_kwargs)
        items.extend(result.get("Items", []))

        last_evaluated_key = result.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break

        query_kwargs["ExclusiveStartKey"] = last_evaluated_key

    return items


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