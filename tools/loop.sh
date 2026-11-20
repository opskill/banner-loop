#!/bin/bash
# Render a concept loop scene -> 1920x540 mp4 -> (optional) AI 4x upscale to 3840x1080 mp4 -> QC.
#
# usage: tools/loop.sh --scene concept_cable_trays --key 10_cable_trays [options]
#
#   --scene NAME      scenes/NAME.py (required)
#   --key KEY         output name, e.g. 10_cable_trays (required unless --still)
#   --frames A-B      frame range (default 1-150 = 5 s @ 30 fps). A partial range (e.g. 40-60) deletes and
#                     re-renders only those frames, then encodes/upscales/QCs the whole sequence in the frames dir
#                     (frames 1..N must all exist). Only a full range (1-150 or more) without --resume wipes the dir.
#   --chunk N         frames per Blender run / GPU-lock hold (default 50)
#   --spp N           Cycles samples (default 64)
#   --still F         render only frame F to out/concepts/video/stills/<scene>_fF.png and stop
#   --resume          skip frames that already exist in the frames dir (after a crash)
#   --upscale 4k|none AI upscale with tools/vtsr (macOS 26+, clang). default 4k on macOS, none elsewhere
#   --no-encode       render frames only (no mp4, no upscale)
#   --no-stats        skip loop QC numbers
#   --no-lock         don't take the shared GPU lock (only if nothing else renders)
#   --env K=V         extra env var for the scene (repeatable), e.g. --env FIBER_CENTER_FILL=0.6
#
# Outputs (gitignored; root = $BANNER_LOOP_OUT or <repo>/out):
#   out/concepts/video/full/<key>_5s_1920x540_frames/f_####.png
#   out/concepts/video/<key>_5s_1920x540.mp4            (H.264, BT.709 tagged)
#   out/concepts/video/<key>_5s_3840x1080_sr.mp4
#   out/concepts/video/<key>_sheet.jpg, <key>_stats.txt (1920 QC + "4K (SR)" QC)
set -euo pipefail

APP=$(cd "$(dirname "$0")/.." && pwd)
OUTROOT=${BANNER_LOOP_OUT:-$APP/out}   # set BANNER_LOOP_OUT when installed as a plugin (cache dir is replaced on update)
V=$OUTROOT/concepts/video
BLENDER_BIN=${BLENDER_BIN:-/Applications/Blender.app/Contents/MacOS/Blender}
LOCK=${BANNER_LOOP_LOCK:-/tmp/blender_concept.lock}   # shared with other renderers on this machine

die() { echo "loop.sh: $*" >&2; exit 2; }
posint() { [[ $2 =~ ^[0-9]+$ ]] && [ $((10#$2)) -ge 1 ] || die "$1 must be a positive integer (got '$2')"; }

scene="" key="" frames="1-150" chunk=50 spp=64 still="" resume=0 upscale=4k upscale_set=0 encode=1 stats=1 lock=1
envs=()
while [ $# -gt 0 ]; do
  case $1 in
    --scene|--key|--frames|--chunk|--spp|--still|--upscale|--env)
      [ $# -ge 2 ] && [[ $2 != --* ]] || die "$1 needs a value (see --help)" ;;
  esac
  case $1 in
    --scene) scene=$2; shift 2 ;;
    --key) key=$2; shift 2 ;;
    --frames) frames=$2; shift 2 ;;
    --chunk) chunk=$2; shift 2 ;;
    --spp) spp=$2; shift 2 ;;
    --still) still=$2; shift 2 ;;
    --resume) resume=1; shift ;;
    --upscale) upscale=$2; upscale_set=1; shift 2 ;;
    --no-encode) encode=0; shift ;;
    --no-stats) stats=0; shift ;;
    --no-lock) lock=0; shift ;;
    --env) envs+=("$2"); shift 2 ;;
    -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

# ---- validate options ----
[[ $scene =~ ^[a-z0-9_]+$ ]] || die "--scene required (e.g. concept_cable_trays)"
[ -f "$APP/scenes/$scene.py" ] || die "no scene: scenes/$scene.py"
posint --chunk "$chunk"; chunk=$((10#$chunk))
posint --spp "$spp"; spp=$((10#$spp))
[ -z "$still" ] || { posint --still "$still"; still=$((10#$still)); }
[[ $frames =~ ^([0-9]+)-([0-9]+)$ ]] || die "--frames must be A-B with positive integers, e.g. 1-150 (got '$frames')"
first=$((10#${BASH_REMATCH[1]})) last=$((10#${BASH_REMATCH[2]}))
[ $first -ge 1 ] && [ $last -ge $first ] || die "--frames A-B needs 1 <= A <= B (got '$frames')"
case $upscale in 4k|none) ;; *) die "--upscale must be 4k or none (got '$upscale')" ;; esac
for e in "${envs[@]+"${envs[@]}"}"; do [[ $e =~ ^[A-Z_][A-Z0-9_]*=[A-Za-z0-9_.-]*$ ]] || die "bad --env $e (K=V, K upper-case)"; done
[ -n "$still" ] || [[ $key =~ ^[a-z0-9_]+$ ]] || die "--key required (e.g. 10_cable_trays)"

# ---- preflight: tools ----
command -v node >/dev/null || die "node not found (Node 20+ runs bin/blender.mjs)"
[ -x "$BLENDER_BIN" ] || command -v "$BLENDER_BIN" >/dev/null || die "Blender not found: $BLENDER_BIN (set BLENDER_BIN)"
if [ -z "$still" ] && [ $encode = 1 ]; then
  command -v ffmpeg >/dev/null || die "ffmpeg not found (needed to encode; or pass --no-encode)"
  if [ $stats = 1 ]; then
    command -v python3 >/dev/null || die "python3 not found (needed for QC; or pass --no-stats)"
    python3 -c 'import numpy, PIL' 2>/dev/null || die "python3 needs numpy and Pillow for QC: python3 -m pip install numpy Pillow (or pass --no-stats)"
  fi
  VTSR=$OUTROOT/vtsr
  if [ $upscale = 4k ]; then
    if [ "$(uname -s)" != Darwin ]; then
      [ $upscale_set = 0 ] || die "--upscale 4k needs macOS 26+ (Apple VideoToolbox super resolution); use --upscale none"
      echo "note: not macOS, so no AI upscale (--upscale none); only the 1920x540 mp4 is made" >&2
      upscale=none
    else
      osv=$(sw_vers -productVersion 2>/dev/null || echo 0)
      [ "${osv%%.*}" -ge 26 ] 2>/dev/null || die "--upscale 4k needs macOS 26+ (this is $osv); use --upscale none"
      if [ ! -x "$VTSR" ] || [ "$APP/tools/vtsr.m" -nt "$VTSR" ]; then
        if ! command -v clang >/dev/null; then
          [ -x "$VTSR" ] || die "clang not found to build tools/vtsr.m (xcode-select --install), or use --upscale none"
          echo "note: tools/vtsr.m is newer than $VTSR but clang is missing; using the old build" >&2
        fi
      fi
    fi
  fi
fi

# ---- shared GPU lock: mkdir $LOCK, pid in $LOCK/pid; released on exit / Ctrl-C ----
held=0
release_lock() { if [ $held = 1 ]; then rm -f "$LOCK/pid"; rmdir "$LOCK" 2>/dev/null || true; held=0; fi; }
trap release_lock EXIT
trap 'release_lock; exit 130' INT
trap 'release_lock; exit 143' TERM
alive() { kill -0 "$1" 2>/dev/null || ps -p "$1" >/dev/null 2>&1; }
acquire_lock() {
  local said="" pid
  until mkdir "$LOCK" 2>/dev/null; do
    pid=$(cat "$LOCK/pid" 2>/dev/null || true)
    if [[ $pid =~ ^[0-9]+$ ]] && ! alive "$pid"; then
      # stale: holder died without releasing. Move it aside atomically so two waiters can't both take over.
      if mv "$LOCK" "$LOCK.stale.$$" 2>/dev/null; then
        echo "GPU lock held by dead pid $pid: taking over" >&2
        rm -rf "$LOCK.stale.$$"
        continue
      fi
    fi
    if [ "$said" != "${pid:-?}" ]; then
      if [ -n "$pid" ]; then echo "waiting for GPU lock (held by pid $pid)…" >&2
      else echo "waiting for GPU lock $LOCK (no pid recorded; remove it if no Blender is running)…" >&2; fi
      said=${pid:-?}
    fi
    sleep 5
  done
  held=1
  echo $$ > "$LOCK/pid"
}

blender() { # LOG args... -> one Blender run (output to LOG), under the shared GPU lock
  local rc=0 log=$1; shift
  if [ $lock = 1 ]; then acquire_lock; fi
  (cd "$APP" && env "${envs[@]+"${envs[@]}"}" BLENDER_BIN="$BLENDER_BIN" RENDER_GPU_ONLY=1 \
    node bin/blender.mjs "$scene" --engine cycles --spp "$spp" "$@") > "$log" 2>&1 || rc=$?
  release_lock
  return $rc
}

if [ -n "$still" ]; then
  mkdir -p "$V/stills"
  log=$V/stills/${scene}_f${still}.log
  blender "$log" --still "$still" --out "$V/stills/${scene}_f${still}" \
    || { echo "still render failed; last lines of $log:" >&2; tail -30 "$log" >&2; exit 1; }
  ls "$V/stills/${scene}_f${still}"* | grep -v '\.log$'
  exit 0
fi

OUT=$V/full/${key}_5s_1920x540
F=${OUT}_frames
mkdir -p "$V/full" "$V/logs"
fname() { printf '%s/f_%04d.png' "$F" "$1"; }
maxframe() { { ls "$F" 2>/dev/null || true; } | sed -n 's/^f_0*\([0-9][0-9]*\)\.png$/\1/p' | sort -n | tail -1; }

existing=$(maxframe); existing=${existing:-0}
full=0; [ $first = 1 ] && [ $last -ge 150 ] && [ $last -ge $existing ] && full=1
if [ $resume = 1 ]; then
  # a crash leaves 0-byte placeholder PNGs; Blender skips existing files (use_overwrite=False), so drop them first
  find "$F" -name 'f_*.png' -size 0 -delete 2>/dev/null || true
elif [ $full = 1 ]; then
  rm -rf "$F"
else
  echo "partial range $first-$last: re-rendering only these frames in $F"
  for ((i = first; i <= last; i++)); do rm -f "$(fname $i)"; done
fi

s=$first
while [ $s -le $last ]; do
  e=$((s + chunk - 1)); [ $e -gt $last ] && e=$last
  if [ $resume = 1 ]; then # skip a fully rendered chunk; restart a partial one from its first missing frame
    while [ $s -le $e ] && [ -s "$(fname $s)" ]; do s=$((s + 1)); done
    [ $s -gt $e ] && { s=$((e + 1)); continue; }
  fi
  t0=$(date +%s)
  blender "$V/logs/${key}_$s.log" --start $s --end $e --out "$OUT" \
    || { echo "render failed; last lines of $V/logs/${key}_$s.log:" >&2; tail -20 "$V/logs/${key}_$s.log" >&2; exit 1; }
  echo "$(date +%T) frames $s-$e  $(( $(date +%s) - t0 )) s"
  s=$((e + 1))
  [ $s -le $last ] && [ $lock = 1 ] && sleep 25   # let other renderers take the GPU
done

# ---- the whole sequence 1..N must be there before encode/upscale/QC ----
n=$(maxframe); n=${n:-0}
missing=()
for ((i = 1; i <= n; i++)); do [ -s "$(fname $i)" ] || missing+=($i); done
echo "frames in $F: 1-$n"
if [ ${#missing[@]} -gt 0 ]; then
  echo "loop.sh: ${#missing[@]} frame(s) missing or empty in 1-$n (first: ${missing[*]:0:10}); render them with --frames A-B (or --resume) before encoding" >&2
  exit 1
fi
[ $n -ge 2 ] || { echo "loop.sh: need at least 2 frames to encode" >&2; exit 1; }
[ $n = 150 ] || echo "note: $n frames (not 150), so this is not a 5 s loop" >&2
[ $encode = 1 ] || exit 0

# BT.709 (limited range) YUV with matching tags, so players don't guess the matrix
ENC=(-vf "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709" -c:v libx264 -crf 20 -preset slow -pix_fmt yuv420p
     -colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv -movflags +faststart)
ffmpeg -v error -y -framerate 30 -start_number 1 -i "$F/f_%04d.png" -frames:v $n "${ENC[@]}" "$V/${key}_5s_1920x540.mp4"
echo "1920: $V/${key}_5s_1920x540.mp4"

rows=$(( (n + 29) / 30 ))
ffmpeg -v error -y -framerate 30 -start_number 1 -i "$F/f_%04d.png" \
  -vf "select='not(mod(n\,30))',scale=1280:-1,tile=1x$rows" -frames:v 1 -q:v 3 "$V/${key}_sheet.jpg"
echo "sheet: $V/${key}_sheet.jpg"
if [ $stats = 1 ]; then
  { echo "== 1920x540 =="; python3 "$APP/tools/loopstats.py" "$F"; } | tee "$V/${key}_stats.txt"
fi

if [ $upscale = 4k ]; then
  if [ ! -x "$VTSR" ] || { [ "$APP/tools/vtsr.m" -nt "$VTSR" ] && command -v clang >/dev/null; }; then
    echo "building $VTSR"
    clang -fobjc-arc -O2 -mmacosx-version-min=26.0 "$APP/tools/vtsr.m" -o "$VTSR" \
      -framework Foundation -framework VideoToolbox -framework CoreVideo -framework CoreMedia \
      -framework ImageIO -framework CoreGraphics -framework UniformTypeIdentifiers \
      || { echo "loop.sh: building tools/vtsr.m failed (or use --upscale none)" >&2; exit 1; }
  fi
  T=$V/full/${key}_sr_tmp; rm -rf "$T"; mkdir -p "$T"
  # Apple's SR model only does 4x: 1920x540 -> 7680x2160, then down to 3840x1080. 8-frame preroll keeps the seam clean.
  "$VTSR" "$F" "$T" 4 8 3840 1080
  ffmpeg -v error -y -framerate 30 -start_number 1 -i "$T/f_%04d.png" -frames:v $n "${ENC[@]}" "$V/${key}_5s_3840x1080_sr.mp4"
  if [ $stats = 1 ]; then
    { echo; echo "== 4K (SR) 3840x1080 =="; python3 "$APP/tools/loopstats.py" "$T"; } | tee -a "$V/${key}_stats.txt"
  fi
  rm -rf "$T"
  echo "4K:   $V/${key}_5s_3840x1080_sr.mp4"
fi
