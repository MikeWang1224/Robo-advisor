# -*- coding: utf-8 -*-
"""
liteon_news_only_multi_source.py

功能：
- 抓取光寶科 (2301) 新聞
- 來源：Yahoo 股市、鉅亨網、中時新聞網、工商時報
- 只儲存 title + content + published_time + source
- 不做 AI 分析，也不存 ai_analyzed / ai_error
"""

import os
import re
import requests
from datetime import datetime
from bs4 import BeautifulSoup

import firebase_admin
from firebase_admin import credentials, firestore

# ---------- Firestore 初始化 ----------
cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------- 公用函式 ----------
def fetch_article(url, max_len=2000):
    """抓取新聞文章全文"""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        text = soup.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        return text[:max_len]
    except:
        return "(抓取失敗)"

def contains_keyword(text):
    """判斷是否含光寶科關鍵字"""
    keywords = ["光寶科", "光寶", "2301"]
    return any(k in text for k in keywords)

# ---------- Yahoo 股市 ----------
def fetch_yahoo_liteon():
    url = "https://tw.stock.yahoo.com/quote/2301/news"
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")
    result = []

    for a in soup.select("a.js-content-viewer"):
        title = a.get_text(strip=True)
        if not contains_keyword(title):
            continue
        link = "https://tw.stock.yahoo.com" + a["href"]
        content = fetch_article(link)
        if not contains_keyword(content):
            continue
        result.append({
            "title": title,
            "content": content,
            "source": "Yahoo股市",
            "published_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    return result

# ---------- 鉅亨網 ----------
def fetch_cnyes_liteon(limit=50):
    result = []
    keywords = ["光寶科", "光寶", "2301"]
    headers = {"User-Agent": "Mozilla/5.0"}

    for kw in keywords:
        try:
            url = f"https://api.cnyes.com/media/api/v1/search/list?keyword={kw}&limit={limit}"
            r = requests.get(url, headers=headers, timeout=10)
            items = r.json().get("items", {}).get("data", [])
            for item in items:
                title = item.get("title", "")
                if not contains_keyword(title):
                    continue
                news_id = item.get("newsId")
                if not news_id:
                    continue
                link = f"https://news.cnyes.com/news/id/{news_id}?exp=a"
                content = fetch_article(link)
                if not contains_keyword(content):
                    continue
                timestamp = item.get("publishAt", 0)
                published_time = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
                result.append({
                    "title": title,
                    "content": content,
                    "source": "鉅亨網",
                    "published_time": published_time
                })
        except:
            continue
    return result

# ---------- 中時新聞網 ----------
def fetch_chinatimes_liteon():
    result = []
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = "https://www.chinatimes.com/search/%E5%85%89%E5%AF%B6%E7%A7%91"
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        articles = soup.select("div.articlebox h3 a")
        for a in articles:
            title = a.get_text(strip=True)
            if not contains_keyword(title):
                continue
            link = a.get("href")
            if not link.startswith("http"):
                link = "https://www.chinatimes.com" + link
            content = fetch_article(link)
            if not contains_keyword(content):
                continue
            result.append({
                "title": title,
                "content": content,
                "source": "中時新聞網",
                "published_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
    except:
        pass
    return result

# ---------- 工商時報 ----------
def fetch_ct_liteon():
    result = []
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = "https://ctee.com.tw/search/%E5%85%89%E5%AF%B6%E7%A7%91"
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        articles = soup.select("h3 a")
        for a in articles:
            title = a.get_text(strip=True)
            if not contains_keyword(title):
                continue
            link = a.get("href")
            if not link.startswith("http"):
                link = "https://ctee.com.tw" + link
            content = fetch_article(link)
            if not contains_keyword(content):
                continue
            result.append({
                "title": title,
                "content": content,
                "source": "工商時報",
                "published_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
    except:
        pass
    return result

# ---------- 寫入 Firestore ----------
def save_to_firestore(news_list):
    today = datetime.now().strftime("%Y%m%d")
    doc_ref = db.collection("NEWS_LiteOn").document(today)
    data = {}
    for i, news in enumerate(news_list, 1):
        data[f"news_{i}"] = news
    doc_ref.set(data, merge=True)
    print(f"✔ 已新增 {len(news_list)} 則新聞到 Firestore: NEWS_LiteOn/{today}")

# ---------- 主程式 ----------
def main():
    print("▶ 正在抓取光寶科新聞...")
    news_list = []
    news_list.extend(fetch_yahoo_liteon())
    news_list.extend(fetch_cnyes_liteon())
    news_list.extend(fetch_chinatimes_liteon())
    news_list.extend(fetch_ct_liteon())

    if not news_list:
        print("⚠ 沒抓到資料")
        return

    save_to_firestore(news_list)

if __name__ == "__main__":
    main()
