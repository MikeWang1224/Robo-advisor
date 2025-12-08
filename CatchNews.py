# -*- coding: utf-8 -*-
"""
光寶科新聞抓取（Yahoo 強化版）
✔ 多關鍵字：光寶科 / 光寶 / 2301
✔ 抓多頁：page=1~3
✔ 新版＋舊版 Yahoo 同時支援
✔ 抓新聞全文
✔ 時間：36 小時內
✔ 寫入 Firestore（不含股價）
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
KEYWORDS = ["光寶科", "光寶", "2301"]
MAX_HOURS = 36
HEADERS = {"User-Agent": "Mozilla/5.0"}

# -----------------------------
# 時間過濾
# -----------------------------
def is_recent(dt):
    return (datetime.now(timezone.utc) - dt).total_seconds() <= MAX_HOURS * 3600

# -----------------------------
# Yahoo 抓取（強化）
# -----------------------------
def fetch_yahoo_multi(limit_each=30):
    print("\n📡 Yahoo 搜尋強化版")

    base = "https://tw.news.yahoo.com"
    all_news, seen_links = [], set()

    for keyword in KEYWORDS:
        print(f"\n🔍 關鍵字：{keyword}")

        for page in range(1, 4):  # 抓 3 頁
            url = f"{base}/search?p={keyword}&sort=time&b={(page-1)*10+1}"

            try:
                r = requests.get(url, headers=HEADERS, timeout=10)
                soup = BeautifulSoup(r.text, "html.parser")

                # 新版 Yahoo
                links = soup.select("a.js-content-viewer")

                # 舊版 Yahoo Fallback
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

                    # 抓內文
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

                    except Exception:
                        continue

            except Exception:
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
    all_news = fetch_yahoo_multi()
    save_news(all_news)
    print("\n🎉 Yahoo 新聞抓取完成（強化版）！")
