from __future__ import annotations

from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_pc_live_final.py <ppsspp_repo>")

SCRIPT = Path(__file__).resolve()
PROJECT = SCRIPT.parents[2]
REPO = Path(sys.argv[1]).resolve()

main_js = PROJECT / "main.js"
renderer_js = PROJECT / "renderer" / "app.js"
renderer_html = PROJECT / "renderer" / "index.html"
controller_js = PROJECT / "core" / "controller-service.js"
native_sender = PROJECT / "core" / "native_sender_v059.js"

debug = REPO / "UI" / "DebugOverlay.cpp"
emu = REPO / "UI" / "EmuScreen.cpp"
bridge = REPO / "SCBD" / "SCBDNativeLiveBridge.h"
p2_header = REPO / "SCBD" / "SCBDP2LogicalInput.h"
build_info = REPO / "PSP_LIVE_FLOGB_BUILD_INFO.txt"

for p in (main_js, renderer_js, renderer_html, controller_js, native_sender, debug, emu, bridge):
    if not p.exists():
        raise SystemExit(f"LIVE FINAL missing file: {p}")

def replace_once(path: Path, old: str, new: str, label: str) -> None:
    src = path.read_text(encoding="utf-8")
    n = src.count(old)
    if n != 1:
        raise SystemExit(f"LIVE FINAL {label}: expected 1 occurrence, found {n}")
    path.write_text(src.replace(old, new, 1), encoding="utf-8")
    print(f"LIVE FINAL {label}: PASS")

def replace_region(path: Path, start_marker: str, end_marker: str, replacement: str, label: str) -> None:
    src = path.read_text(encoding="utf-8")
    a = src.find(start_marker)
    b = src.find(end_marker, a + len(start_marker))
    if a < 0 or b < 0:
        raise SystemExit(f"LIVE FINAL {label}: structural boundary missing")
    path.write_text(src[:a] + replacement + src[b:], encoding="utf-8")
    print(f"LIVE FINAL {label}: PASS")

print("=== PSP FloGB LIVE FINAL: PRODUCTION INPUT + UI ===")

p2_h = r'''#pragma once

#include <algorithm>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <mutex>
#include <string>

#include "Common/CommonTypes.h"
#include "Core/Core.h"
#include "Core/MemMap.h"
#include "Core/MIPS/MIPS.h"

namespace SCBDP2LogicalInput {

inline constexpr u32 kHookAddr = 0x08A542B0;
inline constexpr u32 kOriginalUpdateAddr = 0x08A53924;
inline constexpr u32 kCaveAddr = 0x08BB8FE8;
inline constexpr u32 kP2ModeStoreAddr = 0x08A31ED0;
inline constexpr u32 kP2FighterPtrAddr = 0x08808A2C;
inline constexpr u32 kMailboxAddr = 0x08CCBF04;

inline constexpr u32 kHookOriginal = 0x0E294E49;
inline constexpr u32 kHookPatched = 0x0E2EE3FA;
inline constexpr u32 kP2ModeOriginal = 0xACA2F8D0;
inline constexpr u32 kP2ModePatched = 0xACA3F8D0;

inline constexpr u32 kCaveWords[6] = {
    0x3C0808CD,
    0x8D08BF04,
    0x3A690001,
    0x0109280A,
    0x0A294E49,
    0x00000000,
};

struct Pulse {
    u32 mask = 0;
    int holdMs = 80;
    int gapMs = 70;
};

struct State {
    std::mutex mutex;
    std::deque<Pulse> queue;
    bool installed = false;
    bool incompatible = false;
    bool fighterReady = false;
    bool down = false;
    bool gap = false;
    u32 activeMask = 0;
    u32 mailboxWritten = 0xFFFFFFFF;
    u32 hookWord = 0;
    u32 modeWord = 0;
    u32 p2Ptr = 0;
    u32 lastMask = 0;
    int activeGapMs = 0;
    std::string lastError;
    std::chrono::steady_clock::time_point deadline{};
};

struct Snapshot {
    bool installed = false;
    bool incompatible = false;
    bool fighterReady = false;
    size_t queueSize = 0;
    u32 hookWord = 0;
    u32 modeWord = 0;
    u32 p2Ptr = 0;
    u32 lastMask = 0;
    std::string lastError;
};

inline State &GetState() {
    static State s;
    return s;
}

inline int ClampMs(int v, int lo, int hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

inline bool Valid4(u32 addr) {
    return Memory::IsValidRange(addr, 4);
}

inline void WriteCode(u32 addr, u32 word) {
    Memory::WriteUnchecked_U32(word, addr);
    if (currentMIPS)
        currentMIPS->InvalidateICacheRangeDeferred(addr, 4);
}

inline bool EnsureInstalledCPU(State &s) {
    if (!Memory::IsActive() || !currentMIPS)
        return false;

    if (!Valid4(kHookAddr) || !Valid4(kCaveAddr) || !Valid4(kCaveAddr + 20) ||
        !Valid4(kP2ModeStoreAddr) || !Valid4(kMailboxAddr) || !Valid4(kP2FighterPtrAddr)) {
        s.installed = false;
        s.fighterReady = false;
        s.lastError = "WAIT_MEMORY";
        return false;
    }

    s.hookWord = Memory::Read_Opcode_JIT(kHookAddr).encoding;
    s.modeWord = Memory::Read_Opcode_JIT(kP2ModeStoreAddr).encoding;

    const bool hookCompatible = s.hookWord == kHookOriginal || s.hookWord == kHookPatched;
    const bool modeCompatible = s.modeWord == kP2ModeOriginal || s.modeWord == kP2ModePatched;

    if (!hookCompatible || !modeCompatible) {
        s.installed = false;
        s.fighterReady = false;
        s.incompatible = true;
        s.lastError = !hookCompatible ? "HOOK_SIGNATURE_MISMATCH" : "P2_MODE_SIGNATURE_MISMATCH";
        return false;
    }

    for (int i = 0; i < 6; ++i) {
        const u32 addr = kCaveAddr + static_cast<u32>(i * 4);
        if (Memory::ReadUnchecked_U32(addr) != kCaveWords[i])
            WriteCode(addr, kCaveWords[i]);
    }

    if (s.modeWord != kP2ModePatched)
        WriteCode(kP2ModeStoreAddr, kP2ModePatched);
    if (s.hookWord != kHookPatched)
        WriteCode(kHookAddr, kHookPatched);

    s.hookWord = kHookPatched;
    s.modeWord = kP2ModePatched;
    s.installed = true;
    s.incompatible = false;
    s.lastError.clear();
    return true;
}

inline void EnforceFighterCPU(State &s) {
    s.fighterReady = false;
    s.p2Ptr = 0;

    if (!Valid4(kP2FighterPtrAddr))
        return;

    const u32 p2 = Memory::ReadUnchecked_U32(kP2FighterPtrAddr);
    if (!p2 || !Valid4(p2 + 0xF8CC) || !Valid4(p2 + 0xF8D0))
        return;

    s.p2Ptr = p2;

    if (Memory::ReadUnchecked_U32(p2 + 0xF8CC) != 1)
        Memory::WriteUnchecked_U32(1, p2 + 0xF8CC);
    if (Memory::ReadUnchecked_U32(p2 + 0xF8D0) != 1)
        Memory::WriteUnchecked_U32(1, p2 + 0xF8D0);

    s.fighterReady =
        Memory::ReadUnchecked_U32(p2 + 0xF8CC) == 1 &&
        Memory::ReadUnchecked_U32(p2 + 0xF8D0) == 1;
}

inline bool QueueTap(u32 internalMask, int holdMs = 80, int gapMs = 70) {
    if (!internalMask)
        return false;

    State &s = GetState();
    std::lock_guard<std::mutex> guard(s.mutex);

    if (!s.installed || !s.fighterReady || s.incompatible)
        return false;
    if (s.queue.size() >= 64)
        return false;

    s.queue.push_back(Pulse{
        internalMask,
        ClampMs(holdMs, 25, 350),
        ClampMs(gapMs, 20, 350)
    });
    s.lastMask = internalMask;
    return true;
}

inline void CancelAll() {
    State &s = GetState();
    std::lock_guard<std::mutex> guard(s.mutex);
    s.queue.clear();
    s.down = false;
    s.gap = false;
    s.activeMask = 0;
    s.activeGapMs = 0;

    Core_RunOnCPUThread([&] {
        if (Memory::IsActive() && Valid4(kMailboxAddr)) {
            Memory::WriteUnchecked_U32(0, kMailboxAddr);
            s.mailboxWritten = 0;
        }
    });
}

inline void Process() {
    using Clock = std::chrono::steady_clock;

    State &s = GetState();
    std::lock_guard<std::mutex> guard(s.mutex);
    const auto now = Clock::now();

    if (s.down && now >= s.deadline) {
        s.down = false;
        s.gap = true;
        s.activeMask = 0;
        s.deadline = now + std::chrono::milliseconds(s.activeGapMs);
        s.activeGapMs = 0;
    }

    if (s.gap && now >= s.deadline)
        s.gap = false;

    if (!s.down && !s.gap && !s.queue.empty()) {
        const Pulse pulse = s.queue.front();
        s.queue.pop_front();
        s.activeMask = pulse.mask;
        s.down = true;
        s.activeGapMs = pulse.gapMs;
        s.deadline = now + std::chrono::milliseconds(pulse.holdMs);
    }

    const u32 desiredMask = s.down ? s.activeMask : 0;

    Core_RunOnCPUThread([&] {
        if (!EnsureInstalledCPU(s)) {
            if (Memory::IsActive() && Valid4(kMailboxAddr) && s.mailboxWritten != 0) {
                Memory::WriteUnchecked_U32(0, kMailboxAddr);
                s.mailboxWritten = 0;
            }
            return;
        }

        EnforceFighterCPU(s);

        if (s.mailboxWritten != desiredMask) {
            Memory::WriteUnchecked_U32(desiredMask, kMailboxAddr);
            s.mailboxWritten = desiredMask;
        }
    });
}

inline bool Ready() {
    State &s = GetState();
    std::lock_guard<std::mutex> guard(s.mutex);
    return s.installed && s.fighterReady && !s.incompatible;
}

inline Snapshot Read() {
    State &s = GetState();
    std::lock_guard<std::mutex> guard(s.mutex);
    Snapshot out;
    out.installed = s.installed;
    out.incompatible = s.incompatible;
    out.fighterReady = s.fighterReady;
    out.queueSize = s.queue.size() + (s.down ? 1 : 0);
    out.hookWord = s.hookWord;
    out.modeWord = s.modeWord;
    out.p2Ptr = s.p2Ptr;
    out.lastMask = s.lastMask;
    out.lastError = s.lastError;
    return out;
}

}  // namespace SCBDP2LogicalInput
'''
p2_header.write_text(p2_h, encoding="utf-8")
print("LIVE FINAL P2 logical-slot engine: PASS")

d = debug.read_text(encoding="utf-8")
include_anchor = '#include "SCBD/SCBDNativeLiveBridge.h"\n'
if '#include "SCBD/SCBDP2LogicalInput.h"' not in d:
    if include_anchor not in d:
        raise SystemExit("LIVE FINAL DebugOverlay native bridge include missing")
    d = d.replace(include_anchor, include_anchor + '#include "SCBD/SCBDP2LogicalInput.h"\n', 1)

if "SCBDP2LogicalInput::Process();" not in d:
    process_anchor = "    SCBDNativeLiveBridge::Process();\n"
    if process_anchor not in d:
        raise SystemExit("LIVE FINAL native bridge Process anchor missing")
    d = d.replace(process_anchor, process_anchor + "    SCBDP2LogicalInput::Process();\n", 1)

debug.write_text(d, encoding="utf-8")
print("LIVE FINAL P2 process integration: PASS")

b = bridge.read_text(encoding="utf-8")
if "#include <cctype>" not in b:
    alg_inc = "#include <algorithm>\n"
    if alg_inc not in b:
        raise SystemExit("LIVE FINAL bridge <algorithm> include missing")
    b = b.replace(alg_inc, alg_inc + "#include <cctype>\n", 1)
rank_inc = '#include "SCBD/SCBDNativeRankData.h"\n'
winner_inc = '#include "SCBD/SCBDNativeWinner.h"\n'
input_includes = '#include "SCBD/SCBDVirtualInput.h"\n#include "SCBD/SCBDP2LogicalInput.h"\n'
if '#include "SCBD/SCBDP2LogicalInput.h"' not in b:
    anchor = rank_inc if rank_inc in b else winner_inc
    if anchor not in b:
        raise SystemExit("LIVE FINAL bridge include anchor missing")
    b = b.replace(anchor, anchor + input_includes, 1)

input_helpers = r'''
inline bool ResolveInputButton(const std::string &raw, u32 &p1Mask, u32 &p2Mask) {
    std::string s = raw;
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c){ return static_cast<char>(std::tolower(c)); });

    if (s == "select")   { p1Mask = CTRL_SELECT;   p2Mask = 0x4000; return true; }
    if (s == "start")    { p1Mask = CTRL_START;    p2Mask = 0x8000; return true; }
    if (s == "up")       { p1Mask = CTRL_UP;       p2Mask = 0x2000; return true; }
    if (s == "right")    { p1Mask = CTRL_RIGHT;    p2Mask = 0x0400; return true; }
    if (s == "down")     { p1Mask = CTRL_DOWN;     p2Mask = 0x1000; return true; }
    if (s == "left")     { p1Mask = CTRL_LEFT;     p2Mask = 0x0800; return true; }
    if (s == "l" || s == "ltrigger") { p1Mask = CTRL_LTRIGGER; p2Mask = 0x0002; return true; }
    if (s == "r" || s == "rtrigger") { p1Mask = CTRL_RTRIGGER; p2Mask = 0x0010; return true; }
    if (s == "triangle") { p1Mask = CTRL_TRIANGLE; p2Mask = 0x0100; return true; }
    if (s == "circle")   { p1Mask = CTRL_CIRCLE;   p2Mask = 0x0020; return true; }
    if (s == "cross")    { p1Mask = CTRL_CROSS;    p2Mask = 0x0040; return true; }
    if (s == "square")   { p1Mask = CTRL_SQUARE;   p2Mask = 0x0200; return true; }
    return false;
}

inline std::string P2HealthText() {
    const auto p2 = SCBDP2LogicalInput::Read();
    std::string state =
        p2.incompatible ? "INCOMPAT" :
        (p2.installed && p2.fighterReady) ? "READY" :
        p2.installed ? "HOOKED" : "WAIT";
    return "FLOGB14|P2=" + state + "|Q=" + std::to_string(p2.queueSize);
}

'''
if "inline bool ResolveInputButton(" not in b:
    marker = "inline void HandlePacket(RuntimeState &s, std::string line, const sockaddr_in &peer, int peerLen) {\n"
    if marker not in b:
        raise SystemExit("LIVE FINAL bridge HandlePacket marker missing")
    b = b.replace(marker, input_helpers + marker, 1)

old_ping = '    if (cmd == "PING") { Reply(s, peer, peerLen, "PING", true, "WINDOWS-V0.1"); return; }\n'
if old_ping in b:
    b = b.replace(
        old_ping,
        '    if (cmd == "PING") { Reply(s, peer, peerLen, "PING", true, P2HealthText()); return; }\n',
        1
    )
elif "P2HealthText()" not in b:
    raise SystemExit("LIVE FINAL PING anchor missing")

input_commands = r'''
    if (cmd == "INPUT") {
        if (parts.size() < 6) {
            ++s.errors; s.lastError = "INPUT needs team/button/count/hold/gap";
            Reply(s, peer, peerLen, "INPUT", false, "bad-fields"); return;
        }

        const int team = ParseInt(parts[1], 0);
        const std::string button = UrlDecode(parts[2]);
        const int count = std::clamp(ParseInt(parts[3], 1), 1, 20);
        const int holdMs = std::clamp(ParseInt(parts[4], 80), 25, 350);
        const int gapMs = std::clamp(ParseInt(parts[5], 70), 20, 350);

        u32 p1Mask = 0, p2Mask = 0;
        if ((team != 1 && team != 2) || !ResolveInputButton(button, p1Mask, p2Mask)) {
            ++s.errors; s.lastError = "INPUT invalid team/button";
            Reply(s, peer, peerLen, "INPUT", false, "invalid-input"); return;
        }

        if (team == 2) {
            if (!SCBDP2LogicalInput::Ready()) {
                Reply(s, peer, peerLen, "INPUT", false, "p2-not-ready"); return;
            }
            int accepted = 0;
            for (int i = 0; i < count; ++i)
                accepted += SCBDP2LogicalInput::QueueTap(p2Mask, holdMs, gapMs) ? 1 : 0;
            if (!accepted) {
                Reply(s, peer, peerLen, "INPUT", false, "p2-queue-full"); return;
            }
            Reply(s, peer, peerLen, "INPUT", true, "P2_SLOT1"); return;
        }

        for (int i = 0; i < count; ++i)
            SCBDVirtualInput::QueueTap(p1Mask, holdMs, gapMs);
        Reply(s, peer, peerLen, "INPUT", true, "P1_NATIVE"); return;
    }

    if (cmd == "INPUT_CANCEL") {
        SCBDVirtualInput::CancelAll();
        SCBDP2LogicalInput::CancelAll();
        Reply(s, peer, peerLen, "INPUT_CANCEL", true); return;
    }

'''
if 'if (cmd == "INPUT")' not in b:
    compact_anchor = '    ++s.errors; s.lastError = "unknown command: " + cmd; Reply(s, peer, peerLen, cmd, false, "unknown-command");\n'
    if compact_anchor not in b:
        raise SystemExit("LIVE FINAL bridge unknown-command anchor missing")
    b = b.replace(compact_anchor, input_commands + compact_anchor, 1)

bridge.write_text(b, encoding="utf-8")
print("LIVE FINAL native INPUT transport: PASS")

ns = native_sender.read_text(encoding="utf-8")
sender_methods = r'''
function sendInput({ team, button, count = 1, holdMs = 80, gapMs = 70 }) {
  const t = Number(team) === 2 ? 2 : 1;
  const b = String(button || "cross").trim().toLowerCase();
  const c = Math.max(1, Math.min(20, Number(count) || 1));
  const h = Math.max(25, Math.min(350, Number(holdMs) || 80));
  const g = Math.max(20, Math.min(350, Number(gapMs) || 70));
  return sendRaw(`INPUT\t${t}\t${enc(b)}\t${c}\t${h}\t${g}`);
}

function sendInputCancel() {
  return sendRaw("INPUT_CANCEL");
}

function p2StateFromAck() {
  const m = String(state.lastAck || "").match(/\bP2=(READY|HOOKED|WAIT|INCOMPAT)\b/);
  return m ? m[1] : "WAIT";
}

'''
if "function sendInput({" not in ns:
    marker = "function getStatus() {\n"
    if marker not in ns:
        raise SystemExit("LIVE FINAL native sender getStatus marker missing")
    ns = ns.replace(marker, sender_methods + marker, 1)

old_status = "    nativeOnline: state.lastAckAt > 0 && now - state.lastAckAt < 3000,\n"
new_status = "    nativeOnline: state.lastAckAt > 0 && now - state.lastAckAt < 3000,\n    p2State: p2StateFromAck(),\n    p2Ready: p2StateFromAck() === \"READY\",\n"
if "p2Ready:" not in ns:
    if old_status not in ns:
        raise SystemExit("LIVE FINAL native sender status marker missing")
    ns = ns.replace(old_status, new_status, 1)

if "  sendInput,\n" not in ns:
    export_anchor = "  sendCancel,\n"
    if export_anchor not in ns:
        raise SystemExit("LIVE FINAL native sender export marker missing")
    ns = ns.replace(export_anchor, export_anchor + "  sendInput,\n  sendInputCancel,\n", 1)

native_sender.write_text(ns, encoding="utf-8")
print("LIVE FINAL native sender API: PASS")

m = main_js.read_text(encoding="utf-8")
if "const nativeSender = require('./core/native_sender_v059');" not in m:
    raise SystemExit("LIVE FINAL main nativeSender import missing")

hp_anchor = "const HP={P1:0x08BE364C,P2:0x08BFA30C};\n"
combat_helper = '''const HP={P1:0x08BE364C,P2:0x08BFA30C};
function liveCombatReady(){
  const p=lastControllerState?.ppsspp||{};
  return !!p.connected && p.gamePhase==='ARMED' && p.patchesApplied!==false;
}
'''
if "function liveCombatReady()" not in m:
    if hp_anchor not in m:
        raise SystemExit("LIVE FINAL main HP anchor missing")
    m = m.replace(hp_anchor, combat_helper, 1)

input_start = m.find("  if(type==='input'){\n")
input_end = m.find("  if(type==='heal_team'||type==='damage_enemy'||type==='set_hp'){\n", input_start)
if input_start < 0 or input_end < 0:
    raise SystemExit("LIVE FINAL main input-action structural boundary missing")

input_block = '''  if(type==='input'){
    if(!memberTeam)return;
    if(!liveCombatReady()){
      sendLog(`DROP INPUT ${memberTeam}: game not in ARMED combat`,'warn');
      return;
    }
    const button=String(action.button||'cross').trim().toLowerCase();
    const count=Math.min(20,Math.max(1,Number(action.count||action.amount)||1));
    const holdMs=Math.min(350,Math.max(25,Number(action.holdMs)||80));
    const gapMs=Math.min(350,Math.max(20,Number(action.gapMs)||70));
    await nativeSender.sendInput({
      team:memberTeam==='P2'?2:1,
      button,
      count,
      holdMs,
      gapMs
    });
    return;
  }
'''
m = m[:input_start] + input_block + m[input_end:]

hp_gate = "  if(type==='heal_team'||type==='damage_enemy'||type==='set_hp'){\n"
if "DROP HP ACTION" not in m:
    if hp_gate not in m:
        raise SystemExit("LIVE FINAL HP action marker missing")
    m = m.replace(
        hp_gate,
        hp_gate + "    if(!liveCombatReady()){sendLog(`DROP HP ACTION ${type}: game not in ARMED combat`,'warn');return;}\n",
        1
    )

main_js.write_text(m, encoding="utf-8")
print("LIVE FINAL Rule combat gate + native input: PASS")

c = controller_js.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# PRODUCTION RANDOM R2
# Stop using Soulcalibur sourceSlot 30 (?) for "random".
# Randomize one of the 28 actual fighters, then navigate directly to that slot.
# Shuffle-bag guarantees every fighter appears once before any repeats.
# ---------------------------------------------------------------------------

if "const crypto = require('crypto');" not in c:
    crypto_anchor = "const path = require('path');\n"
    if crypto_anchor not in c:
        raise SystemExit("LIVE FINAL R2 controller crypto import anchor missing")
    c = c.replace(crypto_anchor, crypto_anchor + "const crypto = require('crypto');\n", 1)

random_anchor = "const GIFT_TX_TTL_MS = 6 * 60 * 60 * 1000; // dedupe TikTools retries for 6 hours\n"
random_engine = r"""
const RANDOM_ROSTER = Object.freeze(
  allCharacters()
    .map(x => Object.freeze({sourceSlot:Number(x.sourceSlot), name:String(x.name||'UNKNOWN')}))
    .filter(x => Number.isInteger(x.sourceSlot) && x.sourceSlot >= 1 && x.sourceSlot <= 29 && x.sourceSlot !== 18)
);
if (RANDOM_ROSTER.length !== 28) {
  throw new Error(`RANDOM ROSTER INVALID: expected 28 fighters, got ${RANDOM_ROSTER.length}`);
}

const randomBags = {P1:[], P2:[]};
const randomLast = {P1:null, P2:null};

function resetRandomBags(){
  randomBags.P1=[];
  randomBags.P2=[];
  randomLast.P1=null;
  randomLast.P2=null;
}

function refillRandomBag(team){
  const bag=RANDOM_ROSTER.map(x=>({...x}));
  for(let i=bag.length-1;i>0;i--){
    const j=crypto.randomInt(i+1);
    [bag[i],bag[j]]=[bag[j],bag[i]];
  }

  // Do not allow the first fighter of a fresh bag to equal the last fighter
  // of the previous bag. Random stays random, but consecutive duplicates vanish.
  const prev=randomLast[team];
  if(prev!=null && bag.length>1 && bag[0].sourceSlot===prev){
    const j=bag.findIndex((x,i)=>i>0&&x.sourceSlot!==prev);
    if(j>0)[bag[0],bag[j]]=[bag[j],bag[0]];
  }

  randomBags[team]=bag;
}

function nextRandomCharacter(team='P2'){
  team=team==='P1'?'P1':'P2';
  if(!randomBags[team].length)refillRandomBag(team);
  const item=randomBags[team].shift();
  randomLast[team]=item.sourceSlot;
  return item;
}
"""
if "const RANDOM_ROSTER = Object.freeze(" not in c:
    if random_anchor not in c:
        raise SystemExit("LIVE FINAL R2 random engine anchor missing")
    c = c.replace(random_anchor, random_anchor + random_engine, 1)

# FIX7 already owns the persistent debugger tap implementation.
# Do not rewrite it here. Verify the post-FIX7 async DOWN/HOLD/UP path instead.
tap_required = (
    "  async tap(button, holdMs = 80) {",
    "event:'input.buttons.send'",
    "buttons:{[button]:true}",
    "buttons:{[button]:false}",
    "  async tap(button) { return debuggerClient.tap(button, 80); },",
)
missing_tap = [x for x in tap_required if x not in c]
if missing_tap:
    raise SystemExit(f"LIVE FINAL R2.1 post-FIX7 tap preflight missing: {missing_tap}")
print("LIVE FINAL R2.1 post-FIX7 tap path: PASS")

# Reset bag on a deliberate new session.
reset_marker = "  pickController.clear();\n  native.sendCancel().catch(() => {});"
if "  resetRandomBags();\n" not in c:
    if reset_marker not in c:
        raise SystemExit("LIVE FINAL R2 resetSession marker missing")
    c=c.replace(reset_marker,"  pickController.clear();\n  resetRandomBags();\n  native.sendCancel().catch(() => {});",1)

# Track the actual P2 random fighter in runtime state.
game_state_marker = "  lastError: '',\n"
if "  lastP2Random: null,\n" not in c:
    if game_state_marker not in c:
        raise SystemExit("LIVE FINAL R2 game state marker missing")
    c=c.replace(game_state_marker,game_state_marker+"  lastP2Random: null,\n",1)

# Replace P2 Random30 with direct 28-fighter shuffle-bag selection.
auto_start = c.find("  async autoPickAndStartNextTraining(p1SourceSlot) {\n")
auto_end = c.find("  async waitNextTrainingCombat(", auto_start)
if auto_start < 0 or auto_end < 0:
    raise SystemExit("LIVE FINAL R2 autoPick structural boundary missing")

auto_pick = r"""  async autoPickAndStartNextTraining(p1SourceSlot, p1RandomName = null) {
    this.phase = 'AUTO_PICK';

    const p2Random=nextRandomCharacter('P2');
    this.lastP2Random={...p2Random,at:now()};

    await sleep(1200);
    await this.moveCursor(p1SourceSlot, p1RandomName ? `P1 RANDOM ${p1RandomName}` : 'P1 PICK');

    await this.tap('cross'); await sleep(1200);
    await this.tap('right'); await sleep(900);
    await this.tap('cross'); await sleep(2600);
    await this.tap('cross'); await sleep(1800);

    // P2 cursor starts at Dampierre H3C3. Do NOT use sourceSlot 30 (?) anymore.
    // Pick a real fighter from the 28-character shuffle bag.
    await this.moveCursor(p2Random.sourceSlot, `P2 RANDOM ${p2Random.name}`);
    await this.tap('cross'); await sleep(1800);
    await this.tap('right'); await sleep(1200);
    await this.tap('cross'); await sleep(2800);

    await this.tap('cross'); await sleep(1400);
    await this.tap('cross'); await sleep(1400);
    await this.tap('cross');

    log(`P1 selected + P2 RANDOM BAG -> ${p2Random.name} source=${p2Random.sourceSlot} | map sequence sent`);
    return p2Random;
  },

"""
c = c[:auto_start] + auto_pick + c[auto_end:]

# Replace P1 timeout sourceSlot 30 with the same robust direct-fighter random.
continue_start = c.find("  async continueToNextRound() {\n")
continue_route = c.find("    // Restore combat code before menu/character select", continue_start)
if continue_start < 0 or continue_route < 0:
    raise SystemExit("LIVE FINAL R2 continueToNextRound boundary missing")

old_prefix = c[continue_start:continue_route]
new_prefix = r"""  async continueToNextRound() {
    const a = session.activePick;
    if (!a || !a.locked) {
      this.continueBusy = false;
      return;
    }

    const p1Random=a.timedOut ? nextRandomCharacter('P1') : null;
    const p1SourceSlot=p1Random ? p1Random.sourceSlot : Number(a.sourceSlot);

    if (!Number.isInteger(p1SourceSlot) || p1SourceSlot < 1 || p1SourceSlot > 29 || p1SourceSlot === 18) {
      throw new Error('Invalid P1 source slot: ' + p1SourceSlot);
    }

    if(p1Random){
      a.sourceSlot=p1Random.sourceSlot;
      a.character=p1Random.name;
      log(`P1 TIMEOUT RANDOM BAG -> ${p1Random.name} source=${p1Random.sourceSlot}`,'warn');
    }

"""
c = c[:continue_start] + new_prefix + c[continue_route:]

# Pass P1 random label into selection.
old_call = "    await this.autoPickAndStartNextTraining(p1SourceSlot);"
new_call = "    await this.autoPickAndStartNextTraining(p1SourceSlot,p1Random?.name||null);"
if old_call not in c:
    raise SystemExit("LIVE FINAL R2 autoPick call marker missing")
c=c.replace(old_call,new_call,1)

# Expose actual last P2 random in public state for post-live audit.
public_marker = "      error:game.lastError,\n"
if "      lastP2Random:game.lastP2Random,\n" not in c:
    if public_marker not in c:
        raise SystemExit("LIVE FINAL R2 public state marker missing")
    c=c.replace(public_marker,public_marker+"      lastP2Random:game.lastP2Random,\n",1)

# Hard production checks.
for marker in (
    "const crypto = require('crypto');",
    "RANDOM_ROSTER.length !== 28",
    "function nextRandomCharacter(team='P2')",
    "const p2Random=nextRandomCharacter('P2');",
    "P2 RANDOM BAG",
    "const p1Random=a.timedOut ? nextRandomCharacter('P1') : null;",
    "async tap(button) { return debuggerClient.tap(button, 80); },",
):
    if marker not in c:
        raise SystemExit(f"LIVE FINAL R2 random preflight missing: {marker}")

for forbidden in (
    "await this.moveCursor(30, 'P2 RANDOM')",
    "a.timedOut ? 30 : Number(a.sourceSlot)",
    "P1 selected + P2 Random30",
):
    if forbidden in c:
        raise SystemExit(f"LIVE FINAL R2 old Random30 path survived: {forbidden}")

controller_js.write_text(c, encoding="utf-8")
print("LIVE FINAL R2 production random bag: PASS")

old_p2 = "inputP2:'NOT_WIRED_GAME_INTERNAL_PATH',"
new_p2 = "inputP2:'LOGICAL_SLOT1_NATIVE_HOOK',\n      // LEGACY_WORKFLOW_COMPAT_ONLY inputP2:'NOT_WIRED_GAME_INTERNAL_PATH'"
if old_p2 in c:
    c = c.replace(old_p2, new_p2, 1)
elif "inputP2:'LOGICAL_SLOT1_NATIVE_HOOK'" not in c:
    raise SystemExit("LIVE FINAL controller P2 marker missing")

reset_anchor = "  native.sendCancel().catch(() => {});\n"
if "native.sendInputCancel().catch" not in c:
    if reset_anchor not in c:
        raise SystemExit("LIVE FINAL controller reset native cancel anchor missing")
    c = c.replace(reset_anchor, reset_anchor + "  native.sendInputCancel().catch(() => {});\n", 1)

controller_js.write_text(c, encoding="utf-8")
print("LIVE FINAL controller truth/reset: PASS")

r = renderer_js.read_text(encoding="utf-8")
test_start = r.find("function installGameTestConsole(){")
test_end = r.find("function refreshTestGiftSelect(){", test_start)
if test_start >= 0 and test_end >= 0:
    r = r[:test_start] + "function installGameTestConsole(){ return; }\n" + r[test_end:]
    print("LIVE FINAL hide app test console: PASS")
elif "function installGameTestConsole(){ return; }" not in r:
    print("LIVE FINAL hide app test console: SKIP")

state_old = "const p=s.ppsspp||{},ses=s.session||{},core=s.combatCore||{};"
state_new = "const p=s.ppsspp||{},ses=s.session||{},core=s.combatCore||{},nat=s.native||{};"
if state_old in r:
    r = r.replace(state_old, state_new, 1)
elif state_new not in r:
    raise SystemExit("LIVE FINAL renderer state declaration marker missing")

patch_marker = "$('patchMini').textContent=p.patchesApplied?'ON':'OFF';"
health_code = "$('patchMini').textContent=p.patchesApplied?'ON':'OFF';if($('p2NativeStatus')){const ps=String(nat.p2State||'WAIT');$('p2NativeStatus').textContent=ps;$('p2NativeStatus').style.color=ps==='READY'?'#5fe28b':ps==='INCOMPAT'?'#ff6f7b':'#ffd36a';}"
if "nat.p2State" not in r:
    if patch_marker not in r:
        raise SystemExit("LIVE FINAL renderer Combat Patch marker missing")
    r = r.replace(patch_marker, health_code, 1)

renderer_js.write_text(r, encoding="utf-8")

h = renderer_html.read_text(encoding="utf-8")
winner_test_row = """<div class="row"><button onclick="manualWinner('P1')">Test Winner P1</button><button onclick="manualWinner('P2')">Test Winner P2</button></div>"""
if winner_test_row in h:
    h = h.replace(winner_test_row, "", 1)
status_anchor = '<div>Combat Patch: <b id="patchMini">...</b></div>'
p2_status = status_anchor + '<div>P2 Native: <b id="p2NativeStatus">WAIT</b></div>'
if 'id="p2NativeStatus"' not in h:
    if status_anchor not in h:
        raise SystemExit("LIVE FINAL renderer statusBox marker missing")
    h = h.replace(status_anchor, p2_status, 1)
renderer_html.write_text(h, encoding="utf-8")
print("LIVE FINAL passive P2 health UI: PASS")

menu_touch = '''    if (panel == Panel::MENU) {
        if (MenuButtonRect(0, sw, sh).Contains(touch.x, touch.y)) {
            SetPanel(Panel::RANK_MENU);
            return true;
        }
        if (MenuButtonRect(1, sw, sh).Contains(touch.x, touch.y)) {
            CloseAndSwallow();
            return true;
        }
        return true;
    }
'''
replace_region(
    emu,
    "    if (panel == Panel::MENU) {\n",
    "    if (panel == Panel::RANK_MENU) {\n",
    menu_touch,
    "production in-game menu touch",
)

menu_draw = '''    if (page == Panel::MENU) {
        const char *labels[2] = {"BXH", "DONG"};
        DrawSCBDLayerButton(ctx, font, MenuButtonRect(0, sw, sh), labels[0], 0xDD273244);
        DrawSCBDLayerButton(ctx, font, MenuButtonRect(1, sw, sh), labels[1], 0xDD74343E);
    }

'''
replace_region(
    debug,
    "    if (page == Panel::MENU) {\n",
    "    if (page == Panel::RANK_MENU) {\n",
    menu_draw,
    "production in-game menu renderer",
)

d = debug.read_text(encoding="utf-8")
overlay_anchor = "    DrawSCBDInGameLayer(ctx, ubuntu24, bounds);\n"
pos = d.find(overlay_anchor)
if pos < 0:
    raise SystemExit("LIVE FINAL DrawSCBDInGameLayer anchor missing")

window_end = min(len(d), pos + len(overlay_anchor) + 2500)
before = d[:pos + len(overlay_anchor)]
window = d[pos + len(overlay_anchor):window_end]
after = d[window_end:]
kept = []
removed = []
for line in window.splitlines(keepends=True):
    sline = line.strip()
    is_direct_draw = sline.startswith("DrawSCBD") and sline.endswith(";")
    is_pick_layer = any(token in sline for token in ("Winner", "Pick", "FinalHeroPortrait"))
    if is_direct_draw and is_pick_layer:
        removed.append(sline)
    else:
        kept.append(line)
if removed:
    d = before + "".join(kept) + after
    debug.write_text(d, encoding="utf-8")
    print("LIVE FINAL hide Winner/Pick popup draw calls: PASS (" + str(len(removed)) + ")")
else:
    print("LIVE FINAL hide Winner/Pick popup draw calls: no direct call found")

m = main_js.read_text(encoding="utf-8")
r = renderer_js.read_text(encoding="utf-8")
h = renderer_html.read_text(encoding="utf-8")
c = controller_js.read_text(encoding="utf-8")
ns = native_sender.read_text(encoding="utf-8")
b = bridge.read_text(encoding="utf-8")
d = debug.read_text(encoding="utf-8")
e = emu.read_text(encoding="utf-8")
p2 = p2_header.read_text(encoding="utf-8")

required = {
    "P2 header": (p2, [
        "kHookAddr = 0x08A542B0",
        "kCaveAddr = 0x08BB8FE8",
        "kMailboxAddr = 0x08CCBF04",
        "kP2FighterPtrAddr = 0x08808A2C",
        "kHookOriginal = 0x0E294E49",
        "kHookPatched = 0x0E2EE3FA",
        "kP2ModePatched = 0xACA3F8D0",
        "0x3A690001",
        "fighterReady",
        "Core_RunOnCPUThread",
        "Memory::Read_Opcode_JIT(kHookAddr).encoding",
        "Memory::Read_Opcode_JIT(kP2ModeStoreAddr).encoding",
    ]),
    "bridge": (b, [
        'if (cmd == "INPUT")',
        'if (cmd == "INPUT_CANCEL")',
        "P2HealthText()",
        "SCBDP2LogicalInput::QueueTap",
        "SCBDVirtualInput::QueueTap",
    ]),
    "sender": (ns, [
        "function sendInput({",
        "function sendInputCancel()",
        "p2Ready:",
        "sendInput,",
        "sendInputCancel,",
    ]),
    "main": (m, [
        "function liveCombatReady()",
        "nativeSender.sendInput({",
        "DROP INPUT",
        "DROP HP ACTION",
    ]),
    "controller": (c, [
        "inputP2:'LOGICAL_SLOT1_NATIVE_HOOK'",
        "LEGACY_WORKFLOW_COMPAT_ONLY inputP2:'NOT_WIRED_GAME_INTERNAL_PATH'",
        "native.sendInputCancel().catch",
        "function nextRandomCharacter(team='P2')",
        "P2 RANDOM BAG",
        "lastP2Random:game.lastP2Random",
    ]),
    "renderer": (r + h, [
        'id="p2NativeStatus"',
        "nat.p2State",
    ]),
    "native source": (d + e, [
        "SCBDP2LogicalInput::Process();",
        'const char *labels[2] = {"BXH", "DONG"};',
        "SetPanel(Panel::RANK_MENU)",
        "DrawSCBDMatchTop5HUD",
        "MENU BANG XEP HANG",
    ]),
}
for label, (src, markers) in required.items():
    missing = [x for x in markers if x not in src]
    if missing:
        raise SystemExit(f"LIVE FINAL preflight missing in {label}: {missing}")

if "Read_Opcode_JIT(kHookAddr, true)" in p2 or "Read_Opcode_JIT(kP2ModeStoreAddr, true)" in p2:
    raise SystemExit("LIVE FINAL R2.1 obsolete Read_Opcode_JIT two-arg API survived")

for forbidden in ("await p2CodeMaskTap(", "ppsspp-p2-tap"):
    if forbidden in m:
        raise SystemExit(f"LIVE FINAL deprecated FIX12 path survived in main: {forbidden}")

for forbidden in (
    "await this.moveCursor(30, 'P2 RANDOM')",
    "a.timedOut ? 30 : Number(a.sourceSlot)",
    "P1 selected + P2 Random30",
):
    if forbidden in c:
        raise SystemExit(f"LIVE FINAL R2 old Random30 path survived: {forbidden}")

if "function installGameTestConsole(){ return; }" not in r and "flogbTestConsole" in r:
    raise SystemExit("LIVE FINAL app test console still active")
if "Test Winner P1" in h or "Test Winner P2" in h:
    raise SystemExit("LIVE FINAL manual Winner test buttons still visible")

menu_a = d.find("    if (page == Panel::MENU) {\n")
menu_b = d.find("    if (page == Panel::RANK_MENU) {\n", menu_a)
if menu_a < 0 or menu_b < 0:
    raise SystemExit("LIVE FINAL production menu boundary missing")
menu_block = d[menu_a:menu_b]
for forbidden in ("WINNER TEST", "INPUT LAB", "TEST AVATAR", "SCBD DEV", "MATCH HUD:"):
    if forbidden in menu_block:
        raise SystemExit(f"LIVE FINAL production menu still exposes: {forbidden}")

for marker in ("DrawSCBDMatchTop5HUD", "MENU BANG XEP HANG", "RankFooterCloseRect"):
    if marker not in d:
        raise SystemExit(f"LIVE FINAL required in-game surface missing: {marker}")

if build_info.exists():
    with build_info.open("a", encoding="utf-8") as f:
        f.write(
            "\nPSP FloGB LIVE FINAL\n"
            "P1 gift input: native SCBDVirtualInput over UDP\n"
            "P2 gift input: game logical slot 1 via one-time hook + mailbox\n"
            "P2 fighter forced slot=1 mode=1 while active\n"
            "Deprecated dynamic opcode-per-button FIX12 path disabled\n"
            "Input/HP actions gated to ARMED combat\n"
            "Reset session cancels P1/P2 input queues\n"
            "Passive P2 READY health shown in FloGB\n"
            "In-game UI production-only: Match Top + BXH\n"
            "Random R2: 28-fighter crypto shuffle bag; game Random30 tile disabled\n"
        )

print("LIVE FINAL SOURCE PREFLIGHT PASS")
print("P1: NATIVE INPUT QUEUE")
print("P2: LOGICAL SLOT 1 + MAILBOX")
print("P2 runtime health: READY / HOOKED / WAIT / INCOMPAT")
print("Game actions outside ARMED combat: DROPPED")
print("Random R2: 28-FIGHTER SHUFFLE BAG / NO SLOT30")
print("Visible in game: MATCH TOP + BXH")
print("=== LIVE FINAL R2.1 API-COMPAT PASS ===")
