#!/bin/bash
# Render a concept loop scene -> 1920x540 mp4 -> (optional) AI 4x upscale to 3840x1080 mp4 -> QC.
#
# usage: tools/loop.sh --scene concept_cable_trays --key 10_cable_trays [options]
#
#   --scene NAME      scenes/NAME.py (required)
#   --key KEY         output name, e.g. 10_cable_trays (required unless --still)
#   --frames A-B      frame range (default 1-150 = 5 s @ 30 fps)
#   --chunk N         frames per Blender run / GPU-lock hold (default 50)
#   --spp N           Cycles samples (default 64)
#   --still F         render only frame F to out/concepts/video/stills/<scene>_fF.png and stop
#   --resume          skip frames that already exist in the frames dir (after a crash)
#   --upscale 4k|none AI upscale with tools/vtsr (macOS 26+). default 4k
#   --no-encode       render frames only (no mp4, no upscale)
#   --no-stats        skip loop QC numbers
#   --no-lock         don't take the shared GPU lock (only if nothing else renders)
#   --env K=V         extra env var for the scene (repeatable), e.g. --env FIBER_CENTER_FILL=0.6
#
# Outputs (gitignored; root = $BANNER_LOOP_OUT or <repo>/out):
#   out/concepts/video/full/<key>_5s_1920x540_frames/f_####.png
#   out/concepts/video/<key>_5s_1920x540.mp4
#   out/concepts/video/<key>_5s_3840x1080_sr.mp4
#   out/concepts/video/<key>_sheet.jpg, <key>_stats.txt
set -euo pipefail

APP=$(cd "$(dirname "$0")/.." && pwd)
OUTROOT=${BANNER_LOOP_OUT:-$APP/out}   # set BANNER_LOOP_OUT when installed as a plugin (cache dir is replaced on update)
V=$OUTROOT/concepts/video
BLENDER_BIN=${BLENDER_BIN:-/Applications/Blender.app/Contents/MacOS/Blender}
LOCK=/tmp/blender_concept.lock

scene="" key="" frames="1-150" chunk=50 spp=64 still="" resume=0 upscale=4k encode=1 stats=1 lock=1
envs=()
while [ $# -gt 0 ]; do
  case $1 in
    --scene) scene=$2; shift 2 ;;
    --key) key=$2; shift 2 ;;
    --frames) frames=$2; shift 2 ;;
    --chunk) chunk=$2; shift 2 ;;
    --spp) spp=$2; shift 2 ;;
    --still) still=$2; shift 2 ;;
    --resume) resume=1; shift ;;
    --upscale) upscale=$2; shift 2 ;;
    --no-encode) encode=0; shift ;;
    --no-stats) stats=0; shift ;;
    --no-lock) lock=0; shift ;;
    --env) envs+=("$2"); shift 2 ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

[[ $scene =~ ^[a-z0-9_]+$ ]] || { echo "--scene required (e.g. concept_cable_trays)" >&2; exit 2; }
[ -f "$APP/scenes/$scene.py" ] || { echo "no scene: scenes/$scene.py" >&2; exit 2; }
[ -x "$BLENDER_BIN" ] || command -v "$BLENDER_BIN" >/dev/null || { echo "Blender not found: $BLENDER_BIN (set BLENDER_BIN)" >&2; exit 2; }
[[ $frames =~ ^([0-9]+)-([0-9]+)$ ]] || { echo "--frames must be A-B" >&2; exit 2; }
first=${BASH_REMATCH[1]} last=${BASH_REMATCH[2]}
case $upscale in 4k|none) ;; *) echo "--upscale 4k|none" >&2; exit 2 ;; esac
for e in "${envs[@]+"${envs[@]}"}"; do [[ $e =~ ^[A-Z_][A-Z0-9_]*=[A-Za-z0-9_.-]*$ ]] || { echo "bad --env $e" >&2; exit 2; }; done

blender() { # args... -> one Blender run, under the shared GPU lock
  local rc=0
  if [ $lock = 1 ]; then until mkdir $LOCK 2>/dev/null; do sleep 5; done; fi
  (cd "$APP" && env "${envs[@]+"${envs[@]}"}" BLENDER_BIN="$BLENDER_BIN" RENDER_GPU_ONLY=1 \
    node bin/blender.mjs "$scene" --engine cycles --spp "$spp" "$@") || rc=$?
  if [ $lock = 1 ]; then rmdir $LOCK; fi
  return $rc
}

if [ -n "$still" ]; then
  mkdir -p "$V/stills"
  blender --still "$still" --out "$V/stills/${scene}_f${still}" > "$V/stills/${scene}_f${still}.log" 2>&1
  ls "$V/stills/${scene}_f${still}"* | grep -v '\.log$'
  exit 0
fi

[[ $key =~ ^[a-z0-9_]+$ ]] || { echo "--key required (e.g. 10_cable_trays)" >&2; exit 2; }
OUT=$V/full/${key}_5s_1920x540
F=${OUT}_frames
mkdir -p "$V/full" "$V/logs"
if [ $resume = 1 ]; then
  # a crash leaves 0-byte placeholder PNGs; Blender skips existing files (use_overwrite=False), so drop them first
  find "$F" -name 'f_*.png' -size 0 -delete 2>/dev/null || true
else
  rm -rf "$F"
fi

s=$first
while [ $s -le $last ]; do
  e=$((s + chunk - 1)); [ $e -gt $last ] && e=$last
  if [ $resume = 1 ]; then # skip a fully rendered chunk; restart a partial one from its first missing frame
    while [ $s -le $e ] && [ -s "$F/$(printf 'f_%04d.png' $s)" ]; do s=$((s + 1)); done
    [ $s -gt $e ] && { s=$((e + 1)); continue; }
  fi
  t0=$(date +%s)
  blender --start $s --end $e --out "$OUT" > "$V/logs/${key}_$s.log" 2>&1 || { tail -20 "$V/logs/${key}_$s.log"; exit 1; }
  echo "$(date +%T) frames $s-$e  $(( $(date +%s) - t0 )) s"
  s=$((e + 1))
  [ $s -le $last ] && [ $lock = 1 ] && sleep 25   # let other renderers take the GPU
done

n=$(ls "$F" | grep -c '^f_.*\.png$' || true)
echo "frames in $F: $n"
[ $encode = 1 ] || exit 0

ENC=(-c:v libx264 -crf 20 -preset slow -pix_fmt yuv420p -movflags +faststart)
ffmpeg -v error -y -framerate 30 -start_number $first -i "$F/f_%04d.png" "${ENC[@]}" "$V/${key}_5s_1920x540.mp4"
echo "1920: $V/${key}_5s_1920x540.mp4"

if [ $upscale = 4k ]; then
  VTSR=$OUTROOT/vtsr
  if [ ! -x "$VTSR" ]; then
    clang -fobjc-arc -O2 -mmacosx-version-min=26.0 "$APP/tools/vtsr.m" -o "$VTSR" \
      -framework Foundation -framework VideoToolbox -framework CoreVideo -framework CoreMedia \
      -framework ImageIO -framework CoreGraphics -framework UniformTypeIdentifiers
  fi
  T=$V/full/${key}_sr_tmp; rm -rf "$T"; mkdir -p "$T"
  # Apple's SR model only does 4x: 1920x540 -> 7680x2160, then down to 3840x1080. 8-frame preroll keeps the seam clean.
  "$VTSR" "$F" "$T" 4 8 3840 1080
  ffmpeg -v error -y -framerate 30 -i "$T/f_%04d.png" "${ENC[@]}" "$V/${key}_5s_3840x1080_sr.mp4"
  rm -rf "$T"
  echo "4K:   $V/${key}_5s_3840x1080_sr.mp4"
fi

ffmpeg -v error -y -framerate 30 -i "$F/f_%04d.png" -vf "select='not(mod(n\,30))',scale=1280:-1,tile=1x5" \
  -frames:v 1 -q:v 3 "$V/${key}_sheet.jpg"
echo "sheet: $V/${key}_sheet.jpg"
if [ $stats = 1 ]; then python3 "$APP/tools/loopstats.py" "$F" | tee "$V/${key}_stats.txt"; fi
