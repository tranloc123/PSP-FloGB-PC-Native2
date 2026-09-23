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

print('=== PATCH CHAIN PASS ===')
