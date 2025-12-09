# -*- coding: utf-8 -*-
"""
Yahoo 財經新聞抓取（光寶科）
只抓財報 / 法說 / 公司公告相關新聞
時間過濾：36 小時內
Firestore 存儲：NEWS_LiteOn / YYYYMMDD / articles -> 每篇一個 doc
本地備份：result.txt
"""
import os
import time
import hashlib
import logging
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import re

try:
    from dateutil import parser as dateparser
except:
    dateparser = None

import firebase_admin
from firebase_admin import credentials, firestore

# ---------------- Config ----------------
COLL_NAME = "NEWS_LiteOn"
KEYWORDS = ["光寶科", "光寶", "2301"]
FIN_KEYWORDS = ["財報", "法說", "季報", "公告"]
MAX_HOURS = 36
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/117.0.0.0 Safari/537.36"
}
REQUEST_TIMEOUT = 12
MAX_RETRIES = 2
SLEEP_BETWEEN_REQ = 0.4

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ---------------- Firestore init ----------------
if not firebase_admin._apps:
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not cred_path:
        raise SystemExit("Missing GOOGLE_APPLICATION_CREDENTIALS")
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------------- Helpers ----------------
session = requests.Session()
session.headers.update(HEADERS)

def safe_get(url):
    for attempt in range(1, MAX_RETRIES+1):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r
        except Exception as e:
            logging.debug(f"GET {url} fail attempt {attempt}: {e}")
            time.sleep(0.5 * attempt)
    return None

def clean_text(s):
    return re.sub(r'\s+', ' ', s).strip() if s else ""

def now_utc():
    return datetime.now(timezone.utc)

def parse_datetime_fuzzy(s):
    if not s:
        return None
    s = s.strip()
    if dateparser:
        try:
            dt = dateparser.parse(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except:
            pass
    return None

def is_recent(dt):
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now_utc() - dt).total_seconds() <= MAX_HOURS*3600

def contains_keywords(text, keywords):
    text = text.lower()
    return any(k.lower() in text for k in keywords)

def doc_id_from_url(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()

# ---------------- Yahoo 搜尋抓取 ----------------
def fetch_yahoo_financial(keywords=None, pages=5, per_page_limit=50):
    if keywords is None:
        keywords = KEYWORDS

    base = "https://tw.news.yahoo.com"
    results = []
    seen_urls = set()

    logging.info("📡 Yahoo 財經抓取開始")

    for kw in keywords:
        for page in range(1, pages+1):
            b = (page-1)*10 + 1
            url = f"{base}/search?p={requests.utils.requote_uri(kw)}&sort=time&b={b}"

            r = safe_get(url)
            if not r:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            links = soup.select("a.js-content-viewer, h3 a, a[href*='/news/']")

            for a in links:
                href = a.get("href")
                if not href:
                    continue
                if href.startswith("/"):
                    href = base + href
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                time.sleep(SLEEP_BETWEEN_REQ)
                r2 = safe_get(href)
                if not r2:
                    continue

                s2 = BeautifulSoup(r2.text, "html.parser")

                # --- 取得標題 ---
                title = clean_text(s2.find("h1").get_text()) if s2.find("h1") else ""
                if not title:
                    continue

                # --- 必須包含光寶科 ---
                if not contains_keywords(title, ["光寶科", "光寶", "2301"]):
                    continue

                # --- 時間解析 ---
                dt = None
                t = s2.find("time")
                if t and t.has_attr("datetime"):
                    dt = parse_datetime_fuzzy(t["datetime"])

                if not dt or not is_recent(dt):
                    continue

                # --- 抓內容（新版 Yahoo）---
                body_candidates = [
                    s2.select("article p"),
                    s2.select("div.caas-body p"),
                    s2.select("div.caas-content p"),
                    s2.select("div[class*='caas'] p")
                ]

                content = ""
                for c in body_candidates:
                    if c:
                        content = "\n".join([clean_text(p.get_text()) for p in c])
                        if len(content) > 50:
                            break

                if len(content) < 40:
                    continue

                # --- 必須包含財報關鍵字 ---
                if not contains_keywords(title + " " + content, FIN_KEYWORDS):
                    continue

                results.append({
                    "title": title,
                    "content": content[:2500],
                    "time": dt.isoformat(),
                    "source": "Yahoo",
                    "url": href
                })

                if len(results) >= per_page_limit:
                    return results

    logging.info(f"Yahoo 完成，取得 {len(results)} 篇")
    return results

# ---------------- Firestore ----------------
def save_to_firestore(article_list):
    if not article_list:
        logging.info("Firestore 無需寫入（0 篇）")
        return

    date_key = datetime.now().strftime("%Y%m%d")
    doc = db.collection(COLL_NAME).document(date_key).collection("articles")

    added = 0
    for art in article_list:
        uid = doc_id_from_url(art["url"])
        ref = doc.document(uid)

        if ref.get().exists:
            continue

        ref.set(art)
        added += 1

    logging.info(f"Firestore 新增 {added} 篇")

# ---------------- Local TXT ----------------
def save_to_local(article_list, filename="result.txt"):
    if not article_list:
        logging.info("本地檔案無需寫入（0 篇）")
        return

    with open(filename, "w", encoding="utf-8") as f:
        for art in article_list:
            f.write(f"[{art['time']}] {art['title']}\n")
            f.write(art['content'] + "\n")
            f.write(f"URL: {art['url']}\n")
            f.write("-"*50 + "\n")

    logging.info("已寫入本地 result.txt")

# ---------------- Main ----------------
def main():
    logging.info("開始抓取 Yahoo 財報新聞")
    articles = fetch_yahoo_financial()
    save_to_firestore(articles)
    save_to_local(articles)
    logging.info("全部完成")

if __name__ == "__main__":
    main()
