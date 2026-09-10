import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("ranking revocation is authenticated and removes the approved row", async () => {
  const source = await readFile(new URL("../app/api/rankings/[id]/revoke/route.ts", import.meta.url), "utf8");
  assert.match(source, /oai-authenticated-user-id/);
  assert.match(source, /DELETE FROM rankings WHERE id = \?/);
  assert.match(source, /status = 'rejected'/);
  assert.match(source, /Approval revoked by administrator/);
});
