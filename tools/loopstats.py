"""Loop QC numbers for a rendered PNG sequence (f_0001.png ...).

usage: python3 tools/loopstats.py [--check] <frames_dir>

Prints: adjacent-frame diff vs seam diff (last->first), brightness pumping,
centre 30 % (headline zone) luma, highlight clipping. Banner targets:
seam ~= adjacent diff, adj diff <~ 2-3, pumping within ~+-8 %, centre max luma
ideally < ~120 (calm headline zone), frac>235 tiny.

Streams the frames (keeps only the first, previous and current frame), so 3840x1080
sequences are fine.

--check: exit 1 (and print which check failed) if
  seam > 1.5 x mean adjacent diff + 0.5, pumping beyond +-10 %, or centre p99.9 luma > 160.
"""
import glob
import sys

import numpy as np
from PIL import Image

args = sys.argv[1:]
check = "--check" in args
args = [a for a in args if a != "--check"]
if len(args) != 1 or args[0].startswith("-"):
    sys.exit(__doc__)
d = args[0]
fs = sorted(glob.glob(d + "/f_*.png"))
if len(fs) < 2:
    sys.exit(f"need >= 2 frames in {d}")


def luma(p):
    a = np.asarray(Image.open(p).convert("RGB")).astype(np.float32)
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


n = len(fs)
first = prev = None
adj, cadj, means, cmax, cp99, cmean, frac = [], [], [], [], [], [], []
gmax = 0.0
for p in fs:
    l = luma(p)
    if first is None:
        first = l
        W = l.shape[1]
        c0, c1 = int(W * 0.35), int(W * 0.65)
    elif l.shape != first.shape:
        sys.exit(f"frame size differs: {p}")
    c = l[:, c0:c1]
    means.append(l.mean())
    cmax.append(c.max())
    cp99.append(np.percentile(c, 99.9))
    cmean.append(c.mean())
    frac.append((l > 235).mean())
    gmax = max(gmax, float(l.max()))
    if prev is not None:
        adj.append(np.abs(l - prev).mean())
        cadj.append(np.abs(c - prev[:, c0:c1]).mean())
    prev = l
seam = np.abs(first - prev).mean()
means, cmax, cp99, cmean = map(np.array, (means, cmax, cp99, cmean))
pump_lo, pump_hi = 100 * (means.min() / means.mean() - 1), 100 * (means.max() / means.mean() - 1)
print(f"frames {n}  adj diff mean {np.mean(adj):.2f} max {np.max(adj):.2f}  seam(last->first) {seam:.2f}")
print(f"frame mean luma {means.mean():.1f}  pumping {pump_lo:+.1f}% .. {pump_hi:+.1f}%")
print(f"centre30%: mean {cmean.mean():.1f}  max(max) {cmax.max():.0f}  mean(max) {cmax.mean():.0f}  p99.9 max {cp99.max():.0f}  adj diff {np.mean(cadj):.2f}")
print(f"global max luma {gmax:.0f}  frac>235: {100*np.mean(frac):.3f}%")

if check:
    fails = []
    lim = 1.5 * np.mean(adj) + 0.5
    if seam > lim:
        fails.append(f"seam {seam:.2f} > 1.5 x adj {np.mean(adj):.2f} + 0.5 = {lim:.2f}")
    if pump_lo < -10 or pump_hi > 10:
        fails.append(f"pumping {pump_lo:+.1f}% .. {pump_hi:+.1f}% beyond +-10%")
    if cp99.max() > 160:
        fails.append(f"centre p99.9 luma {cp99.max():.0f} > 160")
    for f in fails:
        print(f"FAIL: {f}")
    print("check: " + ("FAILED" if fails else "ok"))
    sys.exit(1 if fails else 0)
