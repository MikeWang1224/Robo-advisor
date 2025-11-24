# trading_bot_from_groq_results.py
# -*- coding: utf-8 -*-
"""
簡易投資機器人（基於你存在 Firestore 的 Groq_result 結果）
目的：
  - 從 Groq_result / Groq_result_Foxxcon / Groq_result_UMC 讀取最新分析結果
  - 根據分析結果決定今日（或隔日開盤）買賣
  - 初始本金 1,000,000（新台幣）
  - 單次建倉上限 50,000
  - 僅做多（長倉），遇偏空時賣出已持有部位

設計要點（簡單、可立即上線）：
  - 投資規則使用純硬規則（不呼叫 LLM）
  - 所有下單、持倉、資金資訊會寫回 Firestore（便於你在雲端檢視）
  - 下單時若找不到市價，將記為 pending order（等待價格填入/或後續由你補價）

使用前提：
  - 已在執行環境設定好 Google Application Credentials（能連到你的 Firestore）
  - 你之前的程式也使用 google.cloud.firestore.Client()，此腳本與它相容

如何使用：
  - python trading_bot_from_groq_results.py

注意：此程式**不會**直接呼叫券商 API。它會把決策（orders）寫入 Firestore，
券商執行可以由你另一段程式讀取這些 orders 並執行，或手動參考執行。

"""

import re
import json
from datetime import datetime, timezone
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass, asdict

from google.cloud import firestore

# ------------------ 設定 ------------------
INITIAL_CAPITAL = 1_000_000  # 新台幣
MAX_PER_TRADE = 50_000
FIRESTORE_PORTFOLIO_COLLECTION = "Trading_Portfolio"
FIRESTORE_ORDERS_COLLECTION = "Trading_Orders"

# 對應 Groq_result collection -> 標的名稱（簡稱）
RESULT_COLLECTIONS = {
    "Groq_result": "台積電",
    "Groq_result_Foxxcon": "鴻海",
    "Groq_result_UMC": "聯電",
}

# 當無法拿到價格時，order 將被標記為 pending

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
    side: str  # BUY / SELL
    amount: float  # 新台幣
    shares: Optional[float]
    exec_price: Optional[float]
    status: str  # PENDING / FILLED / CANCELLED
    reason: str

# ------------------ 工具函式 ------------------

def get_db():
    return firestore.Client()


def read_latest_result(db: firestore.Client, collection_name: str) -> Optional[Dict]:
    """讀取指定分析結果 collection 最新的一筆 doc（依 timestamp 欄排序或 doc id）"""
    try:
        coll = db.collection(collection_name)
        docs = coll.order_by("timestamp", direction=firestore.Query.DESCENDING).limit(1).stream()
        for d in docs:
            data = d.to_dict() or {}
            data['_doc_id'] = d.id
            return data
        # fallback: 取最後新增的 doc id（若沒有 timestamp 欄）
        docs2 = coll.stream()
        latest = None
        latest_time = None
        for d in docs2:
            try:
                # 嘗試 parse doc id 為時間 YYYYmmdd 或 ISO
                doc = d.to_dict() or {}
                ts = doc.get('timestamp')
                if ts:
                    t = datetime.fromisoformat(ts)
                    if latest_time is None or t > latest_time:
                        latest_time = t
                        latest = (d.id, doc)
            except Exception:
                continue
        if latest:
            docid, doc = latest
            doc['_doc_id'] = docid
            return doc
    except Exception as e:
        print(f"[warning] 讀取 {collection_name} 失敗：{e}")
    return None


def parse_trend_and_score(result_text: str) -> Tuple[Optional[str], Optional[int], str]:
    """
    從 result 欄位文字解析出：
      - trend: one of ['上漲','微漲','微跌','下跌'] 或 None
      - mood_score: int (情緒分數)，若無法解析則 None
      - 原始文字 return
    範例字串（你 code 所產出）：
      "明天台積電股價走勢：微漲 ↗️\n原因：...\n情緒分數：+3"
    """
    if not result_text:
        return None, None, ""
    txt = result_text
    trend = None
    # 優先找中文字（包含前綴）
    m = re.search(r"明天[^\n：]*股價走勢：?\s*([上微下漲跌]{2,3})", txt)
    if m:
        trend = m.group(1)
    else:
        # fallback: 搜尋關鍵詞
        if "上漲" in txt:
            trend = "上漲"
        elif "微漲" in txt:
            trend = "微漲"
        elif "微跌" in txt:
            trend = "微跌"
        elif "下跌" in txt:
            trend = "下跌"
    # 情緒分數
    mood = None
    m2 = re.search(r"情緒分數：\s*([+-]?\d+)", txt)
    if m2:
        try:
            mood = int(m2.group(1))
        except:
            mood = None
    return trend, mood, txt


def load_portfolio(db: firestore.Client) -> Dict[str, Position]:
    """從 Firestore 載入目前持倉（若無則建立初始資金紀錄）"""
    portfolio = {}
    try:
        doc = db.collection(FIRESTORE_PORTFOLIO_COLLECTION).document("account").get()
        if doc.exists:
            data = doc.to_dict() or {}
            # investments 儲存為 dict: ticker -> {shares, avg_price, cost}
            inv = data.get('investments', {})
            for t, v in inv.items():
                portfolio[t] = Position(ticker=t, shares=float(v.get('shares', 0.0)), avg_price=v.get('avg_price'), cost=float(v.get('cost', 0.0)))
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
    """根據每個標的的最新分析結果，決定要下哪些單。
    規則（示範，易於調整）：
      - 上漲 -> BUY 強烈（下滿額 MAX_PER_TRADE）
      - 微漲 -> BUY 中度（下 30,000）
      - 微跌 -> 若持有 -> SELL 30% 持股
      - 下跌 -> 若持有 -> SELL 60% 持股
      - 若情緒分數（mood）非常大（>=6 或 <= -6）可加強倉位/賣出
    返回 orders list 與剩餘現金預估（不包含未來 fill）
    """
    orders: List[Order] = []
    estimated_cash = cash

    for coll, target in RESULT_COLLECTIONS.items():
        res = results.get(coll)
        if not res:
            continue
        doc = res
        result_text = doc.get('result') or doc.get('analysis') or ''
        trend, mood, raw = parse_trend_and_score(result_text)
        ticker = target

        # decide
        if trend == '上漲':
            amt = min(MAX_PER_TRADE, estimated_cash)
            if amt >= 1000:  # 最小金額保護
                ord = Order(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    ticker=ticker,
                    side='BUY',
                    amount=amt,
                    shares=None,
                    exec_price=None,
                    status='PENDING',
                    reason=f"trend={trend}, mood={mood}",
                )
                orders.append(ord)
                estimated_cash -= amt
        elif trend == '微漲':
            amt = min(30_000, estimated_cash, MAX_PER_TRADE)
            if amt >= 1000:
                ord = Order(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    ticker=ticker,
                    side='BUY',
                    amount=amt,
                    shares=None,
                    exec_price=None,
                    status='PENDING',
                    reason=f"trend={trend}, mood={mood}",
                )
                orders.append(ord)
                estimated_cash -= amt
        elif trend == '微跌' or trend == '下跌':
            # 若持有，先賣出部分持股
            pos = portfolio.get(ticker)
            if pos and pos.shares > 0:
                sell_ratio = 0.3 if trend == '微跌' else 0.6
                # attempt to estimate proceeds using avg_price if no market price available
                if pos.avg_price:
                    approx_proceeds = pos.avg_price * pos.shares * sell_ratio
                    amt = min(approx_proceeds, MAX_PER_TRADE)
                else:
                    amt = min( MAX_PER_TRADE, estimated_cash + 0 )  # fallback
                if amt >= 1000:
                    ord = Order(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        ticker=ticker,
                        side='SELL',
                        amount=amt,
                        shares=None,
                        exec_price=None,
                        status='PENDING',
                        reason=f"trend={trend}, mood={mood}",
                    )
                    orders.append(ord)
                    # 不馬上更動現金，等執行回報
        else:
            # 若沒有趨勢或中性，略過
            continue

    return orders, estimated_cash

# ------------------ 主流程 ------------------

def main():
    import os
    from datetime import datetime

    # --- 新增：結果輸出到 result/*.txt ---
    def write_result_file(text: str):
        os.makedirs("result", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"result/{ts}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已輸出報告：{filename}")

    # --- 新增：將輸出內容整合成文字 ---
    def build_daily_text(results, orders, est_cash):
        lines = []
        lines.append("================ 今日預測與投資狀況 ===============")
        for coll, target in RESULT_COLLECTIONS.items():
            r = results.get(coll)
            if not r:
                lines.append(f"今日 {target} 股：無資料")
                continue
            trend, mood, _ = parse_trend_and_score(r.get('result') or r.get('analysis') or '')
            trend_text = trend if trend else "無趨勢"
            lines.append(f"今日 {target} 股 預測為：{trend_text}")

        lines.append(f"
本金剩餘：{est_cash:.0f} 元")

        if not orders:
            lines.append("本日有無投資：無")
            lines.append("原因：無符合條件之買賣訊號")
        else:
            lines.append("本日有無投資：有")
            lines.append("
本日投資：")
            for o in orders:
                lines.append(f"- {o.side} {o.ticker} 金額 {o.amount:.0f} (原因：{o.reason})")

        lines.append("
停損點：avg_price × 0.9 (可自訂)")
        lines.append("====================================================")
        return "
".join(lines)

    # --- 新增：決策輸出格式 ---
    def print_daily_report(results, orders, est_cash):
        print("================ 今日預測與投資狀況 ===============")
        for coll, target in RESULT_COLLECTIONS.items():
            r = results.get(coll)
            if not r:
                print(f"今日 {target} 股：無資料")
                continue
            trend, mood, _ = parse_trend_and_score(r.get('result') or r.get('analysis') or '')
            trend_text = trend if trend else "無趨勢"
            print(f"今日 {target} 股 預測為：{trend_text}")

        print(f"
本金剩餘：{est_cash:.0f} 元")

        if not orders:
            print("本日有無投資：無")
            print("原因：無符合條件之買賣訊號")
        else:
            print("本日有無投資：有")
            print("
本日投資：")
            for o in orders:
                print(f"- {o.side} {o.ticker} 金額 {o.amount:.0f} (原因：{o.reason})")

        print("
停損點：可根據 avg_price * 0.9（自訂）")
        print("====================================================
")

    db = get_db()

    # 讀取現有 portfolio（若無則初始化）
    portfolio = load_portfolio(db)
    # 讀取現金（若無則設為 INITIAL_CAPITAL）
    cash = INITIAL_CAPITAL
    try:
        acc = db.collection(FIRESTORE_PORTFOLIO_COLLECTION).document('account').get()
        if acc.exists:
            d = acc.to_dict() or {}
            cash = float(d.get('cash', INITIAL_CAPITAL))
    except Exception as e:
        print(f"[warning] 讀現金失敗：{e}，使用初始金額 {INITIAL_CAPITAL}")

    # 讀取各標的最新分析結果
    results = {}
    for coll in RESULT_COLLECTIONS.keys():
        doc = read_latest_result(db, coll)
        if doc:
            results[coll] = doc

    # 決策
    orders, est_cash = decide_actions(results, portfolio, cash)

    if not orders:
        print("沒有符合條件的下單決策。")
    else:
        print(f"擬下單 {len(orders)} 筆，預估剩餘現金：{est_cash:.2f} 元")
        # 寫入 Firestore orders
        for o in orders:
            place_order(db, o)
            print(f"寫入 order: {o.side} {o.ticker} 金額 {o.amount:.0f} ({o.reason})")

    # 儲存 portfolio（目前只是更新現金，不改變持倉，除非你另外執行 order fills）
    save_portfolio(db, portfolio, est_cash)

    print("Done. Orders 都已寫入 Firestore -> collection 'Trading_Orders'。\n你可以另外執行一支程式來對接券商並回寫執行結果（執行完後會更新持倉與現金）。")

if __name__ == '__main__':
    main()
