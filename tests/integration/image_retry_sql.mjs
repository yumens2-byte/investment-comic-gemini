// Run: PGLITE_MODULE_PATH=/absolute/path/to/pglite/dist/index.js node tests/integration/image_retry_sql.mjs
// This exercises PostgreSQL SQL/PLpgSQL, not multi-backend advisory-lock contention.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const modulePath = process.env.PGLITE_MODULE_PATH;
if (!modulePath) throw new Error('PGLITE_MODULE_PATH required');
const {PGlite} = await import(pathToFileURL(modulePath).href);
const db = new PGlite();
const checks=[];
async function check(name, body) {await body(); checks.push(name);}
await db.exec(`create schema icg;
create role anon; create role authenticated; create role service_role bypassrls;
grant usage on schema icg to service_role;
create table icg.episode_assets(episode_date date, episode_no int, status text, script_json jsonb);
grant select,update on icg.episode_assets to service_role;`);
for (const path of ['migrations/20261001132931_image_generation_guard.sql',
                   'docs/sql/image-generation-revision.sql','docs/sql/image-generation-recovery.sql',
                   'docs/sql/image-generation-retry.sql']) await db.exec(await readFile(path,'utf8'));
const scope='output/episodes/2026-10-08/panels';
const plan='a'.repeat(64), fps=['1'.repeat(64),'2'.repeat(64),'3'.repeat(64)];
const script={_generation_revision:1,panels:[{idx:4,panel_type:'TENSION'}]};
async function fixture() {
 await db.exec('reset role; truncate icg.image_generation_diagnostics,icg.image_generation_recovery_receipts,icg.image_generation_calls,icg.image_generation_retry_plans,icg.episode_assets;');
 await db.query('insert into icg.episode_assets values($1,1,$2,$3)', ['2026-10-08','narrative_done',JSON.stringify(script)]);
 await db.query(`insert into icg.image_generation_retry_plans(plan_id,scope,panel,revision,fingerprints,script_json,review_evidence)
                 values($1,$2,4,1,$3,$4,$5)`,[plan,scope,JSON.stringify(fps),JSON.stringify(script),'Reviewed nonviolent observation scenes; offline test fixture']);
 await db.exec('set role service_role');
}
async function rpc(name,args) {
 const placeholders=args.map((_,i)=>'$'+(i+1)).join(',');
 return (await db.query(`select icg.${name}(${placeholders}) as result`,args)).rows[0].result;
}
const reserve=(fp=fps[0])=>rpc('image_generation_reserve_retry',[scope,4,fp,plan]);
const finish=(token,state,cost,fp=fps[0],reason=null,hash=null)=>rpc('image_generation_finish_retry',[scope,4,fp,plan,token,state,cost,hash,reason]);
await check('first reservation, refusal settlement, next variant cursor',async()=>{
 await fixture();const first=await reserve();assert.ok(first.token);
 assert.equal((await finish(first.token,'terminal',0.000561,fps[0],'PROHIBITED_CONTENT')).settled,true);
 const cursor=await rpc('image_generation_retry_cursor',[scope,4,plan]);
 assert.equal(cursor.fingerprint,fps[1]);assert.equal(cursor.attempts_used,1);
 assert.ok((await reserve(fps[0])).hold);assert.ok((await reserve(fps[1])).token);
});
await check('three lifetime calls, no fourth across variants',async()=>{
 await fixture();for(const fp of fps){const r=await reserve(fp);assert.ok(r.token);await finish(r.token,'failed',0.001,fp);}
 assert.equal((await reserve()).hold,'generation budget exhausted');
});
await check('queued concurrent reservations issue only one token',async()=>{
 await fixture();const results=await Promise.all(Array.from({length:12},()=>reserve()));
 assert.equal(results.filter(x=>x.token).length,1);
});
await check('idempotent settlement and conflicting settlement',async()=>{
 await fixture();const {token}=await reserve();assert.equal((await finish(token,'failed',0.001)).settled,true);
 assert.equal((await finish(token,'failed',0.001)).settled,true);
 assert.equal((await finish(token,'failed',0.002)).hold,'conflicting settlement');
});
await check('unknown billing blocks the entire scope',async()=>{
 await fixture();const {token}=await reserve();assert.ok((await finish(token,'unknown',null)).hold);
 assert.ok((await reserve(fps[1])).hold);
});
await check('successful alternative is reused by cursor',async()=>{
 await fixture();const first=await reserve();await finish(first.token,'terminal',0.001,fps[0],'SAFETY');
 const second=await reserve(fps[1]);await finish(second.token,'success',0.04,fps[1],null,'f'.repeat(64));
 const cursor=await rpc('image_generation_retry_cursor',[scope,4,plan]);
 assert.equal(cursor.fingerprint,fps[1]);
 assert.equal((await reserve(fps[1])).hold,'already generated');
});
await check('missing review and changed persisted script fail closed',async()=>{
 await fixture();assert.ok((await rpc('image_generation_inspect_retry',[scope,4,fps[0],'b'.repeat(64)])).hold);
 await db.query("update icg.episode_assets set script_json=script_json||'{\"title\":\"changed\"}'::jsonb");
 assert.equal((await reserve()).hold,'reviewed script changed');
});
await check('old terminal is not implicitly acknowledged',async()=>{
 await fixture();await db.query(`insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost,revision)
 values($1,4,$2,'terminal',0.000561,1)`,[scope,'e'.repeat(64)]);
 assert.ok((await reserve()).hold);
});
await check('over-budget settlement remains held',async()=>{
 await fixture();const {token}=await reserve();assert.ok((await finish(token,'terminal',0.11,fps[0],'SAFETY')).hold);
 assert.ok((await reserve(fps[1])).hold);
});
await check('anon cannot execute retry RPC or read plans',async()=>{
 await fixture();await db.exec('set role anon');
 await assert.rejects(()=>reserve(),/permission denied/);
 await assert.rejects(()=>db.query('select * from icg.image_generation_retry_plans'),/permission denied/);
});
await check('private evidence persists and anon cannot read it',async()=>{
 await fixture();const r=await rpc('image_generation_store_diagnostic',[scope,4,plan,'inputs',JSON.stringify({prompts:['quiet observation']})]);
 assert.equal(r.stored,true);
 assert.equal((await db.query('select count(*)::int as n from icg.image_generation_diagnostics')).rows[0].n,1);
 await db.exec('set role anon');
 await assert.rejects(()=>db.query('select * from icg.image_generation_diagnostics'),/permission denied/);
});
await db.exec('reset role');
const version=(await db.query('select version() as version')).rows[0].version;
await db.close();
console.log(JSON.stringify({status:'PASS',checks:checks.length,version,cases:checks,limitation:'single backend; multi-session lock contention unverified'},null,2));
