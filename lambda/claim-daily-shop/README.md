# claim-daily-shop Lambda

Replays GeoGuessr's daily-shop-claim POST using the cookies/headers/browser
fingerprint the Chrome extension captured when a user clicked the real
"free coins" button (see `lambda/shop-claim-credentials/`), stored on that
user's player-map profile row (`PK=COGNITO#<sub>`, `SK=PROFILE`, attributes
`shop_claim_cookies` / `shop_claim_request_headers` / `shop_claim_navigator_info`).

This talks directly to `https://www.geoguessr.com/api/v4/webshop/daily-shop-claim`
over HTTPS using the stdlib `urllib` — no external dependencies, no API
Gateway, no JWT auth involved on this side.

**Not yet wired to a schedule.** For now, invoke it manually from the
console Test tab. Wiring an EventBridge `cron(0 1 * * ? *)` rule to run this
daily is future work.

## Deploy (manual, matches the other Lambdas)

No `build.sh` needed — this is a single self-contained file with no
dependency on `lambda/common/duel_core.py` (deliberately: that module
requires `STATS_TABLE_NAME`/`RAW_BUCKET_NAME` env vars at import time for
the duel-stats Lambdas, which this function has no use for).

Zip `claim_daily_shop.py` on its own, or paste it directly into the Lambda
console's inline code editor.

- **Runtime**: Python 3.12+
- **Handler**: `claim_daily_shop.lambda_handler`
- **Env vars**: `PLAYER_MAP_TABLE_NAME`
- **IAM role permissions**: `dynamodb:GetItem` and `dynamodb:Scan` on the
  player-map table. No S3 or stats-table permissions needed.
- **Timeout**: bump to at least 30s (a full run makes one outbound HTTPS
  call per user with stored credentials).
- **Network**: this Lambda calls the public internet (geoguessr.com)
  directly, so it does NOT need to be attached to a VPC — leave it outside
  any VPC unless your account's default Lambda networking requires one.

## Invoke (AWS console → Test tab)

Claim for every user with stored credentials:

```json
{ "dry_run": true }
```

Then flip `dry_run` to `false` to actually POST.

Restrict to one user (e.g. to test with your own account first):

```json
{ "cognito_sub": "<your cognito sub>", "dry_run": false }
```

The response returns aggregate `counts` (`claimed` / `failed` / `skipped`)
and a per-user `results` list with the HTTP status/response body GeoGuessr
returned (truncated to 200 chars).

## Known limitation worth testing for

Some of the captured cookies (e.g. `cf_clearance`, if GeoGuessr is behind
Cloudflare's bot-challenge) are tied to the browser's original IP/TLS
fingerprint when they were issued. A Lambda replaying from AWS's IP range
with a different TLS fingerprint may get rejected even with a byte-for-byte
correct cookie header. Test with `{"cognito_sub": "<your sub>", "dry_run": false}`
first and check the returned status/body before assuming this works for
every user — if it fails, the cookie jar we need to store client-side may
need to be broader (e.g. explicitly requesting a fresh `cf_clearance` isn't
something this Lambda can do on its own, since solving that challenge
requires a real browser).
