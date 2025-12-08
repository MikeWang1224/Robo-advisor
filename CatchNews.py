# -*- coding: utf-8 -*-
"""
Yahoo 股市 — 光寶科新聞抓取（2301.TW）
✔ 不用 API（避免 Yahoo 400）
✔ 直接抓取 quote 頁面 embedded JSON
✔ 過濾 72 小時內新聞
✔ 自動寫入 Firestore /NEWS_LiteOn/{YYYYMMDD}
"""

import os
import re
import json
import requests
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore


# -----------------------------
# Firebase 初始化
# -----------------------------
cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
firebase_admin.initialize_app(cred)
db = firestore.client()


# -----------------------------
# 主抓取函式：解析 Yahoo quote embedded JSON
# -----------------------------
def fetch_liteon_news():
    print("📡 正在抓取 Yahoo 股市 — 光寶科新聞 (2301.TW)…")

    url = "https://tw.stock.yahoo.com/quote/2301.TW/news"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print("[Error] 抓取 HTML 失敗：", e)
        return []

    html = r.text

    # -----------------------------
    # 抓 embedded JSON
    # -----------------------------
    # Yahoo 網頁中會有 window.YAHOO.context = {...}
    match = re.search(r'root\.App\.main = ({.*?});', html)
    if not match:
        print("❗ 找不到 Yahoo embedded JSON")
        return []

    try:
        data = json.loads(match.group(1))
    except:
        print("❗ Yahoo JSON 解析失敗")
        return []

    # -----------------------------
    # 找新聞資料的位置
    # -----------------------------
    try:
        news_items = (
            data["context"]["dispatcher"]["stores"]["QuoteNewsStore"]["newsList"]["2301.TW"]
        )
    except:
        print("❗ 找不到新聞項目")
        return []

    now = datetime.now()
    three_days_ago = now - timedelta(days=3)

    results = []

    for item in news_items:
        title = item.get("title", "")
        summary = item.get("summary", "")
        link = "https://tw.stock.yahoo.com" + item.get("link", "")
        pub_ts = item.get("publisherTime", 0)  # 毫秒
        pub_time = datetime.fromtimestamp(pub_ts / 1000)

        # 72 小時內
        if pub_time < three_days_ago:
            continue

        # 關鍵字
        if not any(k in (title + summary) for k in ["光寶", "光寶科", "2301"]):
            continue

        results.append({
            "title": title,
            "summary": summary,
            "link": link,
            "pub_time": pub_time
        })

    print(f"🔍 共抓到 {len(results)} 則光寶科股市新聞（3 天內）")
    print("🎉 光寶科股市新聞抓取完成！")
    return results


# -----------------------------
# Firestore 寫入
# -----------------------------
def save_news_to_firestore(news_list):
    if not news_list:
        print("⚠️ 沒有新聞可寫入 Firestore")
        return

    doc_id = datetime.now().strftime("%Y%m%d")
    ref = db.collection("NEWS_LiteOn").document(doc_id)

    data = {}

    for i, n in enumerate(news_list, 1):
        data[f"news_{i}"] = {
            "title": n["title"],
            "summary": n["summary"],
            "link": n["link"],
            "published_time": n["pub_time"].strftime("%Y-%m-%d %H:%M:%S"),
            "source": "Yahoo 股市"
        }

    ref.set(data, merge=False)
    print(f"✅ 已寫入 Firestore：/NEWS_LiteOn/{doc_id}")


# -----------------------------
# 主程式
# -----------------------------
if __name__ == "__main__":
    news = fetch_liteon_news()
    save_news_to_firestore(news)
