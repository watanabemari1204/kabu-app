# -*- coding: utf-8 -*-
"""テクニカル分析エンジン：指標計算・シグナル検出・過去検証（バックテスト）・予測"""
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf

HORIZON = 20      # 検証ホライズン：シグナル発生からの営業日数（約1ヶ月）
RECENT_BARS = 3   # 直近何営業日以内の発生を「アクティブなシグナル」とするか
CHART_BARS = 500  # フロントに返すチャートの本数


def fetch_history(symbol, period="10y"):
    df = yf.Ticker(symbol).history(period=period, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError(f"データが取得できません: {symbol}")
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def add_indicators(df):
    c = df["Close"]
    for n in (5, 25, 75, 200):
        df[f"sma{n}"] = c.rolling(n).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_sig"] = df["macd"].ewm(span=9, adjust=False).mean()
    m20, s20 = c.rolling(20).mean(), c.rolling(20).std()
    df["bb_up"], df["bb_dn"] = m20 + 2 * s20, m20 - 2 * s20
    return df


def _series(x, index):
    return x if isinstance(x, pd.Series) else pd.Series(x, index=index)


def _xup(a, b):
    b = _series(b, a.index)
    return (a > b) & (a.shift(1) <= b.shift(1))


def _xdn(a, b):
    b = _series(b, a.index)
    return (a < b) & (a.shift(1) >= b.shift(1))


SIGNALS = [
    dict(key="gc2575", name="ゴールデンクロス（25日/75日線）", side="buy",
         fn=lambda d: _xup(d["sma25"], d["sma75"]),
         desc="25日移動平均線が75日線を下から上に抜けた。中期の上昇トレンド入りを示す代表的な買いサイン。"),
    dict(key="dc2575", name="デッドクロス（25日/75日線）", side="sell",
         fn=lambda d: _xdn(d["sma25"], d["sma75"]),
         desc="25日移動平均線が75日線を上から下に抜けた。中期の下落トレンド入りを示す代表的な売りサイン。"),
    dict(key="gc525", name="短期ゴールデンクロス（5日/25日線）", side="buy",
         fn=lambda d: _xup(d["sma5"], d["sma25"]),
         desc="5日線が25日線を上抜け。短期の反発・上昇の初動を示すサイン。"),
    dict(key="dc525", name="短期デッドクロス（5日/25日線）", side="sell",
         fn=lambda d: _xdn(d["sma5"], d["sma25"]),
         desc="5日線が25日線を下抜け。短期の勢いが失われたサイン。"),
    dict(key="macd_up", name="MACDゴールデンクロス", side="buy",
         fn=lambda d: _xup(d["macd"], d["macd_sig"]) & (d["macd"] < 0),
         desc="マイナス圏でMACDがシグナル線を上抜け。下落の勢いが尽きて反転し始めたサイン。"),
    dict(key="macd_dn", name="MACDデッドクロス", side="sell",
         fn=lambda d: _xdn(d["macd"], d["macd_sig"]) & (d["macd"] > 0),
         desc="プラス圏でMACDがシグナル線を下抜け。上昇の勢いが失われたサイン。"),
    dict(key="rsi_reb", name="RSI売られすぎからの反発", side="buy",
         fn=lambda d: _xup(d["rsi"], 30),
         desc="RSIが売られすぎ圏（30以下）から回復。売られすぎの反動高が始まりやすいサイン。"),
    dict(key="rsi_cool", name="RSI買われすぎからの失速", side="sell",
         fn=lambda d: _xdn(d["rsi"], 70),
         desc="RSIが買われすぎ圏（70以上）から低下。過熱が冷めて調整に入りやすいサイン。"),
]


def backtest(df, mask, horizon=HORIZON):
    """過去にこのシグナルが出た全ての日について、horizon営業日後のリターンを検証"""
    close = df["Close"].values
    idx = np.where(mask.fillna(False).values)[0]
    events = [(df.index[i].strftime("%Y-%m-%d"), close[i + horizon] / close[i] - 1)
              for i in idx if i + horizon < len(close)]
    if not events:
        return None
    rets = np.array([r for _, r in events])
    wins, losses = rets[rets > 0], rets[rets <= 0]
    return dict(
        n=len(rets), win=int(len(wins)), win_rate=round(len(wins) / len(rets), 3),
        avg=round(float(rets.mean()), 4), med=round(float(np.median(rets)), 4),
        avg_win=round(float(wins.mean()), 4) if len(wins) else 0.0,
        avg_loss=round(float(losses.mean()), 4) if len(losses) else 0.0,
        best=round(float(rets.max()), 4), worst=round(float(rets.min()), 4),
        horizon=horizon,
        recent=[dict(date=d, ret=round(float(r), 4)) for d, r in events[-5:]],
    )


def _round_px(p):
    if p >= 5000:
        return round(p / 10) * 10
    if p >= 1000:
        return round(p)
    return round(p, 1)


def build_explanation(df):
    """今のチャート状態を日本語で説明する根拠リスト"""
    last = df.iloc[-1]
    c = last["Close"]
    out = []
    for n, label in ((25, "25日線（中期トレンド）"), (75, "75日線"), (200, "200日線（長期トレンド）")):
        s = last.get(f"sma{n}")
        if pd.notna(s):
            dev = (c / s - 1) * 100
            out.append(f"株価は{label}の{'上' if dev >= 0 else '下'}（乖離 {dev:+.1f}%）")
    s5, s25, s75, s200 = (last.get(f"sma{n}") for n in (5, 25, 75, 200))
    if all(pd.notna(x) for x in (s5, s25, s75, s200)):
        if s5 > s25 > s75 > s200:
            out.append("移動平均線が 5日>25日>75日>200日 の並び＝上昇トレンドの完成形（パーフェクトオーダー）")
        elif s5 < s25 < s75 < s200:
            out.append("移動平均線が 5日<25日<75日<200日 の並び＝下落トレンドの完成形。買いは慎重に")
    rsi = last.get("rsi")
    if pd.notna(rsi):
        zone = "売られすぎ圏" if rsi <= 30 else "買われすぎ圏" if rsi >= 70 else "中立圏"
        out.append(f"RSI(14) = {rsi:.0f}（{zone}）")
    if pd.notna(last.get("macd")) and pd.notna(last.get("macd_sig")):
        rel = "上" if last["macd"] > last["macd_sig"] else "下"
        zone = "プラス圏" if last["macd"] > 0 else "マイナス圏"
        out.append(f"MACDはシグナル線の{rel}・{zone}（{'上昇' if rel == '上' else '下落'}の勢い）")
    if pd.notna(last.get("bb_up")) and c > last["bb_up"]:
        out.append("株価がボリンジャーバンド+2σを超過＝統計的にかなり過熱した水準")
    elif pd.notna(last.get("bb_dn")) and c < last["bb_dn"]:
        out.append("株価がボリンジャーバンド-2σを下回る＝統計的にかなり売られた水準")
    return out


def analyze(symbol, display_name=None, df=None):
    if df is None:
        df = fetch_history(symbol)
    df = add_indicators(df)
    close = float(df["Close"].iloc[-1])
    prev = float(df["Close"].iloc[-2]) if len(df) > 1 else close

    active, all_events = [], []
    buy_score = sell_score = 0.0
    for sig in SIGNALS:
        mask = sig["fn"](df)
        stats = backtest(df, mask)
        if stats:
            # 的中率はサインの向きで判定：買い＝上昇したら的中、売り＝下落したら的中
            stats["hit_rate"] = stats["win_rate"] if sig["side"] == "buy" \
                else round(1 - stats["win_rate"], 3)
        for ts in df.index[mask.fillna(False)][-30:]:
            all_events.append(dict(date=ts.strftime("%Y-%m-%d"), side=sig["side"], name=sig["name"]))
        recent = mask.iloc[-RECENT_BARS:]
        if recent.any():
            fired = df.index[mask.fillna(False)][-1].strftime("%Y-%m-%d")
            active.append(dict(key=sig["key"], name=sig["name"], side=sig["side"],
                               desc=sig["desc"], fired=fired, stats=stats))
            weight = stats["hit_rate"] if stats and stats["n"] >= 5 else 0.5
            if sig["side"] == "buy":
                buy_score += weight
            else:
                sell_score += weight

    if not active:
        stance, stance_side = "新規シグナルなし（様子見）", "neutral"
    elif max(buy_score, sell_score) < 0.5:
        stance, stance_side = "シグナルあり・ただし過去的中率が低い（様子見）", "neutral"
    elif buy_score > sell_score:
        stance, stance_side = "買い優勢", "buy"
    elif sell_score > buy_score:
        stance, stance_side = "売り優勢（警戒）", "sell"
    else:
        stance, stance_side = "強弱拮抗（様子見）", "neutral"

    # 予測：アクティブな買いシグナルのうち検証回数が最多のものの統計を軸にする
    prediction = None
    basis = [a for a in active if a["side"] == stance_side and a["stats"] and a["stats"]["n"] >= 5]
    if basis:
        best = max(basis, key=lambda a: a["stats"]["n"])
        st = best["stats"]
        low20 = float(df["Low"].iloc[-20:].min())
        if stance_side == "buy":
            target = _round_px(close * (1 + st["avg_win"]))
            stop = _round_px(max(low20, close * (1 + st["avg_loss"])))
            if stop >= close * 0.995:
                stop = _round_px(close * 0.95)
            prediction = dict(
                side="buy", target=target, stop=stop, horizon=st["horizon"],
                basis_signal=best["name"], hit_rate=st["hit_rate"], n=st["n"],
                expected=st["avg"],
                note=(f"「{best['name']}」は過去{st['n']}回発生し、{st['horizon']}営業日後に"
                      f"{st['win']}回上昇（勝率{st['win_rate']*100:.0f}%・平均{st['avg']*100:+.1f}%）。"
                      f"勝ったときの平均+{st['avg_win']*100:.1f}%から目標{target:,}円、"
                      f"負けたときの平均{st['avg_loss']*100:.1f}%と直近20日安値から損切り{stop:,}円を算出。"),
            )
        else:
            target = _round_px(close * (1 + st["avg"]))
            if st["avg"] < 0:
                tail_note = "統計的には下押しリスクが高い局面。買いは見送り、保有中なら利益確保・損切りルールの確認を。"
            else:
                tail_note = ("ただしこの銘柄では過去、平均するとサイン後もプラスで推移しており、"
                             "売りサインの信頼度は高くない。新規買いだけ慎重に。")
            prediction = dict(
                side="sell", target=target, stop=None, horizon=st["horizon"],
                basis_signal=best["name"], hit_rate=st["hit_rate"], n=st["n"],
                expected=st["avg"],
                note=(f"「{best['name']}」は過去{st['n']}回発生し、{st['horizon']}営業日後に"
                      f"{st['n']-st['win']}回下落（的中率{st['hit_rate']*100:.0f}%・平均{st['avg']*100:+.1f}%）。"
                      + tail_note),
            )

    tail = df.iloc[-CHART_BARS:]
    dates = [d.strftime("%Y-%m-%d") for d in tail.index]
    window = set(dates)

    def col(name, digits=2):
        return [None if pd.isna(v) else round(float(v), digits) for v in tail[name]]

    chart = dict(
        dates=dates, open=col("Open"), high=col("High"), low=col("Low"),
        close=col("Close"), volume=[int(v) if pd.notna(v) else 0 for v in tail["Volume"]],
        sma5=col("sma5"), sma25=col("sma25"), sma75=col("sma75"), sma200=col("sma200"),
        markers=[e for e in all_events if e["date"] in window],
    )

    return dict(
        symbol=symbol, name=display_name or symbol,
        close=close, chg=round(close - prev, 2),
        chg_pct=round((close / prev - 1) * 100, 2) if prev else 0,
        last_date=dates[-1], stance=stance, stance_side=stance_side,
        signals=active, explanation=build_explanation(df),
        prediction=prediction, chart=chart,
    )


def _fmt_jpy_cap(v):
    if not v:
        return None
    if v >= 1e12:
        return f"{v/1e12:,.2f}兆円"
    return f"{v/1e8:,.0f}億円"


def get_company(symbol):
    """企業情報（指数・為替はNone）"""
    if symbol.startswith("^") or "=" in symbol:
        return None
    t = yf.Ticker(symbol)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    if not info.get("longName") and not info.get("shortName"):
        return None
    dy = info.get("dividendYield")
    if dy is not None and dy < 1:  # 比率で返るバージョン対策
        dy = dy * 100
    roe = info.get("returnOnEquity")
    earnings = None
    try:
        cal = t.calendar or {}
        ed = cal.get("Earnings Date") or []
        if ed:
            earnings = str(ed[0])
    except Exception:
        pass
    news = []
    try:
        for item in (t.news or [])[:5]:
            content = item.get("content", item)
            title = content.get("title")
            url = (content.get("canonicalUrl") or {}).get("url") or item.get("link")
            if title:
                news.append(dict(title=title, url=url))
    except Exception:
        pass
    return dict(
        long_name=info.get("longName") or info.get("shortName"),
        sector=info.get("sector"), industry=info.get("industry"),
        market_cap=_fmt_jpy_cap(info.get("marketCap")),
        per=info.get("trailingPE"), forward_per=info.get("forwardPE"),
        pbr=info.get("priceToBook"),
        dividend_yield=round(dy, 2) if dy is not None else None,
        roe=round(roe * 100, 1) if roe is not None else None,
        revenue=_fmt_jpy_cap(info.get("totalRevenue")),
        high52=info.get("fiftyTwoWeekHigh"), low52=info.get("fiftyTwoWeekLow"),
        website=info.get("website"), earnings_date=earnings,
        summary=(info.get("longBusinessSummary") or "")[:300] or None,
        news=news,
    )


MARKET_ITEMS = [("^N225", "日経平均"), ("^GSPC", "S&P500"), ("^IXIC", "ナスダック"),
                ("JPY=X", "ドル円"), ("^VIX", "VIX恐怖指数")]


def market_overview():
    """地合い判定：主要指数の位置から「攻め/中立/守り」を出す"""
    rows, score = [], 0.0
    for sym, name in MARKET_ITEMS:
        try:
            df = fetch_history(sym, period="6mo")
        except Exception:
            rows.append(dict(symbol=sym, name=name, error=True))
            continue
        close = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])
        sma25 = float(df["Close"].rolling(25).mean().iloc[-1])
        chg = (close / prev - 1) * 100
        above = close > sma25
        rows.append(dict(symbol=sym, name=name, close=round(close, 2),
                         chg_pct=round(chg, 2), above_sma25=above))
        if sym == "^N225":
            score += (1 if above else 0) + (0.5 if chg > 0 else 0)
        elif sym == "^GSPC":
            score += (1 if above else 0) + (0.5 if chg > 0 else 0)
        elif sym == "^IXIC":
            score += 0.5 if above else 0
        elif sym == "^VIX":
            score += 1 if close < 20 else (-1 if close > 25 else 0)
    if score >= 3:
        verdict, side = "攻めOK（リスクオン）", "buy"
    elif score >= 1.5:
        verdict, side = "中立", "neutral"
    else:
        verdict, side = "守り（リスクオフ）", "sell"
    return dict(rows=rows, score=score, verdict=verdict, side=side)


def screen_universe(universe):
    """ユニバース全銘柄から直近RECENT_BARS日以内にシグナルが出た銘柄を抽出"""
    symbols = [c + ".T" for c, _ in universe]
    data = yf.download(symbols, period="2y", interval="1d", group_by="ticker",
                       auto_adjust=True, progress=False, threads=True)
    results = []
    for code, name in universe:
        sym = code + ".T"
        try:
            df = data[sym].dropna(subset=["Close"]).copy()
        except Exception:
            continue
        if len(df) < 80:
            continue
        df = add_indicators(df)
        close = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])
        hits = []
        for sig in SIGNALS:
            mask = sig["fn"](df)
            recent = mask.iloc[-RECENT_BARS:]
            if recent.any():
                fired = df.index[mask.fillna(False)][-1].strftime("%m/%d")
                hits.append(dict(key=sig["key"], name=sig["name"], side=sig["side"], fired=fired))
        if hits:
            buys = sum(1 for h in hits if h["side"] == "buy")
            sells = len(hits) - buys
            results.append(dict(code=code, name=name, close=close,
                                chg_pct=round((close / prev - 1) * 100, 2),
                                signals=hits, buys=buys, sells=sells))
    results.sort(key=lambda r: (-(r["buys"] - r["sells"]), -r["buys"]))
    return results


def pick_daily(results, max_candidates=10, top=3):
    """スクリーニング結果から「今日のイチオシ」を選ぶ。
    買いシグナルだけが出ている銘柄を過去10年バックテストにかけ、
    的中率55%以上のものを 的中率×期待リターン で採点して上位を返す。
    自信を持てる銘柄がなければ空リスト（＝無理に推さない）。"""
    cand = [r for r in results if r["buys"] > 0 and r["sells"] == 0][:max_candidates]
    picks = []
    for r in cand:
        try:
            a = analyze(r["code"] + ".T", r["name"])
        except Exception:
            continue
        p = a.get("prediction")
        if not p or p["side"] != "buy" or p["hit_rate"] < 0.55:
            continue
        picks.append(dict(
            code=r["code"], name=r["name"], close=a["close"], chg_pct=a["chg_pct"],
            target=p["target"], stop=p["stop"], hit_rate=p["hit_rate"], n=p["n"],
            expected=p["expected"], horizon=p["horizon"], basis=p["basis_signal"],
            signals=[s["name"] for s in a["signals"] if s["side"] == "buy"],
            score=round(p["hit_rate"] * max(p["expected"], 0), 5),
        ))
    picks.sort(key=lambda x: -x["score"])
    return picks[:top]
