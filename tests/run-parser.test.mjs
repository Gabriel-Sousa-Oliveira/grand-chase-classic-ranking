import test from "node:test";
import assert from "node:assert/strict";
import { parseRunTitle } from "../lib/run-parser.ts";

test("parses Ereb Void Invasion with apostrophe time", () => {
  const run = parseRunTitle("Ereb | Vazio (Invasão) 3f (1'32) | Grand Chase Classic");
  assert.deepEqual(
    { character: run.character, category: run.category, floor: run.floor, timeMs: run.timeMs, status: run.status },
    { character: "Ereb", category: "void_invasion", floor: 3, timeMs: 92000, status: "ready_for_review" },
  );
});

test("routes titles without a time to manual/OCR review", () => {
  const nightmare = parseRunTitle("Ereb | Void(Nightmare) 4f | Grand Chase Classic");
  const apocalypse = parseRunTitle("Lupus | Vazio (Apocalipse) 3F Solo Sem poções | Grand Chase Classic");
  assert.equal(nightmare.status, "time_required");
  assert.equal(apocalypse.status, "time_required");
  assert.equal(apocalypse.character, "Rufus/Lupus");
  assert.equal(apocalypse.solo, true);
  assert.equal(apocalypse.noPotions, true);
});

