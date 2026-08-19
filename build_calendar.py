"""
Build a festival / holiday calendar for the darshan series.

Two independent layers, both auditable -- nothing is recalled from memory:

  1. Fixed-date national holidays. Deterministic, computed from the date alone.

  2. Major festivals sourced from TTD's OWN dated posts on news.tirumala.org
     (categories Brahmotsavams / Events / Utsavams / Vaibhavotsavams). Hindu
     festivals are lunisolar, so their dates cannot be derived arithmetically;
     taking them from TTD's announcements keeps every entry traceable to a URL.

Event dating is the delicate part. A title carries either
  - an explicit date or range  ("BRAHMOTSAVAMS FROM SEPTEMBER 15 TO 23",
    "PAVITROTSAVAM ... FROM AUG 18-20", "VARALAKSHMI VRATAM ON AUGUST 20")
    -> use those dates, NOT the publication date; or
  - a same-day report marker   ("GARUDA PANCHAMI OBSERVED", "... HELD",
    "... COMMENCES") -> use the publication date.
A title with neither is skipped rather than guessed at.

Output: festival_calendar.csv  (date, festival, kind, evidence, source_url)
"""

import calendar
import csv
import datetime as dt
import json
import os
import re
import time
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
CACHE = os.path.join(HERE, "raw_calendar")

# Categories that carry festival reportage.
CATEGORIES = {20: "Brahmotsavams", 18: "Events", 21: "Utsavams", 25: "Vaibhavotsavams",
              3: "Temple News", 4: "General News", 19: "Press Releases"}

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
MRE = "|".join(sorted(MONTHS, key=len, reverse=True))

# Major festivals only, as requested. Each entry: canonical name -> regex.
FESTIVALS = [
    ("Srivari Annual Brahmotsavams", r"annual\s+brahmotsavam|salakatla\s+brahmotsavam|srivari\s+brahmotsavam"),
    ("Navaratri Brahmotsavams", r"navarathri\s+brahmotsavam|navaratri\s+brahmotsavam"),
    ("Brahmotsavams", r"brahmotsavam"),
    ("Vaikunta Ekadasi", r"vaikunta\s*ekadasi|vaikuntha\s*ekadashi|vaikunta\s*dwadasi|vaikunta\s*dvadasi"),
    ("Rathasapthami", r"ratha\s*sapthami|ratha\s*saptami"),
    ("Ugadi", r"\bugadi\b"),
    ("Sri Rama Navami", r"rama\s*navami"),
    ("Sri Krishna Janmashtami", r"krishna\s*janmashtami|krishna\s*jayanthi|janmashtami|sri\s*jayanthi"),
    ("Vinayaka Chaturthi", r"vinayaka\s*chaturthi|ganesh\s*chaturthi"),
    ("Deepavali", r"deepavali|diwali"),
    ("Sankranti", r"sankranti|pongal"),
    ("Maha Shivaratri", r"maha\s*shivaratri|mahashivaratri|shivaratri"),
    ("Varalakshmi Vratam", r"varalakshmi\s*vrat"),
    ("Garuda Seva", r"garuda\s*seva|garuda\s*vahanam"),
    ("Pavitrotsavam", r"pavitrotsavam|pavithrotsavam"),
    ("Teppotsavam", r"teppotsavam|float\s+festival"),
    ("Vasanthotsavam", r"vasanthotsavam|vasantotsavam"),
    ("Karthika Deepam", r"karthika\s*deepam|kartika\s*deepam"),
    ("Anivara Asthanam", r"anivara\s*asthanam"),
    ("Padmavathi Karthika Brahmotsavams", r"karthika\s+brahmotsavam"),
    ("Panchami Teertham", r"panchami\s*teertham"),
    ("Hanuman Jayanti", r"hanuman\s*jayanthi|hanumath\s*jayanthi|hanuman\s*jayanti"),
    ("Dasara / Navaratri", r"\bdasara\b|dussehra|sharan\s*navaratri"),
    ("Tiruppavai / Dhanurmasam", r"dhanurmasam|tiruppavai"),
]
FESTIVALS = [(n, re.compile(p, re.I)) for n, p in FESTIVALS]

# Title verbs implying the event happened on the publication date.
SAME_DAY = re.compile(
    r"(?i)\b(observed|held|begins?|began|commence[sd]?|concludes?|concluded|"
    r"performed|celebrated|celebrations?|underway|offered|taken\s+out|ends?)\b")

# Titles that are clearly not event reports.
NON_EVENT = re.compile(
    r"(?i)\b(reviews?|inspects?|arrangements?|preparations?|cancels?|"
    r"appeals?|urges?|invit|tender|recruit|press\s+meet|meeting)\b")

# TTD administers many temples beyond Tirumala, and their Brahmotsavams fall in
# entirely different months. Crediting those to Tirumala would corrupt any
# footfall insight, so each entry is tagged with a venue and only Tirumala (or
# venue-unspecified) events set the headline festival flag.
OTHER_VENUE = re.compile(
    r"(?i)tiruchanoor|tiruchanur|padmavathi|padmavati|govindaraja|kapileswara|"
    r"kapilateertham|srinivasa\s*mangapuram|appalayagunta|nandalur|palamaner|"
    r"valmikipuram|karvetinagaram|narayanavanam|vontimitta|kodandarama|"
    r"jubilee\s*hills|hyderabad|chennai|delhi|mumbai|bengaluru|kurnool|"
    r"soumyanatha|prasanna\s*venkateswara|kalyana\s*venkateswara|"
    r"anjaneya\s*swamy\s*temple|bhu\s*varaha|srikalahasti|kanipakam|"
    r"dwaraka\s*tirumala|visakhapatnam|rishikesh|haridwar|jammu|kashi|bhadrachalam")
TIRUMALA_VENUE = re.compile(
    r"(?i)tirumala|srivari|srivaru|sri\s*venkateswara\s*swamy\s*temple|"
    r"malayappa|ananda\s*nilayam|sri\s*vari")


def venue_of(title):
    other, tml = OTHER_VENUE.search(title), TIRUMALA_VENUE.search(title)
    if other and not tml:
        return "other_temple"
    if tml:
        return "tirumala"
    return "unspecified"


# A genuine festival window is short; a longer span means two separate events
# were spliced together by the range parser.
MAX_RANGE_DAYS = 12

# Not every utsavam moves the crowd. Teppotsavam, Pavitrotsavam, Garuda Seva and
# Vasanthotsavam run on the temple's routine calendar and show no footfall
# signal, so they are tiered as minor and kept out of the headline flag; the
# pilgrimage-defining occasions are tiered major.
MAJOR = {
    "Srivari Annual Brahmotsavams", "Navaratri Brahmotsavams", "Brahmotsavams",
    "Vaikunta Ekadasi", "Rathasapthami", "Ugadi", "Sri Rama Navami",
    "Sri Krishna Janmashtami", "Vinayaka Chaturthi", "Deepavali", "Sankranti",
    "Maha Shivaratri", "Karthika Deepam", "Dasara / Navaratri",
    "Padmavathi Karthika Brahmotsavams", "Hanuman Jayanti", "Varalakshmi Vratam",
    "Republic Day", "Independence Day", "Gandhi Jayanti", "New Year's Day",
    "Christmas",
}


def tier_of(name):
    return "major" if name in MAJOR else "minor"

NATIONAL = {(1, 26): "Republic Day", (8, 15): "Independence Day",
            (10, 2): "Gandhi Jayanti", (1, 1): "New Year's Day",
            (12, 25): "Christmas"}


def get(url, tries=5):
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read(), dict(r.headers)
        except Exception as e:                                   # noqa: BLE001
            last = e
            time.sleep(2 ** a)
    raise RuntimeError(f"{url}: {last}")


def strip(s):
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&#8211;", "-").replace("&amp;", "&").replace("&#8217;", "'")
    s = re.sub(r"&#\d+;", " ", s)
    # titles are "ENGLISH _ telugu"; keep the English half
    s = s.split(" _ ")[0]
    return re.sub(r"\s+", " ", s).strip()


def fetch_category(cat):
    os.makedirs(CACHE, exist_ok=True)
    out, page, total_pages = [], 1, None
    while True:
        path = os.path.join(CACHE, f"cat{cat}_p{page:03d}.json")
        if os.path.exists(path) and os.path.getsize(path) > 50:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        else:
            url = (f"https://news.tirumala.org/wp-json/wp/v2/posts?categories={cat}"
                   f"&per_page=100&page={page}&_fields=id,date,title,link")
            body, headers = get(url)
            if total_pages is None:
                total_pages = int(headers.get("X-WP-TotalPages", 1))
            data = json.loads(body.decode("utf-8"))
            if isinstance(data, dict):
                break
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            time.sleep(0.3)
        if not data:
            break
        out.extend(data)
        if total_pages is None:
            total_pages = 10 ** 6
        if page >= total_pages or len(data) < 100:
            break
        page += 1
    return out


def mk(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        # tolerate "September 31" style slips by clamping to month end
        try:
            return dt.date(y, m, calendar.monthrange(y, m)[1])
        except ValueError:
            return None


def pick_year(month, day, post):
    """Choose the year making the event closest to its announcement."""
    best = None
    for y in (post.year - 1, post.year, post.year + 1):
        c = mk(y, month, day)
        if not c:
            continue
        delta = (c - post).days
        # events are announced shortly before, or reported same day
        score = abs(delta) + (60 if delta < -20 else 0)
        if best is None or score < best[0]:
            best = (score, c)
    return best[1] if best else None


def title_dates(title, post):
    """Explicit dates/ranges in a title -> list of dates."""
    t = title
    # "FROM AUGUST 30 TO SEPTEMBER 03"
    m = re.search(r"(?i)from\s+(" + MRE + r")\s*(\d{1,2})\s*(?:to|-|till|until)\s*(" + MRE + r")\s*(\d{1,2})", t)
    if m:
        a = pick_year(MONTHS[m.group(1).lower()], int(m.group(2)), post)
        b = pick_year(MONTHS[m.group(3).lower()], int(m.group(4)), post)
        if a and b and 0 <= (b - a).days <= MAX_RANGE_DAYS:
            return [a + dt.timedelta(days=i) for i in range((b - a).days + 1)]
        return [x for x in (a,) if x]
    # "FROM SEPTEMBER 15 TO 23" / "AUGUST 17-19" / "FROM AUG 18-20"
    m = re.search(r"(?i)(?:from\s+)?(" + MRE + r")\s*(\d{1,2})\s*(?:to|-|till|until)\s*(\d{1,2})\b", t)
    if m:
        mo = MONTHS[m.group(1).lower()]
        a = pick_year(mo, int(m.group(2)), post)
        b = pick_year(mo, int(m.group(3)), post)
        if a and b and 0 <= (b - a).days <= MAX_RANGE_DAYS:
            return [a + dt.timedelta(days=i) for i in range((b - a).days + 1)]
    # "ON AUGUST 20" / "ON SEPTEMBER 15"
    m = re.search(r"(?i)\bon\s+(" + MRE + r")\s*(\d{1,2})\b", t)
    if m:
        d = pick_year(MONTHS[m.group(1).lower()], int(m.group(2)), post)
        if d:
            return [d]
    return []


def main():
    hits = defaultdict(dict)     # date -> {festival: (kind, evidence, url)}

    posts = {}
    for cat, name in CATEGORIES.items():
        data = fetch_category(cat)
        print(f"{name:<16} {len(data):>6} posts", flush=True)
        for p in data:
            posts[p["id"]] = p
    print(f"{'unique':<16} {len(posts):>6} posts\n", flush=True)

    for p in posts.values():
        title = strip(p["title"]["rendered"])
        if not title or NON_EVENT.search(title):
            continue
        fest = next((n for n, rx in FESTIVALS if rx.search(title)), None)
        if not fest:
            continue
        post_d = dt.date.fromisoformat(p["date"][:10])
        dates = title_dates(title, post_d)
        kind = "announced_dates"
        if not dates and SAME_DAY.search(title):
            dates, kind = [post_d], "same_day_report"
        ven = venue_of(title)
        for d in dates:
            if dt.date(2013, 1, 1) <= d <= dt.date(2027, 12, 31):
                # keep the first (most specific) attribution per festival/date
                hits[d].setdefault(fest, (kind, ven, title[:150], p["link"]))

    rows = []
    for d in sorted(hits):
        for fest, (kind, ven, ev, url) in sorted(hits[d].items()):
            rows.append({"date": d, "festival": fest, "kind": kind, "venue": ven,
                         "tier": tier_of(fest), "evidence": ev, "source_url": url})

    # national holidays across the covered span
    for y in range(2013, 2028):
        for (m, dd), nm in NATIONAL.items():
            rows.append({"date": dt.date(y, m, dd), "festival": nm,
                         "kind": "fixed_national_holiday", "venue": "national",
                         "tier": "major",
                         "evidence": "fixed calendar date", "source_url": ""})

    rows.sort(key=lambda r: (r["date"], r["festival"]))
    out = os.path.join(HERE, "festival_calendar.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["date", "festival", "kind", "venue",
                                          "tier", "evidence", "source_url"])
        w.writeheader()
        w.writerows(rows)

    ks = defaultdict(int)
    for r in rows:
        ks[r["kind"]] += 1
    print(f"calendar entries : {len(rows):,} over {len({r['date'] for r in rows}):,} dates")
    for k, n in sorted(ks.items(), key=lambda x: -x[1]):
        print(f"  {k:<26} {n:>6,}")
    vs = defaultdict(int)
    for r in rows:
        vs[r["venue"]] += 1
    print("  --- by tier ---")
    ts = defaultdict(int)
    for r in rows:
        ts[r["tier"]] += 1
    for k, n in sorted(ts.items(), key=lambda x: -x[1]):
        print(f"  {k:<26} {n:>6,}")
    print("  --- by venue ---")
    for k, n in sorted(vs.items(), key=lambda x: -x[1]):
        print(f"  {k:<26} {n:>6,}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
