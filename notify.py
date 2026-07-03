# -*- coding: utf-8 -*-
"""Telegram通知（@mariwatanabe_bot 経由でまりに送る）"""
import json
import os
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE, "..", ".env")
CHAT_ID_PATH = os.path.join(BASE, "..", "auto_poster", ".telegram_chat_id")
FALLBACK_CHAT_ID = "8764148451"


def _token():
    try:
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith("TELEGRAM_TOKEN"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return os.environ.get("TELEGRAM_TOKEN")


def _chat_id():
    try:
        with open(CHAT_ID_PATH) as f:
            return f.read().strip() or FALLBACK_CHAT_ID
    except OSError:
        return FALLBACK_CHAT_ID


def send(text):
    """4096字制限があるので分割して送る。成功すればTrue"""
    token = _token()
    if not token:
        print("TELEGRAM_TOKEN が見つかりません")
        return False
    ok = True
    chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)] or [text]
    for chunk in chunks:
        data = urllib.parse.urlencode({"chat_id": _chat_id(), "text": chunk}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                ok = ok and json.load(res).get("ok", False)
        except Exception as e:
            print("Telegram送信エラー:", e)
            ok = False
    return ok


if __name__ == "__main__":
    import sys
    send(sys.argv[1] if len(sys.argv) > 1 else "📈 株分析アプリ：通知テスト")
