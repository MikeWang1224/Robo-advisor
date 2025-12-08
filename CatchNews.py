# -*- coding: utf-8 -*-
"""
光寶科股市新聞抓取（Yahoo 財經）
條件：
✔ 3 天內（72 小時）
✔ 標題或內文只要提到光寶科/光寶/2301 即算
✔ Yahoo 財經支援翻頁、多種 selector
✔ 每次存入 Firestore 前覆蓋 document（清空舊資料）
✔ 使用環境變數 GOOGLE_APPLICATION_CREDENTIALS 指向 Firebase 金鑰 JSON 檔
"""

import os
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings
import firebase_admin
from firebase_admin import credentials, firestore

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

HEADERS = {'User-Agent': 'Mozilla/5.0'}

# ----- Firestore 初始化 -----
cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
firebase_admin.initialize_app(cred)
db = firestore.client()


# ----- 時間過濾（72 小時） -----
def is_recent(published_time, hours=72):
    now = datetime.now().astimezone()
    return (now - published_time) <= timedelta(hours=hours)


# ----- 抓文章內容 -----
def fetch_article_content(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        paragraphs = soup.select('article p') or soup.select('p')
        text = "\n".join(p.get_text(strip=True) for p in paragraphs)
        return text[:1500] + ('...' if len(text) > 1500 else '')
    except:
        return ""


# ----- 關鍵字判斷 -----
def contains_keyword(title, content):
    keywords = ["光寶科", "光寶", "2301"]
    text = (title + " " + content)
    return any(k in text for k in keywords)


# =============================
#  Yahoo 財經新聞抓取
# =============================
def fetch_yahoo_news(limit=80, pages=4):
    print("📡 抓取 Yahoo 財經新聞")
    base = "https://tw.news.yahoo.com"
    news_list = []
    seen = set()

    for page in range(1, pages + 1):
        url = f"https://tw.news.search.yahoo.com/search?p=光寶科&b={(page-1)*10+1}"
        r = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(r.text, 'html.parser')

        candidates = (
            soup.select("a.js-content-viewer") +
            soup.select("h3 a") +
            soup.select("a.d-ib") +
            soup.select("a[data-ylk]")
        )

        for a in candidates:
            if len(news_list) >= limit:
                return news_list

            title = a.get_text(strip=True)
            if not title or title in seen:
                continue
            seen.add(title)

            href = a.get("href")
            if not href:
                continue
            if href.startswith("/"):
                href = base + href

            content = fetch_article_content(href)
            if not contains_keyword(title, content):
                continue

            try:
                r2 = requests.get(href, headers=HEADERS)
                s2 = BeautifulSoup(r2.text, 'html.parser')
                time_tag = s2.find("time")
                if not time_tag or not time_tag.has_attr("datetime"):
                    continue
                published_dt = datetime.fromisoformat(
                    time_tag["datetime"].replace("Z", "+00:00")
                ).astimezone()
                if not is_recent(published_dt):
                    continue
            except:
                continue

            news_list.append({
                "title": title,
                "content": content,
                "published_time": published_dt,
                "source": "Yahoo 財經"
            })

    return news_list


# =============================
# Firestore 儲存（清空舊資料）
# =============================
def save_news(news_list):
    doc_id = datetime.now().strftime("%Y%m%d")
    ref = db.collection("NEWS_LiteOn").document(doc_id)

    data = {}
    for i, n in enumerate(news_list, 1):
        data[f"news_{i}"] = {
            "title": n["title"],
            "content": n["content"],
            "published_time": n["published_time"].strftime("%Y-%m-%d %H:%M:%S"),
            "source": n["source"]
        }

    ref.set(data, merge=False)
    print(f"✅ 已清空並存入 Firestore：NEWS_LiteOn/{doc_id}")


# =============================
# 主程式
# =============================
if __name__ == "__main__":
    yahoo_news = fetch_yahoo_news()
    all_news = [n for n in yahoo_news if is_recent(n["published_time"])]

    print(f"🔍 共抓到 {len(all_news)} 則光寶科股市新聞（3 天內）")

    if all_news:
        save_news(all_news)

    print("🎉 光寶科股市新聞抓取完成！")
