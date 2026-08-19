# TTDHistoricData

Historical pilgrim darshan data for Tirumala Tirupati Devasthanams (TTD), scraped, parsed, and
analyzed from TTD's own announcements on [news.tirumala.org](https://news.tirumala.org). Every
number in the output is traceable back to a specific post — nothing is hand-typed or guessed.

## What this is

TTD publishes a daily post announcing how many pilgrims received darshan the previous day. This
project fetches every one of those posts, parses the pilgrim counts (and related figures like
wait times) out of free-form post titles/bodies, resolves duplicates and conflicts, flags
anomalies, builds a festival/holiday calendar to give the numbers context, and renders a
self-contained HTML report with charts and insights.

## Pipeline

The scripts run in sequence, each reading the previous stage's output:

1. **`fetch_darshan.py`** — Pulls every post in the "darshan" category from the WordPress REST
   API and caches the raw JSON to `raw/`, merged into `all_posts.json`. No parsing happens here,
   so the network fetch never needs to be repeated while parsing logic is iterated on.
2. **`parse_darshan.py`** — Parses `all_posts.json` into a per-date pilgrim series. Produces:
   - `darshan_daily.csv` — one row per calendar date (full-day totals)
   - `darshan_all_records.csv` — every parsed record, including partial-day snapshots
   - `darshan_duplicates_resolved.csv` — audit log of how repeated/conflicting dates were settled
   - `darshan_anomalies.csv` — suspicious, unparseable, or out-of-range records
   - `darshan_report.txt` — human-readable summary
3. **`build_calendar.py`** — Builds `festival_calendar.csv`, combining deterministic fixed-date
   national holidays with major festivals sourced from TTD's own dated posts (lunisolar Hindu
   festivals can't be computed arithmetically, so their dates are taken from TTD's announcements
   and kept traceable to a source URL). Raw calendar-category pages are cached in `raw_calendar/`.
4. **`analyze_darshan.py`** — Computes the insight series behind the visual report from
   `darshan_daily.csv`, writing `insights.json` so every figure in the report is derived from
   parsed data rather than typed by hand.
5. **`make_report.py`** — Renders `insights.json` into `darshan_report.html`, a self-contained
   visual report with charts and no hand-typed numbers.
6. **`validate_against_html.py`** — An independent check: re-derives figures straight from the
   public HTML listing pages at `news.tirumala.org/category/darshan/page/N/` and compares them
   against the REST-API-derived dataset, so a parsing or coverage error in the main pipeline
   can't pass unnoticed.

## Running it

```bash
python fetch_darshan.py        # cache raw posts -> raw/, all_posts.json
python parse_darshan.py        # -> darshan_daily.csv and friends
python build_calendar.py       # -> festival_calendar.csv
python analyze_darshan.py      # -> insights.json
python make_report.py          # -> darshan_report.html
python validate_against_html.py  # sanity-check against the public site
```

Each script is a plain Python 3 file with no third-party dependencies — only the standard
library is used.

## Data files

| File | Description |
|---|---|
| `all_posts.json` | Raw cached posts from the WordPress REST API |
| `darshan_daily.csv` | Daily pilgrim totals, one row per date |
| `darshan_all_records.csv` | Every parsed record, including partial-day snapshots |
| `darshan_anomalies.csv` | Records flagged as suspicious or out-of-range |
| `darshan_duplicates_resolved.csv` | Audit trail of duplicate/conflicting-date resolution |
| `darshan_gaps.csv` | Dates with missing data |
| `darshan_title_date_gapfills.csv` | Dates inferred from post titles to fill gaps |
| `festival_calendar.csv` | Festival and holiday calendar with source evidence |
| `insights.json` | Computed statistics behind the visual report |
| `darshan_report.html` | Self-contained HTML report with charts |
| `darshan_report.txt` | Plain-text summary |

## Data provenance

All figures originate from TTD's own public posts. Where a date had to be inferred rather than
read directly from a post, it is marked as such (see `date_source` in `darshan_all_records.csv`),
so every number can be audited back to its source.
