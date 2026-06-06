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


def load_dotenv(root: pathlib.Path):
    env = root / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v

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


EXT_MAP = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


def download(url: str, dest: pathlib.Path):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        ct = r.headers.get("Content-Type", "").split(";")[0].strip()
        if "image" not in ct:
            return False
        blob = r.read()
    if len(blob) < 1500:
        return False
    ext = EXT_MAP.get(ct, ".jpg")
    if dest.suffix != ext:
        dest = dest.with_suffix(ext)
    dest.write_bytes(blob)
    return dest


def inject(html: str, query: str, files) -> str:
    """Add (or replace) data-imgs on the .ph tag identified by its unique data-q."""
    anchor = '<div class="ph" data-q="%s"' % query
    pattern = re.escape(anchor) + r'(?:\s+data-imgs="[^"]*")?'
    repl = anchor + ' data-imgs="%s"' % ",".join(files)
    return re.sub(pattern, lambda m: repl, html, count=1)


def existing_images(slug: str) -> list:
    """Return already-downloaded image paths for a slug (any extension)."""
    found = sorted(IMGDIR.glob("%s-*" % slug))
    return ["images/" + p.name for p in found]


def main():
    load_dotenv(ROOT)
    ap = argparse.ArgumentParser(description="Fetch venue photos via SerpApi.")
    ap.add_argument("--key", default=os.environ.get("SERPAPI_KEY"),
                    help="SerpApi key (or set SERPAPI_KEY env var)")
    ap.add_argument("--per", type=int, default=3, help="images per venue (default 3)")
    ap.add_argument("--force", action="store_true", help="re-fetch even if images exist")
    args = ap.parse_args()
    if not args.key:
        sys.exit("No API key. Use --key or set SERPAPI_KEY.")

    html = HTML.read_text()
    cards = parse_cards(html)
    print("Found %d venues." % len(cards))
    IMGDIR.mkdir(exist_ok=True)
    manifest = {}

    for c in cards:
        if not args.force:
            cached = existing_images(c["slug"])
            if len(cached) >= args.per:
                print("\n[%s]  skipped (cached: %d images)" % (c["name"], len(cached)))
                manifest[c["slug"]] = cached
                html = inject(html, c["query"], cached)
                continue

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
                    saved_path = download(u, dest)
                    if saved_path:
                        saved.append("images/" + saved_path.name)
                        print("  + %s  (%s)" % (saved_path.name, key))
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
