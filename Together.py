# -*- coding: utf-8 -*-
"""
光寶科新聞抓取程式（Yahoo Finance）
版本：Liteon-Yahoo v1
-----------------------------------
✔ 抓光寶科 Yahoo 新聞（36 小時內）
✔ Firestore 上傳
✔ HuggingFace 免費 Embedding
"""

import os
import time
import json
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings
import firebase_admin
from firebase_admin import credentials, firestore

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ---------------------- 設定 ---------------------- #
HEADERS = {'User-Agent': 'Mozilla/5.0'}

HF_API_URL = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"
HF_TOKEN = os.environ.get("HF_TOKEN")

if not HF_TOKEN:
    raise ValueError("⚠️ 找不到 HF_TOKEN，請在 GitHub Secrets 設定！")

HF_HEADERS = {
    "Authorization": f"Bearer {HF_TOKEN}"
}

# Firestore 初始化
key_dict = json.loads(os.environ["NEW_FIREBASE_KEY"])
cred = credentials.Certificate(key_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------------------- 時間過濾 ---------------------- #
def is_recent(published_time, hours=36):
    now = datetime.now().astimezone()
    return (now - published_time) <= timedelta(hours=hours)

# ---------------------- 抓 Yahoo 文章內容 ---------------------- #
def fetch_article_content(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        paragraphs = soup.select('article p') or soup.select('p')

        text = '\n'.join([p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 40])
        return text[:1500] + ('...' if len(text) > 1500 else '')
    except:
        return "無法取得新聞內容"

# ---------------------- HuggingFace Embedding ---------------------- #
def generate_embedding(text):
    if not text:
        return []
    try:
        res = requests.post(
            HF_API_URL,
            headers=HF_HEADERS,
            json={"inputs": text[:1000]},
            timeout=20
        )
        data = res.json()
        if isinstance(data, list):
            return data
    except:
        pass
    return []

# ---------------------- Yahoo 搜尋光寶科 ---------------------- #
def fetch_yahoo_liteon(limit=30):
    print("\n📡 Yahoo：光寶科")
    keyword = "光寶科"
    base = "https://tw.stock.yahoo.com"
    url = f"{base}/search?p={keyword}&sort=time"

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

            # 抓文章內容
            content = fetch_article_content(href)

            # 抓發佈時間
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
                'title': title,
                'content': content,
                'published_time': published_dt
            })

    except:
        pass

    return news_list

# ---------------------- Firestore 儲存 ---------------------- #
def save_news_to_firestore(news_list):
    if not news_list:
        print("⚠️ 無光寶科新聞可寫入 Firebase")
        return

    doc_id = datetime.now().strftime("%Y%m%d")
    ref = db.collection("NEWS_Liteon").document(doc_id)

    data = {}
    for i, n in enumerate(news_list, 1):
        emb = generate_embedding(n["content"])
        data[f"news_{i}"] = {
            "title": n["title"],
            "content": n["content"],
            "embedding": emb,
            "published_time": n["published_time"].strftime("%Y-%m-%d %H:%M")
        }

    ref.set(data)
    print(f"✅ Firestore 儲存完成：NEWS_Liteon/{doc_id}")

# ---------------------- 主程式 ---------------------- #
if __name__ == "__main__":
    liteon_news = fetch_yahoo_liteon(30)
    save_news_to_firestore(liteon_news)
    print("\n🎉 光寶科 Yahoo 新聞抓取完成！")
