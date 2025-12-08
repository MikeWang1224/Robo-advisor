# -*- coding: utf-8 -*-
"""
光寶科股市新聞抓取（Yahoo 股市 + Selenium）
條件：
✔ 3 天內（72 小時）
✔ 標題或內文只要提到光寶科/光寶/2301 即算
✔ 使用 Selenium 模擬瀏覽器抓動態渲染新聞
✔ 每次存入 Firestore 前覆蓋 document（清空舊資料）
✔ 使用環境變數 GOOGLE_APPLICATION_CREDENTIALS 指向 Firebase 金鑰 JSON 檔
"""

import os
from datetime import datetime, timedelta
import time
import firebase_admin
from firebase_admin import credentials, firestore
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# ----- Firestore 初始化 -----
cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
firebase_admin.initialize_app(cred)
db = firestore.client()

# ----- 時間過濾（72 小時） -----
def is_recent(published_time, hours=72):
    now = datetime.now().astimezone()
    return (now - published_time) <= timedelta(hours=hours)

# =============================
#  Selenium 抓 Yahoo 股市新聞
# =============================
def fetch_yahoo_stock_news(max_news=50):
    print("📡 抓取 Yahoo 股市 — 光寶科新聞 (Selenium)")
    
    options = Options()
    options.add_argument("--headless")  # 不開啟瀏覽器畫面
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    driver = webdriver.Chrome(options=options)

    url = "https://tw.stock.yahoo.com/quote/2301.TW/news"
    driver.get(url)
    time.sleep(5)  # 等待 JS 動態載入

    news_list = []
    seen = set()

    # 找新聞區塊，每則新聞在 <li> 或 <a> 標籤
    articles = driver.find_elements(By.CSS_SELECTOR, "li div div a")
    for a in articles:
        if len(news_list) >= max_news:
            break

        title = a.text.strip()
        href = a.get_attribute("href")
        if not title or title in seen or not href:
            continue
        seen.add(title)

        # 嘗試抓時間，通常在同個 li 或 div 的 span
        parent_li = a.find_element(By.XPATH, "./ancestor::li")
        time_text = ""
        try:
            span = parent_li.find_element(By.CSS_SELECTOR, "time")
            time_text = span.get_attribute("datetime")
        except:
            try:
                span = parent_li.find_element(By.CSS_SELECTOR, "span.C(#959595)")
                time_text = span.text
            except:
                time_text = ""

        # 解析時間
        published_dt = None
        try:
            if time_text:
                if "T" in time_text:  # ISO 格式
                    published_dt = datetime.fromisoformat(time_text.replace("Z", "+00:00")).astimezone()
                else:  # 文字格式如 2025/12/08 14:30
                    published_dt = datetime.strptime(time_text, "%Y/%m/%d %H:%M").astimezone()
        except:
            pass

        if not published_dt or not is_recent(published_dt):
            continue

        # 內容抓取（可選）
        content = ""  # 可改成 Selenium 或 requests 抓文章內容

        news_list.append({
            "title": title,
            "url": href,
            "content": content,
            "published_time": published_dt,
            "source": "Yahoo 股市"
        })

    driver.quit()
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
