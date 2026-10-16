begin;
create table if not exists investment.stocks (
 ticker text primary key check(ticker ~ '^[A-Z0-9]{3,10}\.JK$'),
 owner_id uuid not null references auth.users(id), exchange text not null default 'IDX',
 currency text not null default 'IDR', active boolean not null default true,
 unique(owner_id,ticker)
);
create table if not exists investment.stock_prices_daily (
 ticker text not null, trade_date date not null, owner_id uuid not null,
 open numeric not null, high numeric not null, low numeric not null, close numeric not null,
 adjusted_close numeric, volume bigint not null, source text not null,
 fetched_at timestamptz not null, source_reference text, row_hash text not null,
 primary key(ticker,trade_date),
 foreign key(owner_id,ticker) references investment.stocks(owner_id,ticker),
 check(low>0 and high>=greatest(open,close,low) and low<=least(open,close,high)),
 check(open::text not in ('NaN','Infinity','-Infinity') and high::text not in ('NaN','Infinity','-Infinity') and low::text not in ('NaN','Infinity','-Infinity') and close::text not in ('NaN','Infinity','-Infinity')),
 check(adjusted_close is null or (adjusted_close>0 and adjusted_close::text not in ('NaN','Infinity','-Infinity'))),
 check(volume>=0)
);
create table if not exists investment.data_sync_logs (
 run_id uuid primary key, owner_id uuid not null references auth.users(id), ticker text not null,
 source text not null, trigger text not null, started_at timestamptz not null,
 finished_at timestamptz, status text not null,
 records_inserted integer not null default 0, records_updated integer not null default 0,
 records_unchanged integer not null default 0, error_details jsonb, quality jsonb,
 check(status in ('running','success','warning','failed','blocked','skipped'))
);
alter table investment.stocks enable row level security;
alter table investment.stock_prices_daily enable row level security;
alter table investment.data_sync_logs enable row level security;
do $$ declare t text; begin
 foreach t in array array['stocks','stock_prices_daily','data_sync_logs'] loop
  execute format('revoke all on investment.%I from public,anon,authenticated',t);
  execute format('grant select on investment.%I to authenticated',t);
  execute format('grant select,insert,update on investment.%I to service_role',t);
  if not exists(select 1 from pg_policies where schemaname='investment' and tablename=t and policyname='owner_read') then
   execute format('create policy owner_read on investment.%I for select to authenticated using(owner_id=(select auth.uid()))',t);
  end if;
 end loop;
end $$;
create index if not exists data_sync_logs_recent on investment.data_sync_logs(owner_id,ticker,started_at desc);
create or replace function investment.finish_idx_sync(target_owner uuid,run_identifier uuid,run_status text,details jsonb) returns void
language plpgsql security invoker set search_path=investment,pg_catalog as $$
begin
 if run_status not in ('failed','blocked','skipped') then raise exception 'Invalid failure/skip status'; end if;
 update investment.data_sync_logs set status=run_status,finished_at=clock_timestamp(),error_details=details
 where owner_id=target_owner and run_id=run_identifier
 and (status='running' or (run_status='failed' and details->>'phase'='database_readback'));
end $$;
create or replace function investment.commit_idx_eod(target_owner uuid,target_ticker text,run_identifier uuid,price_rows jsonb,validation jsonb) returns jsonb
language plpgsql security invoker set search_path=investment,pg_catalog as $$
declare r jsonb; old investment.stock_prices_daily; added int:=0; changed int:=0; unchanged int:=0; seen text[]:='{}'; runstate text;
begin
 if jsonb_typeof(price_rows)<>'array' or jsonb_array_length(price_rows) not between 1 and 5000 then raise exception 'Invalid bounded batch'; end if;
 perform pg_advisory_xact_lock(hashtextextended(target_ticker,0));
 perform 1 from investment.data_sync_logs where owner_id=target_owner and ticker=target_ticker and run_id=run_identifier and status='running' for update;
 if not found then raise exception 'Active owner-scoped sync log required'; end if;
 insert into investment.stocks(ticker,owner_id) values(target_ticker,target_owner) on conflict(ticker) do nothing;
 perform 1 from investment.stocks where ticker=target_ticker and owner_id=target_owner and active;
 if not found then raise exception 'Ticker ownership mismatch or inactive stock'; end if;
 for r in select value from jsonb_array_elements(price_rows) loop
  if r->>'trade_date'=any(seen) then raise exception 'Duplicate trade date in batch'; end if;
  seen:=array_append(seen,r->>'trade_date');
  if (r->>'trade_date')::date>(now() at time zone 'Asia/Jakarta')::date then raise exception 'Future trading date'; end if;
  select * into old from investment.stock_prices_daily where ticker=target_ticker and trade_date=(r->>'trade_date')::date for update;
  if found and old.fetched_at>(r->>'fetched_at')::timestamptz then unchanged:=unchanged+1;continue; end if;
  if found and old.row_hash=r->>'row_hash' then unchanged:=unchanged+1;continue; end if;
  if found then changed:=changed+1;else added:=added+1;end if;
  insert into investment.stock_prices_daily(owner_id,ticker,trade_date,open,high,low,close,adjusted_close,volume,source,fetched_at,source_reference,row_hash)
  values(target_owner,target_ticker,(r->>'trade_date')::date,(r->>'open')::numeric,(r->>'high')::numeric,(r->>'low')::numeric,(r->>'close')::numeric,(r->>'adjusted_close')::numeric,(r->>'volume')::bigint,r->>'source',(r->>'fetched_at')::timestamptz,r->>'source_reference',r->>'row_hash')
  on conflict(ticker,trade_date) do update set open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,
   adjusted_close=excluded.adjusted_close,volume=excluded.volume,source=excluded.source,fetched_at=excluded.fetched_at,source_reference=excluded.source_reference,row_hash=excluded.row_hash;
 end loop;
 runstate:=case when jsonb_array_length(coalesce(validation->'missing_sessions','[]'))>0 then 'warning' else 'success' end;
 update investment.data_sync_logs set status=runstate,finished_at=clock_timestamp(),records_inserted=added,records_updated=changed,records_unchanged=unchanged,quality=validation
 where owner_id=target_owner and run_id=run_identifier;
 return jsonb_build_object('status',runstate,'records_inserted',added,'records_updated',changed,'records_unchanged',unchanged);
end $$;
revoke all on function investment.commit_idx_eod(uuid,text,uuid,jsonb,jsonb),investment.finish_idx_sync(uuid,uuid,text,jsonb) from public,anon,authenticated;
grant execute on function investment.commit_idx_eod(uuid,text,uuid,jsonb,jsonb),investment.finish_idx_sync(uuid,uuid,text,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
