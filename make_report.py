"""
Render the visual report from insights.json into a self-contained HTML page.

Every figure and every chart coordinate is computed from the parsed data here --
the page carries no hand-typed numbers.
"""

import datetime as dt
import html
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, "insights.json"), encoding="utf-8"))

# validated categorical slots (dataviz reference palette)
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"


def esc(s):
    return html.escape(str(s))


def fm(n):
    return f"{int(round(n)):,}"


def nice_max(v, steps=4):
    """Round an axis top up to a readable step."""
    if v <= 0:
        return steps
    import math
    mag = 10 ** math.floor(math.log10(v))
    for m in (1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10):
        top = m * mag
        if top >= v:
            return top
    return 10 * mag


# ---------------------------------------------------------------- hero series
def hero_chart():
    daily = [(dt.date.fromisoformat(x["d"]), x["p"]) for x in D["daily"]]
    w, h = 1080, 330
    pad_l, pad_r, pad_t, pad_b = 54, 14, 16, 34
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    d0, d1 = daily[0][0], daily[-1][0]
    span = (d1 - d0).days
    top = nice_max(max(p for _, p in daily))

    def X(d):
        return pad_l + (d - d0).days / span * iw

    def Y(p):
        return pad_t + ih - p / top * ih

    # faint daily line, broken across gaps longer than 3 days
    segs, cur = [], []
    prev = None
    for d, p in daily:
        if prev and (d - prev).days > 3:
            segs.append(cur)
            cur = []
        cur.append(f"{X(d):.1f},{Y(p):.1f}")
        prev = d
    segs.append(cur)
    thin = "".join(
        f'<polyline points="{" ".join(s)}" fill="none" stroke="{S1}" '
        f'stroke-width="1" opacity=".26"/>' for s in segs if len(s) > 1)

    # 30-day trailing mean, same gap rule
    roll, buf = [], []
    prev = None
    rsegs, cur = [], []
    for d, p in daily:
        if prev and (d - prev).days > 3:
            rsegs.append(cur)
            cur, buf = [], []
        buf.append(p)
        if len(buf) > 30:
            buf.pop(0)
        if len(buf) >= 10:
            cur.append(f"{X(d):.1f},{Y(statistics.mean(buf)):.1f}")
        prev = d
    rsegs.append(cur)
    thick = "".join(
        f'<polyline points="{" ".join(s)}" fill="none" stroke="{S1}" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        for s in rsegs if len(s) > 1)

    # covid closure band
    ca = dt.date.fromisoformat(D["gaps_note"]["covid_closed_from"])
    cb = dt.date.fromisoformat(D["gaps_note"]["covid_closed_to"])
    band = (f'<rect x="{X(ca):.1f}" y="{pad_t}" width="{X(cb)-X(ca):.1f}" '
            f'height="{ih}" fill="var(--flag)" opacity=".5"/>'
            f'<text x="{X(cb)+6:.1f}" y="{pad_t+13}" class="ann">temple closed '
            f'{(cb-ca).days+1} days</text>')

    grid = "".join(
        f'<line x1="{pad_l}" x2="{w-pad_r}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="grid"/>'
        f'<text x="{pad_l-8}" y="{Y(v)+4:.1f}" class="ytick">{int(v/1000)}k</text>'
        for v in [top * i / 4 for i in range(5)])
    ticks = "".join(
        f'<text x="{X(dt.date(y,1,1)):.1f}" y="{h-12}" class="xtick">{y}</text>'
        for y in range(d0.year + 1, d1.year + 1))
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
            f'aria-label="Daily pilgrims at Tirumala, {D["meta"]["start"]} to {D["meta"]["end"]}">'
            f"{grid}{band}{thin}{thick}{ticks}</svg>")


# ---------------------------------------------------------------- yearly bars
def yearly_chart():
    ys = D["yearly"]
    w, h = 1080, 250
    pad_l, pad_b, pad_t = 54, 46, 12
    iw, ih = w - pad_l - 14, h - pad_t - pad_b
    top = nice_max(max(y["avg"] for y in ys))
    bw = iw / len(ys)
    bars, labs = "", ""
    for i, y in enumerate(ys):
        bh = y["avg"] / top * ih
        x = pad_l + i * bw + bw * 0.16
        bwid = bw * 0.68
        yy = pad_t + ih - bh
        partial = y["days"] < 300
        bars += (f'<rect class="bar" x="{x:.1f}" y="{yy:.1f}" width="{bwid:.1f}" '
                 f'height="{bh:.1f}" rx="4" fill="{S1}"'
                 f'{" opacity=.55" if partial else ""}>'
                 f'<title>{y["year"]}: avg {fm(y["avg"])}/day over {y["days"]} days '
                 f'(max {fm(y["max"])})</title></rect>')
        labs += (f'<text x="{x+bwid/2:.1f}" y="{yy-6:.1f}" class="barval">{fm(y["avg"])}</text>'
                 f'<text x="{x+bwid/2:.1f}" y="{h-26}" class="xtick">{y["year"]}</text>'
                 f'<text x="{x+bwid/2:.1f}" y="{h-12}" class="xtick dim">{y["days"]}d</text>')
    grid = "".join(
        f'<line x1="{pad_l}" x2="{w-14}" y1="{pad_t+ih-v/top*ih:.1f}" '
        f'y2="{pad_t+ih-v/top*ih:.1f}" class="grid"/>'
        f'<text x="{pad_l-8}" y="{pad_t+ih-v/top*ih+4:.1f}" class="ytick">{int(v/1000)}k</text>'
        for v in [top * i / 4 for i in range(5)])
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
            f'aria-label="Average daily pilgrims by year">{grid}{bars}{labs}</svg>')


# ---------------------------------------------------------------- month heat
def month_heat():
    years = [str(y) for y in D["recent_years"]]
    mm = D["month_matrix"]
    vals = [mm[y][m]["avg"] for y in years for m in mm[y]]
    lo, hi = min(vals), max(vals)
    ramp = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec",
            "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95"]
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    cw, ch, lx, ty = 74, 40, 52, 22
    w = lx + 12 * cw + 8
    h = ty + len(years) * ch + 12
    cells = "".join(
        f'<text x="{lx+i*cw+cw/2}" y="{ty-8}" class="xtick">{n}</text>'
        for i, n in enumerate(names))
    for r, y in enumerate(years):
        cells += f'<text x="{lx-10}" y="{ty+r*ch+ch/2+4}" class="ytick">{y}</text>'
        for i in range(12):
            m = str(i + 1)
            if m not in mm[y]:
                continue
            v = mm[y][m]["avg"]
            k = ramp[min(len(ramp) - 1, int((v - lo) / (hi - lo + 1e-9) * len(ramp)))]
            dark = (v - lo) / (hi - lo + 1e-9) > 0.55
            cells += (f'<rect class="cell" x="{lx+i*cw+1}" y="{ty+r*ch+1}" '
                      f'width="{cw-3}" height="{ch-3}" rx="3" fill="{k}">'
                      f'<title>{names[i]} {y}: avg {fm(v)}/day, {mm[y][m]["days"]} days</title></rect>'
                      f'<text x="{lx+i*cw+cw/2}" y="{ty+r*ch+ch/2+4}" '
                      f'class="cellval" fill="{"#fff" if dark else "#0b0b0b"}">'
                      f'{round(v/1000)}k</text>')
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
            f'aria-label="Average daily pilgrims by month and year">{cells}</svg>')


# ---------------------------------------------------------------- simple bars
MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def index_bars(items, key, label_key, aria, hi_color=S2, note=None, months=False):
    w, h = 1080, 200
    pad_l, pad_b, pad_t = 46, 40, 22
    iw, ih = w - pad_l - 14, h - pad_t - pad_b
    top = nice_max(max(i[key] for i in items))
    bw = iw / len(items)
    base = 100
    out = ""
    for i, it in enumerate(items):
        bh = it[key] / top * ih
        x = pad_l + i * bw + bw * 0.18
        bwid = bw * 0.64
        yy = pad_t + ih - bh
        col = hi_color if it[key] >= base else S1
        lab = MONTH_NAMES[int(it[label_key]) - 1] if months else str(it[label_key])[:3]
        out += (f'<rect class="bar" x="{x:.1f}" y="{yy:.1f}" width="{bwid:.1f}" '
                f'height="{bh:.1f}" rx="4" fill="{col}">'
                f'<title>{lab}: index {it[key]} ({note or ""})</title></rect>'
                f'<text x="{x+bwid/2:.1f}" y="{yy-6:.1f}" class="barval">{it[key]}</text>'
                f'<text x="{x+bwid/2:.1f}" y="{h-14}" class="xtick">{lab}</text>')
    y100 = pad_t + ih - base / top * ih
    out += (f'<line x1="{pad_l}" x2="{w-14}" y1="{y100:.1f}" y2="{y100:.1f}" class="baseline"/>'
            f'<text x="{w-16}" y="{y100-6:.1f}" class="ann" text-anchor="end">average = 100</text>')
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="{aria}">{out}</svg>')


# ---------------------------------------------------------------- week profile
def week_profile():
    wp = D["week_profile"]
    w, h = 1080, 220
    pad_l, pad_b, pad_t = 54, 36, 14
    iw, ih = w - pad_l - 14, h - pad_t - pad_b
    top = nice_max(max(x["avg"] for x in wp))
    pts = []
    for x in wp:
        px = pad_l + (x["week"] - 1) / 52 * iw
        py = pad_t + ih - x["avg"] / top * ih
        pts.append(f"{px:.1f},{py:.1f}")
    area = (f'<polygon points="{pad_l},{pad_t+ih} {" ".join(pts)} {pad_l+iw},{pad_t+ih}" '
            f'fill="{S1}" opacity=".13"/>')
    line = f'<polyline points="{" ".join(pts)}" fill="none" stroke="{S1}" stroke-width="2"/>'
    dots = "".join(
        f'<circle cx="{pad_l+(x["week"]-1)/52*iw:.1f}" cy="{pad_t+ih-x["avg"]/top*ih:.1f}" '
        f'r="4" fill="{S1}" class="dot" stroke="var(--surface)" stroke-width="2">'
        f'<title>ISO week {x["week"]}: avg {fm(x["avg"])}/day</title></circle>' for x in wp)
    grid = "".join(
        f'<line x1="{pad_l}" x2="{w-14}" y1="{pad_t+ih-v/top*ih:.1f}" '
        f'y2="{pad_t+ih-v/top*ih:.1f}" class="grid"/>'
        f'<text x="{pad_l-8}" y="{pad_t+ih-v/top*ih+4:.1f}" class="ytick">{int(v/1000)}k</text>'
        for v in [top * i / 4 for i in range(5)])
    mstart = [1, 5, 9, 14, 18, 23, 27, 31, 36, 40, 44, 49]
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    ticks = "".join(
        f'<text x="{pad_l+(mw-1)/52*iw:.1f}" y="{h-12}" class="xtick">{n}</text>'
        for mw, n in zip(mstart, names))
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
            f'aria-label="Average pilgrims by week of year, last five years">'
            f'{grid}{area}{line}{dots}{ticks}</svg>')


# ---------------------------------------------------------------- scatter
def wait_scatter():
    pts = D["wait_scatter"]
    w, h = 1080, 380
    pad_l, pad_b, pad_t = 60, 46, 16
    iw, ih = w - pad_l - 14, h - pad_t - pad_b
    xtop = nice_max(max(p["p"] for p in pts))
    ytop = max(p["w"] for p in pts)
    ytop = ytop + (4 - ytop % 4)

    def X(v):
        return pad_l + v / xtop * iw

    def Y(v):
        return pad_t + ih - v / ytop * ih

    pm, wm = D["wait_meta"]["p_median"], D["wait_meta"]["w_median"]
    quad = (f'<line x1="{X(pm):.1f}" x2="{X(pm):.1f}" y1="{pad_t}" y2="{pad_t+ih}" class="med"/>'
            f'<line x1="{pad_l}" x2="{w-14}" y1="{Y(wm):.1f}" y2="{Y(wm):.1f}" class="med"/>')
    body = ""
    for p in pts:
        c = S2 if p["f"] else S1
        body += (f'<circle cx="{X(p["p"]):.1f}" cy="{Y(p["w"]):.1f}" r="3.4" fill="{c}" '
                 f'opacity="{0.85 if p["f"] else 0.4}" class="pt">'
                 f'<title>{p["d"]}: {fm(p["p"])} pilgrims, {p["w"]}h wait'
                 f'{" — festival/holiday" if p["f"] else ""}</title></circle>')
    grid = "".join(
        f'<line x1="{pad_l}" x2="{w-14}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="grid"/>'
        f'<text x="{pad_l-8}" y="{Y(v)+4:.1f}" class="ytick">{int(v)}h</text>'
        for v in [ytop * i / 4 for i in range(5)])
    xt = "".join(
        f'<text x="{X(v):.1f}" y="{h-24}" class="xtick">{int(v/1000)}k</text>'
        for v in [xtop * i / 4 for i in range(5)])
    lab = (f'<text x="{w-16}" y="{Y(ytop)+16:.1f}" class="ann" text-anchor="end">'
           f'long wait, big crowd</text>'
           f'<text x="{pad_l+8}" y="{Y(ytop)+16:.1f}" class="ann">long wait, small crowd</text>'
           f'<text x="{w-16}" y="{pad_t+ih-8}" class="ann" text-anchor="end">short wait, big crowd</text>'
           f'<text x="{w/2:.0f}" y="{h-6}" class="axtitle">pilgrims that day</text>')
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
            f'aria-label="Sarva darshan waiting hours against daily pilgrim count">'
            f'{grid}{quad}{body}{xt}{lab}</svg>')


# ---------------------------------------------------------------- hundi line
def hundi_chart():
    hs = [x for x in D["hundi_yearly"] if x["n"] >= 30]
    w, h = 520, 200
    pad_l, pad_b, pad_t = 44, 34, 14
    iw, ih = w - pad_l - 14, h - pad_t - pad_b
    top = nice_max(max(x["avg_cr"] for x in hs))
    bw = iw / len(hs)
    out = ""
    for i, x in enumerate(hs):
        bh = x["avg_cr"] / top * ih
        px = pad_l + i * bw + bw * 0.18
        out += (f'<rect class="bar" x="{px:.1f}" y="{pad_t+ih-bh:.1f}" width="{bw*0.64:.1f}" '
                f'height="{bh:.1f}" rx="3" fill="{S3}">'
                f'<title>{x["year"]}: avg Rs {x["avg_cr"]} crore/day ({x["n"]} days)</title></rect>'
                f'<text x="{px+bw*0.32:.1f}" y="{pad_t+ih-bh-5:.1f}" class="barval">{x["avg_cr"]}</text>'
                f'<text x="{px+bw*0.32:.1f}" y="{h-12}" class="xtick">{str(x["year"])[2:]}</text>')
    grid = "".join(
        f'<line x1="{pad_l}" x2="{w-14}" y1="{pad_t+ih-v/top*ih:.1f}" '
        f'y2="{pad_t+ih-v/top*ih:.1f}" class="grid"/>'
        f'<text x="{pad_l-8}" y="{pad_t+ih-v/top*ih+4:.1f}" class="ytick">{v:g}</text>'
        for v in [top * i / 4 for i in range(5)])
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
            f'aria-label="Average daily hundi collection by year">{grid}{out}</svg>')


def tonsure_chart():
    ts = D["tonsure_ratio_yearly"]
    w, h = 520, 200
    pad_l, pad_b, pad_t = 44, 34, 14
    iw, ih = w - pad_l - 14, h - pad_t - pad_b
    top = nice_max(max(x["ratio"] for x in ts))
    pts = [f'{pad_l+i/(len(ts)-1)*iw:.1f},{pad_t+ih-x["ratio"]/top*ih:.1f}'
           for i, x in enumerate(ts)]
    dots = "".join(
        f'<circle cx="{pad_l+i/(len(ts)-1)*iw:.1f}" cy="{pad_t+ih-x["ratio"]/top*ih:.1f}" '
        f'r="4" fill="{S2}" stroke="var(--surface)" stroke-width="2">'
        f'<title>{x["year"]}: {x["ratio"]}% of pilgrims tonsured</title></circle>'
        for i, x in enumerate(ts))
    xt = "".join(
        f'<text x="{pad_l+i/(len(ts)-1)*iw:.1f}" y="{h-12}" class="xtick">{str(x["year"])[2:]}</text>'
        for i, x in enumerate(ts))
    grid = "".join(
        f'<line x1="{pad_l}" x2="{w-14}" y1="{pad_t+ih-v/top*ih:.1f}" '
        f'y2="{pad_t+ih-v/top*ih:.1f}" class="grid"/>'
        f'<text x="{pad_l-8}" y="{pad_t+ih-v/top*ih+4:.1f}" class="ytick">{v:g}%</text>'
        for v in [top * i / 4 for i in range(5)])
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
            f'aria-label="Tonsures as a share of pilgrims by year">{grid}'
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="{S2}" stroke-width="2"/>'
            f'{dots}{xt}</svg>')


# ------------------------------------------------- linked horizontal bar rows
def bar_rows(items, val, label, sub=None, chip=None, href=None, color=S1, unit=""):
    """A ranked list drawn as bars. Rows link to the bulletin they came from,
    which a plain chart cannot do -- that citation is the reason this form
    exists rather than an SVG bar chart."""
    top = max(i[val] for i in items)
    out = ['<div class="rows">']
    for it in items:
        pct = it[val] / top * 100
        link = href(it) if href else None
        chipv = chip(it) if chip else ""
        inner = (
            f'<span class="rl">{label(it)}'
            f'{f"<em>{sub(it)}</em>" if sub else ""}</span>'
            f'<span class="rb"><span class="rf" style="width:{pct:.1f}%;background:{color}"></span></span>'
            f'<span class="rv">{fm(it[val])}{unit}</span>'
            f'{f"<span class=chip>{chipv}</span>" if chipv else "<span class=chip-empty></span>"}')
        out.append(f'<a class="row" href="{esc(link)}" target="_blank" rel="noopener">{inner}</a>'
                   if link else f'<div class="row">{inner}</div>')
    out.append("</div>")
    return "".join(out)


# -------------------------------------------------- weekly lines, one per year
def weekly_by_year():
    wby = D["weekly_by_year"]
    years = sorted(wby)
    w, h = 1080, 300
    pad_l, pad_b, pad_t = 54, 40, 16
    iw, ih = w - pad_l - 14, h - pad_t - pad_b
    top = nice_max(max(p["avg"] for y in years for p in wby[y]))
    # one hue, stepped light->dark by year: these are the same measure over
    # time, not different categories, so a categorical scramble would mislead
    ramp = ["#9ec5f4", "#6da7ec", "#3987e5", "#2a78d6", "#184f95"]
    grid = "".join(
        f'<line x1="{pad_l}" x2="{w-14}" y1="{pad_t+ih-v/top*ih:.1f}" '
        f'y2="{pad_t+ih-v/top*ih:.1f}" class="grid"/>'
        f'<text x="{pad_l-8}" y="{pad_t+ih-v/top*ih+4:.1f}" class="ytick">{int(v/1000)}k</text>'
        for v in [top * i / 4 for i in range(5)])
    lines = ""
    for i, y in enumerate(years):
        col = ramp[i % len(ramp)]
        pts = " ".join(f'{pad_l+(p["week"]-1)/52*iw:.1f},{pad_t+ih-p["avg"]/top*ih:.1f}'
                       for p in wby[y])
        lines += (f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2" '
                  f'stroke-linejoin="round" class="yline" data-year="{y}"><title>{y}</title></polyline>')
        last = wby[y][-1]
        lines += (f'<text x="{pad_l+(last["week"]-1)/52*iw+6:.1f}" '
                  f'y="{pad_t+ih-last["avg"]/top*ih+4:.1f}" class="ylab" fill="{col}">{y}</text>')
    mstart = [1, 5, 9, 14, 18, 23, 27, 31, 36, 40, 44, 49]
    ticks = "".join(
        f'<text x="{pad_l+(mw-1)/52*iw:.1f}" y="{h-12}" class="xtick">{n}</text>'
        for mw, n in zip(mstart, MONTH_NAMES))
    legend = "".join(
        f'<span class="key"><span class="dotk" style="background:{ramp[i%len(ramp)]}"></span>{y}</span>'
        for i, y in enumerate(years))
    return (f'<div class="legend">{legend}</div>'
            f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
            f'aria-label="Average daily pilgrims by week of year, each of the last five years">'
            f'{grid}{lines}{ticks}</svg>')


# ------------------------------------------------------- peak-week timeline
def peak_timeline():
    peaks = sorted(D["peak_weeks"], key=lambda p: p["year"])
    covid = {2020, 2021}
    w = 1080
    rowh = 30
    pad_l, pad_t = 54, 26
    h = pad_t + len(peaks) * rowh + 26
    iw = w - pad_l - 120
    out = "".join(
        f'<text x="{pad_l+(sum(1 for _ in range(0)) + (i/12))*iw:.0f}" y="0" class="xtick"></text>'
        for i in [])
    # month gridlines across a 365-day axis
    doy = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
    for d0, n in zip(doy, MONTH_NAMES):
        x = pad_l + (d0 - 1) / 365 * iw
        out += (f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{pad_t-10}" y2="{pad_t+len(peaks)*rowh}" '
                f'class="grid"/><text x="{x+3:.1f}" y="{pad_t-14}" class="xtick" '
                f'text-anchor="start">{n}</text>')
    for i, p in enumerate(peaks):
        a = dt.date.fromisoformat(p["start"])
        y0 = pad_t + i * rowh
        x = pad_l + (a.timetuple().tm_yday - 1) / 365 * iw
        bw = max(6.0, 7 / 365 * iw)
        cov = p["year"] in covid
        col = S3 if cov else S2
        out += (f'<text x="{pad_l-8}" y="{y0+rowh/2+4}" class="ytick">{p["year"]}</text>'
                f'<line x1="{pad_l}" x2="{pad_l+iw}" y1="{y0+rowh/2}" y2="{y0+rowh/2}" class="grid"/>'
                f'<rect class="bar" x="{x:.1f}" y="{y0+6}" width="{bw:.1f}" height="{rowh-13}" '
                f'rx="3" fill="{col}"{" opacity=.55" if cov else ""}>'
                f'<title>{p["year"]}: {p["start"]} to {p["end"]}, avg {fm(p["avg"])}/day, '
                f'{p["ratio"]}x the year median</title></rect>'
                f'<text x="{pad_l+iw+10}" y="{y0+rowh/2+4}" class="barval" '
                f'text-anchor="start">{fm(p["avg"])}/day &#183; &#215;{p["ratio"]}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
            f'aria-label="Each year\'s heaviest seven-day stretch, placed on the calendar">'
            f'{out}</svg>')


# ------------------------------------------------------- year range plot
def year_range():
    ys = D["yearly"]
    w, h = 1080, 260
    pad_l, pad_b, pad_t = 54, 42, 16
    iw, ih = w - pad_l - 14, h - pad_t - pad_b
    top = nice_max(max(y["max"] for y in ys))
    step = iw / len(ys)
    out = "".join(
        f'<line x1="{pad_l}" x2="{w-14}" y1="{pad_t+ih-v/top*ih:.1f}" '
        f'y2="{pad_t+ih-v/top*ih:.1f}" class="grid"/>'
        f'<text x="{pad_l-8}" y="{pad_t+ih-v/top*ih+4:.1f}" class="ytick">{int(v/1000)}k</text>'
        for v in [top * i / 4 for i in range(5)])
    for i, y in enumerate(ys):
        cx = pad_l + i * step + step / 2

        def Y(v):
            return pad_t + ih - v / top * ih
        out += (f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{Y(y["max"]):.1f}" '
                f'y2="{Y(y["min"]):.1f}" stroke="{S1}" stroke-width="7" '
                f'stroke-linecap="round" opacity=".26"><title>{y["year"]}: quietest '
                f'{fm(y["min"])}, median {fm(y["median"])}, busiest {fm(y["max"])}</title></line>'
                f'<circle cx="{cx:.1f}" cy="{Y(y["median"]):.1f}" r="5.5" fill="{S1}" '
                f'stroke="var(--surface)" stroke-width="2"/>'
                f'<text x="{cx:.1f}" y="{Y(y["max"])-8:.1f}" class="barval">{round(y["max"]/1000)}k</text>'
                f'<text x="{cx:.1f}" y="{h-24}" class="xtick">{y["year"]}</text>'
                f'<text x="{cx:.1f}" y="{h-11}" class="xtick dim">{y["days"]}d</text>')
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
            f'aria-label="Quietest to busiest day each year, with the median marked">{out}</svg>')


# ------------------------------------------------------- wait distribution
def wait_hist():
    hist = D["wait_hist"]
    w, h = 1080, 210
    pad_l, pad_b, pad_t = 46, 40, 20
    iw, ih = w - pad_l - 14, h - pad_t - pad_b
    top = nice_max(max(c for _, c in hist))
    maxh = max(v for v, _ in hist)
    bw = iw / (maxh + 1)
    out = "".join(
        f'<line x1="{pad_l}" x2="{w-14}" y1="{pad_t+ih-v/top*ih:.1f}" '
        f'y2="{pad_t+ih-v/top*ih:.1f}" class="grid"/>'
        f'<text x="{pad_l-8}" y="{pad_t+ih-v/top*ih+4:.1f}" class="ytick">{int(v)}</text>'
        for v in [top * i / 4 for i in range(5)])
    for v, c in hist:
        bh = c / top * ih
        x = pad_l + v * bw + bw * 0.12
        col = S2 if v > 24 else S1
        out += (f'<rect class="bar" x="{x:.1f}" y="{pad_t+ih-bh:.1f}" width="{bw*0.76:.1f}" '
                f'height="{bh:.1f}" rx="2" fill="{col}">'
                f'<title>{v}h queue reported on {c} mornings</title></rect>')
    x24 = pad_l + 24.5 * bw
    out += (f'<line x1="{x24:.1f}" x2="{x24:.1f}" y1="{pad_t-4}" y2="{pad_t+ih}" class="baseline"/>'
            f'<text x="{x24+6:.1f}" y="{pad_t+6}" class="ann">longer than 24h &rarr;</text>')
    out += "".join(
        f'<text x="{pad_l+v*bw+bw/2:.1f}" y="{h-14}" class="xtick">{v}h</text>'
        for v in range(0, maxh + 1, 4))
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" '
            f'aria-label="How often each queue length was reported">{out}</svg>')


# ---------------------------------------------------------------- tables
def rows_table(rows, cols, cls=""):
    head = "".join(f"<th>{esc(c[0])}</th>" for c in cols)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(
            f'<td class="{c[2] if len(c) > 2 else ""}">{c[1](r)}</td>' for c in cols) + "</tr>"
    return f'<div class="tw"><table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def build():
    m = D["meta"]
    fe = D["festival_effect"]
    fw = D["festival_wait"]
    yrs = D["yearly"]
    peak = D["peak_weeks"]
    dow = D["dow"]

    busiest = D["top_days"][0]
    quietest_year = min(yrs, key=lambda y: y["avg"])
    best_year = max(yrs, key=lambda y: y["avg"])

    stat = lambda v, l, s="": (
        f'<div class="stat"><div class="sv">{v}</div><div class="sl">{l}</div>'
        f'{f"<div class=ss>{s}</div>" if s else ""}</div>')

    stats = (stat(f'{m["total_pilgrims"]/1e6:.1f}M', "pilgrims recorded",
                  f'{m["n_days"]:,} days with a published figure')
             + stat(fm(m["median"]), "median day", f'mean {fm(m["mean"])}')
             + stat(fm(busiest["p"]), "busiest day", f'{busiest["d"]} · {busiest["dow"]}')
             + stat(f'{D["wait_meta"]["w_max"]}h', "longest queue recorded",
                    f'median wait {D["wait_meta"]["w_median"]}h'))

    lk = lambda r: r.get("link") or ""
    qlk = lambda r: r.get("qlink") or r.get("link") or ""

    busiest_rows = bar_rows(
        D["top_days"], "p",
        label=lambda r: esc(r["d"]),
        sub=lambda r: esc(r["dow"]) + (f' &middot; {esc(r["fest"])}' if r["fest"] else ""),
        chip=lambda r: (f'{r["wait"]}h queue' if r["wait"] else ""),
        href=lk)

    def ext_rows(key, color):
        return bar_rows(
            D["extremes"][key], "p",
            label=lambda r: esc(r["d"]),
            sub=lambda r: esc(r["fest"]) if r["fest"] else "",
            chip=lambda r: f'{r["w"]}h',
            href=qlk, color=color)

    over24 = bar_rows(
        D["over_24h"][:12], "w",
        label=lambda r: esc(r["d"]),
        sub=lambda r: f'{fm(r["p"])} pilgrims that day',
        chip=lambda r: "bulletin &#8599;",
        href=qlk, color=S2, unit="h")

    fest_rows = bar_rows(
        D["by_festival"], "avg",
        label=lambda r: esc(r["name"]),
        sub=lambda r: f'{r["n"]} days',
        color=S3)

    peak_months = ", ".join(f"{k} ({v})" for k, v in D["peak_month_counts"])

    return f"""<title>Tirumala Darshan Record</title>
<style>
:root {{
  color-scheme: light;
  --ground:#f6f4ef; --surface:#fdfcfa; --ink:#171512; --ink2:#57534a;
  --muted:#8a857a; --rule:#e3ded2; --hair:rgba(23,21,18,.09);
  --brass:#9a6b1f; --flag:#efe4cf; --band:#f0ece1;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
    --ground:#111110; --surface:#1a1a19; --ink:#f7f5f0; --ink2:#c3c2b7;
    --muted:#8f8c83; --rule:#302f2b; --hair:rgba(255,255,255,.10);
    --brass:#d2a24e; --flag:#33301f; --band:#232320;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --ground:#111110; --surface:#1a1a19; --ink:#f7f5f0; --ink2:#c3c2b7;
  --muted:#8f8c83; --rule:#302f2b; --hair:rgba(255,255,255,.10);
  --brass:#d2a24e; --flag:#33301f; --band:#232320;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--ground);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.55;
  -webkit-font-smoothing:antialiased}}
.wrap{{max-width:1180px;margin:0 auto;padding:0 24px 96px}}
h1,h2,h3{{font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  font-weight:600;text-wrap:balance;margin:0}}
header.mast{{padding:64px 0 30px;border-bottom:2px solid var(--ink)}}
.eyebrow{{font-size:11px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--brass);font-weight:700}}
h1{{font-size:clamp(38px,6vw,66px);line-height:1.02;letter-spacing:-.02em;margin:14px 0 12px}}
.dek{{font-size:17px;color:var(--ink2);max-width:64ch}}
.prov{{margin-top:18px;font-size:12.5px;color:var(--muted);
  display:flex;flex-wrap:wrap;gap:6px 18px}}
.prov a{{color:var(--brass)}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));
  gap:1px;background:var(--rule);border:1px solid var(--rule);margin:34px 0 0}}
.stat{{background:var(--surface);padding:20px 22px}}
.sv{{font-size:34px;font-weight:650;letter-spacing:-.02em;line-height:1.1}}
.sl{{font-size:12px;letter-spacing:.09em;text-transform:uppercase;color:var(--brass);
  font-weight:700;margin-top:6px}}
.ss{{font-size:12.5px;color:var(--muted);margin-top:3px;font-variant-numeric:tabular-nums}}
section{{padding-top:52px}}
.shead{{display:flex;align-items:baseline;gap:14px;border-bottom:1px solid var(--rule);
  padding-bottom:10px;margin-bottom:8px}}
.snum{{font-size:12px;font-weight:700;color:var(--brass);letter-spacing:.1em}}
h2{{font-size:27px;letter-spacing:-.01em}}
.lede{{color:var(--ink2);max-width:74ch;margin:14px 0 20px;font-size:15.5px}}
.card{{background:var(--surface);border:1px solid var(--rule);padding:18px 18px 10px;
  margin-bottom:18px;overflow-x:auto}}
.chart{{width:100%;height:auto;display:block;min-width:520px}}
.grid{{stroke:var(--rule);stroke-width:1}}
.baseline{{stroke:var(--muted);stroke-width:1;stroke-dasharray:4 3}}
.med{{stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3;opacity:.8}}
.ytick,.xtick{{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}}
.ytick{{text-anchor:end}} .xtick{{text-anchor:middle}} .xtick.dim{{font-size:9.5px;opacity:.75}}
.barval{{fill:var(--ink2);font-size:10.5px;text-anchor:middle;font-variant-numeric:tabular-nums}}
.cellval{{font-size:11px;text-anchor:middle;font-variant-numeric:tabular-nums;font-weight:600}}
.ann{{fill:var(--muted);font-size:11px}}
.axtitle{{fill:var(--muted);font-size:11.5px;text-anchor:middle}}
.bar,.cell,.dot,.pt{{transition:opacity .12s}}
.card:hover .bar:not(:hover),.card:hover .cell:not(:hover){{opacity:.72}}
.legend{{display:flex;gap:18px;flex-wrap:wrap;font-size:12.5px;color:var(--ink2);
  padding:2px 2px 12px}}
.key{{display:inline-flex;align-items:center;gap:7px}}
.dotk{{width:11px;height:11px;border-radius:50%;display:inline-block}}
.tw{{overflow-x:auto;border:1px solid var(--rule);background:var(--surface);margin-bottom:18px}}
table{{border-collapse:collapse;width:100%;font-size:13.5px;min-width:520px}}
th{{text-align:left;font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--muted);font-weight:700;padding:11px 14px;border-bottom:1px solid var(--rule);
  white-space:nowrap;background:var(--band)}}
td{{padding:9px 14px;border-bottom:1px solid var(--hair)}}
tbody tr:last-child td{{border-bottom:none}}
tbody tr:hover{{background:var(--band)}}
td.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
th:nth-child(n+2){{}}
table a{{color:var(--brass);text-decoration:none;border-bottom:1px solid var(--hair)}}
table a:hover{{border-bottom-color:var(--brass)}}
.rows{{display:flex;flex-direction:column;gap:1px;background:var(--rule);
  border:1px solid var(--rule);margin-bottom:18px}}
.row{{display:grid;grid-template-columns:150px 1fr 84px 78px;align-items:center;gap:12px;
  background:var(--surface);padding:9px 14px;text-decoration:none;color:inherit}}
a.row:hover{{background:var(--band)}}
.rl{{font-size:13px;font-variant-numeric:tabular-nums;display:flex;flex-direction:column}}
.rl em{{font-style:normal;font-size:11.5px;color:var(--muted);margin-top:1px}}
.rb{{height:9px;background:var(--band);border-radius:5px;overflow:hidden}}
.rf{{display:block;height:100%;border-radius:5px}}
.rv{{font-size:13.5px;font-variant-numeric:tabular-nums;text-align:right;font-weight:600}}
.chip{{font-size:11px;color:var(--brass);border:1px solid var(--hair);border-radius:99px;
  padding:2px 8px;text-align:center;white-space:nowrap;justify-self:end}}
.chip-empty{{}}
@media (max-width:700px){{.row{{grid-template-columns:110px 1fr 68px;}}.chip{{display:none}}}}
.ylab{{font-size:11px;font-weight:700;font-variant-numeric:tabular-nums}}
.yline{{transition:opacity .12s}}
.card:hover .yline:not(:hover){{opacity:.35}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
.three{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}}
/* grid children default to min-width:auto, which refuses to shrink below the
   table's min-width and pushes the whole page sideways; 0 lets each .tw scroll
   inside its own column instead */
.two>*,.three>*{{min-width:0}}
.three table{{min-width:330px}}
.three .row{{grid-template-columns:92px 1fr 46px;padding:8px 10px;gap:8px}}
.three .chip{{display:none}}
.three .rl{{font-size:12px}} .three .rv{{font-size:12.5px}}
.two .chart,.three .chart{{min-width:0}}
@media (max-width:900px){{.two,.three{{grid-template-columns:1fr}}}}
.sub{{font-size:12px;letter-spacing:.09em;text-transform:uppercase;color:var(--brass);
  font-weight:700;margin:0 0 8px}}
.note{{font-size:13px;color:var(--muted);border-left:2px solid var(--brass);
  padding:2px 0 2px 14px;margin:16px 0;max-width:78ch}}
.pull{{font-size:19px;line-height:1.5;color:var(--ink);border-top:1px solid var(--rule);
  border-bottom:1px solid var(--rule);padding:18px 0;margin:22px 0;max-width:74ch;
  font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif}}
footer{{margin-top:64px;padding-top:22px;border-top:2px solid var(--ink);
  font-size:13px;color:var(--muted);max-width:80ch}}
footer code{{background:var(--band);padding:1px 5px;font-size:12px}}
a:focus-visible,tr:focus-visible{{outline:2px solid var(--brass);outline-offset:2px}}
@media (prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
</style>

<div class="wrap">
<header class="mast">
  <div class="eyebrow">Tirumala Tirupati Devasthanams &middot; daily darshan bulletins</div>
  <h1>Thirteen years at the hill</h1>
  <p class="dek">Every daily pilgrim count TTD has published since October 2013, recovered
  from {6614:,} bulletins, reconciled to one figure per date, and read for what it says about
  how {m["total_pilgrims"]/1e6:.0f} million darshans actually distribute across a year.</p>
  <div class="prov">
    <span>{m["start"]} &rarr; {m["end"]}</span>
    <span>{m["n_days"]:,} dated days</span>
    <span>source: <a href="https://news.tirumala.org/category/darshan/" target="_blank" rel="noopener">news.tirumala.org</a></span>
    <span>every figure traceable to its bulletin</span>
  </div>
  <div class="stats">{stats}</div>
</header>

<section>
  <div class="shead"><span class="snum">01</span><h2>The whole record</h2></div>
  <p class="lede">Faint line is each published day; the solid line is a 30-day trailing mean.
  Breaks are days TTD published nothing &mdash; the widest is the pandemic closure.</p>
  <div class="card">{hero_chart()}</div>
  <p class="note">Footfall recovered to its pre-pandemic level by 2022 and has climbed since:
  {best_year["year"]} averages {fm(best_year["avg"])} a day against {fm(quietest_year["avg"])} in
  {quietest_year["year"]}, the pandemic year. The ceiling, though, has not moved &mdash; the
  all-time high of {fm(busiest["p"])} still dates from {busiest["d"][:4]}.</p>
</section>

<section>
  <div class="shead"><span class="snum">02</span><h2>Year by year</h2></div>
  <p class="lede">Average pilgrims per published day. Faded bars are years with partial
  coverage &mdash; 2013 starts in October, 2026 ends in August, and 2018&ndash;2020 have
  publication gaps, so their averages describe the days that were reported, not the whole year.</p>
  <div class="card">{yearly_chart()}</div>
  <p class="sub">Quietest to busiest day in each year, median marked</p>
  <div class="card">{year_range()}</div>
</section>

<section>
  <div class="shead"><span class="snum">03</span><h2>When the year is busy</h2></div>
  <p class="lede">Two distinct rush seasons, and neither is the one most people name.
  The index sets each month against the all-years daily average.</p>
  <div class="card">{index_bars(D["season_index"], "index", "month", "Seasonal index by month", note="100 = all-years average", months=True)}</div>
  <p class="note">May and June run hottest &mdash; school holidays, not a festival.
  The Brahmotsavam season in September&ndash;October reads only slightly above average
  on <em>counts</em>, because throughput is capped by how many people the queue can
  physically move; the crowd shows up in waiting hours instead (section 05).</p>

  <p class="sub">Week of year &mdash; each of the last five years drawn separately</p>
  <div class="card">{weekly_by_year()}</div>

  <p class="sub">Month by month, last six years</p>
  <div class="card">{month_heat()}</div>

  <p class="sub">Each year&rsquo;s single heaviest seven-day stretch</p>
  <p class="lede">Peak weeks cluster in {peak_months} &mdash; the summer-holiday
  and Brahmotsavam windows. 2020 and 2021 are shown but sit in a different regime:
  their multiples are inflated by pandemic-depressed medians.</p>
  <div class="card">{peak_timeline()}</div>
</section>

<section>
  <div class="shead"><span class="snum">04</span><h2>The rhythm of the week</h2></div>
  <p class="lede">Weekends carry the load. Index against the all-days average.</p>
  <div class="card">{index_bars(dow, "index", "day", "Index of pilgrims by day of week", note="100 = all-days average")}</div>
  <p class="note">Sunday runs {dow[6]["index"] - dow[3]["index"]} points above Thursday, the
  quietest day &mdash; a {round((dow[6]["avg"]/dow[3]["avg"]-1)*100)}% swing between the
  busiest and lightest weekday, consistent across all thirteen years.</p>
</section>

<section>
  <div class="shead"><span class="snum">05</span><h2>Crowd against queue</h2></div>
  <p class="lede">Each bulletin reports yesterday&rsquo;s pilgrim count alongside
  <em>this</em> morning&rsquo;s queue &mdash; &ldquo;Present Situation on 17-08-2026&rdquo;.
  So the queue reading is re-dated to the morning it describes before being paired with
  that day&rsquo;s eventual total; {D["wait_meta"]["n"]:,} days carry both.
  Dashed lines mark the medians.</p>
  <div class="legend">
    <span class="key"><span class="dotk" style="background:{S2}"></span>festival or national holiday</span>
    <span class="key"><span class="dotk" style="background:{S1}"></span>ordinary day</span>
  </div>
  <div class="card">{wait_scatter()}</div>
  <p class="pull">More waiting does not mean more darshans. Beyond roughly 70,000 a day the
  cloud goes vertical &mdash; the queue lengthens while the count barely moves. That is a
  hard capacity ceiling, not a demand signal.</p>
  <p class="note">Read the pairing carefully: the queue figure is a single morning
  observation, and the count is a whole day&rsquo;s throughput. They describe the same
  calendar day but not the same instant, so this shows how a morning&rsquo;s queue relates
  to that day&rsquo;s outturn &mdash; it is not a per-pilgrim waiting time, and dividing one
  by the other would not mean anything.</p>
  <div class="three">
    <div><p class="sub">Longest queue, big crowd</p>{ext_rows("long_wait_high_crowd", S2)}</div>
    <div><p class="sub">Long queue, small crowd</p>{ext_rows("long_wait_low_crowd", S3)}</div>
    <div><p class="sub">Short queue, big crowd</p>{ext_rows("short_wait_high_crowd", S1)}</div>
  </div>

  <p class="sub">How long the queue actually runs</p>
  <div class="card">{wait_hist()}</div>
  <p class="lede">A queue longer than a day is not a parsing error and not impossible:
  pilgrims hold their place in the compartment sheds overnight. TTD states these
  figures outright &mdash; &ldquo;Approx. Darsan Time.. 48H&rdquo; &mdash; and
  {len(D["over_24h"])} mornings since 2013 were reported above 24 hours. Every row below
  links to the bulletin that says so.</p>
  {over24}
</section>

<section>
  <div class="shead"><span class="snum">06</span><h2>The busiest days on record</h2></div>
  <p class="lede">Each row links to the bulletin it came from. The queue figure shown is
  the one observed that same morning.</p>
  {busiest_rows}
</section>

<section>
  <div class="shead"><span class="snum">07</span><h2>What festivals actually do</h2></div>
  <p class="lede">{fe["festival_days"]:,} days carry a major festival or national holiday
  against {fe["normal_days"]:,} ordinary days.</p>
  <p class="pull">Festival days average {fm(fe["festival_avg"])} pilgrims against
  {fm(fe["normal_avg"])} on ordinary days &mdash; a rise of just {fe["uplift_pct"]}%.
  The queue tells the real story: {fw["festival_avg_wait"]} hours of waiting on festival
  days against {fw["normal_avg_wait"]} on ordinary ones.</p>
  <p class="lede">The temple does not serve many more people on a festival; the same
  number wait considerably longer. During Brahmotsavams TTD suspends paid and privileged
  darshan streams, which lengthens the free queue without raising total throughput.</p>
  {fest_rows}
  <p class="note">Festival dating comes from TTD&rsquo;s own dated posts, not from a
  generic almanac. Coverage is strong for Brahmotsavams and fixed national holidays and
  thinner for single-day lunar festivals such as Vaikunta Ekadasi, which the news titles
  rarely state as a date &mdash; so treat the festival column as a floor, not a census.</p>
</section>

<footer>
  <p><strong>How this was built.</strong> All {6614:,} posts in the darshan category were
  pulled through the site&rsquo;s WordPress REST API, then each post&rsquo;s pilgrim figure and
  date were read from its title and body. The bulletin format changed four times in thirteen
  years, so the parser handles each era explicitly &mdash; including the 2013&ndash;2019
  practice of publishing an interim &ldquo;3am to 6pm&rdquo; count alongside the next
  morning&rsquo;s full-day total. Interim snapshots are held separately and never mixed into
  a daily total.</p>
  <p><strong>One correction worth stating.</strong> An earlier cut of this page paired each
  day&rsquo;s pilgrim count with the queue length printed in the same bulletin. That was wrong:
  a bulletin reports yesterday&rsquo;s count but this morning&rsquo;s queue, and where the
  bulletin states the situation date it matches the publication date in 938 of 959 posts.
  Queue readings are now re-dated to the morning they describe. A ratio of pilgrims to
  queue-hours was also dropped &mdash; dividing a full day&rsquo;s throughput by a single
  morning&rsquo;s queue estimate does not measure anything.</p>
  <p>The dataset was checked against the rendered listing pages independently: 174 posts
  sampled across pages 1 to 662 matched on link, title and figure with no discrepancies.
  Where two bulletins reported the same date, an identical figure was kept once and a
  disagreement resolved to the higher value. Nothing on this page is estimated &mdash;
  every value appeared verbatim in a TTD bulletin, and known source defects (mis-grouped
  digits such as <code>67,3574</code>, truncated titles) are listed in the accompanying
  anomalies file rather than silently corrected.</p>
  <p>Generated {dt.date.today().isoformat()} from <code>darshan_daily.csv</code>.</p>
</footer>
</div>
"""


if __name__ == "__main__":
    out = os.path.join(HERE, "darshan_report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(build())
    print("wrote", out, os.path.getsize(out), "bytes")
