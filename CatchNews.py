# -*- coding: utf-8 -*-
"""
liteon_news_google15.py

功能：
- 抓取光寶科 (2301) 最近兩天新聞
- Google News RSS 每次最多抓 15 則
- 只儲存 title + content + published_time + source
- 不做 AI 分析，也不存 ai_analyzed / ai_error
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
    """判斷是否在最近兩天內"""
    try:
        dt = datetime.strptime(published_time_str, "%Y-%m-%d %H:%M:%S")
        return dt >= datetime.now() - timedelta(days=2)
    except:
        return False

# ---------- Google News RSS ----------
def fetch_google_news_liteon(limit=15):
    result = []
    try:
        rss_url = "https://news.google.com/rss/search?q=光寶科&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        feed = feedparser.parse(rss_url)
        count = 0
        for entry in feed.entries:
            if count >= limit:
                break
            title = entry.get("title", "")
            link = entry.get("link", "")
            content = fetch_article(link)
            if not contains_keyword(title) and not contains_keyword(content):
                continue
            published_time = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M:%S") if entry.get("published_parsed") else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if not is_recent(published_time):
                continue
            result.append({
                "title": title,
                "content": content,
                "source": "Google News",
                "published_time": published_time
            })
            count += 1
    except:
        pass
    return result

# ---------- 寫入 Firestore ----------
def save_to_firestore(news_list):
    today = datetime.now().strftime("%Y%m%d")
    doc_ref = db.collection("NEWS_LiteOn").document(today)
    data = {}
    for i, news in enumerate(news_list, 1):
        data[f"news_{i}"] = news
    doc_ref.set(data, merge=True)
    print(f"✔ 已新增 {len(news_list)} 則新聞到 Firestore: NEWS_LiteOn/{today}")

# ---------- 主程式 ----------
def main():
    print("▶ 正在抓取光寶科新聞 (Google News 15則限制)...")
    news_list = []
    news_list.extend(fetch_google_news_liteon(limit=15))
    if not news_list:
        print("⚠ 沒抓到資料")
        return
    save_to_firestore(news_list)

if __name__ == "__main__":
    main()
