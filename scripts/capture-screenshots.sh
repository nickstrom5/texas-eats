#!/usr/bin/env bash
# Captures every -screenshot screen from an already-booted simulator with Texas Eats installed.
# Usage: bash scripts/capture-screenshots.sh "<simulator name or UDID>" [screen ...]
# PNGs go to docs/screenshots/<prefix><screen>.png, where PREFIX (default empty) lets iPhone and
# iPad runs sit side by side, e.g. PREFIX=ipad- for the 13-inch iPad set.
# A busy machine sometimes hands back a blank frame before the app has drawn; those PNGs are
# tiny, so anything under MIN_BYTES is retried with a longer wait.
set -euo pipefail
DEVICE="${1:?simulator name or UDID}"
shift
SCREENS=("$@")
[ ${#SCREENS[@]} -gt 0 ] || SCREENS=(home bbq taqueria kolache detail map honors oldest saved about)
OUT="$(cd "$(dirname "$0")/.." && pwd)/docs/screenshots"
PREFIX="${PREFIX:-}"
WAIT="${SLEEP:-6}"
MIN_BYTES=120000
mkdir -p "$OUT"
# Screenshot mode pins the location to downtown Austin, so the system permission alert is never wanted here.
xcrun simctl privacy "$DEVICE" revoke location com.texaseats.ios >/dev/null 2>&1 || true
xcrun simctl status_bar "$DEVICE" override --time 9:41 --batteryState discharging --batteryLevel 100 --wifiBars 3 --cellularBars 4 >/dev/null 2>&1 || true
for s in "${SCREENS[@]}"; do
  f="$OUT/$PREFIX$s.png"
  for attempt in 1 2 3 4; do
    xcrun simctl launch --terminate-running-process "$DEVICE" com.texaseats.ios -screenshot "$s" >/dev/null
    sleep $((WAIT + (attempt - 1) * 4))
    xcrun simctl io "$DEVICE" screenshot "$f" >/dev/null 2>&1
    size=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f")
    [ "$size" -ge "$MIN_BYTES" ] && break
    echo "  $s looked blank (${size} bytes), retrying"
  done
  echo "captured $PREFIX$s"
done
# Downscaled copies for quick review in the repo.
cd "$OUT" && for f in $(ls *.png | grep -v '^small-'); do sips -Z 600 "$f" --out "small-$f" >/dev/null; done
