// Isolated PostgreSQL contracts. No production connection or image provider.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {PGlite}=await import(pathToFileURL(process.env.PGLITE_MODULE_PATH).href);
const db=new PGlite(), checks=[];
await db.exec(`create schema icg;create role anon;create role authenticated;
create role service_role bypassrls;grant usage on schema icg to service_role;
create table icg.episode_assets(episode_date date,episode_no int,status text,script_json jsonb);
grant select,update on icg.episode_assets to service_role;`);
for(const path of ['migrations/20261001132931_image_generation_guard.sql',
 'docs/sql/image-generation-revision.sql','docs/sql/image-generation-recovery.sql',
 'docs/sql/image-generation-retry.sql','docs/sql/image-generation-register-repair-plans-v2.sql'])
 await db.exec(await readFile(path,'utf8'));
const scope='output/episodes/2026-10-22/panels';
const source={date:'2026-10-22',_generation_revision:1,panels:[{
 idx:1,panel_type:'TENSION',characters:[{char_id:'HERO'}],action:'original scene',
 setting:'room',narration:'hidden clue',key_text:'clue'}]};
function candidate(){
 const s=structuredClone(source),p=source.panels[0];
 s._reviewed_image_retry_plans={'1':{version:'image-retry-plan-2',plan_id:'a'.repeat(64),
 prompts:['base','reviewed different scene'],review:{actor:'reviewer',
 review_note:'Reviewed material scene change while preserving the hidden clue.',
 source:{cast:p.characters,action:p.action,setting:p.setting,narration:p.narration},repairs:[{}]}}};
 return s;
}
const fps={'1':['1'.repeat(64),'2'.repeat(64)]};
async function rpc(name,args){
 return (await db.query(`select icg.${name}(${args.map((_,i)=>'$'+(i+1))}) as r`,args)).rows[0].r;
}
const register=(s=candidate(),expected=source,fp=fps)=>rpc('image_generation_register_repair_plans_v2',
 [JSON.stringify(expected),JSON.stringify(s),JSON.stringify(fp)]);
async function fixture(){
 await db.exec('reset role;truncate icg.image_generation_diagnostics,icg.image_generation_recovery_receipts,icg.image_generation_calls,icg.image_generation_retry_plans,icg.episode_assets');
 await db.query('insert into icg.episode_assets values($1,1,$2,$3)',
 ['2026-10-22','narrative_done',JSON.stringify(source)]);
 await db.exec('set role service_role');
}
async function check(name,fn){await fn();checks.push(name);}
await check('atomic unchanged-source registration and idempotent retry',async()=>{
 await fixture();assert.equal((await register()).registered,true);assert.equal((await register()).registered,true);
 assert.equal((await db.query('select count(*)::int n from icg.image_generation_retry_plans')).rows[0].n,1);
 assert.deepEqual((await db.query('select script_json from icg.episode_assets')).rows[0].script_json,candidate());
});
await check('refusal selects revised fingerprint without repeating rejected inputs',async()=>{
 await fixture();await register();
 let first=await rpc('image_generation_reserve_retry',[scope,1,fps['1'][0],'a'.repeat(64)]);
 assert.ok(first.token);
 await rpc('image_generation_finish_retry',[scope,1,fps['1'][0],'a'.repeat(64),first.token,'terminal',.001,null,'PROHIBITED_CONTENT']);
 const cursor=await rpc('image_generation_retry_cursor',[scope,1,'a'.repeat(64)]);
 assert.equal(cursor.fingerprint,fps['1'][1]);assert.equal(cursor.attempts_used,1);
 assert.ok((await rpc('image_generation_reserve_retry',[scope,1,fps['1'][0],'a'.repeat(64)])).hold);
 assert.ok((await rpc('image_generation_reserve_retry',[scope,1,fps['1'][1],'a'.repeat(64)])).token);
});
await check('source or cast drift cannot mutate script or register plans',async()=>{
 for(const kind of ['title','cast']){
  await fixture();const s=candidate();if(kind==='title')s.title='changed';else s.panels[0].characters=[];
  assert.ok((await register(s)).hold);
  assert.deepEqual((await db.query('select script_json from icg.episode_assets')).rows[0].script_json,source);
  assert.equal((await db.query('select count(*)::int n from icg.image_generation_retry_plans')).rows[0].n,0);
 }
});
await check('stale expected source and missing review fail closed',async()=>{
 await fixture();assert.ok((await register(candidate(),{...source,title:'stale'})).hold);
 const s=candidate();s._reviewed_image_retry_plans['1'].review.review_note='short';
 assert.ok((await register(s)).hold);
});
await check('coverage, duplicate or invalid fingerprints do not partially register',async()=>{
 for(const fp of [{},{'1':['1'.repeat(64),'1'.repeat(64)]},{'1':['invalid','2'.repeat(64)]}]){
  await fixture();assert.ok((await register(candidate(),source,fp)).hold);
  assert.equal((await db.query('select count(*)::int n from icg.image_generation_retry_plans')).rows[0].n,0);
 }
});
await check('reserved unknown failed and terminal history require explicit recovery',async()=>{
 for(const state of ['reserved','unknown','failed','terminal']){
  await fixture();await db.query('insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost) values($1,1,$2,$3,.001)',[scope,'1'.repeat(64),state]);
  assert.ok((await register()).hold);
 }
});
await check('successful original can be reused but cannot be rewritten',async()=>{
 await fixture();await db.query("insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost,output_hash) values($1,1,$2,'success',.04,$3)",[scope,fps['1'][0],'f'.repeat(64)]);
 assert.equal((await register()).registered,true);
 assert.equal((await rpc('image_generation_retry_cursor',[scope,1,'a'.repeat(64)])).fingerprint,fps['1'][0]);
 await fixture();await db.query("insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost) values($1,1,$2,'success',.04)",[scope,'3'.repeat(64)]);
 assert.ok((await register()).hold);
});
await check('anonymous roles cannot invoke registration',async()=>{
 for(const role of ['anon','authenticated']){
  await db.exec(`reset role;grant usage on schema icg to ${role};set role ${role}`);
  await assert.rejects(()=>register(),/permission denied/);
 }
});
await db.close();
console.log(JSON.stringify({status:'PASS',checks:checks.length,cases:checks,
 limitation:'single backend; no provider acceptance or multi-session lock contention claim'},null,2));
