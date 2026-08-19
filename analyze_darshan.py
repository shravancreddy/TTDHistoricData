"""
Compute the insight series behind the visual report.

Reads darshan_daily.csv and writes insights.json -- every number in the report
is produced here from the parsed data, so the page never carries a hand-typed
figure.
"""

import csv
import datetime as dt
import json
import os
import statistics
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    rows = []
    with open(os.path.join(HERE, "darshan_daily.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            d = dt.date.fromisoformat(r["darshan_date"])
            rows.append({
                "date": d,
                "p": int(r["pilgrims"]),
                "dow": r["day_of_week"],
                "fest": r["is_festival_or_holiday"] == "yes",
                "fest_name": r["festival_name"],
                "wait": _i(r["sarva_hours"]) if r["sarva_hours"] else _i(r["darshan_wait_hours"]),
                "sarva_comp": _i(r["sarva_compartments"]),
                "divya_comp": _i(r["divya_compartments"]),
                "tons": _i(r["tonsures"]),
                "hundi": _f(r["hundi_cr"]),
                "link": r["link"],
                "qlink": r.get("queue_source_link") or "",
            })
    rows.sort(key=lambda x: x["date"])
    return rows


def _i(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    rows = load()
    by_date = {r["date"]: r for r in rows}
    out = {}

    out["meta"] = {
        "n_days": len(rows),
        "start": str(rows[0]["date"]),
        "end": str(rows[-1]["date"]),
        "total_pilgrims": sum(r["p"] for r in rows),
        "median": statistics.median(r["p"] for r in rows),
        "mean": round(statistics.mean(r["p"] for r in rows)),
    }

    # ---- yearly ---------------------------------------------------------
    yr = defaultdict(list)
    for r in rows:
        yr[r["date"].year].append(r["p"])
    out["yearly"] = [{"year": y, "days": len(v), "avg": round(statistics.mean(v)),
                      "total": sum(v), "max": max(v), "min": min(v),
                      "median": round(statistics.median(v))}
                     for y, v in sorted(yr.items())]

    # ---- full daily series (for the long-run line) ----------------------
    out["daily"] = [{"d": str(r["date"]), "p": r["p"]} for r in rows]

    # ---- busiest days ---------------------------------------------------
    top = sorted(rows, key=lambda r: -r["p"])[:15]
    out["top_days"] = [{"d": str(r["date"]), "p": r["p"], "dow": r["dow"],
                        "fest": r["fest_name"] or ("festival" if r["fest"] else ""),
                        "wait": r["wait"], "link": r["link"]} for r in top]

    # ---- wait-time vs crowd quadrants -----------------------------------
    w = [r for r in rows if r["wait"] is not None]
    out["wait_scatter"] = [{"d": str(r["date"]), "p": r["p"], "w": r["wait"],
                            "f": r["fest"]} for r in w]
    if w:
        pmed = statistics.median(r["p"] for r in w)
        wmed = statistics.median(r["wait"] for r in w)
        out["wait_meta"] = {"n": len(w), "p_median": pmed, "w_median": wmed,
                            "w_max": max(r["wait"] for r in w)}
        # the four extremes the brief asks for
        def pack(rs):
            return [{"d": str(r["date"]), "p": r["p"], "w": r["wait"],
                     "fest": r["fest_name"], "link": r["link"], "qlink": r["qlink"]}
                    for r in rs]

        out["extremes"] = {
            "long_wait_high_crowd": pack(sorted(w, key=lambda r: (-r["wait"], -r["p"]))[:10]),
            "long_wait_low_crowd": pack(sorted([x for x in w if x["wait"] >= wmed],
                                               key=lambda r: (r["p"], -r["wait"]))[:10]),
            "short_wait_high_crowd": pack(sorted([x for x in w if x["wait"] <= wmed],
                                                 key=lambda r: (-r["p"], r["wait"]))[:10]),
        }
        # Every queue reading longer than a day, with its citation. These are not
        # parsing errors: TTD publishes them verbatim ("Approx. Darsan Time.. 48H")
        # and the Tirumala queue genuinely runs across nights, pilgrims holding
        # place in the compartment sheds.
        out["over_24h"] = sorted(pack([x for x in w if x["wait"] > 24]),
                                 key=lambda x: (-x["w"], x["d"]))
        out["wait_hist"] = sorted(Counter(x["wait"] for x in w).items())

    # ---- month-on-month, last 6 years -----------------------------------
    years = sorted(yr)
    recent = [y for y in years if y >= max(years) - 5]
    mm = defaultdict(dict)
    for y in recent:
        for m in range(1, 13):
            v = [r["p"] for r in rows if r["date"].year == y and r["date"].month == m]
            if v:
                mm[y][m] = {"avg": round(statistics.mean(v)), "days": len(v),
                            "total": sum(v)}
    out["month_matrix"] = {str(y): {str(m): mm[y][m] for m in sorted(mm[y])} for y in recent}
    out["recent_years"] = recent

    # baseline: average by month across the 5 years before the latest
    base = defaultdict(list)
    for r in rows:
        if max(years) - 5 <= r["date"].year <= max(years) - 1:
            base[r["date"].month].append(r["p"])
    out["month_baseline"] = {str(m): round(statistics.mean(v)) for m, v in sorted(base.items())}
    cur = defaultdict(list)
    for r in rows:
        if r["date"].year == max(years):
            cur[r["date"].month].append(r["p"])
    out["month_current"] = {str(m): round(statistics.mean(v)) for m, v in sorted(cur.items())}
    out["latest_year"] = max(years)

    # ---- week-on-week, last 5 years -------------------------------------
    wk = defaultdict(list)
    for r in rows:
        iso = r["date"].isocalendar()
        if r["date"].year >= max(years) - 4:
            wk[(iso[0], iso[1])].append(r["p"])
    out["weekly"] = [{"year": y, "week": w, "avg": round(statistics.mean(v)), "days": len(v)}
                     for (y, w), v in sorted(wk.items())]

    # each of the last five years as its own week-of-year line
    per = defaultdict(dict)
    for (y, wnum), v in wk.items():
        if wnum <= 53 and len(v) >= 3:
            per[y][wnum] = round(statistics.mean(v))
    out["weekly_by_year"] = {str(y): [{"week": k, "avg": per[y][k]} for k in sorted(per[y])]
                             for y in sorted(per)}

    # week-of-year profile averaged over the last 5 years
    prof = defaultdict(list)
    for (y, w), v in wk.items():
        if len(v) >= 4:
            prof[w].append(statistics.mean(v))
    out["week_profile"] = [{"week": w, "avg": round(statistics.mean(v)), "years": len(v)}
                           for w, v in sorted(prof.items()) if w <= 53]

    # ---- seasonal rush: peak consecutive 7-day window per year -----------
    # Ratio-to-baseline scoring was abandoned here: the COVID closure and the
    # slow 2021 recovery depress any baseline that spans them, so ordinary
    # post-reopening weeks scored as record rushes and crowded out every real
    # peak. Taking each YEAR's own best window instead keeps the comparison
    # inside a comparable regime and shows where the rush recurs in the calendar.
    ymed = {y: statistics.median(v) for y, v in yr.items()}
    peaks = []
    for y in sorted(yr):
        if len(yr[y]) < 200:
            continue                       # part-years cannot be ranked fairly
        best = None
        for i in range(len(rows) - 6):
            seg = rows[i:i + 7]
            if seg[0]["date"].year != y or (seg[-1]["date"] - seg[0]["date"]).days != 6:
                continue
            avg = statistics.mean(s2["p"] for s2 in seg)
            if best is None or avg > best["avg"]:
                best = {"start": str(seg[0]["date"]), "end": str(seg[-1]["date"]),
                        "avg": round(avg), "year": y,
                        "month": seg[3]["date"].strftime("%b"),
                        "baseline": round(ymed[y]),
                        "ratio": round(avg / ymed[y], 2),
                        "fests": "; ".join(sorted({s2["fest_name"] for s2 in seg
                                                   if s2["fest_name"]}))[:110]}
        if best:
            peaks.append(best)
    out["peak_weeks"] = sorted(peaks, key=lambda x: -x["ratio"])
    covid = {2020, 2021}
    out["peak_month_counts"] = sorted(
        Counter(p["month"] for p in peaks if p["year"] not in covid).items(),
        key=lambda kv: -kv[1])

    # ---- wait time on festival vs ordinary days --------------------------
    fw = [r["wait"] for r in rows if r["fest"] and r["wait"] is not None]
    nw = [r["wait"] for r in rows if not r["fest"] and r["wait"] is not None]
    out["festival_wait"] = {
        "festival_avg_wait": round(statistics.mean(fw), 1) if fw else None,
        "normal_avg_wait": round(statistics.mean(nw), 1) if nw else None,
        "festival_n": len(fw), "normal_n": len(nw),
    }

    # seasonal shape: mean by month-of-year across all years
    mo = defaultdict(list)
    for r in rows:
        mo[r["date"].month].append(r["p"])
    grand = statistics.mean(r["p"] for r in rows)
    out["season_index"] = [{"month": m, "avg": round(statistics.mean(v)),
                            "index": round(statistics.mean(v) / grand * 100)}
                           for m, v in sorted(mo.items())]

    # ---- day-of-week ----------------------------------------------------
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    dw = defaultdict(list)
    for r in rows:
        dw[r["dow"]].append(r["p"])
    out["dow"] = [{"day": d, "avg": round(statistics.mean(dw[d])), "n": len(dw[d]),
                   "index": round(statistics.mean(dw[d]) / grand * 100)}
                  for d in order if d in dw]

    # ---- festival effect -------------------------------------------------
    f = [r["p"] for r in rows if r["fest"]]
    nf = [r["p"] for r in rows if not r["fest"]]
    out["festival_effect"] = {
        "festival_days": len(f), "festival_avg": round(statistics.mean(f)) if f else 0,
        "normal_days": len(nf), "normal_avg": round(statistics.mean(nf)) if nf else 0,
        "uplift_pct": round((statistics.mean(f) / statistics.mean(nf) - 1) * 100, 1) if f and nf else 0,
    }
    fn = defaultdict(list)
    for r in rows:
        for name in [x.strip() for x in r["fest_name"].split(";") if x.strip()]:
            fn[name].append(r["p"])
    out["by_festival"] = sorted(
        [{"name": k, "n": len(v), "avg": round(statistics.mean(v))}
         for k, v in fn.items() if len(v) >= 4],
        key=lambda x: -x["avg"])[:12]

    # ---- hundi / tonsures ------------------------------------------------
    h = [r for r in rows if r["hundi"] is not None]
    out["hundi_yearly"] = [
        {"year": y, "avg_cr": round(statistics.mean([r["hundi"] for r in h if r["date"].year == y]), 2),
         "n": len([r for r in h if r["date"].year == y])}
        for y in sorted({r["date"].year for r in h})]
    t = [r for r in rows if r["tons"] is not None]
    out["tonsure_ratio_yearly"] = [
        {"year": y,
         "ratio": round(statistics.mean([r["tons"] / r["p"] for r in t
                                         if r["date"].year == y and r["p"]]) * 100, 1)}
        for y in sorted({r["date"].year for r in t})]

    # ---- covid gap -------------------------------------------------------
    out["gaps_note"] = {
        "covid_closed_from": "2020-03-21", "covid_closed_to": "2020-06-10",
    }

    with open(os.path.join(HERE, "insights.json"), "w", encoding="utf-8") as f2:
        json.dump(out, f2, indent=1, default=str)

    print(f"days {out['meta']['n_days']:,} | {out['meta']['start']} -> {out['meta']['end']}")
    print(f"total pilgrims {out['meta']['total_pilgrims']:,}")
    print(f"festival uplift {out['festival_effect']['uplift_pct']}%")
    print("peak weeks:")
    for p in out["peak_weeks"]:
        print(f"  {p['start']} -> {p['end']}  avg {p['avg']:,}  x{p['ratio']} of {p['year']} mean")
    print("wrote insights.json")


if __name__ == "__main__":
    main()
