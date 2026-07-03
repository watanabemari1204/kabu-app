# -*- coding: utf-8 -*-
"""GitHub Actions用：生成済みhome.jsonから朝のTelegram通知を作って送る（Macが寝てても届く）"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import notify

APP_URL = os.environ.get("APP_URL", "https://watanabemari1204.github.io/kabu-app/")
WEEKDAYS = "月火水木金土日"


def pct(v):
    return f"{v:+.2f}%"


def main(home_path):
    with open(home_path) as f:
        h = json.load(f)
    jst = datetime.now(timezone(timedelta(hours=9)))
    lines = [f"📈 朝の株スキャン {jst.month}/{jst.day}({WEEKDAYS[jst.weekday()]}) ☁️クラウド版"]

    m = h.get("market") or {}
    if m:
        emoji = {"buy": "🔴", "neutral": "🟡", "sell": "🔵"}.get(m.get("side"), "")
        lines.append(f"\n【地合い】{emoji} {m.get('verdict', '')}")
        for r in m.get("rows", []):
            if not r.get("error"):
                lines.append(f"・{r['name']} {r['close']:,.2f}（{pct(r['chg_pct'])}）")

    picks = h.get("picks") or []
    medals = ["🥇", "🥈", "🥉"]
    if picks:
        lines.append("\n【今日のイチオシ】")
        for i, p in enumerate(picks):
            lines.append(f"{medals[i]} {p['name']}({p['code']}) {p['close']:,.0f}円 {pct(p['chg_pct'])}")
            lines.append(f"　{p['basis']}｜過去{p['n']}回・的中率{p['hit_rate']*100:.0f}%・平均{p['expected']*100:+.1f}%")
            lines.append(f"　目標 {p['target']:,.0f}円 / 損切り {p['stop']:,.0f}円")
    else:
        lines.append("\n【今日のイチオシ】該当なし（的中率55%以上の買い場が見つからない日。無理しないのが正解）")

    results = h.get("results") or []
    buys = [r for r in results if r["buys"] > 0 and r["sells"] == 0]
    sells = [r for r in results if r["sells"] > 0 and r["buys"] == 0]
    pick_codes = {p["code"] for p in picks}
    lines.append(f"\n【その他の新規シグナル】買い{len(buys)}銘柄 / 売り{len(sells)}銘柄（主要{h.get('universe')}銘柄中）")
    for r in [b for b in buys if b["code"] not in pick_codes][:5]:
        sigs = "、".join(s["name"] for s in r["signals"] if s["side"] == "buy")
        lines.append(f"🔺 {r['name']}({r['code']}) {r['close']:,.0f}円 {pct(r['chg_pct'])}｜{sigs}")
    for r in sells[:4]:
        sigs = "、".join(s["name"] for s in r["signals"] if s["side"] == "sell")
        lines.append(f"🔻 {r['name']}({r['code']}) {r['close']:,.0f}円 {pct(r['chg_pct'])}｜{sigs}")

    news_items = h.get("news") or []
    if news_items:
        lines.append("\n【経済ニュース】")
        for n in news_items[:5]:
            lines.append(f"・{n['title']}（{n['source']}）")

    lines.append(f"\n詳細 → {APP_URL}")
    text = "\n".join(lines)
    print(text)
    if not notify.send(text):
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "public/data/home.json")
