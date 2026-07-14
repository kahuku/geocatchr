"""
Shared duel-processing core for the GeoCatchr Lambdas.

This module holds the deterministic parts of duel ingestion: resolving which
player belongs to the authenticated user, computing per-round stats, and
writing them to DynamoDB. Both the live ingest handler and the rehydrate
handler import it, so the numbers they produce are guaranteed identical.

It deliberately knows nothing about HTTP, JWT auth, or S3 archiving — those
live in the ingest handler. The DynamoDB table handles are built from the same
env vars both functions set, so writes land in the same tables regardless of
which handler imported this module.
"""

import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import boto3

dynamodb = boto3.resource("dynamodb")

STATS_TABLE_NAME = os.environ["STATS_TABLE_NAME"]
PLAYER_MAP_TABLE_NAME = os.environ["PLAYER_MAP_TABLE_NAME"]

stats_table = dynamodb.Table(STATS_TABLE_NAME)
player_map_table = dynamodb.Table(PLAYER_MAP_TABLE_NAME)


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


def did_user_team_win(state: Dict[str, Any], user_team: Dict[str, Any]) -> bool:
    result = state.get("result") or {}
    winning_team_id = result.get("winningTeamId")
    return bool(winning_team_id and winning_team_id == user_team.get("id"))


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


def record_game(
    cognito_sub: str,
    geoguessr_player_id: str,
    duel_id: str,
    game_won: bool,
    round_rows: List[Dict[str, Any]],
) -> None:
    """
    Stores one row per duel for the user.

    Table keys:
    - PK (string): USER#<cognito_sub>
    - SK (string): GAME#<duel_id>

    The SK uses duel_id (not a timestamp) so re-ingesting the same duel
    overwrites the row instead of producing a duplicate. played_at is fixed on
    first write via if_not_exists so the original ingestion order — which the
    summary endpoint relies on for streak calculation — survives any later
    re-ingest of the same duel.
    """
    played_at = datetime.now(timezone.utc).isoformat()
    rounds_played = len(round_rows)
    rounds_won = sum(1 for r in round_rows if r.get("round_won"))

    stats_table.update_item(
        Key={
            "PK": f"USER#{cognito_sub}",
            "SK": f"GAME#{duel_id}",
        },
        UpdateExpression=(
            "SET user_id = :user_id, "
            "geoguessr_player_id = :geoguessr_player_id, "
            "duel_id = :duel_id, "
            "game_won = :game_won, "
            "rounds_played = :rounds_played, "
            "rounds_won = :rounds_won, "
            "played_at = if_not_exists(played_at, :played_at)"
        ),
        ExpressionAttributeValues={
            ":user_id": cognito_sub,
            ":geoguessr_player_id": geoguessr_player_id,
            ":duel_id": duel_id,
            ":game_won": Decimal("1") if game_won else Decimal("0"),
            ":rounds_played": Decimal(str(rounds_played)),
            ":rounds_won": Decimal(str(rounds_won)),
            ":played_at": played_at,
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
    rounds: List[Dict[str, Any]],
    game_won: bool,
) -> List[Dict[str, Any]]:
    """
    Produces one normalized row per round for the authenticated user.

    Points: sourced from the user's own guesses, never from user_team's
    roundResults. In a team duel, roundResults.score is the *team's* best
    guess for that round, which may belong to a teammate rather than the
    authenticated user — using it here would silently record a teammate's
    score as the user's own.

    Opponent comparison: opp_points is intentionally read from
    opponent_team's roundResults, since that already is the opposing team's
    best guess for the round (no need to inspect individual opponents).

    Multiplier note: each team's roundResults entry carries its own multiplier
    reflecting what was active when that team dealt damage. We normalize each
    side's raw damageDealt by *their own* multiplier so the values are
    is inherently a team-level mechanic (shared health pool), so it isn't
    attributable to a single player the way points are.

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
        user_result = user_round_results.get(round_num) or {}
        opp_result = opp_round_results.get(round_num) or {}

        real_country = pano.get("countryCode") or "unknown"

        # Always the authenticated user's own guess — never the team's
        # (possibly teammate-sourced) best guess for the round.
        points = int(user_guess.get("score", 0))
        # The opposing team's best guess for the round.
        opp_points = int(opp_result.get("score", 0))

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
