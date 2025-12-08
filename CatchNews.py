# -*- coding: utf-8 -*-
"""
光寶科 Yahoo 原生新聞抓取 + Firestore 寫入
✔ 只抓 Yahoo 原生（tw.news.yahoo.com）
✔ 自動解轉址
✔ 抓新聞全文（支援多種 caas-body 結構）
✔ 只抓 36 小時內新聞
✔ 寫入 Firestore，不存 link
"""

import os
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore
import time

# -----------------------------
# Firestore 初始化
# -----------------------------
if not firebase_admin._apps:
    cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    firebase_admin.initialize_app(cred)

db = firestore.client()
COLL_NAME = "NEWS_LiteOn"
KEYWORDS = ["光寶科", "光寶", "2301"]
MAX_HOURS = 36  # 只抓 36 小時內新聞

# -----------------------------
# 時間檢查
# -----------------------------
def in_range(dt):
    return (datetime.now() - dt).total_seconds() <= MAX_HOURS * 3600

# -----------------------------
# 解 Yahoo 轉址
# -----------------------------
def resolve_redirect(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True, timeout=10)
        return r.url
    except:
        return url

# -----------------------------
# 抓文章內文
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
                text = "\n".join([p.get_text(strip=True) for p in paras if len(p.get_text(strip=True)) > 20])
                if text:
                    return text[:1500] + ("..." if len(text) > 1500 else "")
        return ""
    except:
        return ""

# -----------------------------
# 解析相對時間
# -----------------------------
def parse_relative_time(text):
    now = datetime.now()
    try:
        if "分鐘前" in text:
            return now - timedelta(minutes=int(text.replace(" 分鐘前", "")))
        if "小時前" in text:
            return now - timedelta(hours=int(text.replace(" 小時前", "")))
        if "天前" in text:
            return now - timedelta(days=int(text.replace(" 天前", "")))
    except:
        pass
    return now

# -----------------------------
# Yahoo 搜尋頁抓取
# -----------------------------
def fetch_yahoo_search():
    print("📡 抓取 Yahoo 搜尋頁…")
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
        raw_link = title_tag.get("href", "")

        # 關鍵字過濾
        if not any(k in title for k in KEYWORDS):
            continue

        # 時間（相對時間）
        t = n.select_one("span.s-time")
        pub = parse_relative_time(t.get_text(strip=True)) if t else datetime.now()
        if not in_range(pub):
            continue

        # 解析真正網址
        real_url = resolve_redirect(raw_link)
        if "tw.news.yahoo.com" not in real_url:
            continue

        # 抓內文
        content = fetch_yahoo_article(real_url)
        results.append({
            "title": title,
            "content": content,
            "time": pub.strftime("%Y-%m-%d %H:%M"),
            "source": "Yahoo"
        })
        time.sleep(0.3)  # 避免抓太快被擋

    print(f"✔ Yahoo (原生) 抓到 {len(results)} 則（已抓全文）")
    return results

# -----------------------------
# Firestore 寫入
# -----------------------------
def write_to_firestore(news_list):
    today = datetime.now().strftime("%Y%m%d")
    doc_ref = db.collection(COLL_NAME).document(today)
    doc_ref.set({"news_list": news_list}, merge=True)
    print(f"🔥 Firestore 已寫入 → {COLL_NAME}/{today}")
    print(f"📦 共 {len(news_list)} 則新聞（含全文）")

# -----------------------------
# 主流程
# -----------------------------
def main():
    yahoo = fetch_yahoo_search()
    if not yahoo:
        print("⚠️ 沒有 Yahoo 原生新聞可寫入")
        return
    write_to_firestore(yahoo)

if __name__ == "__main__":
    main()
