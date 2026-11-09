import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {stripTypeScriptTypes} from 'node:module';
import {DatabaseSync} from 'node:sqlite';
import {randomUUID} from 'node:crypto';
import test from 'node:test';

// Run the real route handlers and their real SQL against SQLite. Only the
// Cloudflare transport is adapted, so a broken JSON merge fails this test.
async function fixture(t) {
  const db = new DatabaseSync(':memory:'); t.after(()=>db.close());
  db.exec(`CREATE TABLE candidates (id INTEGER PRIMARY KEY, video_id TEXT UNIQUE,
    video_url TEXT, title TEXT, channel TEXT, player_nick TEXT, published_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    character TEXT, category TEXT, floor INTEGER, time_ms INTEGER, confidence REAL,
    status TEXT, era_key TEXT, raw_metadata TEXT DEFAULT '{}');
    CREATE TABLE rankings (id INTEGER PRIMARY KEY, candidate_id INTEGER UNIQUE,
    character TEXT, category TEXT, floor INTEGER, time_ms INTEGER, player_nick TEXT,
    era_key TEXT, approved_at TEXT DEFAULT CURRENT_TIMESTAMP);`);
  function prepare(sql, values=[]) {
    return { bind: (...params)=>prepare(sql,params),
      run: async()=>({meta:{changes:Number(db.prepare(sql).run(...values).changes)}}),
      all: async()=>({results:db.prepare(sql).all(...values)}),
      first: async()=>db.prepare(sql).get(...values) };
  }
  const env={INGEST_API_TOKEN:'test-ingest',DB:{prepare,batch:items=>Promise.all(items.map(i=>i.run()))}};
  globalThis.__ocrTestEnv=env;
  async function route(path) {
    let source=await readFile(new URL(path,import.meta.url),'utf8');
    source=source.replace('import { env } from "cloudflare:workers";', 'const env=globalThis.__ocrTestEnv;');
    source=source.replaceAll(/"@\/lib\/([^"\n]+)"/g,(_,name)=>JSON.stringify(new URL(`../lib/${name}.ts`,import.meta.url).href));
    return import('data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(source)+`\n// ${randomUUID()}`).toString('base64'));
  }
  const candidates=await route('../app/api/candidates/route.ts');
  const outcomes=await route('../app/api/candidates/ocr-outcomes/route.ts');
  const post=(handler,body,headers={authorization:'Bearer test-ingest'})=>handler(new Request('https://example.test/api',{method:'POST',headers:{'content-type':'application/json',...headers},body:JSON.stringify(body)}));
  const candidate=(extra={})=>({video_id:'video',video_url:'https://youtu.be/video',title:'Ronan Duel 4',
    character:'Ronan',category:'duel_4',floor:0,status:'time_required',confidence:.7,era_key:'current',raw_metadata:{description:'old'},...extra});
  const metadata=()=>JSON.parse(db.prepare('SELECT raw_metadata FROM candidates WHERE video_id=?').get('video').raw_metadata);
  return {db,candidates,outcomes,post,candidate,metadata};
}

test('crawler insert → OCR failure → crawler metadata refresh preserves diagnostics and new description',async t=>{
  const f=await fixture(t);
  await f.post(f.candidates.POST,{candidates:[f.candidate()]});
  const result=await f.post(f.outcomes.POST,{outcomes:[{video_id:'video',result:'no_consensus',
    failure_reason:'timer_not_found',ocr_attempted_at:'2026-11-09T12:00:00Z',ocr_attempts:3,
    ocr_version:'gc-ocr-diagnostics-v1',evidence_seconds:15,evidence_image:'ocr-evidence/video.png',
    ocr_diagnostics:{sampled_frames:45,results_frames:2,readable_frames:0}}]});
  assert.equal((await result.json()).updated,1);
  await f.post(f.candidates.POST,{candidates:[f.candidate({title:'Updated Ronan Duel 4',raw_metadata:{description:'new'}})]});
  const m=f.metadata();
  assert.equal(m.description,'new'); assert.equal(m.failure_reason,'timer_not_found');
  assert.equal(m.ocr_attempts,3); assert.equal(m.ocr_version,'gc-ocr-diagnostics-v1');
  assert.equal(m.evidence_seconds,15); assert.equal(m.evidence_image,'ocr-evidence/video.png');
  const report=await (await f.candidates.GET()).json();
  assert.equal(report.candidates[0].failure_reason,'timer_not_found');
  assert.deepEqual(report.ocr_failures,{total_failed:1,breakdown:{timer_not_found:1}});
});

test('older OCR reports cannot overwrite newer reasons or reduce the counter',async t=>{
  const f=await fixture(t);await f.post(f.candidates.POST,{candidates:[f.candidate()]});
  await f.post(f.outcomes.POST,{outcomes:[{video_id:'video',outcome:'error',failure_reason:'download_error',
    attempted_at:'2026-11-09T12:00:00Z',attempts:5}]});
  await f.post(f.outcomes.POST,{outcomes:[{video_id:'video',outcome:'no_consensus',failure_reason:'timer_not_found',
    attempted_at:'2026-11-08T12:00:00Z',attempts:1}]});
  await f.post(f.candidates.POST,{candidates:[f.candidate({raw_metadata:{description:'fresh title',
    ocr_attempted_at:'2026-11-08T12:00:00.000Z',ocr_attempts:1,failure_reason:'timer_not_found'}})]});
  assert.equal(f.metadata().description,'fresh title');
  assert.equal(f.metadata().failure_reason,'download_error');assert.equal(f.metadata().ocr_attempts,5);
  await f.post(f.candidates.POST,{candidates:[f.candidate({raw_metadata:{
    ocr_outcome:'no_consensus',ocr_attempted_at:'2026-11-10T12:00:00.000Z',
    ocr_attempts:1,failure_reason:'timer_not_found'}})]});
  assert.equal(f.metadata().failure_reason,'timer_not_found');
  assert.equal(f.metadata().ocr_attempts,5);
});

test('resolved/protected candidates are excluded and aggregation is not limited to the first queue page',async t=>{
  const f=await fixture(t);
  const insert=f.db.prepare(`INSERT INTO candidates(video_id,status,time_ms,raw_metadata)
    VALUES(?,?,?,?)`);
  const meta=JSON.stringify({ocr_outcome:'no_consensus',failure_reason:'results_screen_not_found'});
  for(let i=0;i<501;i++)insert.run('pending'+i,'time_required',null,meta);
  insert.run('approved','approved',null,meta);insert.run('rejected','rejected',null,meta);
  insert.run('resolved','ready_for_review',80000,meta);
  const report=await (await f.candidates.GET()).json();
  assert.equal(report.candidates.length,500);
  assert.deepEqual(report.ocr_failures,{total_failed:501,breakdown:{results_screen_not_found:501}});
  const response=await f.post(f.outcomes.POST,{outcomes:[{video_id:'approved',outcome:'error'}]});
  assert.equal((await response.json()).updated,0);
});

test('legacy failures stay generic and a changed run identity discards incompatible diagnostics',async t=>{
  const f=await fixture(t);await f.post(f.candidates.POST,{candidates:[f.candidate()]});
  await f.post(f.outcomes.POST,{outcomes:[{video_id:'video',outcome:'no_consensus'}]});
  let report=await (await f.candidates.GET()).json();
  assert.equal(report.ocr_failures.breakdown.timer_not_frozen_or_not_readable,1);
  assert.equal(report.candidates[0].failure_reason,'timer_not_frozen_or_not_readable');
  await f.post(f.candidates.POST,{candidates:[f.candidate({character:'Arme'})]});
  assert.equal(f.metadata().failure_reason,undefined);
  report=await (await f.candidates.GET()).json();assert.equal(report.ocr_failures.total_failed,0);
});

test('outcome input is authenticated, validates reasons, bounds batches and normalizes timestamps',async t=>{
  const f=await fixture(t);await f.post(f.candidates.POST,{candidates:[f.candidate()]});
  assert.equal((await f.post(f.outcomes.POST,{outcomes:[]},{})).status,401);
  const invalid=await f.post(f.outcomes.POST,{outcomes:[null,{video_id:'video',outcome:'other'},
    {video_id:'video',outcome:'error',failure_reason:'invented'},
    {video_id:'video',outcome:'error',attempts:-1},{video_id:'video',outcome:'error',attempted_at:'invalid'}]});
  assert.equal((await invalid.json()).received,0);
  const body={video_id:'video',outcome:'error',attempted_at:'2026-11-09T09:00:00-03:00'};
  const bounded=await f.post(f.outcomes.POST,{outcomes:Array(510).fill(body)});
  assert.equal((await bounded.json()).received,500);
  assert.equal(f.metadata().ocr_attempted_at,'2026-11-09T12:00:00.000Z');
  assert.equal(f.metadata().ocr_attempts,1);
});
