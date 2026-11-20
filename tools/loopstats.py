"""Loop QC numbers for a rendered PNG sequence (f_0001.png ...).

usage: python3 tools/loopstats.py <frames_dir>

Prints: adjacent-frame diff vs seam diff (last->first), brightness pumping,
centre 30 % (headline zone) luma, highlight clipping. Banner targets:
seam ~= adjacent diff, adj diff <~ 2-3, pumping within ~+-8 %, centre max luma
ideally < ~120 (calm headline zone), frac>235 tiny.
"""
import glob
import sys

import numpy as np
from PIL import Image

d = sys.argv[1]
fs = sorted(glob.glob(d + "/f_*.png"))
if len(fs) < 2:
    sys.exit(f"need >= 2 frames in {d}")


def luma(p):
    a = np.asarray(Image.open(p).convert("RGB")).astype(np.float32)
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


L = [luma(p) for p in fs]
n = len(L)
W = L[0].shape[1]
c0, c1 = int(W * 0.35), int(W * 0.65)
adj = [np.abs(L[i + 1] - L[i]).mean() for i in range(n - 1)]
seam = np.abs(L[0] - L[-1]).mean()
means = np.array([l.mean() for l in L])
cmax = np.array([l[:, c0:c1].max() for l in L])
cp99 = np.array([np.percentile(l[:, c0:c1], 99.9) for l in L])
cmean = np.array([l[:, c0:c1].mean() for l in L])
cadj = [np.abs(L[i + 1][:, c0:c1] - L[i][:, c0:c1]).mean() for i in range(n - 1)]
print(f"frames {n}  adj diff mean {np.mean(adj):.2f} max {np.max(adj):.2f}  seam(last->first) {seam:.2f}")
print(f"frame mean luma {means.mean():.1f}  pumping {100*(means.min()/means.mean()-1):+.1f}% .. {100*(means.max()/means.mean()-1):+.1f}%")
print(f"centre30%: mean {cmean.mean():.1f}  max(max) {cmax.max():.0f}  mean(max) {cmax.mean():.0f}  p99.9 max {cp99.max():.0f}  adj diff {np.mean(cadj):.2f}")
print(f"global max luma {max(l.max() for l in L):.0f}  frac>235: {100*np.mean([(l > 235).mean() for l in L]):.3f}%")
