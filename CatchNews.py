# -*- coding: utf-8 -*-
"""
光寶科 Yahoo RSS 新聞抓取 + Firestore 儲存
✔ 只抓 Yahoo 原生 RSS（tw.news.yahoo.com）
✔ 自動解析新聞時間，只抓 36 小時內
✔ 抓新聞全文
✔ 寫入 Firestore，不存 link
"""

import os
import requests
import xml.etree.ElementTree as ET
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
COLL_NAME = "NEWS_LiteOn"

KEYWORDS = ["光寶科", "光寶", "2301"]
MAX_HOURS = 36

# -----------------------------
# 判斷時間是否在範圍內
# -----------------------------
def in_range(dt):
    return (datetime.now(dt.tzinfo or None) - dt).total_seconds() <= MAX_HOURS * 3600

# -----------------------------
# RSS 解析
# -----------------------------
def fetch_yahoo_rss(keyword="光寶科"):
    print("📡 抓取 Yahoo RSS…")
    rss_url = f"https://tw.news.yahoo.com/rss/tag/{keyword}.xml"
    try:
        r = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print("❌ RSS 取得失敗:", e)
        return []

    news_list = []
    for item in root.findall("./channel/item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub_str = item.findtext("pubDate") or ""
        content = item.findtext("description") or ""

        # 解析時間
        try:
            pub_dt = datetime.strptime(pub_str, "%a, %d %b %Y %H:%M:%S %z")
        except:
            pub_dt = datetime.now()

        if not in_range(pub_dt):
            continue

        # 關鍵字過濾
        if not any(k in title for k in KEYWORDS):
            continue

        # 嘗試抓全文
        full_content = fetch_yahoo_article(link)
        if full_content:
            content = full_content

        news_list.append({
            "title": title,
            "content": content,
            "time": pub_dt.strftime("%Y-%m-%d %H:%M"),
            "source": "Yahoo"
        })

    print(f"✔ Yahoo RSS 抓到 {len(news_list)} 則新聞")
    return news_list

# -----------------------------
# Yahoo 文章抓取（全文）
# -----------------------------
def fetch_yahoo_article(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        SELECTORS = [
            "div.caas-body p",
            "article.caas-body p",
            "div.caas-content p",
            "div.caas-body-wrapper p",
            "div.caas-body > p",
        ]

        for css in SELECTORS:
            paras = soup.select(css)
            if paras:
                return "\n".join([p.get_text(strip=True) for p in paras if len(p.get_text(strip=True)) > 40])

        return ""
    except:
        return ""

# -----------------------------
# Firestore 儲存
# -----------------------------
def write_to_firestore(news_list):
    if not news_list:
        print("⚠️ 沒有新聞可寫入")
        return

    today = datetime.now().strftime("%Y%m%d")
    doc_ref = db.collection(COLL_NAME).document(today)
    doc_ref.set({"news_list": news_list}, merge=True)

    print(f"🔥 Firestore 已寫入 → {COLL_NAME}/{today}")
    print(f"📦 共 {len(news_list)} 則新聞（含全文）")

# -----------------------------
# 主程式
# -----------------------------
def main():
    news = fetch_yahoo_rss("光寶科")
    write_to_firestore(news)

if __name__ == "__main__":
    main()
