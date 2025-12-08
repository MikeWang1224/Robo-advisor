# -*- coding: utf-8 -*-
"""
Yahoo 股市 — 光寶科新聞抓取（2301.TW）
✔ 可用 Yahoo API（不會 400）
✔ 過濾 72 小時內新聞
✔ 自動寫入 Firestore /NEWS_LiteOn/{YYYYMMDD}
"""

import os
import requests
import urllib.parse
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
# Yahoo 光寶科 API 抓取
# -----------------------------
def fetch_liteon_yahoo_news():
    print("📡 正在抓取 Yahoo 股市 — 光寶科新聞 (2301.TW)…")

    # Yahoo API 必需 JSON + URL Encode，否則 400
    query = {
        "symbols": ["2301.TW"],
        "limit": 50
    }
    # Yahoo 必須使用 JSON 格式
    encoded = urllib.parse.quote(str(query).replace("'", '"'))

    API_URL = (
        "https://tw.stock.yahoo.com/_td-stock/api/resource/"
        f"StockLatestNewsService;url={encoded}"
    )

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }

    try:
        r = requests.get(API_URL, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[Error] API 抓取錯誤：{e}")
        print("❗ URL：", API_URL)
        return []

    news_items = data.get("items", [])
    results = []

    now = datetime.now()
    three_days_ago = now - timedelta(days=3)

    for item in news_items:
        title = item.get("title", "")
        summary = item.get("summary", "")
        link = "https://tw.stock.yahoo.com" + item.get("link", "")
        pub_ms = item.get("pubDate", 0)
        pub_time = datetime.fromtimestamp(pub_ms / 1000)

        # 時間過濾（72 小時）
        if pub_time < three_days_ago:
            continue

        # 關鍵字過濾
        if not (
            "光寶" in title or "光寶科" in title or "2301" in title or
            "光寶" in summary or "光寶科" in summary or "2301" in summary
        ):
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

    # 覆蓋整份文件（清空舊資料）
    ref.set(data, merge=False)

    print(f"✅ 已寫入 Firestore：/NEWS_LiteOn/{doc_id}")


# -----------------------------
# 主程式
# -----------------------------
if __name__ == "__main__":
    news = fetch_liteon_yahoo_news()
    save_news_to_firestore(news)
