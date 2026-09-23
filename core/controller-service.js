'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const WebSocket = require('ws');
const native = require('./native_sender_v059');
const { resolvePick, parsePickComment, allCharacters } = require('./character_resolver_v059b');

const HOST = '127.0.0.1';
const HTTP_PORT = Number(process.env.SCBD_LIVE_PORT || 8797);
const PPSSPP_URL = process.env.SCBD_PPSSPP_DEBUGGER || 'ws://127.0.0.1:9000/debugger';
const PPSSPP_PROTOCOL = 'debugger.ppsspp.org';
const TIKTOOLS_BASE = 'wss://api.tik.tools';
const CONTROL_HTML = path.join(__dirname, 'control-live-v060.html');
const GIFT_RULES_FILE = path.join(__dirname, 'gift_rules.txt');

const WINNER_INTRO_MS = 2200;
const PICK_WINDOW_MS = 15000;
const PICK_SUCCESS_MS = 4500;
const TIMEOUT_NOTICE_MS = 1800;
const POLL_HP_MS = 70;
const POLL_STATE_MS = 220;
const GIFT_TX_TTL_MS = 6 * 60 * 60 * 1000; // dedupe TikTools retries for 6 hours

// Proven ULUS10457 addresses from the Android project.
const RAM = Object.freeze({
  MODE:      0x08BCFE44,
  GATE:      0x08BD034C,
  STATE:     0x08BCFCC8,
  COMBAT:    0x08BCFC90,
  STATE3:    0x08BCFC68,
  VICTORY5:  0x08BCFC50,
  P1_HP:     0x08BE364C,
  P2_HP:     0x08BFA30C,
  V5_COUNT:  0x08BCFC54,
  V5_LIMIT:  0x08BCFC58,
});

// V20 FULL baseline previously verified in live RAM.
// We capture the current opcode first, NOP for combat, then restore before CS.
const BASE_PATCHES = Object.freeze([
  0x08814E04, 0x08814E0C, 0x08814E1C,
  0x08814EAC, 0x08814EBC, 0x08814ED4,
  0x08814FBC, 0x08814FCC,
  0x08814E24, 0x08814EDC,
  0x08814EB8, 0x08814FC8,
  0x08835D50,
  0x08816178,
]);

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const now = () => Date.now();
function hex(v) { return '0x' + ((v >>> 0).toString(16).toUpperCase().padStart(8, '0')); }
function u32ToFloat(v) {
  const b = Buffer.allocUnsafe(4);
  b.writeUInt32LE(v >>> 0, 0);
  return b.readFloatLE(0);
}

const logs = [];
function log(message, kind = 'info') {
  const row = { at: now(), kind, message: String(message) };
  logs.push(row);
  if (logs.length > 250) logs.shift();
  const stamp = new Date(row.at).toLocaleTimeString();
  console.log(`[${stamp}] ${row.message}`);
}

// -----------------------------------------------------------------------------
// Gift rules
// -----------------------------------------------------------------------------
let giftRulesRaw = '';
let giftRules = new Map();

function parseGiftRules(raw) {
  const map = new Map();
  for (const line of String(raw || '').split(/\r?\n/)) {
    const s = line.trim();
    if (!s || s.startsWith('#')) continue;
    const eq = s.lastIndexOf('=');
    if (eq <= 0 || eq >= s.length - 1) continue;
    const name = s.slice(0, eq).trim().toLowerCase();
    const value = Number(s.slice(eq + 1).trim());
    if (name && Number.isFinite(value) && value >= 0) map.set(name, Math.floor(value));
  }
  return map;
}

function loadGiftRules() {
  try { giftRulesRaw = fs.readFileSync(GIFT_RULES_FILE, 'utf8'); }
  catch { giftRulesRaw = ''; }
  giftRules = parseGiftRules(giftRulesRaw);
}
loadGiftRules();

function giftScore(giftName, diamondCount, repeatCount) {
  const count = Math.max(1, Number(repeatCount) || 1);
  const mapped = giftRules.get(String(giftName || '').trim().toLowerCase());
  if (mapped !== undefined) return mapped * count;
  return Math.max(1, Number(diamondCount) || 0) * count;
}

// -----------------------------------------------------------------------------
// Session / teams / leaderboard
// -----------------------------------------------------------------------------
const session = {
  members: new Map(),
  activePick: null,
  lastMatch: null,
  rounds: 0,
};

function normalizeTeam(v) {
  const t = String(v || '').toUpperCase();
  return t === 'P1' || t === 'P2' ? t : null;
}

function userKey(u = {}) {
  return String(u.id || u.secUid || u.uniqueId || u.nickname || '').trim().toLowerCase();
}

function displayName(u = {}) {
  return String(u.uniqueId || u.nickname || u.id || 'viewer').trim();
}

function mergeUserProfile(member, u = {}) {
  if (u.id) member.id = String(u.id);
  if (u.secUid) member.secUid = String(u.secUid);
  if (u.uniqueId) member.uniqueId = String(u.uniqueId);
  if (u.nickname) member.nickname = String(u.nickname);
  if (u.avatar) member.avatar = String(u.avatar);
  member.displayName = displayName(u) || member.displayName;
  member.lastSeenAt = now();
}

function ensureMember(u = {}) {
  const key = userKey(u);
  if (!key) return null;
  let m = session.members.get(key);
  if (!m) {
    m = {
      key,
      id: '', secUid: '', uniqueId: '', nickname: '', avatar: '',
      displayName: displayName(u),
      team: null,
      score: 0,
      gifts: 0,
      joinedAt: now(),
      lastSeenAt: now(),
    };
    session.members.set(key, m);
  }
  mergeUserProfile(m, u);
  return m;
}

function assignTeam(u, team) {
  team = normalizeTeam(team);
  const m = ensureMember(u);
  if (!m || !team) return { ok:false, reason:'INVALID_USER_OR_TEAM' };
  if (m.team && m.team !== team) {
    return { ok:false, locked:true, team:m.team, reason:'TEAM_LOCKED' };
  }
  const first = !m.team;
  m.team = team;
  return { ok:true, first, member:m };
}

function addGift(u, points) {
  const m = ensureMember(u);
  if (!m) return { ok:false, reason:'INVALID_USER' };
  if (!m.team) return { ok:false, ignored:true, reason:'NO_TEAM', member:m };
  m.score += Math.max(0, Number(points) || 0);
  m.gifts += 1;
  return { ok:true, member:m };
}

function leaderboard(team, limit = 100) {
  team = team ? normalizeTeam(team) : null;
  return [...session.members.values()]
    .filter(m => !team || m.team === team)
    .sort((a,b) => (b.score - a.score) || (a.joinedAt - b.joinedAt) || a.key.localeCompare(b.key))
    .slice(0, limit)
    .map(m => ({
      key:m.key,
      username:m.displayName,
      uniqueId:m.uniqueId,
      nickname:m.nickname,
      avatar:m.avatar,
      team:m.team,
      score:m.score,
      gifts:m.gifts,
    }));
}

function top1(team) {
  return leaderboard(team, 1)[0] || null;
}

function resetSession() {
  session.members.clear();
  session.activePick = null;
  session.lastMatch = null;
  session.rounds = 0;
  pickController.clear();
  native.sendCancel().catch(() => {});
  log('SESSION RESET: team locks + scores cleared', 'warn');
}

// -----------------------------------------------------------------------------
// Native Winner / Pick state coordination
// -----------------------------------------------------------------------------
const pickController = {
  openTimer: null,
  timeoutTimer: null,
  clear() {
    if (this.openTimer) clearTimeout(this.openTimer);
    if (this.timeoutTimer) clearTimeout(this.timeoutTimer);
    this.openTimer = null;
    this.timeoutTimer = null;
  }
};

function sameViewerKey(a, b) {
  return String(a || '').toLowerCase() === String(b || '').toLowerCase();
}

function openWinnerPick(winnerTeam) {
  pickController.clear();
  const winnerTop = top1(winnerTeam);
  const opensAt = now() + WINNER_INTRO_MS;
  const expiresAt = opensAt + PICK_WINDOW_MS;

  session.activePick = {
    winnerTeam,
    top1Key: winnerTop?.key || '',
    top1Name: winnerTop?.username || 'NO TOP1',
    top1Avatar: winnerTop?.avatar || '',
    top1Score: winnerTop?.score || 0,
    status: 'winner_intro',
    opensAt,
    expiresAt,
    pick: null,
    sourceSlot: null,
    character: null,
    decisionAt: 0,
    routeAfter: 0,
    locked: false,
    timedOut: false,
  };

  native.sendWinner({
    username: session.activePick.top1Name,
    team: winnerTeam === 'P2' ? 2 : 1,
    score: session.activePick.top1Score,
    avatar: session.activePick.top1Avatar,
  }).catch(e => log('Native WINNER error: ' + e.message, 'error'));

  log(`WINNER ${winnerTeam} | TOP1=${session.activePick.top1Name} | score=${session.activePick.top1Score}`);

  pickController.openTimer = setTimeout(() => {
    const a = session.activePick;
    if (!a || a.locked) return;
    a.status = 'open';
    log(`PICK OPEN 15s | only ${a.top1Name} may use /pick 1..28`);
  }, WINNER_INTRO_MS);

  pickController.timeoutTimer = setTimeout(() => {
    const a = session.activePick;
    if (!a || a.locked) return;
    a.locked = true;
    a.timedOut = true;
    a.status = 'timeout';
    a.sourceSlot = 30;
    a.character = 'GAME RANDOM';
    a.decisionAt = now();
    a.routeAfter = a.decisionAt + TIMEOUT_NOTICE_MS;
    native.sendTimeout().catch(e => log('Native TIMEOUT error: ' + e.message, 'error'));
    log('PICK TIMEOUT -> P1 source slot 30 RANDOM (Soulcalibur decides fighter)', 'warn');
    game.maybeContinueAfterDecision();
  }, WINNER_INTRO_MS + PICK_WINDOW_MS);
}

function processPickComment(u, text) {
  const a = session.activePick;
  if (!a) return { ok:false, reason:'NO_PICK_WINDOW' };
  if (a.locked) return { ok:false, reason:'PICK_ALREADY_LOCKED' };
  if (now() < a.opensAt || a.status === 'winner_intro') return { ok:false, reason:'PICK_NOT_OPEN' };
  if (now() > a.expiresAt) return { ok:false, reason:'PICK_EXPIRED' };
  if (!a.top1Key) return { ok:false, reason:'NO_TOP1' };

  const key = userKey(u);
  if (!sameViewerKey(key, a.top1Key)) {
    return { ok:false, reason:'NOT_WINNER_TOP1', expected:a.top1Name };
  }

  const resolved = parsePickComment(String(text || ''));
  if (!resolved) return { ok:false, reason:'INVALID_PICK' };

  a.locked = true;
  a.status = 'success';
  a.pick = resolved.pick;
  a.sourceSlot = resolved.sourceSlot;
  a.character = resolved.character;
  a.decisionAt = now();
  a.routeAfter = a.decisionAt + PICK_SUCCESS_MS;
  pickController.clear();

  native.sendPick(resolved.pick).catch(e => log('Native PICK error: ' + e.message, 'error'));
  log(`PICK LOCKED: ${a.top1Name} -> /pick ${resolved.pick} ${resolved.character} | source=${resolved.sourceSlot}`);
  game.maybeContinueAfterDecision();
  return { ok:true, resolved };
}

// -----------------------------------------------------------------------------
// TikTools real LIVE provider
// -----------------------------------------------------------------------------
const live = {
  socket: null,
  desired: false,
  reconnectTimer: null,
  liveInput: '',
  uniqueId: '',
  apiKey: '',
  connected: false,
  roomId: '',
  status: 'DISCONNECTED',
  lastEventAt: 0,
  error: '',
};

function sanitizeUser(s) {
  return String(s || '').trim().replace(/^@/, '').replace(/[^A-Za-z0-9._-]/g, '');
}

async function resolveLiveInput(raw) {
  const input = String(raw || '').trim();
  if (!input) throw new Error('Chưa nhập TikTok LIVE link hoặc @username.');
  if (input.startsWith('@')) {
    const u = sanitizeUser(input.slice(1));
    if (!u) throw new Error('Username không hợp lệ.');
    return u;
  }
  if (!input.includes('://') && !input.includes('/')) {
    const u = sanitizeUser(input);
    if (!u) throw new Error('Username không hợp lệ.');
    return u;
  }
  const direct = input.match(/https?:\/\/(?:www\.)?tiktok\.com\/@([^/?#]+)\/live/i);
  if (direct) return sanitizeUser(direct[1]);
  if (/^https?:\/\//i.test(input)) {
    if (typeof fetch !== 'function') throw new Error('Node.js cần phiên bản hỗ trợ fetch để resolve link rút gọn.');
    const response = await fetch(input, {
      redirect:'follow',
      headers:{'User-Agent':'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36'}
    });
    const finalUrl = response.url || input;
    try { if (response.body && response.body.cancel) await response.body.cancel(); } catch {}
    const m = finalUrl.match(/https?:\/\/(?:www\.)?tiktok\.com\/@([^/?#]+)\/live/i);
    if (m) return sanitizeUser(m[1]);
    const loose = finalUrl.match(/tiktok\.com\/@([^/?#]+)/i);
    if (loose) return sanitizeUser(loose[1]);
    throw new Error('Không tách được @username từ link cuối: ' + finalUrl);
  }
  throw new Error('Định dạng TikTok LIVE không nhận diện được.');
}

function parseTikUser(u, fallback = {}) {
  u = u && typeof u === 'object' ? u : {};
  fallback = fallback && typeof fallback === 'object' ? fallback : {};
  return {
    id: String(u.id || u.userId || fallback.senderUserId || fallback.userId || ''),
    uniqueId: String(u.uniqueId || fallback.user_unique_id || fallback.uniqueId || ''),
    nickname: String(u.nickname || fallback.nickname || ''),
    avatar: String(u.profilePictureUrl || u.avatar || fallback.profilePictureUrl || fallback.avatar || ''),
    secUid: String(u.secUid || fallback.secUid || ''),
  };
}

const seenGiftTransactions = new Map();
function isDuplicateGiftTransaction(data = {}) {
  const tx = String(data.transactionId || '').trim();
  if (!tx) return false;
  const t = now();
  for (const [key, at] of seenGiftTransactions) {
    if (t - at > GIFT_TX_TTL_MS) seenGiftTransactions.delete(key);
  }
  if (seenGiftTransactions.has(tx)) return true;
  seenGiftTransactions.set(tx, t);
  return false;
}

function disconnectLive(userInitiated = true) {
  live.desired = !userInitiated && live.desired;
  if (userInitiated) live.desired = false;
  if (live.reconnectTimer) clearTimeout(live.reconnectTimer);
  live.reconnectTimer = null;
  if (live.socket) {
    try { live.socket.close(1000, 'user disconnect'); } catch {}
    try { live.socket.terminate(); } catch {}
    live.socket = null;
  }
  live.connected = false;
  live.roomId = '';
  live.status = 'DISCONNECTED';
  if (userInitiated) log('TikTok LIVE disconnected', 'warn');
}

function scheduleLiveReconnect() {
  if (!live.desired || live.reconnectTimer) return;
  live.reconnectTimer = setTimeout(() => {
    live.reconnectTimer = null;
    if (live.desired && live.uniqueId && live.apiKey) connectLiveResolved(live.uniqueId, live.apiKey, true);
  }, 3000);
}

function handleTikToolsMessage(raw) {
  let root;
  try { root = JSON.parse(String(raw)); }
  catch { return; }
  const event = String(root.event || '');
  const data = root.data && typeof root.data === 'object' ? root.data : null;
  live.lastEventAt = now();

  if (event === 'roomInfo') {
    live.connected = true;
    live.roomId = String(root.roomId || '');
    live.uniqueId = sanitizeUser(root.uniqueId || live.uniqueId);
    live.status = `CONNECTED @${live.uniqueId}${live.roomId ? ' | room ' + live.roomId : ''}`;
    log('TikTools ' + live.status);
    return;
  }
  if (!data) return;

  if (event === 'chat' || event === 'comment') {
    const u = parseTikUser(data.user, data);
    const comment = String(data.comment || '').trim();
    const member = ensureMember(u);
    const who = member?.displayName || displayName(u);

    if (comment === '1' || comment === '2') {
      const team = comment === '1' ? 'P1' : 'P2';
      const result = assignTeam(u, team);
      if (result.ok && result.first) log(`TEAM LOCK: ${who} -> ${team}`);
      else if (result.reason === 'TEAM_LOCKED') log(`TEAM SWITCH BLOCKED: ${who} remains ${result.team}`, 'warn');
      return;
    }

    if (/^\/pick\b/i.test(comment)) {
      const result = processPickComment(u, comment);
      if (!result.ok && result.reason === 'NOT_WINNER_TOP1') {
        log(`PICK IGNORED: ${who} is not winner Top1 (expected ${result.expected})`, 'warn');
      }
      return;
    }
    return;
  }

  if (event === 'gift') {
    const giftName = String(data.giftName || '');
    const diamondCount = Number(data.diamondCount || 0);
    const repeatCount = Math.max(1, Number(data.repeatCount || 1));
    const repeatEnd = Object.prototype.hasOwnProperty.call(data, 'repeatEnd') ? !!data.repeatEnd : true;

    if (!repeatEnd) return; // streak gifts score only on final event
    if (isDuplicateGiftTransaction(data)) {
      log(`GIFT DUPLICATE IGNORED: ${giftName} tx=${String(data.transactionId || '').slice(0, 16)}...`, 'warn');
      return;
    }

    // v3 may preserve senderUserId even when the nested user object is truncated.
    const u = parseTikUser(data.user, data);
    const points = giftScore(giftName, diamondCount, repeatCount);
    const result = addGift(u, points);
    const who = result.member?.displayName || displayName(u);
    if (!result.ok && result.reason === 'NO_TEAM') {
      log(`GIFT IGNORED: ${who} -> ${giftName} x${repeatCount} (${points}) | viewer has no team`, 'warn');
      return;
    }
    if (result.ok) {
      log(`GIFT: ${who} [${result.member.team}] -> ${giftName} x${repeatCount} +${points} | total=${result.member.score}`);
    }
  }
}

function connectLiveResolved(uniqueId, apiKey, reconnect = false) {
  if (!uniqueId || !apiKey) throw new Error('Thiếu uniqueId hoặc TikTools API Key.');
  if (live.socket) {
    try { live.socket.terminate(); } catch {}
    live.socket = null;
  }
  live.desired = true;
  live.uniqueId = uniqueId;
  live.apiKey = apiKey;
  live.connected = false;
  live.roomId = '';
  live.error = '';
  live.status = reconnect ? `RECONNECTING @${uniqueId}` : `CONNECTING @${uniqueId}`;

  const url = `${TIKTOOLS_BASE}?uniqueId=${encodeURIComponent(uniqueId)}&apiKey=${encodeURIComponent(apiKey)}`;
  log(`${reconnect ? 'Reconnecting' : 'Connecting'} TikTools @${uniqueId}...`);

  const ws = new WebSocket(url, { handshakeTimeout: 20000 });
  live.socket = ws;

  ws.on('open', () => {
    live.status = 'WEBSOCKET OPEN | waiting roomInfo';
    log('TikTools WebSocket open, waiting roomInfo...');
  });
  ws.on('message', handleTikToolsMessage);
  ws.on('close', (code, reason) => {
    if (live.socket === ws) live.socket = null;
    live.connected = false;
    live.status = `CLOSED ${code} ${String(reason || '')}`.trim();
    if (live.desired) {
      log('TikTools disconnected, reconnect in 3s...', 'warn');
      scheduleLiveReconnect();
    }
  });
  ws.on('error', err => {
    live.error = err.message || String(err);
    log('TikTools error: ' + live.error, 'error');
  });
}

async function connectLive(rawInput, apiKey) {
  const uniqueId = await resolveLiveInput(rawInput);
  live.liveInput = String(rawInput || '');
  connectLiveResolved(uniqueId, String(apiKey || '').trim(), false);
  return uniqueId;
}

// -----------------------------------------------------------------------------
// PPSSPP Remote Debugger
// -----------------------------------------------------------------------------
class PPSSPPDebugger {
  constructor() {
    this.ws = null;
    this.connected = false;
    this.status = 'DISCONNECTED';
    this.ticket = 1;
    this.pending = new Map();
    this.reconnectTimer = null;
    this.wantConnection = true;
  }

  connect() {
    if (!this.wantConnection || this.connected || (this.ws && this.ws.readyState === WebSocket.CONNECTING)) return;
    this.status = 'CONNECTING';
    const ws = new WebSocket(PPSSPP_URL, PPSSPP_PROTOCOL, { handshakeTimeout:8000 });
    this.ws = ws;

    ws.on('open', () => {
      if (this.ws !== ws) return;
      this.connected = true;
      this.status = 'CONNECTED';
      log('PPSSPP Remote Debugger CONNECTED');
      game.onDebuggerConnected();
    });
    ws.on('message', raw => this.onMessage(raw));
    ws.on('close', () => {
      if (this.ws === ws) this.ws = null;
      this.connected = false;
      this.status = 'DISCONNECTED';
      for (const p of this.pending.values()) {
        clearTimeout(p.timer);
        p.reject(new Error('PPSSPP_DISCONNECTED'));
      }
      this.pending.clear();
      game.onDebuggerDisconnected();
      this.scheduleReconnect();
    });
    ws.on('error', err => {
      this.status = 'ERROR: ' + (err.message || err);
    });
  }

  scheduleReconnect() {
    if (!this.wantConnection || this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, 2500);
  }

  onMessage(raw) {
    let m;
    try { m = JSON.parse(String(raw)); } catch { return; }
    if (m.ticket === undefined) return;
    const p = this.pending.get(m.ticket);
    if (!p) return;
    if (p.kind === 'u32') {
      if (m.uintValue === undefined && m.value === undefined) return;
      this.pending.delete(m.ticket);
      clearTimeout(p.timer);
      p.resolve((m.uintValue ?? m.value) >>> 0);
    }
  }

  readU32(address, timeout = 1200) {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return reject(new Error('PPSSPP_NOT_OPEN'));
      const ticket = this.ticket++;
      const timer = setTimeout(() => {
        this.pending.delete(ticket);
        reject(new Error('READ_TIMEOUT ' + hex(address)));
      }, timeout);
      this.pending.set(ticket, {kind:'u32', resolve, reject, timer});
      this.ws.send(JSON.stringify({event:'memory.read_u32', ticket, address:address >>> 0}));
    });
  }

  async readRetry(address, tries = 3) {
    let last;
    for (let i=0; i<tries; i++) {
      try { return await this.readU32(address, 700); }
      catch (e) { last = e; await sleep(60); }
    }
    throw last || new Error('READ_FAILED');
  }

  writeU32(address, value) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify({event:'memory.write_u32', ticket:this.ticket++, address:address >>> 0, value:value >>> 0}));
    return true;
  }

  tap(button, duration = 2) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify({event:'input.buttons.press', ticket:this.ticket++, button, duration}));
    return true;
  }
}

const debuggerClient = new PPSSPPDebugger();

// -----------------------------------------------------------------------------
// Game automation / KO / full Character Select / next round
// -----------------------------------------------------------------------------
const game = {
  phase: 'WAIT_DEBUGGER',
  armed: false,
  cycleActive: false,
  gameReady: false,
  continueBusy: false,
  patchesApplied: false,
  patchOriginals: new Map(),
  lastP1HP: null,
  lastP2HP: null,
  lastMode: null,
  lastState: null,
  lastError: '',
  roundStartedAt: 0,
  hpLoopRunning: false,
  stateLoopRunning: false,

  async onDebuggerConnected() {
    this.phase = 'WAIT_COMBAT';
    this.lastError = '';
    if (!this.hpLoopRunning) this.hpLoop();
    if (!this.stateLoopRunning) this.stateLoop();
  },

  onDebuggerDisconnected() {
    this.phase = 'WAIT_DEBUGGER';
    this.armed = false;
    this.patchesApplied = false;
    this.patchOriginals.clear();
  },

  async applyCombatPatches() {
    if (this.patchesApplied || !debuggerClient.connected) return;
    const originals = new Map();
    for (const addr of BASE_PATCHES) {
      try {
        const current = await debuggerClient.readRetry(addr, 3);
        originals.set(addr, current >>> 0);
        if ((current >>> 0) !== 0) debuggerClient.writeU32(addr, 0);
        await sleep(18);
      } catch (e) {
        this.lastError = `Patch read failed ${hex(addr)}: ${e.message}`;
        log(this.lastError, 'error');
        return;
      }
    }
    this.patchOriginals = originals;
    this.patchesApplied = true;
    log(`COMBAT PATCHES APPLIED ${BASE_PATCHES.length}/${BASE_PATCHES.length}`);
  },

  async restoreCombatPatches() {
    if (!this.patchesApplied || !debuggerClient.connected) return;
    for (const addr of BASE_PATCHES) {
      const original = this.patchOriginals.get(addr);
      if (original !== undefined) {
        debuggerClient.writeU32(addr, original >>> 0);
        await sleep(18);
      }
    }
    this.patchesApplied = false;
    this.patchOriginals.clear();
    log('COMBAT PATCHES RESTORED');
  },

  async armIfCombat() {
    if (!debuggerClient.connected || this.cycleActive || this.armed) return;
    try {
      const mode = (await debuggerClient.readRetry(RAM.MODE, 2)) >>> 0;
      const state = (await debuggerClient.readRetry(RAM.STATE, 2)) >>> 0;
      const p1 = u32ToFloat(await debuggerClient.readRetry(RAM.P1_HP, 2));
      const p2 = u32ToFloat(await debuggerClient.readRetry(RAM.P2_HP, 2));
      this.lastMode = mode; this.lastState = state; this.lastP1HP = p1; this.lastP2HP = p2;
      if (mode === 0x19 && state === RAM.COMBAT && Number.isFinite(p1) && Number.isFinite(p2) && p1 > 1 && p2 > 1) {
        await this.applyCombatPatches();
        if (!this.patchesApplied) return;
        this.armed = true;
        this.phase = 'ARMED';
        this.roundStartedAt = now();
        log(`BATTLE ARMED | P1=${p1.toFixed(1)} P2=${p2.toFixed(1)}`);
      }
    } catch {}
  },

  async hpLoop() {
    this.hpLoopRunning = true;
    while (true) {
      if (!debuggerClient.connected) { await sleep(350); continue; }
      if (!this.armed || this.cycleActive) { await this.armIfCombat(); await sleep(180); continue; }
      try {
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
      await sleep(POLL_HP_MS);
    }
  },

  async stateLoop() {
    this.stateLoopRunning = true;
    while (true) {
      if (debuggerClient.connected) {
        try {
          this.lastMode = (await debuggerClient.readU32(RAM.MODE, 500)) >>> 0;
          this.lastState = (await debuggerClient.readU32(RAM.STATE, 500)) >>> 0;
        } catch {}
      }
      await sleep(POLL_STATE_MS);
    }
  },

  async handleKO(loser) {
    if (!this.armed || this.cycleActive) return;
    this.armed = false;
    this.cycleActive = true;
    this.gameReady = false;
    this.continueBusy = false;
    this.phase = 'KO_DETECTED';
    const winnerTeam = loser === 'P1' ? 'P2' : 'P1';
    session.rounds += 1;
    session.lastMatch = { loser, winnerTeam, at:now(), round:session.rounds };
    log(`REAL KO: ${loser} -> WINNER ${winnerTeam}`);

    openWinnerPick(winnerTeam);

    // Proven real victory path.
    debuggerClient.writeU32(RAM.GATE, 3);
    await sleep(150);
    debuggerClient.writeU32(RAM.STATE, RAM.STATE3);
    this.phase = 'OUTRO';
    log('GATE=3 + STATE3 @150ms -> real victory/outro');

    this.waitOutroAndReturn().catch(e => {
      this.lastError = e.message;
      log('OUTRO error: ' + e.message, 'error');
    });
  },

  async waitOutroAndReturn() {
    const started = now();
    let victoryEnteredAt = 0;
    let internalDone = false;

    while (now() - started < 9000) {
      try {
        const state = (await debuggerClient.readU32(RAM.STATE, 550)) >>> 0;
        this.lastState = state;
        if (state === RAM.VICTORY5) {
          if (!victoryEnteredAt) {
            victoryEnteredAt = now();
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
          if (victoryEnteredAt && now() - victoryEnteredAt >= 7500) break;
        }
      } catch {}
      if (!victoryEnteredAt && now() - started >= 6500) break;
      await sleep(140);
    }

    if (internalDone) await sleep(650);
    this.phase = 'RETURN_COMBAT';
    debuggerClient.writeU32(RAM.MODE, 0x19);
    await sleep(120);
    debuggerClient.writeU32(RAM.GATE, 0);
    await sleep(120);
    debuggerClient.writeU32(RAM.STATE, RAM.COMBAT);
    await sleep(900);
    this.gameReady = true;
    log('OUTRO COMPLETE -> clean return Training Combat');
    this.maybeContinueAfterDecision();
  },

  maybeContinueAfterDecision() {
    if (this.continueBusy || !this.cycleActive || !this.gameReady) return;
    const a = session.activePick;
    if (!a || !a.locked) return;
    const wait = Math.max(0, (a.routeAfter || now()) - now());
    this.continueBusy = true;
    setTimeout(() => this.continueToNextRound().catch(e => {
      this.lastError = e.message;
      log('NEXT ROUND error: ' + e.message, 'error');
      this.continueBusy = false;
    }), wait);
  },

  tap(button) { debuggerClient.tap(button, 2); },

  async routeToFullCharacterSelect() {
    this.phase = 'ROUTE_FULL_CS';
    log('MENU ROUTE -> FULL CHARACTER SELECT');
    this.tap('start'); await sleep(700);
    this.tap('up'); await sleep(300);
    this.tap('cross'); await sleep(700);
    this.tap('up'); await sleep(300);
    this.tap('cross'); await sleep(1500);
    this.tap('cross'); await sleep(1800);
    log('FULL CHARACTER SELECT route sent');
  },

  numberToGrid(sourceSlot) {
    const idx = sourceSlot - 1;
    return { row:Math.floor(idx / 5) + 1, col:(idx % 5) + 1 };
  },

  movesFromDampierre(sourceSlot) {
    const target = this.numberToGrid(sourceSlot);
    let row = 3, col = 3;
    const moves = [];
    while (row > target.row) { moves.push('up'); row--; }
    while (row < target.row) { moves.push('down'); row++; }
    while (col > target.col) { moves.push('left'); col--; }
    while (col < target.col) { moves.push('right'); col++; }
    return moves;
  },

  async moveCursor(sourceSlot, label) {
    const moves = this.movesFromDampierre(sourceSlot);
    const g = this.numberToGrid(sourceSlot);
    log(`${label}: source ${sourceSlot} -> H${g.row}C${g.col} | ${moves.length ? moves.join(' -> ') : '(Dampierre start)'}`);
    for (const m of moves) { this.tap(m); await sleep(450); }
    await sleep(900);
  },

  async autoPickAndStartNextTraining(p1SourceSlot) {
    this.phase = 'AUTO_PICK';
    await sleep(1200);
    await this.moveCursor(p1SourceSlot, 'P1 PICK');

    this.tap('cross'); await sleep(1200);
    this.tap('right'); await sleep(900);
    this.tap('cross'); await sleep(2600);
    this.tap('cross'); await sleep(1800);

    // P2 cursor restarts at Dampierre H3C3. Random = source slot 30 = H6C5.
    await this.moveCursor(30, 'P2 RANDOM');
    this.tap('cross'); await sleep(1800);
    this.tap('right'); await sleep(1200);
    this.tap('cross'); await sleep(2800);

    this.tap('cross'); await sleep(1400);
    this.tap('cross'); await sleep(1400);
    this.tap('cross');
    log('P1 selected + P2 Random30 + map sequence sent');
  },

  async waitNextTrainingCombat(timeoutMs = 35000) {
    const start = now();
    this.phase = 'WAIT_NEXT_COMBAT';
    while (now() - start < timeoutMs) {
      try {
        const mode = (await debuggerClient.readRetry(RAM.MODE, 2)) >>> 0;
        const state = (await debuggerClient.readRetry(RAM.STATE, 2)) >>> 0;
        const p1 = u32ToFloat(await debuggerClient.readRetry(RAM.P1_HP, 2));
        const p2 = u32ToFloat(await debuggerClient.readRetry(RAM.P2_HP, 2));
        this.lastMode=mode; this.lastState=state; this.lastP1HP=p1; this.lastP2HP=p2;
        if (mode === 0x19 && state === RAM.COMBAT && Number.isFinite(p1) && Number.isFinite(p2) && p1 > 1 && p2 > 1) {
          return true;
        }
      } catch {}
      await sleep(500);
    }
    return false;
  },

  async continueToNextRound() {
    const a = session.activePick;
    if (!a || !a.locked) {
      this.continueBusy = false;
      return;
    }
    const p1SourceSlot = a.timedOut ? 30 : Number(a.sourceSlot);
    if (!Number.isInteger(p1SourceSlot) || p1SourceSlot < 1 || p1SourceSlot > 30 || p1SourceSlot === 18) {
      throw new Error('Invalid P1 source slot: ' + p1SourceSlot);
    }

    // Restore combat code before menu/character select, matching proven V1.6 behavior.
    await this.restoreCombatPatches();
    await this.routeToFullCharacterSelect();
    await this.autoPickAndStartNextTraining(p1SourceSlot);

    const ok = await this.waitNextTrainingCombat();
    if (!ok) {
      this.phase = 'NEXT_COMBAT_TIMEOUT';
      this.continueBusy = false;
      log('TIMEOUT waiting next Training Combat', 'error');
      return;
    }

    await this.applyCombatPatches();
    this.cycleActive = false;
    this.gameReady = false;
    this.continueBusy = false;
    this.armed = this.patchesApplied;
    this.phase = this.armed ? 'ARMED' : 'WAIT_COMBAT';
    session.activePick = null;
    log(`NEXT ROUND READY | P1 source=${p1SourceSlot} | P2=Random30`);
  },

  async manualWinner(team) {
    team = normalizeTeam(team);
    if (!team) throw new Error('team must be P1 or P2');
    if (this.cycleActive) throw new Error('cycle already active');
    const loser = team === 'P1' ? 'P2' : 'P1';
    await this.handleKO(loser);
  },
};

debuggerClient.connect();

// -----------------------------------------------------------------------------
// HTTP control server
// -----------------------------------------------------------------------------
function publicState() {
  const a = session.activePick;
  return {
    version:'1.1.0-unified-combat-core',
    combatCore:{antiHeal:true,realKO:true,outro:true,winnerPick:true,fullCharacterSelect:true,p2Random30:true,ranking:true},
    native:native.getStatus(),
    ppsspp:{
      connected:debuggerClient.connected,
      status:debuggerClient.status,
      url:PPSSPP_URL,
      gamePhase:game.phase,
      armed:game.armed,
      cycleActive:game.cycleActive,
      patchesApplied:game.patchesApplied,
      p1HP:Number.isFinite(game.lastP1HP) ? Number(game.lastP1HP.toFixed(2)) : null,
      p2HP:Number.isFinite(game.lastP2HP) ? Number(game.lastP2HP.toFixed(2)) : null,
      mode:game.lastMode === null ? null : hex(game.lastMode),
      state:game.lastState === null ? null : hex(game.lastState),
      error:game.lastError,
    },
    live:{
      connected:live.connected,
      status:live.status,
      uniqueId:live.uniqueId,
      roomId:live.roomId,
      lastEventAt:live.lastEventAt,
      error:live.error,
    },
    session:{
      rounds:session.rounds,
      memberCount:session.members.size,
      top1P1:top1('P1'),
      top1P2:top1('P2'),
      leaderboardP1:leaderboard('P1', 20),
      leaderboardP2:leaderboard('P2', 20),
      activePick:a,
      lastMatch:session.lastMatch,
    },
    giftRules:giftRulesRaw,
    characters:allCharacters(),
    logs:logs.slice(-100),
  };
}

function sendJson(res, status, obj) {
  const body = Buffer.from(JSON.stringify(obj));
  res.writeHead(status, {
    'Content-Type':'application/json; charset=utf-8',
    'Content-Length':body.length,
    'Cache-Control':'no-store',
    'Access-Control-Allow-Origin':'*',
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', c => {
      raw += c;
      if (raw.length > 1024 * 1024) reject(new Error('BODY_TOO_LARGE'));
    });
    req.on('end', () => {
      if (!raw) return resolve({});
      try { resolve(JSON.parse(raw)); }
      catch { reject(new Error('INVALID_JSON')); }
    });
    req.on('error', reject);
  });
}

async function handleApi(req, res, pathname) {
  if (req.method === 'GET' && pathname === '/api/state') return sendJson(res, 200, {ok:true, ...publicState()});

  if (req.method === 'POST' && pathname === '/api/live/connect') {
    const body = await readBody(req);
    if (!String(body.apiKey || '').trim()) throw new Error('Chưa nhập TikTools API Key.');
    const uniqueId = await connectLive(body.liveInput, body.apiKey);
    return sendJson(res, 200, {ok:true, uniqueId});
  }
  if (req.method === 'POST' && pathname === '/api/live/disconnect') {
    disconnectLive(true);
    return sendJson(res, 200, {ok:true});
  }
  if (req.method === 'POST' && pathname === '/api/session/reset') {
    resetSession();
    return sendJson(res, 200, {ok:true});
  }
  if (req.method === 'POST' && pathname === '/api/gift-rules') {
    const body = await readBody(req);
    giftRulesRaw = String(body.rules || '');
    giftRules = parseGiftRules(giftRulesRaw);
    fs.writeFileSync(GIFT_RULES_FILE, giftRulesRaw, 'utf8');
    log(`Gift rules updated: ${giftRules.size} custom rules`);
    return sendJson(res, 200, {ok:true, count:giftRules.size});
  }

  // Local test tools use the same real session engine.
  if (req.method === 'POST' && pathname === '/api/test/team') {
    const b = await readBody(req);
    const u = {uniqueId:String(b.username || 'TEST_VIEWER'), nickname:String(b.username || 'TEST_VIEWER'), avatar:''};
    return sendJson(res, 200, {ok:true, result:assignTeam(u, b.team)});
  }
  if (req.method === 'POST' && pathname === '/api/test/gift') {
    const b = await readBody(req);
    const u = {uniqueId:String(b.username || 'TEST_VIEWER'), nickname:String(b.username || 'TEST_VIEWER'), avatar:''};
    const support = Math.max(0, Number(b.support ?? b.points) || 0);
    return sendJson(res, 200, {ok:true, result:addGift(u, support)});
  }
  if (req.method === 'POST' && pathname === '/api/test/comment') {
    const b = await readBody(req);
    const u = {uniqueId:String(b.username || 'TEST_VIEWER'), nickname:String(b.username || 'TEST_VIEWER'), avatar:''};
    return sendJson(res, 200, {ok:true, result:processPickComment(u, b.comment)});
  }
  if (req.method === 'POST' && pathname === '/api/test/winner') {
    const b = await readBody(req);
    const team = normalizeTeam(b.team);
    if (!team) throw new Error('team phải là P1/P2');
    if (game.cycleActive) throw new Error('Game cycle đang chạy.');
    openWinnerPick(team);
    return sendJson(res, 200, {ok:true, activePick:session.activePick});
  }
  if (req.method === 'POST' && pathname === '/api/manual/ko') {
    const b = await readBody(req);
    await game.manualWinner(b.winnerTeam);
    return sendJson(res, 200, {ok:true});
  }

  sendJson(res, 404, {ok:false, error:'NOT_FOUND'});
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host || HOST}`);
    if (url.pathname.startsWith('/api/')) return await handleApi(req, res, url.pathname);
    if (req.method === 'GET' && (url.pathname === '/' || url.pathname === '/index.html')) {
      const html = fs.readFileSync(CONTROL_HTML);
      res.writeHead(200, {'Content-Type':'text/html; charset=utf-8','Content-Length':html.length,'Cache-Control':'no-store'});
      return res.end(html);
    }
    sendJson(res, 404, {ok:false,error:'NOT_FOUND'});
  } catch (e) {
    log('HTTP error: ' + e.message, 'error');
    sendJson(res, 400, {ok:false,error:e.message});
  }
});

server.on('error', err => {
  if (err && err.code === 'EADDRINUSE') {
    console.error(`\n[SCBD] Port ${HTTP_PORT} đang bị dùng. Hãy dừng Bridge cũ bằng Ctrl+C rồi chạy lại.\n`);
  } else {
    console.error(err);
  }
  process.exit(1);
});

server.listen(HTTP_PORT, HOST, () => {
  log(`SCBD TikTok LIVE V0.6.0R1 control ready: http://${HOST}:${HTTP_PORT}/`);
  log('Waiting PPSSPP Remote Debugger + TikTools LIVE connection...');
});

async function shutdown() {
  log('Shutting down... restoring combat patches if possible', 'warn');
  live.desired = false;
  try { disconnectLive(true); } catch {}
  try { await game.restoreCombatPatches(); } catch {}
  try { native.sendCancel().catch(()=>{}); } catch {}
  try { server.close(); } catch {}
  try { debuggerClient.wantConnection = false; debuggerClient.ws?.terminate(); } catch {}
  setTimeout(() => process.exit(0), 200).unref();
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
