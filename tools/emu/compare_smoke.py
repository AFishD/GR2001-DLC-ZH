#!/usr/bin/env python3
"""compare_smoke.py -- A/B compare two run_smoke.py output directories.

Pairs the *native* (clean emulated framebuffer) screenshots by capture tag
(e.g. "045s", "final"), then reports per-pair pixel statistics so a Chinese
localization build can be compared against the English baseline, or two
candidate builds against each other.

Usage:
    python tools\\emu\\compare_smoke.py ^
        --a work\\analysis\\emu\\baseline --b work\\analysis\\emu\\font_proto ^
        --out work\\analysis\\emu\\ab_baseline_vs_fontproto.json

    # or a single pair:
    python tools\\emu\\compare_smoke.py --image-a a.png --image-b b.png

Pairing rule: prefix_"native_<tag>.png" files inside each run directory; tags
are matched by name.  Extra/missing tags are reported.  A pair is "identical"
when every pixel matches, "content-diff" otherwise; region statistics
(y-band histograms) help localise where the diff lives.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
except ImportError as e:  # pragma: no cover
    print(f"PIL/numpy required: {e}", file=sys.stderr)
    sys.exit(2)


def collect(run_dir: Path) -> dict[str, Path]:
    out = {}
    for p in sorted(run_dir.glob("*native_*.png")):
        tag = p.stem.split("native_", 1)[1]
        out[tag] = p
    if not out:  # fall back to window captures
        for p in sorted(run_dir.glob("*window_*.png")):
            tag = p.stem.split("window_", 1)[1]
            out[tag] = p
    return out


def diff_pair(a: Path, b: Path, bands: int = 8) -> dict:
    ia = Image.open(a).convert("RGB")
    ib = Image.open(b).convert("RGB")
    rec = {"a": str(a), "b": str(b), "size_a": list(ia.size), "size_b": list(ib.size)}
    if ia.size != ib.size:
        ib = ib.resize(ia.size, Image.BILINEAR)
        rec["resized_b_to_a"] = True
    aa = np.asarray(ia, dtype=np.int16)
    bb = np.asarray(ib, dtype=np.int16)
    d = np.abs(aa - bb).max(axis=2)
    total = int(d.size)
    changed = int((d > 0).sum())
    rec.update({
        "pixels": total,
        "pixels_diff": changed,
        "pixels_diff_ratio": round(changed / total, 6) if total else 0.0,
        "identical": changed == 0,
        "mean_abs_diff": round(float(d.mean()), 4),
        "max_abs_diff": int(d.max()),
        "luma_mean_a": round(float(aa.mean()), 2),
        "luma_mean_b": round(float(bb.mean()), 2),
    })
    h = d.shape[0]
    band_stats = []
    for i in range(bands):
        y0 = h * i // bands
        y1 = h * (i + 1) // bands
        band_stats.append({"y": [y0, y1],
                           "diff_px": int((d[y0:y1] > 0).sum()),
                           "ratio": round(float((d[y0:y1] > 0).mean()), 5)})
    rec["bands"] = band_stats
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", help="run_smoke output dir A (baseline)")
    ap.add_argument("--b", help="run_smoke output dir B (candidate)")
    ap.add_argument("--image-a")
    ap.add_argument("--image-b")
    ap.add_argument("--out", help="write JSON report here")
    a = ap.parse_args(argv)

    if a.image_a and a.image_b:
        rep = {"pairs": [diff_pair(Path(a.image_a), Path(a.image_b))]}
    elif a.a and a.b:
        run_a = collect(Path(a.a))
        run_b = collect(Path(a.b))
        tags = sorted(set(run_a) & set(run_b))
        rep = {
            "dir_a": str(a.a), "dir_b": str(a.b),
            "tags_a": sorted(run_a), "tags_b": sorted(run_b),
            "shared_tags": tags,
            "only_a": sorted(set(run_a) - set(run_b)),
            "only_b": sorted(set(run_b) - set(run_a)),
            "pairs": [],
        }
        for t in tags:
            rec = diff_pair(run_a[t], run_b[t])
            rec["tag"] = t
            rep["pairs"].append(rec)
    else:
        ap.error("need either --a/--b or --image-a/--image-b")

    pairs = rep["pairs"]
    identical = sum(1 for p in pairs if p["identical"])
    rep["summary"] = {
        "pairs": len(pairs),
        "identical": identical,
        "different": len(pairs) - identical,
        "max_pixels_diff_ratio": max((p["pixels_diff_ratio"] for p in pairs), default=0.0),
    }
    text = json.dumps(rep, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"wrote {a.out}")
    else:
        print(text)
    print(f"[compare] pairs={len(pairs)} identical={identical} "
          f"different={len(pairs) - identical}")
    for p in pairs:
        print(f"  {p.get('tag', '?'):>8}  diff={p['pixels_diff']:>9} px "
              f"({p['pixels_diff_ratio'] * 100:6.3f}%)  max={p['max_abs_diff']:>3}  "
              f"{'IDENTICAL' if p['identical'] else 'DIFF'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
