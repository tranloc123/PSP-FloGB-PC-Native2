from __future__ import annotations

from pathlib import Path
import subprocess
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: build_patch_chain_fix7.py <ppsspp_repo>")

ROOT = Path(__file__).resolve().parent
REPO = Path(sys.argv[1]).resolve()
PYTHON = sys.executable

def run(*args):
    cmd = [str(x) for x in args]
    print(">>>", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)

print("=== PSP FloGB Native Windows PATCH CHAIN + FIX7 ===")
run(PYTHON, ROOT / "build_patch_chain.py", REPO)
run(PYTHON, ROOT / "tools" / "apply_pc_fix7.py", REPO)
print("=== PATCH CHAIN + FIX7 PASS ===")
