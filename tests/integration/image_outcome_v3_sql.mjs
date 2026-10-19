// Real SQL/PLpgSQL in an isolated PostgreSQL engine; no production connection.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {PGlite}=await import(pathToFileURL(process.env.PGLITE_MODULE_PATH).href);
const db=new PGlite();
await db.exec(`create schema icg; create role anon; create role authenticated;
create role service_role bypassrls; grant usage on schema icg to service_role;
create table icg.episode_assets(episode_date date,episode_no int,status text,script_json jsonb,
 unique(episode_date,episode_no)); grant select,update on icg.episode_assets to service_role;`);
for(const p of ['migrations/20261001132931_image_generation_guard.sql',
 'docs/sql/image-generation-revision.sql','docs/sql/image-generation-recovery.sql',
 'docs/sql/image-generation-retry.sql','docs/sql/image-generation-attempt-diagnostics.sql',
 'docs/sql/image-generation-outcome-v3.sql','docs/sql/image-generation-register-recovery-v3.sql'])
 await db.exec(await readFile(p,'utf8'));
const scope='output/episodes/2026-10-20/panels', fp='a'.repeat(64), next='b'.repeat(64);
const checks=[];
async function check(name,fn){await fn();checks.push(name);}
async function rpc(name,args){return (await db.query(`select icg.${name}(${args.map((_,i)=>'$'+(i+1))}) as r`,args)).rows[0].r;}
async function reserve(panel=1){return rpc('image_generation_reserve',[scope,panel,fp]);}
async function finish(token,state='terminal',cost=.0007752,reason='PROHIBITED_CONTENT',hash=null){
 return rpc('image_generation_finish_outcome_v3',[scope,1,fp,token,state,cost,hash,reason,null,1]);
}
async function fixture(){
 await db.exec(`reset role; truncate icg.image_generation_diagnostics,icg.image_generation_attempt_diagnostics,
 icg.image_generation_recovery_receipts,icg.image_generation_calls,icg.image_generation_retry_plans,
 icg.episode_assets,icg.image_generation_run_status; set role service_role;`);
}
await check('known-cost refusal is settled but scope stays held',async()=>{
 assert.equal((await rpc('image_generation_outcome_v3_capability',[])).version,'image-outcome-3');
 await fixture();const {token}=await reserve();const r=await finish(token);
 assert.equal(r.settled,true);assert.equal(r.hold_code,'CONTENT_REVIEW_REQUIRED');
 assert.equal(r.retry_allowed,false);assert.equal(r.state,'terminal');
 assert.equal(Number(r.cost_usd),.0007752);assert.ok((await reserve(2)).hold);
});
await check('same settlement is idempotent; changed cost/reason conflicts',async()=>{
 await fixture();const {token}=await reserve();const first=await finish(token);
 assert.deepEqual(await finish(token),first);
 assert.equal((await finish(token,'terminal',.002)).hold,'conflicting settlement');
 assert.equal((await finish(token,'terminal',.0007752,'SAFETY')).hold,'conflicting settlement');
 assert.equal((await db.query('select count(*)::int as n from icg.image_generation_calls')).rows[0].n,1);
});
await check('unknown usage and over-budget costs remain reconciliation holds',async()=>{
 await fixture();const {token}=await reserve();const r=await finish(token,'terminal',null);
 assert.equal(r.state,'unknown');assert.equal(r.hold_code,'PROVIDER_OUTCOME_UNKNOWN');
 assert.ok((await reserve(2)).hold);
 await fixture();const t=(await reserve()).token;
 assert.equal((await finish(t,'terminal',.11)).hold_code,'GENERATION_COST_RECONCILIATION_REQUIRED');
});
await check('successful PNG requires hash and never resets historical cost',async()=>{
 await fixture();const {token}=await reserve();assert.ok((await finish(token,'success',.04,null)).hold);
 const r=await finish(token,'success',.04,null,'f'.repeat(64));assert.equal(r.state,'success');
 assert.equal((await rpc('image_generation_inspect',[scope,1,fp])).output_hash,'f'.repeat(64));
 assert.equal((await reserve()).hold,'already generated');
});
await check('reservation identity includes revision and retry plan',async()=>{
 await fixture();const {token}=await reserve();
 assert.ok((await rpc('image_generation_finish_outcome_v3',[scope,1,fp,token,'failed',0,null,null,null,2])).hold);
 assert.ok((await rpc('image_generation_finish_outcome_v3',[scope,1,fp,token,'failed',0,null,null,'z',1])).hold);
 assert.equal((await db.query('select state from icg.image_generation_calls')).rows[0].state,'reserved');
});
await check('run telemetry isolates attempts and refuses private payload fields',async()=>{
 await fixture();const report={run_id:'123',run_attempt:'1',complete:false,successful_images:0};
 assert.equal((await rpc('image_generation_store_run_status_v3',[scope,1,'123','1',JSON.stringify(report)])).stored,true);
 assert.ok((await rpc('image_generation_store_run_status_v3',[scope,1,'123','1',JSON.stringify({...report,prompt_text:'PRIVATE'})])).hold);
 assert.equal((await rpc('image_generation_store_run_status_v3',[scope,1,'123','2',JSON.stringify({...report,run_attempt:'2'})])).stored,true);
 assert.equal((await db.query('select count(*)::int as n from icg.image_generation_run_status')).rows[0].n,2);
});
const original={episode_id:'ICG-2026-10-20-001',date:'2026-10-20',event_type:'BATTLE',
 _state_candidate:{version:'state-candidate-1'},panels:[{idx:1,panel_type:'BATTLE',action:'old',setting:'room',characters:[],narration:'keep'}]};
function candidate(){return {...original,_generation_revision:2,_scene_contracts:{'1':{}},
 _reviewed_image_inputs:{version:'reviewed-image-inputs-1',model:'gemini-2.5-flash-image',aspect_ratio:null},
 panels:[{...original.panels[0],action:'Observe a separate display'}]};}
async function recoveryFixture(){
 await fixture();const {token}=await reserve();await finish(token);
 await db.exec('reset role');
 await db.query('insert into icg.episode_assets values($1,1,$2,$3)',['2026-10-20','narrative_done',JSON.stringify(original)]);
 await db.exec('set role service_role');return token;
}
async function register(token,script=candidate(),fingerprints={'1':next},source=original){
 return rpc('image_generation_register_recovery_v3',[JSON.stringify(source),JSON.stringify(script),token,2,
  .0007752,JSON.stringify(fingerprints),'operator','Reviewed non-contact scene, preserve cast and public story']);
}
await check('reviewed recovery registers candidate and receipt atomically',async()=>{
 const token=await recoveryFixture();assert.equal((await register(token)).registered,true);
 assert.equal((await register(token)).registered,true);
 assert.equal((await rpc('image_generation_recovery_preflight',[scope,2])).authorized,true);
 assert.equal((await rpc('image_generation_inspect_v2',[scope,1,next,2])).hold,undefined);
 assert.ok((await rpc('image_generation_inspect_v2',[scope,1,fp,2])).hold);
 assert.equal((await db.query('select count(*)::int as n from icg.image_generation_calls')).rows[0].n,1);
});
await check('failed recovery receipt rolls back candidate update',async()=>{
 const token=await recoveryFixture();await assert.rejects(()=>register(token,candidate(),{'1':fp}),/rolled back/);
 assert.deepEqual((await db.query('select script_json from icg.episode_assets')).rows[0].script_json,original);
 assert.equal((await db.query('select count(*)::int as n from icg.image_generation_recovery_receipts')).rows[0].n,0);
});
await check('source drift, cast changes and narrative changes cannot register',async()=>{
 const token=await recoveryFixture();
 assert.equal((await register(token,candidate(),{'1':next},{...original,title:'drift'})).hold,'recovery source changed');
 assert.ok((await register(token,{...candidate(),title:'invented'})).hold);
 const c=candidate();c.panels[0].characters=[{char_id:'invented'}];assert.ok((await register(token,c)).hold);
});
await check('new unknown call blocks reviewed recovery',async()=>{
 const token=await recoveryFixture();await db.query(`insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost)
 values($1,2,$2,'unknown',.1)`,[scope,next]);assert.ok((await register(token)).hold);
});
await check('anon and authenticated cannot execute or read new telemetry',async()=>{
 await fixture();const {token}=await reserve();
 for(const role of ['anon','authenticated']){
  await db.exec(`reset role; grant usage on schema icg to ${role}; set role ${role}`);
  await assert.rejects(()=>finish(token),/permission denied/);
  await assert.rejects(()=>register(token),/permission denied/);
  await assert.rejects(()=>db.query('select * from icg.image_generation_run_status'),/permission denied/);
 }
});
await db.close();
console.log(JSON.stringify({status:'PASS',checks:checks.length,cases:checks,
 limitation:'single PostgreSQL backend; multi-session lock contention and provider acceptance not tested'},null,2));
