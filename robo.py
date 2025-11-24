# trading_bot_from_groq_results.py
# -*- coding: utf-8 -*-
"""
簡易投資機器人（基於你存在 Firestore 的 Groq_result 結果 + 即時股價）
目的：
  - 從 Groq_result / Groq_result_Foxxcon / Groq_result_UMC 讀取最新分析結果
  - 根據分析結果決定今日（或隔日開盤）買賣
  - 初始本金 1,000,000（新台幣）
  - 單次建倉上限 50,000
  - 僅做多（長倉），遇偏空時賣出已持有部位
"""

import re
import json
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
    """
    抓台灣上市股票即時成交價
    stock_no: 股票代號，例如 '2330'
    """
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{stock_no}.tw"
    try:
        r = requests.get(url)
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
            data['_doc_id'] = d.id
            return data
        docs2 = coll.stream()
        latest = None
        latest_time = None
        for d in docs2:
            try:
                doc = d.to_dict() or {}
                ts = doc.get('timestamp')
                if ts:
                    t = datetime.fromisoformat(ts)
                    if latest_time is None or t > latest_time:
                        latest_time = t
                        latest = (d.id, doc)
            except:
                continue
        if latest:
            docid, doc = latest
            doc['_doc_id'] = docid
            return doc
    except Exception as e:
        print(f"[warning] 讀取 {collection_name} 失敗：{e}")
    return None

def parse_trend_and_score(result_text: str) -> Tuple[Optional[str], Optional[int], str]:
    if not result_text:
        return None, None, ""
    txt = result_text
    trend = None

    m = re.search(r"明天[^\n：]*股價走勢：?\s*([上微下漲跌]{2,3})", txt)
    if m:
        trend = m.group(1)
    else:
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

def load_portfolio(db: firestore.Client) -> Dict[str, Position]:
    portfolio = {}
    try:
        doc = db.collection(FIRESTORE_PORTFOLIO_COLLECTION).document("account").get()
        if doc.exists:
            data = doc.to_dict() or {}
            inv = data.get('investments', {})
            for t, v in inv.items():
                portfolio[t] = Position(
                    ticker=t,
                    shares=float(v.get('shares', 0.0)),
                    avg_price=v.get('avg_price'),
                    cost=float(v.get('cost', 0.0))
                )
            return portfolio
    except Exception as e:
        print(f"[warning] 載入 portfolio 失敗：{e}")
    return portfolio

def save_portfolio(db: firestore.Client, portfolio: Dict[str, Position], cash: float):
    inv = {}
    for t, p in portfolio.items():
        inv[t] = {
            'shares': p.shares,
            'avg_price': p.avg_price,
            'cost': p.cost,
        }
    payload = {
        'cash': cash,
        'investments': inv,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    db.collection(FIRESTORE_PORTFOLIO_COLLECTION).document('account').set(payload)

def place_order(db: firestore.Client, order: Order):
    db.collection(FIRESTORE_ORDERS_COLLECTION).add(asdict(order))

# ------------------ 決策邏輯 ------------------

def decide_actions(results: Dict[str, Dict], portfolio: Dict[str, Position], cash: float) -> Tuple[List[Order], float]:
    orders = []
    estimated_cash = cash

    for coll, (target, stock_no) in RESULT_COLLECTIONS.items():
        res = results.get(coll)
        if not res:
            continue

        doc = res
        result_text = doc.get('result') or doc.get('analysis') or ''
        trend, mood, raw = parse_trend_and_score(result_text)
        ticker = target

        # 抓即時股價
        current_price = get_twse_price(stock_no)
        if current_price <= 0:
            print(f"[warning] {ticker} 無法抓到即時價格，略過")
            continue

        if trend in ['上漲', '微漲']:
            if trend == '上漲':
                amt = min(MAX_PER_TRADE, estimated_cash)
            else:  # 微漲
                amt = min(30_000, estimated_cash, MAX_PER_TRADE)

            if amt >= 1000:
                shares = amt / current_price
                orders.append(Order(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    ticker=ticker,
                    side='BUY',
                    amount=amt,
                    shares=shares,
                    exec_price=current_price,
                    status='PENDING',
                    reason=f"trend={trend}, mood={mood}",
                ))
                estimated_cash -= amt

        elif trend in ['微跌', '下跌']:
            pos = portfolio.get(ticker)
            if pos and pos.shares > 0:
                sell_ratio = 0.3 if trend == '微跌' else 0.6
                if pos.avg_price:
                    approx_proceeds = pos.avg_price * pos.shares * sell_ratio
                    amt = min(approx_proceeds, MAX_PER_TRADE)
                else:
                    amt = MAX_PER_TRADE

                if amt >= 1000:
                    orders.append(Order(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        ticker=ticker,
                        side='SELL',
                        amount=amt,
                        shares=None,
                        exec_price=None,
                        status='PENDING',
                        reason=f"trend={trend}, mood={mood}",
                    ))

    return orders, estimated_cash

# ------------------ 主流程 ------------------

def main():
    import os
    from datetime import datetime

    # --- 結果寫檔 ---
    def write_result_file(text: str):
        folder = "results"
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"{folder}/{ts}.txt"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(text)

        print(f"已輸出報告：{filename}")

    # --- 將資訊組合為字串 ---
    def build_daily_text(results, orders, est_cash):
        lines = []
        lines.append("================ 今日預測與投資狀況 ===============")

        for coll, (target, _) in RESULT_COLLECTIONS.items():
            r = results.get(coll)
            if not r:
                lines.append(f"今日 {target} 股：無資料")
                continue
            trend, mood, _ = parse_trend_and_score(r.get('result') or r.get('analysis') or '')
            trend_text = trend if trend else "無趨勢"
            lines.append(f"今日 {target} 股 預測為：{trend_text}")

        lines.append(f"\n本金剩餘：{est_cash:.0f} 元")

        if not orders:
            lines.append("本日有無投資：無")
            lines.append("原因：無符合條件之買賣訊號")
        else:
            lines.append("本日有無投資：有")
            lines.append("\n本日投資：")
            for o in orders:
                lines.append(f"- {o.side} {o.ticker} 金額 {o.amount:.0f} 股數 {o.shares:.4f} 成交價 {o.exec_price} (原因：{o.reason})")

        lines.append("\n停損點：avg_price × 0.9 (可自訂)")
        lines.append("====================================================")
        return "\n".join(lines)

    db = get_db()

    # 讀 portfolio
    portfolio = load_portfolio(db)

    # 讀現金
    cash = INITIAL_CAPITAL
    try:
        acc = db.collection(FIRESTORE_PORTFOLIO_COLLECTION).document('account').get()
        if acc.exists:
            d = acc.to_dict() or {}
            cash = float(d.get('cash', INITIAL_CAPITAL))
    except Exception as e:
        print(f"[warning] 讀現金失敗：{e} 使用初始金額。")

    # 抓各標的最新分析
    results = {}
    for coll in RESULT_COLLECTIONS.keys():
        doc = read_latest_result(db, coll)
        if doc:
            results[coll] = doc

    # 下單決策
    orders, est_cash = decide_actions(results, portfolio, cash)

    if orders:
        print(f"擬下單 {len(orders)} 筆，預估剩餘現金：{est_cash:.2f} 元")
        for o in orders:
            place_order(db, o)
            print(f"寫入 order: {o.side} {o.ticker} 金額 {o.amount:.0f} 股數 {o.shares:.4f} 成交價 {o.exec_price}")
    else:
        print("沒有符合條件的下單決策。")

    # 存 portfolio
    save_portfolio(db, portfolio, est_cash)

    # 寫出完整報告
    report = build_daily_text(results, orders, est_cash)
    write_result_file(report)

    print("Done. Orders 已寫入 Firestore。")

if __name__ == '__main__':
    main()
