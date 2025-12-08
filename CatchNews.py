# -*- coding: utf-8 -*-
"""
光寶科新聞抓取（Yahoo）
✔ 只抓光寶科
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
KEYWORDS = ["光寶科", "光寶", "2301"]
MAX_HOURS = 36
HEADERS = {"User-Agent": "Mozilla/5.0"}

# -----------------------------
# 時間過濾
# -----------------------------
def is_recent(dt):
    return (datetime.now(timezone.utc) - dt).total_seconds() <= MAX_HOURS * 3600

# -----------------------------
# Yahoo 抓取
# -----------------------------
def fetch_yahoo(keyword="光寶科", limit=30):
    print(f"\n📡 Yahoo：{keyword}")
    base = "https://tw.news.yahoo.com"
    url = f"{base}/search?p={keyword}&sort=time"

    news_list, seen = [], set()

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')

        # Yahoo 搜尋結果
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

            # -----------------------------
            # 抓取內文 + 時間
            # -----------------------------
            try:
                r2 = requests.get(href, headers=HEADERS, timeout=10)
                s2 = BeautifulSoup(r2.text, 'html.parser')

                # ---- 抓全文（避免 403 簡化版本）----
                paras = s2.select("article p") or s2.select("p")
                content = "\n".join(
                    p.get_text(strip=True)
                    for p in paras
                    if len(p.get_text(strip=True)) > 40
                )[:1500]

                # ---- 抓時間 ----
                time_tag = s2.find("time")
                if not time_tag or not time_tag.has_attr("datetime"):
                    continue

                published_dt = datetime.fromisoformat(
                    time_tag["datetime"].replace("Z", "+00:00")
                )

                if not is_recent(published_dt):
                    continue

                news_list.append({
                    "title": title,
                    "content": content,
                    "time": published_dt.strftime("%Y-%m-%d %H:%M"),
                    "source": "Yahoo"
                })

                time.sleep(0.3)

            except Exception:
                continue

    except Exception:
        pass

    return news_list

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
    all_news = fetch_yahoo("光寶科", 30)
    save_news(all_news)
    print("\n🎉 Yahoo 新聞抓取完成！")
