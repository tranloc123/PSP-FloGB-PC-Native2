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

# On Windows, <windows.h> defines DrawText as a macro that expands to
# DrawTextW/DrawTextA.  That macro also rewrites C++ member calls such as
# ctx->Draw()->DrawText(...), which is why MSVC reports that DrawBuffer has
# no member named DrawTextW even though the source text says DrawText.
#
# Insert the undef AFTER every include, immediately before the first static
# function/SCBD helper in this translation unit.
macro_guard = '''#ifdef DrawText
#undef DrawText
#endif

'''
if '#undef DrawText' not in d:
    first_static = d.find('static ')
    if first_static < 0:
        raise SystemExit('Windows UI compatibility failed: cannot find post-include insertion point')
    d = d[:first_static] + macro_guard + d[first_static:]

if '#undef DrawText' not in d:
    raise SystemExit('Windows UI compatibility failed: DrawText macro guard was not inserted')

debug.write_text(d, encoding='utf-8')
print(f'Windows UI compat: DrawTextW -> DrawText source replacements: {drawtextw_count} occurrence(s)')
print('Windows UI compat: #undef DrawText inserted after includes')

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
if '#undef DrawText' not in d:
    raise SystemExit('Final source preflight: Windows DrawText macro guard missing')

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


# ---------------------------------------------------------------------------
# Unified PC gameplay hotfix 1.2.1
# - Hard anti-heal watchdog in the JS controller.
# - Intentional Gift Rule healing can temporarily raise the anti-heal floor.
# - Gift Rule TEST executes the real configured actions without adding BXH.
# - PSP button test console is injected into the Game tab.
# ---------------------------------------------------------------------------
def replace_exact_in_file(path: Path, old: str, new: str, label: str):
    src = path.read_text(encoding='utf-8')
    count = src.count(old)
    if count != 1:
        raise SystemExit(f'Unified 1.2.1 {label}: expected 1 occurrence, found {count}')
    path.write_text(src.replace(old, new, 1), encoding='utf-8')

controller = ROOT.parent / 'core' / 'controller-service.js'
main_js = ROOT.parent / 'main.js'
renderer_js = ROOT.parent / 'renderer' / 'app.js'

for p in (controller, main_js, renderer_js):
    if not p.exists():
        raise SystemExit(f'Unified 1.2.1 missing source file: {p}')

replace_exact_in_file(
    controller,
    """function u32ToFloat(v) {
  const b = Buffer.allocUnsafe(4);
  b.writeUInt32LE(v >>> 0, 0);
  return b.readFloatLE(0);
}
""",
    """function u32ToFloat(v) {
  const b = Buffer.allocUnsafe(4);
  b.writeUInt32LE(v >>> 0, 0);
  return b.readFloatLE(0);
}
function floatToU32(v) {
  const b = Buffer.allocUnsafe(4);
  b.writeFloatLE(Number(v) || 0, 0);
  return b.readUInt32LE(0);
}
""",
    'controller floatToU32'
)

replace_exact_in_file(
    controller,
    """  lastError: '',
  roundStartedAt: 0,
  hpLoopRunning: false,
""",
    """  lastError: '',
  roundStartedAt: 0,
  antiHealP1: null,
  antiHealP2: null,
  antiHealAllowP1Until: 0,
  antiHealAllowP2Until: 0,
  antiHealAllowP1Max: 0,
  antiHealAllowP2Max: 0,
  antiHealCorrections: 0,
  hpLoopRunning: false,
""",
    'controller antiheal fields'
)

replace_exact_in_file(
    controller,
    """    this.patchesApplied = false;
    this.patchOriginals.clear();
  },
""",
    """    this.patchesApplied = false;
    this.patchOriginals.clear();
    this.antiHealP1 = null;
    this.antiHealP2 = null;
    this.antiHealAllowP1Until = 0;
    this.antiHealAllowP2Until = 0;
  },
""",
    'controller disconnect antiheal reset'
)

replace_exact_in_file(
    controller,
    """        this.armed = true;
        this.phase = 'ARMED';
        this.roundStartedAt = now();
        log(`BATTLE ARMED | P1=${p1.toFixed(1)} P2=${p2.toFixed(1)}`);
""",
    """        this.armed = true;
        this.phase = 'ARMED';
        this.roundStartedAt = now();
        this.antiHealP1 = p1;
        this.antiHealP2 = p2;
        this.antiHealAllowP1Until = 0;
        this.antiHealAllowP2Until = 0;
        log(`BATTLE ARMED | P1=${p1.toFixed(1)} P2=${p2.toFixed(1)} | ANTI-HEAL WATCHDOG ON`);
""",
    'controller arm antiheal'
)

replace_exact_in_file(
    controller,
    """      try {
        const p1 = u32ToFloat(await debuggerClient.readU32(RAM.P1_HP, 500));
        const p2 = u32ToFloat(await debuggerClient.readU32(RAM.P2_HP, 500));
        this.lastP1HP = p1; this.lastP2HP = p2;
        if (Number.isFinite(p1) && p1 <= 0.5 && Number.isFinite(p2) && p2 > 0.5) {
          await this.handleKO('P1');
        } else if (Number.isFinite(p2) && p2 <= 0.5 && Number.isFinite(p1) && p1 > 0.5) {
          await this.handleKO('P2');
        } else if (Number.isFinite(p1) && Number.isFinite(p2) && p1 <= 0.5 && p2 <= 0.5) {
          // Extremely rare simultaneous zero: choose the side whose previous surviving HP is higher.
          await this.handleKO(p1 <= p2 ? 'P1' : 'P2');
        }
      } catch {}
""",
    """      try {
        let p1 = u32ToFloat(await debuggerClient.readU32(RAM.P1_HP, 500));
        let p2 = u32ToFloat(await debuggerClient.readU32(RAM.P2_HP, 500));
        const t = now();
        const eps = 0.05;

        // Hard anti-heal watchdog. The opcode patch remains the first line of defence.
        // This guard prevents any remaining game-side regeneration from raising HP.
        if (Number.isFinite(p1)) {
          if (!Number.isFinite(this.antiHealP1)) this.antiHealP1 = p1;
          if (p1 < this.antiHealP1) {
            this.antiHealP1 = p1;
          } else if (p1 > this.antiHealP1 + eps) {
            if (t <= this.antiHealAllowP1Until && p1 <= this.antiHealAllowP1Max + 0.5) {
              this.antiHealP1 = p1;
            } else {
              debuggerClient.writeU32(RAM.P1_HP, floatToU32(this.antiHealP1));
              p1 = this.antiHealP1;
              this.antiHealCorrections += 1;
            }
          }
        }

        if (Number.isFinite(p2)) {
          if (!Number.isFinite(this.antiHealP2)) this.antiHealP2 = p2;
          if (p2 < this.antiHealP2) {
            this.antiHealP2 = p2;
          } else if (p2 > this.antiHealP2 + eps) {
            if (t <= this.antiHealAllowP2Until && p2 <= this.antiHealAllowP2Max + 0.5) {
              this.antiHealP2 = p2;
            } else {
              debuggerClient.writeU32(RAM.P2_HP, floatToU32(this.antiHealP2));
              p2 = this.antiHealP2;
              this.antiHealCorrections += 1;
            }
          }
        }

        this.lastP1HP = p1; this.lastP2HP = p2;
        if (Number.isFinite(p1) && p1 <= 0.5 && Number.isFinite(p2) && p2 > 0.5) {
          await this.handleKO('P1');
        } else if (Number.isFinite(p2) && p2 <= 0.5 && Number.isFinite(p1) && p1 > 0.5) {
          await this.handleKO('P2');
        } else if (Number.isFinite(p1) && Number.isFinite(p2) && p1 <= 0.5 && p2 <= 0.5) {
          await this.handleKO(p1 <= p2 ? 'P1' : 'P2');
        }
      } catch {}
""",
    'controller hard antiheal watchdog'
)

replace_exact_in_file(
    controller,
    """  async handleKO(loser) {
""",
    """  allowHPIncrease(team, hp, ms = 1400) {
    team = normalizeTeam(team);
    hp = Number(hp);
    if (!team || !Number.isFinite(hp)) return false;
    const until = now() + Math.max(200, Math.min(3000, Number(ms) || 1400));
    if (team === 'P1') {
      this.antiHealAllowP1Until = until;
      this.antiHealAllowP1Max = Math.max(Number(this.antiHealP1) || 0, hp);
    } else {
      this.antiHealAllowP2Until = until;
      this.antiHealAllowP2Max = Math.max(Number(this.antiHealP2) || 0, hp);
    }
    return true;
  },

  async handleKO(loser) {
""",
    'controller allow intentional heal'
)

replace_exact_in_file(
    controller,
    """      error:game.lastError,
""",
    """      error:game.lastError,
      antiHealCorrections:game.antiHealCorrections,
      antiHealFloorP1:Number.isFinite(game.antiHealP1) ? Number(game.antiHealP1.toFixed(2)) : null,
      antiHealFloorP2:Number.isFinite(game.antiHealP2) ? Number(game.antiHealP2.toFixed(2)) : null,
""",
    'controller expose antiheal state'
)

replace_exact_in_file(
    controller,
    """  if (req.method === 'POST' && pathname === '/api/test/winner') {
""",
    """  if (req.method === 'POST' && pathname === '/api/antiheal/allow') {
    const b = await readBody(req);
    const ok = game.allowHPIncrease(b.team, b.hp, b.ms);
    if (!ok) throw new Error('antiheal allow requires team=P1/P2 and numeric hp');
    return sendJson(res, 200, {ok:true});
  }
  if (req.method === 'POST' && pathname === '/api/test/winner') {
""",
    'controller antiheal API'
)

replace_exact_in_file(
    main_js,
    """    await ppssppCommand(async api=>{ const raw=await api.readU32(HP[target]); let hp=u32ToFloat(raw);
      if(type==='heal_team') hp=Math.min(cap,hp+amount); else if(type==='damage_enemy') hp=Math.max(0,hp-amount); else hp=Math.max(0,Math.min(cap,Number(action.value??action.amount)||0));
      api.writeU32(HP[target],floatToU32(hp)); }); return;
""",
    """    await ppssppCommand(async api=>{ const raw=await api.readU32(HP[target]); const before=u32ToFloat(raw); let hp=before;
      if(type==='heal_team') hp=Math.min(cap,hp+amount); else if(type==='damage_enemy') hp=Math.max(0,hp-amount); else hp=Math.max(0,Math.min(cap,Number(action.value??action.amount)||0));
      if(hp > before + 0.01) await postApi('/api/antiheal/allow',{team:target,hp,ms:1600});
      api.writeU32(HP[target],floatToU32(hp)); }); return;
""",
    'main intentional heal allowance'
)

replace_exact_in_file(
    main_js,
    """ipcMain.handle('test-gift',async(_,x)=>{await postApi('/api/test/team',{username:x.username||'TEST',team:x.team||'P1'});return postApi('/api/test/gift',{username:x.username||'TEST',points:Number(x.points)||0});});
""",
    """ipcMain.handle('test-gift',async(_,x)=>{await postApi('/api/test/team',{username:x.username||'TEST',team:x.team||'P1'});return postApi('/api/test/gift',{username:x.username||'TEST',points:Number(x.points)||0});});
ipcMain.handle('test-rule-gift',async(_,x={})=>{
  const giftId=String(x.giftId||'').trim();
  if(!giftId) throw new Error('Chưa chọn quà để test.');
  const team=String(x.team||'P1').toUpperCase()==='P2'?'P2':'P1';
  const units=Math.max(1,Math.min(99,Number(x.units)||1));
  const learnedDb=readJson(LEARNED_FILE,{});
  const learnedGift=learnedDb[giftId]||{};
  const fakeEvt={
    type:'gift',
    units,
    diamonds:Number(learnedGift.diamondCount||0)*units,
    user:{id:'TEST_RULE_USER',uniqueId:'TEST_RULE',nickname:'TEST RULE',avatar:''},
    payload:{
      giftId,
      giftName:String(x.giftName||learnedGift.name||giftId),
      diamondCount:Number(learnedGift.diamondCount||0),
      repeatCount:units
    }
  };
  const rule=findGiftRule(fakeEvt);
  if(!rule) throw new Error('Quà này chưa được Add Rule.');
  sendLog(`TEST GIFT ${fakeEvt.payload.giftName} x${units} -> ${team}`);
  await applyRuleActions(rule,team,fakeEvt);
  return {ok:true,giftId,name:fakeEvt.payload.giftName,team,units,actions:rule.actions||[]};
});
""",
    'main real Gift Rule test'
)

renderer_inject = r"""function installGameTestConsole(){
  if(document.getElementById('flogbTestConsole'))return;
  const game=document.getElementById('game'); if(!game)return;
  const card=document.createElement('div'); card.className='card'; card.id='flogbTestConsole';
  card.innerHTML=`
    <h3>TEST GAME / QUÀ</h3>
    <p class="muted">Nút PSP gửi input thẳng vào FloGB Native Engine. TEST QUÀ chạy đúng Rule đã lưu và không cộng BXH.</p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
      <div>
        <b>PSP Button Test</b>
        <div class="row" style="margin-top:10px;flex-wrap:wrap">
          <button data-psp="l">L</button><button data-psp="r">R</button>
          <button data-psp="up">UP</button><button data-psp="down">DOWN</button>
          <button data-psp="left">LEFT</button><button data-psp="right">RIGHT</button>
          <button data-psp="triangle">TRIANGLE</button><button data-psp="circle">CIRCLE</button>
          <button data-psp="cross">CROSS</button><button data-psp="square">SQUARE</button>
          <button data-psp="start">START</button><button data-psp="select">SELECT</button>
        </div>
      </div>
      <div>
        <b>Gift Rule Test</b>
        <div class="row" style="margin-top:10px;flex-wrap:wrap">
          <select id="testGiftSelect" style="min-width:220px"></select>
          <select id="testGiftTeam"><option value="P1">Team P1</option><option value="P2">Team P2</option></select>
          <input id="testGiftUnits" type="number" min="1" max="99" value="1" style="width:80px" title="So luong qua">
          <button id="btnTestGiftRule" class="primary">TEST QUA</button>
        </div>
      </div>
    </div>
    <div id="gameTestStatus" class="muted" style="margin-top:10px">San sang.</div>
  `;
  game.appendChild(card);
  card.querySelectorAll('[data-psp]').forEach(btn=>btn.onclick=async()=>{
    const status=document.getElementById('gameTestStatus');
    try{
      await ipcRenderer.invoke('ppsspp-tap',btn.dataset.psp);
      status.textContent='Da gui nut PSP: '+btn.dataset.psp.toUpperCase();
    }catch(e){
      status.textContent='Loi nut PSP: '+(e?.message||e);
    }
  });
  document.getElementById('btnTestGiftRule').onclick=async()=>{
    const status=document.getElementById('gameTestStatus');
    const giftId=document.getElementById('testGiftSelect').value;
    const team=document.getElementById('testGiftTeam').value;
    const units=Number(document.getElementById('testGiftUnits').value)||1;
    if(!giftId){status.textContent='Chua co qua da Add Rule de test.';return;}
    try{
      const r=await ipcRenderer.invoke('test-rule-gift',{giftId,team,units});
      status.textContent=`TEST OK: ${r.name} x${r.units} -> ${r.team}`;
    }catch(e){
      status.textContent='TEST FAIL: '+(e?.message||e);
    }
  };
}
function refreshTestGiftSelect(){
  const sel=document.getElementById('testGiftSelect'); if(!sel)return;
  const prev=sel.value;
  const rows=giftRows().filter(g=>g.configured);
  sel.innerHTML=rows.map(g=>`<option value="${esc(g.giftId)}">${esc(g.name)} [${esc(g.giftId)}]</option>`).join('');
  if(rows.some(g=>String(g.giftId)===String(prev)))sel.value=prev;
}
"""

replace_exact_in_file(
    renderer_js,
    """async function init(){const s=await ipcRenderer.invoke('get-settings');""",
    renderer_inject + """async function init(){installGameTestConsole();const s=await ipcRenderer.invoke('get-settings');""",
    'renderer inject test console'
)

replace_exact_in_file(
    renderer_js,
    """const eng=await ipcRenderer.invoke('get-engine-info');$('engineInfo').textContent=eng.bundledExists?`NATIVE FLOGB ENGINE: ${eng.bundledPath}`:`NATIVE ENGINE MISSING: bản build này không hợp lệ, hãy build lại bằng workflow Native Unified.`;renderGiftTable();}""",
    """const eng=await ipcRenderer.invoke('get-engine-info');$('engineInfo').textContent=eng.bundledExists?`NATIVE FLOGB ENGINE: ${eng.bundledPath}`:`NATIVE ENGINE MISSING: bản build này không hợp lệ, hãy build lại bằng workflow Native Unified.`;renderGiftTable();refreshTestGiftSelect();}""",
    'renderer init gift tester'
)

replace_exact_in_file(
    renderer_js,
    """document.querySelectorAll('.removeRule').forEach(b=>b.onclick=()=>{const id=b.closest('tr').dataset.id;delete giftRules.rules[id];renderGiftTable();});}""",
    """document.querySelectorAll('.removeRule').forEach(b=>b.onclick=()=>{const id=b.closest('tr').dataset.id;delete giftRules.rules[id];renderGiftTable();refreshTestGiftSelect();});refreshTestGiftSelect();}""",
    'renderer refresh gift tester'
)

replace_exact_in_file(
    renderer_js,
    """giftRules=await ipcRenderer.invoke('save-rules',giftRules);alert('Đã lưu Game Rule. Không cần build lại EXE.');};""",
    """giftRules=await ipcRenderer.invoke('save-rules',giftRules);refreshTestGiftSelect();alert('Đã lưu Game Rule.');};""",
    'renderer save gift tester'
)

print('Unified PC gameplay hotfix 1.2.1 source patch applied')


# ---------------------------------------------------------------------------
# Unified PC hotfix 1.2.2
# 1) Gauge anti-flicker patch 0x08836E18 from confirmed Android baseline.
# 2) Explicit DOWN -> hold -> UP for test buttons / Gift Rule input.
# 3) Replace native mock rankings with runtime real ranking transport.
# ---------------------------------------------------------------------------

project_root = ROOT.parent
controller = project_root / 'core' / 'controller-service.js'
main_js = project_root / 'main.js'
renderer_js = project_root / 'renderer' / 'app.js'
native_sender = project_root / 'core' / 'native_sender_v059.js'

# ---- 1. Gauge / HP visual sync ----------------------------------------------
replace_exact_in_file(
    controller,
    '''  0x08835D50,
  0x08816178,
''',
    '''  0x08835D50,
  0x08836E18, // Android V1.4B/V1.6 confirmed gauge anti-flicker patch
  0x08816178,
''',
    'add gauge anti-flicker opcode'
)

# ---- 2. Input must release before the temporary debugger socket closes -------
replace_exact_in_file(
    main_js,
    '''tap:(button,duration=2)=>ws.send(JSON.stringify({event:'input.buttons.press',ticket:ticket++,button,duration}))''',
    '''tap:async(button,duration=2)=>{
        button=button==='l'?'ltrigger':button==='r'?'rtrigger':button;
        const holdMs=Math.max(45,Math.min(140,Number(duration||1)*35));
        ws.send(JSON.stringify({event:'input.buttons.send',ticket:ticket++,buttons:{[button]:true}}));
        await new Promise(r=>setTimeout(r,holdMs));
        ws.send(JSON.stringify({event:'input.buttons.send',ticket:ticket++,buttons:{[button]:false}}));
        await new Promise(r=>setTimeout(r,45));
      }''',
    'explicit PSP button down/up'
)

replace_exact_in_file(
    main_js,
    '''await ppssppCommand(async api=>{for(let i=0;i<count;i++){api.tap(button,2);await new Promise(r=>setTimeout(r,gap));}}); return;''',
    '''await ppssppCommand(async api=>{for(let i=0;i<count;i++){await api.tap(button,2);await new Promise(r=>setTimeout(r,gap));}}); return;''',
    'await Gift Rule button release'
)

replace_exact_in_file(
    renderer_js,
    '''<button data-psp="l">L</button><button data-psp="r">R</button>''',
    '''<button data-psp="ltrigger">L</button><button data-psp="rtrigger">R</button>''',
    'correct L/R debugger button names'
)

# ---- 3. Runtime native ranking data -----------------------------------------
rank_data_h = r'''#pragma once

#include <array>
#include <cstdint>
#include <string>

namespace SCBDNativeRankData {

enum class List {
    MATCH_P1 = 0,
    MATCH_P2 = 1,
    WEEK = 2,
    MONTH = 3,
    STREAK = 4,
    UNKNOWN = 99,
};

struct Row {
    bool valid = false;
    std::string name;
    std::string initial;
    std::string avatarUrl;
    int score = 0;
    int current = 0;
    int best = 0;
    uint32_t color = 0xE0606875;
};

inline uint32_t ColorForName(const std::string &name) {
    uint32_t h = 2166136261u;
    for (unsigned char c : name) {
        h ^= c;
        h *= 16777619u;
    }
    const uint32_t r = 72u + ((h >> 0) & 0x7Fu);
    const uint32_t g = 72u + ((h >> 8) & 0x7Fu);
    const uint32_t b = 72u + ((h >> 16) & 0x7Fu);
    return 0xE0000000u | (b << 16) | (g << 8) | r;
}

inline std::string InitialFor(const std::string &name) {
    if (name.empty())
        return "?";
    unsigned char c = static_cast<unsigned char>(name[0]);
    if (c < 0x80)
        return std::string(1, static_cast<char>(c));
    return "*";
}

inline List ParseList(const std::string &s) {
    if (s == "MATCH_P1") return List::MATCH_P1;
    if (s == "MATCH_P2") return List::MATCH_P2;
    if (s == "WEEK") return List::WEEK;
    if (s == "MONTH") return List::MONTH;
    if (s == "STREAK") return List::STREAK;
    return List::UNKNOWN;
}

inline std::array<Row, 100> &Rows(List list) {
    static std::array<Row, 100> matchP1{};
    static std::array<Row, 100> matchP2{};
    static std::array<Row, 100> week{};
    static std::array<Row, 100> month{};
    static std::array<Row, 100> streak{};
    switch (list) {
    case List::MATCH_P1: return matchP1;
    case List::MATCH_P2: return matchP2;
    case List::MONTH: return month;
    case List::STREAK: return streak;
    case List::WEEK:
    default: return week;
    }
}

inline std::array<std::array<Row, 3>, 28> &CharacterRows() {
    static std::array<std::array<Row, 3>, 28> rows{};
    return rows;
}

inline void Clear(List list) {
    if (list == List::UNKNOWN)
        return;
    for (auto &r : Rows(list))
        r = Row{};
}

inline void ClearCharacters() {
    for (auto &ch : CharacterRows())
        for (auto &r : ch)
            r = Row{};
}

inline void SetRow(List list, int index, const std::string &name, int score,
                   const std::string &avatarUrl, int current, int best) {
    if (list == List::UNKNOWN || index < 0 || index >= 100)
        return;
    Row &r = Rows(list)[index];
    r.valid = true;
    r.name = name;
    r.initial = InitialFor(name);
    r.avatarUrl = avatarUrl;
    r.score = score;
    r.current = current;
    r.best = best;
    r.color = ColorForName(name);
}

inline void SetCharacterRow(int characterIndex, int slot, const std::string &name,
                            int score, const std::string &avatarUrl) {
    if (characterIndex < 0 || characterIndex >= 28 || slot < 0 || slot >= 3)
        return;
    Row &r = CharacterRows()[characterIndex][slot];
    r.valid = true;
    r.name = name;
    r.initial = InitialFor(name);
    r.avatarUrl = avatarUrl;
    r.score = score;
    r.color = ColorForName(name);
}

}  // namespace SCBDNativeRankData
'''
(REPO / 'SCBD' / 'SCBDNativeRankData.h').write_text(rank_data_h, encoding='utf-8')

# Extend UDP bridge.
bridge_path = must('SCBD/SCBDNativeLiveBridge.h')
b = bridge_path.read_text(encoding='utf-8')
bridge_inc_anchor = '#include "SCBD/SCBDNativeWinner.h"\n'
rank_inc = '#include "SCBD/SCBDNativeRankData.h"\n'
if rank_inc not in b:
    if bridge_inc_anchor not in b:
        raise SystemExit('Unified 1.2.2 bridge include anchor missing')
    b = b.replace(bridge_inc_anchor, bridge_inc_anchor + rank_inc, 1)

rank_commands = r'''
    if (cmd == "RANK_CLEAR") {
        if (parts.size() < 2) {
            Reply(s, peer, peerLen, "RANK_CLEAR", false, "bad-fields");
            return;
        }
        const auto list = SCBDNativeRankData::ParseList(parts[1]);
        if (list == SCBDNativeRankData::List::UNKNOWN) {
            Reply(s, peer, peerLen, "RANK_CLEAR", false, "bad-list");
            return;
        }
        SCBDNativeRankData::Clear(list);
        Reply(s, peer, peerLen, "RANK_CLEAR", true);
        return;
    }

    if (cmd == "RANK_ROW") {
        if (parts.size() < 8) {
            Reply(s, peer, peerLen, "RANK_ROW", false, "bad-fields");
            return;
        }
        const auto list = SCBDNativeRankData::ParseList(parts[1]);
        const int index = ParseInt(parts[2], -1);
        if (list == SCBDNativeRankData::List::UNKNOWN || index < 0 || index >= 100) {
            Reply(s, peer, peerLen, "RANK_ROW", false, "bad-index");
            return;
        }
        SCBDNativeRankData::SetRow(
            list, index, UrlDecode(parts[3]),
            std::max(0, ParseInt(parts[4], 0)),
            UrlDecode(parts[5]),
            std::max(0, ParseInt(parts[6], 0)),
            std::max(0, ParseInt(parts[7], 0))
        );
        Reply(s, peer, peerLen, "RANK_ROW", true);
        return;
    }

    if (cmd == "CHAR_CLEAR") {
        SCBDNativeRankData::ClearCharacters();
        Reply(s, peer, peerLen, "CHAR_CLEAR", true);
        return;
    }

    if (cmd == "CHAR_ROW") {
        if (parts.size() < 6) {
            Reply(s, peer, peerLen, "CHAR_ROW", false, "bad-fields");
            return;
        }
        const int characterIndex = ParseInt(parts[1], -1);
        const int slot = ParseInt(parts[2], -1);
        if (characterIndex < 0 || characterIndex >= 28 || slot < 0 || slot >= 3) {
            Reply(s, peer, peerLen, "CHAR_ROW", false, "bad-index");
            return;
        }
        SCBDNativeRankData::SetCharacterRow(
            characterIndex, slot, UrlDecode(parts[3]),
            std::max(0, ParseInt(parts[4], 0)),
            UrlDecode(parts[5])
        );
        Reply(s, peer, peerLen, "CHAR_ROW", true);
        return;
    }

'''
# patch_windows_native_bridge.py rewrites the bridge into a compact Windows form,
# so do not depend on the old Android multi-line "unknown command" block.
# Insert ranking handlers immediately before the final unknown-command fallback.
if 'if (cmd == "RANK_ROW")' not in b:
    compact_anchor = '    ++s.errors; s.lastError = "unknown command: " + cmd; Reply(s, peer, peerLen, cmd, false, "unknown-command");\n'
    android_anchor = '''    ++s.errors;
    s.lastError = std::string("unknown command: ") + cmd;
    Reply(s, peer, peerLen, cmd, false, "unknown-command");
'''
    if compact_anchor in b:
        b = b.replace(compact_anchor, rank_commands + compact_anchor, 1)
    elif android_anchor in b:
        b = b.replace(android_anchor, rank_commands + android_anchor, 1)
    else:
        # Last-resort structural anchor: place handlers before HandlePacket closes.
        fallback = '\n}\n\ninline void Process() {\n'
        if fallback not in b:
            raise SystemExit('Unified 1.2.2 bridge command anchor missing: neither Windows nor Android fallback found')
        b = b.replace(fallback, '\n' + rank_commands + fallback, 1)
bridge_path.write_text(b, encoding='utf-8')

# Sender methods.
ns = native_sender.read_text(encoding='utf-8')
sender_insert = r'''
async function sendRankSnapshot(list, rows, limit = 100) {
  const safeList = String(list || '').toUpperCase();
  await sendRaw(`RANK_CLEAR\t${safeList}`);
  const src = Array.isArray(rows) ? rows.slice(0, limit) : [];
  for (let i = 0; i < src.length; i++) {
    const r = src[i] || {};
    await sendRaw(
      `RANK_ROW\t${safeList}\t${i}\t${enc(r.name || r.username || r.uniqueId || '')}` +
      `\t${Math.max(0, Number(r.score) || 0)}\t${enc(r.avatar || '')}` +
      `\t${Math.max(0, Number(r.current) || 0)}\t${Math.max(0, Number(r.best) || 0)}`
    );
  }
}

async function sendCharacterSnapshot(characters) {
  await sendRaw('CHAR_CLEAR');
  const groups = Array.isArray(characters) ? characters.slice(0, 28) : [];
  for (let ci = 0; ci < groups.length; ci++) {
    const rows = Array.isArray(groups[ci]) ? groups[ci].slice(0, 3) : [];
    for (let slot = 0; slot < rows.length; slot++) {
      const r = rows[slot] || {};
      await sendRaw(
        `CHAR_ROW\t${ci}\t${slot}\t${enc(r.name || r.username || r.uniqueId || '')}` +
        `\t${Math.max(0, Number(r.score) || 0)}\t${enc(r.avatar || '')}`
      );
    }
  }
}

'''
if 'async function sendRankSnapshot(' not in ns:
    anchor = 'function getStatus() {\n'
    if anchor not in ns:
        raise SystemExit('Unified 1.2.2 native sender anchor missing')
    ns = ns.replace(anchor, sender_insert + anchor, 1)

exports_anchor = '''  sendCancel,
  getStatus,
};'''
if 'sendRankSnapshot,' not in ns:
    if exports_anchor not in ns:
        raise SystemExit('Unified 1.2.2 native sender exports anchor missing')
    ns = ns.replace(
        exports_anchor,
        '''  sendCancel,
  sendRankSnapshot,
  sendCharacterSnapshot,
  getStatus,
};''',
        1
    )
native_sender.write_text(ns, encoding='utf-8')

# Real streaks.
replace_exact_in_file(
    controller,
    '''      score: 0,
      gifts: 0,
      joinedAt: now(),
''',
    '''      score: 0,
      gifts: 0,
      currentStreak: 0,
      bestStreak: 0,
      joinedAt: now(),
''',
    'controller real streak member fields'
)

replace_exact_in_file(
    controller,
    '''      gifts:m.gifts,
    }));
}

function top1(team) {
''',
    '''      gifts:m.gifts,
      currentStreak:m.currentStreak || 0,
      bestStreak:m.bestStreak || 0,
    }));
}

function streakLeaderboard(limit = 100) {
  return [...session.members.values()]
    .filter(m => !!m.team)
    .sort((a,b) =>
      ((b.bestStreak || 0) - (a.bestStreak || 0)) ||
      ((b.currentStreak || 0) - (a.currentStreak || 0)) ||
      ((b.score || 0) - (a.score || 0)) ||
      (a.joinedAt - b.joinedAt)
    )
    .slice(0, limit)
    .map(m => ({
      key:m.key, username:m.displayName, avatar:m.avatar,
      current:m.currentStreak || 0, best:m.bestStreak || 0,
      score:m.bestStreak || 0,
    }));
}

function top1(team) {
''',
    'controller real streak leaderboard'
)

replace_exact_in_file(
    controller,
    '''    session.rounds += 1;
    session.lastMatch = { loser, winnerTeam, at:now(), round:session.rounds };
''',
    '''    for (const m of session.members.values()) {
      if (!m.team) continue;
      if (m.team === winnerTeam) {
        m.currentStreak = (m.currentStreak || 0) + 1;
        m.bestStreak = Math.max(m.bestStreak || 0, m.currentStreak);
      } else {
        m.currentStreak = 0;
      }
    }
    session.rounds += 1;
    session.lastMatch = { loser, winnerTeam, at:now(), round:session.rounds };
''',
    'controller update real streak on KO'
)

replace_exact_in_file(
    controller,
    '''      leaderboardP2:leaderboard('P2', 20),
      activePick:a,
''',
    '''      leaderboardP2:leaderboard('P2', 20),
      leaderboardStreak:streakLeaderboard(100),
      activePick:a,
''',
    'controller expose real streak'
)

# Main rank sync.
replace_exact_in_file(
    main_js,
    '''const WebSocket = require('ws');
''',
    '''const WebSocket = require('ws');
const nativeSender = require('./core/native_sender_v059');
''',
    'main native rank sender import'
)

main_rank_helpers = r'''
let nativeRankPushBusy = false;
const nativeRankHashes = new Map();
let lastCharacterPickToken = '';

const NATIVE_CHARACTER_ORDER = [
  'ALGOL','AMY','ASTAROTH','CASSANDRA','CERVANTES','DAMPIERRE','HILDE',
  'IVY','KILIK','KRATOS','LIZARDMAN','MAXI','MITSURUGI','NIGHTMARE',
  'RAPHAEL','ROCK','SEONG_MI_NA','SETSUKA','SIEGFRIED','SOPHITIA','TAKI',
  'TALIM','TIRA','VOLDO','XIANGHUA','YOSHIMITSU','YUN_SEONG','ZASALAMEL'
];
function normCharacter(v){return String(v||'').toUpperCase().replace(/[^A-Z0-9]/g,'');}
function scoreSince(u, days){
  const cut=new Date(); cut.setHours(0,0,0,0); cut.setDate(cut.getDate()-(days-1));
  let total=0;
  for(const [d,v] of Object.entries(u.daily||{})){
    const dt=new Date(d+'T00:00:00');
    if(dt>=cut) total+=Number(v||0);
  }
  return total;
}
function persistentRows(days){
  const db=readJson(RANKINGS_FILE,{users:{}});
  return Object.values(db.users||{}).map(u=>({
    name:u.uniqueId||u.nickname||u.id||'viewer',
    avatar:u.avatar||'', score:scoreSince(u,days),
  })).filter(r=>r.score>0).sort((a,b)=>b.score-a.score).slice(0,100);
}
function characterRows(){
  const db=readJson(RANKINGS_FILE,{users:{}});
  return NATIVE_CHARACTER_ORDER.map(ch=>{
    const key=normCharacter(ch);
    return Object.values(db.users||{}).map(u=>({
      name:u.uniqueId||u.nickname||u.id||'viewer',
      avatar:u.avatar||'', score:Number((u.characters||{})[key]||0),
    })).filter(r=>r.score>0).sort((a,b)=>b.score-a.score).slice(0,3);
  });
}
function trackCharacterPick(state){
  const a=state?.session?.activePick;
  if(!a || a.status!=='success' || !a.top1Key || !a.character)return;
  const token=[state?.session?.rounds||0,a.top1Key,a.character,a.decisionAt||0].join('|');
  if(token===lastCharacterPickToken)return;
  lastCharacterPickToken=token;
  const db=readJson(RANKINGS_FILE,{users:{}});
  const id=String(a.top1Key);
  const u=db.users[id]||{id,uniqueId:a.top1Name||id,nickname:'',avatar:a.top1Avatar||'',total:0,gifts:0,likes:0,daily:{},characters:{}};
  u.characters=u.characters||{};
  const ck=normCharacter(a.character);
  u.characters[ck]=Number(u.characters[ck]||0)+1;
  db.users[id]=u;
  writeJson(RANKINGS_FILE,db);
}
async function pushRankIfChanged(list,rows){
  const sig=JSON.stringify(rows);
  if(nativeRankHashes.get(list)===sig)return;
  nativeRankHashes.set(list,sig);
  await nativeSender.sendRankSnapshot(list,rows);
}
async function pushRealNativeRankings(state){
  if(nativeRankPushBusy)return;
  nativeRankPushBusy=true;
  try{
    const ses=state?.session||{};
    await pushRankIfChanged('MATCH_P1',(ses.leaderboardP1||[]).slice(0,10).map(r=>({name:r.username,avatar:r.avatar,score:r.score})));
    await pushRankIfChanged('MATCH_P2',(ses.leaderboardP2||[]).slice(0,10).map(r=>({name:r.username,avatar:r.avatar,score:r.score})));
    await pushRankIfChanged('STREAK',(ses.leaderboardStreak||[]).slice(0,100).map(r=>({name:r.username,avatar:r.avatar,score:r.best,current:r.current,best:r.best})));
    await pushRankIfChanged('WEEK',persistentRows(7));
    await pushRankIfChanged('MONTH',persistentRows(30));
    const chars=characterRows();
    const csig=JSON.stringify(chars);
    if(nativeRankHashes.get('CHAR')!==csig){
      nativeRankHashes.set('CHAR',csig);
      await nativeSender.sendCharacterSnapshot(chars);
    }
  }catch(e){
    sendLog('Native ranking sync: '+e.message,'error');
  }finally{
    nativeRankPushBusy=false;
  }
}

'''
m = main_js.read_text(encoding='utf-8')
if 'function pushRealNativeRankings(' not in m:
    rank_anchor = "function stableName(user={}){ return String(user.uniqueId||user.nickname||user.id||'viewer'); }\n"
    if rank_anchor not in m:
        raise SystemExit('Unified 1.2.2 main rank helper anchor missing')
    m = m.replace(rank_anchor, rank_anchor + main_rank_helpers, 1)
    main_js.write_text(m, encoding='utf-8')

replace_exact_in_file(
    main_js,
    '''      lastControllerState=await getState();
      if(win && !win.isDestroyed()) win.webContents.send('controller-state',lastControllerState);
''',
    '''      lastControllerState=await getState();
      trackCharacterPick(lastControllerState);
      pushRealNativeRankings(lastControllerState).catch(()=>{});
      if(win && !win.isDestroyed()) win.webContents.send('controller-state',lastControllerState);
''',
    'main push real native ranking data'
)

# Native in-game match/ranking UI.
debug = must('UI/DebugOverlay.cpp')
d = debug.read_text(encoding='utf-8')
rank_include = '#include "SCBD/SCBDNativeRankData.h"\n'
if rank_include not in d:
    inc_anchor = '#include "SCBD/SCBDNativeLiveBridge.h"\n'
    if inc_anchor not in d:
        raise SystemExit('Unified 1.2.2 DebugOverlay rank include anchor missing')
    d = d.replace(inc_anchor, inc_anchor + rank_include, 1)

mock_start = d.find('static const SCBDMatchMockRow kSCBDP1MockRows[] = {')
mock_end = d.find('static void BuildSCBDTop5(', mock_start)
if mock_start < 0 or mock_end < 0:
    raise SystemExit('Unified 1.2.2 match mock block not found')
live_match_helper = r'''static int BuildSCBDLiveRows(
    SCBDNativeRankData::List list,
    SCBDMatchMockRow out[10]
) {
    int count = 0;
    const auto &src = SCBDNativeRankData::Rows(list);
    for (const auto &r : src) {
        if (!r.valid) continue;
        if (count >= 10) break;
        out[count] = SCBDMatchMockRow{
            r.initial.c_str(), r.name.c_str(), r.score, r.color
        };
        ++count;
    }
    return count;
}

'''
d = d[:mock_start] + live_match_helper + d[mock_end:]

old_build = '''    BuildSCBDTop5(kSCBDP1MockRows, static_cast<int>(sizeof(kSCBDP1MockRows) / sizeof(kSCBDP1MockRows[0])), p1Top);
    BuildSCBDTop5(kSCBDP2MockRows, static_cast<int>(sizeof(kSCBDP2MockRows) / sizeof(kSCBDP2MockRows[0])), p2Top);
'''
new_build = '''    SCBDMatchMockRow p1Live[10];
    SCBDMatchMockRow p2Live[10];
    const int p1Count = BuildSCBDLiveRows(SCBDNativeRankData::List::MATCH_P1, p1Live);
    const int p2Count = BuildSCBDLiveRows(SCBDNativeRankData::List::MATCH_P2, p2Live);
    BuildSCBDTop5(p1Live, p1Count, p1Top);
    BuildSCBDTop5(p2Live, p2Count, p2Top);
'''
if old_build not in d:
    raise SystemExit('Unified 1.2.2 match mock usage not found')
d = d.replace(old_build, new_build)

rank_page_start = d.find('    if (page == Panel::RANK) {\n')
rank_page_end = d.find('    if (page == Panel::DEV) {\n', rank_page_start)
if rank_page_start < 0 or rank_page_end < 0:
    raise SystemExit('Unified 1.2.2 in-game rank page block not found')

real_rank_page = r'''    if (page == Panel::RANK) {
        static const char *tabs[4] = {"TOP TUAN","TOP THANG","TOP NHAN VAT","CHUOI WIN"};
        const int active = RankTab();
        for (int i = 0; i < 4; ++i)
            DrawSCBDLayerButton(ctx, font, RankTabRect(i, sw, sh), tabs[i], i == active ? 0xEE9B7427 : 0xCC2A3240);

        const Rect list = RankListRect(sw, sh);
        const float rowH = 36.0f;
        const float scroll = RankScroll();
        const int total = RankRowCount();
        const int first = std::max(0, static_cast<int>(scroll / rowH));
        const float yoff = -(scroll - first * rowH);
        static const char *chars[28] = {
            "ALGOL","AMY","ASTAROTH","CASSANDRA","CERVANTES","DAMPIERRE","HILDE",
            "IVY","KILIK","KRATOS","LIZARDMAN","MAXI","MITSURUGI","NIGHTMARE",
            "RAPHAEL","ROCK","SEONG_MI_NA","SETSUKA","SIEGFRIED","SOPHITIA","TAKI",
            "TALIM","TIRA","VOLDO","XIANGHUA","YOSHIMITSU","YUN_SEONG","ZASALAMEL"
        };

        ctx->Flush();
        ctx->BeginNoTex();
        ctx->Draw()->Rect(list.x, list.y, list.w, list.h, 0xB810141C);
        ctx->Flush();
        ctx->Begin();
        ctx->BindFontTexture();

        const auto listType =
            active == 0 ? SCBDNativeRankData::List::WEEK :
            active == 1 ? SCBDNativeRankData::List::MONTH :
                          SCBDNativeRankData::List::STREAK;
        const auto &liveRows = SCBDNativeRankData::Rows(listType);
        const auto &charRows = SCBDNativeRankData::CharacterRows();

        for (int i = first; i < total; ++i) {
            const float y = list.y + yoff + (i - first) * rowH;
            if (y > list.y + list.h - 2.0f) break;
            if (y + rowH < list.y) continue;

            const float cy = y + rowH * 0.5f;
            const uint32_t rowColor = (i % 2) ? 0x8C1D2430 : 0xA8252C38;

            if (active == 2) {
                bool any = false;
                for (int slot = 0; slot < 3; ++slot) any = any || charRows[i][slot].valid;
                if (!any) continue;
            } else {
                if (i >= 100 || !liveRows[i].valid) continue;
            }

            ctx->Flush();
            ctx->BeginNoTex();
            ctx->Draw()->Rect(list.x + 3.0f, y + 1.0f, list.w - 6.0f, rowH - 2.0f, rowColor);
            ctx->Flush();
            ctx->Begin();
            ctx->BindFontTexture();

            DrawSCBDRankNumber(ctx, i + 1, list.x + 10.0f, cy,
                active == 2 ? 21.0f : 18.0f, 0xFFFFD86A);

            if (active == 2) {
                const float portraitX = list.x + 43.0f;
                const float portraitW = 62.0f;
                const float portraitH = rowH - 1.0f;
                DrawSCBDCharacterPortraitSlot(ctx, font, chars[i], i, portraitX, y + 0.5f, portraitW, portraitH);
                ctx->Draw()->SetFontScale(0.34f, 0.34f);
                ctx->Draw()->DrawText(font, chars[i], portraitX + portraitW + 12.0f, cy, 0xFFFFFFFF, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);

                const float usersStart = list.x + std::min(292.0f, list.w * 0.36f);
                const float userColumnW = (list.x + list.w - usersStart - 8.0f) / 3.0f;
                for (int slot = 0; slot < 3; ++slot) {
                    const auto &rr = charRows[i][slot];
                    if (!rr.valid) continue;
                    SCBDRankAvatarMock user{rr.name.c_str(), rr.initial.c_str(), rr.color};
                    const float colX = usersStart + userColumnW * slot;
                    const float avatarX = colX + 15.0f;
                    DrawSCBDRankAvatar(ctx, font, user, avatarX, cy, 10.5f, slot + 1, true);
                    ctx->Draw()->SetFontScale(0.30f, 0.30f);
                    ctx->Draw()->DrawTextRect(font, rr.name.c_str(), colX + 34.0f, y + 4.0f,
                        userColumnW - 37.0f, rowH - 8.0f, 0xFFFFFFFF,
                        ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);
                }
            } else {
                const auto &rr = liveRows[i];
                SCBDRankAvatarMock user{rr.name.c_str(), rr.initial.c_str(), rr.color};
                const float avatarX = list.x + 58.0f;
                DrawSCBDRankAvatar(ctx, font, user, avatarX, cy, 11.0f, i + 1, active != 3);
                ctx->Draw()->SetFontScale(0.34f, 0.34f);
                ctx->Draw()->DrawText(font, rr.name.c_str(), list.x + 78.0f, cy, 0xFFFFFFFF, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);

                char valueText[64];
                if (active == 3)
                    std::snprintf(valueText, sizeof(valueText), "CURRENT:%d  BEST:%d", rr.current, rr.best);
                else
                    std::snprintf(valueText, sizeof(valueText), "%d", rr.score);
                ctx->Draw()->SetFontScale(0.34f, 0.34f);
                ctx->Draw()->DrawText(font, valueText, list.x + list.w - 14.0f, cy,
                    0xFFFFD77A, ALIGN_RIGHT | ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);
            }
        }
    }

'''
d = d[:rank_page_start] + real_rank_page + d[rank_page_end:]
debug.write_text(d, encoding='utf-8')

# Fail early before long MSBuild if this hotfix did not apply.
checks = {
    controller: ['0x08836E18', 'leaderboardStreak'],
    main_js: ['input.buttons.send', 'pushRealNativeRankings', 'nativeSender.sendCharacterSnapshot'],
    native_sender: ['sendRankSnapshot', 'sendCharacterSnapshot'],
    debug: ['SCBDNativeRankData::List::MATCH_P1', 'CharacterRows()', 'CURRENT:%d  BEST:%d'],
    bridge_path: ['RANK_ROW', 'CHAR_ROW'],
}
for path, needles in checks.items():
    src = path.read_text(encoding='utf-8')
    missing = [n for n in needles if n not in src]
    if missing:
        raise SystemExit(f'Unified 1.2.2 preflight missing in {path.name}: {missing}')

print('Unified PC hotfix 1.2.2: gauge sync + explicit button release + REAL native rankings applied')

print('=== PATCH CHAIN PASS ===')
