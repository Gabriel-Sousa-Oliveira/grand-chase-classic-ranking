import assert from "node:assert/strict";
import test from "node:test";
import { canonicalizePlayerNick } from "../lib/player-nick.ts";

test("treats Bork as an alias of Borkaz", () => {
  assert.equal(canonicalizePlayerNick("Bork"), "Borkaz");
  assert.equal(canonicalizePlayerNick(" bOrK "), "Borkaz");
  assert.equal(canonicalizePlayerNick("Borkaz"), "Borkaz");
});
