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

test("parses Korean and Thai titles plus the Azin alias", () => {
  const korean = parseRunTitle("그랜드체이스 클래식 아신 공허 침공 3층 01:07");
  assert.deepEqual([korean.character, korean.category, korean.floor, korean.timeMs], ["Asin", "void_invasion", 3, 67_000]);
  const thai = parseRunTitle("แกรนด์เชส คลาสสิก อาซิน วอยด์ อินเวชัน 3ชั้น 01:08");
  assert.deepEqual([thai.character, thai.category, thai.floor, thai.timeMs], ["Asin", "void_invasion", 3, 68_000]);
  assert.equal(parseRunTitle("Azin Void Invasion 3F 01:09").character, "Asin");
});

test("parses Duel Lv.4 as a complete zero-floor category", () => {
  const result = parseRunTitle("Grand Chase Classic Ereb Duel Lv.4 01:05");
  assert.deepEqual(
    {character:result.character, category:result.category, floor:result.floor, timeMs:result.timeMs, status:result.status, confidence:result.confidence},
    {character:"Ereb", category:"duel_4", floor:0, timeMs:65_000, status:"ready_for_review", confidence:95},
  );
});
