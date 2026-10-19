// Execute real PL/pgSQL against isolated PostgreSQL; no production connection.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {PGlite}=await import(pathToFileURL(process.env.PGLITE_MODULE_PATH).href);
const db=new PGlite();
await db.exec(`create schema icg; create role anon; create role authenticated;
create role service_role bypassrls; grant usage on schema icg to service_role;
create table icg.episode_assets(episode_date date,episode_no int,status text,script_json jsonb,
 artifact_run_id text, unique(episode_date,episode_no));
grant select,update on icg.episode_assets to service_role;`);
for(const p of ['migrations/20261001132931_image_generation_guard.sql',
 'docs/sql/image-generation-revision.sql','docs/sql/image-generation-recovery.sql',
 'docs/sql/image-generation-retry.sql','docs/sql/image-generation-attempt-diagnostics.sql',
 'docs/sql/image-generation-outcome-v3.sql','docs/sql/image-generation-register-recovery-v3.sql',
 'docs/sql/image-quality-candidates.sql']) await db.exec(await readFile(p,'utf8'));
const scope='output/episodes/2026-10-20/panels', fp='a'.repeat(64), newer='b'.repeat(64), oldHash='c'.repeat(64), newHash='d'.repeat(64);
const source={date:'2026-10-20',panels:[{idx:1,panel_type:'CLIMAX',characters:[{char_id:'hero'}],
 action:'stands still',setting:'vault',narration:'unchanged'}]};
const base=[{panel_idx:1,output_hash:oldHash,artifact_run_id:'123',artifact_name:'episode-123',artifact_path:'2026-10-20/panels/P1.png'}];
function bundle(){return {version:'image-quality-candidate-1',purpose:'QUALITY_RETAKE',
 id:'11111111-1111-4111-8111-111111111111',date:'2026-10-20',revision:3,
 source_script:source,candidate_script:{...source,_generation_revision:3,
 _reviewed_image_inputs:{version:'reviewed-image-inputs-2',aspect_ratio:'4:5',panels:[{idx:1,fingerprint:newer}]},
 panels:[{...source.panels[0],action:'turns toward dial'}]},base_manifest:base,base_artifact_run_id:'123',
 base_selection_version:0,max_calls:1,max_cost_usd:.1,panels:[{panel_idx:1,fingerprint:newer}]};}
const checks=[];
async function check(name,fn){await fn();checks.push(name);}
async function rpc(name,args){return(await db.query(`select icg.${name}(${args.map((_,i)=>'$'+(i+1)).join(',')}) as r`,args)).rows[0].r;}
async function fixture(){
 await db.exec(`reset role; truncate icg.image_generation_attempt_diagnostics,icg.image_generation_diagnostics,
 icg.image_generation_recovery_receipts,icg.image_generation_calls,icg.image_quality_selection_history,
 icg.image_quality_selections,icg.image_quality_candidates,icg.episode_assets cascade;`);
 await db.query('insert into icg.episode_assets values($1,1,$2,$3,$4)', ['2026-10-20','image_generated',JSON.stringify(source),'123']);
 await db.query(`insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost,output_hash,revision)
 values($1,1,$2,'success',.04,$3,2)`,[scope,fp,oldHash]);
 await db.exec(`insert into icg.image_generation_attempt_diagnostics(token,kind,payload)
 select token,'inputs','{"run_id":"123"}'::jsonb from icg.image_generation_calls; set role service_role`);
}
async function register(b=bundle()){return rpc('image_quality_register',[JSON.stringify(b)]);}
async function approve(b=bundle()){
 const r=await register(b);assert.equal(r.registered,true,JSON.stringify(r));
 assert.equal((await rpc('image_quality_approve',[b.id,r.digest,'operator','Reviewed exact motion, camera, references and budget'])).approved,true);
 return r;
}
async function reserve(b=bundle()){return rpc('image_quality_reserve',[b.id,1,newer,'456']);}
async function finish(token,state='success',cost=.04,hash=newHash){return rpc('image_generation_finish_outcome_v3',
 [scope,1,newer,token,state,cost,hash,null,null,3]);}
function review(){return {episode_continuity:'PASS',evidence:'Compared whole episode and composed previews',panels:[
 {panel_idx:1,output_hash:newHash,safety:'PASS',canon:'PASS',quality:'REVIEW',assembly:'PASS',
 evidence:'Actual pose and camera inspected; minor lighting warning accepted'}]};}
async function ready(){const r=await approve();const t=(await reserve()).token;assert.ok(t);assert.equal((await finish(t)).settled,true);
 assert.equal((await rpc('image_quality_review',[bundle().id,r.digest,'reviewer',JSON.stringify(review())])).reviewed,true);return r;}
await check('unapproved generation blocked; registration is idempotent and private',async()=>{
 await fixture();const r=await register();assert.equal(r.registered,true,JSON.stringify(r));assert.deepEqual(await register(),r);
 assert.ok((await reserve()).hold);
 assert.ok((await rpc('image_quality_approve',[bundle().id,'wrong','op','Reviewed exact motion, camera and budget'])).hold);
});
await check('source, story, cast and base artifact drift blocked',async()=>{
 for(const mutate of [b=>b.source_script={...source,title:'drift'},b=>b.candidate_script.panels[0].narration='invented',
 b=>b.candidate_script.panels[0].characters=[],b=>b.base_artifact_run_id='999',b=>b.base_manifest=[{...base[0],output_hash:fp}],
 b=>b.panels=[...b.panels,...b.panels],b=>b.max_cost_usd=.01]){
 await fixture();const b=structuredClone(bundle());mutate(b);assert.ok((await register(b)).hold);}
});
await check('approved reservation uses canonical scope and preserves cumulative attempts and cost',async()=>{
 await fixture();await approve();const r=await reserve();assert.ok(r.token,JSON.stringify(r));
 assert.ok((await reserve()).hold);
 assert.equal((await finish(r.token)).settled,true);
 assert.equal((await rpc('image_quality_inspect',[bundle().id,1,newer])).output_hash,newHash);
 assert.equal(Number((await db.query('select sum(cost) s from icg.image_generation_calls')).rows[0].s),.08);
 assert.equal((await db.query('select status from icg.episode_assets')).rows[0].status,'image_generated');
});
await check('new candidate cannot reset lifetime panel cap',async()=>{
 await fixture();await db.exec('reset role');
 await db.query(`insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost,revision)
 values($1,1,$2,'failed',0,1),($1,1,$2,'failed',0,1)`,[scope,fp]);await db.exec('set role service_role');
 await approve();assert.equal((await reserve()).hold,'generation budget exhausted');
});
await check('scope/global cost cap and unknown outcomes block generation',async()=>{
 for(const state of ['unknown','reserved','terminal']){
 await fixture();await db.exec('reset role');await db.query(`insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost)
 values($1,2,$2,$3,.1)`,[scope,fp,state]);await db.exec('set role service_role');
 await approve();assert.ok((await reserve()).hold);}
 await fixture();await db.exec('reset role');await db.query(`insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost)
 values($1,2,$2,'failed',2.9)`,[scope,fp]);await db.exec('set role service_role');
 await approve();assert.equal((await reserve()).hold,'generation budget exhausted');
});
await check('failed retake has no second paid reservation',async()=>{
 await fixture();await approve();const t=(await reserve()).token;await finish(t,'failed',.002,null);
 assert.ok((await reserve()).hold);assert.ok((await rpc('image_quality_inspect',[bundle().id,1,newer])).hold);
});
await check('human review binds hashes, canon, safety and composed preview',async()=>{
 await fixture();const r=await approve();const t=(await reserve()).token;await finish(t);
 for(const mutate of [r=>r.panels[0].output_hash=fp,r=>r.panels[0].canon='FAIL',r=>r.panels[0].assembly='UNKNOWN',
 r=>r.panels[0].safety='FAIL',r=>r.episode_continuity='UNKNOWN',r=>r.panels=[]]){
 const v=review();mutate(v);assert.ok((await rpc('image_quality_review',[bundle().id,r.digest,'reviewer',JSON.stringify(v)])).hold);}
 assert.ok((await rpc('image_quality_select',[bundle().id,r.digest,0,'operator','Select reviewed generated images'])).hold);
});
await check('selection is atomic, versions conflict, episode state and original remain intact',async()=>{
 await fixture();const r=await ready();const selected=await rpc('image_quality_select',[bundle().id,r.digest,0,'operator','Select the reviewed quality image candidate']);
 assert.equal(selected.selected,true,JSON.stringify(selected));assert.equal(selected.version,1);assert.equal(selected.publication_authorized,false);
 assert.equal(selected.manifest[0].artifact_run_id,'456');assert.equal(selected.manifest[0].output_hash,newHash);
 assert.ok((await rpc('image_quality_select',[bundle().id,r.digest,0,'operator','Select reviewed generated images'])).hold);
 assert.deepEqual((await db.query('select script_json from icg.episode_assets')).rows[0].script_json,source);
 assert.equal((await db.query('select artifact_run_id from icg.episode_assets')).rows[0].artifact_run_id,'123');
 const rolled=await rpc('image_quality_rollback',[scope,1,0,'operator','Restore original approved successful images']);
 assert.equal(rolled.version,2);assert.deepEqual(rolled.manifest,base);
 assert.equal((await db.query('select count(*)::int n from icg.image_quality_selection_history')).rows[0].n,3);
});
await check('source changes and publication after approval invalidate generation and selection',async()=>{
 await fixture();const r=await ready();await db.exec(`reset role; update icg.episode_assets set status='published'; set role service_role`);
 assert.ok((await reserve()).hold);
 assert.ok((await rpc('image_quality_select',[bundle().id,r.digest,0,'operator','Select reviewed generated images'])).hold);
});
await check('cancel does not forgive unknown calls or remove the selected manifest',async()=>{
 await fixture();const r=await approve();
 assert.equal((await rpc('image_quality_cancel',[bundle().id,r.digest,'operator','Cancel draft and preserve original successful images'])).cancelled,true);
 assert.ok((await reserve()).hold);
 await fixture();const approved=await approve();const t=(await reserve()).token;
 await finish(t,'unknown',null,null);
 assert.ok((await rpc('image_quality_cancel',[bundle().id,approved.digest,'operator','Cancel draft and preserve original successful images'])).hold);
});
await check('anon/authenticated have no table or RPC access',async()=>{
 await fixture();
 for(const role of ['anon','authenticated']){
 await db.exec(`reset role; grant usage on schema icg to ${role}; set role ${role}`);
 await assert.rejects(()=>register(),/permission denied/);
 await assert.rejects(()=>reserve(),/permission denied/);
 await assert.rejects(()=>db.query('select * from icg.image_quality_candidates'),/permission denied/);
 await assert.rejects(()=>db.query('select * from icg.image_quality_selection_history'),/permission denied/);
 }
});
await db.close();console.log(JSON.stringify({status:'PASS',checks:checks.length,cases:checks,
 limitation:'single backend; concurrent runner lock contention and real provider quality are not simulated'},null,2));
