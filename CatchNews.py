# -*- coding: utf-8 -*-
"""
光寶科新聞抓取（Yahoo 個股新聞 + 鉅亨網）
只抓光寶科 + 36 小時內新聞  
"""

import os
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings
import firebase_admin
from firebase_admin import credentials, firestore

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ----- 設定 -----
HEADERS = {'User-Agent': 'Mozilla/5.0'}

# Firestore 初始化
cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
firebase_admin.initialize_app(cred)
db = firestore.client()


# ----- 時間過濾 -----
def is_recent(published_time, hours=36):
    now = datetime.now().astimezone()
    return (now - published_time) <= timedelta(hours=hours)


# ----- 抓文章內容 -----
def fetch_article_content(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')

        paragraphs = soup.select('article p') or soup.select('p')
        text = "\n".join([p.get_text(strip=True) for p in paragraphs])
        return text[:1500] + ('...' if len(text) > 1500 else '')
    except:
        return "無法取得新聞內容"


# =============================
#  Yahoo 個股新聞（大量抓）
# =============================
def fetch_yahoo_news_stock(symbol="2301", limit=50):
    print(f"📡 Yahoo 個股新聞：{symbol}")

    url = f"https://tw.stock.yahoo.com/quote/{symbol}/news"
    news_list, seen = [], set()

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")

        # 個股新聞列表
        cards = soup.select("ul[data-test-locator='stream-container'] li")

        for card in cards:
            if len(news_list) >= limit:
                break

            a = card.find("a")
            if not a:
                continue

            title = a.get_text(strip=True)
            if not title or title in seen:
                continue
            seen.add(title)

            href = a.get("href")
            if href.startswith("/"):
                href = "https://tw.stock.yahoo.com" + href

            # 再抓文章，看實際發布時間
            try:
                r2 = requests.get(href, headers=HEADERS, timeout=10)
                s2 = BeautifulSoup(r2.text, "html.parser")

                time_tag = s2.find("time")
                if not time_tag or not time_tag.has_attr("datetime"):
                    continue

                published_dt = datetime.fromisoformat(
                    time_tag["datetime"].replace("Z", "+00:00")
                ).astimezone()

                if not is_recent(published_dt):
                    continue

                content = fetch_article_content(href)

                news_list.append({
                    "title": title,
                    "content": content,
                    "published_time": published_dt,
                    "source": "Yahoo"
                })

            except:
                continue

    except Exception as e:
        print("Yahoo 個股新聞錯誤：", e)

    return news_list


# =============================
#  鉅亨網（含 fallback 關鍵字）
# =============================
def fetch_cnyes_news(keyword="光寶科", limit=30):
    print(f"📡 鉅亨網：{keyword}")

    keywords = [keyword, "光寶", "2301"]  # fallback

    news_list = []

    for kw in keywords:
        try:
            url = f"https://api.cnyes.com/media/api/v1/search/list?keyword={kw}&limit=30"
            r = requests.get(url, headers=HEADERS, timeout=10)
            data = r.json()

            items = data.get("items", {}).get("data", [])

            if not items:
                print(f"⚠ 鉅亨搜尋「{kw}」無資料")
                continue

            for item in items:
                if len(news_list) >= limit:
                    break

                title = item.get("title", "")
                if not title:
                    continue

                timestamp = item.get("publishAt", 0)
                if timestamp == 0:
                    continue

                published_dt = datetime.fromtimestamp(timestamp).astimezone()

                if not is_recent(published_dt):
                    continue

                article_url = f"https://news.cnyes.com/news/id/{item.get('newsId')}?exp=a"
                content = fetch_article_content(article_url)

                news_list.append({
                    "title": title,
                    "content": content,
                    "published_time": published_dt,
                    "source": "鉅亨網"
                })

            if news_list:
                break

        except Exception as e:
            print("鉅亨網錯誤：", e)

    return news_list


# =============================
# Firestore 儲存
# =============================
def save_news(news_list):
    doc_id = datetime.now().strftime("%Y%m%d")
    ref = db.collection("NEWS_LiteOn").document(doc_id)

    data = {}
    for i, n in enumerate(news_list, 1):
        data[f"news_{i}"] = {
            "title": n["title"],
            "content": n["content"],
            "published_time": n["published_time"].strftime("%Y-%m-%d %H:%M"),
            "source": n["source"]
        }

    ref.set(data)
    print(f"✅ Firestore 儲存完成：NEWS_LiteOn/{doc_id}")


# =============================
# 主程式
# =============================
if __name__ == "__main__":
    yahoo_news = fetch_yahoo_news_stock("2301", 50)
    cnyes_news = fetch_cnyes_news("光寶科", 30)

    all_news = yahoo_news + cnyes_news

    if all_news:
        save_news(all_news)

    print("\n🎉 光寶科（2301）新聞抓取完成！（Yahoo 個股新聞 + 鉅亨）")
