# -*- coding: utf-8 -*-
"""
光寶科新聞抓取（Yahoo + 鉅亨網）
修復：Yahoo JSON 結構變動 → 自動 fallback 到 HTML 解析
"""

import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

TARGET = ["光寶科", "光寶", "2301"]
MAX_HOURS = 72  # 只抓 3 天內的新聞

def in_range(publish_time):
    """判斷是否在 72 小時內"""
    now = datetime.now()
    return (now - publish_time).total_seconds() <= MAX_HOURS * 3600

def fetch_yahoo_json():
    """新版 Yahoo JSON 抓取"""
    try:
        url = "https://tw.stock.yahoo.com/_td-stock/api/resource/StockNewsListService.newsList?symbol=2301.TW"
        headers = {"User-Agent": "Mozilla/5.0"}
        data = requests.get(url, headers=headers, timeout=10).json()

        # JSON 新版格式 → data["data"]["list"]
        news_list = data.get("data", {}).get("list", [])
        results = []

        for n in news_list:
            title = n.get("title", "")
            link = "https://tw.stock.yahoo.com" + n.get("link", "")
            ts = n.get("pubDate", 0) / 1000  # 13-digit timestamp
            publish_time = datetime.fromtimestamp(ts)

            if any(k in title for k in TARGET) and in_range(publish_time):
                results.append({
                    "title": title,
                    "link": link,
                    "time": publish_time.strftime("%Y-%m-%d %H:%M")
                })

        return results

    except Exception:
        return None  # 代表 JSON 解析失敗


def fetch_yahoo_html():
    """Yahoo HTML 版本備援解析"""
    url = "https://tw.stock.yahoo.com/quote/2301.TW/news"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")

    blocks = soup.select("li.js-stream-content")
    results = []

    for b in blocks:
        title = b.select_one("h3").get_text(strip=True)
        link = "https://tw.stock.yahoo.com" + b.select_one("a")["href"]

        # 擷取日期
        time_text = b.select_one("span").get_text(strip=True)
        try:
            if "天" in time_text:
                hours_ago = int(time_text.replace("天前", "")) * 24
                publish_time = datetime.now() - timedelta(hours=hours_ago)
            elif "小時" in time_text:
                hours_ago = int(time_text.replace("小時前", ""))
                publish_time = datetime.now() - timedelta(hours=hours_ago)
            else:
                publish_time = datetime.now()
        except:
            publish_time = datetime.now()

        if any(k in title for k in TARGET) and in_range(publish_time):
            results.append({
                "title": title,
                "link": link,
                "time": publish_time.strftime("%Y-%m-%d %H:%M")
            })

    return results


def fetch_chinatimes():
    """抓取鉅亨網"""
    url = "https://news.cnyes.com/search?keyword=光寶科"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    blocks = soup.select("a._1Zdp")

    for b in blocks:
        title = b.get_text(strip=True)
        link = "https://news.cnyes.com" + b["href"]

        # 無法直接抓時間 → 略過時間檢查
        if any(k in title for k in TARGET):
            results.append({
                "title": title,
                "link": link,
                "time": "N/A"
            })

    return results


def fetch_all():
    print("📡 正在抓取 Yahoo 股市 — 光寶科新聞 (2301.TW)…")

    yahoo_json = fetch_yahoo_json()

    if yahoo_json is None:
        print("❗ Yahoo JSON 解析失敗 → 改用 HTML 抓取…")
        yahoo_data = fetch_yahoo_html()
    else:
        yahoo_data = yahoo_json

    print(f"✔ Yahoo 取得 {len(yahoo_data)} 則")

    print("📡 正在抓取 鉅亨網…")
    cnyes = fetch_chinatimes()
    print(f"✔ 鉅亨網 取得 {len(cnyes)} 則")

    all_news = yahoo_data + cnyes

    if not all_news:
        print("⚠️ 沒有新聞可寫入 Firestore")
    else:
        print(f"📦 共 {len(all_news)} 則新聞")

    return all_news


if __name__ == "__main__":
    fetch_all()
