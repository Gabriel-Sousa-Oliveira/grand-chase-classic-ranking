import assert from "node:assert/strict";
import test from "node:test";

import { topRankingsByCharacter } from "../lib/ranking.ts";

const row = (id, nick, time, era) => ({
  id,
  character: "Lass",
  category: "void_invasion",
  floor: 3,
  time_ms: time,
  player_nick: nick,
  era_key: era,
});

test("historical ranking is globally fastest and keeps one run per nick", () => {
  const result = topRankingsByCharacter([
    row(1, "Choco", 84_000, "syntaxii_2026_archive"),
    row(2, "xandindj", 74_000, "current"),
    row(3, "Choco", 96_000, "current"),
  ], "void_invasion", 3, "all");

  assert.deepEqual(result[0].runs.map(run => [run.player_nick, run.time_ms]), [
    ["xandindj", 74_000],
    ["Choco", 84_000],
  ]);
});

test("period filter does not mix eras", () => {
  const result = topRankingsByCharacter([
    row(1, "Choco", 84_000, "syntaxii_2026_archive"),
    row(2, "xandindj", 74_000, "current"),
  ], "void_invasion", 3, "current");
  assert.deepEqual(result[0].runs.map(run => run.player_nick), ["xandindj"]);
});
