# -*- coding: utf-8 -*-
"""
liteon_groq_sentiment.py

功能：
- 從 Firestore 讀取 NEWS_LiteOn/{doc} 的新聞（未分析者）
- 用 Groq 中文模型做情緒 (利多/利空/中性)、score(-1~1)、event、reason
- 將結果寫回 Firestore（同 doc 下新增 ai_xxx 欄位，並在另一 collection 建立彙總）
- 簡單重試、速率控制、日誌輸出
"""

import os
import time
import json
import re
from datetime import datetime
from typing import Dict, Any, List, Optional

import firebase_admin
from firebase_admin import credentials, firestore

import requests  # 使用 requests 對 Groq REST API (較通用)
# 如果你有官方 groq python 客戶端，可替換成該 client

# ---------- 設定 ----------
SRC_COLLECTION = "NEWS_LiteOn"           # 原始新聞位置
DST_COLLECTION = "NEWS_Sentiment_LiteOn" # 分析後彙總位置（可選）
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.ai/v1/chat/completions"  # 以 REST API 為例
MAX_PER_RUN = 200     # 單次處理總新聞上限（避免一次處理太多）
SLEEP_BETWEEN_CALLS = 0.6  # 每次呼叫 Groq 的最小間隔（秒）
RETRY_TIMES = 2
# -------------------------

if not GROQ_API_KEY:
    raise RuntimeError("請在環境變數設定 GROQ_API_KEY")

# Firebase init
cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
firebase_admin.initialize_app(cred)
db = firestore.client()


# ---------- 幫助函式 ----------
def extract_json_from_text(txt: str) -> Optional[Dict[str, Any]]:
    """
    嘗試從模型回傳的文字中擷取 JSON 物件。
    支援回傳時有 ``` 或其他雜訊的情形。
    """
    # 先找第一個 { ... } 區塊
    m = re.search(r"(\{(?:.|\s)*\})", txt)
    if m:
        candidate = m.group(1)
        try:
            return json.loads(candidate)
        except Exception:
            # 嘗試用單引號轉雙引號（最後手段）
            try:
                fixed = candidate.replace("'", '"')
                return json.loads(fixed)
            except Exception:
                return None
    # 若沒找到 JSON，嘗試 entire string parse
    try:
        return json.loads(txt)
    except Exception:
        return None


def build_prompt(title: str, content: str) -> str:
    """
    建 prompt（中文），要求模型輸出嚴格 JSON
    """
    prompt = f"""
你是一位台股金融分析師（使用中文）。請閱讀下列新聞（新聞標題與內文），針對「光寶科 (2301)」評估對股價的可能影響，並**只回傳純 JSON**，格式如下：
{{
  "sentiment": "利多" 或 "利空" 或 "中性",
  "score": 數字 (浮點), 介於 -1.0 ~ 1.0,
  "event": "接單/財報/法說/停工/出貨/訴訟/新品/一般新聞",
  "reason": "一句話說明判斷原因（中文，簡短）"
}}

新聞標題：{title}
新聞內容：{content}

注意：
- JSON 欄位名稱請精確對應上面四個欄位。
- score 越接近 1 表示強烈利多，越接近 -1 表示強烈利空。
- 不要在回應中加入任何額外文字或程式碼塊，若能請直接輸出 JSON。
"""
    return prompt


def call_groq(prompt: str, model: str = "qwen-2.5-32b", temperature: float = 0.0) -> Optional[Dict[str, Any]]:
    """
    透過 Groq REST API 呼叫模型 (chat completion style)
    回傳解析過的 dict（或 None）
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GROQ_API_KEY}"
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": temperature,
        "max_tokens": 400,
    }

    for attempt in range(RETRY_TIMES + 1):
        try:
            r = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=30)
            if r.status_code != 200:
                print(f"Groq 回應非 200: {r.status_code}, body: {r.text}")
                time.sleep(1 + attempt * 1.5)
                continue

            resp = r.json()
            # 嘗試抓第一條 message content
            content = None
            if "choices" in resp and len(resp["choices"]) > 0:
                # 不同 API 回傳結構可能不同，嘗試多種 key
                ch = resp["choices"][0]
                if isinstance(ch, dict) and "message" in ch and "content" in ch["message"]:
                    content = ch["message"]["content"]
                elif "text" in ch:
                    content = ch["text"]
                else:
                    # fallback to stringify
                    content = json.dumps(ch)

            if not content:
                print("Groq 回傳無 content，原始回應：", resp)
                return None

            parsed = extract_json_from_text(content)
            if parsed:
                return parsed
            else:
                print("無法解析 JSON，模型原始回傳：", content)
                return None

        except Exception as e:
            print("呼叫 Groq 發生例外：", e)
            time.sleep(1 + attempt * 1.5)

    return None


# ---------- Firestore 讀取未分析新聞 ----------
def fetch_unprocessed_news(limit: int = 200) -> List[Dict[str, Any]]:
    """
    讀取 SRC_COLLECTION 最新幾份 doc（按 doc id 當成日期排序），
    並回傳裡面沒有 'sentiment' 欄位或 ai 欄位為空的新聞項目（合併回傳：包含 doc_ref info）
    回傳結構：
    [
      {
        "doc_id": "20251201",
        "field": "news_1",
        "title": ...,
        "content": ...,
        "published_time": "...",
        "source": ...,
        "raw_doc_ref": <DocumentReference>
      }, ...
    ]
    """
    results = []
    # 取得最近 N 個 doc（Firestore 沒有內建「排序檔名」的方法，這裡列出所有後挑最近的）
    docs = db.collection(SRC_COLLECTION).list_documents()
    doc_ids = [d.id for d in docs]
    doc_ids = sorted(doc_ids, reverse=True)  # 以 id 倒序（假設 id 為 YYYYMMDD）
    checked = 0

    for doc_id in doc_ids:
        if checked >= 50:  # 防止一次掃太多 doc
            break
        doc_ref = db.collection(SRC_COLLECTION).document(doc_id)
        doc = doc_ref.get()
        if not doc.exists:
            continue
        data = doc.to_dict()
        # 尋找所有 news_x 欄位
        for k, v in data.items():
            if not k.startswith("news_"):
                continue
            checked += 1
            if checked > limit:
                break
            # 如果已經有 sentiment 或 score 就跳過
            if isinstance(v, dict) and ("sentiment" in v or "score" in v or v.get("ai_analyzed", False)):
                continue
            title = v.get("title") or ""
            content = v.get("content") or ""
            results.append({
                "doc_id": doc_id,
                "field": k,
                "title": title,
                "content": content,
                "source": v.get("source"),
                "published_time": v.get("published_time"),
                "doc_ref": doc_ref
            })
        if checked >= limit:
            break

    print(f"fetch_unprocessed_news -> 取得 {len(results)} 則尚未分析的新聞")
    return results


# ---------- 主處理流程 ----------
def process_batch():
    items = fetch_unprocessed_news(limit=MAX_PER_RUN)
    if not items:
        print("沒有待處理的新聞。")
        return

    processed = []
    for i, item in enumerate(items, 1):
        title = item["title"]
        content = item["content"]
        doc_ref = item["doc_ref"]
        field = item["field"]
        doc_id = item["doc_id"]

        # 安全檢查：若內容過短，跳過
        if not title and not content:
            print(f"[{doc_id}/{field}] 無標題與內容，跳過")
            continue

        prompt = build_prompt(title, content)
        print(f"[{i}/{len(items)}] 分析 {doc_id}/{field} - {title[:60]}")

        ai_result = call_groq(prompt)
        # 等短暫時間，避免被限流
        time.sleep(SLEEP_BETWEEN_CALLS)

        # 若呼叫失敗，記錄並標示已嘗試
        if not ai_result:
            print(f" -> Groq 無回傳或解析失敗，標記嘗試後跳過：{doc_id}/{field}")
            try:
                # 在原始 doc 的該 news_x 加上 ai_analyzed = True, ai_error = True
                doc_ref.update({f"{field}.ai_analyzed": True, f"{field}.ai_error": True})
            except Exception as e:
                print("寫回 Firestore 標記錯誤：", e)
            continue

        # 清理與預設值
        sentiment = ai_result.get("sentiment")
        score = ai_result.get("score")
        event = ai_result.get("event")
        reason = ai_result.get("reason")

        # 嘗試把 score 轉成 float
        try:
            score = float(score)
        except Exception:
            # 若模型給 "0.7" 或 "0.7)" 等，嘗試提取數字
            m = re.search(r"-?\d+\.?\d*", str(score or ""))
            score = float(m.group(0)) if m else None

        # 組要寫回的 payload（同一 doc 裡更新該 news_x 的 ai 欄位）
        ai_payload = {
            f"{field}.ai_analyzed": True,
            f"{field}.sentiment": sentiment,
            f"{field}.score": score,
            f"{field}.event": event,
            f"{field}.reason": reason,
            f"{field}.ai_ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        try:
            doc_ref.update(ai_payload)
        except Exception as e:
            print("寫回 Firestore 發生錯誤：", e)
            continue

        # 也寫入 DST_COLLECTION 作為彙總（以 doc_id 為 key）
        try:
            dst_ref = db.collection(DST_COLLECTION).document(doc_id)
            dst_ref.set({
                field: {
                    "title": title,
                    "content": content,
                    "source": item.get("source"),
                    "published_time": item.get("published_time"),
                    "sentiment": sentiment,
                    "score": score,
                    "event": event,
                    "reason": reason,
                    "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            }, merge=True)
        except Exception as e:
            print("寫入 DST_COLLECTION 錯誤：", e)

        processed.append((doc_id, field, sentiment, score))
    print(f"處理完成，共分析 {len(processed)} 筆新聞。")


if __name__ == "__main__":
    process_batch()
