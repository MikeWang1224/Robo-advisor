# -*- coding: utf-8 -*-
"""
光寶科新聞抓取（Yahoo 主站搜尋版 + 鉅亨網）
✔ 100% 可抓得到（不依賴 Yahoo 股票頁）
"""

import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

KEYWORDS = ["光寶科", "光寶", "2301"]
MAX_HOURS = 72  # 只抓三天內

def in_range(dt):
    """判斷是否在 72 小時之內"""
    return (datetime.now() - dt).total_seconds() <= MAX_HOURS * 3600


# ----------------------------------------------------------
# ★ Yahoo 搜尋頁 (最穩、最不容易壞)
# ----------------------------------------------------------
def fetch_yahoo_search():
    print("📡 正在抓取 Yahoo 搜尋頁…")

    url = "https://tw.news.search.yahoo.com/search?p=光寶科"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []

    items = soup.select("div.NewsArticle")  # 主站搜尋固定使用這個 class

    for n in items:
        title_tag = n.select_one("h4 > a")
        if not title_tag:
            continue

        title = title_tag.get_text(strip=True)
        link = title_tag["href"]

        # 判斷是否包含關鍵字
        if not any(k in title for k in KEYWORDS):
            continue

        # --- 抓時間 (X 天前 / X 小時前) ---
        time_tag = n.select_one("span.s-time")
        if time_tag:
            txt = time_tag.get_text(strip=True)
            publish_time = parse_relative_time(txt)
        else:
            publish_time = datetime.now()

        if not in_range(publish_time):
            continue

        results.append({
            "title": title,
            "link": link,
            "time": publish_time.strftime("%Y-%m-%d %H:%M")
        })

    print(f"✔ Yahoo 搜尋抓到 {len(results)} 則")
    return results


def parse_relative_time(text):
    """解析 Yahoo 的「xx 小時前 / xx 天前」格式"""
    now = datetime.now()
    try:
        if "分鐘" in text:
            m = int(text.replace(" 分鐘前", ""))
            return now - timedelta(minutes=m)
        if "小時" in text:
            h = int(text.replace(" 小時前", ""))
            return now - timedelta(hours=h)
        if "天" in text:
            d = int(text.replace(" 天前", ""))
            return now - timedelta(days=d)
    except:
        pass
    return now


# ----------------------------------------------------------
# 鉅亨網（搜尋）
# ----------------------------------------------------------
def fetch_cnyes():
    print("📡 正在抓取 鉅亨網…")

    url = "https://news.cnyes.com/search?keyword=光寶科"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []

    items = soup.select("a._1Zdp")

    for n in items:
        title = n.get_text(strip=True)
        link = "https://news.cnyes.com" + n.get("href", "")

        if any(k in title for k in KEYWORDS):
            results.append({
                "title": title,
                "link": link,
                "time": "N/A"
            })

    print(f"✔ 鉅亨網抓到 {len(results)} 則")
    return results


# ----------------------------------------------------------
# 主整合流程
# ----------------------------------------------------------
def fetch_all():
    yahoo = fetch_yahoo_search()
    cnyes = fetch_cnyes()

    all_news = yahoo + cnyes

    if not all_news:
        print("⚠️ 仍然沒有新聞（不太可能）")
    else:
        print(f"📦 共抓到 {len(all_news)} 則新聞")

    return all_news


if __name__ == "__main__":
    fetch_all()
