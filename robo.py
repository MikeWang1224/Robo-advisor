# -*- coding: utf-8 -*-
"""
光寶科新聞抓取 + Groq 情緒分析（Yahoo + 鉅亨網）
✔ 3 天內
✔ 中文金融模型評估：利多/利空/中性 + -1~1 分數 + 事件類型
✔ 寫入 Firestore（NEWS_LiteOn）
"""

import os
import requests 
import json
from datetime import datetime, timedelta
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings
import firebase_admin
from firebase_admin import credentials, firestore
from groq import Groq  # <--- 新增

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

HEADERS = {'User-Agent': 'Mozilla/5.0'}
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))   # <--- Groq 初始化

# Firestore 初始化
cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
firebase_admin.initialize_app(cred)
db = firestore.client()


# ----- 時間過濾（72 小時） -----
def is_recent(published_time, hours=72):
    now = datetime.now().astimezone()
    return (now - published_time) <= timedelta(hours=hours)


# ----- 抓文章內容 -----
def fetch_article_content(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')

        paragraphs = soup.select('article p') or soup.select('p')
        text = "\n".join(p.get_text(strip=True) for p in paragraphs)
        return text[:1500] + ('...' if len(text) > 1500 else '')
    except:
        return ""


# ----- 關鍵字判斷 -----
def contains_keyword(title, content):
    keywords = ["光寶科", "光寶", "2301"]
    text = (title + " " + content)
    return any(k in text for k in keywords)


# ----- Groq AI：新聞情緒、事件分析 -----
def analyze_news_groq(title, content):
    try:
        prompt = f"""
你是一位台股金融分析師，請閱讀以下新聞，針對「光寶科(2301)」評估對股價的可能影響。

請輸出 JSON 格式：
{{
  "sentiment": "利多 or 利空 or 中性",
  "score": -1.0 ~ 1.0,
  "reason": "簡短原因（必填）",
  "event": "接單/財報/法說/停工/出貨/訴訟/新品/一般新聞"
}}

新聞標題：{title}
新聞內容：{content}
"""

        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="qwen-2.5-32b",  # 中文模型（金融適用）
            temperature=0.3,
            max_tokens=300
        )

        text = response.choices[0].message.content
        try:
            result = json.loads(text)
        except:
            return None

        return result

    except Exception as e:
        print("❌ GROQ 分析錯誤：", e)
        return None


# =============================
#  Yahoo 新聞
# =============================
def fetch_yahoo_news(limit=80, pages=4):
    print("📡 抓取 Yahoo 新聞")
    base = "https://tw.news.yahoo.com"
    
    news_list = []
    seen = set()

    for page in range(1, pages + 1):
        url = f"https://tw.news.search.yahoo.com/search?p=光寶科&b={(page-1)*10+1}"
        r = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(r.text, 'html.parser')

        candidates = (
            soup.select("a.js-content-viewer") +
            soup.select("h3 a") +
            soup.select("a.d-ib") +
            soup.select("a[data-ylk]")
        )

        for a in candidates:
            if len(news_list) >= limit:
                return news_list

            title = a.get_text(strip=True)
            if not title or title in seen:
                continue
            seen.add(title)

            href = a.get("href")
            if not href:
                continue
            if href.startswith("/"):
                href = base + href

            content = fetch_article_content(href)
            if not contains_keyword(title, content):
                continue

            try:
                r2 = requests.get(href, headers=HEADERS)
                s2 = BeautifulSoup(r2.text, 'html.parser')
                time_tag = s2.find("time")

                if not time_tag or not time_tag.has_attr("datetime"):
                    continue

                published_dt = datetime.fromisoformat(
                    time_tag["datetime"].replace("Z", "+00:00")
                ).astimezone()

                if not is_recent(published_dt):
                    continue

            except:
                continue

            # *** AI 分析 ***
            ai = analyze_news_groq(title, content)

            news_list.append({
                "title": title,
                "content": content,
                "published_time": published_dt,
                "source": "Yahoo",
                "ai": ai
            })

    return news_list


# =============================
#  鉅亨網
# =============================
def fetch_cnyes_news(limit=40):
    print("📡 抓取 鉅亨網")

    keywords = ["光寶科", "光寶", "2301"]
    news_list = []
    seen = set()

    for kw in keywords:
        try:
            url = f"https://api.cnyes.com/media/api/v1/search/list?keyword={kw}&limit=50"
            r = requests.get(url, headers=HEADERS, timeout=10)
            items = r.json().get("items", {}).get("data", [])

            for item in items:
                if len(news_list) >= limit:
                    return news_list

                title = item.get("title", "")
                if not title or title in seen:
                    continue
                seen.add(title)

                timestamp = item.get("publishAt", 0)
                if not timestamp:
                    continue

                published_dt = datetime.fromtimestamp(timestamp).astimezone()
                if not is_recent(published_dt):
                    continue

                article_url = f"https://news.cnyes.com/news/id/{item.get('newsId')}?exp=a"
                content = fetch_article_content(article_url)

                if not contains_keyword(title, content):
                    continue

                # *** AI 分析 ***
                ai = analyze_news_groq(title, content)

                news_list.append({
                    "title": title,
                    "content": content,
                    "published_time": published_dt,
                    "source": "鉅亨網",
                    "ai": ai
                })

        except Exception as e:
            print("鉅亨網抓取錯誤：", e)

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
            "content": n["content"],
            "source": n["source"],
            "published_time": n["published_time"].strftime("%Y-%m-%d %H:%M"),
            "sentiment": n["ai"].get("sentiment") if n.get("ai") else None,
            "score": n["ai"].get("score") if n.get("ai") else None,
            "event": n["ai"].get("event") if n.get("ai") else None,
            "reason": n["ai"].get("reason") if n.get("ai") else None
        }

    ref.set(data)
    print(f"✅ 已存入 Firestore：NEWS_LiteOn/{doc_id}")


# =============================
# 主程式
# =============================
if __name__ == "__main__":
    yahoo_news = fetch_yahoo_news()
    cnyes_news = fetch_cnyes_news()

    all_news = yahoo_news + cnyes_news

    print(f"🔍 共抓到 {len(all_news)} 則光寶科相關新聞（3 天內）")

    if all_news:
        save_news(all_news)

    print("🎉 光寶科新聞抓取 + Groq 分析完成！")
