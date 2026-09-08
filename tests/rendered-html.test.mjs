import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("build contains GC Run Radar metadata", async () => {
  const output = await readFile(new URL("../dist/server/index.js", import.meta.url), "utf8");
  assert.match(output, /title:\s*"GC Run Radar"/);
  assert.match(output, /"codex-preview":\s*"development"/);
});
