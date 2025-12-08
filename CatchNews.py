# -*- coding: utf-8 -*-
"""
光寶科新聞抓取（TechNews + Yahoo + CNBC） - 修正版
✔ 只抓光寶科
✔ 抓新聞全文
✔ 時間過濾：36 小時內
✔ 寫入 Firestore，不存股價
✔ 更穩健的 selector、重試、錯誤處理、去重
"""
import os
import time
import json
import re
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict
import requests
from bs4 import BeautifulSoup

# Optional: better date parsing if python-dateutil is installed
try:
    from dateutil import parser as dateparser
except Exception:
    dateparser = None

# Firestore imports
import firebase_admin
from firebase_admin import credentials, firestore

# -----------------------------
# 設定
# -----------------------------
COLL_NAME = "NEWS_LiteOn"
KEYWORDS = ["光寶科", "光寶", "2301", "Lite-On", "LiteOn", "Lite On"]
MAX_HOURS = 36
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/117.0.0.0 Safari/537.36"
}
REQUEST_TIMEOUT = 15  # seconds
MAX_RETRIES = 3
SLEEP_BETWEEN_REQ = 0.4

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# -----------------------------
# Firestore 初始化
# -----------------------------
if not firebase_admin._apps:
    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not cred_path:
        logging.error("請先設定環境變數 GOOGLE_APPLICATION_CREDENTIALS 指向你的 Firebase key JSON 檔案")
        raise SystemExit("Missing GOOGLE_APPLICATION_CREDENTIALS")
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# -----------------------------
# 工具函式
# -----------------------------
def now():
    return datetime.now(timezone.utc)

def is_recent(dt: datetime) -> bool:
    """判斷是否在 MAX_HOURS 內。接受 timezone-aware dt 或 naive (視為本地時間)。"""
    if dt.tzinfo is None:
        # assume local -> convert to UTC using system local offset
        dt = dt.replace(tzinfo=timezone.utc)
    return (now() - dt).total_seconds() <= MAX_HOURS * 3600

def parse_datetime(dt_str: str) -> datetime:
    """嘗試解析時間字串為 datetime（UTC-aware）。若解析失敗會拋例外。"""
    if not dt_str or not isinstance(dt_str, str):
        raise ValueError("空的時間字串")
    dt_str = dt_str.strip()
    # try dateutil if available
    if dateparser:
        try:
            parsed = dateparser.parse(dt_str)
            if parsed is None:
                raise ValueError("dateutil 無法解析")
            # make timezone-aware: if naive, assume UTC (many news sites use ISO Z)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            pass
    # fallback common patterns
    # ISO-like
    iso_try = re.sub(r'(\.\d+)?Z$', '+00:00', dt_str)
    try:
        parsed = datetime.fromisoformat(iso_try)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        pass
    # common formats
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(dt_str, fmt)
            parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            continue
    raise ValueError(f"無法解析時間: {dt_str}")

# requests session with retries
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(max_retries=3)
session.mount("http://", adapter)
session.mount("https://", adapter)
session.headers.update(HEADERS)

def safe_get(url: str, headers: dict = None, timeout=REQUEST_TIMEOUT):
    headers = headers or {}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            logging.warning(f"GET {url} 失敗 (attempt {attempt}): {e}")
            if attempt < MAX_RETRIES:
                time.sleep(0.5 * attempt)
            else:
                return None

def clean_text(s: str) -> str:
    return re.sub(r'\s+', ' ', s).strip()

# -----------------------------
# TechNews
# -----------------------------
def fetch_technews(keyword="光寶科", limit=30) -> List[Dict]:
    logging.info(f"📡 TechNews：{keyword}")
    links = []
    results = []
    # 改為官方搜尋 page(s)
    search_url = f"https://technews.tw/page/1/?s={requests.utils.requote_uri(keyword)}"
    r = safe_get(search_url)
    if not r:
        logging.warning("TechNews 搜尋頁抓取失敗")
        return results
    s = BeautifulSoup(r.text, "html.parser")
    # WordPress 常用文章卡片 selector
    cards = s.select("article.post a") or s.select("h2.entry-title a") or s.select(".entry-title a")
    for a in cards:
        href = a.get("href")
        if href and href.startswith("https://technews.tw/"):
            links.append(href)
    # 去重並限制數量
    links = list(dict.fromkeys(links))[:limit]
    for link in links:
        time.sleep(SLEEP_BETWEEN_REQ)
        r2 = safe_get(link)
        if not r2:
            continue
        s2 = BeautifulSoup(r2.text, "html.parser")
        title_tag = s2.find('h1') or s2.select_one(".entry-title") or s2.select_one("h1.entry-title")
        if not title_tag:
            continue
        title = clean_text(title_tag.get_text())
        # time tag: TechNews 用 <time class="entry-date">YYYY/MM/DD HH:MM</time>
        time_tag = s2.find("time", class_="entry-date")
        published_dt = None
        if time_tag:
            try:
                published_dt = parse_datetime(time_tag.get_text(strip=True))
            except Exception:
                pass
        # fallback: meta[property="article:published_time"]
        if not published_dt:
            meta = s2.find("meta", {"property": "article:published_time"}) or s2.find("meta", {"name": "pubdate"})
            if meta and meta.has_attr("content"):
                try:
                    published_dt = parse_datetime(meta["content"])
                except Exception:
                    pass
        if not published_dt:
            # 無時間資料則跳過（避免抓到無關內容）
            continue
        if not is_recent(published_dt):
            continue
        paras = s2.select("article p") or s2.select("p")
        content = "\n".join([clean_text(p.get_text()) for p in paras if len(clean_text(p.get_text())) > 40])
        if not content:
            continue
        results.append({
            "title": title,
            "content": content[:1500],
            "time": published_dt.strftime("%Y-%m-%d %H:%M %Z"),
            "source": "TechNews",
            "url": link
        })
    logging.info(f"TechNews 抓到 {len(results)} 筆符合的新聞")
    return results

# -----------------------------
# Yahoo
# -----------------------------
def fetch_yahoo(keyword="光寶科", limit=30) -> List[Dict]:
    logging.info(f"📡 Yahoo：{keyword}")
    base = "https://tw.news.yahoo.com"
    # 用 search?p=keyword&sort=time
    search_url = f"{base}/search?p={requests.utils.requote_uri(keyword)}&sort=time"
    news_list = []
    seen_titles = set()
    r = safe_get(search_url)
    if not r:
        logging.warning("Yahoo 搜尋頁抓取失敗")
        return news_list
    s = BeautifulSoup(r.text, "html.parser")
    # 搜尋結果的連結可能在多種位置，嘗試幾種 selector
    link_selectors = [
        'a.js-content-viewer',  # 舊版
        'h3 a',                 # 常見
        'a[href*="/news/"]',    # 直接過濾 news 路徑
        'a[href*="/articles/"]'
    ]
    candidates = []
    for sel in link_selectors:
        candidates += s.select(sel)
    # 以 href 過濾，且確保連到 tw.news.yahoo.com 或外部來源的新聞頁
    links = []
    for a in candidates:
        href = a.get("href") or a.get("data-href")
        if not href:
            continue
        # 可能是相對路徑
        if href.startswith("/"):
            href = base + href
        # exclude ad/tracking
        if 'yahoo.com/amp' in href or 'video' in href:
            # still allow amp if it's article
            pass
        links.append((href, clean_text(a.get_text() or "")))
    # 去重順序保持
    seen = set()
    filtered_links = []
    for href, title_text in links:
        if href in seen:
            continue
        seen.add(href)
        filtered_links.append((href, title_text))
        if len(filtered_links) >= limit * 2:
            break
    for href, title_text in filtered_links:
        if len(news_list) >= limit:
            break
        time.sleep(SLEEP_BETWEEN_REQ)
        r2 = safe_get(href)
        if not r2:
            continue
        s2 = BeautifulSoup(r2.text, "html.parser")
        # 試著抓 title 與時間
        title = title_text or (s2.find("h1") and clean_text(s2.find("h1").get_text())) or ""
        if not title:
            # fallback meta
            meta_title = s2.find("meta", {"property": "og:title"}) or s2.find("meta", {"name": "title"})
            if meta_title and meta_title.get("content"):
                title = clean_text(meta_title["content"])
        if not title or title in seen_titles:
            continue
        # time: <time datetime="..."> 或 meta property article
        published_dt = None
        time_tag = s2.find("time")
        if time_tag and time_tag.has_attr("datetime"):
            try:
                published_dt = parse_datetime(time_tag["datetime"])
            except Exception:
                # sometimes it's inner text
                try:
                    published_dt = parse_datetime(time_tag.get_text(strip=True))
                except Exception:
                    published_dt = None
        if not published_dt:
            meta = s2.find("meta", {"property": "article:published_time"}) or s2.find("meta", {"name": "ptime"})
            if meta and meta.has_attr("content"):
                try:
                    published_dt = parse_datetime(meta["content"])
                except Exception:
                    published_dt = None
        if not published_dt:
            # 如果沒有時間，跳過以免超時或抓到不是新聞的頁面
            continue
        if not is_recent(published_dt):
            continue
        paras = s2.select("article p") or s2.select("div[class*='article'] p') or s2.select("p")
        content = "\n".join([clean_text(p.get_text()) for p in paras if len(clean_text(p.get_text())) > 40])
        if not content:
            continue
        # 關鍵字檢查：確保內文或標題有關鍵字（避免抓到無關頁面）
        if not any(k.lower() in (title + content).lower() for k in KEYWORDS):
            continue
        news_list.append({
            "title": title,
            "content": content[:1500],
            "time": published_dt.strftime("%Y-%m-%d %H:%M %Z"),
            "source": "Yahoo",
            "url": href
        })
        seen_titles.add(title)
    logging.info(f"Yahoo 抓到 {len(news_list)} 筆符合的新聞")
    return news_list

# -----------------------------
# CNBC（保留但容錯）
# -----------------------------
def fetch_cnbc(keyword_list=["Lite-On"], limit=20) -> List[Dict]:
    logging.info(f"📡 CNBC：{'/'.join(keyword_list)}")
    base_search = "https://www.cnbc.com/search/?query=" + '+'.join(requests.utils.requote_uri(k) for k in keyword_list)
    results = []
    r = safe_get(base_search)
    if not r:
        logging.warning("CNBC 搜尋頁抓取失敗")
        return results
    s = BeautifulSoup(r.text, "html.parser")
    articles = s.select("article a") or s.select(".SearchResult-card a") or s.select("a.Card-title")
    seen = set()
    for a in articles:
        if len(results) >= limit:
            break
        href = a.get("href")
        title = clean_text(a.get_text() or "")
        if not href or not title:
            continue
        # 跳過重複
        if title in seen:
            continue
        # 確認標題含關鍵字
        if not any(k.lower() in title.lower() for k in keyword_list):
            # 也可嘗試到內文檢查，但先過濾一輪
            pass
        # 完整連結
        if not href.startswith("http"):
            href = "https://www.cnbc.com" + href
        time.sleep(SLEEP_BETWEEN_REQ)
        r2 = safe_get(href)
        if not r2:
            continue
        s2 = BeautifulSoup(r2.text, "html.parser")
        # 試抓時間
        published_dt = None
        time_tag = s2.find("time")
        if time_tag and time_tag.has_attr("datetime"):
            try:
                published_dt = parse_datetime(time_tag["datetime"])
            except Exception:
                pass
        if not published_dt:
            meta = s2.find("meta", {"property": "article:published_time"})
            if meta and meta.has_attr("content"):
                try:
                    published_dt = parse_datetime(meta["content"])
                except Exception:
                    pass
        if not published_dt:
            continue
        if not is_recent(published_dt):
            continue
        paras = s2.select("p")
        content = "\n".join([clean_text(p.get_text()) for p in paras if len(clean_text(p.get_text())) > 40])
        if not content:
            continue
        # 再檢查關鍵字
        if not any(k.lower() in (title + content).lower() for k in KEYWORDS):
            continue
        results.append({
            "title": title,
            "content": content[:1500],
            "time": published_dt.strftime("%Y-%m-%d %H:%M %Z"),
            "source": "CNBC",
            "url": href
        })
        seen.add(title)
    logging.info(f"CNBC 抓到 {len(results)} 筆符合的新聞")
    return results

# -----------------------------
# Firestore 寫入
# -----------------------------
def save_news(news_list: List[Dict]):
    if not news_list:
        logging.warning("⚠️ 沒有新聞可寫入")
        return
    # 去重（以 title + source 為 key）
    unique = {}
    for n in news_list:
        key = (n.get("title","").strip(), n.get("source",""))
        if key not in unique:
            unique[key] = n
    news_items = list(unique.values())
    today = datetime.now().strftime("%Y%m%d")
    ref = db.collection(COLL_NAME).document(today)
    data = {}
    for i, n in enumerate(news_items, 1):
        data[f"news_{i}"] = n
    try:
        ref.set(data)
        logging.info(f"🔥 Firestore 已寫入 → {COLL_NAME}/{today}")
        logging.info(f"📦 共 {len(news_items)} 則新聞")
    except Exception as e:
        logging.error(f"Firestore 寫入失敗: {e}")

# -----------------------------
# 主程式
# -----------------------------
def main():
    all_news = []
    try:
        all_news += fetch_technews("光寶科", 30)
    except Exception as e:
        logging.exception("TechNews 抓取發生錯誤：%s", e)
    try:
        all_news += fetch_yahoo("光寶科", 30)
    except Exception as e:
        logging.exception("Yahoo 抓取發生錯誤：%s", e)
    try:
        # CNBC 關鍵字採多形態，比對較寬鬆
        all_news += fetch_cnbc(["Lite-On", "LiteOn", "Lite On"], 20)
    except Exception as e:
        logging.exception("CNBC 抓取發生錯誤：%s", e)

    # 最後再去一次關鍵字過濾（保險）
    filtered = []
    for n in all_news:
        if any(k.lower() in (n.get("title","") + n.get("content","")).lower() for k in KEYWORDS):
            filtered.append(n)
    save_news(filtered)
    logging.info("🎉 全部新聞抓取完成！")

if __name__ == "__main__":
    main()
