begin;
create table if not exists investment.sector_model_runs(
 owner_id uuid not null references auth.users(id),model_id text not null,
 generated_at timestamptz not null,report jsonb not null,primary key(owner_id,model_id)
);
create table if not exists investment.sector_macro_context(
 owner_id uuid not null references auth.users(id),snapshot_id text not null,
 generated_at timestamptz not null,payload jsonb not null,primary key(owner_id,snapshot_id)
);
create table if not exists investment.sector_monitor_runs(
 owner_id uuid not null references auth.users(id),run_id uuid not null,
 generated_at timestamptz not null,status text not null,payload jsonb not null,primary key(owner_id,run_id)
);
create table if not exists investment.sector_opportunity_state(
 owner_id uuid not null references auth.users(id),theme_id text not null,
 material_key text not null,revision bigint not null default 1,
 updated_at timestamptz not null,payload jsonb not null,primary key(owner_id,theme_id)
);
create table if not exists investment.sector_notifications(
 owner_id uuid not null references auth.users(id),id uuid not null default gen_random_uuid(),
 theme_id text not null,revision bigint not null,title text not null,
 created_at timestamptz not null,read_at timestamptz,payload jsonb not null,
 primary key(owner_id,id),unique(owner_id,theme_id,revision)
);
alter table investment.sector_model_runs enable row level security;
alter table investment.sector_macro_context enable row level security;
alter table investment.sector_monitor_runs enable row level security;
alter table investment.sector_opportunity_state enable row level security;
alter table investment.sector_notifications enable row level security;
do $$ declare t text; begin
 foreach t in array array['sector_model_runs','sector_macro_context','sector_monitor_runs','sector_opportunity_state','sector_notifications'] loop
  execute format('revoke all on investment.%I from public,anon,authenticated,service_role',t);
  if not exists(select 1 from pg_policies where schemaname='investment' and tablename=t and policyname='owner_read') then
   execute format('create policy owner_read on investment.%I for select to authenticated using(owner_id=(select auth.uid()))',t);
  end if;
  execute format('grant select on investment.%I to authenticated,service_role',t);
 end loop;
end $$;
grant insert on investment.sector_model_runs,investment.sector_macro_context,investment.sector_monitor_runs to service_role;
revoke update,delete on investment.daily_market_analysis from service_role;
create index if not exists sector_model_recent on investment.sector_model_runs(owner_id,generated_at desc);
create index if not exists sector_macro_recent on investment.sector_macro_context(owner_id,generated_at desc);
create index if not exists sector_monitor_recent on investment.sector_monitor_runs(owner_id,generated_at desc);
create index if not exists sector_notification_recent on investment.sector_notifications(owner_id,created_at desc);

create or replace function investment.publish_sector_updates(target_owner uuid,candidates jsonb,checked_at timestamptz)
returns jsonb language plpgsql security definer set search_path=pg_catalog as $$
declare candidate jsonb;previous investment.sector_opportunity_state%rowtype;next_revision bigint;changes integer:=0;notices integer:=0;should_notify boolean;
begin
 if jsonb_typeof(candidates)<>'array' or jsonb_array_length(candidates)>20 then raise exception 'Invalid candidates'; end if;
 perform pg_advisory_xact_lock(hashtextextended(target_owner::text||':sector-opportunities',0));
 for candidate in select value from jsonb_array_elements(candidates) loop
  if candidate->>'id' !~ '^[a-z0-9_]{1,60}$' or candidate->>'material_key' !~ '^[0-9a-f]{64}$' then raise exception 'Invalid candidate identity'; end if;
  select * into previous from investment.sector_opportunity_state where owner_id=target_owner and theme_id=candidate->>'id';
  if previous.updated_at>checked_at then continue; end if;
  if previous.material_key is not distinct from candidate->>'material_key' then continue; end if;
  next_revision=coalesce(previous.revision,0)+1;
  should_notify=(candidate->>'status'='supported') or (previous.revision is not null and previous.payload->>'status' is distinct from candidate->>'status');
  insert into investment.sector_opportunity_state(owner_id,theme_id,material_key,revision,updated_at,payload)
   values(target_owner,candidate->>'id',candidate->>'material_key',next_revision,checked_at,candidate)
   on conflict(owner_id,theme_id) do update set material_key=excluded.material_key,revision=excluded.revision,updated_at=excluded.updated_at,payload=excluded.payload;
  changes=changes+1;
  if should_notify then
   insert into investment.sector_notifications(owner_id,theme_id,revision,title,created_at,payload)
    values(target_owner,candidate->>'id',next_revision,
     case when previous.revision is null then 'Tesis riset baru: ' else 'Pembaruan tesis: ' end || (candidate->>'title'),checked_at,
     jsonb_build_object('theme_id',candidate->>'id','status',candidate->>'status','research_only',true))
    on conflict(owner_id,theme_id,revision) do nothing;
   notices=notices+1;
  end if;
 end loop;
 return jsonb_build_object('changed',changes,'notifications_created',notices);
end $$;
revoke all on function investment.publish_sector_updates(uuid,jsonb,timestamptz) from public,anon,authenticated;
grant execute on function investment.publish_sector_updates(uuid,jsonb,timestamptz) to service_role;
create or replace function investment.read_sector_notification(target_owner uuid,notification_id uuid)
returns jsonb language plpgsql security definer set search_path=pg_catalog as $$
begin
 update investment.sector_notifications set read_at=coalesce(read_at,clock_timestamp()) where owner_id=target_owner and id=notification_id;
 return jsonb_build_object('updated',found);
end $$;
revoke all on function investment.read_sector_notification(uuid,uuid) from public,anon,authenticated;
grant execute on function investment.read_sector_notification(uuid,uuid) to service_role;
-- Morning/closing and opportunity jobs can collect the same new RSS item.
-- Preserve earliest knowledge time and the latest snapshot atomically.
create or replace function investment.preserve_news_times()
returns trigger language plpgsql set search_path=pg_catalog as $$
declare earliest timestamptz;
begin
 earliest=least(old.first_seen_at,new.first_seen_at);
 if new.retrieved_at<old.retrieved_at then new=old; end if;
 new.first_seen_at=earliest;
 return new;
end $$;
revoke all on function investment.preserve_news_times() from public,anon,authenticated;
drop trigger if exists preserve_news_times on investment.news_items;
create trigger preserve_news_times before update on investment.news_items for each row execute function investment.preserve_news_times();
notify pgrst,'reload schema';
commit;
