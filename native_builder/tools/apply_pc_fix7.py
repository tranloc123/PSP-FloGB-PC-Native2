from __future__ import annotations

from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_pc_fix7.py <ppsspp_repo>")

SCRIPT = Path(__file__).resolve()
PROJECT = SCRIPT.parents[2]
REPO = Path(sys.argv[1]).resolve()

controller = PROJECT / "core" / "controller-service.js"
main_js = PROJECT / "main.js"
renderer_js = PROJECT / "renderer" / "app.js"
debug_cpp = REPO / "UI" / "DebugOverlay.cpp"
bridge_h = REPO / "SCBD" / "SCBDNativeLiveBridge.h"
build_info = REPO / "PSP_LIVE_FLOGB_BUILD_INFO.txt"


def must(path: Path) -> Path:
    if not path.exists():
        raise SystemExit(f"FIX7 missing file: {path}")
    return path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    src = must(path).read_text(encoding="utf-8")
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"FIX7 {label}: expected 1 occurrence, found {count}")
    path.write_text(src.replace(old, new, 1), encoding="utf-8")
    print(f"FIX7 {label}: PASS")


def regex_once(path: Path, pattern: str, replacement: str, label: str) -> None:
    src = must(path).read_text(encoding="utf-8")
    out, count = re.subn(pattern, replacement, src, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"FIX7 {label}: expected 1 regex match, found {count}")
    path.write_text(out, encoding="utf-8")
    print(f"FIX7 {label}: PASS")


print("=== PSP FloGB PC Native FIX7 ===")
print("Project:", PROJECT)
print("PPSSPP :", REPO)

# ---------------------------------------------------------------------------
# 1) REAL LIVE identity transport
# ---------------------------------------------------------------------------

replace_once(
    controller,
    """const session = {
  members: new Map(),
  activePick: null,
  lastMatch: null,
  rounds: 0,
};""",
    """const session = {
  members: new Map(),
  activePick: null,
  lastMatch: null,
  rounds: 0,
  lastTrace: null,
};""",
    "session trace field",
)

replace_once(
    controller,
    """  session.lastMatch = null;
  session.rounds = 0;
  pickController.clear();""",
    """  session.lastMatch = null;
  session.rounds = 0;
  session.lastTrace = null;
  pickController.clear();""",
    "session trace reset",
)

live_api = r"""
  // REAL TikTok event ingress. Keep /api/test/* strictly for local test tools.
  if (req.method === 'POST' && pathname === '/api/live/team') {
    const b = await readBody(req);
    const u = b.user && typeof b.user === 'object' ? b.user : {};
    const result = assignTeam(u, b.team);
    const traceId = String(b.traceId || '');
    session.lastTrace = {
      traceId, stage:'CONTROLLER_TEAM', at:now(),
      userKey:userKey(u), username:displayName(u),
      avatar:String(u.avatar || ''), team:normalizeTeam(b.team),
      ok:!!result.ok, reason:result.reason || ''
    };
    log(`TRACE ${traceId || '-'} CONTROLLER_TEAM ${displayName(u)} -> ${normalizeTeam(b.team) || '?'} | ${result.ok ? 'OK' : result.reason}`);
    return sendJson(res, 200, {ok:true, result, trace:session.lastTrace});
  }

  if (req.method === 'POST' && pathname === '/api/live/gift') {
    const b = await readBody(req);
    const u = b.user && typeof b.user === 'object' ? b.user : {};
    const points = Math.max(0, Number(b.points ?? b.support) || 0);
    const result = addGift(u, points);
    const traceId = String(b.traceId || '');
    session.lastTrace = {
      traceId, stage:'CONTROLLER_GIFT', at:now(),
      userKey:userKey(u), username:displayName(u),
      avatar:String(u.avatar || ''), points,
      ok:!!result.ok, reason:result.reason || ''
    };
    log(`TRACE ${traceId || '-'} CONTROLLER_GIFT ${displayName(u)} +${points} | ${result.ok ? 'OK' : result.reason}`);
    return sendJson(res, 200, {ok:true, result, trace:session.lastTrace});
  }

  if (req.method === 'POST' && pathname === '/api/live/comment') {
    const b = await readBody(req);
    const u = b.user && typeof b.user === 'object' ? b.user : {};
    const result = processPickComment(u, b.comment);
    const traceId = String(b.traceId || '');
    session.lastTrace = {
      traceId, stage:'CONTROLLER_PICK_COMMENT', at:now(),
      userKey:userKey(u), username:displayName(u),
      avatar:String(u.avatar || ''), comment:String(b.comment || ''),
      ok:!!result.ok, reason:result.reason || ''
    };
    log(`TRACE ${traceId || '-'} CONTROLLER_PICK ${displayName(u)} ${String(b.comment || '')} | ${result.ok ? 'OK' : result.reason}`);
    return sendJson(res, 200, {ok:true, result, trace:session.lastTrace});
  }

"""

replace_once(
    controller,
    """  // Local test tools use the same real session engine.
""",
    live_api + """  // Local test tools use the same real session engine.
""",
    "real LIVE API endpoints",
)

replace_once(
    controller,
    """      lastMatch:session.lastMatch,
    },""",
    """      lastMatch:session.lastMatch,
      lastTrace:session.lastTrace,
    },""",
    "expose live trace",
)

route_report = r"""async function routeReport({kind,payload}){
  if(kind==='NORMALIZED_EVENT'){
    const e=typeof payload==='string'?JSON.parse(payload):payload; if(!e||!e.type)return;
    const traceId=String(e.eventId||`evt-${Date.now()}`);
    if(e.type==='comment'){
      const text=String(e.payload?.text||'').trim(), name=stableName(e.user);
      if(text==='1'||text==='2'){
        const team=text==='1'?'P1':'P2';
        sessionTeams.set(String(e.user?.id||e.user?.secUid||e.user?.uniqueId||name),team);
        const reply=await postApi('/api/live/team',{traceId,user:e.user||{},team});
        sendLog(`TRACE ${traceId} MAIN_TEAM ${name} -> ${team} | ${reply?.result?.ok?'OK':(reply?.result?.reason||'UNKNOWN')}`);
      }else if(/^\/pick\s+/i.test(text)){
        const reply=await postApi('/api/live/comment',{traceId,user:e.user||{},comment:text});
        sendLog(`TRACE ${traceId} MAIN_PICK ${name} ${text} | ${reply?.result?.ok?'OK':(reply?.result?.reason||'IGNORED')}`);
      }
    }
    win?.webContents.send('live-event',e); return;
  }

  if(kind==='SCORING_EVENT'){
    const e=typeof payload==='string'?JSON.parse(payload):payload; if(!e||markScore(e.scoringId))return;
    const traceId=String(e.scoringId||e.eventId||`score-${Date.now()}`);
    const name=stableName(e.user);
    const team=sessionTeams.get(String(e.user?.id||e.user?.secUid||e.user?.uniqueId||name))||null;
    if(e.type==='gift'){
      learnGift(e);
      const support=calcSupportValue(e);
      addRanking(e.user,support,'gift');
      const reply=await postApi('/api/live/gift',{traceId,user:e.user||{},points:support});
      sendLog(`TRACE ${traceId} MAIN_GIFT ${name} +${support} | ${reply?.result?.ok?'OK':(reply?.result?.reason||'IGNORED')}`);
      const rule=findGiftRule(e);
      await applyRuleActions(rule,team,e);
    }
    win?.webContents.send('scoring-event',e);
  }
}
"""

regex_once(
    main_js,
    r"async function routeReport\(\{kind,payload\}\)\{.*?\n\}\n\nipcMain\.on\('scbd-live-report'",
    route_report + "\nipcMain.on('scbd-live-report'",
    "main real viewer route",
)

# ---------------------------------------------------------------------------
# 2) Explicit PSP DOWN -> hold -> UP
# ---------------------------------------------------------------------------

replace_once(
    controller,
    """  tap(button, duration = 2) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify({event:'input.buttons.press', ticket:this.ticket++, button, duration}));
    return true;
  }""",
    """  async tap(button, holdMs = 80) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    button = button === 'l' ? 'ltrigger' : button === 'r' ? 'rtrigger' : String(button || 'cross');
    const ms = Math.max(45, Math.min(140, Number(holdMs) || 80));
    this.ws.send(JSON.stringify({
      event:'input.buttons.send',
      ticket:this.ticket++,
      buttons:{[button]:true}
    }));
    await sleep(ms);
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify({
      event:'input.buttons.send',
      ticket:this.ticket++,
      buttons:{[button]:false}
    }));
    await sleep(35);
    return true;
  }""",
    "controller explicit PSP release",
)

replace_once(
    controller,
    """  tap(button) { debuggerClient.tap(button, 2); },""",
    """  async tap(button) { return debuggerClient.tap(button, 80); },""",
    "game async tap wrapper",
)

tap_replacements = {
    "    this.tap('start'); await sleep(700);": "    await this.tap('start'); await sleep(700);",
    "    this.tap('up'); await sleep(300);": "    await this.tap('up'); await sleep(300);",
    "    this.tap('cross'); await sleep(700);": "    await this.tap('cross'); await sleep(700);",
    "    this.tap('cross'); await sleep(1500);": "    await this.tap('cross'); await sleep(1500);",
    "    this.tap('cross'); await sleep(1800);": "    await this.tap('cross'); await sleep(1800);",
    "    for (const m of moves) { this.tap(m); await sleep(450); }": "    for (const m of moves) { await this.tap(m); await sleep(450); }",
    "    this.tap('cross'); await sleep(1200);": "    await this.tap('cross'); await sleep(1200);",
    "    this.tap('right'); await sleep(900);": "    await this.tap('right'); await sleep(900);",
    "    this.tap('cross'); await sleep(2600);": "    await this.tap('cross'); await sleep(2600);",
    "    this.tap('right'); await sleep(1200);": "    await this.tap('right'); await sleep(1200);",
    "    this.tap('cross'); await sleep(2800);": "    await this.tap('cross'); await sleep(2800);",
    "    this.tap('cross'); await sleep(1400);": "    await this.tap('cross'); await sleep(1400);",
    "    this.tap('cross');\n    log('P1 selected + P2 Random30 + map sequence sent');":
        "    await this.tap('cross');\n    log('P1 selected + P2 Random30 + map sequence sent');",
}
src = must(controller).read_text(encoding="utf-8")
for old, new in tap_replacements.items():
    if old not in src:
        raise SystemExit(f"FIX7 awaited automation taps: missing marker: {old[:60]}")
    src = src.replace(old, new)
controller.write_text(src, encoding="utf-8")
print("FIX7 awaited automation taps: PASS")

# ---------------------------------------------------------------------------
# 3) Gauge opcode verification
# ---------------------------------------------------------------------------

replace_once(
    controller,
    """  antiHealCorrections: 0,
  hpLoopRunning: false,""",
    """  antiHealCorrections: 0,
  patchReadbackFailures: 0,
  gaugePatchOriginal: null,
  lastKOTrace: null,
  koFailureCooldownUntil: 0,
  hpLoopRunning: false,""",
    "runtime verification fields",
)

apply_patches = r"""  async applyCombatPatches() {
    if (this.patchesApplied || !debuggerClient.connected) return;
    const originals = new Map();
    const touched = [];

    const rollback = async () => {
      for (const addr of touched.reverse()) {
        const original = originals.get(addr);
        if (original !== undefined) {
          debuggerClient.writeU32(addr, original >>> 0);
          await sleep(18);
        }
      }
    };

    for (const addr of BASE_PATCHES) {
      try {
        const current = await debuggerClient.readRetry(addr, 3);
        originals.set(addr, current >>> 0);
        if (addr === 0x08836E18) this.gaugePatchOriginal = current >>> 0;

        if ((current >>> 0) !== 0) {
          debuggerClient.writeU32(addr, 0);
          touched.push(addr);
        }
        await sleep(25);

        const readback = (await debuggerClient.readRetry(addr, 3)) >>> 0;
        if (readback !== 0) {
          this.patchReadbackFailures += 1;
          this.lastError = `PATCH READBACK FAIL ${hex(addr)} expected=0 got=${hex(readback)}`;
          log(this.lastError, 'error');
          await rollback();
          return;
        }

        if (addr === 0x08836E18) {
          log(`GAUGE PATCH VERIFY ${hex(addr)} original=${hex(current)} readback=${hex(readback)} | NOP CONFIRMED`);
        }
      } catch (e) {
        this.lastError = `Patch verify failed ${hex(addr)}: ${e.message}`;
        log(this.lastError, 'error');
        await rollback();
        return;
      }
    }

    this.patchOriginals = originals;
    this.patchesApplied = true;
    log(`COMBAT PATCHES VERIFIED ${BASE_PATCHES.length}/${BASE_PATCHES.length}`);
  },"""

regex_once(
    controller,
    r"  async applyCombatPatches\(\) \{.*?\n  \},\n\n  async restoreCombatPatches",
    apply_patches + "\n\n  async restoreCombatPatches",
    "verified combat patches",
)

# ---------------------------------------------------------------------------
# 4) Arm even when one HP is already zero
# ---------------------------------------------------------------------------

arm_combat = r"""  async armIfCombat() {
    if (!debuggerClient.connected || this.cycleActive || this.armed) return;
    if (now() < this.koFailureCooldownUntil) return;
    try {
      const mode = (await debuggerClient.readRetry(RAM.MODE, 2)) >>> 0;
      const state = (await debuggerClient.readRetry(RAM.STATE, 2)) >>> 0;
      const p1 = u32ToFloat(await debuggerClient.readRetry(RAM.P1_HP, 2));
      const p2 = u32ToFloat(await debuggerClient.readRetry(RAM.P2_HP, 2));
      this.lastMode = mode; this.lastState = state; this.lastP1HP = p1; this.lastP2HP = p2;

      if (mode !== 0x19 || state !== RAM.COMBAT || !Number.isFinite(p1) || !Number.isFinite(p2))
        return;

      await this.applyCombatPatches();
      if (!this.patchesApplied) return;

      this.armed = true;
      this.phase = 'ARMED';
      this.roundStartedAt = now();
      this.antiHealP1 = p1;
      this.antiHealP2 = p2;
      this.antiHealAllowP1Until = 0;
      this.antiHealAllowP2Until = 0;

      if (p1 <= 0.5 && p2 > 0.5) {
        log(`BATTLE ARMED WITH ZERO HP | P1=${p1.toFixed(1)} P2=${p2.toFixed(1)} -> immediate KO P1`, 'warn');
        await this.handleKO('P1');
        return;
      }
      if (p2 <= 0.5 && p1 > 0.5) {
        log(`BATTLE ARMED WITH ZERO HP | P1=${p1.toFixed(1)} P2=${p2.toFixed(1)} -> immediate KO P2`, 'warn');
        await this.handleKO('P2');
        return;
      }
      if (p1 <= 0.5 && p2 <= 0.5) {
        log(`BATTLE ARMED WITH DOUBLE ZERO | P1=${p1.toFixed(1)} P2=${p2.toFixed(1)} -> KO P1 fallback`, 'warn');
        await this.handleKO('P1');
        return;
      }

      if (p1 > 1 && p2 > 1) {
        log(`BATTLE ARMED | P1=${p1.toFixed(1)} P2=${p2.toFixed(1)} | ANTI-HEAL WATCHDOG ON`);
      } else {
        this.armed = false;
        this.phase = 'WAIT_COMBAT';
      }
    } catch (e) {
      this.lastError = `armIfCombat: ${e.message}`;
    }
  },"""

regex_once(
    controller,
    r"  async armIfCombat\(\) \{.*?\n  \},\n\n  async hpLoop",
    arm_combat + "\n\n  async hpLoop",
    "zero-at-entry combat arm",
)

# ---------------------------------------------------------------------------
# 5) Verified KO -> State3 -> Victory5 -> Outro -> clean return -> Winner/Pick
# ---------------------------------------------------------------------------

ko_block = r"""  async handleKO(loser) {
    if (!this.armed || this.cycleActive) return;
    this.armed = false;
    this.cycleActive = true;
    this.gameReady = false;
    this.continueBusy = false;
    this.phase = 'KO_DETECTED';
    const winnerTeam = loser === 'P1' ? 'P2' : 'P1';

    for (const m of session.members.values()) {
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
    this.lastKOTrace = {
      loser, winnerTeam, startedAt:now(), attempts:0,
      gate:null, state:null, victorySeen:false, cleanReturn:false
    };
    log(`REAL KO DETECTED: ${loser} -> WINNER ${winnerTeam}`);

    const transition = await this.forceKOTransition();
    if (!transition.ok) {
      this.phase = 'KO_TRANSITION_FAILED';
      this.lastError = transition.error;
      this.cycleActive = false;
      this.continueBusy = false;
      this.koFailureCooldownUntil = now() + 3000;
      log(this.lastError, 'error');
      return;
    }

    this.phase = 'OUTRO';
    this.waitOutroAndReturn(winnerTeam).catch(e => {
      this.lastError = e.message;
      this.phase = 'KO_TRANSITION_FAILED';
      this.cycleActive = false;
      this.continueBusy = false;
      this.koFailureCooldownUntil = now() + 3000;
      log('OUTRO/VICTORY verify error: ' + e.message, 'error');
    });
  },

  async forceKOTransition() {
    let lastGate = null;
    let lastState = null;

    for (let attempt = 1; attempt <= 3; attempt++) {
      this.lastKOTrace.attempts = attempt;

      debuggerClient.writeU32(RAM.GATE, 3);
      await sleep(90);
      try { lastGate = (await debuggerClient.readRetry(RAM.GATE, 3)) >>> 0; } catch {}

      debuggerClient.writeU32(RAM.STATE, RAM.STATE3);
      await sleep(170);

      const watchStart = now();
      while (now() - watchStart < 700) {
        try {
          lastState = (await debuggerClient.readRetry(RAM.STATE, 2)) >>> 0;
          this.lastState = lastState;
          if (lastState === RAM.STATE3 || lastState === RAM.VICTORY5 || lastState !== RAM.COMBAT)
            break;
        } catch {}
        await sleep(90);
      }

      this.lastKOTrace.gate = lastGate;
      this.lastKOTrace.state = lastState;
      log(`KO TRANSITION TRY ${attempt}/3 | GATE=${lastGate === null ? '?' : lastGate} STATE=${lastState === null ? '?' : hex(lastState)}`);

      if (lastGate === 3 && lastState !== null && lastState !== RAM.COMBAT) {
        log(`KO TRANSITION ACCEPTED | STATE3=${hex(RAM.STATE3)} VICTORY5=${hex(RAM.VICTORY5)}`);
        return {ok:true, gate:lastGate, state:lastState};
      }
      await sleep(180);
    }

    return {
      ok:false,
      error:`KO_TRANSITION_FAILED gate=${lastGate === null ? '?' : lastGate} state=${lastState === null ? '?' : hex(lastState)} expected non-COMBAT after STATE3 write`
    };
  },

  async waitOutroAndReturn(winnerTeam) {
    const started = now();
    let victoryEnteredAt = 0;
    let internalDone = false;

    while (now() - started < 10000) {
      try {
        const state = (await debuggerClient.readU32(RAM.STATE, 550)) >>> 0;
        this.lastState = state;

        if (state === RAM.VICTORY5) {
          if (!victoryEnteredAt) {
            victoryEnteredAt = now();
            this.lastKOTrace.victorySeen = true;
            log('VICTORY5 ENTERED');
          }

          try {
            const count = (await debuggerClient.readU32(RAM.V5_COUNT, 500)) >>> 0;
            const limit = (await debuggerClient.readU32(RAM.V5_LIMIT, 500)) >>> 0;
            if (limit > 0 && count >= limit) {
              log(`VICTORY TIMER ${count}/${limit}`);
              internalDone = true;
              break;
            }
          } catch {}

          if (victoryEnteredAt && now() - victoryEnteredAt >= 7500)
            break;
        }
      } catch {}

      await sleep(140);
    }

    if (!victoryEnteredAt) {
      throw new Error(
        `VICTORY5_NOT_OBSERVED after KO | lastState=${this.lastState === null ? '?' : hex(this.lastState)}`
      );
    }

    if (internalDone) await sleep(650);

    this.phase = 'RETURN_COMBAT';
    debuggerClient.writeU32(RAM.MODE, 0x19);
    await sleep(120);
    debuggerClient.writeU32(RAM.GATE, 0);
    await sleep(120);
    debuggerClient.writeU32(RAM.STATE, RAM.COMBAT);
    await sleep(300);

    let returned = false;
    const verifyStart = now();
    while (now() - verifyStart < 2600) {
      try {
        const mode = (await debuggerClient.readRetry(RAM.MODE, 2)) >>> 0;
        const gate = (await debuggerClient.readRetry(RAM.GATE, 2)) >>> 0;
        const state = (await debuggerClient.readRetry(RAM.STATE, 2)) >>> 0;
        this.lastMode = mode;
        this.lastState = state;
        if (mode === 0x19 && gate === 0 && state === RAM.COMBAT) {
          returned = true;
          break;
        }
      } catch {}
      await sleep(120);
    }

    if (!returned) {
      throw new Error(
        `CLEAN_RETURN_VERIFY_FAILED mode=${this.lastMode === null ? '?' : hex(this.lastMode)} state=${this.lastState === null ? '?' : hex(this.lastState)}`
      );
    }

    this.gameReady = true;
    this.lastKOTrace.cleanReturn = true;
    log('OUTRO VERIFIED -> clean return Training Combat');

    openWinnerPick(winnerTeam);
    this.maybeContinueAfterDecision();
  },

  maybeContinueAfterDecision() {"""

regex_once(
    controller,
    r"  async handleKO\(loser\) \{.*?\n  maybeContinueAfterDecision\(\) \{",
    ko_block,
    "verified KO/Victory/Outro state machine",
)

replace_once(
    controller,
    """      antiHealFloorP2:Number.isFinite(game.antiHealP2) ? Number(game.antiHealP2.toFixed(2)) : null,
""",
    """      antiHealFloorP2:Number.isFinite(game.antiHealP2) ? Number(game.antiHealP2.toFixed(2)) : null,
      patchReadbackFailures:game.patchReadbackFailures,
      gaugePatchOriginal:game.gaugePatchOriginal === null ? null : hex(game.gaugePatchOriginal),
      koTrace:game.lastKOTrace,
      inputP1:'DEBUGGER_EXPLICIT_DOWN_UP',
      inputP2:'NOT_WIRED_GAME_INTERNAL_PATH',
""",
    "expose KO/gauge/P2 truth",
)

# ---------------------------------------------------------------------------
# 6) LIVE UI: window-open is not the same thing as event flow
# ---------------------------------------------------------------------------

replace_once(
    renderer_js,
    """let currentState=null, giftRules={version:2,mode:'game-actions-only',rules:{}}, learned={}, rankings={users:{}}, liveWindowOpened=false;""",
    """let currentState=null, giftRules={version:2,mode:'game-actions-only',rules:{}}, learned={}, rankings={users:{}}, liveWindowOpened=false, lastProbeEventAt=0;""",
    "renderer probe event clock",
)

replace_once(
    renderer_js,
    """$('liveStatus').textContent=liveWindowOpened?'OPEN':'OFF';$('liveDot').className='dot '+(liveWindowOpened?'on':'');""",
    """const probeAlive=Date.now()-lastProbeEventAt<10000;$('liveStatus').textContent=probeAlive?'EVENTS':(liveWindowOpened?'WINDOW':'OFF');$('liveDot').className='dot '+(probeAlive?'on':(liveWindowOpened?'on':''));""",
    "renderer honest LIVE status",
)

replace_once(
    renderer_js,
    """ipcRenderer.on('live-event',(_,e)=>{$('lastEvent').textContent=JSON.stringify(e,null,2)});""",
    """ipcRenderer.on('live-event',(_,e)=>{lastProbeEventAt=Date.now();$('lastEvent').textContent=JSON.stringify(e,null,2)});""",
    "renderer record actual event",
)

# ---------------------------------------------------------------------------
# 7) Native mock hard stop
# ---------------------------------------------------------------------------

debug_src = must(debug_cpp).read_text(encoding="utf-8")
for token in ("kSCBDP1MockRows", "kSCBDP2MockRows"):
    if token in debug_src:
        pos = debug_src.find(token)
        print(debug_src[max(0, pos - 350):pos + 550])
        raise SystemExit(f"FIX7 PREBUILD STOP: native mock identifier survived: {token}")

for required in (
    "BuildSCBDLiveRows(SCBDNativeRankData::List::MATCH_P1",
    "BuildSCBDLiveRows(SCBDNativeRankData::List::MATCH_P2",
):
    if required not in debug_src:
        raise SystemExit(f"FIX7 PREBUILD STOP: missing native real-data marker: {required}")

for fake in ("NEW-PLAYER", "NEW-CHALLENGER", "PLAYER-K", "PLAYER-M"):
    if fake in debug_src:
        raise SystemExit(f"FIX7 PREBUILD STOP: old native fake ranking row survived: {fake}")

bridge_src = must(bridge_h).read_text(encoding="utf-8")
for marker in ("RANK_ROW", "CHAR_ROW", "WSAStartup"):
    if marker not in bridge_src:
        raise SystemExit(f"FIX7 PREBUILD STOP: native bridge marker missing: {marker}")

# ---------------------------------------------------------------------------
# 8) Source preflight
# ---------------------------------------------------------------------------

checks = {
    controller: [
        "0x08836E18",
        "GAUGE PATCH VERIFY",
        "input.buttons.send",
        "KO_TRANSITION_FAILED",
        "VICTORY5_NOT_OBSERVED",
        "/api/live/team",
        "/api/live/gift",
        "/api/live/comment",
        "inputP2:'NOT_WIRED_GAME_INTERNAL_PATH'",
    ],
    main_js: [
        "/api/live/team",
        "/api/live/gift",
        "/api/live/comment",
        "user:e.user||{}",
        "TRACE ${traceId}",
    ],
    renderer_js: [
        "lastProbeEventAt",
        "'EVENTS'",
        "'WINDOW'",
    ],
}

for path, markers in checks.items():
    src = must(path).read_text(encoding="utf-8")
    missing = [m for m in markers if m not in src]
    if missing:
        raise SystemExit(f"FIX7 source preflight missing in {path.name}: {missing}")

controller_src = controller.read_text(encoding="utf-8")
if "input.buttons.press" in controller_src:
    raise SystemExit("FIX7 source preflight: controller still contains input.buttons.press")

winner_pos = controller_src.find("openWinnerPick(winnerTeam);")
return_pos = controller_src.find("OUTRO VERIFIED -> clean return Training Combat")
if winner_pos < 0 or return_pos < 0 or winner_pos < return_pos:
    raise SystemExit("FIX7 source preflight: Winner/Pick still opens before verified clean return")

if build_info.exists():
    with build_info.open("a", encoding="utf-8") as f:
        f.write(
            "\nPSP FloGB PC Native FIX7\n"
            "Real TikTok identity transport preserves id/secUid/uniqueId/nickname/avatar\n"
            "Gauge patch write/readback verified at 0x08836E18\n"
            "KO requires non-COMBAT transition + VICTORY5 + clean-return verification\n"
            "Winner/Pick opens only after verified KO/Victory/Outro return\n"
            "Input uses explicit DOWN/UP on persistent debugger path\n"
            "P2 combat input is explicitly NOT_WIRED pending game-internal P2/AI trace\n"
            "Native ranking hard-preflight rejects surviving mock identifiers\n"
        )

print("FIX7 SOURCE PREFLIGHT PASS")
print("IMPORTANT: P2 combat virtual input is intentionally reported NOT_WIRED, not faked.")
print("=== FIX7 PASS ===")
