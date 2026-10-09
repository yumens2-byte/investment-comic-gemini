// Embedded PostgreSQL contract checks. No production credentials or connections.
// PGLITE_MODULE must point to @electric-sql/pglite/dist/index.js when not locally installed.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
const { PGlite } = await import(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const db = new PGlite();
let checks = 0;
function check(label, value) { assert.ok(value,label); checks++; console.log(`PASS ${label}`); }
async function rejects(label, sql, params=[]) {
  try { await db.query(sql,params); } catch { check(label,true); return; }
  throw new Error(`Expected rejection: ${label}`);
}
const query = async (sql,params=[]) => (await db.query(sql,params)).rows;
const rpc = async (fn,values) => (await query(`select icg_side.${fn}(${values.map((_,i)=>'$'+(i+1)).join(',')}) as result`,values))[0].result;
await db.exec('create role anon; create role authenticated; create role service_role bypassrls; create schema icg_side; grant usage on schema icg_side to service_role;');
await db.exec(`create schema icg; grant usage on schema icg to service_role;
create table icg.daily_snapshots(snapshot_date date, us10y float, vix float, oil_wti float, spy_change float,
nasdaq_change float, dollar_index float, hy_spread float, fear_greed float, created_at timestamptz, data_quality jsonb);
grant select on icg.daily_snapshots to service_role;
insert into icg.daily_snapshots(snapshot_date,vix,created_at,data_quality) values(current_date,15,now(),'{}');`);
const file = fs.readdirSync(path.join(root,'supabase/migrations')).find(p=>p.endsWith('_market_talk.sql'));
await db.exec(fs.readFileSync(path.join(root,'supabase/migrations',file),'utf8'));
const automatic = fs.readdirSync(path.join(root,'supabase/migrations')).find(p=>p.endsWith('_market_talk_automatic.sql'));
await db.exec(fs.readFileSync(path.join(root,'supabase/migrations',automatic),'utf8'));
const hardening = fs.readdirSync(path.join(root,'supabase/migrations')).find(p=>p.endsWith('_market_talk_hardening.sql'));
await db.exec(fs.readFileSync(path.join(root,'supabase/migrations',hardening),'utf8'));
await db.exec('set role service_role');
check('hardening contract version', (await rpc('talk_contract_version',[]))===3);
check('quality view carries raw source metadata', (await query('select data_quality,created_at from icg_side.market_talk_source_v1'))[0].created_at != null);
await rejects('source view remains read only','update icg_side.market_talk_source_v1 set vix=99');
async function page(id,enabled=true) {
  await query('insert into icg_side.facebook_page_policy(page_id,enabled,exclusive_managed,daily_budget_usd,monthly_budget_usd) values($1,$2,true,1,2)',[id,enabled]);
  await rpc('facebook_observe',[id,[]]);
}
const expiry = new Date(Date.now()+3600000).toISOString();
const hash = 'a'.repeat(64);
await page('p1');
const [first,second] = await Promise.all([
  rpc('facebook_begin',['p1','one','sidestory',hash,expiry]),
  rpc('facebook_begin',['p1','one','sidestory',hash,expiry])]);
check('duplicate request admits only one sender',first.status==='SENDING' && second.status==='UNKNOWN');
check('another track blocked by unresolved send',(await rpc('facebook_begin',['p1','two','talk',hash,expiry])).status==='UNKNOWN');
await rejects('wrong claim token cannot finish','select icg_side.facebook_finish($1,$2,$3,$4,$5,$6)', ['p1','one','00000000-0000-0000-0000-000000000000','PUBLISHED','p1_1','']);
await rejects('null token cannot finish','select icg_side.facebook_finish($1,$2,$3,$4,$5,$6)', ['p1','one',null,'PUBLISHED','p1_1','']);
await rpc('facebook_finish',['p1','one',first.token,'PUBLISHED','p1_1','']);
check('published replay returns prior ID',(await rpc('facebook_begin',['p1','one','sidestory',hash,expiry])).post_id==='p1_1');
check('minimum gap enforced',(await rpc('facebook_begin',['p1','two','sidestory',hash,expiry])).status==='PAGE_LIMIT');
await rejects('payload changes cannot reuse key','select icg_side.facebook_begin($1,$2,$3,$4,$5)',['p1','one','sidestory','b'.repeat(64),expiry]);
await page('p2');
const unknown = await rpc('facebook_begin',['p2','one','sidestory',hash,expiry]);
await rpc('facebook_finish',['p2','one',unknown.token,'UNKNOWN',null,'timeout']);
await rejects('resume blocked with uncertain result','select icg_side.facebook_set_hold($1,$2,$3,$4)',['p2','reviewer','I reviewed the unresolved result',true]);
check('UNKNOWN permanently blocks retries',(await rpc('facebook_begin',['p2','one','sidestory',hash,expiry])).status==='UNKNOWN');
await rpc('facebook_observe',['p2',[{id:'p2_1',created_time:new Date().toISOString()}]]);
await rpc('facebook_resolve',['p2','one','p2_1',new Date().toISOString(),'reviewer','Verified exact post ID and actual Page text']);
check('reconciliation coalesces external receipt',(await query('select count(*)::int as n from icg_side.facebook_deliveries where page_id=$1',['p2']))[0].n===1);
check('reconciliation does not auto-reactivate',(await query('select enabled from icg_side.facebook_page_policy where page_id=$1',['p2']))[0].enabled===false);
await page('p3');
await rpc('facebook_observe',['p3',[{id:'p3_1',created_time:new Date(Date.now()-5*3600000).toISOString()},{id:'p3_2',created_time:new Date(Date.now()-10*3600000).toISOString()}]]);
check('manual/external posts count toward Page cap',(await rpc('facebook_begin',['p3','one','sidestory',hash,expiry])).status==='PAGE_LIMIT');
await page('p4');
await rpc('talk_cost_reserve',['p4','cost1',.6]);
await rejects('conservative daily cost ceiling','select icg_side.talk_cost_reserve($1,$2,$3)',['p4','cost2',.5]);
await rejects('generation idempotency','select icg_side.talk_cost_reserve($1,$2,$3)',['p4','cost1',.1]);
await rejects('nonfinite cost','select icg_side.talk_cost_reserve($1,$2,$3)',['p4','bad','NaN']);
await page('p5');
await query(`insert into icg_side.talk_items(revision,page_id,semantic_key,body_hash,send_hash,body,creative,payload,due_at,expires_at)
 values($1,'p5','claim','body',$1,'reviewed body','creative','{}',now()-interval '1 minute',now()+interval '1 hour')`,[hash]);
check('unapproved cannot send',(await rpc('facebook_begin',['p5',hash,'talk',hash,expiry])).status==='APPROVAL_OR_TIME_REQUIRED');
await rpc('talk_approve',[hash,'reviewer','Source date, exact facts and canon checked']);
await rejects('approved body is immutable','update icg_side.talk_items set body=$1 where revision=$2',['changed',hash]);
const talk = await rpc('facebook_begin',['p5',hash,'talk',hash,expiry]);
check('approved due content can send',talk.status==='SENDING');
await rpc('facebook_finish',['p5',hash,talk.token,'PUBLISHED','p5_1','']);
check('receipt and talk state commit together',(await query('select status from icg_side.talk_items where revision=$1',[hash]))[0].status==='PUBLISHED');
await page('p6',false);
check('disabled by policy',(await rpc('facebook_begin',['p6','one','sidestory',hash,expiry])).status==='CHANNEL_HOLD');
await page('p7');
await rejects('null observation cannot attest freshness','select icg_side.facebook_observe($1,$2)',['p7',null]);
await query("update icg_side.facebook_page_policy set observed_at=now()-interval '3 minutes' where page_id='p7'");
check('stale Page observation blocks send',(await rpc('facebook_begin',['p7','one','sidestory',hash,expiry])).status==='OBSERVATION_REQUIRED');
await rpc('facebook_observe',['p7',[]]);
check('null expiry refused',(await rpc('facebook_begin',['p7','one','sidestory',hash,null])).status==='EXPIRED');
await page('p8');
const rev8='8'.repeat(64);
await query(`insert into icg_side.talk_items(revision,page_id,semantic_key,body_hash,send_hash,body,creative,payload,due_at,expires_at)
 values($1,'p8','claim','body',$1,'body','creative','{}',now(),now()+interval '1 hour')`,[rev8]);
await rpc('talk_approve',[rev8,'reviewer','Evidence and character setting checked']);
await rpc('talk_hold',[rev8,'reviewer','Wrong source corrected; review again']);
check('hold removes prior approval',(await query('select approved_at,status from icg_side.talk_items where revision=$1',[rev8]))[0].approved_at===null);
await query(`insert into icg_side.talk_items(revision,page_id,semantic_key,body_hash,send_hash,body,creative,payload,due_at,expires_at)
 values($1,'p8','claim','body2',$1,'fixed body','creative','{}',now(),now()+interval '1 hour')`,['9'.repeat(64)]);
check('corrected claim can have a new reviewed revision',true);

await page('p9');
await page('coexist');
await query("update icg_side.facebook_page_policy set exclusive_managed=false where page_id='coexist'");
check('coexistence requires explicit opt-in',(await rpc('facebook_begin',['coexist','one','sidestory',hash,expiry])).status==='CHANNEL_HOLD');
await query("update icg_side.facebook_page_policy set coexistence_allowed=true where page_id='coexist'");
check('coexistence allows controlled sender without false exclusive claim',(await rpc('facebook_begin',['coexist','one','sidestory',hash,expiry])).status==='SENDING');
check('coexistence still blocks concurrent sender',(await rpc('facebook_begin',['coexist','two','sidestory',hash,expiry])).status==='UNKNOWN');
// Cost ceilings retain uncertain charges; no automatic refunds.
await query("update icg_side.facebook_page_policy set daily_budget_usd=5,monthly_budget_usd=1 where page_id='p9'");
await rpc('talk_cost_reserve',['p9','c1',.8]);
await rejects('monthly cost ceiling','select icg_side.talk_cost_reserve($1,$2,$3)',['p9','c2',.3]);
await rpc('talk_model_state',['p9','c1','generation','RESERVED']);
await rpc('talk_model_state',['p9','c1','generation','UNKNOWN']);
await rejects('uncertain model cannot be completed or refunded', "select icg_side.talk_model_state('p9','c1','generation','COMPLETE')");
await rejects('model attempt requires durable cost', "select icg_side.talk_model_state('p9','missing','generation','RESERVED')");
const today = new Date().toISOString().slice(0,10);
await rejects('cannot claim success without a posted delivery', 'select icg_side.talk_record_outcome($1,$2,$3,$4,$5,$6,$7)', ['p9',today,'run1','publish','PUBLISHED','PUBLISHED_VERIFIED',hash]);
await rpc('talk_record_outcome',['p5',today,'run2','publish','PUBLISHED','PUBLISHED_VERIFIED',hash]);
await rpc('talk_record_outcome',['p5',today,'run3','automate','BLOCKED','SOURCE_SESSION_REQUIRED',null]);
check('published slot cannot downgrade',(await query("select status from icg_side.talk_slots where page_id='p5'"))[0].status==='PUBLISHED');
await rejects('run events cannot be edited', "update icg_side.talk_run_events set status='BLOCKED'");
await rejects('run events cannot be deleted', 'delete from icg_side.talk_run_events');
check('all attempts retained in run events',(await query("select count(*)::int n from icg_side.talk_run_events where page_id='p5'"))[0].n===2);
await rejects('outcome rejects exception text', 'select icg_side.talk_record_outcome($1,$2,$3,$4,$5,$6,$7)', ['p5',today,'run4','publish','BLOCKED','secret token https://private',null]);
check('main source values unchanged',(await query('select vix from icg.daily_snapshots'))[0].vix===15);
await db.exec('reset role; set role anon;');
await rejects('anon cannot read run events','select * from icg_side.talk_run_events');
await rejects('anon cannot read provenance','select * from icg_side.market_talk_source_v1');
await rejects('anon cannot read drafts','select * from icg_side.talk_items');
await rejects('anon cannot call send RPC','select icg_side.facebook_begin($1,$2,$3,$4,$5)',['p6','bad','sidestory',hash,expiry]);
await db.exec('reset role;');
check('all new tables have RLS',(await query("select count(*)::int n from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='icg_side' and c.relkind='r' and not c.relrowsecurity"))[0].n===0);
check('new functions use SECURITY INVOKER',(await query("select count(*)::int n from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='icg_side' and p.prosecdef"))[0].n===0);
console.log(`SQL CONTRACT: ${checks} passed (embedded PostgreSQL; not a multi-connection deployment test)`);
await db.close();
