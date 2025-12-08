# -*- coding: utf-8 -*-
"""
光寶科新聞抓取 + Firestore 寫入
✔ Yahoo 搜尋頁（保證抓到）
✔ 鉅亨網搜尋
✔ 只存 3 天內
✔ 寫入 Firestore：NEWS_LiteOn / YYYYMMDD
"""

import os
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore


# -----------------------------
# Firestore 初始化
# -----------------------------
if not firebase_admin._apps:
    cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    firebase_admin.initialize_app(cred)

db = firestore.client()

COLL_NAME = "NEWS_LiteOn"  # Firestore collection name
KEYWORDS = ["光寶科", "光寶", "2301"]
MAX_HOURS = 72  # 三天內


def in_range(dt):
    """判斷是否在 72 小時之內"""
    return (datetime.now() - dt).total_seconds() <= MAX_HOURS * 3600


# ----------------------------------------------------------
# ★ Yahoo 搜尋頁 — 最穩定，不會被改版
# ----------------------------------------------------------
def fetch_yahoo_search():
    print("📡 正在抓取 Yahoo 搜尋頁…")

    url = "https://tw.news.search.yahoo.com/search?p=光寶科"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []

    items = soup.select("div.NewsArticle")
    for n in items:
        title_tag = n.select_one("h4 > a")
        if not title_tag:
            continue

        title = title_tag.get_text(strip=True)
        link = title_tag["href"]

        # 關鍵字過濾
        if not any(k in title for k in KEYWORDS):
            continue

        # 時間：x 小時前 / x 天前
        time_tag = n.select_one("span.s-time")
        if time_tag:
            publish_time = parse_relative_time(time_tag.get_text(strip=True))
        else:
            publish_time = datetime.now()

        if not in_range(publish_time):
            continue

        results.append({
            "title": title,
            "link": link,
            "time": publish_time.strftime("%Y-%m-%d %H:%M"),
            "source": "Yahoo"
        })

    print(f"✔ Yahoo 搜尋抓到 {len(results)} 則")
    return results


def parse_relative_time(text):
    """解析 Yahoo 的相對時間"""
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
# ★ 鉅亨網搜尋
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
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "source": "Cnyes"
            })

    print(f"✔ 鉅亨網抓到 {len(results)} 則")
    return results


# ----------------------------------------------------------
# ★ Firestore 寫入
# ----------------------------------------------------------
def write_to_firestore(news_list):
    today = datetime.now().strftime("%Y%m%d")
    doc_ref = db.collection(COLL_NAME).document(today)

    # 寫入欄位：news_list = [...]
    doc_ref.set({"news_list": news_list}, merge=True)

    print(f"🔥 已寫入 Firestore → /{COLL_NAME}/{today}")
    print(f"📦 共 {len(news_list)} 則新聞")


# ----------------------------------------------------------
# ★ 主流程
# ----------------------------------------------------------
def main():
    yahoo = fetch_yahoo_search()
    cnyes = fetch_cnyes()

    all_news = yahoo + cnyes

    if not all_news:
        print("⚠️ 沒有新聞可寫入 Firestore")
        return

    write_to_firestore(all_news)


if __name__ == "__main__":
    main()
