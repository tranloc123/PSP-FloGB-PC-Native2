const dgram = require("dgram");
const { resolvePick } = require("./character_resolver_v059b");

const HOST = process.env.SCBD_NATIVE_HOST || "127.0.0.1";
const PORT = Number(process.env.SCBD_NATIVE_PORT || 8796);
const socket = dgram.createSocket("udp4");

const state = {
  sent: 0,
  sendErrors: 0,
  lastSent: "",
  lastSentAt: 0,
  lastAck: "",
  lastAckAt: 0,
  lastAckAddress: "",
};

socket.on("message", (msg, rinfo) => {
  state.lastAck = msg.toString("utf8");
  state.lastAckAt = Date.now();
  state.lastAckAddress = `${rinfo.address}:${rinfo.port}`;
});

socket.on("error", (err) => {
  state.sendErrors++;
  state.lastAck = `SOCKET ERROR: ${err.message}`;
});

function enc(value) {
  return encodeURIComponent(String(value ?? ""));
}

function sendRaw(line) {
  const payload = Buffer.from(String(line), "utf8");
  state.sent++;
  state.lastSent = String(line);
  state.lastSentAt = Date.now();

  return new Promise((resolve, reject) => {
    socket.send(payload, PORT, HOST, (err) => {
      if (err) {
        state.sendErrors++;
        reject(err);
      } else {
        resolve();
      }
    });
  });
}

function sendPing() {
  return sendRaw("PING");
}

function sendWinner({ username, team, score = 0, avatar = "" }) {
  const safeTeam = Number(team) === 2 ? 2 : 1;
  return sendRaw(
    `WINNER\t${enc(username)}\t${safeTeam}\t${Math.max(0, Number(score) || 0)}\t${enc(avatar)}`
  );
}

function sendPick(input) {
  const requested = input && typeof input === "object"
    ? (input.characterId ?? input.pick ?? input.id)
    : input;

  const resolved = resolvePick(requested);
  if (!resolved) {
    throw new Error("pick must resolve to /pick 1..28");
  }

  // V0.5.9B: pick number is the single source of truth.
  // Any character/name field supplied by a caller is deliberately ignored.
  return sendRaw(`PICK\t${resolved.characterId}\t${enc(resolved.character)}`);
}

function sendTimeout() {
  return sendRaw("TIMEOUT");
}

function sendCancel() {
  return sendRaw("CANCEL");
}

function getStatus() {
  const now = Date.now();
  return {
    host: HOST,
    port: PORT,
    sent: state.sent,
    sendErrors: state.sendErrors,
    lastSent: state.lastSent,
    lastSentAt: state.lastSentAt,
    lastAck: state.lastAck,
    lastAckAt: state.lastAckAt,
    lastAckAddress: state.lastAckAddress,
    nativeOnline: state.lastAckAt > 0 && now - state.lastAckAt < 3000,
  };
}

const heartbeat = setInterval(() => {
  sendPing().catch(() => {});
}, 1000);
if (heartbeat.unref) heartbeat.unref();

module.exports = {
  sendRaw,
  sendPing,
  sendWinner,
  sendPick,
  sendTimeout,
  sendCancel,
  getStatus,
};
