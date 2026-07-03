# -*- coding: utf-8 -*-
"""GitHub Actions用：全銘柄を一括分析して静的JSONを書き出す
出力: <out>/home.json（地合い・イチオシ・スクリーニング・ニュース）
      <out>/stocks/<code>.json（銘柄ごとのフル分析）
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import yfinance as yf

import analysis
import news
import tickers

analysis.CHART_BARS = 300  # クラウド版はファイルサイズ節約のため約1年強に絞る

INDICES = [("^N225", "日経平均", "n225"), ("JPY=X", "ドル円", "usdjpy"),
           ("^GSPC", "S&P500", "gspc")]


def dump(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def main(out):
    os.makedirs(os.path.join(out, "stocks"), exist_ok=True)
    symbols = [c + ".T" for c, _ in tickers.UNIVERSE]
    batch = yf.download(symbols, period="10y", interval="1d", group_by="ticker",
                        auto_adjust=True, progress=False, threads=True)

    analyses, screen = {}, []
    for code, name in tickers.UNIVERSE:
        sym = code + ".T"
        try:
            df = batch[sym].dropna(subset=["Close"]).copy()
        except Exception:
            continue
        if len(df) < 80:
            continue
        try:
            df.index = df.index.tz_localize(None)
        except (TypeError, AttributeError):
            pass
        try:
            a = analysis.analyze(sym, name, df=df[["Open", "High", "Low", "Close", "Volume"]])
        except Exception as e:
            print(f"skip {code}: {e}")
            continue
        analyses[code] = a
        if a["signals"]:
            buys = sum(1 for s in a["signals"] if s["side"] == "buy")
            screen.append(dict(
                code=code, name=name, close=a["close"], chg_pct=a["chg_pct"],
                signals=[dict(name=s["name"], side=s["side"],
                              fired=s["fired"][5:].replace("-", "/")) for s in a["signals"]],
                buys=buys, sells=len(a["signals"]) - buys))
    screen.sort(key=lambda r: (-(r["buys"] - r["sells"]), -r["buys"]))

    picks = []
    for r in screen:
        if r["buys"] == 0 or r["sells"] > 0:
            continue
        p = analyses[r["code"]].get("prediction")
        if not p or p["side"] != "buy" or p["hit_rate"] < 0.55:
            continue
        picks.append(dict(code=r["code"], name=r["name"], close=r["close"],
                          chg_pct=r["chg_pct"], target=p["target"], stop=p["stop"],
                          hit_rate=p["hit_rate"], n=p["n"], expected=p["expected"],
                          horizon=p["horizon"], basis=p["basis_signal"],
                          score=round(p["hit_rate"] * max(p["expected"], 0), 5)))
    picks.sort(key=lambda x: -x["score"])
    picks = picks[:3]
    for p in picks:  # 企業情報はAPI節約のためイチオシ3銘柄だけ
        try:
            analyses[p["code"]]["company"] = analysis.get_company(p["code"] + ".T")
        except Exception:
            pass

    for code, a in analyses.items():
        dump(os.path.join(out, "stocks", f"{code}.json"), a)
    for sym, name, fname in INDICES:
        try:
            dump(os.path.join(out, "stocks", f"{fname}.json"), analysis.analyze(sym, name))
        except Exception as e:
            print(f"skip {fname}: {e}")

    jst = datetime.now(timezone(timedelta(hours=9)))
    home = dict(date=jst.strftime("%Y-%m-%d"), generated=jst.strftime("%H:%M"),
                universe=len(tickers.UNIVERSE), universe_list=tickers.UNIVERSE,
                market=analysis.market_overview(),
                results=screen, picks=picks, news=news.fetch_news(12))
    dump(os.path.join(out, "home.json"), home)
    print(f"analyzed={len(analyses)} signals={len(screen)} picks={len(picks)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="public/data")
    main(ap.parse_args().out)
