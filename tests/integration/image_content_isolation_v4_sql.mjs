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
 'docs/sql/image-generation-outcome-v3.sql','docs/sql/image-generation-register-recovery-v3.sql',
 'docs/sql/image-generation-content-isolation-v4.sql'])
 await db.exec(await readFile(p,'utf8'));

const scope='output/episodes/2026-10-21/panels',fp='a'.repeat(64),other='b'.repeat(64);
const checks=[];
async function check(name,fn){await fn();checks.push(name);}
async function rpc(name,args){return (await db.query(`select icg.${name}(${args.map((_,i)=>'$'+(i+1))}) as r`,args)).rows[0].r;}
const inspect=(panel=2,fingerprint=other,revision=1)=>rpc('image_generation_inspect_independent_v4',[scope,panel,fingerprint,revision]);
const reserve=(panel=2,fingerprint=other,revision=1)=>rpc('image_generation_reserve_independent_v4',[scope,panel,fingerprint,revision]);
async function fixture(){
 await db.exec(`reset role; truncate icg.image_generation_diagnostics,icg.image_generation_attempt_diagnostics,
 icg.image_generation_recovery_receipts,icg.image_generation_calls,icg.image_generation_retry_plans,
 icg.episode_assets,icg.image_generation_run_status;
 insert into icg.episode_assets values('2026-10-21',1,'narrative_done','{}'); set role service_role;`);
}
async function refusal({cost=.001,reason='PROHIBITED_CONTENT',evidence=true}={}){
 const {token}=await reserve(1,fp);
 await rpc('image_generation_store_attempt_diagnostic',[scope,1,fp,token,'inputs',JSON.stringify({prompt_text:'test fixture'})]);
 const r=await rpc('image_generation_finish_outcome_v3',[scope,1,fp,token,'terminal',cost,null,reason,null,1]);
 if(evidence) await rpc('image_generation_store_attempt_diagnostic',[scope,1,fp,token,'refusal',JSON.stringify({finish_reason:reason})]);
 return {token,receipt:r};
}
await check('capability identifies all independent RPCs',async()=>{
 await fixture();assert.equal((await rpc('image_generation_content_isolation_v4_capability',[])).version,'image-content-isolation-4');
});
await check('settled evidenced refusal isolates only another panel; original RPC stays held',async()=>{
 await fixture();const {token}=await refusal();
 assert.equal((await inspect()).hold,undefined);assert.ok((await reserve()).token);
 assert.ok((await rpc('image_generation_inspect',[scope,2,other])).hold);
 const row=(await db.query('select state,result_code,cost from icg.image_generation_calls where token=$1',[token])).rows[0];
 assert.equal(row.state,'terminal');assert.equal(row.result_code,'CONTENT_REVIEW_REQUIRED');assert.equal(Number(row.cost),.001);
});
await check('rejected panel cannot be repeated or changed',async()=>{
 await fixture();await refusal();assert.ok((await reserve(1,fp)).hold);assert.ok((await reserve(1,other)).hold);
});
await check('unknown and reserved calls still block whole scope',async()=>{
 await fixture();await reserve(1,fp);assert.ok((await reserve()).hold);
 await fixture();await refusal({cost:null});assert.ok((await reserve()).hold);
});
await check('legacy null outcome metadata remains blocked',async()=>{
 await fixture();await db.query("insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost) values($1,1,$2,'terminal',.001)",[scope,fp]);
 assert.ok((await reserve()).hold);
});
await check('missing refusal evidence and mismatched reason remain blocked',async()=>{
 await fixture();const {token}=await refusal({evidence:false});assert.ok((await reserve()).hold);
 await rpc('image_generation_store_attempt_diagnostic',[scope,1,fp,token,'refusal',JSON.stringify({finish_reason:'SAFETY'})]);
 assert.ok((await reserve()).hold);
});
await check('over-cost and non-content terminal remain blocked',async()=>{
 await fixture();await refusal({cost:.11});assert.ok((await reserve()).hold);
 await fixture();await refusal({reason:'OTHER'});assert.ok((await reserve()).hold);
});
await check('all review reasons are terminal only for the rejected panel',async()=>{
 for(const reason of ['SAFETY','IMAGE_SAFETY','BLOCKLIST','RECITATION','IMAGE_RECITATION','SPII','IMAGE_PROHIBITED_CONTENT','ESCALATION','PUP_LIMITED_DISABLED']){
  await fixture();await refusal({reason});assert.equal((await inspect()).hold,undefined);assert.ok((await reserve(1,fp)).hold);
 }
});
await check('success hashes reuse at zero additional reservations',async()=>{
 await fixture();await refusal();const {token}=await reserve();
 await rpc('image_generation_finish_outcome_v3',[scope,2,other,token,'success',.04,'f'.repeat(64),null,null,1]);
 assert.equal((await inspect()).output_hash,'f'.repeat(64));
 assert.equal((await reserve()).hold,'already generated');
 assert.equal((await db.query('select count(*)::int as n from icg.image_generation_calls')).rows[0].n,2);
 assert.ok((await inspect(2,'c'.repeat(64))).hold);
});
await check('revision and malformed identity fail closed',async()=>{
 await fixture();for(const revision of [null,0,2,100]) assert.ok((await reserve(2,other,revision)).hold);
 assert.ok((await reserve(0)).hold);assert.ok((await reserve(2,'invalid')).hold);
});
await check('historic calls preserve lifetime budgets after isolation',async()=>{
 await fixture();await refusal();
 await db.query("insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost) select $1,2,$2,'failed',0 from generate_series(1,3)",[scope,other]);
 assert.equal((await reserve()).hold,'generation budget exhausted');
});
await check('queued reserves issue one token and preserve unknown scope stop',async()=>{
 await fixture();await refusal();const r=await Promise.all(Array.from({length:8},()=>reserve()));
 assert.equal(r.filter(x=>x.token).length,1);
});
await check('anonymous roles cannot read or invoke independent contract',async()=>{
 await fixture();for(const role of ['anon','authenticated']){
  await db.exec(`reset role; grant usage on schema icg to ${role}; set role ${role}`);
  await assert.rejects(()=>reserve(),/permission denied/);
  await assert.rejects(()=>rpc('image_generation_content_isolation_v4_capability',[]),/permission denied/);
 }
});

await check('current narrative revision and status cannot be bypassed',async()=>{
 for(const script of [{_generation_revision:2},{_generation_revision:'1'},{_generation_revision:null}]){
  await fixture();await db.query('update icg.episode_assets set script_json=$1',[JSON.stringify(script)]);
  assert.ok((await reserve()).hold);
 }
 await fixture();await db.query("update icg.episode_assets set status='published'");assert.ok((await reserve()).hold);
 await fixture();await db.exec('reset role; truncate icg.episode_assets; set role service_role');assert.ok((await reserve()).hold);
 await fixture();await db.query('update icg.episode_assets set script_json=$1',[JSON.stringify({_generation_revision:1})]);
 assert.ok((await reserve()).token);
});
await check('revision call history and reviewed plan cannot be downgraded',async()=>{
 await fixture();await db.query("insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost,revision) values($1,3,$2,'failed',0,2)",[scope,fp]);
 assert.ok((await reserve()).hold);
 await fixture();await db.query(`insert into icg.image_generation_retry_plans
 (plan_id,scope,panel,revision,fingerprints,script_json,review_evidence)
 values($1,$2,4,1,$3,'{}','Reviewed offline test plan forbids ordinary downgrade')`,
 ['d'.repeat(64),scope,JSON.stringify([fp])]);
 assert.ok((await reserve()).hold);
});
async function seedBudget(count,cost,{sameScope=false,samePanel=false,month=false}={}){
 // Synthetic historical ledger rows isolate each aggregate budget independently.
 await db.query(`insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost,created_at)
 select case when $1::boolean then $2 else 'historical-budget-'||g::text end,
 case when $3::boolean then 2 else g+10 end,$4,'failed',$5,
 case when $6::boolean then date_trunc('month',now() at time zone 'UTC') at time zone 'UTC' else now() end
 from generate_series(1,$7::integer) g`,[sameScope,scope,samePanel,other,cost,month,count]);
}
await check('scope lifetime count and cost caps preserve exact boundary',async()=>{
 await fixture();await seedBudget(30,0,{sameScope:true});assert.equal((await reserve()).hold,'generation budget exhausted');
 await fixture();await seedBudget(29,.1,{sameScope:true});assert.ok((await reserve()).token);
 await fixture();await seedBudget(29,.10001,{sameScope:true});assert.equal((await reserve()).hold,'generation budget exhausted');
});
await check('UTC day count and cost caps preserve exact boundary',async()=>{
 await fixture();await seedBudget(60,0);assert.equal((await reserve()).hold,'generation budget exhausted');
 await fixture();await seedBudget(59,0);assert.ok((await reserve()).token);
 await fixture();await seedBudget(10,.591);assert.equal((await reserve()).hold,'generation budget exhausted');
 await fixture();await seedBudget(10,.59);assert.ok((await reserve()).token);
});
await check('UTC month count and cost caps remain cumulative across earlier days',async()=>{
 const {day}= (await db.query("select extract(day from now() at time zone 'UTC')::int as day")).rows[0];
 if(day===1){
  // The monthly window equals the daily window on day one; daily caps are stricter.
  await fixture();await seedBudget(300,0,{month:true});assert.equal((await reserve()).hold,'generation budget exhausted');
  return;
 }
 await fixture();await seedBudget(300,0,{month:true});assert.equal((await reserve()).hold,'generation budget exhausted');
 await fixture();await seedBudget(299,0,{month:true});assert.ok((await reserve()).token);
 await fixture();await seedBudget(150,.2,{month:true});assert.equal((await reserve()).hold,'generation budget exhausted');
 await fixture();await seedBudget(150,.199,{month:true});assert.ok((await reserve()).token);
});

await db.close();
console.log(JSON.stringify({status:'PASS',checks:checks.length,cases:checks,
 limitation:'single PostgreSQL backend; multi-session lock contention and provider acceptance not tested'},null,2));
