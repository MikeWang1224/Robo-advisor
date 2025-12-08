# -*- coding: utf-8 -*-
"""
光寶科新聞抓取（Yahoo 搜尋 + 鉅亨全文）+ Firestore 寫入
✔ 抓標題
✔ 自動解轉址（Yahoo redirect）
✔ 抓新聞全文
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
MAX_HOURS = 72


def in_range(dt):
    return (datetime.now() - dt).total_seconds() <= MAX_HOURS * 3600


# ----------------------------------------------------------
# 解開 Yahoo 轉址 r.search.yahoo.com → 真正文章頁
# ----------------------------------------------------------
def resolve_redirect(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True, timeout=10)
        return r.url
    except:
        return url


# ----------------------------------------------------------
# 抓 Yahoo 新聞內文
# ----------------------------------------------------------
def fetch_yahoo_article(url):
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        paras = soup.select("div.caas-body p")
        if not paras:
            return ""

        text = "\n".join([p.get_text(strip=True) for p in paras])
        return text

    except:
        return ""


# ----------------------------------------------------------
# Yahoo 搜尋頁
# ----------------------------------------------------------
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
        raw_link = title_tag["href"]

        # 關鍵字過濾
        if not any(k in title for k in KEYWORDS):
            continue

        # 時間
        t = n.select_one("span.s-time")
        pub = parse_relative_time(t.get_text(strip=True)) if t else datetime.now()
        if not in_range(pub):
            continue

        # 解轉址
        real_url = resolve_redirect(raw_link)

        # 抓內文
        content = fetch_yahoo_article(real_url)

        results.append({
            "title": title,
            "content": content,
            "time": pub.strftime("%Y-%m-%d %H:%M"),
            "source": "Yahoo"
        })

    print(f"✔ Yahoo 搜尋抓到 {len(results)} 則（已抓全文）")
    return results


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


# ----------------------------------------------------------
# 鉅亨網全文抓取
# ----------------------------------------------------------
def fetch_cnyes():
    print("📡 抓取 鉅亨網…")

    url = "https://news.cnyes.com/search?keyword=光寶科"
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    items = soup.select("a._1Zdp")

    for n in items:
        title = n.get_text(strip=True)
        link = "https://news.cnyes.com" + n.get("href", "")

        if any(k in title for k in KEYWORDS):
            content = fetch_cnyes_article(link)

            results.append({
                "title": title,
                "content": content,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "source": "Cnyes"
            })

    print(f"✔ 鉅亨網抓到 {len(results)} 則（已抓全文）")
    return results


def fetch_cnyes_article(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        paras = soup.select("article p")
        return "\n".join([p.get_text(strip=True) for p in paras])
    except:
        return ""


# ----------------------------------------------------------
# Firestore 寫入
# ----------------------------------------------------------
def write_to_firestore(news_list):
    today = datetime.now().strftime("%Y%m%d")
    doc_ref = db.collection(COLL_NAME).document(today)

    doc_ref.set({"news_list": news_list}, merge=True)

    print(f"🔥 Firestore 已寫入 → {COLL_NAME}/{today}")
    print(f"📦 共 {len(news_list)} 則新聞（含全文）")


# ----------------------------------------------------------
# 主流程
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
