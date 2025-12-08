# -*- coding: utf-8 -*-
"""
光寶科 Yahoo 原生新聞抓取 + Firestore 寫入
--------------------------------------------------
✔ 只抓 Yahoo 原生（tw.news.yahoo.com）
✔ 自動解轉址
✔ 多種 caas-body 全文解析
✔ 關鍵字：光寶科 / 光寶 / 2301
✔ 只抓 72 小時內新聞
✔ 寫入 Firestore（NEWS_LiteOn）
"""

import os
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore


# -------------------------------------------------------------
# Firestore 初始化
# -------------------------------------------------------------
if not firebase_admin._apps:
    cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    firebase_admin.initialize_app(cred)

db = firestore.client()

COLL_NAME = "NEWS_LiteOn"
KEYWORDS = ["光寶科", "光寶", "2301"]
MAX_HOURS = 72
HEADERS = {"User-Agent": "Mozilla/5.0"}


# -------------------------------------------------------------
# 是否在時間內
# -------------------------------------------------------------
def is_recent(dt):
    return (datetime.now() - dt).total_seconds() <= MAX_HOURS * 3600


# -------------------------------------------------------------
# 解 Yahoo 轉址
# -------------------------------------------------------------
def resolve_redirect(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        return r.url
    except:
        return url


# -------------------------------------------------------------
# 解析相對時間（3 小時前 / 1 天前）
# -------------------------------------------------------------
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


# -------------------------------------------------------------
# 抓 Yahoo 原生全文
# -------------------------------------------------------------
def fetch_yahoo_article(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
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
                return "\n".join([p.get_text(strip=True) for p in paras if p.get_text(strip=True)])

        return ""
    except:
        return ""


# -------------------------------------------------------------
# 抓 Yahoo 搜尋頁：只取 Yahoo 原生 + 關鍵字
# -------------------------------------------------------------
def fetch_yahoo_news():
    print(f"\n📡 抓 Yahoo 原生：光寶科")

    url = "https://tw.news.search.yahoo.com/search?p=光寶科&sort=time"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []

    for item in soup.select("div.NewsArticle"):
        title_tag = item.select_one("h4 > a")
        if not title_tag:
            continue

        title = title_tag.get_text(strip=True)

        # 過濾關鍵字
        if not any(k in title for k in KEYWORDS):
            continue

        raw_link = title_tag["href"]

        # 時間
        t = item.select_one("span.s-time")
        pub = parse_relative_time(t.get_text(strip=True)) if t else datetime.now()

        # 時間過舊 → 跳過
        if not is_recent(pub):
            continue

        # 解轉址
        real_url = resolve_redirect(raw_link)

        # 只保留 Yahoo 原生
        if "tw.news.yahoo.com" not in real_url:
            continue

        # 抓全文
        content = fetch_yahoo_article(real_url)

        results.append({
            "title": title,
            "content": content,
            "time": pub.strftime("%Y-%m-%d %H:%M"),
            "source": "Yahoo"
        })

    print(f"✔ Yahoo 原生：共 {len(results)} 則")
    return results


# -------------------------------------------------------------
# Firestore 寫入
# -------------------------------------------------------------
def save_to_firestore(news_list):
    if not news_list:
        print("⚠️ 無新聞可寫入 Firestore")
        return

    doc_id = datetime.now().strftime("%Y%m%d")

    db.collection(COLL_NAME).document(doc_id).set(
        {"news_list": news_list},
        merge=True
    )

    print(f"🔥 Firestore 寫入完成 → {COLL_NAME}/{doc_id}")


# -------------------------------------------------------------
# 主流程
# -------------------------------------------------------------
def main():
    news = fetch_yahoo_news()
    save_to_firestore(news)
    print("\n🎉 光寶科 Yahoo 原生新聞抓取完成！")


if __name__ == "__main__":
    main()
