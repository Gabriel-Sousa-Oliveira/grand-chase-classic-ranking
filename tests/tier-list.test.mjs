import assert from "node:assert/strict";
import test from "node:test";

import {buildPerformanceTiers} from "../lib/tier-list.ts";

const row = (id, character, time, era = "current") => ({
  id, character, category: "duel_4", floor: 0, time_ms: time,
  player_nick: `Player ${id}`, era_key: era, video_url: `https://youtu.be/video0000${id}`,
});

test("tier list uses only the fastest run from each character", () => {
  const result = buildPerformanceTiers([
    row(1, "Edel", 69_000), row(2, "Edel", 72_000), row(3, "Ereb", 65_000),
  ], "duel_4", 0, "current");
  assert.deepEqual(result.entries.map(entry => [entry.character, entry.time_ms]), [
    ["Ereb", 65_000], ["Edel", 69_000],
  ]);
  assert.equal(result.entries[0].tier, "S");
  assert.equal(result.entries[0].gap_percent, 0);
  assert.equal(result.representedCharacters, 2);
  assert.equal(result.provisional, true);
});

test("tier list separates five equally sized relative bands", () => {
  const result = buildPerformanceTiers(
    Array.from({length: 25}, (_, index) => row(index + 1, `Character ${index + 1}`, 60_000 + index * 1_000)),
    "duel_4", 0, "current",
  );
  assert.deepEqual(result.tiers.map(group => group.entries.length), [5, 5, 5, 5, 5]);
  assert.equal(result.provisional, false);
  assert.equal(result.coveragePercent, 100);
});
