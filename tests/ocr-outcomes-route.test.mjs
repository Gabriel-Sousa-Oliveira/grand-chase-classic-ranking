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
