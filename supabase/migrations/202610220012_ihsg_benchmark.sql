begin;
create table if not exists investment.market_benchmark_prices_daily(
 owner_id uuid not null references auth.users(id),symbol text not null check(symbol='^JKSE'),
 trade_date date not null,open double precision not null,high double precision not null,
 low double precision not null,close double precision not null,volume bigint not null check(volume>=0),
 source text not null default 'Yahoo Finance',fetched_at timestamptz not null,
 primary key(owner_id,symbol,trade_date),
 check(open>0 and low>0 and close>0 and high>=greatest(open,close,low) and low<=least(open,close,high))
);
alter table investment.market_benchmark_prices_daily enable row level security;
revoke all on investment.market_benchmark_prices_daily from public,anon,authenticated,service_role;
grant select on investment.market_benchmark_prices_daily to authenticated,service_role;
grant insert,update on investment.market_benchmark_prices_daily to service_role;
do $$begin
 if not exists(select 1 from pg_policies where schemaname='investment' and tablename='market_benchmark_prices_daily' and policyname='owner_read') then
  create policy owner_read on investment.market_benchmark_prices_daily for select to authenticated using(owner_id=(select auth.uid()));
 end if;
end $$;
notify pgrst,'reload schema';
commit;
