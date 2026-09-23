from __future__ import annotations
from pathlib import Path
import subprocess, sys, shutil

if len(sys.argv) != 2:
    raise SystemExit('Usage: build_patch_chain.py <ppsspp_repo>')

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / 'tools'
BRANDING = ROOT / 'branding'
REPO = Path(sys.argv[1]).resolve()
PYTHON = sys.executable


def run(*args, cwd=None):
    cmd = [str(x) for x in args]
    print('>>>', ' '.join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def apply(name, *extra):
    run(PYTHON, TOOLS / name, REPO, *extra)


def must(rel):
    p = REPO / rel
    if not p.exists():
        raise SystemExit(f'Missing after patch: {rel}')
    return p

print('=== PSP FloGB native Windows patch chain ===')

# V0.3 -> V0.4.6 baseline used by the proven Android branch.
run(PYTHON, TOOLS / 'apply_psp_live_flogb_v0_3.py', REPO, BRANDING / 'PSP_Live_FloGB_icon_source.png')
for name in [
    'apply_psp_live_flogb_v0_4.py',
    'apply_psp_live_flogb_v0_4_1.py',
    'apply_psp_live_flogb_v0_4_2.py',
    'apply_psp_live_flogb_v0_4_3.py',
    'apply_psp_live_flogb_v0_4_4.py',
    'apply_psp_live_flogb_v0_4_5.py',
    'apply_psp_live_flogb_v0_4_6.py',
]:
    apply(name)

# Repair the old 0.5.0 patcher boundary exactly like the proven APK workflow.
run(PYTHON, TOOLS / 'fix_v0_5_0_controls_boundary.py', cwd=ROOT)
apply('apply_psp_live_flogb_v0_5_0.py')

# Cumulative PPSSPP API compatibility fixes from the later proven APK workflows.
header = must('SCBD/SCBDNativeHUDScreens.h')
s = header.read_text(encoding='utf-8')
line_replacements = {
    '        avatar->SetScale(0.72f);': '        avatar->SetSmall(true);',
    '            portrait->SetScale(0.62f);': '            portrait->SetSmall(true);',
    '        row->SetScale(static_cast<float>(cfg.rankFontPct) / 100.0f);': '        row->SetSmall(cfg.rankFontPct < 100);',
    '            row->SetScale(static_cast<float>(cfg.rankFontPct) / 100.0f);': '            row->SetSmall(cfg.rankFontPct < 100);',
}
lines = s.splitlines(keepends=True)
seen = {k: 0 for k in line_replacements}
out = []
for line in lines:
    bare = line.rstrip('\r\n')
    nl = line[len(bare):]
    if bare in line_replacements:
        seen[bare] += 1
        out.append(line_replacements[bare] + nl)
    else:
        out.append(line)
bad = {k:v for k,v in seen.items() if v != 1}
if bad:
    raise SystemExit(f'V0.5.0 UI compatibility marker mismatch: {bad}')
s = ''.join(out)
if s.count('UI::DialogResult') != 1 or s.count('UI::DR_OK') != 1:
    raise SystemExit('V0.5.0 DialogResult marker mismatch')
s = s.replace('UI::DialogResult', 'DialogResult').replace('UI::DR_OK', 'DR_OK')
if s.count('UI::ORIENT_HORIZONTAL') != 2:
    raise SystemExit('V0.5.0 orientation marker mismatch')
s = s.replace('UI::ORIENT_HORIZONTAL', 'ORIENT_HORIZONTAL')
header.write_text(s, encoding='utf-8')

debug = must('UI/DebugOverlay.cpp')
d = debug.read_text(encoding='utf-8')
old = '    const Config &cfg = Cfg();'
new = '    const auto &cfg = SCBDNativeHUD::Cfg();'
if d.count(old) == 1:
    d = d.replace(old, new, 1)
elif new not in d:
    raise SystemExit('V0.5.0 ambiguous Config hotfix marker missing')
debug.write_text(d, encoding='utf-8')

apply('apply_psp_live_flogb_v0_5_0_hotfix5.py')
apply('apply_psp_live_flogb_v0_5_1.py')
apply('apply_psp_live_flogb_v0_5_2.py')

# V0.5.3 character portrait atlas.
char_atlas = REPO / 'assets/scbd/characters/character_portraits_atlas.png'
char_atlas.parent.mkdir(parents=True, exist_ok=True)
run(PYTHON, TOOLS / 'build_scbd_character_atlas_v053.py', BRANDING / 'SCBD_character_sheet_v053.png', char_atlas)
apply('apply_psp_live_flogb_v0_5_3.py')

# V0.5.4a. The original v054 patcher produces the exact 1540x220 seven-tier atlas;
# the later workflow only renamed this lane to 054a after an asset/workflow correction.
rank_atlas = REPO / 'assets/scbd/rank_frames/rank_frames_atlas.png'
rank_atlas.parent.mkdir(parents=True, exist_ok=True)
run(PYTHON, TOOLS / 'build_scbd_rank_frame_atlas_v054a.py', BRANDING / 'SCBD_rank_frames_v054a.jpg', rank_atlas)
apply('apply_psp_live_flogb_v0_5_4a.py')

# V0.5.5 rendered rank numbers.
rank_nums = REPO / 'assets/scbd/rank_numbers/rank_numbers_atlas.png'
rank_nums.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(BRANDING / 'SCBD_rank_numbers_v055.png', rank_nums)
apply('apply_psp_live_flogb_v0_5_5.py')

# V0.5.6 clean RGBA frame atlas supersedes the temporary 0.5.4a asset.
shutil.copy2(BRANDING / 'SCBD_rank_frames_v056.png', rank_atlas)
apply('apply_psp_live_flogb_v0_5_6.py')

for name in [
    'apply_psp_live_flogb_v0_5_7.py',
    'apply_psp_live_flogb_v0_5_7a.py',
    'apply_psp_live_flogb_v0_5_7b.py',
    'apply_psp_live_flogb_v0_5_7c.py',
    'apply_psp_live_flogb_v0_5_7c3.py',
    'apply_psp_live_flogb_v0_5_7c4r1.py',
]:
    apply(name)

# Install split ranking/pick/font assets before the final cumulative 0.5.9E/HOTFIX8 patcher.
assets = {
    BRANDING / 'SCBD_character_portraits_ranking_v058c.png': REPO / 'assets/scbd/characters/character_portraits_atlas.png',
    BRANDING / 'SCBD_pick_portraits_exact_v058c.png': REPO / 'assets/scbd/winner_asset_v058c/pick_portraits_exact.png',
    BRANDING / 'SCBD_royal_unicode_atlas_v058c.png': REPO / 'assets/scbd/winner_asset_v058c/royal_unicode_atlas.png',
    BRANDING / 'SCBD_timer_digits_v058c.png': REPO / 'assets/scbd/winner_asset_v058c/timer_digits.png',
}
for src, dst in assets.items():
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

# This file is the final cumulative patch from the user-confirmed Android HOTFIX8 package.
apply('apply_psp_live_flogb_v0_5_8c.py')

# Windows compatibility adapter for V0.5.9A native live bridge.
run(PYTHON, TOOLS / 'patch_windows_native_bridge.py', REPO)

# ---------------------------------------------------------------------------
# Windows / pinned PPSSPP UI API compatibility
#
# The Android patch lineage contains two API forms that do not compile against
# the pinned Windows x64 PPSSPP source:
#   1) DrawBuffer::DrawTextW(...) -> DrawBuffer::DrawText(...)
#   2) LinearLayout::padding is UI::Margins, not UI::Padding.
#
# Keep this post-pass AFTER all APK-derived patches so later patchers cannot
# re-introduce the incompatible forms.
# ---------------------------------------------------------------------------
debug = must('UI/DebugOverlay.cpp')
d = debug.read_text(encoding='utf-8')

drawtextw_count = d.count('DrawTextW(')
if drawtextw_count:
    d = d.replace('DrawTextW(', 'DrawText(')

if 'DrawTextW(' in d:
    raise SystemExit('Windows UI compatibility failed: DrawTextW survived')

debug.write_text(d, encoding='utf-8')
print(f'Windows UI compat: DrawTextW -> DrawText: {drawtextw_count} occurrence(s)')

emu = must('UI/EmuScreen.cpp')
e = emu.read_text(encoding='utf-8')

padding_fixes = 0
for old in (
    'g_scbdInspectorPanel->padding = Padding(6);',
    'g_scbdInspectorPanel->padding = UI::Padding(6);',
):
    count = e.count(old)
    if count:
        e = e.replace(old, 'g_scbdInspectorPanel->padding = UI::Margins(6);')
        padding_fixes += count

if 'g_scbdInspectorPanel->padding = Padding(6);' in e or \
   'g_scbdInspectorPanel->padding = UI::Padding(6);' in e:
    raise SystemExit('Windows UI compatibility failed: SCBD inspector Padding survived')

emu.write_text(e, encoding='utf-8')
print(f'Windows UI compat: inspector Padding -> Margins: {padding_fixes} occurrence(s)')

# Structural preflight.
d = must('UI/DebugOverlay.cpp').read_text(encoding='utf-8')
required = [
    'SCBDVirtualInput::Process();',
    'DrawSCBDMatchTop5HUD',
    'WINNER FINAL V0.5.8C',
    'SCBDNativeLiveBridge::Process();',
    'DrawSCBDFinalHeroPortraitV059C',
]
missing = [m for m in required if m not in d]
if missing:
    raise SystemExit(f'Final source preflight missing: {missing}')

if 'DrawTextW(' in d:
    raise SystemExit('Final source preflight: Windows-incompatible DrawTextW still present')

emu_check = must('UI/EmuScreen.cpp').read_text(encoding='utf-8')
if 'g_scbdInspectorPanel->padding = Padding(6);' in emu_check or \
   'g_scbdInspectorPanel->padding = UI::Padding(6);' in emu_check:
    raise SystemExit('Final source preflight: Windows-incompatible inspector Padding still present')
for rel in [
    'SCBD/SCBDNativeWinner.h',
    'SCBD/SCBDNativeLiveBridge.h',
    'SCBD/SCBDNativeHUDScreens.h',
    'assets/scbd/characters/character_portraits_atlas.png',
    'assets/scbd/winner_asset_v058c/pick_portraits_exact.png',
]:
    must(rel)

info = must('PSP_LIVE_FLOGB_BUILD_INFO.txt')
with info.open('a', encoding='utf-8') as f:
    f.write('\nPSP FloGB Native Windows Engine V0.1\n')
    f.write('Port target: Windows x64 / MSVC / bundled in PSP FloGB Unified\n')
    f.write('Native bridge: cross-platform UDP 127.0.0.1:8796 with Winsock on Windows\n')

print('=== PATCH CHAIN PASS ===')
