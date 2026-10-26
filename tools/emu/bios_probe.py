# -*- coding: utf-8 -*-
"""bios_probe.py —— 用指定 BIOS 启动（不开 fastboot），连拍 BIOS/开机画面，验证 BIOS 语言。

用法：
  python tools/emu/bios_probe.py --iso <iso> --bios "<bios.bin>" --out <dir> --runtime <dir>
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import nav_squad as NS  # noqa: E402
import run_smoke as RS  # noqa: E402


class Args(object):
    def __init__(self, iso, out, runtime):
        self.iso = iso
        self.out = out
        self.runtime = runtime
        self.input = 'post'
        self.sweep = False
        self.diag = True
        self.mode = 'run'


class BiosProbe(NS.Runner):
    def __init__(self, args, bios_path):
        super(BiosProbe, self).__init__(args)
        self.bios_path = Path(bios_path)

    def start(self):
        try:
            subprocess.run(['taskkill', '/IM', 'pcsx2-qt.exe', '/F', '/T'],
                           capture_output=True, timeout=20)
        except Exception:
            pass
        prov = RS.provision_runtime(self.runtime, Path(RS.DEFAULT_SOURCE_PCSX2),
                                    self.bios_path, force=True)
        ini = RS.write_clean_ini(self.runtime, renderer='dx12',
                                 bios_name=Path(prov['bios']).name,
                                 framelimit=True, memcard='', texfilter=-1)
        NS.patch_ini_osd(Path(ini))
        log_path = self.out / 'emulog.txt'
        if log_path.exists():
            log_path.unlink()
        exe = self.runtime / 'pcsx2-qt.exe'
        cmd = [str(exe), '-batch', '-logfile', str(log_path), '--', str(self.iso)]
        self.console = open(self.out / 'console.txt', 'wb')
        self.proc = subprocess.Popen(cmd, cwd=str(self.runtime),
                                     stdout=self.console,
                                     stderr=subprocess.STDOUT,
                                     env=dict(__import__('os').environ))
        self.log('boot pid=%d iso=%s bios=%s' % (self.proc.pid, self.iso.name,
                                                 self.bios_path.name))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--iso', required=True)
    ap.add_argument('--bios', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--runtime', required=True)
    ap.add_argument('--secs', type=float, default=110.0)
    ap.add_argument('--step', type=float, default=3.0)
    a = ap.parse_args()
    p = BiosProbe(Args(a.iso, a.out, a.runtime), a.bios)
    p.start()
    try:
        t0 = time.time()
        i = 0
        while time.time() - t0 < a.secs:
            img = p.grab()
            if img is not None:
                p.save(img, 'bios_%03d' % i)
            i += 1
            time.sleep(a.step)
    finally:
        p.stop()


if __name__ == '__main__':
    main()
