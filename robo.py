# trading_bot_full.py
# -*- coding: utf-8 -*-
"""
完整模擬投資機器人（基於 Firestore 的 Groq_result + 即時股價）
功能：
- 從 Firestore 抓最新 Groq 結果
- 抓取即時股價（TWSE）
- 買入：當訊號為 上漲 / 微漲 -> 下買單（每筆最多 MAX_PER_TRADE）
- 賣出：當訊號為 下跌 / 微跌 -> 對應持股全部賣出
- 也支援「停利 / 停損」條件
- 將下單記錄寫入 Firestore (Trading_Orders)，並更新持倉 (Trading_Portfolio) 與帳戶現金 (Trading_Account)
- 產生可讀報告並輸出到本地 results/ 與 GitHub 資料夾

使用說明：
1. 在執行前，確保已設定 GOOGLE_APPLICATION_CREDENTIALS 指向你的 Firebase service account json。
2. 安裝相依套件：google-cloud-firestore, requests
3. 執行：python trading_bot_full.py

注意：此為模擬下單（程式直接把狀態寫入 Firestore），非連接真實券商下單。
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
PROFIT_TARGET = 0.05   # 若股價 >= avg_price * (1 + PROFIT_TARGET) -> 可賣出
STOP_LOSS = 0.03       # 若股價 <= avg_price * (1 - STOP_LOSS)  -> 可賣出

FIRESTORE_PORTFOLIO_COLLECTION = "Trading_Portfolio"
FIRESTORE_ORDERS_COLLECTION = "Trading_Orders"
FIRESTORE_ACCOUNT_COLLECTION = "Trading_Account"
FIRESTORE_ACCOUNT_DOC = "ACCOUNT"

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

# ------------------ Firestore / 資訊函式 ------------------

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


def ensure_account(db: firestore.Client):
    doc_ref = db.collection(FIRESTORE_ACCOUNT_COLLECTION).document(FIRESTORE_ACCOUNT_DOC)
    doc = doc_ref.get()
    if not doc.exists:
        doc_ref.set({"cash": INITIAL_CAPITAL, "updated_at": firestore.SERVER_TIMESTAMP})


def get_account_cash(db: firestore.Client) -> float:
    doc = db.collection(FIRESTORE_ACCOUNT_COLLECTION).document(FIRESTORE_ACCOUNT_DOC).get()
    if doc.exists:
        data = doc.to_dict() or {}
        return float(data.get("cash", 0.0))
    return 0.0


def set_account_cash(db: firestore.Client, new_cash: float):
    db.collection(FIRESTORE_ACCOUNT_COLLECTION).document(FIRESTORE_ACCOUNT_DOC).set({"cash": new_cash, "updated_at": firestore.SERVER_TIMESTAMP})


def get_portfolio(db: firestore.Client) -> Dict[str, Position]:
    res = {}
    coll = db.collection(FIRESTORE_PORTFOLIO_COLLECTION).stream()
    for d in coll:
        data = d.to_dict() or {}
        ticker = data.get("ticker") or d.id
        res[ticker] = Position(
            ticker=ticker,
            shares=float(data.get("shares", 0.0)),
            avg_price=float(data.get("avg_price", 0.0)) if data.get("avg_price") is not None else None,
            cost=float(data.get("cost", 0.0))
        )
    return res


def upsert_portfolio_position(db: firestore.Client, pos: Position):
    doc_ref = db.collection(FIRESTORE_PORTFOLIO_COLLECTION).document(pos.ticker)
    doc_ref.set({"ticker": pos.ticker, "shares": pos.shares, "avg_price": pos.avg_price, "cost": pos.cost, "updated_at": firestore.SERVER_TIMESTAMP})


def delete_portfolio_position(db: firestore.Client, ticker: str):
    db.collection(FIRESTORE_PORTFOLIO_COLLECTION).document(ticker).delete()

# ------------------ 下單 / 執行（模擬） ------------------

def record_order(db: firestore.Client, order: Order):
    db.collection(FIRESTORE_ORDERS_COLLECTION).add(asdict(order))


def execute_buy(db: firestore.Client, ticker: str, price: float, amount: float) -> Order:
    # 計算可買股數
    shares = round(amount / price, 4)
    real_amount = shares * price

    # 取現金
    cash = get_account_cash(db)
    if real_amount > cash:
        # 不足以買
        order = Order(timestamp=datetime.now(timezone.utc).isoformat(), ticker=ticker, side="BUY", amount=real_amount, shares=shares, exec_price=price, status="FAILED", reason="Insufficient cash")
        record_order(db, order)
        return order

    # 扣現金、更新現金
    new_cash = cash - real_amount
    set_account_cash(db, new_cash)

    # 更新持倉（加權平均價格）
    portfolio = get_portfolio(db)
    if ticker in portfolio:
        p = portfolio[ticker]
        total_cost = p.cost + real_amount
        total_shares = p.shares + shares
        avg_price = total_cost / total_shares if total_shares > 0 else price
        new_pos = Position(ticker=ticker, shares=total_shares, avg_price=avg_price, cost=total_cost)
    else:
        new_pos = Position(ticker=ticker, shares=shares, avg_price=price, cost=real_amount)

    upsert_portfolio_position(db, new_pos)

    order = Order(timestamp=datetime.now(timezone.utc).isoformat(), ticker=ticker, side="BUY", amount=real_amount, shares=shares, exec_price=price, status="EXECUTED", reason="signal BUY")
    record_order(db, order)
    return order


def execute_sell(db: firestore.Client, ticker: str, price: float, shares_to_sell: float) -> Order:
    portfolio = get_portfolio(db)
    if ticker not in portfolio:
        order = Order(timestamp=datetime.now(timezone.utc).isoformat(), ticker=ticker, side="SELL", amount=0.0, shares=0.0, exec_price=price, status="FAILED", reason="No position")
        record_order(db, order)
        return order

    pos = portfolio[ticker]
    if shares_to_sell <= 0 or pos.shares <= 0:
        order = Order(timestamp=datetime.now(timezone.utc).isoformat(), ticker=ticker, side="SELL", amount=0.0, shares=0.0, exec_price=price, status="FAILED", reason="Zero shares")
        record_order(db, order)
        return order

    shares = min(pos.shares, round(shares_to_sell, 4))
    real_amount = shares * price

    # 增加現金
    cash = get_account_cash(db)
    new_cash = cash + real_amount
    set_account_cash(db, new_cash)

    # 更新持倉
    remaining_shares = pos.shares - shares
    if remaining_shares <= 0:
        delete_portfolio_position(db, ticker)
    else:
        # 保持原始 avg_price，cost 依剩餘股數調整
        remaining_cost = pos.avg_price * remaining_shares
        new_pos = Position(ticker=ticker, shares=remaining_shares, avg_price=pos.avg_price, cost=remaining_cost)
        upsert_portfolio_position(db, new_pos)

    order = Order(timestamp=datetime.now(timezone.utc).isoformat(), ticker=ticker, side="SELL", amount=real_amount, shares=shares, exec_price=price, status="EXECUTED", reason="signal SELL or target/stoploss")
    record_order(db, order)
    return order

# ------------------ 決策邏輯 ------------------

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


def decide_and_execute(db: firestore.Client) -> Dict:
    # 確保帳戶存在
    ensure_account(db)

    # 讀取帳戶現金與持倉
    cash = get_account_cash(db)
    portfolio = get_portfolio(db)

    results = {}
    for coll in RESULT_COLLECTIONS.keys():
        doc = read_latest_result(db, coll)
        if doc:
            results[coll] = doc

    executed_orders = []

    # 先檢查每個持倉是否觸及停利/停損
    prices_cache = {}
    for ticker, pos in portfolio.items():
        # 找對應股票代號（從 RESULT_COLLECTIONS 反查）
        stock_no = None
        for v in RESULT_COLLECTIONS.values():
            if v[0] == ticker:
                stock_no = v[1]
                break
        if not stock_no:
            continue
        price = get_twse_price(stock_no)
        prices_cache[ticker] = price
        if price <= 0:
            continue
        # 停利
        if pos.avg_price and price >= pos.avg_price * (1 + PROFIT_TARGET):
            o = execute_sell(db, ticker, price, pos.shares)
            executed_orders.append(o)
            continue
        # 停損
        if pos.avg_price and price <= pos.avg_price * (1 - STOP_LOSS):
            o = execute_sell(db, ticker, price, pos.shares)
            executed_orders.append(o)

    # 對每個 signal 決定買/賣
    for coll, (target, stock_no) in RESULT_COLLECTIONS.items():
        res = results.get(coll)
        if not res:
            continue
        text = res.get("result") or res.get("analysis") or ""
        trend, mood, _ = parse_trend_and_score(text)
        price = prices_cache.get(target) or get_twse_price(stock_no)
        prices_cache[target] = price
        if price <= 0:
            continue

        # 如果 signal 是上漲，買入
        if trend in ["上漲", "微漲"]:
            amt = min(MAX_PER_TRADE, get_account_cash(db))
            if amt >= 1000:
                o = execute_buy(db, target, price, amt)
                executed_orders.append(o)

        # 如果 signal 是下跌，全部賣出（若有持倉）
        if trend in ["下跌", "微跌"]:
            port = get_portfolio(db)
            if target in port and port[target].shares > 0:
                o = execute_sell(db, target, price, port[target].shares)
                executed_orders.append(o)

    # 計算報表資訊
    final_cash = get_account_cash(db)
    final_portfolio = get_portfolio(db)

    # 計算持倉市值與未實現損益
    holdings_report = []
    total_holdings_value = 0.0
    for ticker, pos in final_portfolio.items():
        # find price
        price = prices_cache.get(ticker)
        if not price:
            # try to find stock_no
            for v in RESULT_COLLECTIONS.values():
                if v[0] == ticker:
                    price = get_twse_price(v[1])
                    prices_cache[ticker] = price
                    break
        market_value = pos.shares * (price or 0)
        unreal_pl = market_value - pos.cost
        holdings_report.append({
            "ticker": ticker,
            "shares": pos.shares,
            "avg_price": pos.avg_price,
            "market_price": price,
            "market_value": market_value,
            "cost": pos.cost,
            "unrealized_pl": unreal_pl,
        })
        total_holdings_value += market_value

    account_summary = {
        "cash": final_cash,
        "holdings_value": total_holdings_value,
        "total_account_value": final_cash + total_holdings_value,
        "orders_executed": [asdict(o) for o in executed_orders]
    }

    return {"account_summary": account_summary, "holdings": holdings_report}

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

    result = decide_and_execute(db)

    # 產生文字報表
    s = result["account_summary"]
    holdings = result["holdings"]

    lines = []
    lines.append("==== 今日完整交易報告 ====")
    lines.append(f"時間：{datetime.now(timezone.utc).isoformat()}")
    lines.append(f"初始本金：{INITIAL_CAPITAL:,} 元")
    lines.append("")

    lines.append("【帳戶摘要】")
    lines.append(f"  現金：{s['cash']:,.0f} 元")
    lines.append(f"  持倉市值：{s['holdings_value']:,.0f} 元")
    lines.append(f"  總帳戶價值：{s['total_account_value']:,.0f} 元")
    lines.append("")

    if holdings:
        lines.append("【持倉明細】")
        for h in holdings:
            lines.append(f"  股票：{h['ticker']}")
            lines.append(f"    股數：{h['shares']}")
            lines.append(f"    成本均價：{h['avg_price']}")
            lines.append(f"    市價：{h['market_price']}")
            lines.append(f"    市值：{h['market_value']:,.0f} 元")
            lines.append(f"    未實現損益：{h['unrealized_pl']:,.0f} 元")
            lines.append("")
    else:
        lines.append("目前無持倉")

    if s['orders_executed']:
        lines.append("【執行的訂單】")
        for o in s['orders_executed']:
            lines.append(f"  {o['timestamp']} - {o['side']} {o['ticker']}  股數={o['shares']}  價格={o['exec_price']}  金額={o['amount']:,.0f}  狀態={o['status']}  原因={o['reason']}")
    else:
        lines.append("無執行的訂單")

    report_text = "\n".join(lines)

    write_report_to_folders(report_text)

    print("✅ 執行完成")

if __name__ == "__main__":
    main()
