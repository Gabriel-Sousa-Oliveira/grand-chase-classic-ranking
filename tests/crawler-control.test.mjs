import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  CRAWLER_COOLDOWN_MS,
  cooldownRemainingSeconds,
  isActiveRun,
  parseLookbackDays,
} from "../lib/crawler-control.ts";

const run = (overrides = {}) => ({
  id: 1,
  status: "completed",
  conclusion: "success",
  html_url: "https://github.com/example/actions/runs/1",
  event: "workflow_dispatch",
  created_at: "2026-09-24T12:00:00.000Z",
  updated_at: "2026-09-24T12:02:00.000Z",
  ...overrides,
});

test("accepts only bounded crawler periods", () => {
  assert.equal(parseLookbackDays(3), 3);
  assert.equal(parseLookbackDays("30"), 30);
  assert.equal(parseLookbackDays(0), null);
  assert.equal(parseLookbackDays(365), null);
});

test("detects active workflow runs", () => {
  assert.equal(isActiveRun(run({ status: "queued" })), true);
  assert.equal(isActiveRun(run({ status: "in_progress" })), true);
  assert.equal(isActiveRun(run()), false);
});

test("enforces a ten minute cooldown for manual dispatches", () => {
  const started = Date.parse("2026-09-24T12:00:00.000Z");
  assert.equal(cooldownRemainingSeconds([run()], started + 60_000), 540);
  assert.equal(cooldownRemainingSeconds([run()], started + CRAWLER_COOLDOWN_MS), 0);
  assert.equal(cooldownRemainingSeconds([run({ event: "schedule" })], started + 60_000), 0);
});

test("crawler route keeps credentials server-side and restricts the administrator", async () => {
  const source = await readFile(new URL("../app/api/crawler/route.ts", import.meta.url), "utf8");
  assert.match(source, /oai-authenticated-user-id/);
  assert.match(source, /oai-authenticated-user-email/);
  assert.match(source, /ADMIN_EMAIL/);
  assert.match(source, /GITHUB_WORKFLOW_TOKEN/);
  assert.match(source, /actions\/workflows\/\$\{WORKFLOW\}\/dispatches/);
  assert.match(source, /mode: "recent"/);
  assert.match(source, /origin !== new URL\(request\.url\)\.origin/);
  assert.doesNotMatch(source, /github_pat_[A-Za-z0-9_]+/);
});
