// Real PL/pgSQL in an isolated backend. No production or provider connection.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const {PGlite}=await import(pathToFileURL(process.env.PGLITE_MODULE_PATH).href);
const db=new PGlite();
await db.exec(`create schema icg; create role anon; create role authenticated;
create role service_role bypassrls; grant usage on schema icg to service_role;
create table icg.episode_assets(episode_date date,episode_no int,status text,script_json jsonb,
 artifact_run_id text,error_message text,updated_at timestamptz not null default clock_timestamp(),unique(episode_date,episode_no));
grant select,insert,update on icg.episode_assets to service_role;`);
for(const p of ['migrations/20261001132931_image_generation_guard.sql','docs/sql/image-generation-revision.sql',
 'docs/sql/image-generation-recovery.sql','docs/sql/image-generation-retry.sql',
 'docs/sql/image-generation-attempt-diagnostics.sql','docs/sql/image-generation-outcome-v3.sql',
 'docs/sql/image-generation-register-recovery-v3.sql','docs/sql/image-quality-candidates.sql',
 'supabase/migrations/20261026041544_visual_quality_contracts.sql']) await db.exec(await readFile(p,'utf8'));
const day='2026-10-26',scope=`output/episodes/${day}/panels`,hash=n=>n.repeat(64);
const policy={version:'visual-quality-1',mode:'enforce',layout:'mobile-reserved-band-1',layout_sha256:hash('d')};
const source={date:day,episode_id:`ICG-${day}-001`,_state_candidate:{version:'state-candidate-1'},panels:[1,2].map(idx=>({idx,panel_type:'BATTLE',
 characters:[{char_id:'hero',form:'form0'}],action:'turns toward the dial',setting:'vault',narration:'unchanged'})),
 _scene_performance_v2:{'1':{panel_idx:1,required_story_facts:['unchanged']},'2':{panel_idx:2,required_story_facts:['unchanged']}}};
function initial(){return {...structuredClone(source),_generation_revision:1,_reviewed_image_inputs:{
 version:'reviewed-image-inputs-2',origin:'INITIAL_GENERATION',model:'gemini-2.5-flash-image',aspect_ratio:'4:5',ref_binding_version:'canon-form-1',
 panels:[1,2].map(idx=>({idx,fingerprint:hash(idx===1?'a':'b'),scene_sha256:hash(idx===1?'c':'d'),ref_bindings:[]}))}};}
async function rpc(name,args=[]){return (await db.query(`select icg.${name}(${args.map((_,i)=>'$'+(i+1)).join(',')}) r`,args)).rows[0].r;}
async function fixture(){
 await db.exec(`reset role; truncate icg.visual_quality_claims,icg.visual_quality_revocations,icg.visual_quality_reviews,
 icg.visual_quality_inputs,icg.image_quality_candidates,icg.image_quality_selections,icg.image_quality_selection_history,
 icg.image_generation_attempt_diagnostics,icg.image_generation_diagnostics,icg.image_generation_recovery_receipts,
 icg.image_generation_calls,icg.episode_assets cascade`);
 await db.query('insert into icg.episode_assets(episode_date,episode_no,status,script_json,artifact_run_id) values($1,1,$2,$3,$4)',[day,'narrative_done',JSON.stringify(source),'999']);
 await db.exec('set role service_role');
}
async function freeze(){return rpc('visual_quality_freeze_inputs',[JSON.stringify(source),JSON.stringify(initial()),JSON.stringify(policy),'operator','Freeze reviewed exact visual inputs before any provider call']);}
async function row(){return (await db.query('select * from icg.episode_assets')).rows[0];}
async function call(idx,state='success'){
 return (await db.query(`insert into icg.image_generation_calls(scope,panel,fingerprint,state,cost,output_hash,revision,provider_reason,result_code,settled_at)
 values($1,$2,$3,$4,.04,$5,1,$6,$7,clock_timestamp()) returning token`,
 [scope,idx,hash(idx===1?'a':'b'),state,state==='success'?hash(idx===1?'e':'f'):null,
 state==='terminal'?'PROHIBITED_CONTENT':null,state==='terminal'?'CONTENT_REVIEW_REQUIRED':null])).rows[0].token;
}
async function assembled(){
 const frozen=(await freeze()).script;assert.ok(frozen);
 const tokens=[await call(1),await call(2)];
 for(const token of tokens) await db.query(`insert into icg.image_generation_attempt_diagnostics(token,kind,payload)
 values($1,'inputs','{"run_id":"999"}')`,[token]);
 const effective=[1,2].map((idx,i)=>({panel_idx:idx,output_hash:hash(idx===1?'e':'f'),fingerprint:hash(idx===1?'a':'b'),
 origin_token:tokens[i],origin_revision:1,candidate_id:null,scene_sha256:hash(idx===1?'c':'d'),
 scene:frozen._scene_performance_v2[idx],ref_bindings:[]}));
 const script={...frozen,_effective_render_manifest:effective,_mobile_layout_report:{version:'mobile-layout-report-1'},
 _assembly_manifest:{version:'assembly-manifest-2',policy_sha256:frozen._visual_policy_sha256,effective_render_manifest:effective,slides:[hash('1'),hash('2')]}};
 script._assembly_manifest.visual_contract={policy:script._visual_policy,scene_plan:script._scene_performance_v2,
 mobile_layout_report:script._mobile_layout_report,public_script:Object.fromEntries(Object.entries(script).filter(([k])=>!k.startsWith('_')))};
 await db.query(`update icg.episode_assets set status='assembled',script_json=$1`,[JSON.stringify(script)]);
 return JSON.parse(JSON.stringify(script));
}
function review(script){return {episode_continuity:'PASS',evidence:'Human inspected every original image and the complete mobile sequence',
 panels:script._effective_render_manifest.map((p,i)=>({panel_idx:p.panel_idx,output_hash:p.output_hash,slide_hash:script._assembly_manifest.slides[i],
 checks:Object.fromEntries(['motion','rhythm','canon','story','typography','mobile'].map(k=>[k,{status:'PASS',evidence:'Human checked the exact image and observed this visual requirement'}]))}))};}
async function approve(script){return rpc('visual_quality_record_review',[JSON.stringify(script),JSON.stringify(review(script)),'reviewer']);}
async function claim(script){return rpc('claim_visual_publication',[day,1,(await row()).updated_at,JSON.stringify(script)]);}
const checks=[];async function check(name,fn){await fn();checks.push(name);}
await check('initial revision 1 freeze is CAS, immutable and idempotent',async()=>{
 await fixture(); const f=await freeze();assert.equal(f.registered,true,JSON.stringify(f));
 assert.deepEqual(await freeze(),f);assert.equal((await rpc('visual_quality_require_inputs',[JSON.stringify(f.script)])).authorized,true);
 const changed=structuredClone(source);changed.title='drift';assert.ok((await rpc('visual_quality_freeze_inputs',[JSON.stringify(changed),JSON.stringify(initial()),JSON.stringify(policy),'operator','Freeze reviewed inputs with immutable source'])).hold);
 await assert.rejects(()=>db.query(`update icg.episode_assets set visual_policy_json=null`),/VISUAL_POLICY/);
 const noMirror=structuredClone(f.script);delete noMirror._visual_policy;await assert.rejects(()=>db.query('update icg.episode_assets set script_json=$1',[JSON.stringify(noMirror)]),/VISUAL_POLICY/);
 await assert.rejects(()=>db.query(`update icg.visual_quality_inputs set actor='other'`),/append-only|permission denied/);
});
await check('unfrozen inputs and generation after an earlier call are rejected',async()=>{
 await fixture();await call(1);assert.ok((await freeze()).hold);
 await fixture();await freeze();await assert.rejects(()=>db.query(`insert into icg.image_generation_calls(scope,panel,fingerprint,state,revision) values($1,1,$2,'reserved',1)`,[scope,hash('9')]),/UNFROZEN/);
});
await check('UNKNOWN review and incomplete/failed checks cannot authorize publication',async()=>{
 await fixture();const script=await assembled();assert.ok((await rpc('visual_quality_publication_ready',[JSON.stringify(script)])).hold);
 for(const mutate of [r=>r.panels.pop(),r=>r.panels[0].checks.motion.status='FAIL',r=>r.panels[0].checks.mobile.status='UNKNOWN',
 r=>r.panels[0].slide_hash=hash('0'),r=>r.panels[0].checks.canon.evidence='short']){
 const v=review(script);mutate(v);assert.ok((await rpc('visual_quality_record_review',[JSON.stringify(script),JSON.stringify(v),'reviewer'])).hold);}
 const drift=structuredClone(script);drift._effective_render_manifest[0].scene={invented:true};
 await assert.rejects(()=>db.query('update icg.episode_assets set script_json=$1',[JSON.stringify(drift)]),/VISUAL_ASSEMBLY_CAPABILITY/);
});
await check('review, claim and snapshot bind exact bytes and reject stale versions',async()=>{
 await fixture();const script=await assembled();const r=await approve(script);assert.equal(r.reviewed,true,JSON.stringify(r));
 assert.equal((await rpc('visual_quality_publication_ready',[JSON.stringify(script)])).ready,true);
 assert.ok((await rpc('claim_visual_publication',[day,1,'2000-01-01T00:00:00Z',JSON.stringify(script)])).hold);
 const c=await claim(script);assert.ok(c.token,JSON.stringify(c));assert.ok((await claim(script)).hold);
 assert.equal((await rpc('visual_quality_require_snapshot',[day,c.token])).authorized,true);
 assert.ok((await rpc('visual_quality_require_snapshot',[day,'PUBLISH_HOLD:wrong'])).hold);
});
await check('active claim blocks selection, review changes, revocation and old-code claim bypass',async()=>{
 await fixture();const script=await assembled();const r=await approve(script);const c=await claim(script);assert.ok(c.token);
 assert.ok((await rpc('visual_quality_revoke',[r.id,'operator','Revoke previously reviewed exact images'])).hold);
 assert.ok((await approve(script)).hold);
 await assert.rejects(()=>db.query(`insert into icg.image_quality_selections(scope,manifest,actor,note) values($1,'[]','op','note')`,[scope]),/PUBLICATION_BUSY/);
 const drift={...script,title:'changed'};await assert.rejects(()=>db.query('update icg.episode_assets set script_json=$1',[JSON.stringify(drift)]),/PUBLICATION_BUSY/);
 await db.exec(`update icg.episode_assets set error_message=null`);
 await assert.rejects(()=>db.query(`update icg.episode_assets set error_message='PUBLISH_HOLD:old-code'`),/CAPABILITY/);
});
await check('revocation invalidates previous PASS without falling back to older reviews',async()=>{
 await fixture();const script=await assembled();const first=await approve(script);const second=await approve(script);assert.ok(first.id&&second.id);
 assert.equal((await rpc('visual_quality_revoke',[second.id,'operator','Revoke the latest exact visual review evidence'])).revoked,true);
 assert.ok((await claim(script)).hold);
});
await check('v2 partial recovery preserves successes and refuses new reservations for reused inputs',async()=>{
 await fixture();const s=(await freeze()).script;await call(1);const terminal=await call(2,'terminal');
 const next=structuredClone(s);next._generation_revision=2;next._reviewed_image_inputs.origin='RECOVERY';
 next._reviewed_image_inputs.panels[0].reuse_only=true;next._reviewed_image_inputs.panels[0].output_hash=hash('e');
 next.panels[1].action='pivots toward the dial';next._reviewed_image_inputs.panels[1].fingerprint=hash('9');
 const fingerprints={'1':hash('a'),'2':hash('9')};
 const bad=structuredClone(next);bad._reviewed_image_inputs.panels[0].fingerprint=hash('8');
 assert.ok((await rpc('image_generation_register_recovery_v3',[JSON.stringify(s),JSON.stringify(bad),terminal,2,.04,JSON.stringify(fingerprints),'operator','Reviewed failed panel only, preserving every successful image'])).hold);
 const r=await rpc('image_generation_register_recovery_v3',[JSON.stringify(s),JSON.stringify(next),terminal,2,.04,JSON.stringify(fingerprints),'operator','Reviewed failed panel only, preserving every successful image']);
 assert.equal(r.registered,true,JSON.stringify(r));
 assert.equal((await rpc('visual_quality_require_inputs',[JSON.stringify(next)])).authorized,true);
 await assert.rejects(()=>db.query(`insert into icg.image_generation_calls(scope,panel,fingerprint,state,revision) values($1,1,$2,'reserved',2)`,[scope,hash('a')]),/UNFROZEN/);
 assert.equal((await db.query('select count(*)::int n from icg.image_generation_calls')).rows[0].n,2);
 assert.equal(Number((await db.query('select sum(cost) c from icg.image_generation_calls')).rows[0].c),.08);
});
await check('mixed origin generation run is accepted only with matching token/fingerprint diagnostics',async()=>{
 await fixture();const token=await call(1);
 await db.query(`insert into icg.image_generation_attempt_diagnostics(token,kind,payload) values($1,'inputs',$2)`,[token,JSON.stringify({run_id:'111'})]);
 const s={date:day,panels:[source.panels[0]]};await db.query(`update icg.episode_assets set script_json=$1,status='image_generated'`,[JSON.stringify(s)]);
 const base={panel_idx:1,output_hash:hash('e'),artifact_run_id:'999',artifact_name:'episode-999',artifact_path:`${day}/panels/P1.png`};
 const b={version:'image-quality-candidate-1',purpose:'QUALITY_RETAKE',id:'11111111-1111-4111-8111-111111111111',date:day,revision:3,source_script:s,
 candidate_script:{...s,_generation_revision:3,_reviewed_image_inputs:{version:'reviewed-image-inputs-2',aspect_ratio:'4:5',panels:[{idx:1,fingerprint:hash('7')}]}},
 base_manifest:[base],base_artifact_run_id:'999',base_selection_version:0,max_calls:1,max_cost_usd:.1,panels:[{panel_idx:1,fingerprint:hash('7')}]};
 assert.ok((await rpc('image_quality_register',[JSON.stringify(b)])).hold);
 b.base_manifest[0]={...base,origin_token:token,origin_run_id:'111',origin_fingerprint:hash('a')};
 assert.equal((await rpc('image_quality_register',[JSON.stringify(b)])).registered,true);
});
await check('pending policy cannot become a legacy generation after a failed registration',async()=>{
 await fixture();const pending={...source,_visual_policy_intent:policy};
 await db.query('update icg.episode_assets set script_json=$1',[JSON.stringify(pending)]);
 await assert.rejects(()=>call(1),/REGISTRATION_REQUIRED/);
 await assert.rejects(()=>db.query('update icg.episode_assets set script_json=$1',[JSON.stringify(source)]),/PENDING_POLICY_IMMUTABLE/);
 assert.equal((await db.query('select count(*)::int n from icg.image_generation_calls')).rows[0].n,0);
});
await check('old assembly and dialogue edits without a new subject cannot reuse PASS',async()=>{
 await fixture();const script=await assembled();await approve(script);
 const old=structuredClone(script);old._assembly_manifest.version='assembly-manifest-1';
 await assert.rejects(()=>db.query('update icg.episode_assets set script_json=$1',[JSON.stringify(old)]),/ASSEMBLY_CAPABILITY/);
 const edit=structuredClone(script);edit.panels[0].narration='edited dialogue';
 await assert.rejects(()=>db.query('update icg.episode_assets set script_json=$1',[JSON.stringify(edit)]),/ASSEMBLY_CAPABILITY/);
 edit._assembly_manifest.visual_contract.public_script=Object.fromEntries(Object.entries(edit).filter(([k])=>!k.startsWith('_')));
 edit._assembly_manifest.slides[0]=hash('9');
 await db.query('update icg.episode_assets set script_json=$1',[JSON.stringify(edit)]);
 assert.ok((await rpc('visual_quality_publication_ready',[JSON.stringify(edit)])).hold);
});
await check('approved quality candidates keep their independent authorization and input registry',async()=>{
 await fixture();const script=await assembled();const id='11111111-1111-4111-8111-111111111111';
 const candidate=structuredClone(script);candidate._quality_candidate_id=id;candidate._generation_revision=3;
 candidate._reviewed_image_inputs.panels[0].fingerprint=hash('9');
 candidate._reviewed_image_inputs.panels[0].scene_sha256=hash('8');candidate._scene_performance_v2['1'].camera={shot_size:'MS'};
 const base=[1,2].map(idx=>({panel_idx:idx,output_hash:hash(idx===1?'e':'f'),artifact_run_id:'999',artifact_name:'episode-999',artifact_path:`${day}/panels/P${idx}.png`}));
 const b={version:'image-quality-candidate-1',purpose:'QUALITY_RETAKE',id,date:day,revision:3,source_script:script,
 candidate_script:candidate,base_manifest:base,base_artifact_run_id:'999',base_selection_version:0,max_calls:1,max_cost_usd:.1,
 panels:[{panel_idx:1,fingerprint:hash('9')}]};
 const r=await rpc('image_quality_register',[JSON.stringify(b)]);assert.equal(r.registered,true,JSON.stringify(r));
 assert.ok((await rpc('visual_quality_require_inputs',[JSON.stringify(candidate)])).hold);
 await rpc('image_quality_approve',[id,r.digest,'operator','Approve exact quality candidate inputs and budget']);
 assert.equal((await rpc('visual_quality_require_inputs',[JSON.stringify(candidate)])).authorized,true);
 const t=(await rpc('image_quality_reserve',[id,1,hash('9'),'456'])).token;assert.ok(t);
 assert.equal((await rpc('image_generation_finish_outcome_v3',[scope,1,hash('9'),t,'success',.04,hash('7'),null,null,3])).settled,true);
 const qreview={episode_continuity:'PASS',evidence:'Synthetic continuity and mobile candidate checks',panels:[
 {panel_idx:1,output_hash:hash('7'),safety:'PASS',canon:'PASS',quality:'PASS',assembly:'PASS',evidence:'Synthetic evidence for candidate output hash'}]};
 assert.equal((await rpc('image_quality_review',[id,r.digest,'reviewer',JSON.stringify(qreview)])).reviewed,true);
 const selection=await rpc('image_quality_select',[id,r.digest,0,'operator','Select the reviewed synthetic candidate image']);assert.equal(selection.selected,true,JSON.stringify(selection));
 const next=structuredClone(script);next._image_quality_selection={scope,version:selection.version,manifest:selection.manifest};
 const actual=next._effective_render_manifest[0];actual.origin_token=t;actual.origin_revision=3;actual.candidate_id=id;
 actual.fingerprint=hash('9');actual.output_hash=hash('7');actual.scene_sha256=hash('8');actual.scene=candidate._scene_performance_v2['1'];
 next._assembly_manifest.effective_render_manifest=next._effective_render_manifest;next._assembly_manifest.slides[0]=hash('6');
 await db.query('update icg.episode_assets set script_json=$1',[JSON.stringify(next)]);
 assert.ok((await rpc('visual_quality_publication_ready',[JSON.stringify(next)])).hold);
 assert.equal((await approve(next)).reviewed,true);
 assert.equal((await rpc('visual_quality_publication_ready',[JSON.stringify(next)])).ready,true);

});
await check('anon/authenticated cannot read evidence or execute visual functions',async()=>{
 await fixture();for(const role of ['anon','authenticated']){
 await db.exec(`reset role; grant usage on schema icg to ${role}; set role ${role}`);
 await assert.rejects(()=>rpc('visual_quality_capability'),/permission denied/);
 await assert.rejects(()=>db.query('select * from icg.visual_quality_inputs'),/permission denied/);
 await assert.rejects(()=>rpc('visual_quality_record_review',[JSON.stringify(initial()),'{}','operator']),/permission denied/);
 }
});
await db.close();console.log(JSON.stringify({status:'PASS',checks:checks.length,cases:checks,
 limitation:'Single backend; real multiconnection contention and actual image quality are separate tests.'},null,2));
