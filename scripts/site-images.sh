#!/usr/bin/env bash
# Landing-page screenshots: 480px-wide copies of docs/screenshots/{home,bbq,detail,map,honors}.png in docs/img/, PNG plus WebP
# (cwebp -q 84), as in co-eats. Run after scripts/capture-screenshots.sh, then re-run scripts/make-site.py (it reads the image sizes
# and writes the "What it looks like" section only when these files exist).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p docs/img
for s in home bbq detail map honors; do
  [ -f "docs/screenshots/$s.png" ] || { echo "missing docs/screenshots/$s.png"; exit 1; }
  sips -Z 1043 "docs/screenshots/$s.png" --out "docs/img/screen-$s.png" >/dev/null   # 480 x 1043 for a 1320 x 2868 capture
  cwebp -quiet -q 84 "docs/img/screen-$s.png" -o "docs/img/screen-$s.webp"
done
ls -la docs/img
