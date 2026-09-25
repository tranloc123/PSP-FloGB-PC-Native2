from __future__ import annotations
from pathlib import Path
import json, subprocess, sys

if len(sys.argv) != 2:
    raise SystemExit('Usage: build_patch_chain_final.py <ppsspp_repo>')
ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
REPO = Path(sys.argv[1]).resolve()
PYTHON = sys.executable

def run(*args):
    cmd=[str(x) for x in args]; print('>>>',' '.join(cmd),flush=True); subprocess.run(cmd,check=True)

def patch_package_json():
    p=PROJECT/'package.json'
    pkg=json.loads(p.read_text(encoding='utf-8'))
    pkg.setdefault('scripts',{})['dist']='electron-builder --win nsis portable --publish never'
    b=pkg.setdefault('build',{}); w=b.setdefault('win',{}); w['target']=['nsis','portable']; w.pop('artifactName',None); b.pop('artifactName',None)
    n=b.setdefault('nsis',{}); n.setdefault('oneClick',False); n.setdefault('allowToChangeInstallationDirectory',True); n.setdefault('createDesktopShortcut',True); n.setdefault('shortcutName','PSP FloGB'); n['artifactName']='PSP-FloGB-Native-Unified-${version}-${arch}-Setup.${ext}'
    b.setdefault('portable',{})['artifactName']='PSP-FloGB-Native-Unified-${version}-${arch}-Portable.${ext}'
    p.write_text(json.dumps(pkg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    s=p.read_text(encoding='utf-8')
    miss=[x for x in ('--publish never','-Setup.${ext}','-Portable.${ext}') if x not in s]
    if miss: raise SystemExit(f'PACKAGE AUTO-PATCH FAILED: {miss}')
    print('FINAL package.json auto-patch: PASS')

print('=== PSP FloGB FINAL ONE-BUILD PATCH CHAIN ===')
run(PYTHON, ROOT/'build_patch_chain_fix7.py', REPO)
run(PYTHON, ROOT/'tools'/'apply_pc_fix8_rank_reset.py', REPO)
run(PYTHON, ROOT/'tools'/'apply_pc_fix9_multistream_online.py', REPO)
run(PYTHON, ROOT/'tools'/'apply_pc_fix10_control_center.py', REPO)
patch_package_json()
print('=== FINAL PATCH CHAIN PASS: FIX7 + FIX8 + FIX9 + FIX10 + PACKAGE ===')
