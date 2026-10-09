// Offline PostgreSQL contracts. PGLITE_MODULE_PATH points to pglite/dist/index.js.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {PGlite} = await import(pathToFileURL(process.env.PGLITE_MODULE_PATH).href);
const db = new PGlite();
await db.exec(`create schema icg;
create role anon; create role authenticated; create role service_role bypassrls;
grant usage on schema icg to service_role;`);
await db.exec(await readFile('migrations/20261001132931_image_generation_guard.sql','utf8'));
await db.exec(await readFile('docs/sql/image-generation-attempt-diagnostics.sql','utf8'));
const scope='output/episodes/2026-10-09/panels', fp='a'.repeat(64);
await db.exec('set role service_role');
async function rpc(name,args) {
 return (await db.query(`select icg.${name}(${args.map((_,i)=>'$'+(i+1)).join(',')}) as r`,args)).rows[0].r;
}
const {token}=await rpc('image_generation_reserve',[scope,2,fp]);
assert.ok(token);
const diagnostic=(kind,payload,overrides={})=>rpc('image_generation_store_attempt_diagnostic',
 [overrides.scope??scope,overrides.panel??2,overrides.fp??fp,overrides.token??token,kind,JSON.stringify(payload)]);
const input={prompt_text:'original adult fictional analyst observes data',ref_sha256:[]};
const checks=[];
async function check(name,body){await body();checks.push(name);}
await check('ordinary inputs do not require a reviewed retry plan',async()=>{
 assert.equal((await diagnostic('inputs',input)).stored,true);
});
await check('identical evidence is idempotent; changes are rejected',async()=>{
 assert.equal((await diagnostic('inputs',input)).stored,true);
 assert.equal((await diagnostic('inputs',{prompt_text:'changed'})).hold,'attempt diagnostic cannot change');
 assert.equal((await db.query('select count(*)::int as n from icg.image_generation_attempt_diagnostics')).rows[0].n,1);
});
await check('token, panel, scope and fingerprint must all match',async()=>{
 for(const overrides of [{token:'00000000-0000-0000-0000-000000000000'},{panel:3},
                         {scope:'output/episodes/2026-10-10/panels'},{fp:'b'.repeat(64)}]) {
  assert.equal((await diagnostic('refusal',{},overrides)).hold,'stale attempt diagnostic token');
 }
});
await check('refusal survives terminal settlement without unlocking the scope',async()=>{
 assert.ok((await rpc('image_generation_finish',[scope,2,fp,token,'terminal',0.000621,null])).hold);
 const payload={finish_reason:'PROHIBITED_CONTENT',cost_usd:0.000621,
                details:{finish_message:'provider evidence',safety_ratings:[]}};
 assert.equal((await diagnostic('refusal',payload)).stored,true);
 const rows=(await db.query('select state,cost from icg.image_generation_calls where token=$1',[token])).rows;
 assert.equal(rows[0].state,'terminal');assert.equal(Number(rows[0].cost),0.000621);
 assert.ok((await rpc('image_generation_reserve',[scope,3,'c'.repeat(64)])).hold);
});
await check('invalid kind, non-object and oversized payload are rejected',async()=>{
 assert.ok((await diagnostic('unknown',{})).hold);
 assert.ok((await diagnostic('refusal','string')).hold);
 assert.ok((await diagnostic('refusal',{large:'x'.repeat(262145)})).hold);
});
await check('late inputs cannot invent evidence for a finished call',async()=>{
 const other=(await db.query(`insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost)
 values($1,4,$2,'success',0.04) returning token`,[scope,'d'.repeat(64)])).rows[0].token;
 assert.equal((await diagnostic('inputs',input,{token:other,panel:4,fp:'d'.repeat(64)})).hold,
              'inputs must precede provider call');
});
await check('anon and authenticated cannot read, insert or execute',async()=>{
 for(const role of ['anon','authenticated']) {
  await db.exec('reset role; grant usage on schema icg to '+role+'; set role '+role);
  await assert.rejects(()=>db.query('select * from icg.image_generation_attempt_diagnostics'),/permission denied/);
  await assert.rejects(()=>diagnostic('inputs',input),/permission denied/);
  await assert.rejects(()=>db.query(`insert into icg.image_generation_attempt_diagnostics(token,kind,payload)
    values($1,'inputs','{}')`,[token]),/permission denied/);
 }
 await db.exec('reset role; set role service_role');
});
await check('service role cannot update or delete preserved evidence',async()=>{
 await assert.rejects(()=>db.query("update icg.image_generation_attempt_diagnostics set payload='{}'"),/permission denied/);
 await assert.rejects(()=>db.query('delete from icg.image_generation_attempt_diagnostics'),/permission denied/);
});
await db.close();
console.log(JSON.stringify({status:'PASS',checks:checks.length,cases:checks,
 limitation:'single backend; no paid calls or production changes'},null,2));
