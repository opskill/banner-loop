---
name: banner-loop
description: Make or fix a 32:9 hero-banner loop video (5 s seamless, dark calm centre for an HTML headline) from the bundled Blender scenes or your own — render 1920x540, AI-upscale to 3840x1080, QC the loop, optionally review and fix. Also the asset/tool license rules for anything that ends up in these videos. Use for "render the X loop", "4K upscale", "make the loop calmer", "new banner scene", "asset license", and Korean requests like "배너 루프 렌더", "4K 업스케일", "루프 다시 뽑아", "에셋 라이선스".
---

# banner-loop

Pipeline: `scenes/<scene>.py` → Cycles 1920x540 PNG frames → 1920 mp4 → Apple VideoToolbox AI 4x (7680x2160) →
down to 3840x1080 → `_sr.mp4` → QC numbers + contact sheet.

Ask the user only for what changes the result (which scene, what to fix, ship or not). Everything else has defaults.

## Where things are

`R` = the repo root: `${CLAUDE_PLUGIN_ROOT}` when installed as a plugin (if that text is shown literally, you are in
a clone — use the clone's root, the folder with `tools/loop.sh`). Scenes `R/scenes/`, tools `R/tools/`.
When running from a plugin install, write outputs into the user's current project, not the plugin cache:
`BANNER_LOOP_OUT="$PWD/out" R/tools/loop.sh ...`. First run there: `node R/bin/fetch-assets.mjs` (two CC0 textures; they land in the plugin cache, so re-run after a plugin update).
For custom scenes, clone the repo and work in the clone.

## Options (one command)

```bash
R/tools/loop.sh --scene concept_cable_trays --key 10_cable_trays
```

| option | default | when |
|---|---|---|
| `--scene NAME` | required | `scenes/NAME.py` |
| `--key KEY` | required | output name `<nn>_<name>` |
| `--size WxH` | `1920x540` | other formats (Shorts 1080x1920, feed 1080x1350) — scene must read `lib.loop_size()`; >1920x1080 needs `--upscale none` |
| `--frames A-B` | `1-150` | 5 s @ 30 fps; partial re-render of a range |
| `--spp N` | `64` | 96 for noisy macro scenes (fiber, ix_hub); 32 for drafts |
| `--chunk N` | `50` | frames per GPU-lock hold |
| `--still F` | – | one test frame (do 1, 75, 150 before a full run) |
| `--resume` | off | continue after a crash |
| `--upscale 4k\|none` | `4k` | `none` = 1920 only (non-macOS) |
| `--no-encode` / `--no-stats` | off | frames only / skip QC |
| `--no-lock` | off | only if nothing else uses the GPU |
| `--env K=V` | – | scene knobs read from env |

`BLENDER_BIN` defaults to `/Applications/Blender.app/Contents/MacOS/Blender`. Outputs (gitignored) in
`out/concepts/video/`: frames in `full/<key>_5s_1920x540_frames/`, both mp4s, `<key>_sheet.jpg`, `<key>_stats.txt`.

Long runs: start in the background, give the user an ETA, don't poll. M2 Pro: 7–23 s/frame (17–57 min per loop),
upscale ≈ 5 min 20 s. Never render 3840x1080 directly — ~4x the render time; render 1920 and upscale.

## Shared GPU lock

Every Blender run takes `/tmp/blender_concept.lock` (`mkdir` acquire, `rmdir` release); `loop.sh` handles it. Several
agents may render at once — never kill another's Blender. A stale lock after a crash may be removed only when no
`Blender -b` process is running. After a crash use `--resume` (it also drops 0-byte placeholder frames, which Blender
would otherwise skip because scenes set `use_overwrite=False`).

## Banner rules for scenes

- 32:9, no text / logos / brand names.
- Centre ~30 % width stays dark and calm (headline). QC: centre max luma ideally < ~120.
- Gentle motion: mean adjacent diff ≲ 2–3 (0–255); fine-detail pans can read higher — check the sheet. No pumping
  (frame mean within ~±8 %).
- Seamless: frame 151 == frame 1. Integer number of periods for camera travel and pulses; fixed seed,
  `use_animated_seed=False`. QC: seam diff ≈ adjacent diff.
- Mobile pages crop to ~16:10; the crop must not be an empty gradient.
- Blender 5.x: animate with **drivers** on `frame`; keyframes ease even after `lib.set_default_interpolation`.
- Blender-version differences only in `scenes/lib.py`.

## Review → fix loop (optional)

1. A separate reviewer agent (not the author) looks at sheets, a 16:10 centre crop, 4K crops and stats, and returns
   per-scene fixes plus ship/drop.
2. One fixer per 2–3 scenes, brief = the review + these rules; at most one fix round after the first full render.
3. Re-render with `loop.sh`, report stats before → after.

## Licenses — check before anything goes into a video

Allowed, commercial OK, no attribution: Poly Haven (CC0) assets in `assets/manifest.json`; procedural geometry written
in scene code; renders from Blender (GPL covers the program, not output); macOS VideoToolbox SR output; ffmpeg as a tool.
Fonts for any overlay text: OFL fonts (e.g. Pretendard, Noto) bundled or installed — don't bake proprietary system fonts
into published video.

Needs attribution: CC-BY assets — record author/license/URL next to the asset and credit where the video is published.

Not allowed: paid/marketplace assets, unclear licenses, "personal use only", NC or ND licenses, ripped game/film assets,
real company logos/trademarks, other people's footage, AI images of unclear provenance. New source: verify the license
on the source page, record it in `manifest.json`, keep API tokens only in the shell env (never in code, commits, chat).

Not legal advice: have the publisher's legal team confirm before public use.

## Done means

150 frames, seam ≈ adjacent diff, centre calm, no pumping (numbers reported), both mp4s exist, sheet viewed. In a clone,
scene changes committed; from a plugin install, scenes are read-only — copy one into a clone to change it.
