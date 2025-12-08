# -*- coding: utf-8 -*-
"""
liteon_news_multi_source_selenium.py

功能：
- 抓取光寶科 (2301) 新聞
- 來源：Yahoo 股市、鉅亨網、中時新聞網、工商時報、MoneyDJ、ETtoday、TechNews、Google News RSS
- 使用 Selenium 抓取需要 JavaScript 的頁面
- 只儲存 title + content + published_time + source
- 不做 AI 分析，也不存 ai_analyzed / ai_error
"""

import os
import re
import time
import requests
from datetime import datetime
from bs4 import BeautifulSoup
import feedparser

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

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

# ---------- Selenium 初始化 ----------
def init_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    driver = webdriver.Chrome(options=chrome_options)
    return driver

# ---------- Yahoo 股市 ----------
def fetch_yahoo_liteon(driver):
    result = []
    try:
        driver.get("https://tw.stock.yahoo.com/quote/2301/news")
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, "html.parser")
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
    except Exception as e:
        print("Yahoo股市抓取失敗:", e)
    return result

# ---------- 鉅亨網 ----------
def fetch_cnyes_liteon(limit=50):
    result = []
    headers = {"User-Agent": "Mozilla/5.0"}
    keywords = ["光寶科", "光寶", "2301"]
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
        except Exception as e:
            print("鉅亨網抓取失敗:", e)
            continue
    return result

# ---------- 中時新聞網 ----------
def fetch_chinatimes_liteon(driver):
    result = []
    try:
        driver.get("https://www.chinatimes.com/search/光寶科")
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, "html.parser")
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
    except Exception as e:
        print("中時新聞抓取失敗:", e)
    return result

# ---------- 工商時報 ----------
def fetch_ct_liteon(driver):
    result = []
    try:
        driver.get("https://ctee.com.tw/search/%E5%85%89%E5%AF%B6%E7%A7%91")
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, "html.parser")
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
    except Exception as e:
        print("工商時報抓取失敗:", e)
    return result

# ---------- MoneyDJ ----------
def fetch_moneydj_liteon():
    result = []
    try:
        url = "https://www.moneydj.com/KMDJ/News/NewsList/Finance"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        articles = soup.select("div.news_listbox a")
        for a in articles:
            title = a.get_text(strip=True)
            if not contains_keyword(title):
                continue
            link = a.get("href")
            if not link.startswith("http"):
                link = "https://www.moneydj.com" + link
            content = fetch_article(link)
            if not contains_keyword(content):
                continue
            result.append({
                "title": title,
                "content": content,
                "source": "MoneyDJ",
                "published_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
    except Exception as e:
        print("MoneyDJ抓取失敗:", e)
    return result

# ---------- ETtoday 財經 ----------
def fetch_ettoday_liteon():
    result = []
    try:
        url = "https://www.ettoday.net/news/focus/%E5%85%89%E5%AF%B6%E7%A7%91"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        articles = soup.select("h3 a")
        for a in articles:
            title = a.get_text(strip=True)
            if not contains_keyword(title):
                continue
            link = a.get("href")
            if not link.startswith("http"):
                link = "https://www.ettoday.net" + link
            content = fetch_article(link)
            if not contains_keyword(content):
                continue
            result.append({
                "title": title,
                "content": content,
                "source": "ETtoday",
                "published_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
    except Exception as e:
        print("ETtoday抓取失敗:", e)
    return result

# ---------- TechNews ----------
def fetch_technews_liteon():
    result = []
    try:
        url = "https://technews.tw/?s=%E5%85%89%E5%AF%B6%E7%A7%91"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        articles = soup.select("h3.entry-title a")
        for a in articles:
            title = a.get_text(strip=True)
            if not contains_keyword(title):
                continue
            link = a.get("href")
            content = fetch_article(link)
            if not contains_keyword(content):
                continue
            result.append({
                "title": title,
                "content": content,
                "source": "TechNews",
                "published_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
    except Exception as e:
        print("TechNews抓取失敗:", e)
    return result

# ---------- Google News RSS ----------
def fetch_google_news_liteon():
    result = []
    try:
        rss_url = "https://news.google.com/rss/search?q=光寶科&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        feed = feedparser.parse(rss_url)
        for entry in feed.entries:
            title = entry.get("title", "")
            link = entry.get("link", "")
            content = title  # RSS 先用標題
            published_time = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M:%S") if entry.get("published_parsed") else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result.append({
                "title": title,
                "content": content,
                "source": "Google News",
                "published_time": published_time
            })
    except Exception as e:
        print("Google News抓取失敗:", e)
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
    driver = init_driver()
    news_list = []
    news_list.extend(fetch_yahoo_liteon(driver))
    news_list.extend(fetch_cnyes_liteon())
    news_list.extend(fetch_chinatimes_liteon(driver))
    news_list.extend(fetch_ct_liteon(driver))
    driver.quit()
    news_list.extend(fetch_moneydj_liteon())
    news_list.extend(fetch_ettoday_liteon())
    news_list.extend(fetch_technews_liteon())
    news_list.extend(fetch_google_news_liteon())

    if not news_list:
        print("⚠ 沒抓到資料")
        return

    save_to_firestore(news_list)

if __name__ == "__main__":
    main()
