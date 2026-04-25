#!/usr/bin/env python3
"""
Replay archived raw GeoCatchr ingest requests from a local folder back into the ingest API.

Usage:
  python replay_ingest_folder.py \
    --folder /path/to/raw \
    --endpoint https://f53qk2aal4.execute-api.us-east-1.amazonaws.com/ingest-duel \
    --access-token YOUR_ACCESS_TOKEN

Optional:
  --expected-sub e488c4c8-7041-70e9-9938-6dbc6b332ef2
  --dry-run
  --limit 10
  --sort path
  --pause-ms 100

Notes:
- This assumes each local JSON file is one archived request body exactly like what was stored in S3.
- All replays will be attributed to the Cognito user represented by the access token.
- If your files are from more than one user, replay separately with the correct token for each user.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

try:
    import requests
except ImportError:
    print("This script requires 'requests'. Install it with: pip install requests", file=sys.stderr)
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True, help="Local folder containing archived JSON request files")
    parser.add_argument("--endpoint", required=True, help="Ingest endpoint URL")
    parser.add_argument("--access-token", required=True, help="Cognito access token for Authorization: Bearer ...")
    parser.add_argument("--expected-sub", default=None, help="Optional Cognito sub to verify against file path player=<sub>")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print what would be sent without POSTing")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of files to replay")
    parser.add_argument(
        "--sort",
        choices=["path", "mtime"],
        default="path",
        help="Replay order. 'path' is deterministic; 'mtime' follows file modified time.",
    )
    parser.add_argument("--pause-ms", type=int, default=50, help="Pause between requests in milliseconds")
    parser.add_argument("--timeout-sec", type=int, default=20, help="HTTP timeout per request in seconds")
    return parser.parse_args()


def find_json_files(folder: Path, sort_mode: str) -> List[Path]:
    files = [p for p in folder.rglob("*.json") if p.is_file()]
    if sort_mode == "mtime":
        files.sort(key=lambda p: p.stat().st_mtime)
    else:
        files.sort(key=lambda p: str(p))
    return files


def extract_sub_from_path(path: Path) -> str | None:
    # Matches path parts like: player=<cognito_sub>
    for part in path.parts:
        if part.startswith("player="):
            return part.split("=", 1)[1] or None
    return None


def load_json_file(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON is not an object")
    return data


def validate_archived_body(data: Dict[str, Any]) -> Tuple[bool, str]:
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return False, "missing or invalid 'payload'"

    duel = payload.get("duel")
    if not isinstance(duel, dict):
        return False, "missing or invalid 'payload.duel'"

    state = duel.get("state")
    if not isinstance(state, dict):
        return False, "missing or invalid 'payload.duel.state'"

    game_id = payload.get("gameId") or state.get("gameId")
    if not game_id:
        return False, "missing gameId"

    teams = state.get("teams")
    rounds = state.get("rounds")
    if not isinstance(teams, list) or not isinstance(rounds, list):
        return False, "missing or invalid teams/rounds"

    return True, "ok"


def summarize_body(data: Dict[str, Any]) -> Dict[str, Any]:
    payload = data.get("payload") or {}
    duel = payload.get("duel") or {}
    state = duel.get("state") or {}
    return {
        "gameId": payload.get("gameId") or state.get("gameId"),
        "type": data.get("type"),
        "receivedAt": data.get("receivedAt"),
        "teams": len(state.get("teams") or []),
        "rounds": len(state.get("rounds") or []),
    }


def replay_file(
    path: Path,
    endpoint: str,
    access_token: str,
    timeout_sec: int,
    dry_run: bool,
) -> Tuple[bool, str, int | None]:
    data = load_json_file(path)
    ok, reason = validate_archived_body(data)
    if not ok:
        return False, f"invalid archived body: {reason}", None

    if dry_run:
        summary = summarize_body(data)
        return True, f"dry-run: would replay {summary}", None

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    resp = requests.post(
        endpoint,
        headers=headers,
        json=data,
        timeout=timeout_sec,
    )

    text = resp.text.strip()
    if resp.ok:
        return True, text[:500], resp.status_code
    return False, text[:500], resp.status_code


def main() -> int:
    args = parse_args()
    folder = Path(args.folder)

    if not folder.exists() or not folder.is_dir():
        print(f"Folder does not exist or is not a directory: {folder}", file=sys.stderr)
        return 1

    files = find_json_files(folder, args.sort)
    if args.limit is not None:
        files = files[: args.limit]

    if not files:
        print("No JSON files found.")
        return 0

    print(f"Found {len(files)} JSON files under {folder}")

    success_count = 0
    fail_count = 0
    skipped_count = 0

    for i, path in enumerate(files, start=1):
        path_sub = extract_sub_from_path(path)
        if args.expected_sub and path_sub and path_sub != args.expected_sub:
            print(f"[{i}/{len(files)}] SKIP {path}  path_sub={path_sub} != expected_sub={args.expected_sub}")
            skipped_count += 1
            continue

        try:
            ok, detail, status = replay_file(
                path=path,
                endpoint=args.endpoint,
                access_token=args.access_token,
                timeout_sec=args.timeout_sec,
                dry_run=args.dry_run,
            )

            if ok:
                success_count += 1
                status_str = f" status={status}" if status is not None else ""
                print(f"[{i}/{len(files)}] OK   {path}{status_str}  {detail}")
            else:
                fail_count += 1
                status_str = f" status={status}" if status is not None else ""
                print(f"[{i}/{len(files)}] FAIL {path}{status_str}  {detail}")

        except Exception as e:
            fail_count += 1
            print(f"[{i}/{len(files)}] EXC  {path}  {type(e).__name__}: {e}")

        if not args.dry_run and args.pause_ms > 0:
            time.sleep(args.pause_ms / 1000.0)

    print()
    print("Replay complete")
    print(f"  Success: {success_count}")
    print(f"  Failed:  {fail_count}")
    print(f"  Skipped: {skipped_count}")

    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())