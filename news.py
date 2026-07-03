# -*- coding: utf-8 -*-
"""経済ニュース取得（NHK経済＋Yahoo!ニュース経済のRSS。30分キャッシュ）"""
import time
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

FEEDS = [
    ("NHK経済", "https://www3.nhk.or.jp/rss/news/cat5.xml"),
    ("Yahoo!経済", "https://news.yahoo.co.jp/rss/topics/business.xml"),
]
_cache = {"t": 0.0, "items": []}


def fetch_news(limit=12):
    if time.time() - _cache["t"] < 1800 and _cache["items"]:
        return _cache["items"][:limit]
    items = []
    for source, url in FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as res:
                root = ET.fromstring(res.read())
            for it in root.iter("item"):
                title = (it.findtext("title") or "").strip()
                link = (it.findtext("link") or "").strip()
                try:
                    ts = parsedate_to_datetime(it.findtext("pubDate") or "")
                    when, key = ts.strftime("%m/%d %H:%M"), ts.timestamp()
                except Exception:
                    when, key = "", 0.0
                if title:
                    items.append(dict(title=title, url=link, time=when, ts=key, source=source))
        except Exception:
            continue
    seen, uniq = set(), []
    for x in sorted(items, key=lambda i: -i["ts"]):
        if x["title"] in seen:
            continue
        seen.add(x["title"])
        uniq.append(x)
    if uniq:
        _cache["t"], _cache["items"] = time.time(), uniq
    return uniq[:limit]


if __name__ == "__main__":
    for n in fetch_news(8):
        print(f"[{n['source']}] {n['time']} {n['title']}")
