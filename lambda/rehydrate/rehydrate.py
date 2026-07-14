"""
Rehydrate / repopulate Lambda.

Replays already-archived duel JSON back into the DynamoDB stats tables AFTER
you've wiped them — without ever going through API Gateway, the JWT authorizer,
or re-archiving anything to S3.

Why this exists
---------------
The live ingest path (lambda/ingest/ingest.py) derives *who a duel belongs to*
from the verified Cognito JWT (`requestContext...claims.sub`). Replaying over
HTTP would therefore attribute every duel to whoever's token you happened to
use — the exact thing we must never do here.

Instead, this function trusts the two identifiers that are already baked into
each archived record and can't be faked at replay time:

  - cognito_sub          -> read from the S3 key segment `player=<sub>`
                            (written from the verified JWT at original ingest)
  - geoguessr_player_id  -> read from the archived request body

Both are the originals. A file missing either one HARD-FAILS that file rather
than falling back to any default, so a duel can never land on the wrong player.

It then calls the *same* pure functions the live ingest uses
(build_round_rows / update_country_stats / record_game), so the recomputed
numbers are identical to what live ingest would have produced. It deliberately
does NOT call archive_raw_request, so no duplicate S3 copies are ever created.

Idempotency note
----------------
update_country_stats uses DynamoDB `ADD` (additive), so this is only correct
run ONCE against freshly-wiped COUNTRY# rows. This function does not reset
anything — per design it assumes you've already deleted the stats rows.
Run with dry_run first to see what would happen.

Invoke (from the AWS console "Test" tab)
----------------------------------------
Scan the raw bucket directly (normal case — no export needed):

    { "mode": "bucket", "prefix": "raw/", "dry_run": true }
    { "mode": "bucket", "prefix": "raw/", "dry_run": false }

Replay from an exported zip you uploaded somewhere in S3:

    { "mode": "zip", "zip_bucket": "my-scratch-bucket",
      "zip_key": "exports/2026-07-13.zip", "dry_run": true }

Optional keys (both modes): "limit" (int), "player" (only this cognito_sub).

Required env vars (same names/values as the ingest Lambda):
    STATS_TABLE_NAME, PLAYER_MAP_TABLE_NAME, RAW_BUCKET_NAME
The raw bucket defaults to RAW_BUCKET_NAME when "bucket"/"zip_bucket" is omitted.
"""

import io
import json
import os
import zipfile
from typing import Any, Dict, List, Optional

import boto3

# Reuse the exact stats math the live ingest uses. duel_core is bundled into
# this function's deploy zip at build time (see build.sh) and owns the DynamoDB
# table handles, so update_country_stats/record_game write to the same tables
# this function is pointed at.
import duel_core

s3 = boto3.client("s3")

RAW_BUCKET_NAME = os.environ["RAW_BUCKET_NAME"]

# Cap the per-file detail we echo back so a full-bucket run doesn't return a
# multi-megabyte payload. Aggregate counts always reflect every file.
MAX_REPORTED_RESULTS = 200


# ---------------------------------------------------------------------------
# Identity extraction (the safety-critical part)
# ---------------------------------------------------------------------------

def extract_cognito_sub(key_or_path: str) -> Optional[str]:
    """Pulls <sub> out of a `.../player=<sub>/...` S3 key or zip entry name."""
    for part in key_or_path.split("/"):
        if part.startswith("player="):
            return part.split("=", 1)[1] or None
    return None


def extract_duel_id(body: Dict[str, Any]) -> Optional[str]:
    payload = body.get("payload") or {}
    state = (payload.get("duel") or {}).get("state") or {}
    return payload.get("gameId") or state.get("gameId")


# ---------------------------------------------------------------------------
# Core replay of one archived record
# ---------------------------------------------------------------------------

def replay_one(source_path: str, body: Dict[str, Any], dry_run: bool) -> Dict[str, Any]:
    """
    Recomputes and writes stats for a single archived duel.

    source_path is the S3 key (bucket mode) or the zip entry name (zip mode);
    it is the ONLY source of cognito_sub, so it must carry `player=<sub>`.

    Never archives to S3 and never mutates the raw record.
    """
    result: Dict[str, Any] = {"source": source_path, "status": None, "message": ""}

    cognito_sub = extract_cognito_sub(source_path)
    if not cognito_sub:
        result["status"] = "failed"
        result["message"] = "No `player=<sub>` segment in path — refusing to guess an owner"
        return result

    geoguessr_player_id = body.get("geoguessr_player_id")
    if not geoguessr_player_id:
        result["status"] = "failed"
        result["message"] = "Archived body has no geoguessr_player_id — refusing to guess a player"
        return result

    payload = body.get("payload") or {}
    state = (payload.get("duel") or {}).get("state") or {}
    duel_id = extract_duel_id(body)
    teams = state.get("teams") or []
    rounds = state.get("rounds") or []

    result["cognito_sub"] = cognito_sub
    result["geoguessr_player_id"] = geoguessr_player_id
    result["duel_id"] = duel_id

    if not duel_id:
        result["status"] = "failed"
        result["message"] = "Missing duel/game ID"
        return result
    if not teams or not rounds:
        result["status"] = "failed"
        result["message"] = "Missing teams or rounds"
        return result

    # Re-validate that this gg player really is in this duel's teams — same
    # check the live ingest performs. Guarantees the duel maps to a real player.
    user_player, user_team, opponent_team = duel_core.find_user_player_and_teams(
        teams, geoguessr_player_id
    )
    if not user_player or not user_team:
        result["status"] = "failed"
        result["message"] = f"Player '{geoguessr_player_id}' not found in any team"
        return result

    game_won = duel_core.did_user_team_win(state, user_team)
    round_rows = duel_core.build_round_rows(
        cognito_sub=cognito_sub,
        duel_id=duel_id,
        user_team=user_team,
        opponent_team=opponent_team,
        user_player=user_player,
        rounds=rounds,
        game_won=game_won,
    )
    if not round_rows:
        result["status"] = "failed"
        result["message"] = "No round data could be extracted"
        return result

    if dry_run:
        result["status"] = "dry_run"
        result["message"] = (
            f"Would write {len(round_rows)} round(s) for sub={cognito_sub} "
            f"gg={geoguessr_player_id} duel={duel_id} won={game_won}"
        )
        return result

    for row in round_rows:
        duel_core.update_country_stats(row)

    duel_core.record_game(
        cognito_sub=cognito_sub,
        geoguessr_player_id=geoguessr_player_id,
        duel_id=duel_id,
        game_won=game_won,
        round_rows=round_rows,
    )

    result["status"] = "ok"
    result["rounds"] = len(round_rows)
    result["message"] = f"Ingested {len(round_rows)} round(s), won={game_won}"
    return result


# ---------------------------------------------------------------------------
# Sources: raw S3 bucket, or an uploaded zip
# ---------------------------------------------------------------------------

def iter_bucket_records(bucket: str, prefix: str):
    """Yields (key, body_dict) for every .json object under prefix."""
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents") or []:
            key = obj["Key"]
            if not key.endswith(".json"):
                continue
            raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            yield key, json.loads(raw)


def iter_zip_records(bucket: str, key: str):
    """Yields (entry_name, body_dict) for every .json entry in the zip."""
    raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for name in zf.namelist():
            if name.endswith("/") or not name.endswith(".json"):
                continue
            with zf.open(name) as f:
                yield name, json.loads(f.read())


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    event = event or {}
    mode = event.get("mode", "bucket")
    dry_run = bool(event.get("dry_run", True))  # safe default: dry run
    limit = event.get("limit")
    only_player = event.get("player")  # optional: restrict to one cognito_sub

    if mode == "bucket":
        bucket = event.get("bucket") or RAW_BUCKET_NAME
        prefix = event.get("prefix", "raw/")
        source = iter_bucket_records(bucket, prefix)
        source_desc = f"s3://{bucket}/{prefix}"
    elif mode == "zip":
        bucket = event.get("zip_bucket") or RAW_BUCKET_NAME
        key = event.get("zip_key")
        if not key:
            return {"error": "mode 'zip' requires 'zip_key'"}
        source = iter_zip_records(bucket, key)
        source_desc = f"s3://{bucket}/{key}"
    else:
        return {"error": f"Unknown mode '{mode}' (use 'bucket' or 'zip')"}

    counts = {"ok": 0, "failed": 0, "skipped": 0, "dry_run": 0}
    reported: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    processed = 0

    for source_path, body in source:
        if limit is not None and processed >= limit:
            break

        if only_player and extract_cognito_sub(source_path) != only_player:
            counts["skipped"] += 1
            continue

        try:
            result = replay_one(source_path, body, dry_run)
        except Exception as e:  # noqa: BLE001 — never let one bad file abort the run
            result = {"source": source_path, "status": "failed", "message": f"{type(e).__name__}: {e}"}

        processed += 1
        status = result["status"]
        counts[status] = counts.get(status, 0) + 1

        if status == "failed":
            failures.append(result)
        if len(reported) < MAX_REPORTED_RESULTS:
            reported.append(result)
        print(f"[{status}] {source_path} :: {result['message']}")

    summary = {
        "source": source_desc,
        "dry_run": dry_run,
        "processed": processed,
        "counts": counts,
        "failures": failures[:MAX_REPORTED_RESULTS],
        "results_truncated": processed > len(reported),
    }
    print("SUMMARY:", json.dumps(summary["counts"]))
    return summary
