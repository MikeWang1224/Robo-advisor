# -*- coding: utf-8 -*-
"""
liteon_news_only.py

功能：
- 抓取光寶科 (2301) 新聞
- 只儲存 title + content + published_time + source
- 不做 AI 分析，也不存 ai_analyzed / ai_error
"""

import os
import re
import requests
from datetime import datetime
from bs4 import BeautifulSoup

import firebase_admin
from firebase_admin import credentials, firestore

# ---------- Firestore 初始化 ----------
cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------- Yahoo 抓取 ----------
def fetch_yahoo_liteon():
    """抓取光寶科（2301）新聞"""
    url = "https://tw.stock.yahoo.com/quote/2301/news"
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")

    result = []
    for a in soup.select("a.js-content-viewer"):
        title = a.get_text(strip=True)
        link = "https://tw.stock.yahoo.com" + a["href"]

        # 取文章內文
        content = fetch_article(link)

        result.append({
            "title": title,
            "content": content,
            "source": "Yahoo股市",
            "published_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    return result

def fetch_article(url):
    """抓取 Yahoo 新聞文章全文"""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        return text[:2000]  # 避免內容過長
    except:
        return "(抓取失敗)"

# ---------- 寫入 Firestore ----------
def save_to_firestore(news_list):
    """存入 Firestore -> Collection: NEWS_LiteOn / Doc: 日期"""
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
    news_list = fetch_yahoo_liteon()

    if not news_list:
        print("⚠ 沒抓到資料")
        return

    save_to_firestore(news_list)

if __name__ == "__main__":
    main()
