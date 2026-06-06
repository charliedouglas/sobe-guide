#!/usr/bin/env python3
"""Fetch rotating venue photos via SerpApi (Google Images) and wire them into index.html.

Run this on a normal machine (not the sandbox) where your SerpApi key works:

    SERPAPI_KEY=your_key  python3 tools/fetch_photos.py
    # or:
    python3 tools/fetch_photos.py --key your_key --per 3

What it does:
  * reads every venue out of index.html (using each card's data-q search term),
  * asks SerpApi Google Images for photos of that venue,
  * downloads up to --per images each into ./images/,
  * adds a data-imgs="images/..." attribute to that venue's photo box so the
    page crossfades through them (see the carousel script in index.html).

Re-running refreshes everything. The API key is only read at runtime and is
never written to disk or into index.html. Requires Python 3, no pip installs.

Afterwards:  git add images index.html && git commit -m "Add venue photos" && git push
"""
import argparse
import json
import os
import pathlib
import re
import sys
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = ROOT / "index.html"
IMGDIR = ROOT / "images"
UA = "Mozilla/5.0 (compatible; sobe-guide/1.0)"


def slugify(name: str) -> str:
    name = name.replace("&amp;", "and").replace("&", "and")
    name = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return name or "venue"


def parse_cards(html: str):
    """Return [{name, query, slug}] for every venue card with a data-q term."""
    cards = []
    for chunk in html.split('<div class="card')[1:]:
        mq = re.search(r'data-q="([^"]+)"', chunk)
        mn = re.search(r'<div class="name">([^<]+)', chunk)
        if not mq or not mn:
            continue
        name = mn.group(1).strip()
        cards.append({"name": name, "query": mq.group(1).strip(), "slug": slugify(name)})
    return cards


def serpapi_images(query: str, key: str):
    params = urllib.parse.urlencode(
        {"engine": "google_images", "q": query, "api_key": key, "ijn": "0"}
    )
    url = "https://serpapi.com/search.json?" + params
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data.get("images_results", [])


def download(url: str, dest: pathlib.Path) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        if "image" not in r.headers.get("Content-Type", ""):
            return False
        blob = r.read()
    if len(blob) < 1500:  # skip 1x1 pixels / error pages
        return False
    dest.write_bytes(blob)
    return True


def inject(html: str, query: str, files) -> str:
    """Add (or replace) data-imgs on the .ph tag identified by its unique data-q."""
    anchor = '<div class="ph" data-q="%s"' % query
    pattern = re.escape(anchor) + r'(?:\s+data-imgs="[^"]*")?'
    repl = anchor + ' data-imgs="%s"' % ",".join(files)
    return re.sub(pattern, lambda m: repl, html, count=1)


def main():
    ap = argparse.ArgumentParser(description="Fetch venue photos via SerpApi.")
    ap.add_argument("--key", default=os.environ.get("SERPAPI_KEY"),
                    help="SerpApi key (or set SERPAPI_KEY env var)")
    ap.add_argument("--per", type=int, default=3, help="images per venue (default 3)")
    args = ap.parse_args()
    if not args.key:
        sys.exit("No API key. Use --key or set SERPAPI_KEY.")

    html = HTML.read_text()
    cards = parse_cards(html)
    print("Found %d venues." % len(cards))
    IMGDIR.mkdir(exist_ok=True)
    manifest = {}

    for c in cards:
        print("\n[%s]  q=%r" % (c["name"], c["query"]))
        try:
            results = serpapi_images(c["query"], args.key)
        except Exception as e:
            print("  ! search failed:", e)
            continue
        saved = []
        for res in results:
            if len(saved) >= args.per:
                break
            for key in ("original", "thumbnail"):
                u = res.get(key)
                if not u:
                    continue
                dest = IMGDIR / ("%s-%d.jpg" % (c["slug"], len(saved) + 1))
                try:
                    if download(u, dest):
                        saved.append("images/" + dest.name)
                        print("  + %s  (%s)" % (dest.name, key))
                        break
                except Exception:
                    continue
        if saved:
            manifest[c["slug"]] = saved
            html = inject(html, c["query"], saved)
        else:
            print("  (no images saved)")

    HTML.write_text(html)
    (IMGDIR / "photos.json").write_text(json.dumps(manifest, indent=2))
    print("\nDone. Wrote %d venues' photos into images/ and updated index.html." % len(manifest))
    print("Next:  git add images index.html && git commit -m 'Add venue photos' && git push")


if __name__ == "__main__":
    main()
