# rehydrate Lambda

Repopulates the DynamoDB stats tables from already-archived duel JSON **after
you've wiped them** — without going through API Gateway, the JWT authorizer, or
re-archiving anything to S3.

## Why it's safe to attribute duels to the right player

Every archived record already carries both identities, and neither can be faked
at replay time:

| identity | source | set by |
| --- | --- | --- |
| `cognito_sub` | the S3 key segment `player=<sub>` | the verified JWT at original ingest |
| `geoguessr_player_id` | the archived request body | the extension, validated against teams at ingest |

`rehydrate.py` reads both from the record, re-validates that the gg player is
actually in the duel's teams, then calls the **same** shared `duel_core`
functions as live ingest (`build_round_rows` / `update_country_stats` /
`record_game`). A record missing either identity **hard-fails that file** — it
never falls back to a default, so a duel can't land on the wrong user.

It never archives to S3, so **no duplicate S3 copies are created**. It also
does not touch the player-map table (the Cognito username isn't in the
archive), so it can't clobber that mapping.

## Important: run it exactly once against wiped tables

`update_country_stats` uses DynamoDB `ADD` (additive). Running rehydrate twice
**doubles** the COUNTRY# counters. By design this function does not reset
anything — delete the stats rows yourself first, then run once. Always
`dry_run` first.

(`record_game` uses `SET`, so GAME# rows are idempotent either way. The player
map table is not touched by this function.)

## Deploy (manual, matches the other Lambdas)

```bash
./build.sh          # -> rehydrate.zip  (bundles rehydrate.py + a copy of common/duel_core.py)
```

Create a Lambda (Python 3.12+), upload `rehydrate.zip`, set handler to
`rehydrate.lambda_handler`, and give it:

- **Env vars** (same values as the ingest Lambda):
  `STATS_TABLE_NAME`, `PLAYER_MAP_TABLE_NAME`, `RAW_BUCKET_NAME`
- **IAM role** permissions:
  - `dynamodb:UpdateItem` on the stats table
  - `s3:GetObject` + `s3:ListBucket` on the raw bucket (and on the zip's bucket,
    if different)
- **Timeout**: bump to a few minutes for a full-bucket run.

There are **no secrets** — it authenticates to AWS via its execution role only,
which is why the whole thing lives safely in the repo.

## Invoke (AWS console → Test tab)

Scan the raw bucket directly (normal case, no export needed):

```json
{ "mode": "bucket", "prefix": "raw/", "dry_run": true }
```

Then flip `dry_run` to `false` to write.

Replay from an exported zip you uploaded to S3:

```json
{ "mode": "zip", "zip_bucket": "my-scratch-bucket", "zip_key": "exports/2026-07-13.zip", "dry_run": true }
```

Optional keys (either mode): `"limit": 50` to cap files, `"player": "<cognito_sub>"`
to restrict to one user.

The response returns aggregate `counts`, the source, and up to 200 per-file
results (with every `failed` file listed).
