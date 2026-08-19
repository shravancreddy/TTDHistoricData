"""
Fetch every post in the 'darshan' category (id=2) from news.tirumala.org
via the WordPress REST API, and cache the raw JSON to disk.

Raw data only -- no parsing here. Parsing lives in parse_darshan.py so the
network fetch never has to be repeated while the parser is iterated on.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://news.tirumala.org/wp-json/wp/v2/posts"
CATEGORY = 2
PER_PAGE = 100
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"

FIELDS = "id,date,date_gmt,modified,slug,link,title,content,categories"


def get(url, tries=5):
    """GET with retry/backoff. Returns (body_bytes, headers)."""
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read(), dict(r.headers)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            last = e
            wait = 2 ** attempt
            print(f"    retry {attempt+1}/{tries} after {wait}s ({e})", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"failed after {tries} tries: {url}\n{last}")


def main():
    os.makedirs(OUTDIR, exist_ok=True)

    # Page 1 also tells us the totals via response headers.
    first_url = f"{BASE}?categories={CATEGORY}&per_page={PER_PAGE}&page=1&_fields={FIELDS}"
    body, headers = get(first_url)
    total_posts = int(headers.get("X-WP-Total", 0))
    total_pages = int(headers.get("X-WP-TotalPages", 0))
    print(f"X-WP-Total={total_posts}  X-WP-TotalPages={total_pages}", flush=True)

    with open(os.path.join(OUTDIR, "page_001.json"), "wb") as f:
        f.write(body)
    got = len(json.loads(body.decode("utf-8")))
    print(f"page 1/{total_pages}: {got} posts", flush=True)

    for page in range(2, total_pages + 1):
        path = os.path.join(OUTDIR, f"page_{page:03d}.json")
        if os.path.exists(path) and os.path.getsize(path) > 100:
            print(f"page {page}/{total_pages}: cached", flush=True)
            continue
        url = f"{BASE}?categories={CATEGORY}&per_page={PER_PAGE}&page={page}&_fields={FIELDS}"
        body, _ = get(url)
        data = json.loads(body.decode("utf-8"))
        if isinstance(data, dict):  # error object
            print(f"page {page}: ERROR payload {data}", file=sys.stderr)
            break
        with open(path, "wb") as f:
            f.write(body)
        print(f"page {page}/{total_pages}: {len(data)} posts", flush=True)
        time.sleep(0.4)  # be polite to the server

    # Consolidate, de-duplicating by post id.
    seen = {}
    for name in sorted(os.listdir(OUTDIR)):
        if not name.startswith("page_"):
            continue
        with open(os.path.join(OUTDIR, name), encoding="utf-8") as f:
            for p in json.load(f):
                seen[p["id"]] = p
    allp = sorted(seen.values(), key=lambda p: p["date"], reverse=True)
    out = os.path.join(os.path.dirname(OUTDIR), "all_posts.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(allp, f, ensure_ascii=False)
    print(f"\nunique posts: {len(allp)}  (API reported {total_posts})")
    if allp:
        print(f"newest: {allp[0]['date']}\noldest: {allp[-1]['date']}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
