import assert from "node:assert/strict";
import test from "node:test";
import { buildGitHubSubmissionUrl, isYouTubeUrl } from "../lib/submission.ts";

test("accepts supported YouTube URL formats", () => {
  assert.equal(isYouTubeUrl("https://youtu.be/Q2TUPeiTmPI"), true);
  assert.equal(isYouTubeUrl("https://www.youtube.com/watch?v=Q2TUPeiTmPI"), true);
  assert.equal(isYouTubeUrl("https://youtube.com/shorts/Q2TUPeiTmPI"), true);
  assert.equal(isYouTubeUrl("https://example.com/watch?v=Q2TUPeiTmPI"), false);
});

test("builds an encoded and structured GitHub issue", () => {
  const url = new URL(buildGitHubSubmissionUrl({
    videoUrl: "https://youtu.be/Q2TUPeiTmPI",
    character: "Ereb",
    dungeon: "Duel 4",
    notes: "Tempo aparece no final.",
  }));
  assert.equal(url.hostname, "github.com");
  assert.match(url.searchParams.get("title"), /^\[Run submission\]/);
  assert.match(url.searchParams.get("body"), /https:\/\/youtu\.be\/Q2TUPeiTmPI/);
  assert.match(url.searchParams.get("body"), /Tempo aparece no final\./);
});
