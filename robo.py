# trading_bot_from_groq_results.py
# -*- coding: utf-8 -*-
"""
簡易投資機器人（基於你存在 Firestore 的 Groq_result 結果 + 即時股價）
測試模式：全部從初始本金 1,000,000 計算
"""

import re
import json
import os
from datetime import datetime, timezone
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass, asdict

import requests
from google.cloud import firestore

# ------------------ 設定 ------------------
INITIAL_CAPITAL = 1_000_000
MAX_PER_TRADE = 50_000

FIRESTORE_PORTFOLIO_COLLECTION = "Trading_Portfolio"
FIRESTORE_ORDERS_COLLECTION = "Trading_Orders"

RESULT_COLLECTIONS = {
    "Groq_result": ("台積電", "2330"),
    "Groq_result_Foxxcon": ("鴻海", "2317"),
    "Groq_result_UMC": ("聯電", "2303"),
}

# ✅ 你的 GitHub 專案資料夾路徑（自己改成你的實際路徑）
GITHUB_RESULTS_FOLDER = r"./github_results"

# ------------------ Dataclasses ------------------
@dataclass
class Position:
    ticker: str
    shares: float
    avg_price: Optional[float]
    cost: float

@dataclass
class Order:
    timestamp: str
    ticker: str
    side: str
    amount: float
    shares: Optional[float]
    exec_price: Optional[float]
    status: str
    reason: str

# ------------------ 工具函式 ------------------

def get_db():
    return firestore.Client()

def get_twse_price(stock_no: str) -> float:
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{stock_no}.tw"
    try:
        r = requests.get(url, timeout=5)
        data = r.json()
        msg = data.get("msgArray", [])
        if msg and "z" in msg[0]:
            price_str = msg[0]["z"]
            if price_str != "--":
                return float(price_str)
    except Exception as e:
        print(f"[error] TWSE 抓價失敗：{e}")
    return 0.0

def read_latest_result(db: firestore.Client, collection_name: str) -> Optional[Dict]:
    try:
        coll = db.collection(collection_name)
        docs = coll.order_by("timestamp", direction=firestore.Query.DESCENDING).limit(1).stream()
        for d in docs:
            data = d.to_dict() or {}
            data["_doc_id"] = d.id
            return data
    except Exception as e:
        print(f"[warning] 讀取 {collection_name} 失敗：{e}")
    return None

def parse_trend_and_score(result_text: str) -> Tuple[Optional[str], Optional[int], str]:
    if not result_text:
        return None, None, ""
    txt = result_text
    trend = None

    if "上漲" in txt:
        trend = "上漲"
    elif "微漲" in txt:
        trend = "微漲"
    elif "微跌" in txt:
        trend = "微跌"
    elif "下跌" in txt:
        trend = "下跌"

    mood = None
    m2 = re.search(r"情緒分數：\s*([+-]?\d+)", txt)
    if m2:
        try:
            mood = int(m2.group(1))
        except:
            mood = None

    return trend, mood, txt

def place_order(db: firestore.Client, order: Order):
    db.collection(FIRESTORE_ORDERS_COLLECTION).add(asdict(order))

# ------------------ 決策邏輯 ------------------

def decide_actions(results: Dict[str, Dict], cash: float) -> Tuple[List[Order], float]:
    orders = []
    estimated_cash = cash

    for coll, (target, stock_no) in RESULT_COLLECTIONS.items():
        res = results.get(coll)
        if not res:
            continue

        text = res.get("result") or res.get("analysis") or ""
        trend, mood, _ = parse_trend_and_score(text)

        price = get_twse_price(stock_no)
        if price <= 0:
            continue

        if trend in ["上漲", "微漲"]:
            amt = min(MAX_PER_TRADE, estimated_cash)
            if amt >= 1000:
                shares = round(amt / price, 4)
                real_amt = shares * price
                estimated_cash -= real_amt

                orders.append(Order(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    ticker=target,
                    side="BUY",
                    amount=real_amt,
                    shares=shares,
                    exec_price=price,
                    status="PENDING",
                    reason=f"trend={trend}, mood={mood}"
                ))

    return orders, estimated_cash

# ------------------ 輸出檔案 ------------------

def write_report_to_folders(text: str):
    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H.%M.%S")
    filename = f"{ts}.txt"

    # 本地 results
    local_folder = "results"
    os.makedirs(local_folder, exist_ok=True)
    local_path = os.path.join(local_folder, filename)

    # GitHub 專案資料夾
    os.makedirs(GITHUB_RESULTS_FOLDER, exist_ok=True)
    github_path = os.path.join(GITHUB_RESULTS_FOLDER, filename)

    # 寫檔
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(text)

    with open(github_path, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"✅ 已輸出本地：{local_path}")
    print(f"✅ 已輸出 GitHub 資料夾：{github_path}")

# ------------------ 主程式 ------------------

def main():
    db = get_db()

    cash = INITIAL_CAPITAL

    results = {}
    for coll in RESULT_COLLECTIONS.keys():
        doc = read_latest_result(db, coll)
        if doc:
            results[coll] = doc

    orders, est_cash = decide_actions(results, cash)

    for o in orders:
        place_order(db, o)

    # 建立報告文字
    lines = []
    lines.append("==== 今日交易模擬報告 ====")
    lines.append(f"初始本金：{INITIAL_CAPITAL:,}")
    lines.append(f"剩餘現金：{est_cash:,.0f}")
    lines.append("")

    if orders:
        lines.append("交易紀錄：")
        for o in orders:
            lines.append(f"{o.side} {o.ticker} 金額={o.amount:.0f} 股數={o.shares} 價格={o.exec_price}")
    else:
        lines.append("今日無交易")

    report_text = "\n".join(lines)

    # 輸出到本地 + GitHub 資料夾
    write_report_to_folders(report_text)

    print("✅ 執行完成")

if __name__ == "__main__":
    main()
