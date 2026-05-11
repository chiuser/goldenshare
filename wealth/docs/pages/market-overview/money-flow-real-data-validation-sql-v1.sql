\echo '=== money-flow real data validation (v1) ==='
\echo '--- env clock ---'
select
  now() at time zone 'Asia/Shanghai' as now_sh,
  current_date as db_current_date;

\echo '--- source profile ---'
select
  min(trade_date) as source_min_trade_date,
  max(trade_date) as source_max_trade_date,
  count(*) as source_rows
from core_serving.market_moneyflow_dc;

\echo '--- latest two rows snapshot ---'
with latest as (
  select max(trade_date) as d from core_serving.market_moneyflow_dc
)
select
  m.trade_date,
  m.net_amount,
  m.net_amount_rate,
  m.buy_elg_amount,
  m.buy_elg_amount_rate,
  m.buy_lg_amount,
  m.buy_lg_amount_rate,
  m.buy_md_amount,
  m.buy_md_amount_rate,
  m.buy_sm_amount,
  m.buy_sm_amount_rate
from core_serving.market_moneyflow_dc m
where m.trade_date in (
  (select d from latest),
  (select max(trade_date) from core_serving.market_moneyflow_dc where trade_date < (select d from latest))
)
order by m.trade_date desc;

\echo '--- state cases matrix (A/B/C/D) ---'
with runtime as (
  select
    (now() at time zone 'Asia/Shanghai') as now_sh
),
source_span as (
  select
    min(trade_date) as min_trade_date,
    max(trade_date) as max_trade_date
  from core_serving.market_moneyflow_dc
),
case_inputs as (
  select 'A_default'::text as case_name, null::date as requested_trade_date
  union all
  select 'B_explicit_today', (select now_sh::date from runtime)
  union all
  select 'C_source_min', (select min_trade_date from source_span)
  union all
  select 'D_before_source_min', (select min_trade_date - interval '1 day' from source_span)::date
),
calendar as (
  select trade_date, is_open, pretrade_date
  from core_serving.trade_calendar
  where exchange = 'SSE'
),
default_expected as (
  select
    case
      when extract(hour from r.now_sh) >= 20 then lo.latest_open
      when cd.current_day_open then coalesce(po.prev_open, lo.latest_open)
      else lo.latest_open
    end as expected_trade_date
  from runtime r
  cross join lateral (
    select max(trade_date) as latest_open
    from calendar
    where is_open and trade_date <= r.now_sh::date
  ) lo
  cross join lateral (
    select coalesce((select is_open from calendar where trade_date = r.now_sh::date), false) as current_day_open
  ) cd
  cross join lateral (
    select max(trade_date) as prev_open
    from calendar
    where is_open and trade_date < r.now_sh::date
  ) po
),
resolved as (
  select
    c.case_name,
    c.requested_trade_date,
    case
      when c.requested_trade_date is not null then c.requested_trade_date
      else (select expected_trade_date from default_expected)
    end as expected_trade_date
  from case_inputs c
),
enriched as (
  select
    r.case_name,
    r.requested_trade_date,
    r.expected_trade_date,
    (
      select max(trade_date) from core_serving.market_moneyflow_dc
    ) as observed_trade_date,
    (
      select max(trade_date) from calendar c where c.is_open and c.trade_date < r.expected_trade_date
    ) as prev_trade_date
  from resolved r
),
today_prev as (
  select
    e.*,
    exists (
      select 1 from core_serving.market_moneyflow_dc m where m.trade_date = e.expected_trade_date
    ) as has_today_row,
    exists (
      select 1 from core_serving.market_moneyflow_dc m where m.trade_date = e.prev_trade_date
    ) as has_prev_row
  from enriched e
),
history_counts as (
  select
    t.*,
    (
      select count(*)
      from core_serving.market_moneyflow_dc m
      where m.trade_date in (
        select c.trade_date
        from calendar c
        where c.is_open and c.trade_date <= t.expected_trade_date
        order by c.trade_date desc
        limit 22
      )
    ) as history_points_1m,
    (
      select count(*)
      from core_serving.market_moneyflow_dc m
      where m.trade_date in (
        select c.trade_date
        from calendar c
        where c.is_open and c.trade_date <= t.expected_trade_date
        order by c.trade_date desc
        limit 62
      )
    ) as history_points_3m
  from today_prev t
)
select
  h.case_name,
  h.requested_trade_date,
  h.expected_trade_date,
  h.observed_trade_date,
  h.prev_trade_date,
  h.has_today_row,
  h.has_prev_row,
  h.history_points_1m,
  h.history_points_3m,
  case
    when h.observed_trade_date is null then 'EMPTY'
    when h.expected_trade_date > h.observed_trade_date then 'DELAYED'
    when (not h.has_today_row) and (not h.has_prev_row) and h.history_points_1m = 0 and h.history_points_3m = 0 then 'EMPTY'
    when (not h.has_today_row) or (not h.has_prev_row) or h.history_points_1m < 22 or h.history_points_3m < 62 then 'PARTIAL'
    else 'READY'
  end as derived_module_status
from history_counts h
order by h.case_name;

\echo '--- performance baseline / Query-P1 (today+prev) ---'
explain (analyze, buffers, format text)
with runtime as (
  select (now() at time zone 'Asia/Shanghai') as now_sh
),
calendar as (
  select trade_date, is_open, pretrade_date
  from core_serving.trade_calendar
  where exchange = 'SSE'
),
expected as (
  select
    case
      when extract(hour from r.now_sh) >= 20 then lo.latest_open
      when cd.current_day_open then coalesce(po.prev_open, lo.latest_open)
      else lo.latest_open
    end as expected_trade_date
  from runtime r
  cross join lateral (
    select max(trade_date) as latest_open
    from calendar
    where is_open and trade_date <= r.now_sh::date
  ) lo
  cross join lateral (
    select coalesce((select is_open from calendar where trade_date = r.now_sh::date), false) as current_day_open
  ) cd
  cross join lateral (
    select max(trade_date) as prev_open
    from calendar
    where is_open and trade_date < r.now_sh::date
  ) po
),
prev_day as (
  select max(trade_date) as prev_trade_date
  from calendar
  where is_open and trade_date < (select expected_trade_date from expected)
)
select
  m.trade_date,
  m.net_amount,
  m.net_amount_rate,
  m.buy_elg_amount,
  m.buy_elg_amount_rate,
  m.buy_lg_amount,
  m.buy_lg_amount_rate,
  m.buy_md_amount,
  m.buy_md_amount_rate,
  m.buy_sm_amount,
  m.buy_sm_amount_rate
from core_serving.market_moneyflow_dc m
where m.trade_date in (
  (select expected_trade_date from expected),
  (select prev_trade_date from prev_day)
);

\echo '--- performance baseline / Query-P2 (1m history, 22 points) ---'
explain (analyze, buffers, format text)
with runtime as (
  select (now() at time zone 'Asia/Shanghai') as now_sh
),
calendar as (
  select trade_date, is_open, pretrade_date
  from core_serving.trade_calendar
  where exchange = 'SSE'
),
expected as (
  select
    case
      when extract(hour from r.now_sh) >= 20 then lo.latest_open
      when cd.current_day_open then coalesce(po.prev_open, lo.latest_open)
      else lo.latest_open
    end as expected_trade_date
  from runtime r
  cross join lateral (
    select max(trade_date) as latest_open
    from calendar
    where is_open and trade_date <= r.now_sh::date
  ) lo
  cross join lateral (
    select coalesce((select is_open from calendar where trade_date = r.now_sh::date), false) as current_day_open
  ) cd
  cross join lateral (
    select max(trade_date) as prev_open
    from calendar
    where is_open and trade_date < r.now_sh::date
  ) po
),
window_days as (
  select c.trade_date
  from calendar c
  where c.is_open and c.trade_date <= (select expected_trade_date from expected)
  order by c.trade_date desc
  limit 22
)
select
  m.trade_date,
  m.net_amount
from core_serving.market_moneyflow_dc m
join window_days w on w.trade_date = m.trade_date
order by m.trade_date;

\echo '--- performance baseline / Query-P3 (3m history, 62 points) ---'
explain (analyze, buffers, format text)
with runtime as (
  select (now() at time zone 'Asia/Shanghai') as now_sh
),
calendar as (
  select trade_date, is_open, pretrade_date
  from core_serving.trade_calendar
  where exchange = 'SSE'
),
expected as (
  select
    case
      when extract(hour from r.now_sh) >= 20 then lo.latest_open
      when cd.current_day_open then coalesce(po.prev_open, lo.latest_open)
      else lo.latest_open
    end as expected_trade_date
  from runtime r
  cross join lateral (
    select max(trade_date) as latest_open
    from calendar
    where is_open and trade_date <= r.now_sh::date
  ) lo
  cross join lateral (
    select coalesce((select is_open from calendar where trade_date = r.now_sh::date), false) as current_day_open
  ) cd
  cross join lateral (
    select max(trade_date) as prev_open
    from calendar
    where is_open and trade_date < r.now_sh::date
  ) po
),
window_days as (
  select c.trade_date
  from calendar c
  where c.is_open and c.trade_date <= (select expected_trade_date from expected)
  order by c.trade_date desc
  limit 62
)
select
  m.trade_date,
  m.net_amount
from core_serving.market_moneyflow_dc m
join window_days w on w.trade_date = m.trade_date
order by m.trade_date;

\echo '=== end ==='
