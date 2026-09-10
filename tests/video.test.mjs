import assert from "node:assert/strict";
import test from "node:test";

import {getVideoPreview} from "../lib/video.ts";

test("builds a thumbnail from YouTube watch and short links", () => {
  assert.equal(
    getVideoPreview("https://www.youtube.com/watch?v=CD3mVzdsp0M").thumbnailUrl,
    "https://i.ytimg.com/vi/CD3mVzdsp0M/hqdefault.jpg",
  );
  assert.equal(
    getVideoPreview("https://youtu.be/5D4_AfVl2eU").thumbnailUrl,
    "https://i.ytimg.com/vi/5D4_AfVl2eU/hqdefault.jpg",
  );
});

test("keeps non-YouTube sources usable without inventing a thumbnail", () => {
  assert.deepEqual(getVideoPreview("https://chzzk.naver.com/video/123"), {
    platform: "CHZZK",
    watchUrl: "https://chzzk.naver.com/video/123",
    thumbnailUrl: null,
  });
});
