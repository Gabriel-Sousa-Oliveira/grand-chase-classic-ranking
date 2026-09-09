import assert from "node:assert/strict";
import test from "node:test";

import { buildRecordProgression, topRankingsByCharacter } from "../lib/ranking.ts";

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

test("record progression includes only chronological improvements", () => {
  const rows = [
    {...row(1, "A", 90_000, "current"), published_at: "2026-01-01", video_url: "https://example.com/1"},
    {...row(2, "B", 95_000, "current"), published_at: "2026-02-01"},
    {...row(3, "C", 80_000, "current"), published_at: "2026-03-01"},
  ];
  const result = buildRecordProgression(rows, "void_invasion", 3, "Lass", "current");
  assert.deepEqual(result.map(event => [event.player_nick, event.improvement_ms]), [["C", 10_000], ["A", null]]);
});
