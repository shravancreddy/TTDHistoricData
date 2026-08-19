"""
Independent check that the REST-API dataset matches the rendered category
pages at https://news.tirumala.org/category/darshan/page/N/.

The main pipeline reads the WP REST API. This script re-derives the figures
straight from the public HTML listing pages and compares them, so a parsing or
coverage error in the API path cannot pass unnoticed.
"""

import html
import json
import os
import random
import re
import sys
import time
import urllib.request

import parse_darshan as P

HERE = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
LAST_PAGE = 662


def fetch(url, tries=4):
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:                                  # noqa: BLE001
            if a == tries - 1:
                raise
            time.sleep(2 ** a)
    return ""


def page_url(n):
    return ("https://news.tirumala.org/category/darshan/" if n == 1
            else f"https://news.tirumala.org/category/darshan/page/{n}/")


LINK_RE = re.compile(
    r'<h\d[^>]*class="[^"]*post-title[^"]*"[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.S | re.I)
FALLBACK_RE = re.compile(
    r'<a[^>]+rel="bookmark"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)


def scrape(page):
    doc = fetch(page_url(page))
    found = LINK_RE.findall(doc) or FALLBACK_RE.findall(doc)
    if not found:
        # last resort: any permalink that looks like a darshan post
        found = re.findall(r'href="(https://news\.tirumala\.org/[^"]*darshan[^"]*/)"[^>]*>(.*?)</a>',
                           doc, re.S | re.I)
    out = []
    for href, raw in found:
        title = P.clean(html.unescape(raw))
        if title:
            out.append((href.split("#")[0].rstrip("/") + "/", title))
    # de-dup while preserving order
    seen, uniq = set(), []
    for h, t in out:
        if h not in seen:
            seen.add(h)
            uniq.append((h, t))
    return uniq


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    with open(os.path.join(HERE, "all_posts.json"), encoding="utf-8") as f:
        posts = json.load(f)
    by_link = {p["link"].split("#")[0].rstrip("/") + "/": p for p in posts}

    with open(os.path.join(HERE, "darshan_all_records.csv"), encoding="utf-8-sig") as f:
        import csv
        recs = {r["link"].split("#")[0].rstrip("/") + "/": r
                for r in csv.DictReader(f)}

    random.seed(20260818)
    pages = sorted({1, 2, LAST_PAGE, LAST_PAGE - 1}
                   | set(random.sample(range(3, LAST_PAGE - 1), n)))

    tot = miss = title_bad = count_bad = 0
    problems = []
    for pg in pages:
        items = scrape(pg)
        if not items:
            problems.append(f"page {pg}: no posts scraped from HTML")
            print(f"page {pg:>4}: NO POSTS SCRAPED", flush=True)
            continue
        pm = pt = pc = 0
        for link, title in items:
            tot += 1
            post = by_link.get(link)
            if post is None:
                miss += 1
                pm += 1
                problems.append(f"page {pg}: link absent from API dataset: {link}")
                continue
            if P.clean(post["title"]["rendered"]) != title:
                title_bad += 1
                pt += 1
                problems.append(f"page {pg}: title differs for {link}\n"
                                f"      html={title}\n      api ={P.clean(post['title']['rendered'])}")
            # re-derive the count straight from the HTML listing title
            hv, _, _ = P.extract_count(title)
            rec = recs.get(link)
            if hv is not None and rec is not None and rec["pilgrims"]:
                if int(rec["pilgrims"]) != hv:
                    count_bad += 1
                    pc += 1
                    problems.append(f"page {pg}: count differs for {link}: "
                                    f"html={hv} csv={rec['pilgrims']}")
        print(f"page {pg:>4}: {len(items):>2} posts | missing {pm} | "
              f"title-diff {pt} | count-diff {pc}", flush=True)
        time.sleep(0.3)

    print("\n" + "=" * 62)
    print(f"HTML posts checked      : {tot}")
    print(f"Missing from API dataset: {miss}")
    print(f"Title mismatches        : {title_bad}")
    print(f"Count mismatches        : {count_bad}")
    print("=" * 62)
    if problems:
        print("\nDetails:")
        for p in problems[:40]:
            print("  -", p)
    else:
        print("\nHTML listing pages agree with the REST-API dataset.")


if __name__ == "__main__":
    main()
