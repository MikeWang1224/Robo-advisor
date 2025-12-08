# -*- coding: utf-8 -*-
"""
光寶科 Yahoo 原生新聞抓取 + Firestore 寫入（只抓光寶科）
✔ 只抓 Yahoo 原生（tw.news.yahoo.com）
✔ 自動解轉址
✔ 抓新聞全文（支援多種 caas-body 結構）
✔ 僅抓最近 36 小時新聞
✔ 寫入 Firestore，不存 link
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
COLL_NAME = "NEWS_LiteOn"
KEYWORDS = ["光寶科", "光寶", "2301"]
MAX_HOURS = 36

# -----------------------------
# 時間判斷
# -----------------------------
def in_range(dt):
    return (datetime.now() - dt).total_seconds() <= MAX_HOURS * 3600

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
# 解 Yahoo 轉址
# -----------------------------
def resolve_redirect(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True, timeout=10)
        return r.url
    except:
        return url

# -----------------------------
# 抓 Yahoo 原生文章內容
# -----------------------------
def fetch_yahoo_article(url):
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
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
                return "\n".join([p.get_text(strip=True) for p in paras if len(p.get_text(strip=True)) > 20])
        return ""
    except:
        return ""

# -----------------------------
# 抓 Yahoo 搜尋頁
# -----------------------------
def fetch_yahoo_search():
    print("📡 抓取 Yahoo 搜尋頁…")
    url = "https://tw.news.search.yahoo.com/search?p=光寶科&sort=time"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select("div.NewsArticle")
        results = []

        for n in items:
            title_tag = n.select_one("h4 > a")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            if not any(k in title for k in KEYWORDS):
                continue
            raw_link = title_tag["href"]
            real_url = resolve_redirect(raw_link)
            if "tw.news.yahoo.com" not in real_url:
                continue

            t = n.select_one("span.s-time")
            pub = parse_relative_time(t.get_text(strip=True)) if t else datetime.now()
            if not in_range(pub):
                continue

            content = fetch_yahoo_article(real_url)
            if not content:
                continue

            results.append({
                "title": title,
                "content": content,
                "time": pub.strftime("%Y-%m-%d %H:%M"),
                "source": "Yahoo"
            })

        print(f"✔ Yahoo (原生) 抓到 {len(results)} 則（已抓全文）")
        return results

    except Exception as e:
        print(f"❌ 抓取 Yahoo 搜尋頁失敗: {e}")
        return []

# -----------------------------
# Firestore 寫入
# -----------------------------
def write_to_firestore(news_list):
    if not news_list:
        print("⚠️ 沒有 Yahoo 原生新聞可寫入")
        return
    today = datetime.now().strftime("%Y%m%d")
    doc_ref = db.collection(COLL_NAME).document(today)
    doc_ref.set({"news_list": news_list}, merge=True)
    print(f"🔥 Firestore 已寫入 → {COLL_NAME}/{today}")
    print(f"📦 共 {len(news_list)} 則新聞（含全文）")

# -----------------------------
# 主流程
# -----------------------------
def main():
    yahoo_news = fetch_yahoo_search()
    write_to_firestore(yahoo_news)

if __name__ == "__main__":
    main()
