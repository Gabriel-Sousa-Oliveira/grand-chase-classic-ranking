import test from "node:test";
import assert from "node:assert/strict";
import {digitsOnly,parseTimeParts,splitTimeLabel} from "../lib/time-input.ts";

test("builds a run time from mobile-friendly numeric fields",()=>{
  assert.equal(parseTimeParts({minutes:"1",seconds:"24",milliseconds:""}),84_000);
  assert.equal(parseTimeParts({minutes:"0",seconds:"59",milliseconds:"45"}),59_450);
});

test("rejects invalid seconds and empty times",()=>{
  assert.equal(parseTimeParts({minutes:"1",seconds:"60",milliseconds:""}),null);
  assert.equal(parseTimeParts({minutes:"",seconds:"24",milliseconds:""}),null);
  assert.equal(parseTimeParts({minutes:"0",seconds:"0",milliseconds:""}),null);
});

test("splits existing labels and sanitizes pasted mobile values",()=>{
  assert.deepEqual(splitTimeLabel("01:32"),{minutes:"1",seconds:"32",milliseconds:""});
  assert.equal(digitsOnly("1,24",2),"12");
});
