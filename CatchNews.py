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
except Exception:
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
        logging.error("請先設定環境變數 GOOGLE_APPLICATION_CREDENTIALS 指向你的 Firebase key JSON 檔案")
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
    try:
        iso = re.sub(r'(\.\d+)?Z$', '+00:00', s)
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except:
        pass
    formats = ["%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
    for f in formats:
        try:
            dt = datetime.strptime(s, f)
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except:
            continue
    return None

def is_recent(dt):
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now_utc() - dt).total_seconds() <= MAX_HOURS*3600

def contains_keywords(text, keywords):
    if not text:
        return False
    txt = text.lower()
    for k in keywords:
        if k.lower() in txt:
            return True
    return False

def doc_id_from_url(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()

# ---------------- Yahoo 財經抓取 ----------------
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
            s = BeautifulSoup(r.text, "html.parser")
            links = s.select("a.js-content-viewer") or s.select("h3 a") or s.select("a[href*='/news/']")
            for a in links:
                href = a.get("href") or a.get("data-href")
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
                title_tag = s2.find("h1")
                title = clean_text(title_tag.get_text()) if title_tag else ""
                dt = None
                time_tag = s2.find("time")
                if time_tag and time_tag.has_attr("datetime"):
                    dt = parse_datetime_fuzzy(time_tag["datetime"])
                if not dt:
                    meta = s2.find("meta", {"property":"article:published_time"}) or s2.find("meta", {"name":"ptime"})
                    if meta and meta.get("content"):
                        dt = parse_datetime_fuzzy(meta.get("content"))
                if not dt or not is_recent(dt):
                    continue
                paras = s2.select("article p") or s2.select('div[class*="article"] p') or s2.select("p")
                content = "\n".join([clean_text(p.get_text()) for p in paras if len(clean_text(p.get_text()))>40])
                if not content:
                    continue
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
                    break
            if len(results) >= per_page_limit:
                break
    logging.info(f"Yahoo 完成，取得 {len(results)} 篇")
    return results

# ---------------- Save to Firestore ----------------
def save_to_firestore(article_list):
    if not article_list:
        logging.info("沒有文章要寫入 Firestore")
        return
    date_key = datetime.now().strftime("%Y%m%d")
    base_doc = db.collection(COLL_NAME).document(date_key)
    articles_col = base_doc.collection("articles")
    added = 0
    for art in article_list:
        uid = doc_id_from_url(art.get("url","") or art.get("title","") + str(art.get("time","")))
        try:
            doc_ref = articles_col.document(uid)
            if doc_ref.get().exists:
                continue
            doc_ref.set({
                "title": art.get("title"),
                "content": art.get("content"),
                "time": art.get("time"),
                "source": art.get("source"),
                "url": art.get("url"),
                "fetched_at": now_utc().isoformat()
            })
            added += 1
        except Exception as e:
            logging.warning(f"寫入單篇失敗: {e}")
    try:
        base_doc.collection("meta").document("summary").set({
            "date": date_key,
            "total_fetched": len(article_list),
            "added": added,
            "updated_at": now_utc().isoformat()
        })
    except Exception as e:
        logging.warning(f"寫入 meta 失敗: {e}")
    logging.info(f"Firestore 已寫入：新增 {added} 篇（總抓取 {len(article_list)} 篇）")

# ---------------- Save to local file ----------------
def save_to_local(article_list, filename="result.txt"):
    if not article_list:
        logging.info("沒有文章要寫入本地檔案")
        return
    try:
        with open(filename, "w", encoding="utf-8") as f:
            for art in article_list:
                f.write(f"[{art['time']}] {art['title']}\n")
                f.write(f"{art['content']}\n")
                f.write(f"URL: {art['url']}\n")
                f.write("-"*60 + "\n")
        logging.info(f"已寫入本地檔案：{filename}")
    except Exception as e:
        logging.warning(f"寫入本地檔案失敗: {e}")

# ---------------- Main ----------------
def main():
    logging.info("開始抓取（Yahoo 財經光寶科財報新聞）")
    all_articles = fetch_yahoo_financial(KEYWORDS, pages=5, per_page_limit=50)
    save_to_firestore(all_articles)
    save_to_local(all_articles)
    logging.info("抓取完成。")

if __name__ == "__main__":
    main()
