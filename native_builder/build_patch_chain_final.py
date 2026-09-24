from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys

if len(sys.argv) != 2:
    raise SystemExit('Usage: build_patch_chain_final.py <ppsspp_repo>')

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
REPO = Path(sys.argv[1]).resolve()
PYTHON = sys.executable


def run(*args):
    cmd=[str(x) for x in args]
    print('>>>',' '.join(cmd),flush=True)
    subprocess.run(cmd,check=True)


def patch_package_json():
    pkg_path = PROJECT / 'package.json'
    if not pkg_path.exists():
        raise SystemExit(f'Missing package.json: {pkg_path}')

    try:
        pkg = json.loads(pkg_path.read_text(encoding='utf-8'))
    except Exception as e:
        raise SystemExit(f'Invalid package.json: {e}')

    scripts = pkg.setdefault('scripts', {})
    scripts['dist'] = 'electron-builder --win nsis portable --publish never'

    build = pkg.setdefault('build', {})
    win = build.setdefault('win', {})
    win['target'] = ['nsis', 'portable']

    # Remove ambiguous artifactName values that made NSIS/Portable collide.
    win.pop('artifactName', None)
    build.pop('artifactName', None)

    nsis = build.setdefault('nsis', {})
    nsis.setdefault('oneClick', False)
    nsis.setdefault('allowToChangeInstallationDirectory', True)
    nsis.setdefault('createDesktopShortcut', True)
    nsis.setdefault('shortcutName', 'PSP FloGB')
    nsis['artifactName'] = 'PSP-FloGB-Native-Unified-${version}-${arch}-Setup.${ext}'

    portable = build.setdefault('portable', {})
    portable['artifactName'] = 'PSP-FloGB-Native-Unified-${version}-${arch}-Portable.${ext}'

    pkg_path.write_text(
        json.dumps(pkg, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8'
    )

    # Hard verification before GitHub workflow reaches its own preflight.
    check = pkg_path.read_text(encoding='utf-8')
    required = (
        '--publish never',
        '-Setup.${ext}',
        '-Portable.${ext}',
    )
    missing = [x for x in required if x not in check]
    if missing:
        raise SystemExit(f'PACKAGE AUTO-PATCH FAILED, missing markers: {missing}')

    print('FINAL package.json auto-patch: PASS')
    print('  dist: electron-builder --win nsis portable --publish never')
    print('  artifacts: separate Setup / Portable names')


print('=== PSP FloGB FINAL ONE-BUILD PATCH CHAIN ===')
run(PYTHON, ROOT / 'build_patch_chain_fix7.py', REPO)
run(PYTHON, ROOT / 'tools' / 'apply_pc_fix8_rank_reset.py', REPO)
run(PYTHON, ROOT / 'tools' / 'apply_pc_fix9_multistream_online.py', REPO)

# Always repair Electron packaging in the GitHub Actions workspace.
# This intentionally does not depend on the repository package.json already
# being updated, so one forgotten upload cannot waste another build.
patch_package_json()

print('=== FINAL PATCH CHAIN PASS: FIX7 + FIX8 + FIX9 + PACKAGE ===')
