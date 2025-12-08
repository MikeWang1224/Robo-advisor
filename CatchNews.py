# -*- coding: utf-8 -*-
"""
光寶科股市新聞抓取（Yahoo 股市新聞頁面）
條件：
✔ 3 天內（72 小時）
✔ 標題或內文只要提到光寶科/光寶/2301 就算一則
✔ 直接抓取 Yahoo 股市個股新聞頁面 (2301.TW)
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

# ----- 抓文章內容（可選） -----
def fetch_article_content(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        paragraphs = soup.select('article p') or soup.select('p')
        text = "\n".join(p.get_text(strip=True) for p in paragraphs)
        return text[:1500] + ('...' if len(text) > 1500 else '')
    except Exception as e:
        return ""

# ----- 關鍵字判斷（不一定需要，但保留） -----
def contains_keyword(title, content):
    keywords = ["光寶科", "2301", "光寶"]
    text = (title + " " + content)
    return any(k in text for k in keywords)

# =============================
#  Yahoo 股市 — 光寶科新聞抓取
# =============================
def fetch_yahoo_stock_news():
    print("📡 抓取 Yahoo 股市 — 光寶科新聞")
    url = "https://tw.stock.yahoo.com/quote/2301.TW/news"
    r = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(r.text, 'html.parser')

    news_list = []
    seen = set()

    # 每條新聞通常包在 <li> 或 <div>，可透過標題 h3 + a 來抓
    for a in soup.select("a.js-content-viewer, a[href^='/news/'], li a"):
        title = a.get_text(strip=True)
        if not title or title in seen:
            continue
        seen.add(title)

        href = a.get("href")
        if not href:
            continue
        # 完整連結
        if href.startswith("/"):
            href = "https://tw.stock.yahoo.com" + href

        # 試著擷取時間（有些在相同 list item, 在 time 或 span 裡）
        parent = a.find_parent()
        time_tag = None
        if parent:
            time_tag = parent.select_one("time") or parent.select_one("span[class*='C(#959595)']")

        published_dt = None
        if time_tag and time_tag.has_attr("datetime"):
            published_dt = datetime.fromisoformat(
                time_tag["datetime"].replace("Z", "+00:00")
            ).astimezone()
        else:
            # 如果沒有 datetime attribute，試 parse text 如 "2025/12/08 14:30"
            t = time_tag.get_text(strip=True) if time_tag else ""
            try:
                published_dt = datetime.strptime(t, "%Y/%m/%d %H:%M").astimezone()
            except:
                pass

        # 如果拿不到時間，就略過
        if not published_dt or not is_recent(published_dt):
            continue

        # 抓內容（可選，可加也可不加）
        content = fetch_article_content(href)

        # 關鍵字過濾（可視情況移除）
        if not contains_keyword(title, content):
            # 若不需要內文過濾，可註解掉這行
            # continue
            pass

        news_list.append({
            "title": title,
            "url": href,
            "content": content,
            "published_time": published_dt,
            "source": "Yahoo 股市"
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
            "url": n["url"],
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
    yahoo_news = fetch_yahoo_stock_news()
    print(f"🔍 共抓到 {len(yahoo_news)} 則光寶科股市新聞（3 天內）")
    if yahoo_news:
        save_news(yahoo_news)
    print("🎉 光寶科股市新聞抓取完成！")
