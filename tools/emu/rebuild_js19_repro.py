# -*- coding: utf-8 -*-
"""Rebuild the JS_ZH19 reproduction ISO from the English original + the
payloads recovered from the PCSX2 cdvd block dump (task-5 / lead request #2).

Inputs (all recovered by the dump-analysis workstream):
  work/analysis/js19/JS_ZH19_ELF_from_dump.bin   patched ELF (5,319,720 B)
  work/analysis/js19/payloads/00009_COMMON.PAK.bin       raw payload (763,676 B)
  work/analysis/js19/payloads/00576_EN_STRINGS.RES.bin   LZO frame (expanded 177,441 B)
  work/analysis/js19/payloads/00580_FONT.RES.bin         LZO frame (expanded 7,488 B)

rebuild.py expects *expanded* blobs for LZO resources, so the frames are
decompressed here first (dlclib.lzo_subs + lzo_join).

Usage:
    python tools\\emu\\rebuild_js19_repro.py [--out PATH] [--force]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent.parent
TOOLS_DLC = WORKSPACE / "tools" / "dlc"
sys.path.insert(0, str(TOOLS_DLC))
import dlclib as L  # noqa: E402

ORIG_ISO = WORKSPACE / "third_party" / "orig" / "ps2" / "[PS2] Tom Clancy's Ghost Recon - Jungle Storm (U).iso"
JS19 = WORKSPACE / "work" / "analysis" / "js19"
ELF = JS19 / "JS_ZH19_ELF_from_dump.bin"
COMMON_PAK = JS19 / "payloads" / "00009_COMMON.PAK.bin"
EN_STRINGS = JS19 / "payloads" / "00576_EN_STRINGS.RES.bin"
FONT_RES = JS19 / "payloads" / "00580_FONT.RES.bin"
EXPANDED = JS19 / "expanded"
DEFAULT_OUT = JS19 / "JS_ZH19_repro.iso"

EXPECT_LEN = {"elf": 5319720, "common_pak": 763676, "en_strings": 177441, "font_res": 7488}


def expand_frame(path: Path, expect_len: int) -> bytes:
    raw = path.read_bytes()
    subs = L.lzo_subs(raw)
    if not subs:
        raise SystemExit(f"{path.name}: no LZO substreams parsed")
    blob = L.lzo_join(subs)
    if len(blob) != expect_len:
        raise SystemExit(f"{path.name}: expanded {len(blob)} != expected {expect_len} "
                         f"(substreams={[(s[1], s[2]) for s in subs]})")
    return blob


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--force", action="store_true", help="overwrite existing output")
    a = ap.parse_args(argv)

    for p in (ORIG_ISO, ELF, COMMON_PAK, EN_STRINGS, FONT_RES):
        if not p.exists():
            raise SystemExit(f"missing input: {p}")

    out_iso = Path(a.out)
    if out_iso.exists() and not a.force:
        print(f"[js19] output already exists: {out_iso} (use --force to rebuild)")
        return 0

    EXPANDED.mkdir(parents=True, exist_ok=True)
    elf = ELF.read_bytes()
    pak = COMMON_PAK.read_bytes()
    en = expand_frame(EN_STRINGS, EXPECT_LEN["en_strings"])
    font = expand_frame(FONT_RES, EXPECT_LEN["font_res"])
    (EXPANDED / "00576_EN_STRINGS.RES.blob.bin").write_bytes(en)
    (EXPANDED / "00580_FONT.RES.blob.bin").write_bytes(font)

    print(f"[js19] elf={len(elf)} sha256={L.sha256(elf)[:16]}...")
    print(f"[js19] common_pak={len(pak)} sha256={L.sha256(pak)[:16]}...")
    print(f"[js19] en_strings_frame={EN_STRINGS.stat().st_size} expanded={len(en)} "
          f"sha256={L.sha256(en)[:16]}...")
    print(f"[js19] font_res_frame={FONT_RES.stat().st_size} expanded={len(font)} "
          f"sha256={L.sha256(font)[:16]}...")

    cmd = [sys.executable, str(TOOLS_DLC / "rebuild.py"),
           "--iso", str(ORIG_ISO), "--out", str(out_iso),
           "--elf", str(ELF),
           "--replace", f"GR#9={COMMON_PAK}",
           "--replace", f"GR#576={EXPANDED / '00576_EN_STRINGS.RES.blob.bin'}",
           "--replace", f"GR#580={EXPANDED / '00580_FONT.RES.blob.bin'}"]
    print("[js19] running:", " ".join(cmd))
    r = subprocess.run(cmd, cwd=str(WORKSPACE))
    if r.returncode != 0:
        print(f"[js19] rebuild.py FAILED rc={r.returncode}")
        return r.returncode
    print(f"[js19] built {out_iso} ({out_iso.stat().st_size} B) "
          f"sha256={L.sha256_file(out_iso)[:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
