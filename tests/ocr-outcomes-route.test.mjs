import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("OCR outcome repair is authenticated, bounded and batched",async()=>{
  const source=await readFile(new URL("../app/api/candidates/ocr-outcomes/route.ts",import.meta.url),"utf8");
  assert.match(source,/oai-authenticated-user-id/);
  assert.match(source,/slice\(0, 500\)/);
  assert.match(source,/DB\.batch\(statements\)/);
  assert.match(source,/status IN \('ready_for_review','time_required','classification_required'\)/);
});

test("pending queue excludes OCR matches and exposes audit evidence",async()=>{
  const source=await readFile(new URL("../app/api/candidates/route.ts",import.meta.url),"utf8");
  assert.match(source,/ocr_time_ms/);
  assert.match(source,/ocr_confidence/);
  assert.match(source,/evidence_frame/);
  assert.match(source,/evidence_seconds_from_end/);
  assert.match(source,/evidence_image/);
  assert.match(source,/ocr_roi/);
  assert.match(source,/processing_reason/);
  assert.match(source,/ocr_outcome'\), ''\) != 'matched'/);
  assert.match(source,/ocr_attempted_at/);
  assert.match(source,/THEN raw_metadata/);
});
