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

test("keeps incomplete, ambiguous, and OCR-derived candidates manual", () => {
  assert.equal(shouldAutoApproveTitle({ ...complete, time_ms: null, status: "time_required" }), false);
  assert.equal(shouldAutoApproveTitle({ ...complete, character: null }), false);
  assert.equal(shouldAutoApproveTitle({ ...complete, confidence: 0.94 }), false);
});
