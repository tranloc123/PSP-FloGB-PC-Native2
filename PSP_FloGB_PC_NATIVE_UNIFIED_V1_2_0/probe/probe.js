(() => {
  try {
    if (window.__SCBD_LOCAL_PROBE__ && window.__SCBD_LOCAL_PROBE__.dispose) {
      window.__SCBD_LOCAL_PROBE__.dispose();
    }
  } catch (_) {}

  const VERSION = "dev-probe-0.4.0-scoring-bridge";
  let active = true;
  let observer = null;

  const seenDom = new Map();
  const identityQueue = [];
  const MAX_QUEUE = 120;
  const MAX_QUEUE_AGE = 10000;
  const td = new TextDecoder("utf-8", { fatal: false });

  // Gift combo state. TikTok combo messages usually send cumulative repeatCount
  // (1 -> 2 -> 3), so game scoring must use delta (1,1,1), not 1+2+3.
  const giftComboState = new Map();
  const seenGiftTransactions = new Map();
  const GIFT_STATE_TTL = 15000;
  const GIFT_FALLBACK_TTL = 4500;
  let fullFrameNoticeSent = false;


  function clean(s) {
    return String(s || "").replace(/\s+/g, " ").trim();
  }

  function report(kind, obj) {
    try {
      SCBD.report(kind, typeof obj === "string" ? obj : JSON.stringify(obj));
    } catch (_) {}
  }

  // ==========================================================
  // SCBD EVENT NORMALIZER V1
  // ==========================================================

  let normalizedSeq = 0;
  const NORMALIZED_SCHEMA = "scbd.event.v1";

  // ==========================================================
  // SCORING BRIDGE V1
  // Emits only authoritative, scoring-safe TikTok events.
  // No arbitrary game point values are hard-coded here.
  // The game/controller can map `units` / `diamonds` to its own rules.
  // ==========================================================

  const SCORING_SCHEMA = "scbd.scoring.v1";
  const scoringSeen = new Map();
  const SCORING_DEDUPE_TTL = 60000;

  function cleanupScoringSeen(now) {
    for (const [k, ts] of scoringSeen.entries()) {
      if (now - ts > SCORING_DEDUPE_TTL) scoringSeen.delete(k);
    }
  }

  function scoringKey(evt) {
    if (!evt) return "";

    if (evt.type === "gift" && evt.payload && evt.payload.transactionId) {
      return [
        "gift",
        evt.room && evt.room.streamer || "",
        evt.payload.transactionId
      ].join(":");
    }

    return String(evt.eventId || "");
  }

  function makeScoringEvent(evt) {
    if (!evt || !evt.meta || evt.meta.scoringSafe !== true) return null;

    if (evt.type !== "gift" && evt.type !== "like") return null;

    const base = {
      schema: SCORING_SCHEMA,
      scoringId: scoringKey(evt),
      sourceEventId: String(evt.eventId || ""),
      type: String(evt.type || ""),
      ts: Number(evt.ts || Date.now()),
      room: {
        streamer: String(evt.room && evt.room.streamer || ""),
        roomId: String(evt.room && evt.room.roomId || "")
      },
      user: {
        id: String(evt.user && evt.user.id || ""),
        uniqueId: String(evt.user && evt.user.uniqueId || ""),
        nickname: String(evt.user && evt.user.nickname || ""),
        avatar: String(evt.user && evt.user.avatar || "")
      },
      units: 0,
      diamonds: 0,
      payload: {},
      meta: {
        authoritative: true,
        scoringSafe: true,
        source: String(evt.meta.source || ""),
        wsMethod: String(evt.meta.wsMethod || "")
      }
    };

    if (evt.type === "like") {
      base.units = Math.max(0, Number(evt.payload && evt.payload.count || 0));
      base.payload = {
        count: base.units,
        totalLikeCount: Math.max(0, Number(evt.payload && evt.payload.totalLikeCount || 0))
      };
    } else if (evt.type === "gift") {
      const delta = Math.max(0, Number(evt.payload && evt.payload.comboDelta || 0));
      const diamondDelta = Math.max(0, Number(evt.payload && evt.payload.diamondDelta || 0));

      base.units = delta;
      base.diamonds = diamondDelta;
      base.payload = {
        giftId: String(evt.payload && evt.payload.giftId || ""),
        giftName: String(evt.payload && evt.payload.giftName || ""),
        repeatCount: Math.max(0, Number(evt.payload && evt.payload.repeatCount || 0)),
        comboDelta: delta,
        diamondCount: Math.max(0, Number(evt.payload && evt.payload.diamondCount || 0)),
        diamondDelta,
        transactionId: String(evt.payload && evt.payload.transactionId || ""),
        comboId: String(evt.payload && evt.payload.comboId || "")
      };
    }

    if (base.units <= 0) return null;
    return base;
  }

  function reportScoringEvent(evt) {
    const scoring = makeScoringEvent(evt);
    if (!scoring) return;

    const now = Date.now();
    cleanupScoringSeen(now);

    if (scoring.scoringId && scoringSeen.has(scoring.scoringId)) {
      report("SCORING_DUPLICATE_DROP", {
        scoringId: scoring.scoringId,
        type: scoring.type,
        ts: now
      });
      return;
    }

    if (scoring.scoringId) scoringSeen.set(scoring.scoringId, now);
    report("SCORING_EVENT", scoring);
  }

  function currentStreamer() {
    try {
      const m = String(location.pathname || "").match(/^\/@([^/]+)\/live/i);
      return m ? decodeURIComponent(m[1]) : "";
    } catch (_) {
      return "";
    }
  }

  function makeEventId(type, userId, ts) {
    normalizedSeq = (normalizedSeq + 1) >>> 0;
    return [
      "scbd",
      String(ts || Date.now()),
      String(normalizedSeq),
      String(type || "unknown"),
      String(userId || "anon")
    ].join(":");
  }

  function normalizedUser(raw) {
    raw = raw || {};

    return {
      id: String(raw.userId || ""),
      uniqueId: String(raw.uniqueId || ""),
      nickname: String(raw.nickname || ""),
      secUid: String(raw.secUid || ""),
      avatar: String(raw.avatar || "")
    };
  }

  function normalizeEvent(raw) {
    if (!raw || !raw.type) return null;

    const ts = Number(raw.ts || Date.now());
    const user = normalizedUser(raw);
    const type = String(raw.type);

    const out = {
      schema: NORMALIZED_SCHEMA,
      eventId: makeEventId(type, user.id, ts),
      type,
      ts,

      room: {
        streamer: currentStreamer(),
        roomId: ""
      },

      user,

      payload: {},
      meta: {
        source: String(raw.source || raw.identitySource || "dom"),
        wsMethod: String(raw.wsMethod || ""),
        identitySource: String(raw.identitySource || ""),
        authoritative: false,
        scoringSafe: false
      }
    };

    if (type === "comment") {
      out.payload = {
        text: String(raw.content || "")
      };

      out.meta.authoritative = true;
      out.meta.scoringSafe = true;

    } else if (type === "join") {
      out.payload = {};

      out.meta.authoritative = true;
      out.meta.scoringSafe = true;

    } else if (type === "like") {
      out.payload = {
        count: Number(raw.count || 0),
        totalLikeCount: Number(raw.totalLikeCount || 0)
      };

      // Like count comes directly from WebcastLikeMessage.
      out.meta.authoritative =
        raw.source === "tiktok_websocket" &&
        raw.wsMethod === "WebcastLikeMessage";

      out.meta.scoringSafe = out.meta.authoritative;

    } else if (type === "gift") {
      out.payload = {
        giftName: String(raw.giftName || ""),
        quantity: Number(raw.quantity || 1),
        repeatCount: Number(raw.repeatCount || raw.quantity || 1),
        comboDelta: Number(raw.comboDelta || raw.quantity || 1),
        giftId: String(raw.giftId || ""),
        diamondCount: Number(raw.diamondCount || 0),
        diamondDelta: Number(raw.diamondDelta || 0),
        transactionId: String(raw.transactionId || ""),
        comboId: String(raw.comboId || "")
      };

      const safeWsGift =
        raw.source === "tiktok_websocket" &&
        raw.wsMethod === "WebcastGiftMessage" &&
        Number(raw.comboDelta || raw.quantity || 0) > 0 &&
        !!raw.giftId;

      out.meta.authoritative = safeWsGift;
      out.meta.scoringSafe = safeWsGift;

    } else if (type === "share" || type === "follow") {
      out.payload = {};

      out.meta.authoritative = true;
      out.meta.scoringSafe = true;

    } else {
      out.payload = {
        rawText: String(raw.text || raw.content || "")
      };
    }

    return out;
  }

  function reportEvent(raw) {
    report("EVENT", raw);

    const normalized = normalizeEvent(raw);
    if (normalized) {
      report("NORMALIZED_EVENT", normalized);
      reportScoringEvent(normalized);
    }
  }

  // ==========================================================
  // PROTOBUF DECODER
  // ==========================================================

  function readVarint(u8, pos, end) {
    let v = 0n;
    let shift = 0n;

    while (pos < end && shift <= 70n) {
      const b = BigInt(u8[pos++]);
      v |= (b & 0x7fn) << shift;

      if ((b & 0x80n) === 0n) {
        return { value: v, pos };
      }

      shift += 7n;
    }

    throw new Error("bad-varint");
  }

  function parseMessage(u8, start = 0, end = u8.length, depth = 0) {
    const fields = [];
    let pos = start;
    let guard = 0;

    try {
      while (pos < end && guard++ < 5000) {
        const key = readVarint(u8, pos, end);
        pos = key.pos;

        const fieldNo = Number(key.value >> 3n);
        const wire = Number(key.value & 7n);

        if (!fieldNo || ![0, 1, 2, 5].includes(wire)) {
          return { ok: false, fields: [], consumed: pos - start };
        }

        if (wire === 0) {
          const x = readVarint(u8, pos, end);
          pos = x.pos;

          fields.push({
            no: fieldNo,
            wire,
            value: x.value
          });

        } else if (wire === 1) {
          if (pos + 8 > end) {
            return { ok: false, fields: [], consumed: pos - start };
          }

          fields.push({
            no: fieldNo,
            wire,
            bytes: u8.slice(pos, pos + 8)
          });

          pos += 8;

        } else if (wire === 5) {
          if (pos + 4 > end) {
            return { ok: false, fields: [], consumed: pos - start };
          }

          fields.push({
            no: fieldNo,
            wire,
            bytes: u8.slice(pos, pos + 4)
          });

          pos += 4;

        } else {
          const l = readVarint(u8, pos, end);
          pos = l.pos;

          if (l.value > BigInt(end - pos)) {
            return { ok: false, fields: [], consumed: pos - start };
          }

          const len = Number(l.value);
          const bytes = u8.slice(pos, pos + len);
          pos += len;

          let str = "";
          try {
            str = td.decode(bytes);
          } catch (_) {}

          let nested = null;

          if (depth < 8 && bytes.length > 0) {
            try {
              const p = parseMessage(bytes, 0, bytes.length, depth + 1);

              if (p.ok && p.consumed === bytes.length && p.fields.length) {
                nested = p;
              }
            } catch (_) {}
          }

          fields.push({
            no: fieldNo,
            wire,
            bytes,
            str,
            nested
          });
        }
      }

      return {
        ok: pos === end,
        fields,
        consumed: pos - start
      };

    } catch (_) {
      return {
        ok: false,
        fields: [],
        consumed: pos - start
      };
    }
  }

  function fieldsByNo(msg, no) {
    return (msg && msg.fields ? msg.fields : []).filter(f => f.no === no);
  }

  function firstVarint(msg, no) {
    const f = fieldsByNo(msg, no).find(x => x.wire === 0);
    return f ? f.value : null;
  }

  function firstString(msg, no) {
    const f = fieldsByNo(msg, no).find(x => x.wire === 2 && x.str);
    return f ? clean(f.str) : "";
  }

  function firstNested(msg, no) {
    const f = fieldsByNo(msg, no).find(x => x.wire === 2 && x.nested);
    return f ? f.nested : null;
  }

  function walkMessages(msg, fn, depth = 0) {
    if (!msg || depth > 9) return;

    fn(msg);

    for (const f of msg.fields || []) {
      if (f.nested) {
        walkMessages(f.nested, fn, depth + 1);
      }
    }
  }

  function printable(s) {
    if (!s || s.length > 500) return false;

    let good = 0;

    for (const ch of s) {
      if (ch >= " " || ch === "\n" || ch === "\t") good++;
    }

    return good / Math.max(1, s.length) > 0.88;
  }

  function findMethod(msg) {
    let found = "";

    walkMessages(msg, m => {
      if (found) return;

      for (const f of m.fields || []) {
        if (f.wire !== 2 || !f.str || !printable(f.str)) continue;

        const s = clean(f.str);

        if (/^Webcast[A-Za-z0-9_]+Message$/.test(s)) {
          found = s;
          return;
        }
      }
    });

    return found;
  }

  function avatarFromUser(userMsg) {
    const imageMsg = firstNested(userMsg, 9);
    if (!imageMsg) return "";

    const urls = fieldsByNo(imageMsg, 1)
      .filter(x => x.wire === 2 && x.str && /^https?:\/\//i.test(x.str))
      .map(x => x.str);

    return urls[0] || "";
  }

  function userCandidates(msg) {
    const out = [];

    walkMessages(msg, m => {
      const id = firstVarint(m, 1);
      const nickname = firstString(m, 3);
      const uniqueId = firstString(m, 38);
      const secUid = firstString(m, 46);

      if (
        id !== null &&
        id > 1000000000000000n &&
        nickname &&
        uniqueId
      ) {
        out.push({
          userId: id.toString(),
          nickname,
          uniqueId,
          secUid,
          avatar: avatarFromUser(m)
        });
      }
    });

    const ids = new Set();

    return out.filter(u => {
      if (ids.has(u.userId)) return false;
      ids.add(u.userId);
      return true;
    });
  }

  function userFromMessage(userMsg) {
    if (!userMsg) return null;

    const id = firstVarint(userMsg, 1);
    const nickname = firstString(userMsg, 3);
    const uniqueId = firstString(userMsg, 38);
    const secUid = firstString(userMsg, 46);

    if (
      id === null ||
      id <= 1000000000000000n ||
      !nickname
    ) {
      return null;
    }

    return {
      userId: id.toString(),
      nickname,
      uniqueId,
      secUid,
      avatar: avatarFromUser(userMsg)
    };
  }

  function extractLikePayload(msg) {
    let found = null;

    walkMessages(msg, m => {
      if (found) return;

      const userMsg = firstNested(m, 5);
      if (!userMsg) return;

      const user = userFromMessage(userMsg);
      if (!user) return;

      const countV = firstVarint(m, 2);
      const totalV = firstVarint(m, 3);

      if (countV === null || totalV === null) return;

      const count = Number(countV);
      const totalLikeCount = Number(totalV);

      if (
        !Number.isFinite(count) ||
        count <= 0 ||
        count > 100000 ||
        !Number.isFinite(totalLikeCount) ||
        totalLikeCount < 0
      ) {
        return;
      }

      found = {
        user,
        count,
        totalLikeCount
      };
    });

    return found;
  }

  function extractGiftPayload(msg) {
    let found = null;

    walkMessages(msg, m => {
      if (found) return;

      const userMsg = firstNested(m, 7);
      const giftMsg = firstNested(m, 15);

      if (!userMsg || !giftMsg) return;

      const user = userFromMessage(userMsg);
      if (!user) return;

      const giftIdV = firstVarint(m, 2);
      const repeatV = firstVarint(m, 5);
      const comboV = firstVarint(m, 11);
      const transactionId = firstString(m, 16);

      if (giftIdV === null || repeatV === null) return;

      const giftId = giftIdV.toString();
      const repeatCount = Number(repeatV);

      const giftObjectIdV = firstVarint(giftMsg, 5);
      const diamondV = firstVarint(giftMsg, 7);
      const giftName =
        firstString(giftMsg, 16) ||
        firstString(giftMsg, 2);

      if (!giftName || !Number.isFinite(repeatCount) || repeatCount <= 0) {
        return;
      }

      if (
        giftObjectIdV !== null &&
        giftObjectIdV.toString() !== giftId
      ) {
        return;
      }

      found = {
        user,
        giftId,
        repeatCount,
        comboId: comboV !== null ? comboV.toString() : "",
        transactionId,
        giftName,
        diamondCount: diamondV !== null ? Number(diamondV) : 0
      };
    });

    return found;
  }

  function cleanupGiftState(now) {
    for (const [k, v] of giftComboState.entries()) {
      if (now - v.ts > GIFT_STATE_TTL) {
        giftComboState.delete(k);
      }
    }

    for (const [tx, ts] of seenGiftTransactions.entries()) {
      if (now - ts > GIFT_STATE_TTL) {
        seenGiftTransactions.delete(tx);
      }
    }
  }

  function giftDeltaFor(gift, now) {
    cleanupGiftState(now);

    if (gift.transactionId) {
      if (seenGiftTransactions.has(gift.transactionId)) {
        return {
          duplicate: true,
          delta: 0,
          key: ""
        };
      }

      seenGiftTransactions.set(gift.transactionId, now);
    }

    const room = currentStreamer();
    const stableCombo = gift.comboId;

    const key = stableCombo
      ? [
          room,
          gift.user.userId,
          gift.giftId,
          stableCombo
        ].join("|")
      : [
          room,
          gift.user.userId,
          gift.giftId,
          "fallback"
        ].join("|");

    const prev = giftComboState.get(key);

    let delta = gift.repeatCount;

    if (prev) {
      const age = now - prev.ts;

      if (
        stableCombo ||
        age <= GIFT_FALLBACK_TTL
      ) {
        if (gift.repeatCount >= prev.repeatCount) {
          delta = gift.repeatCount - prev.repeatCount;
        } else {
          // Counter reset means a new combo/session.
          delta = gift.repeatCount;
        }
      }
    }

    giftComboState.set(key, {
      repeatCount: gift.repeatCount,
      ts: now,
      transactionId: gift.transactionId
    });

    return {
      duplicate: false,
      delta: Math.max(0, delta),
      key
    };
  }

  function b64ToBytes(b64) {
    const s = atob(String(b64 || ""));
    const u8 = new Uint8Array(s.length);

    for (let i = 0; i < s.length; i++) {
      u8[i] = s.charCodeAt(i) & 255;
    }

    return u8;
  }

  function findGzip(u8) {
    for (let i = 0; i + 1 < u8.length; i++) {
      if (u8[i] === 0x1f && u8[i + 1] === 0x8b) return i;
    }

    return -1;
  }

  async function gunzip(u8) {
    if (typeof DecompressionStream === "undefined") {
      throw new Error("DecompressionStream unavailable");
    }

    const ds = new DecompressionStream("gzip");
    const blob = new Blob([u8]);
    const ab = await new Response(
      blob.stream().pipeThrough(ds)
    ).arrayBuffer();

    return new Uint8Array(ab);
  }

  function trimQueue(now = Date.now()) {
    while (
      identityQueue.length &&
      now - identityQueue[0].ts > MAX_QUEUE_AGE
    ) {
      identityQueue.shift();
    }

    while (identityQueue.length > MAX_QUEUE) {
      identityQueue.shift();
    }
  }

  function pushIdentity(method, users) {
    const ts = Date.now();

    for (const user of users) {
      identityQueue.push({
        ts,
        method,
        user
      });
    }

    trimQueue(ts);
  }

  function responseContainers(parsed) {
    const out = [];

    for (const f of fieldsByNo(parsed, 1)) {
      if (f.wire !== 2 || !f.nested) continue;

      const container = f.nested;
      const method = firstString(container, 1);

      if (!/^Webcast[A-Za-z0-9_]+Message$/.test(method)) continue;

      const payloadField = fieldsByNo(container, 2)
        .find(x => x.wire === 2 && x.bytes);

      if (!payloadField) continue;

      let payload = payloadField.nested;

      if (!payload && payloadField.bytes && payloadField.bytes.length) {
        try {
          const p = parseMessage(
            payloadField.bytes,
            0,
            payloadField.bytes.length
          );
          if (p.ok) payload = p;
        } catch (_) {}
      }

      if (!payload) continue;

      const msgIdV = firstVarint(container, 3);

      out.push({
        method,
        payload,
        msgId: msgIdV !== null ? msgIdV.toString() : ""
      });
    }

    // Compatibility fallback for frames whose wrapper shape differs.
    if (!out.length) {
      const method = findMethod(parsed);
      if (method) {
        out.push({
          method,
          payload: parsed,
          msgId: ""
        });
      }
    }

    return out;
  }

  function handleDecodedContainer(item) {
    const method = item.method;
    const payload = item.payload;
    const msgId = item.msgId || "";

    if (method === "WebcastLikeMessage") {
      const like = extractLikePayload(payload);

      if (like) {
        pushIdentity(method, [like.user]);

        reportEvent({
          type: "like",
          source: "tiktok_websocket",
          count: like.count,
          totalLikeCount: like.totalLikeCount,
          userId: like.user.userId,
          nickname: like.user.nickname,
          uniqueId: like.user.uniqueId,
          secUid: like.user.secUid,
          avatar: like.user.avatar,
          wsMethod: method,
          wsMsgId: msgId,
          ts: Date.now()
        });
      }

      return;
    }

    if (method === "WebcastGiftMessage") {
      const gift = extractGiftPayload(payload);

      if (!gift) {
        report("GIFT_WS_DECODE_FAIL", {
          ts: Date.now(),
          msgId,
          topFields: (payload.fields || []).map(f => ({
            no: f.no,
            wire: f.wire,
            len: f.bytes ? f.bytes.length : 0
          })).slice(0, 40)
        });
        return;
      }

      const now = Date.now();
      const combo = giftDeltaFor(gift, now);

      pushIdentity(method, [gift.user]);

      report("GIFT_WS", {
        ts: now,
        msgId,
        giftId: gift.giftId,
        giftName: gift.giftName,
        repeatCount: gift.repeatCount,
        comboDelta: combo.delta,
        comboId: gift.comboId,
        transactionId: gift.transactionId,
        diamondCount: gift.diamondCount,
        userId: gift.user.userId,
        nickname: gift.user.nickname,
        duplicate: combo.duplicate
      });

      if (!combo.duplicate && combo.delta > 0) {
        reportEvent({
          type: "gift",
          source: "tiktok_websocket",
          giftName: gift.giftName,
          quantity: combo.delta,
          comboDelta: combo.delta,
          repeatCount: gift.repeatCount,
          giftId: gift.giftId,
          diamondCount: gift.diamondCount,
          diamondDelta: gift.diamondCount > 0
            ? gift.diamondCount * combo.delta
            : 0,
          comboId: gift.comboId,
          transactionId: gift.transactionId,
          userId: gift.user.userId,
          nickname: gift.user.nickname,
          uniqueId: gift.user.uniqueId,
          secUid: gift.user.secUid,
          avatar: gift.user.avatar,
          wsMethod: method,
          wsMsgId: msgId,
          ts: now
        });
      }

      return;
    }

    const users = userCandidates(payload);
    if (!users.length) return;

    pushIdentity(method, users);

    report("WS_IDENTITY", {
      ts: Date.now(),
      method,
      msgId,
      users
    });
  }

  async function decodeWs(detail) {
    if (!active || !detail || detail.kind !== "binary") return;

    const d = detail.data || {};
    const declaredLen = Number(d.len || 0);
    let raw = null;

    // Dev Shell V2 passes the COMPLETE ArrayBuffer directly in CustomEvent.detail.
    if (d.buffer instanceof ArrayBuffer) {
      raw = new Uint8Array(d.buffer);
    } else if (ArrayBuffer.isView(d.buffer)) {
      raw = new Uint8Array(
        d.buffer.buffer,
        d.buffer.byteOffset,
        d.buffer.byteLength
      );
    } else {
      // Backward compatibility with V1 bootstrap for complete small frames.
      const sampleBytes = Number(d.sampleBytes || 0);
      if (
        declaredLen > 0 &&
        declaredLen === sampleBytes &&
        d.b64
      ) {
        raw = b64ToBytes(d.b64);
      }
    }

    if (!raw || !raw.length) return;
    if (declaredLen > 0 && raw.length !== declaredLen) return;

    if (!fullFrameNoticeSent) {
      fullFrameNoticeSent = true;
      report("WS_FULL_FRAME", {
        len: raw.length,
        transport: d.buffer instanceof ArrayBuffer
          ? "arraybuffer-v2"
          : "legacy-complete-b64"
      });
    }

    try {
      const gz = findGzip(raw);
      if (gz < 0) return;

      const decompressed = await gunzip(raw.slice(gz));
      const parsed = parseMessage(decompressed);
      if (!parsed.ok) return;

      const containers = responseContainers(parsed);
      if (!containers.length) return;

      // A single TikTok frame can contain several message containers.
      // Process every container instead of trusting only the first method.
      for (const item of containers) {
        try {
          handleDecodedContainer(item);
        } catch (_) {}
      }

    } catch (_) {}
  }

  // ==========================================================
  // REACT FIBER IDENTITY
  // ==========================================================

  function numericId(v) {
    if (typeof v === "bigint") {
      const s = v.toString();
      return /^\d{15,22}$/.test(s) ? s : "";
    }

    if (typeof v === "number" && Number.isFinite(v)) {
      const s = String(Math.trunc(v));
      return /^\d{15,22}$/.test(s) ? s : "";
    }

    if (typeof v === "string") {
      const s = v.trim();
      return /^\d{15,22}$/.test(s) ? s : "";
    }

    return "";
  }

  function avatarString(v) {
    if (typeof v !== "string") return "";

    const s = v.trim();

    if (!/^https?:\/\//i.test(s)) return "";

    if (
      /-avt-|tiktok-shrink|cropcenter|tos-.*avt/i.test(s) &&
      !/badge|resource\//i.test(s)
    ) {
      return s;
    }

    return "";
  }

  function keyValue(obj, keys) {
    if (!obj || typeof obj !== "object") return undefined;

    for (const k of keys) {
      if (Object.prototype.hasOwnProperty.call(obj, k)) {
        return obj[k];
      }
    }

    return undefined;
  }

  function candidateFromObject(obj, targetNickname) {
    if (!obj || typeof obj !== "object") return null;

    const nick = clean(keyValue(obj, [
      "nickname", "nickName", "displayName",
      "display_name", "display_name_text"
    ]) || "");

    if (!nick || nick !== clean(targetNickname)) return null;

    let userId = numericId(
      keyValue(obj, [
        "userId", "user_id", "uid", "id",
        "userID", "user_id_str"
      ])
    );

    let uniqueId = clean(
      keyValue(obj, [
        "uniqueId", "unique_id", "username",
        "userName", "handle"
      ]) || ""
    );

    let secUid = clean(
      keyValue(obj, [
        "secUid", "sec_uid", "secUID"
      ]) || ""
    );

    let avatar = "";

    for (const k of [
      "avatar", "avatarThumb", "avatar_thumb",
      "avatarMedium", "avatar_medium",
      "avatarLarger", "avatar_larger"
    ]) {
      const v = obj[k];

      if (typeof v === "string") {
        avatar = avatarString(v) || avatar;
      }

      if (v && typeof v === "object") {
        const urlList =
          v.urlList || v.url_list || v.urls || [];

        if (Array.isArray(urlList)) {
          for (const u of urlList) {
            avatar = avatarString(u) || avatar;
            if (avatar) break;
          }
        }
      }

      if (avatar) break;
    }

    if (!userId && !uniqueId && !secUid && !avatar) {
      return null;
    }

    return {
      userId,
      nickname: nick,
      uniqueId,
      secUid,
      avatar
    };
  }

  function searchObjectGraph(root, targetNickname) {
    if (!root || typeof root !== "object") return null;

    const q = [{ value: root, depth: 0 }];
    const seen = new WeakSet();
    let visited = 0;

    while (q.length && visited < 1800) {
      const { value, depth } = q.shift();

      if (!value || typeof value !== "object") continue;
      if (seen.has(value)) continue;

      seen.add(value);
      visited++;

      const c = candidateFromObject(value, targetNickname);
      if (c) return c;

      if (depth >= 5) continue;

      let keys = [];

      try {
        keys = Object.keys(value);
      } catch (_) {
        continue;
      }

      for (const k of keys.slice(0, 100)) {
        if (
          k === "children" ||
          k === "parentElement" ||
          k === "ownerDocument" ||
          k === "stateNode" ||
          k === "_owner"
        ) {
          continue;
        }

        let v;

        try {
          v = value[k];
        } catch (_) {
          continue;
        }

        if (!v || typeof v !== "object") continue;

        // Skip DOM nodes.
        if (
          typeof Node !== "undefined" &&
          v instanceof Node
        ) {
          continue;
        }

        q.push({
          value: v,
          depth: depth + 1
        });
      }
    }

    return null;
  }

  function reactIdentity(owner, nickname) {
    let cur = owner;

    for (let domDepth = 0; cur && domDepth < 7; domDepth++, cur = cur.parentElement) {
      let keys = [];

      try {
        keys = Object.keys(cur);
      } catch (_) {}

      for (const k of keys) {
        if (
          k.startsWith("__reactProps$") ||
          k.startsWith("__reactFiber$")
        ) {
          let root;

          try {
            root = cur[k];
          } catch (_) {
            continue;
          }

          const direct = searchObjectGraph(root, nickname);
          if (direct) return direct;

          // Walk Fiber return chain as well.
          if (k.startsWith("__reactFiber$")) {
            let fiber = root;

            for (let fDepth = 0; fiber && fDepth < 14; fDepth++, fiber = fiber.return) {
              for (const candidateRoot of [
                fiber.memoizedProps,
                fiber.pendingProps,
                fiber.memoizedState
              ]) {
                const found = searchObjectGraph(candidateRoot, nickname);
                if (found) return found;
              }
            }
          }
        }
      }
    }

    return null;
  }

  // ==========================================================
  // DOM EVENT PARSER
  // ==========================================================

  function classify(text) {
    if (/đã tham gia|joined(?: the LIVE)?/i.test(text)) return "join";
    if (/đã thích phiên LIVE|liked the LIVE/i.test(text)) return "like";
    if (/đã gửi|sent .+×|gifted the host/i.test(text)) return "gift";
    if (/đã chia sẻ phiên LIVE|shared the LIVE/i.test(text)) return "share";
    if (/đã follow chủ phòng|followed the host/i.test(text)) return "follow";
    return "comment";
  }

  function expectedMethods(type) {
    switch (type) {
      case "join":
        return ["WebcastMemberMessage"];

      case "like":
        return ["WebcastLikeMessage"];

      case "comment":
        return ["WebcastChatMessage"];

      case "gift":
        return ["WebcastGiftMessage"];

      case "share":
      case "follow":
        return ["WebcastSocialMessage"];

      default:
        return [];
    }
  }

  function findWsIdentity(type, nickname, now) {
    trimQueue(now);

    const allowed = new Set(expectedMethods(type));
    if (!allowed.size) return null;

    let best = null;
    let bestDt = Infinity;

    for (let i = identityQueue.length - 1; i >= 0; i--) {
      const rec = identityQueue[i];

      if (!allowed.has(rec.method)) continue;
      if (clean(rec.user.nickname) !== clean(nickname)) continue;

      const dt = Math.abs(now - rec.ts);

      if (dt > MAX_QUEUE_AGE) continue;

      if (dt < bestDt) {
        best = {
          ...rec.user,
          method: rec.method,
          dtMs: rec.ts - now
        };

        bestDt = dt;
      }
    }

    return best;
  }

  function parseGift(content) {
    let m = content.match(/đã gửi\s+(.+?)\s*[×x]\s*(\d+)/i);
    if (!m) m = content.match(/sent\s+(.+?)\s*[×x]\s*(\d+)/i);
    if (!m) m = content.match(/gifted the host\s+(\d+)\s+(.+)$/i);

    if (!m) return {};

    if (/gifted the host/i.test(content)) {
      return {
        quantity: Number(m[1]) || 1,
        giftName: clean(m[2])
      };
    }

    return {
      giftName: clean(m[1]),
      quantity: Number(m[2]) || 1
    };
  }

  function findRow(owner) {
    let cur = owner;
    let fallback = owner.parentElement || owner;

    for (let depth = 0; cur && depth < 10; depth++, cur = cur.parentElement) {
      const text = clean(cur.innerText || cur.textContent || "");

      if (!text || text.length > 900) continue;

      fallback = cur;

      if (cur.hasAttribute && cur.hasAttribute("data-index")) {
        return cur;
      }

      const type = classify(text);
      const ownerName = clean(owner.innerText || owner.textContent || "");

      if (
        type !== "comment" &&
        text.includes(ownerName) &&
        text.length > ownerName.length + 2
      ) {
        return cur;
      }
    }

    return fallback;
  }

  function extractParts(row, owner) {
    const nickname = clean(owner.innerText || owner.textContent || "");
    const full = clean(row.innerText || row.textContent || "");

    const idx = full.indexOf(nickname);

    let prefix = "";
    let content = full;

    if (idx >= 0) {
      prefix = clean(full.slice(0, idx));
      content = clean(full.slice(idx + nickname.length));
    }

    let level = null;
    const nums = prefix.match(/\b(\d{1,3})\b/g);

    if (nums && nums.length) {
      const n = Number(nums[0]);
      if (Number.isFinite(n)) level = n;
    }

    return {
      nickname,
      full,
      prefix,
      content,
      level
    };
  }

  function realAvatar(row) {
    try {
      for (const img of Array.from(row.querySelectorAll("img"))) {
        const src = img.currentSrc || img.src || "";
        const s = src.toLowerCase();

        if (!s) continue;

        if (/grade_badge|fans_badge|resource\/|webcast-va\/.*badge/.test(s)) {
          continue;
        }

        if (/-avt-|tiktok-shrink|cropcenter|tos-.*avt/.test(s)) {
          return src;
        }
      }
    } catch (_) {}

    return "";
  }

  function inferUniqueId(row) {
    try {
      for (const a of Array.from(row.querySelectorAll('a[href*="/@"]'))) {
        const href = a.getAttribute("href") || "";
        const m = href.match(/\/@([^/?#]+)/);

        if (m) return decodeURIComponent(m[1]);
      }
    } catch (_) {}

    return "";
  }

  function mergeIdentity(primary, secondary, domAvatar, domUniqueId) {
    const a = primary || {};
    const b = secondary || {};

    return {
      userId: a.userId || b.userId || "",
      uniqueId: a.uniqueId || b.uniqueId || domUniqueId || "",
      secUid: a.secUid || b.secUid || "",
      avatar: a.avatar || b.avatar || domAvatar || ""
    };
  }

  function emitOwner(owner) {
    if (!active || !owner || !owner.isConnected) return;

    const row = findRow(owner);
    if (!row) return;

    const parts = extractParts(row, owner);

    if (!parts.nickname || !parts.full) return;

    const type = classify(parts.full);

    // TikTok likes are emitted authoritatively from WebcastLikeMessage above.
    // Do not emit the visual DOM "đã thích phiên LIVE" row again, or likes double-count.
    if (type === "like") return;

    if (type === "comment" && !parts.content) return;

    const now = Date.now();
    const key = type + "|" + parts.nickname + "|" + parts.content;
    const prev = seenDom.get(key) || 0;

    if (now - prev < 1800) return;
    seenDom.set(key, now);

    if (seenDom.size > 600) {
      const cutoff = now - 40000;

      for (const [k, t] of seenDom.entries()) {
        if (t < cutoff) seenDom.delete(k);
      }
    }

    const react = reactIdentity(owner, parts.nickname);
    const ws = findWsIdentity(type, parts.nickname, now);

    const merged = mergeIdentity(
      react,
      ws,
      realAvatar(row),
      inferUniqueId(row)
    );

    const event = {
      type,
      nickname: parts.nickname,
      content: parts.content,
      text: parts.full,
      level: parts.level,

      userId: merged.userId,
      uniqueId: merged.uniqueId,
      secUid: merged.secUid,
      avatar: merged.avatar,

      identitySource:
        react ? "react" :
        ws ? "websocket" :
        (merged.avatar || merged.uniqueId) ? "dom" :
        "none",

      wsMethod: ws ? ws.method : "",
      identityDtMs: ws ? ws.dtMs : null,
      ts: now
    };

    if (type === "gift") {
      Object.assign(event, parseGift(parts.content));
      event.source = "dom_fallback";
    }

    if (react) {
      report("REACT_IDENTITY", {
        nickname: parts.nickname,
        type,
        identity: react
      });
    }

    reportEvent(event);
  }

  function scanNode(node) {
    if (!active || !node) return;

    const root = node.nodeType === Node.ELEMENT_NODE
      ? node
      : node.parentElement;

    if (!root) return;

    if (
      root.matches &&
      root.matches('[data-e2e="message-owner-name"]')
    ) {
      emitOwner(root);
    }

    try {
      for (const owner of root.querySelectorAll('[data-e2e="message-owner-name"]')) {
        emitOwner(owner);
      }
    } catch (_) {}

    let cur = root;

    for (let depth = 0; cur && depth < 7; depth++, cur = cur.parentElement) {
      try {
        const owner = cur.querySelector &&
          cur.querySelector('[data-e2e="message-owner-name"]');

        if (owner) {
          emitOwner(owner);
          break;
        }
      } catch (_) {}
    }
  }

  function startObserver() {
    if (observer) observer.disconnect();

    const target = document.body || document.documentElement;
    if (!target) return;

    observer = new MutationObserver(mutations => {
      for (const m of mutations) {
        for (const n of m.addedNodes || []) {
          scanNode(n);
        }

        if (m.type === "characterData") {
          scanNode(m.target);
        }
      }
    });

    observer.observe(target, {
      childList: true,
      subtree: true,
      characterData: true
    });
  }

  function onWs(e) {
    decodeWs(e.detail || {});
  }

  window.addEventListener("__SCBD_WS_MESSAGE__", onWs);
  startObserver();

  window.__SCBD_LOCAL_PROBE__ = {
    version: VERSION,

    startCapture() {
      active = true;

      report("CAPTURE_START", {
        version: VERSION,
        mode: "react+full-websocket+multi-message+scoring-bridge"
      });
    },

    stopCapture() {
      active = false;

      report("CAPTURE_END", {
        version: VERSION
      });
    },

    dispose() {
      active = false;

      if (observer) observer.disconnect();
      observer = null;

      window.removeEventListener("__SCBD_WS_MESSAGE__", onWs);
    }
  };

  report("PROBE_READY", {
    version: VERSION,
    mode: "REACT_IDENTITY+FULL_WEBSOCKET+MULTI_MESSAGE+SCORING_BRIDGE"
  });
})();