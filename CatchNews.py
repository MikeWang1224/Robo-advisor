# -*- coding: utf-8 -*-
"""
光寶科新聞抓取（Yahoo + 鉅亨網）
條件：
✔ 3 天內（72 小時）
✔ 標題或內文 只要提到光寶科/光寶/2301 就算一則
✔ Yahoo + 鉅亨網
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

# Firestore 初始化
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


# ----- 關鍵字判斷：標題 or 內文有提到即算 -----
def contains_keyword(title, content):
    keywords = ["光寶科", "光寶", "2301"]
    text = (title + " " + content)
    return any(k in text for k in keywords)


# =============================
#  Yahoo 新聞
# =============================
def fetch_yahoo_news(limit=40):
    print("📡 抓取 Yahoo 新聞")
    base = "https://tw.news.yahoo.com"
    url = f"{base}/search?p=光寶科&sort=time"

    news_list, seen = [], set()

    try:
        r = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(r.text, 'html.parser')
        links = soup.select('a.js-content-viewer') or soup.select('h3 a')

        for a in links:
            if len(news_list) >= limit:
                break

            title = a.get_text(strip=True)
            if not title or title in seen:
                continue
            seen.add(title)

            href = a.get("href")
            if href and not href.startswith("http"):
                href = base + href

            # 文章內容
            content = fetch_article_content(href)

            # 沒關鍵字就略過
            if not contains_keyword(title, content):
                continue

            # 解析發布時間
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
                "source": "Yahoo"
            })

    except Exception as e:
        print("Yahoo 抓取錯誤：", e)

    return news_list


# =============================
#  鉅亨網
# =============================
def fetch_cnyes_news(limit=40):
    print("📡 抓取 鉅亨網")

    keywords = ["光寶科", "光寶", "2301"]
    news_list = []
    seen = set()

    for kw in keywords:
        try:
            url = f"https://api.cnyes.com/media/api/v1/search/list?keyword={kw}&limit=50"
            r = requests.get(url, headers=HEADERS, timeout=10)
            data = r.json()

            items = data.get("items", {}).get("data", [])

            for item in items:
                if len(news_list) >= limit:
                    break

                title = item.get("title", "")
                if not title or title in seen:
                    continue
                seen.add(title)

                timestamp = item.get("publishAt", 0)
                if not timestamp:
                    continue

                published_dt = datetime.fromtimestamp(timestamp).astimezone()
                if not is_recent(published_dt):
                    continue

                article_url = f"https://news.cnyes.com/news/id/{item.get('newsId')}?exp=a"
                content = fetch_article_content(article_url)

                # 標題或內文提到即可
                if not contains_keyword(title, content):
                    continue

                news_list.append({
                    "title": title,
                    "content": content,
                    "published_time": published_dt,
                    "source": "鉅亨網"
                })

            if news_list:
                break

        except Exception as e:
            print("鉅亨網抓取錯誤：", e)

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
    print(f"✅ 已存入 Firestore：NEWS_LiteOn/{doc_id}")


# =============================
# 主程式
# =============================
if __name__ == "__main__":
    yahoo_news = fetch_yahoo_news()
    cnyes_news = fetch_cnyes_news()

    all_news = yahoo_news + cnyes_news

    print(f"🔍 共抓到 {len(all_news)} 則光寶科相關新聞（3 天內）")

    if all_news:
        save_news(all_news)

    print("🎉 光寶科新聞抓取完成！")
