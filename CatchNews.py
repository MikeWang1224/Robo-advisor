# -*- coding: utf-8 -*-
"""
liteon_news_yahoo15.py

- 只抓最近兩天內的光寶科新聞（Yahoo 新聞）
- 最多 15 則
- 使用 Base64 金鑰 NEW_FIREBASE_KEY_B64 初始化 Firestore
- 時間判斷使用 UTC
- 執行前會清空今天的 Firestore 文件
"""

import os
import re
import json
import base64
import requests
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
import feedparser
import firebase_admin
from firebase_admin import credentials, firestore

# ---------- Firestore 初始化（使用 Base64 金鑰 NEW_FIREBASE_KEY_B64） ----------
key_b64 = os.environ.get("NEW_FIREBASE_KEY")
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
    """判斷是否兩天內，使用 UTC"""
    if not published_dt:
        return False
    now_utc = datetime.now(timezone.utc)
    published_utc = published_dt.replace(tzinfo=timezone.utc)
    return published_utc >= now_utc - timedelta(days=2)

# ---------- Yahoo News RSS ----------
def fetch_yahoo_news_liteon(limit=15):
    news = []
    # Yahoo 新聞搜尋 RSS，q=光寶科
    rss_url = "https://tw.news.yahoo.com/rss/tag/2301"

    try:
        feed = feedparser.parse(rss_url)

        for entry in feed.entries[:limit]:

            # -------- 解析 published_time --------
            published_dt = None
            if entry.get("published_parsed"):
                published_dt = datetime(*entry.published_parsed[:6])
            else:
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

            # 關鍵字過濾
            if not contains_keyword(title) and not contains_keyword(content):
                continue

            published_time = published_dt.strftime("%Y-%m-%d %H:%M:%S")
            news.append({
                "title": title,
                "content": content,
                "source": "Yahoo News",
                "published_time": published_time
            })

            if len(news) >= limit:
                break

    except Exception as e:
        print("RSS 抓取錯誤：", e)

    return news

# ---------- 寫入 Firestore ----------
def save_to_firestore(news_list):
    today = datetime.now().strftime("%Y%m%d")
    doc_ref = db.collection("NEWS_LiteOn").document(today)

    # ---------- 清空今日文件 ----------
    doc_ref.delete()
    print(f"🗑 已清空 Firestore: NEWS_LiteOn/{today}")

    # ---------- 寫入新資料 ----------
    data = {f"news_{i}": news for i, news in enumerate(news_list, 1)}
    doc_ref.set(data, merge=True)
    print(f"✔ 已新增 {len(news_list)} 則新聞到 Firestore: NEWS_LiteOn/{today}")

# ---------- 主程式 ----------
def main():
    print("▶ 正在抓取光寶科 Yahoo 新聞（最多 15 則，最近兩天內）...")
    news_list = fetch_yahoo_news_liteon(limit=15)

    if not news_list:
        print("⚠ 沒抓到資料")
        return

    save_to_firestore(news_list)

if __name__ == "__main__":
    main()
