begin;
-- Reuse macro snapshots, price/model tables, news and the existing notification inbox.
create table if not exists investment.sector_intelligence_evaluations(
 owner_id uuid not null references auth.users(id),evaluation_id text not null,
 generated_at timestamptz not null,payload jsonb not null,primary key(owner_id,evaluation_id)
);
create table if not exists investment.sectoral_thesis_revisions(
 owner_id uuid not null references auth.users(id),session_id text not null,revision bigint not null,
 published_at timestamptz not null,reason text not null,payload jsonb not null,
 primary key(owner_id,session_id,revision)
);
create table if not exists investment.sector_evidence_assertions(
 owner_id uuid not null references auth.users(id),id uuid not null default gen_random_uuid(),
 created_at timestamptz not null default now(),payload jsonb not null,primary key(owner_id,id)
);
alter table investment.sector_intelligence_evaluations enable row level security;
alter table investment.sectoral_thesis_revisions enable row level security;
alter table investment.sector_evidence_assertions enable row level security;
do $$ declare t text; begin
 foreach t in array array['sector_intelligence_evaluations','sectoral_thesis_revisions','sector_evidence_assertions'] loop
  execute format('revoke all on investment.%I from public,anon,authenticated,service_role',t);
  if not exists(select 1 from pg_policies where schemaname='investment' and tablename=t and policyname='owner_read') then
   execute format('create policy owner_read on investment.%I for select to authenticated using(owner_id=(select auth.uid()))',t);
  end if;
  execute format('grant select on investment.%I to authenticated,service_role',t);
 end loop;
end $$;
-- Evidence assertions are append-only reviewed input, never written by frontend or an LLM.
grant insert on investment.sector_evidence_assertions to service_role;
create index if not exists intelligence_latest on investment.sector_intelligence_evaluations(owner_id,generated_at desc);
create index if not exists thesis_latest on investment.sectoral_thesis_revisions(owner_id,published_at desc);
create or replace function investment.publish_sector_intelligence(target_owner uuid,evaluation jsonb,proposals jsonb)
returns jsonb language plpgsql security definer set search_path=pg_catalog as $$
declare s jsonb; previous investment.sectoral_thesis_revisions%rowtype;rev bigint;
 changes integer:=0;notices integer:=0;stamp timestamptz;last_check timestamptz;urgent boolean;
begin
 if evaluation->>'evaluation_id' !~ '^[0-9a-f]{64}$' or jsonb_typeof(proposals)<>'array' or jsonb_array_length(proposals)>20
  or jsonb_array_length(evaluation->'top_industries')>3 then raise exception 'Invalid evaluation'; end if;
 stamp=(evaluation->>'generated_at')::timestamptz;
 if stamp>clock_timestamp()+interval '5 minutes' then raise exception 'Future evaluation rejected'; end if;
 perform pg_advisory_xact_lock(hashtextextended(target_owner::text||':sector-intelligence',0));
 select max(generated_at) into last_check from investment.sector_intelligence_evaluations where owner_id=target_owner;
 if last_check>stamp then raise exception 'Stale evaluation; retry with current data'; end if;
 insert into investment.sector_intelligence_evaluations values(target_owner,evaluation->>'evaluation_id',stamp,evaluation)
  on conflict(owner_id,evaluation_id) do nothing;
 for s in select value from jsonb_array_elements(proposals) loop
  if s->>'id' !~ '^v2_[a-z_]{1,50}$' or s->>'content_key' !~ '^[0-9a-f]{64}$' or s->>'publication_reason' is null then raise exception 'Invalid thesis'; end if;
  select * into previous from investment.sectoral_thesis_revisions where owner_id=target_owner and session_id=s->>'id' order by revision desc limit 1;
  if previous.payload->>'content_key'=s->>'content_key' then continue; end if;
  if previous.revision is null and (s->>'status'<>'High Conviction' or not exists(select 1 from jsonb_array_elements(s->'industries') i where (i->>'eligible')::boolean)) then raise exception 'Unsupported initial publication'; end if;
  if previous.revision is not null and previous.payload->>'version' is distinct from s->>'version' then continue; end if;
  urgent=s->>'publication_reason' in ('verified_invalidation','contrary_evidence_or_gate_lost','evidence_expired')
   or exists(select 1 from jsonb_array_elements(s->'assertions') a where a->>'urgent_policy'='true');
  if previous.revision is not null and not urgent and stamp-previous.published_at<make_interval(hours=>(evaluation->'config'->>'cooldown_hours')::int) then continue; end if;
  rev=coalesce(previous.revision,0)+1;
  insert into investment.sectoral_thesis_revisions values(target_owner,s->>'id',rev,stamp,s->>'publication_reason',s);
  insert into investment.sector_notifications(owner_id,theme_id,revision,title,created_at,payload)
   values(target_owner,s->>'id',rev,
    case when s->>'status'='Invalidated' then 'Sectoral Thesis Invalidated: '
     when previous.revision is null then 'New Sectoral Analysis: '
     when s->>'status'='High Conviction' then 'Sectoral Conviction Upgraded: '
     else 'Sectoral Thesis Review: ' end || (s->>'title'),stamp,
    jsonb_build_object('session_id',s->>'id','revision',rev,'event',s->>'title','reason',s->>'publication_reason',
     'score',s->'score','previous_score',previous.payload->'score','industries',s->'industries','research_only',true))
   on conflict(owner_id,theme_id,revision) do nothing;
  changes=changes+1;notices=notices+1;
 end loop;
 return jsonb_build_object('published',changes,'notifications_created',notices);
end $$;
revoke all on function investment.publish_sector_intelligence(uuid,jsonb,jsonb) from public,anon,authenticated;
grant execute on function investment.publish_sector_intelligence(uuid,jsonb,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
