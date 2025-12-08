# -*- coding: utf-8 -*-
"""
liteon_news_selenium_full.py

功能：
- 抓取光寶科 (2301) 新聞
- 來源：Yahoo 股市、中時新聞網、工商時報
- 使用 Selenium 抓取動態生成頁面
- 只儲存 title + content + published_time + source
- 不做 AI 分析，也不存 ai_analyzed / ai_error
"""

import os
import re
import time
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests
import firebase_admin
from firebase_admin import credentials, firestore

# ---------- Firestore 初始化 ----------
cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------- 公用函式 ----------
def fetch_article(url, max_len=2000):
    """抓取文章全文"""
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

# ---------- Selenium 初始化 ----------
def init_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # 無頭模式
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=chrome_options)
    return driver

# ---------- 中時新聞網 ----------
def fetch_chinatimes_liteon(driver, max_news=20):
    result = []
    try:
        driver.get("https://www.chinatimes.com/search/光寶科")
        # 等待文章列表出現
        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.articlebox h3 a"))
        )
        # 滾動到底部以載入更多文章
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        articles = soup.select("div.articlebox h3 a")
        for a in articles[:max_news]:
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
    except Exception as e:
        print("中時新聞抓取失敗:", e)
    return result

# ---------- 工商時報 ----------
def fetch_ct_liteon(driver, max_news=20):
    result = []
    try:
        driver.get("https://ctee.com.tw/search/光寶科")
        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "h3 a"))
        )
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        articles = soup.select("h3 a")
        for a in articles[:max_news]:
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
    except Exception as e:
        print("工商時報抓取失敗:", e)
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
    # Yahoo
    news_list.extend(fetch_yahoo_liteon())
    # Selenium
    driver = init_driver()
    news_list.extend(fetch_chinatimes_liteon(driver))
    news_list.extend(fetch_ct_liteon(driver))
    driver.quit()

    if not news_list:
        print("⚠ 沒抓到資料")
        return

    save_to_firestore(news_list)

if __name__ == "__main__":
    main()
