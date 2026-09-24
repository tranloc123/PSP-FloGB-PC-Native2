from __future__ import annotations

from pathlib import Path
import subprocess
import sys

if len(sys.argv) != 2:
    raise SystemExit('Usage: build_patch_chain_final.py <ppsspp_repo>')

ROOT = Path(__file__).resolve().parent
REPO = Path(sys.argv[1]).resolve()
PYTHON = sys.executable


def run(*args):
    cmd=[str(x) for x in args]
    print('>>>',' '.join(cmd),flush=True)
    subprocess.run(cmd,check=True)

print('=== PSP FloGB FINAL ONE-BUILD PATCH CHAIN ===')
run(PYTHON, ROOT / 'build_patch_chain_fix7.py', REPO)
run(PYTHON, ROOT / 'tools' / 'apply_pc_fix8_rank_reset.py', REPO)
run(PYTHON, ROOT / 'tools' / 'apply_pc_fix9_multistream_online.py', REPO)
print('=== FINAL PATCH CHAIN PASS: FIX7 + FIX8 + FIX9 ===')
