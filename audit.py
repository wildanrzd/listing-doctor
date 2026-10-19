#!/usr/bin/env python3
"""Listing Doctor v0 - audit one Etsy listing.

Two modes, same model, so the comparison is honest:
  doctor <listing_id>   data-fed audit: your listing + the listings that outrank it
  naive  <listing_id>   the same listing, asked the way a seller would ask a chatbot

Usage:
  export ETSY_KEY=your_keystring
  python3 audit.py doctor 4339889009
  python3 audit.py doctor 4339889009 --keyword "plaid tablecloth"
  python3 audit.py naive  4339889009

Etsy key lookup order: $ETSY_KEY, ./.etsy-key, ~/.config/etsy/keystring
AI: shells out to `opencode run`, so it uses your existing OpenCode subscription.
No dependencies, stdlib only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://openapi.etsy.com/v3/application"
HERE = pathlib.Path(__file__).resolve().parent
REPORTS = HERE / "reports"
UA = "ListingDoctor/0.1 (+https://github.com/wildanrzd/listing-doctor)"

FILLER = {
    "the", "a", "an", "and", "or", "for", "with", "of", "in", "on", "to", "your",
    "new", "set", "pcs", "inch", "inches", "cm", "x",
}


# ---------------------------------------------------------------- key + http

def load_key() -> str:
    candidates = [
        os.environ.get("ETSY_KEY", "").strip(),
        (HERE / ".etsy-key").read_text().strip() if (HERE / ".etsy-key").exists() else "",
        (pathlib.Path.home() / ".config/etsy/keystring").read_text().strip()
        if (pathlib.Path.home() / ".config/etsy/keystring").exists() else "",
    ]
    for c in candidates:
        if c:
            return c
    sys.exit(
        "No Etsy key found.\n"
        "Put your keystring in one of these:\n"
        "  export ETSY_KEY=xxxx\n"
        f"  echo xxxx > {HERE / '.etsy-key'}\n"
        "  mkdir -p ~/.config/etsy && echo xxxx > ~/.config/etsy/keystring"
    )


def api(path: str, params: dict | None = None) -> dict:
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={"x-api-key": KEY, "User-Agent": UA,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:600]
        sys.exit(f"Etsy API {e.code} on {url}\n{body}")


# ---------------------------------------------------------------- etsy data

def get_listing(listing_id: str) -> dict:
    return api(f"/listings/{listing_id}")


def get_image_count(listing_id: str) -> int | None:
    try:
        return api(f"/listings/{listing_id}/images").get("count")
    except SystemExit:
        return None


def find_competitors(keyword: str, limit: int) -> list[dict]:
    resp = api("/listings/active", {
        "keywords": keyword, "limit": min(limit, 100),
        "sort_on": "score", "sort_order": "down",
    })
    return resp.get("results", [])


def price_of(listing: dict) -> str:
    p = listing.get("price") or {}
    amount, divisor = p.get("amount"), p.get("divisor") or 100
    if amount is None:
        return "?"
    return f"{amount / divisor:.2f} {p.get('currency_code', '')}".strip()


def keyword_from_title(title: str, override: str | None) -> str:
    if override:
        return override
    words = re.findall(r"[a-zA-Z0-9']+", title.lower())
    keep = [w for w in words if len(w) > 2 and w not in FILLER]
    return " ".join(keep[:4])


# ---------------------------------------------------------------- prompts

def doctor_prompt(me: dict, competitors: list[dict], keyword: str) -> str:
    lines = [f"Seller's listing (id {me.get('listing_id')})",
             f"Title: {me.get('title')}",
             f"Tags: {', '.join(me.get('tags') or []) or '(none)'}",
             f"Price: {price_of(me)}",
             f"Views: {me.get('views')}  Favorites: {me.get('num_favorers')}",
             f"Description: {(me.get('description') or '')[:1200]}",
             "",
             f'What currently ranks on Etsy search for "{keyword}" (live, top {len(competitors)}):']
    for i, c in enumerate(competitors, 1):
        tags = ", ".join((c.get("tags") or [])[:12])
        lines.append(
            f"{i}. {c.get('title')}\n"
            f"   tags: {tags or '(none returned)'}\n"
            f"   price: {price_of(c)}  favorites: {c.get('num_favorers')}  views: {c.get('views')}"
        )
    lines += [
        "",
        "TASK — write the audit. Markdown, short lines, no preamble, no essay.",
        "1. Score the listing 0-100 for being found and clicked, one line of why.",
        "2. Top 3 problems, most costly first, each citing a specific competitor above.",
        "3. Rewritten title, under 140 characters, front-loading the buyer's words.",
        "4. Exactly 13 tags, each under 20 characters, no duplicates, multi-word when useful.",
        "5. Five fixes ranked by expected impact, one sentence each, each doable in 5 minutes.",
        "6. Questions buyers in this niche ask that this description never answers.",
        "",
        "RULES",
        "- Use only the data above. Never invent numbers, keywords or reviews.",
        "- No generic advice ('use relevant keywords'). Every line must be specific to this listing.",
        "- Where the listing is weak, say what the winners do instead.",
    ]
    return "\n".join(lines)


def naive_prompt(me: dict) -> str:
    return (
        "Here's my Etsy listing. How can I improve it and get more sales?\n\n"
        f"Title: {me.get('title')}\n"
        f"Tags: {', '.join(me.get('tags') or []) or '(none)'}\n"
        f"Price: {price_of(me)}\n"
        f"Description: {(me.get('description') or '')[:1200]}\n\n"
        "Give me suggestions."
    )


# ---------------------------------------------------------------- model

def ask(prompt: str, model: str | None) -> str:
    cmd = ["opencode", "run"]
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if p.returncode != 0:
        sys.exit(f"opencode run failed ({p.returncode}):\n{p.stderr[-1500:]}")
    return p.stdout.strip()


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description="Audit one Etsy listing.")
    ap.add_argument("mode", choices=["doctor", "naive"])
    ap.add_argument("listing_id")
    ap.add_argument("--keyword", help="force the search keyword (default: derived from the title)")
    ap.add_argument("--limit", type=int, default=12, help="competitors to pull (default 12)")
    ap.add_argument("--model", help="opencode model, e.g. opencode-go/deepseek-v4.1-flash")
    args = ap.parse_args()

    global KEY
    KEY = load_key()

    listing_id = re.sub(r"\D", "", args.listing_id)
    if not listing_id:
        sys.exit("listing_id must contain digits")

    REPORTS.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")

    me = get_listing(listing_id)
    if "listing_id" not in me and "title" not in me:
        sys.exit(f"Unexpected response: {json.dumps(me)[:400]}")
    me["image_count"] = get_image_count(listing_id)

    keyword = keyword_from_title(me.get("title", ""), args.keyword)

    if args.mode == "naive":
        prompt = naive_prompt(me)
        competitors: list[dict] = []
    else:
        competitors = find_competitors(keyword, args.limit)
        prompt = doctor_prompt(me, competitors, keyword)

    (REPORTS / f"{listing_id}-{stamp}-data.json").write_text(
        json.dumps({"listing": me, "competitors": competitors, "keyword": keyword}, indent=2))

    print(f"listing : {me.get('title')}")
    print(f"tags    : {', '.join(me.get('tags') or []) or '(none)'}")
    print(f"keyword : {keyword}")
    print(f"competer: {len(competitors)} listings pulled from Etsy")
    print("-" * 70)

    answer = ask(prompt, args.model)

    out = REPORTS / f"{listing_id}-{stamp}-{args.mode}.md"
    out.write_text(answer)
    print(answer)
    print("-" * 70)
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
