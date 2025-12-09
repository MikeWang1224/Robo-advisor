# -*- coding: utf-8 -*-
"""
多公司新聞抓取程式（台積電 + 鴻海 + 聯電）
版本：v7-huggingface（embedding 版 / Yahoo 強化版）
------------------------------------------------------
✔ Yahoo 新版 HTML 結構完整支援（2025）
✔ Firestore 只用日期當 ID
✔ 儲存新聞 title + content + 漲跌 + embedding
✔ Hugging Face 免費 Embedding API
✔ 新聞時間解析，只抓 36 小時內新聞
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
import yfinance as yf

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ---------------------- 設定 ---------------------- #
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
}

HF_API_URL = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"
HF_TOKEN = os.environ.get("HF_TOKEN")

if not HF_TOKEN:
    raise ValueError("⚠️ 找不到 HF_TOKEN，請在 GitHub Secrets 設定！")

HF_HEADERS = {"Authorization": f"Bearer {HF_TOKEN}"}

# Firestore 初始化
key_dict = json.loads(os.environ["NEWS"])
cred = credentials.Certificate(key_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

ticker_map = {"台積電": "2330.TW", "鴻海": "2317.TW", "聯電": "2303.TW"}

# ---------------------- 時間過濾 ---------------------- #
def is_recent(published_time, hours=36):
    """判斷新聞是否在最近 X 小時內"""
    now = datetime.now().astimezone()
    return (now - published_time) <= timedelta(hours=hours)

# ---------------------- 股價漲跌 ---------------------- #
def fetch_stock_change(stock_name):
    ticker = ticker_map.get(stock_name)
    if not ticker: return "無資料"
    try:
        df = yf.Ticker(ticker).history(period="2d")
        if len(df) < 2: return "無資料"
        last = df['Close'].iloc[-1]
        prev = df['Close'].iloc[-2]
        diff = last - prev
        pct = diff / prev * 100
        sign = "+" if diff >= 0 else ""
        return f"{sign}{diff:.2f} ({sign}{pct:.2f}%)"
    except:
        return "無資料"

def add_price_change(news_list, stock_name):
    change = fetch_stock_change(stock_name)
    for n in news_list:
        n["price_change"] = change
    return news_list

# ---------------------- Embedding ---------------------- #
def generate_embedding(text):
    if not text: return []
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

# ---------------------- 文章內文 ---------------------- #
def fetch_article_content(url, source):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')

        # Yahoo 新版（2025）
        if source == 'yahoo':
            bdys = soup.find("div", {"class": "caas-body"})
            if bdys:
                paragraphs = bdys.find_all(["p", "h2"])
            else:
                paragraphs = soup.find_all("p")

        else:
            paragraphs = soup.find_all("p")

        text = "\n".join([
            p.get_text(strip=True)
            for p in paragraphs if len(p.get_text(strip=True)) > 40
        ])

        return text[:1500] + ('...' if len(text) > 1500 else '')
    except:
        return "無法取得新聞內容"

# ---------------------- Yahoo 新聞（全修正） ---------------------- #
def fetch_yahoo_news(keyword="台積電", limit=30):
    print(f"\n📡 Yahoo：{keyword}")
    base = "https://tw.news.yahoo.com"
    url = f"{base}/search?p={keyword}&sort=time"

    news_list, seen = [], set()

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')

        # 2025 Yahoo 主要選擇器
        items = soup.select("li.js-stream-content")                 # 主要
        items += soup.select("div.SerpHoverCard")                   # 部分搜尋結果
        items += soup.select("h3 a")                                # fallback

        for item in items:
            if len(news_list) >= limit: break

            # 標題
            a = item.find("a")
            if not a: continue

            title = a.get_text(strip=True)
            if not title or title in seen: continue
            seen.add(title)

            href = a.get("href")
            if href and not href.startswith("http"):
                href = base + href

            # 取得文章時間
            try:
                art = requests.get(href, headers=HEADERS)
                s2 = BeautifulSoup(art.text, 'html.parser')
                time_tag = s2.find("time")
                if not time_tag or not time_tag.has_attr("datetime"):
                    continue
                published = datetime.fromisoformat(
                    time_tag["datetime"].replace("Z", "+00:00")
                ).astimezone()
                if not is_recent(published, 36):
                    continue
            except:
                continue

            # 內文
            content = fetch_article_content(href, 'yahoo')

            news_list.append({
                "title": title,
                "content": content,
                "published_time": published
            })

    except Exception as e:
        print(f"Yahoo 抓取錯誤：{e}")

    return news_list

# ---------------------- Firestore ---------------------- #
def save_news(news_list, collection):
    doc_id = datetime.now().strftime("%Y%m%d")
    ref = db.collection(collection).document(doc_id)

    data = {}
    for i, n in enumerate(news_list, 1):
        emb = generate_embedding(n.get("content", ""))
        data[f"news_{i}"] = {
            "title": n["title"],
            "price_change": n["price_change"],
            "content": n["content"],
            "embedding": emb,
            "published_time": n["published_time"].strftime("%Y-%m-%d %H:%M")
        }

    ref.set(data)
    print(f"✅ Firestore 儲存完成：{collection}/{doc_id}")

# ---------------------- 主程式 ---------------------- #
if __name__ == "__main__":

    # 台積電
    tsmc = fetch_yahoo_news("台積電", 30)
    if tsmc:
        tsmc = add_price_change(tsmc, "台積電")
        save_news(tsmc, "NEWS")

    # 鴻海
    fox = fetch_yahoo_news("鴻海", 30)
    if fox:
        fox = add_price_change(fox, "鴻海")
        save_news(fox, "NEWS_Foxxcon")

    # 聯電
    umc = fetch_yahoo_news("聯電", 30)
    if umc:
        umc = add_price_change(umc, "聯電")
        save_news(umc, "NEWS_UMC")

    print("\n🎉 全部新聞抓取完成！")
