import assert from "node:assert/strict";
import test from "node:test";

import { shouldAutoApproveTitle } from "../lib/candidate-policy.ts";

const complete = {
  status: "ready_for_review",
  character: "Ereb",
  category: "void_invasion",
  floor: 3,
  time_ms: 92_000,
  confidence: 0.95,
};

test("auto-approves complete high-confidence title parses", () => {
  assert.equal(shouldAutoApproveTitle(complete), true);
  assert.equal(shouldAutoApproveTitle({ ...complete, floor: 0 }), true);
});

test("keeps incomplete and ambiguous candidates manual", () => {
  assert.equal(shouldAutoApproveTitle({ ...complete, time_ms: null, status: "time_required" }), false);
  assert.equal(shouldAutoApproveTitle({ ...complete, character: null }), false);
  assert.equal(shouldAutoApproveTitle({ ...complete, confidence: 0.94 }), false);
});

test("auto-approves OCR times only with multi-frame consensus", () => {
  const ocr = { ...complete, confidence: 0.72, raw_metadata: JSON.stringify({
    ocr_outcome: "matched", ocr: { matching_frames: 2, observations: 2 },
  }) };
  assert.equal(shouldAutoApproveTitle(ocr), true);
  assert.equal(shouldAutoApproveTitle({
    ...ocr,
    raw_metadata: JSON.stringify({
      ocr_outcome: "matched", ocr: { matching_frames: 1, observations: 1 },
    }),
  }), false);
});
