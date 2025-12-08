# -*- coding: utf-8 -*-
"""
liteon_news_google15.py

- 以 entry.published 判斷兩天內
- 最終最多 15 則
- 使用 Base64 金鑰 NEW_FIREBASE_KEY_B64 初始化 Firestore
"""

import os
import re
import json
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import feedparser
import firebase_admin
from firebase_admin import credentials, firestore
import base64

# ---------- Firestore 初始化（使用 Base64 金鑰 NEW_FIREBASE_KEY_B64） ----------
key_b64 = os.environ.get("NEW_FIREBASE_KEY_B64")
if not key_b64:
    raise ValueError("❌ 找不到 NEW_FIREBASE_KEY_B64 環境變數")

key_json = base64.b64decode(key_b64)
cred = credentials.Certificate(json.loads(key_json))
firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------- 公用函式 ----------
def fetch_article(url, max_len=2000):
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
    keywords = ["光寶科", "光寶", "2301"]
    return any(k in text for k in keywords)

def is_recent(published_dt):
    """published_dt 是 datetime 物件，判斷是否兩天內"""
    if not published_dt:
        return False
    return published_dt >= datetime.now() - timedelta(days=2)

# ---------- Google News RSS ----------
def fetch_google_news_liteon(limit=15):
    news = []
    rss_url = "https://news.google.com/rss/search?q=光寶科&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"

    try:
        feed = feedparser.parse(rss_url)

        for entry in feed.entries[:limit]:

            # -------- 解析 published_time --------
            published_dt = None

            if entry.get("published_parsed"):
                published_dt = datetime(*entry.published_parsed[:6])
            else:
                # 嘗試 "YYYY-MM-DD HH:MM:SS" 格式
                published_raw = entry.get("published", "")
                try:
                    published_dt = datetime.strptime(published_raw, "%Y-%m-%d %H:%M:%S")
                except:
                    published_dt = None

            # 時間過濾（僅保留最近兩天）
            if not is_recent(published_dt):
                continue

            # -------- 標題 / 連結 / 內容 --------
            title = entry.get("title", "")
            link = entry.get("link", "")
            content = fetch_article(link)

            if not contains_keyword(title) and not contains_keyword(content):
                continue

            published_time = published_dt.strftime("%Y-%m-%d %H:%M:%S")
            news.append({
                "title": title,
                "content": content,
                "source": "Google News",
                "published_time": published_time
            })

            # 最終限制：最多 15 則
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
    print("▶ 正在抓取光寶科新聞（最多 15 則，兩天內）...")
    news_list = fetch_google_news_liteon(limit=15)

    if not news_list:
        print("⚠ 沒抓到資料")
        return

    save_to_firestore(news_list)

if __name__ == "__main__":
    main()
