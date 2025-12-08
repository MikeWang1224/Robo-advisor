# -*- coding: utf-8 -*-
"""
liteon_news_google15.py

限制：
- Google News RSS 抓取最多 15 則（最終存入 Firestore 的也是最多 15 則）
- 僅保存 title / content / published_time / source
"""

import os
import re
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import feedparser
import firebase_admin
from firebase_admin import credentials, firestore

# ---------- Firestore 初始化 ----------
cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------- 公用函式 ----------
def fetch_article(url, max_len=2000):
    """抓取文章全文"""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        return text[:max_len]
    except:
        return "(抓取失敗)"

def contains_keyword(text):
    """判斷是否含光寶科關鍵字"""
    keywords = ["光寶科", "光寶", "2301"]
    return any(k in text for k in keywords)

def is_recent(published_time_str):
    """是否在兩天內"""
    try:
        dt = datetime.strptime(published_time_str, "%Y-%m-%d %H:%M:%S")
        return dt >= datetime.now() - timedelta(days=2)
    except:
        return False

# ---------- Google News RSS ----------
def fetch_google_news_liteon(limit=15):
    news = []
    rss_url = "https://news.google.com/rss/search?q=光寶科&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"

    try:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:limit]:  # RSS 最多只抓 15
            title = entry.get("title", "")
            link = entry.get("link", "")

            # 文章內容
            content = fetch_article(link)

            # 關鍵字過濾
            if not contains_keyword(title) and not contains_keyword(content):
                continue

            # 時間檢查
            if entry.get("published_parsed"):
                published_time = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M:%S")
            else:
                published_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if not is_recent(published_time):
                continue

            news.append({
                "title": title,
                "content": content,
                "source": "Google News",
                "published_time": published_time
            })

            # **最終限制：不能超過 15 則**
            if len(news) >= limit:
                break

    except Exception as e:
        print("RSS 抓取錯誤：", e)

    return news

# ---------- 寫入 Firestore ----------
def save_to_firestore(news_list):
    today = datetime.now().strftime("%Y%m%d")
    doc_ref = db.collection("NEWS_LiteOn").document(today)

    data = {f"news_{i}": news for i, news in enumerate(news_list, 1)}

    doc_ref.set(data, merge=True)
    print(f"✔ 已新增 {len(news_list)} 則新聞到 Firestore: NEWS_LiteOn/{today}")

# ---------- 主程式 ----------
def main():
    print("▶ 正在抓取光寶科新聞（最多 15 則）...")
    news_list = fetch_google_news_liteon(limit=15)

    if not news_list:
        print("⚠ 沒抓到資料")
        return

    save_to_firestore(news_list)

if __name__ == "__main__":
    main()
