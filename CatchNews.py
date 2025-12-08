# -*- coding: utf-8 -*-
"""
光寶科新聞抓取（Yahoo + TechNews 強化版）
✔ 多關鍵字：光寶科 / 光寶 / 2301
✔ Yahoo 抓多頁 + 新舊版支援
✔ TechNews 多頁解析
✔ 抓新聞全文
✔ 時間過濾：36 小時內
✔ 寫入 Firestore（不存股價）
"""

import os
import time
import requests
from datetime import datetime, timedelta, timezone
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
KEYWORDS = ["光寶科", "光寶", "2301"]  # 多關鍵字
MAX_HOURS = 36
HEADERS = {"User-Agent": "Mozilla/5.0"}

# -----------------------------
# 時間過濾
# -----------------------------
def is_recent(dt):
    return (datetime.now(timezone.utc) - dt).total_seconds() <= MAX_HOURS * 3600


# -----------------------------
# Yahoo 強化抓取
# -----------------------------
def fetch_yahoo(limit_each=30):
    print("\n📡 Yahoo 強化抓取中...")

    base = "https://tw.news.yahoo.com"
    all_news, seen_links = [], set()

    for keyword in KEYWORDS:
        print(f"\n🔍 Yahoo 搜尋關鍵字：{keyword}")

        for page in range(1, 4):  # 抓 3 頁
            url = f"{base}/search?p={keyword}&sort=time&b={(page-1)*10+1}"

            try:
                r = requests.get(url, headers=HEADERS, timeout=10)
                soup = BeautifulSoup(r.text, "html.parser")

                # 新版 Yahoo
                links = soup.select("a.js-content-viewer")

                # 舊版 Yahoo
                if not links:
                    links = soup.select("h3 a")

                for a in links:
                    href = a.get("href")
                    if not href:
                        continue

                    if not href.startswith("http"):
                        href = base + href

                    if href in seen_links:
                        continue
                    seen_links.add(href)

                    # 抓全文
                    try:
                        r2 = requests.get(href, headers=HEADERS, timeout=10)
                        s2 = BeautifulSoup(r2.text, "html.parser")

                        title = s2.find("h1")
                        if not title:
                            continue
                        title = title.get_text(strip=True)

                        paras = s2.select("article p") or s2.select("p")
                        content = "\n".join(
                            p.get_text(strip=True)
                            for p in paras
                            if len(p.get_text(strip=True)) > 40
                        )[:1500]

                        # 時間
                        time_tag = s2.find("time")
                        if not time_tag or not time_tag.has_attr("datetime"):
                            continue

                        published_dt = datetime.fromisoformat(
                            time_tag["datetime"].replace("Z", "+00:00")
                        )
                        if not is_recent(published_dt):
                            continue

                        all_news.append({
                            "title": title,
                            "content": content,
                            "time": published_dt.strftime("%Y-%m-%d %H:%M"),
                            "source": "Yahoo"
                        })

                        time.sleep(0.3)

                    except:
                        continue

            except:
                continue

    return all_news


# -----------------------------
# TechNews 強化抓取
# -----------------------------
def fetch_technews(limit_pages=3):
    print("\n📡 TechNews 強化抓取中...")

    base = "https://technews.tw"
    all_news, seen_links = [], set()

    for keyword in KEYWORDS:
        print(f"\n🔍 TechNews 搜尋關鍵字：{keyword}")
        url = f"https://technews.tw/google-search/?googlekeyword={keyword}"

        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")

            raw_links = soup.find_all("a", href=True)
            links = []

            for a in raw_links:
                href = a["href"]
                if href.startswith(base) and "/tag/" not in href:
                    if href not in links:
                        links.append(href)

            links = links[:50]  # 避免抓太多

        except:
            continue

        # 抓每篇文章
        for link in links:
            if link in seen_links:
                continue
            seen_links.add(link)

            try:
                r2 = requests.get(link, headers=HEADERS, timeout=10)
                s2 = BeautifulSoup(r2.text, "html.parser")

                title_tag = s2.find("h1")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)

                time_tag = s2.find("time", class_="entry-date")
                if not time_tag:
                    continue

                published_dt = datetime.strptime(
                    time_tag.get_text(strip=True), "%Y/%m/%d %H:%M"
                ).replace(tzinfo=timezone.utc)

                if not is_recent(published_dt):
                    continue

                paras = s2.select("article p") or s2.select("p")
                content = "\n".join(
                    p.get_text(strip=True)
                    for p in paras
                    if len(p.get_text(strip=True)) > 40
                )[:1500]

                all_news.append({
                    "title": title,
                    "content": content,
                    "time": published_dt.strftime("%Y-%m-%d %H:%M"),
                    "source": "TechNews"
                })

                time.sleep(0.3)

            except:
                continue

    return all_news


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

    # Yahoo + TechNews
    all_news += fetch_yahoo()
    all_news += fetch_technews()

    save_news(all_news)

    print("\n🎉 Yahoo + TechNews 新聞抓取完成！")
