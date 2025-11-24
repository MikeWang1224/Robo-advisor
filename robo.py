# -*- coding: utf-8 -*-

import os
import time
import json
import requests
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

# ===================== 基本設定 =====================
INITIAL_CAPITAL = 1000000
RESULTS_DIR = "results"
GITHUB_RESULTS_DIR = "./github_results"

os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(GITHUB_RESULTS_DIR, exist_ok=True)

# ===================== Firebase =====================
cred = credentials.Certificate("firebase_key.json")  # ←改成你的 key
firebase_admin.initialize_app(cred)
db = firestore.client()

# ===================== 抓 TWSE 股價（穩定版） =====================
def get_tw_price(stock_id):
    urls = [
        f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{stock_id}.tw",
        f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=otc_{stock_id}.tw"
    ]

    headers = {"User-Agent": "Mozilla/5.0"}

    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            data = r.json()

            if "msgArray" in data and len(data["msgArray"]) > 0:
                price = float(data["msgArray"][0]["z"])
                return price
        except:
            continue

    print(f"[⚠️] TWSE 抓價失敗：{stock_id}")
    return None

# ===================== 讀 Firestore 資料 =====================
def load_groq_signals():
    col = db.collection("Groq_Results")
    docs = col.stream()
    signals = []

    for d in docs:
        data = d.to_dict()
        signals.append(data)

    return signals

# ===================== 讀取帳戶狀態 =====================
def load_account():
    doc = db.collection("Trading_Account").document("ACCOUNT").get()
    if doc.exists:
        return doc.to_dict()["cash"]
    else:
        db.collection("Trading_Account").document("ACCOUNT").set({
            "cash": INITIAL_CAPITAL
        })
        return INITIAL_CAPITAL

def save_account(cash):
    db.collection("Trading_Account").document("ACCOUNT").update({
        "cash": cash
    })

# ===================== 持倉相關 =====================
def load_portfolio(stock_id):
    doc = db.collection("Trading_Portfolio").document(stock_id).get()
    if doc.exists:
        return doc.to_dict()
    return None

def save_portfolio(stock_id, shares, avg_price):
    db.collection("Trading_Portfolio").document(stock_id).set({
        "shares": shares,
        "avg_price": avg_price,
        "update_time": datetime.now()
    })

def delete_portfolio(stock_id):
    db.collection("Trading_Portfolio").document(stock_id).delete()

# ===================== 訂單紀錄 =====================
def record_order(data):
    db.collection("Trading_Orders").add(data)

# ===================== 下單物件 =====================
class Order:
    def __init__(self, ticker, price, shares):
        self.ticker = ticker
        self.exec_price = price
        self.shares = shares
        self.amount = price * shares

# ===================== 主程式 =====================
def main():
    cash = load_account()
    signals = load_groq_signals()
    orders = []
    sell_orders = []

    lines = []
    lines.append("==== 交易機器人報表 ====")
    lines.append(f"時間：{datetime.now()}")
    lines.append(f"初始現金：{cash:,.0f} 元")
    lines.append("")

    # ======== 先檢查持倉是否需要停利/停損 ========
    port_docs = db.collection("Trading_Portfolio").stream()
    for p in port_docs:
        p_data = p.to_dict()
        stock_id = p.id
        cur_price = get_tw_price(stock_id)

        if not cur_price:
            continue

        avg = p_data["avg_price"]
        shares = p_data["shares"]

        profit_ratio = (cur_price - avg) / avg

        if profit_ratio >= 0.08:  # 停利 8%
            sell_orders.append((stock_id, cur_price, shares, "停利"))
        elif profit_ratio <= -0.05:  # 停損 -5%
            sell_orders.append((stock_id, cur_price, shares, "停損"))

    # ======== 執行賣出 ========
    for s in sell_orders:
        stock_id, price, shares, reason = s
        amount = price * shares
        cash += amount

        delete_portfolio(stock_id)

        record_order({
            "type": "SELL",
            "ticker": stock_id,
            "price": price,
            "shares": shares,
            "amount": amount,
            "reason": reason,
            "time": datetime.now()
        })

        lines.append(f"【賣出】{stock_id}")
        lines.append(f"  原因：{reason}")
        lines.append(f"  價格：{price}")
        lines.append(f"  股數：{shares}")
        lines.append(f"  金額：{amount:,.0f}")
        lines.append("")

    # ======== 買入策略 ========
    for s in signals:
        if s.get("prediction") not in ["上漲", "微漲"]:
            continue

        stock_id = s.get("stock_id")
        price = get_tw_price(stock_id)

        if not price:
            lines.append(f"[跳過] {stock_id} 無法取得股價")
            continue

        budget = cash * 0.05
        shares = budget / price

        if shares <= 0:
            continue

        order = Order(stock_id, price, shares)
        orders.append(order)

        cash -= order.amount

        # 更新持倉
        hold = load_portfolio(stock_id)
        if hold:
            total_shares = hold["shares"] + shares
            new_avg = ((hold["shares"] * hold["avg_price"]) + order.amount) / total_shares
            save_portfolio(stock_id, total_shares, new_avg)
        else:
            save_portfolio(stock_id, shares, price)

        record_order({
            "type": "BUY",
            "ticker": stock_id,
            "price": price,
            "shares": shares,
            "amount": order.amount,
            "time": datetime.now()
        })

    # ======== 輸出買入紀錄 ========
    if orders:
        lines.append("【買入明細】")
        for o in orders:
            lines.append(f"股票：{o.ticker}")
            lines.append(f"  成交價：{o.exec_price}")
            lines.append(f"  股數：{o.shares:.2f}")
            lines.append(f"  總金額：{o.amount:,.0f}")
            lines.append("")
    else:
        lines.append("今日無買入交易")

    lines.append("")
    lines.append(f"剩餘現金：{cash:,.0f} 元")

    save_account(cash)

    # ======== 存檔 ========
    now = datetime.now().strftime("%Y%m%d_%H.%M.%S")
    local_path = os.path.join(RESULTS_DIR, f"{now}.txt")
    github_path = os.path.join(GITHUB_RESULTS_DIR, f"result_{datetime.now().strftime('%Y%m%d')}.txt")

    with open(local_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # ✅ GitHub 也輸出完整交易明細
    with open(github_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"✅ 已輸出本地：{local_path}")
    print(f"✅ 已輸出 GitHub 資料夾：{github_path}")
    print("✅ 執行完成")

# =====================
if __name__ == "__main__":
    main()
