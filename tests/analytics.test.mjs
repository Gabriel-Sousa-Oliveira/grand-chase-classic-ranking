import assert from "node:assert/strict";
import test from "node:test";

import {buildAnalytics, gameCharacters, processingRate} from "../lib/analytics.ts";

const dungeons=[
  {key:"void_invasion:3",category:"void_invasion",floor:3,label:"Invasion"},
  {key:"void_taint:3",category:"void_taint",floor:3,label:"Taint"},
];
const row=(id,character,nick,time,category="void_invasion",era="current")=>({id,character,category,floor:3,time_ms:time,player_nick:nick,era_key:era});

test("analytics measures unique top-four coverage rather than duplicate runs",()=>{
  const data=buildAnalytics([
    row(1,"Lass","Choco",84_000),
    row(2,"Lass","choco",96_000),
    row(3,"Lass","xandindj",74_000),
    row(4,"Ereb","Borkaz",92_000),
  ],dungeons,"all");
  assert.equal(data.verifiedRuns,4);
  assert.equal(data.uniquePlayers,3);
  assert.equal(data.representedCharacters,2);
  assert.equal(data.boards[0].filledSlots,3);
  assert.equal(data.boards[0].byCharacter.get("Lass"),2);
  assert.equal(data.totalSlots,dungeons.length*gameCharacters.length*4);
});

test("analytics period filter excludes other eras",()=>{
  const data=buildAnalytics([
    row(1,"Lass","Choco",84_000,"void_invasion","syntaxii_2026_archive"),
    row(2,"Lass","xandindj",74_000),
  ],dungeons,"current");
  assert.equal(data.verifiedRuns,1);
  assert.equal(data.boards[0].filledSlots,1);
});

test("processing rate is safe for an empty dataset",()=>{
  assert.equal(processingRate(7,10),70);
  assert.equal(processingRate(1,3),33);
  assert.equal(processingRate(0,0),0);
});
