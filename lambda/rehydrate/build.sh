#!/usr/bin/env bash
#
# Packages the rehydrate Lambda for upload to the AWS console.
#
# The handler imports the shared duel_core module (single source of truth in
# lambda/common/) so it reuses ingest's exact stats math. We copy it into the
# build at package time rather than duplicating it in git.
#
#   ./build.sh            -> produces rehydrate.zip in this directory
#
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
core_src="$here/../common/duel_core.py"
out="$here/rehydrate.zip"

if [[ ! -f "$core_src" ]]; then
  echo "error: cannot find duel_core.py at $core_src" >&2
  exit 1
fi

build="$(mktemp -d)"
trap 'rm -rf "$build"' EXIT

cp "$here/rehydrate.py" "$build/rehydrate.py"
cp "$core_src" "$build/duel_core.py"

rm -f "$out"
( cd "$build" && zip -q "$out" rehydrate.py duel_core.py )

echo "Built $out"
echo "Contents:"
unzip -l "$out"
