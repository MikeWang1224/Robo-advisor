# -*- coding: utf-8 -*-
"""
Yahoo 財經新聞抓取（光寶科）
抓所有光寶科新聞 → 再挑財報/法說/公告
時間篩選：36 小時
Firestore：NEWS_LiteOn / YYYYMMDD / articles
本地：result.txt（永不為空）
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
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
    )
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
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r
        except Exception:
            time.sleep(0.5 * attempt)
    return None

def clean_text(s):
    return re.sub(r"\s+", " ", s).strip() if s else ""

def now_utc():
    return datetime.now(timezone.utc)

def parse_datetime_fuzzy(s):
    if not s:
        return None
    try:
        dt = dateparser.parse(s)
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except:
        return None

def is_recent(dt):
    if not dt:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now_utc() - dt).total_seconds() <= MAX_HOURS * 3600

def contains_keywords(text, keywords):
    t = text.lower()
    return any(k.lower() in t for k in keywords)

def doc_id_from_url(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


# ---------------- Yahoo 抓全部光寶新聞 ----------------
def fetch_yahoo_all(keywords=None, pages=5):
    if keywords is None:
        keywords = KEYWORDS

    base = "https://tw.news.yahoo.com"
    results = []
    seen = set()

    logging.info("📡 Yahoo 搜尋（不篩財報）開始…")

    for kw in keywords:
        for page in range(1, pages + 1):
            b = (page - 1) * 10 + 1
            url = f"{base}/search?p={kw}&sort=time&b={b}"

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
                if href in seen:
                    continue
                seen.add(href)

                # 抓內頁
                time.sleep(SLEEP_BETWEEN_REQ)
                r2 = safe_get(href)
                if not r2:
                    continue

                s2 = BeautifulSoup(r2.text, "html.parser")

                # 標題
                title = clean_text(s2.find("h1").get_text()) if s2.find("h1") else ""
                if not title:
                    continue

                # 必須包含光寶關鍵字
                if not contains_keywords(title, ["光寶", "光寶科", "2301"]):
                    continue

                # 時間
                t = s2.find("time")
                dt = None
                if t and t.has_attr("datetime"):
                    dt = parse_datetime_fuzzy(t["datetime"])

                if not dt or not is_recent(dt):
                    continue

                # 抓內文（強化 selector）
                selectors = [
                    "article p",
                    "div.caas-body p",
                    "div.caas-content p",
                    "div[class*='caas'] p"
                ]
                content = ""
                for sel in selectors:
                    paras = s2.select(sel)
                    if paras:
                        text = "\n".join([clean_text(p.get_text()) for p in paras])
                        if len(text) > 40:
                            content = text
                            break
                if len(content) < 30:
                    continue

                results.append({
                    "title": title,
                    "content": content[:2500],
                    "time": dt.isoformat(),
                    "url": href,
                    "source": "Yahoo"
                })

    logging.info(f"Yahoo 搜尋完成，共抓到 {len(results)} 則光寶科新聞（尚未篩財報）")
    return results


# ---------------- 過濾財報/法說類 ----------------
def filter_financial_news(articles):
    fin = []
    for a in articles:
        if contains_keywords(a["title"] + " " + a["content"], FIN_KEYWORDS):
            fin.append(a)
    logging.info(f"經財報篩選後，共 {len(fin)} 則")
    return fin


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
    with open(filename, "w", encoding="utf-8") as f:

        if not article_list:
            f.write("今日沒有任何符合（財報/法說/公告）的光寶科新聞。\n")
            logging.info("result.txt 已寫入（無新聞但不為空）")
            return

        for art in article_list:
            f.write(f"[{art['time']}] {art['title']}\n")
            f.write(art['content'] + "\n")
            f.write(f"URL: {art['url']}\n")
            f.write("-" * 60 + "\n")

    logging.info("result.txt 已寫入（有內容）")


# ---------------- Main ----------------
def main():
    logging.info("開始抓取 Yahoo 光寶科新聞（完整模式）")

    all_news = fetch_yahoo_all()          # 抓所有光寶新聞
    fin_news = filter_financial_news(all_news)  # 篩財報/法說/公告

    save_to_firestore(fin_news)
    save_to_local(fin_news)

    logging.info("抓取完成。")

if __name__ == "__main__":
    main()
