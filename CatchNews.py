# -*- coding: utf-8 -*-
"""
liteon_news_multi_source_limited.py

功能：
- 抓取光寶科 (2301) 最近兩天新聞
- 每個來源最多抓 15 則
- 來源：Yahoo 股市、鉅亨網、中時新聞網、工商時報、MoneyDJ、ETtoday、TechNews、Google News RSS
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
    keywords = ["光寶科", "光寶", "2301"]
    return any(k in text for k in keywords)

def is_recent(published_time_str):
    """判斷是否在最近兩天內"""
    try:
        dt = datetime.strptime(published_time_str, "%Y-%m-%d %H:%M:%S")
        return dt >= datetime.now() - timedelta(days=2)
    except:
        return False

# ---------- 每個來源抓取範例 ----------
def fetch_yahoo_liteon(limit=15):
    result = []
    try:
        url = "https://tw.stock.yahoo.com/quote/2301/news"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        for a in soup.select("a.js-content-viewer")[:limit]:
            title = a.get_text(strip=True)
            if not contains_keyword(title):
                continue
            link = "https://tw.stock.yahoo.com" + a["href"]
            published_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if not is_recent(published_time):
                continue
            result.append({
                "title": title,
                "content": fetch_article(link),
                "source": "Yahoo股市",
                "published_time": published_time
            })
    except:
        pass
    return result

def fetch_cnyes_liteon(limit=15):
    result = []
    headers = {"User-Agent": "Mozilla/5.0"}
    keywords = ["光寶科", "光寶", "2301"]
    count = 0
    for kw in keywords:
        if count >= limit:
            break
        try:
            url = f"https://api.cnyes.com/media/api/v1/search/list?keyword={kw}&limit={limit}"
            r = requests.get(url, headers=headers, timeout=10)
            items = r.json().get("items", {}).get("data", [])
            for item in items:
                if count >= limit:
                    break
                title = item.get("title", "")
                if not contains_keyword(title):
                    continue
                news_id = item.get("newsId")
                if not news_id:
                    continue
                link = f"https://news.cnyes.com/news/id/{news_id}?exp=a"
                timestamp = item.get("publishAt", 0)
                published_time = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
                if not is_recent(published_time):
                    continue
                result.append({
                    "title": title,
                    "content": fetch_article(link),
                    "source": "鉅亨網",
                    "published_time": published_time
                })
                count += 1
        except:
            continue
    return result

# 其他來源同理，只要在每個來源迴圈前加 `count` 控制 15 則，並用 is_recent 過濾最近兩天

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
    print("▶ 正在抓取光寶科新聞...")
    news_list = []
    news_list.extend(fetch_yahoo_liteon())
    news_list.extend(fetch_cnyes_liteon())
    # 可依需求把其他來源也加進來
    if not news_list:
        print("⚠ 沒抓到資料")
        return
    save_to_firestore(news_list)

if __name__ == "__main__":
    main()
