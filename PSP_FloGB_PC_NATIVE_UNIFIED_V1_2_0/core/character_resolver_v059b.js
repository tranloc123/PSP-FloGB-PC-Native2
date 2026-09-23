const MAP = Object.freeze([
  null,
  { pick: 1,  sourceSlot: 1,  name: "YOSHIMITSU" },
  { pick: 2,  sourceSlot: 2,  name: "SETSUKA" },
  { pick: 3,  sourceSlot: 3,  name: "VOLDO" },
  { pick: 4,  sourceSlot: 4,  name: "CASSANDRA" },
  { pick: 5,  sourceSlot: 5,  name: "LIZARDMAN" },
  { pick: 6,  sourceSlot: 6,  name: "TAKI" },
  { pick: 7,  sourceSlot: 7,  name: "MITSURUGI" },
  { pick: 8,  sourceSlot: 8,  name: "ALGOL" },
  { pick: 9,  sourceSlot: 9,  name: "SOPHITIA" },
  { pick: 10, sourceSlot: 10, name: "TIRA" },
  { pick: 11, sourceSlot: 11, name: "SIEGFRIED" },
  { pick: 12, sourceSlot: 12, name: "HILDE" },
  { pick: 13, sourceSlot: 13, name: "DAMPIERRE" },
  { pick: 14, sourceSlot: 14, name: "KRATOS" },
  { pick: 15, sourceSlot: 15, name: "NIGHTMARE" },
  { pick: 16, sourceSlot: 16, name: "XIANGHUA" },
  { pick: 17, sourceSlot: 17, name: "MAXI" },
  // Original slot 18 is the custom-character tile and is intentionally skipped.
  { pick: 18, sourceSlot: 19, name: "RAPHAEL" },
  { pick: 19, sourceSlot: 20, name: "ASTAROTH" },
  { pick: 20, sourceSlot: 21, name: "YUN-SEONG" },
  { pick: 21, sourceSlot: 22, name: "KILIK" },
  { pick: 22, sourceSlot: 23, name: "IVY" },
  { pick: 23, sourceSlot: 24, name: "AMY" },
  { pick: 24, sourceSlot: 25, name: "ROCK" },
  { pick: 25, sourceSlot: 26, name: "TALIM" },
  { pick: 26, sourceSlot: 27, name: "SEONG MI-NA" },
  { pick: 27, sourceSlot: 28, name: "CERVANTES" },
  { pick: 28, sourceSlot: 29, name: "ZASALAMEL" },
]);

function normalizePick(value) {
  if (typeof value === "string") {
    const s = value.trim();
    const match = s.match(/^\/?pick\s+(\d{1,2})$/i);
    if (match) value = match[1];
  }

  const n = Number(value);
  if (!Number.isInteger(n) || n < 1 || n > 28) {
    return null;
  }
  return n;
}

function resolvePick(value) {
  const pick = normalizePick(value);
  if (pick == null) return null;
  const item = MAP[pick];
  return {
    pick: item.pick,
    characterId: item.pick,
    sourceSlot: item.sourceSlot,
    character: item.name,
    name: item.name,
    portraitIndex: item.pick - 1,
    portraitFile: `SCBD_PICK_${String(item.pick).padStart(2, "0")}.png`,
  };
}

function parsePickComment(comment) {
  if (typeof comment !== "string") return null;
  const match = comment.trim().match(/^\/pick\s+(\d{1,2})$/i);
  if (!match) return null;
  return resolvePick(match[1]);
}

function allCharacters() {
  return MAP.slice(1).map(x => ({ ...x }));
}

module.exports = {
  resolvePick,
  parsePickComment,
  normalizePick,
  allCharacters,
};
