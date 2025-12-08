# -*- coding: utf-8 -*-
"""
Yahoo 股市 — 光寶科新聞抓取（2301.TW）
✔ 使用可用的 StockLatestNewsService API
✔ 過濾 72 小時內
✔ 搜尋 title / summary 中是否包含 光寶 / 光寶科 / 2301
"""

import requests
from datetime import datetime, timedelta

def fetch_liteon_yahoo_news():
    print("📡 正在抓取 Yahoo 股市 — 光寶科新聞 (2301.TW)…")

    API_URL = "https://tw.stock.yahoo.com/_td-stock/api/resource/StockLatestNewsService;limit=100;symbols=2301.TW"

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

        # 是否 72 小時內
        if pub_time < three_days_ago:
            continue

        # 是否與光寶科相關
        if not (
            "光寶" in title or "光寶科" in title or "2301" in title or
            "光寶" in summary or "光寶科" in summary or "2301" in summary
        ):
            continue

        results.append({
            "title": title,
            "summary": summary,
            "link": link,
            "pub_time": pub_time.strftime("%Y-%m-%d %H:%M:%S")
        })

    print(f"🔍 共抓到 {len(results)} 則光寶科股市新聞（3 天內）")
    print("🎉 光寶科股市新聞抓取完成！")

    return results


# 🔽 測試執行
if __name__ == "__main__":
    news = fetch_liteon_yahoo_news()
    for n in news:
        print(n)
