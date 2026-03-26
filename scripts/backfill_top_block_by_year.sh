#!/usr/bin/env bash
set -euo pipefail

START_YEAR="${START_YEAR:-2026}"
END_YEAR="${END_YEAR:-2026}"

for year in $(seq "$START_YEAR" "$END_YEAR"); do
  echo "==== YEAR $year ===="

  YEAR="$year" python3 - <<'PY' | while read -r d; do
import os
from sqlalchemy import create_engine, text
from src.config.settings import get_settings

engine = create_engine(get_settings().database_url, future=True)
year = os.environ["YEAR"]
with engine.connect() as conn:
    rows = conn.execute(text(f"""
        select trade_date
        from core.trade_calendar
        where exchange = 'SSE'
          and is_open = true
          and trade_date between '{year}-01-01' and '{year}-12-31'
        order by trade_date
    """))
    for row in rows:
        print(row.trade_date.isoformat())
PY
    echo "top_list $d"
    goldenshare sync-daily --trade-date "$d" --resources top_list

    echo "block_trade $d"
    goldenshare sync-daily --trade-date "$d" --resources block_trade
  done

  echo "==== YEAR $year DONE ===="
done
