import assert from "node:assert/strict";
import test from "node:test";

import {matchesQualityFilter, qualityIssues, qualityPriority} from "../lib/data-quality.ts";

const complete={character:"Ereb",category:"void_invasion",floor:3,time_ms:92_000,confidence:.95};

test("separates technical OCR errors from no-consensus reviews",()=>{
  assert.deepEqual(qualityIssues({...complete,time_ms:null,ocr_outcome:"error"}),["time","ocr_error"]);
  assert.deepEqual(qualityIssues({...complete,time_ms:null,ocr_outcome:"no_consensus"}),["time","ocr_no_consensus"]);
});

test("flags incomplete classification and low confidence",()=>{
  const issues=qualityIssues({...complete,character:null,confidence:.72});
  assert.ok(issues.includes("classification"));
  assert.ok(issues.includes("low_confidence"));
});

test("detects duplicate and statistically unusual candidates",()=>{
  const candidate={...complete,time_ms:220_000,benchmark_ms:90_000,benchmark_count:4,possible_duplicate:1};
  assert.ok(qualityIssues(candidate).includes("duplicate"));
  assert.ok(qualityIssues(candidate).includes("outlier"));
  assert.equal(matchesQualityFilter(candidate,"risk"),true);
  assert.ok(qualityPriority({...complete,time_ms:null,ocr_outcome:"error"})>qualityPriority(candidate));
});
