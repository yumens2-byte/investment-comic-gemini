// Disposable embedded PostgreSQL only. Replace clocks in test migration copies.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const {PGlite}=await import(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const db=new PGlite();
const dir=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../supabase/migrations');
const q=async(sql,args=[]) => (await db.query(sql,args)).rows;
const rpc=async(name,args=[]) => (await q('select icg_side.'+name+'('+args.map((_,i)=>'$'+(i+1)).join(',')+') r',args))[0].r;
let checks=0;
const ok=(name,v)=>{assert.ok(v,name);checks++;console.log('PASS '+name)};
async function fail(name,sql,args=[]){try{await q(sql,args)}catch{ok(name,true);return}throw Error(name)}
await db.exec("create role anon; create role authenticated; create role service_role bypassrls; create schema icg_side; grant usage on schema icg_side to service_role; create schema icg; grant usage on schema icg to service_role;");
await db.exec("create table icg.daily_snapshots(snapshot_date date,us10y float,vix float,oil_wti float,spy_change float,nasdaq_change float,dollar_index float,hy_spread float,fear_greed float,created_at timestamptz,data_quality jsonb); grant select on icg.daily_snapshots to service_role;");
await db.exec("create table icg_side.test_clock(t timestamptz); insert into icg_side.test_clock values('2026-10-16T11:00:00Z'); grant select,update on icg_side.test_clock to service_role; create function icg_side.test_now() returns timestamptz language sql as $$select t from icg_side.test_clock$$;");
for(const suffix of ['_market_talk.sql','_market_talk_automatic.sql','_market_talk_hardening.sql','_market_talk_db_only_v4.sql','_market_talk_actions_watchdog_v5.sql']){
 const file=fs.readdirSync(dir).find(x=>x.endsWith(suffix));
 await db.exec(fs.readFileSync(path.join(dir,file),'utf8').replace(/\b(clock_timestamp|now)\(\)/g,'icg_side.test_now()'));
}
await db.exec('set role service_role');
const day='2026-10-16',due='2026-10-16T05:00:00Z',end='2026-10-16T14:30:00Z',hash='a'.repeat(64);
const owner='00000000-0000-0000-0000-000000000001',other='00000000-0000-0000-0000-000000000002';
async function page(id,version=5){
 await q('insert into icg_side.facebook_page_policy(page_id,daily_budget_usd,monthly_budget_usd) values($1,1,2)',[id]);
 await q('insert into icg_side.talk_policy(page_id,enabled,policy_version,effective_from) values($1,true,$2,$3)',[id,version,day]);
}
async function schedule(id){return rpc('talk_schedule_ensure_v5',[id,day,due])}
async function claim(id,who=owner,mode='recovery'){return rpc('talk_execution_claim_v5',[id,day,mode,who,'run:1'])}
async function item(id,key=hash){
 await q("insert into icg_side.talk_items(revision,page_id,semantic_key,body_hash,send_hash,body,creative,payload,status,approved_at,due_at,expires_at) values($1,$2,$1,$1,$3,'body','creative','{}','APPROVED',icg_side.test_now(),$4,$5)",[key,id,hash,due,end]);
}
ok('contract versions coexist',(await rpc('talk_contract_version_v4'))===4 && (await rpc('talk_contract_version_v5'))===5);
await page('legacy',4);
await fail('migration does not activate existing v4 policy','select icg_side.talk_schedule_ensure_v5($1,$2,$3)',['legacy',day,due]);
await page('p');
const saved=await schedule('p');
ok('extended recovery deadline',new Date(saved.window_end).getTime()===new Date(end).getTime());
ok('normal still stops at 1800',(await rpc('talk_preflight_v5',['p',day,'normal',null])).status==='PENDING_RECOVERY');
ok('recovery after 1800',(await rpc('talk_preflight_v5',['p',day,'recovery',null])).status==='READY');
ok('first claim',(await claim('p')).status==='CLAIMED');
ok('overlap rejected',(await claim('p',other)).status==='IN_PROGRESS');
await fail('stale owner cannot reserve paid work','select icg_side.talk_cost_reserve_v5($1,$2,$3,$4,$5)',['p','cost',0.01,other,'recovery']);
ok('owner cost reservation',await rpc('talk_cost_reserve_v5',['p','cost',0.01,owner,'recovery']));
await fail('same paid key never replays','select icg_side.talk_cost_reserve_v5($1,$2,$3,$4,$5)',['p','cost',0.01,owner,'recovery']);
await item('p');
ok('stale sender blocked',(await rpc('talk_begin_v5',['p',hash,'talk',hash,end,other,'recovery'])).status==='CLAIM_LOST');
const sent=await rpc('talk_begin_v5',['p',hash,'talk',hash,end,owner,'recovery']);
ok('owner sends once',sent.status==='SENDING');
ok('ambiguous send never replayed',(await rpc('talk_begin_v5',['p',hash,'talk',hash,end,owner,'recovery'])).status==='UNKNOWN');
await rpc('talk_finish_v4',['p',hash,sent.token,'PUBLISHED','p_1','']);
ok('exact publication stored',(await rpc('talk_snapshot_v5',['p',day])).deliveries[0].post_id==='p_1');
await rpc('talk_execution_finish_v5',['p',day,owner,'POSTED_UNVERIFIED','RECEIPT_READ_FAILED',true]);
ok('verification cooldown',(await claim('p',other,'verify')).status==='RETRY_WAIT');
await q("update icg_side.test_clock set t='2026-10-16T11:01:01Z'");
ok('verification can resume',(await claim('p',other,'verify')).status==='CLAIMED');
await rpc('talk_record_outcome_v4',['p',day,'run2','verify','PUBLISHED','PUBLISHED_VERIFIED',hash]);
await rpc('talk_execution_finish_v5',['p',day,other,'PUBLISHED','PUBLISHED',false]);
ok('verified stops all execution',(await claim('p',owner,'verify')).status==='WATCH_OK');
await page('retry');await schedule('retry');
for(let n=1;n<=3;n++){
 ok('bounded attempt '+n,(await claim('retry')).execution_count===n);
 await rpc('talk_execution_finish_v5',['retry',day,owner,'BLOCKED','DB_API_FAILURE',true]);
 await q("update icg_side.test_clock set t=t+interval '31 minutes'");
}
ok('fourth attempt blocked',(await claim('retry')).status==='RETRY_EXHAUSTED');
await page('lost');await schedule('lost');await claim('lost');
await q("update icg_side.test_clock set t=t+interval '16 minutes'");
await fail('expired lease cannot reserve cost','select icg_side.talk_cost_reserve_v5($1,$2,$3,$4,$5)',['lost','lost-cost',0.01,owner,'recovery']);
ok('expired lease can be re-arbitrated',(await claim('lost',other)).status==='CLAIMED');
await fail('old owner cannot finish new owner','select icg_side.talk_execution_finish_v5($1,$2,$3,$4,$5,$6)',['lost',day,owner,'BLOCKED','DB_API_FAILURE',true]);
await page('boundary');await schedule('boundary');
await q("update icg_side.test_clock set t='2026-10-16T14:30:00Z'");
ok('2330 hard cutoff',(await claim('boundary')).status==='MISSED_FINAL');
await q("update icg_side.test_clock set t='2026-10-16T15:00:00Z'");
ok('midnight never reposts previous day',(await claim('boundary')).status==='OUTSIDE_RECOVERY_DAY');
await db.exec('reset role');
ok('anon cannot claim',(await q("select has_function_privilege('anon','icg_side.talk_execution_claim_v5(text,date,text,uuid,text)','EXECUTE') b"))[0].b===false);
ok('RLS enabled',(await q("select relrowsecurity from pg_class where oid='icg_side.talk_recovery'::regclass"))[0].relrowsecurity);
await db.exec("create schema cron;create table cron.job(jobid integer,jobname text);insert into cron.job values(1,'icg_talk_dispatch'),(2,'icg_talk_dispatch_cutoff'),(3,'icg_talk_dispatch_reconcile'),(4,'unrelated');create function cron.unschedule(p integer) returns boolean language plpgsql as $$begin delete from cron.job where jobid=p;return true;end$$;create schema private;create table private.icg_talk_dispatch_log(id integer);insert into private.icg_talk_dispatch_log values(1);");
const retirement=fs.readdirSync(dir).find(x=>x.endsWith('_remove_market_talk_db_scheduler.sql'));
await db.exec(fs.readFileSync(path.join(dir,retirement),'utf8'));
ok('only scoped cron removed',(await q('select * from cron.job')).length===1 && (await q('select * from cron.job'))[0].jobname==='unrelated');
ok('dispatcher audit retained',(await q('select * from private.icg_talk_dispatch_log')).length===1);
console.log(checks+' v5 PostgreSQL checks passed');
await db.close();
