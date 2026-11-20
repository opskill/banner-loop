#!/bin/bash
# Assemble the demo site into site/dist (gitignored): page + logo + posters + the release MP4s.
# usage: site/build.sh [release-tag]   then: cd site/dist && vercel deploy --prod
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
TAG=${1:-v0.2.0}
D=$ROOT/site/dist
mkdir -p "$D/posters" "$D/videos"
cp "$ROOT/site/index.html" "$ROOT/site/vercel.json" "$D/"
cp "$ROOT/.github/opskill-logo.svg" "$D/logo.svg"
cp "$ROOT"/docs/examples/*.jpg "$D/posters/"
# release assets are named <key>_1920x540.mp4 / <key>_3840x1080.mp4, the same names the page uses
for k in $(ls "$ROOT"/docs/examples/*.jpg | xargs -n1 basename | sed 's/\.jpg$//'); do
  for res in 1920x540 3840x1080; do
    out="$D/videos/${k}_${res}.mp4"
    [ -s "$out" ] || curl -fsSL "https://github.com/opskill/banner-loop/releases/download/$TAG/${k}_${res}.mp4" -o "$out"
  done
done
echo "site ready: $D ($(du -sh "$D" | cut -f1))"
