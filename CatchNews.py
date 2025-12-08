# -*- coding: utf-8 -*-
"""
光寶科新聞抓取（TechNews + Yahoo + CNBC）
✔ 只抓光寶科
✔ 抓新聞全文
✔ 時間過濾：36 小時內
✔ 寫入 Firestore，不存股價
"""

import os
import time
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
HEADERS = {"User-Agent": "Mozilla/5.0"}

# -----------------------------
# 時間過濾
# -----------------------------
def is_recent(dt):
    return (datetime.now() - dt).total_seconds() <= MAX_HOURS * 3600

# -----------------------------
# TechNews
# -----------------------------
def fetch_technews(keyword="光寶科", limit=30):
    print(f"\n📡 TechNews：{keyword}")
    links, news = [], []
    url = f'https://technews.tw/google-search/?googlekeyword={keyword}'
    try:
        res = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(res.text, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('https://technews.tw/') and '/tag/' not in href:
                if href not in links:
                    links.append(href)
        links = links[:limit]
    except:
        return []

    for link in links:
        try:
            r = requests.get(link, headers=HEADERS)
            s = BeautifulSoup(r.text, 'html.parser')
            title_tag = s.find('h1')
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            time_tag = s.find("time", class_="entry-date")
            if not time_tag:
                continue
            published_dt = datetime.strptime(time_tag.get_text(strip=True), "%Y/%m/%d %H:%M")
            if not is_recent(published_dt):
                continue
            paras = s.select("article p") or s.select("p")
            content = "\n".join([p.get_text(strip=True) for p in paras if len(p.get_text(strip=True)) > 40])
            news.append({"title": title, "content": content[:1500], "time": published_dt.strftime("%Y-%m-%d %H:%M"), "source": "TechNews"})
            time.sleep(0.3)
        except:
            continue
    return news

# -----------------------------
# Yahoo
# -----------------------------
def fetch_yahoo(keyword="光寶科", limit=30):
    print(f"\n📡 Yahoo：{keyword}")
    base = "https://tw.news.yahoo.com"
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
            # 文章內容與時間
            try:
                r2 = requests.get(href, headers=HEADERS)
                s2 = BeautifulSoup(r2.text, 'html.parser')
                content = "\n".join([p.get_text(strip=True) for p in s2.select("article p") or s2.select("p") if len(p.get_text(strip=True)) > 40])
                time_tag = s2.find("time")
                if not time_tag or not time_tag.has_attr("datetime"):
                    continue
                published_dt = datetime.fromisoformat(time_tag["datetime"].replace("Z", "+00:00"))
                if not is_recent(published_dt):
                    continue
                news_list.append({"title": title, "content": content[:1500], "time": published_dt.strftime("%Y-%m-%d %H:%M"), "source": "Yahoo"})
            except:
                continue
    except:
        pass
    return news_list

# -----------------------------
# CNBC
# -----------------------------
def fetch_cnbc(keyword_list=["Lite-On"], limit=20):
    print(f"\n📡 CNBC：{'/'.join(keyword_list)}")
    urls = ["https://www.cnbc.com/search/?query=" + '+'.join(keyword_list)]
    news, seen = [], set()
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS)
            soup = BeautifulSoup(r.text, 'html.parser')
            articles = soup.select("article a")
            for a in articles:
                if len(news) >= limit:
                    break
                title = a.get_text(strip=True)
                href = a.get("href")
                if not title or title in seen or not href:
                    continue
                if not any(k.lower() in title.lower() for k in keyword_list):
                    continue
                if not href.startswith("http"):
                    href = "https://www.cnbc.com" + href
                try:
                    r2 = requests.get(href, headers=HEADERS)
                    s2 = BeautifulSoup(r2.text, 'html.parser')
                    content = "\n".join([p.get_text(strip=True) for p in s2.select("p") if len(p.get_text(strip=True)) > 40])
                    time_tag = s2.find("time")
                    if not time_tag or not time_tag.has_attr("datetime"):
                        continue
                    published_dt = datetime.fromisoformat(time_tag["datetime"].replace("Z", "+00:00"))
                    if not is_recent(published_dt):
                        continue
                    seen.add(title)
                    news.append({"title": title, "content": content[:1500], "time": published_dt.strftime("%Y-%m-%d %H:%M"), "source": "CNBC"})
                except:
                    continue
        except:
            continue
    return news

# -----------------------------
# Firestore 寫入
# -----------------------------
def save_news(news_list):
    if not news_list:
        print("⚠️ 沒有新聞可寫入")
        return
    today = datetime.now().strftime("%Y%m%d")
    ref = db.collection(COLL_NAME).document(today)
    data = {}
    for i, n in enumerate(news_list, 1):
        data[f"news_{i}"] = n
    ref.set(data)
    print(f"🔥 Firestore 已寫入 → {COLL_NAME}/{today}")
    print(f"📦 共 {len(news_list)} 則新聞")

# -----------------------------
# 主程式
# -----------------------------
if __name__ == "__main__":
    all_news = []
    all_news += fetch_technews("光寶科", 30)
    all_news += fetch_yahoo("光寶科", 30)
    all_news += fetch_cnbc(["Lite-On"], 20)
    save_news(all_news)
    print("\n🎉 全部新聞抓取完成！")
