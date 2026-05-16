# IndiaStox Weekly — rendered panels

*Generated 2026-05-16T17:22:23+00:00 from `warehouse/indiastox.duckdb`. Same numbers a Metabase dashboard would render — see `dashboard/seed.py` for the API path that produces the actual UI.*

### Panel 1 — Weekly Challenge Funnel (Unstop cohort, strict-subset)

| step | n | % of registered |
| --- | --- | --- |
| unstop_registered | 1368 | 100.0% |
| challenge_signed_up | 1258 | 92.0% |
| made_a_prediction | 901 | 65.9% |
| outcome_resolved | 901 | 65.9% |

### Panel 2 — Channel Attribution (ghost_rate by source, from metric_results)

| source | ghost_rate | metric_version |
| --- | --- | --- |
| whatsapp_dark | 29.1% | v1.0.0 |
| unstop | 28.6% | v1.0.0 |
*Read from `metric_results` (the metric layer's materialization) — never re-computed in this file.*

### Panel 3 — Cohort Retention (W01 cohort, day-by-day activity)

| signup-week day | active_users | % of cohort |
| --- | --- | --- |
| day 0 | 51 | 2.5% |
| day 1 | 233 | 11.7% |
| day 2 | 418 | 20.9% |
| day 3 | 560 | 28.0% |
| day 4 | 530 | 26.5% |
| day 5 | 577 | 28.8% |
| day 6 | 539 | 27.0% |
*Cohort = 2000 W01 signups. Retention = unique-active-user count by signup-week-day.*

### Panel 4 — Identity Resolution Quality

| bucket | users | % |
| --- | --- | --- |
| high (≥ 0.85) | 1632 | 81.6% |
| medium (0.60–0.84) | 344 | 17.2% |
| low (< 0.60) | 24 | 1.2% |
| blocked (shared device) | 170 | 8.5% |
