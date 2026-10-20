begin;
create table if not exists investment.daily_market_analysis (
 owner_id uuid not null references auth.users(id),
 report_id text not null check(report_id ~ '^[0-9a-f]{64}$'),
 report_date date not null,
 generated_at timestamptz not null,
 method text not null,
 report jsonb not null check(jsonb_typeof(report)='object'),
 primary key(owner_id,report_id)
);
create index if not exists daily_market_analysis_recent on investment.daily_market_analysis(owner_id,generated_at desc);
alter table investment.daily_market_analysis enable row level security;
revoke all on investment.daily_market_analysis from public,anon,authenticated;
do $$ begin
 if not exists(select 1 from pg_policies where schemaname='investment' and tablename='daily_market_analysis' and policyname='owner_read') then
  create policy owner_read on investment.daily_market_analysis for select to authenticated using(owner_id=(select auth.uid()));
 end if;
end $$;
grant select on investment.daily_market_analysis to authenticated;
-- Append-only reports: an unsuccessful run cannot overwrite a valid report.
grant select,insert on investment.daily_market_analysis to service_role;
notify pgrst,'reload schema';
commit;
