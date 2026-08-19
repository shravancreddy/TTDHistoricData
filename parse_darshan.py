"""
Parse the cached darshan posts into a per-date pilgrim series.

Reads all_posts.json (produced by fetch_darshan.py) and writes:
  darshan_daily.csv        one row per calendar date (full-day totals)
  darshan_all_records.csv  every parsed record, incl. partial-day snapshots
  darshan_duplicates_resolved.csv  audit log of how repeated/conflicting dates
                           were settled (same value kept; disagreement -> highest)
  darshan_anomalies.csv    suspicious / unparseable / out-of-range records
  darshan_report.txt       human-readable summary

Nothing is invented: a value appears only if it was literally present in the
post's title or body. Dates that had to be inferred are marked as such in the
date_source column so they can be audited.
"""

import csv
import datetime as dt
import json
import os
import re
import statistics
import unicodedata
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "all_posts.json")

ENTITIES = {
    "&#8230;": "...", "&hellip;": "...", "&amp;": "&", "&nbsp;": " ",
    "&#8211;": "-", "&#8212;": "-", "&ndash;": "-", "&mdash;": "-",
    "&#8217;": "'", "&#8216;": "'", "&rsquo;": "'", "&lsquo;": "'",
    "&#8220;": '"', "&#8221;": '"', "&quot;": '"', "&#039;": "'",
    "&#8242;": "'", "&lt;": "<", "&gt;": ">", "&#44;": ",",
}

# The feed spells it darshan / dharshan / darshana / darshanam / Darshanam.
# A trailing \b is wrong here: "Darshanam" has no boundary after "darshan".
DARSHAN = r"(?:da|dha)rshan\w{0,3}"

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "febr": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))


def clean(html):
    """HTML fragment -> flat single-spaced text."""
    if not html:
        return ""
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", " \n ", s)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    for a, b in ENTITIES.items():
        s = s.replace(a, b)
    s = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))) if int(m.group(1)) < 0x110000 else " ", s)
    s = unicodedata.normalize("NFKC", s)
    # The feed is littered with U+FFFD / stray control chars; drop them.
    s = "".join(ch if (ch.isprintable() or ch in "\n\t") else " " for ch in s)
    s = s.replace("�", " ")
    return re.sub(r"[ \t]+", " ", s).strip()


def flat(s):
    return re.sub(r"\s+", " ", s).strip()


def to_int(raw):
    """'64,628' / '11, 978' / '1,00,246' -> int. None if implausible."""
    if raw is None:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# count extraction
# --------------------------------------------------------------------------
# Either digit-grouped (97,014 / 11, 978 / 1,00,246) or a plain 3-7 digit run.
# Ordering matters: a bare \d{1,3} branch would truncate "9582" to "958".
# A comma may be followed by a space ("11, 978"), but a dot separator may not be
# spaced -- otherwise a repeated headline ("18,941 . 18,941") is swallowed whole
# and rejected as a 10-digit number.
NUM = r"(?:\d{1,3}(?:,\s?\d{2,3}|\.\d{3})+|\d{3,7})"

# Clock times inside titles ("from 5:45 am till 9:00 pm on 04-07-2020: 11, 978")
# carry colons that would otherwise be mistaken for the count separator. Rewrite
# them to dots first so the count patterns can stay anchored to the FIRST colon.
# Binding to the last colon instead is not an option: it runs past the count and
# latches onto the following field ("Tonsures: 35,825").
TIME_COLON = re.compile(r"(?i)\b(\d{1,2}):(\d{2})(\s*(?:am|pm|noon|hrs|hours)\b)")


def defuse_times(text):
    return TIME_COLON.sub(r"\1.\2\3", text)


COUNT_PATTERNS = [
    # "Total pilgrims who had darshan on 01.07.2022: 64,628"
    (r"(?i)total\s+(?:number\s+of\s+)?pilgrims?\s+who\s+had\s+darshan[^:]{0,90}?:\s*("
     + NUM + r")", "total_stated"),
    # "Total Number of Pilgrims who had darshan on 12:06:20- 6015" (dash, and a
    # colon-punctuated date that rules out a [^:] gap)
    (r"(?i)total\s+(?:number\s+of\s+)?pilgrims?\s+who\s+had\s+darshan.{0,45}?-\s*("
     + NUM + r")", "total_stated"),
    # "TTD records highest number of pilgrims today after resuming Darshan
    #  from June 11 on 05.09.2020: 13,486"
    (r"(?i)records\s+highest\s+number\s+of\s+pilgrims[^:]{0,90}?:\s*(" + NUM + r")", "total_stated"),
    # "Pilgrims who had darshan from 5.45am till 9.00pm on 04-07-2020: 11, 978"
    (r"(?i)pilgrims?\s+who\s+had\s+darshan[^:]{0,90}?:\s*(" + NUM + r")", "total_stated"),
    # "About 48,658 pilgrims had Srivari Darshanam on November 18"
    (r"(?i)about\s*(" + NUM + r")\s*\.?\s*pilgrims?\s+had\s+(?:srivari\s+)?" + DARSHAN, "about"),
    # "TOTAL PILGRIMS HAD DARSHAN: 46,722"
    (r"(?i)total\s+pilgrims?\s+had\s+" + DARSHAN + r"\s*[:\-]\s*(" + NUM + r")", "total_stated"),
    # generic "<n> pilgrims had darshan"
    (r"(?i)(" + NUM + r")\s*pilgrims?\s+had\s+(?:srivari\s+)?" + DARSHAN, "generic"),
    # "pilgrims had darshan ... : 64,628"
    (r"(?i)pilgrims?\s+had\s+(?:srivari\s+)?" + DARSHAN + r"[^:]{0,60}?:\s*(" + NUM + r")", "generic"),
]

# A stated "Total pilgrims ..." is a day total even when a time window is quoted.
TOTAL_PHRASE = re.compile(r"(?i)total\s+pilgrims?\s+(?:who\s+)?had\s+darshan")


def extract_count(text, want_flag=False):
    """(value, kind, evidence[, malformed]).

    `malformed` marks a source typo such as "About 67,3574 pilgrims" or
    "1,07853", where a digit still trails the correctly-grouped match. The
    figure is unrecoverable without guessing, so it is surfaced for review
    rather than silently trusted.
    """
    text = defuse_times(text)
    for pat, kind in COUNT_PATTERNS:
        m = re.search(pat, text)
        if m:
            v = to_int(m.group(1))
            if v is not None and 100 <= v <= 400000:
                # A digit still touching either end of the match means the
                # source number was mis-grouped and the regex re-anchored
                # inside it ("67,3574" -> 3574, "1,07853" -> 7853).
                tail = text[m.end(1):m.end(1) + 1]
                head = text[m.start(1) - 1:m.start(1)] if m.start(1) else ""
                bad = tail.isdigit() or head.isdigit() or head in (",", ".")
                ev = flat(m.group(0))[:150]
                return (v, kind, ev, bad) if want_flag else (v, kind, ev)
    return (None, None, None, False) if want_flag else (None, None, None)


# --------------------------------------------------------------------------
# date extraction
# --------------------------------------------------------------------------
def mk_date(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def infer_year(month, day, post_dt):
    """Month/day with no year -> pick the year nearest the post date."""
    best = None
    for y in (post_dt.year - 1, post_dt.year, post_dt.year + 1):
        cand = mk_date(y, month, day)
        if cand is None:
            continue
        # darshan date should sit at or just before the post date
        delta = (post_dt.date() - cand).days
        score = abs(delta - 1)          # typical lag is 1 day
        if delta < -2:                  # future beyond tolerance
            score += 500
        if best is None or score < best[0]:
            best = (score, cand)
    return best[1] if best else None


def extract_date(text, post_dt):
    """Return (date, source_label). Only explicit in-text dates here."""
    text = defuse_times(text)
    # 1) explicit numeric date attached to a darshan phrase
    m = re.search(
        r"(?i)" + DARSHAN + r"\s*(?:on|from[^\n]{0,40}?on|till[^\n]{0,40}?on)?\s*"
        r"(\d{1,2})\s*[\.\-/:]\s*(\d{1,2})\s*[\.\-/:]\s*(\d{2,4})", text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        got = mk_date(y, mo, d)
        if got:
            return got, "explicit_dmy"

    # 2) explicit "on <Month> <Day>[, YYYY]" following a darshan phrase
    m = re.search(
        r"(?i)" + DARSHAN + r"[^\.\n]{0,70}?\bon\s*(" + MONTH_RE +
        r")\.?\s*(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})?", text)
    if m:
        mo = MONTHS[m.group(1).lower()]
        d = int(m.group(2))
        if m.group(3):
            got = mk_date(int(m.group(3)), mo, d)
            if got:
                return got, "explicit_mdy"
        got = infer_year(mo, d, post_dt)
        if got:
            return got, "month_day_year_inferred"

    # 3) darshan phrase followed directly by "<Month> <Day>" (missing "on")
    m = re.search(
        r"(?i)" + DARSHAN + r"[^\.\n]{0,50}?\b(" + MONTH_RE +
        r")\.?\s*(\d{1,2})(?:st|nd|rd|th)?\b", text)
    if m:
        got = infer_year(MONTHS[m.group(1).lower()], int(m.group(2)), post_dt)
        if got:
            return got, "month_day_year_inferred"

    # 4) any bare numeric date in the text (e.g. VQC situation line)
    m = re.search(r"\b(\d{1,2})\s*[\.\-/]\s*(\d{1,2})\s*[\.\-/]\s*(\d{4})\b", text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        got = mk_date(y, mo, d)
        if got:
            return got, "loose_dmy"

    return None, None


# --------------------------------------------------------------------------
# supplementary fields
# --------------------------------------------------------------------------
def money_cr(text):
    """Hundi collection normalised to rupees crore."""
    m = re.search(r"(?i)(?:hundi\s*kanukalu|hundi|parakamani)\s*[:\-\.]*\s*"
                  r"(?:rs\.?\s*)?([\d,\.]+)\s*(cr|crore|crores|lakh|lakhs|lac|lacs|l\b)?", text)
    if not m:
        return None
    try:
        val = float(re.sub(r"[^\d\.]", "", m.group(1)).rstrip("."))
    except ValueError:
        return None
    unit = (m.group(2) or "cr").lower()
    if unit.startswith(("lakh", "lac", "l")):
        val /= 100.0
    return round(val, 4)


def lac(text, *labels):
    for lab in labels:
        m = re.search(r"(?i)(?:" + lab + r")\s*[:\-\.]*\s*([\d,\.]+)\s*(cr|crore|lakh|lakhs|lac|lacs)?", text)
        if m:
            try:
                val = float(re.sub(r"[^\d\.]", "", m.group(1)).rstrip("."))
            except ValueError:
                continue
            unit = (m.group(2) or "").lower()
            if unit.startswith("cr"):
                val *= 100.0
            return round(val, 4)
    return None


def simple_int(text, label, lo=0, hi=200000):
    # label must be grouped: a bare alternation would swallow the capture group.
    m = re.search(r"(?i)(?:" + label + r")\s*[:\-\.]*\s*(" + NUM + r")", text)
    if m:
        v = to_int(m.group(1))
        if v is not None and lo <= v <= hi:
            return v
    return None


def tonsures(text):
    # modern single figure
    v = simple_int(text, r"tonsures?")
    if v is not None:
        return v
    # 2020 style: Male / Female / Total block
    m = re.search(r"(?i)tonsures?.{0,120}?total\s*[:\-]\s*(" + NUM + r")", text, re.S)
    if m:
        return to_int(m.group(1))
    return None


# --------------------------------------------------------------------------
# queue detail: compartments and waiting hours per darshan class
# --------------------------------------------------------------------------
# 2013-2019: "Sarva Darshan (Free darshan)- 8 compartments / 6 hours;
#             Divya Darshan (Footpath darshan) 2 compartments / 4hours and
#             Special Entry Darshan (Rs.300) after 10am."
# 2020+    : "Sarvadarshanam (without SSD Tokens)... 18 H"
# The queue can also be reported as a state rather than a count -- "Line
# Outside", "Direct", "Closed" -- which matters more than a missing number.
QUEUE_STOP = re.compile(
    r"(?i);|,|\band\s+special\b|\bspecial\s+entry\b|\bdivya\b|\btotal\s+pilgrims\b|"
    r"\bcurrent\s+situation\b|\bwaiting\s+compartments\b")

HOURS_RE = re.compile(r"(?i)(\d{1,3})\s*(?:-\s*(\d{1,3})\s*)?(?:h\b|hr|hrs|hour|hours)")
COMPART_RE = re.compile(r"(?i)(\d{1,3})\s*compartments?")


def _segment(text, label_re, span=110):
    m = re.search(label_re, text)
    if not m:
        return None
    chunk = text[m.end(): m.end() + span]
    stop = QUEUE_STOP.search(chunk)
    if stop:
        chunk = chunk[:stop.start()]
    return chunk


def queue_detail(text, which):
    """(compartments, hours, status) for 'sarva' or 'divya'."""
    if which == "sarva":
        label = r"(?i)sarva\s*d[ha]?[ar]*rshan\w*"
    else:
        label = r"(?i)divya\s*d[ha]?[ar]*rshan\w*"
    seg = _segment(text, label)
    if seg is None:
        return None, None, None

    comp = COMPART_RE.search(seg)
    comp_n = int(comp.group(1)) if comp else None

    hrs = HOURS_RE.search(seg)
    # a range ("10-12H") is recorded at its upper bound
    hours = int(hrs.group(2) or hrs.group(1)) if hrs else None
    if hours is not None and not 0 <= hours <= 48:
        hours = None

    low = seg.lower()
    if re.search(r"line\s*out|outside\s*line|out\s*side\s*line", low):
        status = "line outside"
    elif "direct" in low:
        status = "direct"
    elif "closed" in low:
        status = "closed"
    elif comp_n is not None:
        status = "compartments"
    elif hours is not None:
        status = "hours only"
    else:
        status = None
    return comp_n, hours, status


def special_entry_status(text):
    seg = _segment(text, r"(?i)special\s*entry\s*d[ha]?[ar]*rshan\w*", span=70)
    if seg is None:
        return None
    seg = re.sub(r"^\s*\([^)]*\)\s*", " ", seg)          # drop "(Rs.300)"
    seg = flat(seg).strip(" .-:;")
    return seg[:60] or None


def darshan_hours(text):
    m = re.search(r"(?i)(?:approx\.?\s*)?dars[ha]*[ae]?n\s*time[^\d]{0,80}?(\d{1,2})\s*(?:h|hr|hrs|hours)\b", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(?i)sarva\s*dars?h?an[^\d]{0,60}?(\d{1,2})\s*(?:h|hr|hrs|hours)\b", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(?i)upto\s+(\d{1,2})\s*hours", text)
    if m:
        return int(m.group(1))
    return None


def waiting_compartments(text):
    m = re.search(r"(?i)waiting\s*compartments?\s*[:\-\.]*\s*([^\n]{0,90})", text)
    if m:
        v = flat(m.group(1)).strip(" .-:")
        v = re.sub(r"(?i)\bapprox.*$", "", v).strip(" .-:")
        if v:
            return v[:90]
    m = re.search(r"(?i)compartments\s+waiting\s+in\s+vqc[^\d]{0,20}(\d{1,3})", text)
    if m:
        return f"VQC-II: {int(m.group(1))} compartments"
    return None


# Interim windows appear as "from 3am to 6pm", "between 3am to 6pm" and bare
# "Srivari Darshan 3am to 6pm on May 26", so the leading preposition is not
# required. The opening endpoint must carry am/pm (that anchors it as a clock
# time); the closing one need not, because the feed contains typos like
# "from 3am to 9m".
# A bulletin reports YESTERDAY's pilgrim count but TODAY's queue: "...had darshan
# on 16.08.2026: 97,014 / Present Situation on 17-08-2026: ... Approx. Darshan
# Time .. 18 H", and the 2013-2019 wording "waiting hours detail by 5am" is the
# same thing without a date. Verified against the feed: where the situation date
# is stated it equals the publication date in 938 of 959 posts. So the queue
# figures belong to the POST date, not to the darshan date, and pairing them with
# the same row's pilgrim count compares a full day against the next morning.
SITUATION_DATE = re.compile(
    r"(?i)(?:present\s+situation|v\.?q\.?c[\s\.]*situation[^\n]{0,60}?)\bon\s*"
    r"(\d{1,2})[-./](\d{1,2})[-./](\d{2,4})")


def situation_date(text, post_dt):
    m = SITUATION_DATE.search(text)
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        d = mk_date(y, int(m.group(2)), int(m.group(1)))
        # a stated date far from publication is a source typo; fall back
        if d and abs((d - post_dt.date()).days) <= 3:
            return d, "stated"
    return post_dt.date(), "post_date"


PARTIAL_RE = re.compile(
    r"(?i)\b\d{1,2}(?:[:\.]\d{2})?\s*(?:am|pm|noon)\s*(?:to|till|until|-)\s*"
    r"\d{1,2}(?:[:\.]\d{2})?\s*(?:am|pm|noon|m)?")


def main():
    with open(SRC, encoding="utf-8") as f:
        posts = json.load(f)

    records = []
    for p in posts:
        title = clean(p["title"]["rendered"])
        body = clean(p["content"]["rendered"])
        # Some posts repeat the title as the first body line; joining is safe
        # because every extractor anchors on an explicit label.
        text = flat(title + " . " + body)
        post_dt = dt.datetime.strptime(p["date"][:19], "%Y-%m-%dT%H:%M:%S")

        count, ckind, cev, cbad = extract_count(text, want_flag=True)

        # --- interim-window classification (needed before dating) ----------
        partial = bool(PARTIAL_RE.search(title))
        if not partial and PARTIAL_RE.search(text) and count is not None:
            # only treat as partial when the time-range sits next to the count
            m = PARTIAL_RE.search(text)
            cm = re.search(re.escape(cev), text) if cev else None
            if cm is None or abs(m.start() - cm.start()) < 200:
                partial = True
        # An explicit "Total pilgrims ..." normally marks a day total -- but the
        # 2019 VQC bulletins say "TOTAL PILGRIMS HAD DARSHAN: 46,722" inside a
        # 6pm snapshot, so this override must not fire when the title itself
        # advertises an interim window.
        if TOTAL_PHRASE.search(text) and not PARTIAL_RE.search(title):
            partial = False

        # --- dating --------------------------------------------------------
        # Title and body sometimes disagree (title "on May 2", body "on May 1"
        # on a post published May 2 06:38). Rather than always trusting the
        # title, prefer whichever date gives a plausible publication lag: a
        # full-day total lands the next morning, an interim window the same day.
        d_title, s_title = extract_date(flat(title), post_dt)
        d_body, s_body = extract_date(flat(body), post_dt)
        expected = 0 if partial else 1

        def lag_score(cand):
            lag = (post_dt.date() - cand).days
            return (abs(lag - expected), 0 if lag >= 0 else 1)

        cands = []
        if d_title:
            cands.append((d_title, s_title, "title"))
        if d_body:
            cands.append((d_body, s_body, "body"))
        date_mismatch = bool(d_title and d_body and d_title != d_body)
        if cands:
            best = min(cands, key=lambda c: lag_score(c[0]))
            date, dsrc = best[0], f"{best[1]}@{best[2]}"
        else:
            date, dsrc = None, None

        queue_only = count is None and re.search(r"(?i)compartment|waiting|line outside", text) is not None

        sarva_c, sarva_h, sarva_s = queue_detail(text, "sarva")
        divya_c, divya_h, divya_s = queue_detail(text, "divya")
        obs_date, obs_src = situation_date(text, post_dt)

        records.append({
            "post_id": p["id"],
            "post_datetime": post_dt.isoformat(sep=" "),
            "post_date": post_dt.date(),
            "darshan_date": date,
            "date_source": dsrc,
            "date_title_body_mismatch": date_mismatch,
            "date_in_title": d_title,
            "date_in_body": d_body,
            "pilgrims": count,
            "count_kind": ckind,
            "count_malformed_in_source": cbad,
            "is_partial_day": partial,
            "queue_status_only": queue_only,
            "tonsures": tonsures(text),
            "hundi_cr": money_cr(text),
            "laddu_lakh": lac(text, r"laddu\s*sale", r"laddus?"),
            "annaprasadam_lakh": lac(text, r"annaprasadams?", r"anna\s*prasadams?"),
            "hospital": simple_int(text, r"aswini\s*hospital|aswinihospital|hospital", 0, 50000),
            "darshan_wait_hours": darshan_hours(text),
            "waiting_compartments": waiting_compartments(text),
            "queue_observed_date": obs_date,
            "queue_observed_src": obs_src,
            "sarva_compartments": sarva_c,
            "sarva_hours": sarva_h,
            "sarva_status": sarva_s,
            "divya_compartments": divya_c,
            "divya_hours": divya_h,
            "divya_status": divya_s,
            "special_entry_status": special_entry_status(text),
            "title": title[:220],
            "link": p["link"],
            "evidence": cev,
        })

    # ---- infer missing dates from neighbours -----------------------------
    # Posts are chronological, so a missing darshan date is filled from the
    # dominant post-date -> darshan-date lag of its nearest dated neighbours.
    records.sort(key=lambda r: (r["post_datetime"], r["post_id"]))
    known = [(i, r) for i, r in enumerate(records) if r["darshan_date"]]
    lags = [(r["post_date"] - r["darshan_date"]).days for _, r in known]

    for i, r in enumerate(records):
        if r["darshan_date"] or r["pilgrims"] is None:
            continue  # queue-only posts do not need a date
        near = []
        for j in range(max(0, i - 6), min(len(records), i + 7)):
            rj = records[j]
            if rj["darshan_date"] and rj["is_partial_day"] == r["is_partial_day"]:
                near.append((rj["post_date"] - rj["darshan_date"]).days)
        lag = statistics.mode(near) if near else (statistics.mode(lags) if lags else 1)
        if not 0 <= lag <= 3:
            lag = 1
        r["darshan_date"] = r["post_date"] - dt.timedelta(days=lag)
        r["date_source"] = f"inferred_from_neighbours(lag={lag})"

    # ---- promote sole-report days ----------------------------------------
    # In 2013-2019 an interim "from 3am to 6pm" post sits alongside a separate
    # next-morning full total, so it is genuinely partial. During the 2020 COVID
    # restrictions the windowed post ("from 5:45am till 9:00pm") was the day's
    # ONLY report and therefore is the day total. Distinguish by evidence, not
    # by era: promote a partial only when no full-day post exists for that date.
    for r in records:
        r["promoted_from_partial"] = False
    per_date = defaultdict(list)
    for r in records:
        if r["pilgrims"] is not None and r["darshan_date"]:
            per_date[r["darshan_date"]].append(r)
    for d, rs in per_date.items():
        if rs and all(r["is_partial_day"] for r in rs):
            best = max(rs, key=lambda r: (r["pilgrims"], r["post_datetime"]))
            best["is_partial_day"] = False
            best["promoted_from_partial"] = True

    # ---- split into series ----------------------------------------------
    counted = [r for r in records if r["pilgrims"] is not None and r["darshan_date"]]
    full = [r for r in counted if not r["is_partial_day"]]
    partials = [r for r in counted if r["is_partial_day"]]

    by_date = defaultdict(list)
    for r in full:
        by_date[r["darshan_date"]].append(r)

    anomalies = []
    resolved = []

    # ---- one authoritative row per date ---------------------------------
    # Resolution rules, per the brief:
    #   * repeated posts carrying the SAME figure -> keep it, drop the duplicate
    #   * posts disagreeing on the figure         -> keep the HIGHEST
    # Either way the date is settled here, so it no longer needs review; the
    # decision is written to darshan_duplicates_resolved.csv as an audit trail.
    daily = {}
    for d, rs in by_date.items():
        vals = {r["pilgrims"] for r in rs}
        if len(rs) > 1:
            agree = len(vals) == 1
            chosen = max(rs, key=lambda r: (r["pilgrims"], r["post_datetime"]))
            best = dict(chosen)
            best["resolution"] = ("duplicate_same_value" if agree
                                  else "conflict_took_highest")
            resolved.append({
                "darshan_date": d,
                "values_seen": ", ".join(f"{v:,}" for v in sorted(vals, reverse=True)),
                "values_agree": "yes" if agree else "no",
                "chosen_value": chosen["pilgrims"],
                "spread": (max(vals) - min(vals)) if len(vals) > 1 else 0,
                "n_posts": len(rs),
                "resolution": best["resolution"],
                "post_ids": ", ".join(str(r["post_id"]) for r in sorted(
                    rs, key=lambda r: r["post_datetime"])),
                "chosen_post_id": chosen["post_id"],
                "chosen_link": chosen["link"],
            })
        else:
            best = dict(rs[0])
            best["resolution"] = "single_post"
        best["n_posts_for_date"] = len(rs)
        best["conflicting_values"] = len(vals) > 1
        daily[d] = best

    # ---- fill empty dates named by a mismatched title --------------------
    # When a post's title and body disagree on the date, the body wins (it is
    # the reliable half -- titles get truncated, "on May 26" -> "on May 2").
    # If the date the TITLE named holds no data at all, that record is also
    # written there so the otherwise-empty day is populated.
    gapfilled = []
    for r in records:
        if not r.get("date_title_body_mismatch") or r["pilgrims"] is None:
            continue
        td = r["date_in_title"]
        if not td or td in daily or r["is_partial_day"]:
            continue
        row = dict(r)
        row["darshan_date"] = td
        row["date_source"] = "title_date_gapfill"
        row["resolution"] = "gapfilled_from_title_date"
        row["n_posts_for_date"] = 1
        row["conflicting_values"] = False
        daily[td] = row
        gapfilled.append({
            "darshan_date": td, "pilgrims": r["pilgrims"],
            "body_date_used_elsewhere": r["darshan_date"],
            "post_id": r["post_id"], "title": r["title"], "link": r["link"],
        })

    dates = sorted(daily)
    # anomaly: unparsed posts that look like they should carry a count
    for r in records:
        if r["pilgrims"] is None and not r["queue_status_only"]:
            anomalies.append({
                "type": "no_count_extracted", "darshan_date": r["darshan_date"] or "",
                "value": "", "detail": "no pilgrim figure found in title or body",
                "post_id": r["post_id"], "post_datetime": r["post_datetime"],
                "title": r["title"], "link": r["link"],
            })
        if r.get("count_malformed_in_source"):
            anomalies.append({
                "type": "malformed_number_in_source", "darshan_date": r["darshan_date"],
                "value": r["pilgrims"],
                "detail": f"source digits are mis-grouped, figure unreliable: {r['evidence']}",
                "post_id": r["post_id"], "post_datetime": r["post_datetime"],
                "title": r["title"], "link": r["link"],
            })
        if r.get("date_title_body_mismatch") and r["pilgrims"] is not None:
            anomalies.append({
                "type": "title_body_date_mismatch", "darshan_date": r["darshan_date"],
                "value": r["pilgrims"],
                "detail": f"title says {r['date_in_title']}, body says {r['date_in_body']}; "
                          f"used {r['darshan_date']} ({r['date_source']})",
                "post_id": r["post_id"], "post_datetime": r["post_datetime"],
                "title": r["title"], "link": r["link"],
            })
        if r["darshan_date"] and r["pilgrims"] is not None:
            lag = (r["post_date"] - r["darshan_date"]).days
            if lag < 0 or lag > 4:
                anomalies.append({
                    "type": "implausible_post_lag", "darshan_date": r["darshan_date"],
                    "value": r["pilgrims"], "detail": f"post is {lag} days after darshan date",
                    "post_id": r["post_id"], "post_datetime": r["post_datetime"],
                    "title": r["title"], "link": r["link"],
                })

    vals = [daily[d]["pilgrims"] for d in dates]
    if vals:
        med = statistics.median(vals)
        for d in dates:
            v = daily[d]["pilgrims"]
            if v < 3000:
                anomalies.append({
                    "type": "very_low_count", "darshan_date": d, "value": v,
                    "detail": f"far below median {med:,.0f} - verify (possible partial/closure)",
                    "post_id": daily[d]["post_id"], "post_datetime": daily[d]["post_datetime"],
                    "title": daily[d]["title"], "link": daily[d]["link"]})
            elif v > 150000:
                anomalies.append({
                    "type": "very_high_count", "darshan_date": d, "value": v,
                    "detail": f"far above median {med:,.0f} - verify",
                    "post_id": daily[d]["post_id"], "post_datetime": daily[d]["post_datetime"],
                    "title": daily[d]["title"], "link": daily[d]["link"]})
        # day-over-day jumps
        for a, b in zip(dates, dates[1:]):
            if (b - a).days == 1:
                va, vb = daily[a]["pilgrims"], daily[b]["pilgrims"]
                if va and vb and (vb > va * 3 or vb * 3 < va) and abs(vb - va) > 20000:
                    anomalies.append({
                        "type": "day_over_day_jump", "darshan_date": b, "value": vb,
                        "detail": f"{va:,} on {a} -> {vb:,} on {b}",
                        "post_id": daily[b]["post_id"], "post_datetime": daily[b]["post_datetime"],
                        "title": daily[b]["title"], "link": daily[b]["link"]})

    # Same-date conflicts are no longer reported as anomalies: they are settled
    # by the highest-value rule above and logged in darshan_duplicates_resolved.csv.

    # ---- re-attach the queue snapshot to the morning it describes ---------
    # The queue fields carried on each record describe that bulletin's OWN
    # publication morning, which is the day after its pilgrim count. Re-key them
    # so row D holds the queue seen on the morning of D -- taken from the
    # bulletin published on D -- and record which bulletin it came from.
    QFIELDS = ["sarva_compartments", "sarva_hours", "sarva_status",
               "divya_compartments", "divya_hours", "divya_status",
               "special_entry_status", "darshan_wait_hours", "waiting_compartments"]
    qmap = {}
    for r in sorted(records, key=lambda r: r["post_datetime"]):
        if any(r.get(k) is not None for k in QFIELDS):
            qmap.setdefault(r["queue_observed_date"], r)

    for d, row in daily.items():
        for k in QFIELDS:                       # clear the mis-dated values
            row[k] = None
        q = qmap.get(d)
        if q:
            for k in QFIELDS:
                row[k] = q[k]
            row["queue_observed_on"] = d
            row["queue_source_post_id"] = q["post_id"]
            row["queue_source_link"] = q["link"]
        else:
            row["queue_observed_on"] = None
            row["queue_source_post_id"] = None
            row["queue_source_link"] = None

    # ---- weekday + festival / holiday annotation -------------------------
    # The calendar is built separately by build_calendar.py from TTD's own
    # dated posts plus fixed national holidays. Other TTD temples run their own
    # Brahmotsavams in different months, so only Tirumala / venue-unspecified
    # entries set the headline flag; everything found is still listed.
    cal_major, cal_minor, cal_other = (defaultdict(list), defaultdict(list),
                                       defaultdict(list))
    cal_path = os.path.join(HERE, "festival_calendar.csv")
    if os.path.exists(cal_path):
        with open(cal_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                d = dt.date.fromisoformat(row["date"])
                relevant = row.get("venue") in ("tirumala", "unspecified", "national")
                if not relevant:
                    cal_other[d].append(row["festival"])
                elif row.get("tier") == "major":
                    cal_major[d].append(row["festival"])
                else:
                    cal_minor[d].append(row["festival"])

    for d, row in daily.items():
        row["day_of_week"] = d.strftime("%A")
        row["is_weekend"] = d.weekday() >= 5
        names = sorted(set(cal_major.get(d, [])))
        row["is_festival_or_holiday"] = "yes" if names else "no"
        row["festival_name"] = "; ".join(names)
        row["minor_utsavam"] = "; ".join(sorted(set(cal_minor.get(d, []))))
        row["other_temple_events"] = "; ".join(sorted(set(cal_other.get(d, []))))

    # missing dates in the covered span
    gaps = []
    if dates:
        cur = dates[0]
        have = set(dates)
        while cur <= dates[-1]:
            if cur not in have:
                gaps.append(cur)
            cur += dt.timedelta(days=1)

    # ---- write outputs ---------------------------------------------------
    def w(name, rows, cols):
        path = os.path.join(HERE, name)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            wr.writeheader()
            for r in rows:
                wr.writerow(r)
        return path

    daily_cols = ["darshan_date", "day_of_week", "is_weekend",
                  "is_festival_or_holiday", "festival_name", "minor_utsavam",
                  "other_temple_events",
                  "pilgrims", "tonsures", "hundi_cr", "laddu_lakh",
                  "annaprasadam_lakh", "hospital",
                  "sarva_compartments", "sarva_hours", "sarva_status",
                  "divya_compartments", "divya_hours", "divya_status",
                  "special_entry_status", "darshan_wait_hours",
                  "waiting_compartments", "queue_observed_on",
                  "queue_source_post_id", "queue_source_link",
                  "date_source", "count_kind",
                  "n_posts_for_date", "conflicting_values", "resolution",
                  "post_id", "post_datetime", "title", "link"]
    w("darshan_daily.csv", [daily[d] for d in dates], daily_cols)

    all_cols = ["post_id", "post_datetime", "darshan_date", "date_source", "pilgrims",
                "count_kind", "is_partial_day", "queue_status_only", "tonsures",
                "hundi_cr", "laddu_lakh", "annaprasadam_lakh", "hospital",
                "sarva_compartments", "sarva_hours", "sarva_status",
                "divya_compartments", "divya_hours", "divya_status",
                "special_entry_status", "queue_observed_date", "queue_observed_src",
                "darshan_wait_hours", "waiting_compartments", "title", "link", "evidence"]
    w("darshan_all_records.csv", records, all_cols)

    resolved.sort(key=lambda r: str(r["darshan_date"]))
    w("darshan_duplicates_resolved.csv", resolved,
      ["darshan_date", "values_seen", "values_agree", "chosen_value", "spread",
       "n_posts", "resolution", "post_ids", "chosen_post_id", "chosen_link"])

    w("darshan_title_date_gapfills.csv", gapfilled,
      ["darshan_date", "pilgrims", "body_date_used_elsewhere", "post_id", "title", "link"])

    # the old outstanding-duplicates file is now always empty; remove it so a
    # stale copy cannot be mistaken for unreviewed work
    old_dup = os.path.join(HERE, "darshan_duplicates.csv")
    if os.path.exists(old_dup):
        os.remove(old_dup)

    anomalies.sort(key=lambda a: (a["type"], str(a["darshan_date"])))
    w("darshan_anomalies.csv", anomalies,
      ["type", "darshan_date", "value", "detail", "post_id", "post_datetime", "title", "link"])

    w("darshan_partial_day.csv", partials,
      ["darshan_date", "pilgrims", "post_id", "post_datetime", "date_source",
       "darshan_wait_hours", "waiting_compartments", "title", "link"])

    w("darshan_gaps.csv", [{"missing_date": g, "weekday": g.strftime("%a")} for g in gaps],
      ["missing_date", "weekday"])

    # ---- report ----------------------------------------------------------
    lines = []
    A = lines.append
    A("TIRUMALA DARSHAN - HISTORIC PILGRIM DATA")
    A("=" * 60)
    A(f"Source          : https://news.tirumala.org/category/darshan/ (WP REST API, category id 2)")
    A(f"Posts fetched   : {len(posts):,}")
    A(f"Records parsed  : {len(records):,}")
    A(f"  with a pilgrim count : {len(counted):,}")
    A(f"  full-day totals      : {len(full):,}")
    A(f"  partial-day snapshots: {len(partials):,}")
    A(f"  queue-status only    : {sum(1 for r in records if r['queue_status_only']):,}")
    A(f"  no count found       : {sum(1 for r in records if r['pilgrims'] is None):,}")
    A("")
    A(f"Unique dates    : {len(dates):,}")
    if dates:
        A(f"Coverage        : {dates[0]} -> {dates[-1]}  "
          f"({(dates[-1]-dates[0]).days + 1:,} calendar days, {len(gaps):,} missing)")
        A(f"Pilgrims/day    : min {min(vals):,}  median {statistics.median(vals):,.0f}  max {max(vals):,}")
        top = sorted(dates, key=lambda d: -daily[d]["pilgrims"])[:5]
        A("")
        A("Highest recorded days:")
        for d in top:
            A(f"  {d}  {daily[d]['pilgrims']:>8,}")
    A("")
    A("Date provenance:")
    for k, n in Counter((daily[d]["date_source"] or "?") for d in dates).most_common():
        A(f"  {k:<35} {n:>6,}")
    A("")
    A("Field coverage across daily rows:")
    for fld in ["pilgrims", "tonsures", "hundi_cr", "laddu_lakh", "annaprasadam_lakh",
                "hospital", "sarva_compartments", "sarva_hours", "sarva_status",
                "divya_compartments", "divya_hours", "special_entry_status",
                "darshan_wait_hours", "waiting_compartments"]:
        n = sum(1 for d in dates if daily[d].get(fld) is not None)
        A(f"  {fld:<22} {n:>6,} / {len(dates):,}")
    A("")
    A("Coverage by year:")
    yc = Counter(d.year for d in dates)
    for y in sorted(yc):
        yv = [daily[d]["pilgrims"] for d in dates if d.year == y]
        A(f"  {y}  {yc[y]:>4} days   avg {statistics.mean(yv):>9,.0f}   "
          f"min {min(yv):>7,}   max {max(yv):>7,}")
    A("")
    A(f"Duplicate/conflict dates resolved: {len(resolved):,} "
      f"(same value {sum(1 for r in resolved if r['values_agree']=='yes'):,}, "
      f"took highest {sum(1 for r in resolved if r['values_agree']=='no'):,})")
    A(f"Dates gapfilled from a mismatched title date: {len(gapfilled):,}")
    nf = sum(1 for d in dates if daily[d].get("is_festival_or_holiday") == "yes")
    A(f"Dates flagged festival/holiday: {nf:,} of {len(dates):,}")
    A(f"Anomalies flagged: {len(anomalies):,}")
    for k, n in Counter(a["type"] for a in anomalies).most_common():
        A(f"  {k:<32} {n:>6,}")
    A("")
    A("Outputs: darshan_daily.csv, darshan_all_records.csv,")
    A("         darshan_duplicates_resolved.csv, darshan_title_date_gapfills.csv,")
    A("         darshan_anomalies.csv, darshan_partial_day.csv, darshan_gaps.csv")

    report = "\n".join(lines)
    with open(os.path.join(HERE, "darshan_report.txt"), "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(report)


if __name__ == "__main__":
    main()
