import os
import sqlite3
from datetime import datetime, timezone, date
import requests
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# CRYPTO BOT 500 v2 — PAPER TRADING ONLY
# No API keys. No real order execution.
API = "https://data-api.binance.vision"
DB = "paper_trading_v2.db"
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INTERVAL = "5m"

st.set_page_config(page_title="CRYPTO BOT 500 v2", layout="wide")
st.title("CRYPTO BOT 500 — versão 2.0")
st.caption("Simulador experimental. Não conecta à sua conta Binance e não envia ordens reais.")

with st.sidebar:
    st.header("Configurações")
    capital_brl = st.number_input("Capital virtual (R$)", min_value=100.0, value=500.0, step=50.0)
    fx = st.number_input("Câmbio estimado (R$/USDT)", min_value=1.0, value=5.70, step=0.05)
    refresh_seconds = st.selectbox("Atualização do painel", [30, 60, 120, 300], index=1)
    stop_pct = st.slider("Stop-loss (%)", 0.5, 5.0, 2.0, 0.25) / 100
    target_pct = st.slider("Alvo de lucro (%)", 1.0, 10.0, 4.0, 0.25) / 100
    allocation_pct = st.slider("Alocação máxima por ativo (%)", 10, 50, 25, 5) / 100
    daily_loss_pct = st.slider("Limite de perda diária realizada (%)", 0.5, 5.0, 1.5, 0.25) / 100
    max_loss_pct = st.slider("Limite de perda acumulada (%)", 2.0, 15.0, 8.0, 0.5) / 100
    fee_pct = st.number_input("Taxa estimada por lado (%)", min_value=0.0, max_value=1.0, value=0.10, step=0.01) / 100

capital_usdt = capital_brl / fx
fee_rate = fee_pct

def connect():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS wallet (
        symbol TEXT PRIMARY KEY, cash REAL NOT NULL, qty REAL NOT NULL DEFAULT 0,
        entry REAL NOT NULL DEFAULT 0, stop REAL NOT NULL DEFAULT 0,
        target REAL NOT NULL DEFAULT 0, last_candle INTEGER NOT NULL DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, symbol TEXT, side TEXT,
        price REAL, qty REAL, fee REAL, pnl REAL, note TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
    c.commit()
    return c

conn = connect()

def get_meta(key, default=None):
    r = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default

def set_meta(key, value):
    conn.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, str(value)))
    conn.commit()

if get_meta("initialized") is None:
    per_asset = capital_usdt / len(SYMBOLS)
    for symbol in SYMBOLS:
        conn.execute("INSERT OR REPLACE INTO wallet(symbol,cash,qty,entry,stop,target,last_candle) VALUES(?,?,0,0,0,0,0)",
                     (symbol, per_asset))
    set_meta("initial_capital_usdt", capital_usdt)
    set_meta("initialized", "yes")
    set_meta("halted", "no")
    conn.commit()

def get_wallet(symbol):
    return conn.execute("SELECT * FROM wallet WHERE symbol=?", (symbol,)).fetchone()

def save_wallet(symbol, cash, qty, entry, stop, target, candle):
    conn.execute("""UPDATE wallet SET cash=?,qty=?,entry=?,stop=?,target=?,last_candle=?
                    WHERE symbol=?""", (cash, qty, entry, stop, target, candle, symbol))
    conn.commit()

def trade(symbol, side, price, qty, fee, pnl, note):
    conn.execute("INSERT INTO trades(ts,symbol,side,price,qty,fee,pnl,note) VALUES(?,?,?,?,?,?,?,?)",
                 (datetime.now().astimezone().isoformat(timespec="seconds"),
                  symbol, side, price, qty, fee, pnl, note))
    conn.commit()

def fetch_candles(symbol):
    response = requests.get(
        f"{API}/api/v3/klines",
        params={"symbol": symbol, "interval": INTERVAL, "limit": 120},
        timeout=15,
        headers={"User-Agent": "crypto-bot-500-paper/2.0"}
    )
    response.raise_for_status()
    names = ["open_time","open","high","low","close","volume","close_time",
             "quote_volume","trades","taker_base","taker_quote","ignore"]
    df = pd.DataFrame(response.json(), columns=names)
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    df = df[pd.to_numeric(df["close_time"]) < now_ms].copy()
    df["sma20"] = df["close"].rolling(20).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    change = df["close"].diff()
    avg_gain = change.clip(lower=0).rolling(14).mean()
    avg_loss = (-change.clip(upper=0)).rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["rsi"] = 100 - (100 / (1 + rs))
    return df.dropna(subset=["sma20", "sma50", "rsi"])

def equity_value(prices):
    total = 0.0
    for symbol in SYMBOLS:
        w = get_wallet(symbol)
        total += float(w["cash"]) + float(w["qty"]) * prices.get(symbol, 0.0)
    return total

def realized_today():
    rows = conn.execute("SELECT pnl FROM trades WHERE side='VENDA' AND substr(ts,1,10)=?",
                        (date.today().isoformat(),)).fetchall()
    return sum(float(r["pnl"] or 0) for r in rows)

st_autorefresh(interval=refresh_seconds * 1000, key="auto_refresh")
market, errors = {}, {}
for symbol in SYMBOLS:
    try:
        market[symbol] = fetch_candles(symbol)
    except Exception as exc:
        errors[symbol] = str(exc)

if errors:
    st.error("Erro ao consultar dados públicos: " + " | ".join(f"{k}: {v}" for k, v in errors.items()))

if market:
    prices = {s: float(df.iloc[-1]["close"]) for s, df in market.items()}
    initial = float(get_meta("initial_capital_usdt", capital_usdt))
    equity_before = equity_value(prices)
    total_loss = max(0.0, (initial - equity_before) / initial)
    daily_loss = max(0.0, -realized_today() / initial)
    halted = get_meta("halted", "no") == "yes"

    if total_loss >= max_loss_pct or daily_loss >= daily_loss_pct:
        halted = True
        set_meta("halted", "yes")

    # Only one evaluation per fully closed 5-minute candle.
    if not halted:
        for symbol, df in market.items():
            row = df.iloc[-1]
            candle = int(row["close_time"])
            w = get_wallet(symbol)
            if candle <= int(w["last_candle"]):
                continue

            price = float(row["close"])
            sma20, sma50, rsi = float(row["sma20"]), float(row["sma50"]), float(row["rsi"])
            cash, qty = float(w["cash"]), float(w["qty"])
            entry, stop, target = float(w["entry"]), float(w["stop"]), float(w["target"])

            if qty > 0:
                reason = None
                if price <= stop:
                    reason = "Stop-loss atingido"
                elif price >= target:
                    reason = "Alvo de lucro atingido"
                elif sma20 < sma50:
                    reason = "Sinal de tendência contrário"
                if reason:
                    gross = qty * price
                    fee = gross * fee_rate
                    net = gross - fee
                    pnl = net - qty * entry
                    cash += net
                    trade(symbol, "VENDA", price, qty, fee, pnl, reason)
                    qty, entry, stop, target = 0.0, 0.0, 0.0, 0.0
            else:
                if sma20 > sma50 and 50 <= rsi <= 70:
                    budget = min(cash, initial * allocation_pct)
                    if budget > 5:
                        fee = budget * fee_rate
                        qty = (budget - fee) / price
                        cash -= budget
                        entry = price
                        stop = price * (1 - stop_pct)
                        target = price * (1 + target_pct)
                        trade(symbol, "COMPRA", price, qty, fee, 0.0,
                              "SMA20 > SMA50 e RSI entre 50 e 70")
            save_wallet(symbol, cash, qty, entry, stop, target, candle)

    equity = equity_value(prices)
    pnl = equity - initial
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Patrimônio virtual", f"R$ {equity * fx:,.2f}", f"R$ {pnl * fx:,.2f}")
    c2.metric("Capital inicial", f"R$ {initial * fx:,.2f}")
    c3.metric("Resultado", f"{pnl:+.4f} USDT")
    c4.metric("Perda sobre capital inicial", f"{total_loss * 100:.2f}%")

    if halted:
        st.error("CIRCUITO DE SEGURANÇA ATIVADO. Novas compras estão bloqueadas.")

    st.subheader("Mercado e sinais")
    for symbol, df in market.items():
        row = df.iloc[-1]
        w = get_wallet(symbol)
        st.markdown(f"**{symbol}**")
        a, b, c, d = st.columns(4)
        a.metric("Preço", f"${float(row['close']):,.2f}")
        b.metric("RSI (14)", f"{float(row['rsi']):.1f}")
        c.metric("Posição", "Aberta" if float(w["qty"]) > 0 else "Sem posição")
        d.metric("Caixa", f"{float(w['cash']):.4f} USDT")
        st.caption(f"SMA20: {float(row['sma20']):.2f} | SMA50: {float(row['sma50']):.2f}")
        chart = df.set_index(pd.to_datetime(df["close_time"], unit="ms"))[["close","sma20","sma50"]].tail(60)
        st.line_chart(chart)

    st.subheader("Carteira simulada")
    wallet_rows = []
    for symbol in SYMBOLS:
        w = get_wallet(symbol)
        price = prices.get(symbol, 0.0)
        wallet_rows.append({
            "Ativo": symbol,
            "Caixa (USDT)": round(float(w["cash"]), 4),
            "Quantidade": round(float(w["qty"]), 8),
            "Preço de entrada": round(float(w["entry"]), 2),
            "Valor da posição (USDT)": round(float(w["qty"]) * price, 4)
        })
    st.dataframe(pd.DataFrame(wallet_rows), use_container_width=True, hide_index=True)

    st.subheader("Histórico de operações")
    history = pd.read_sql_query(
        "SELECT ts, symbol, side, price, qty, fee, pnl, note FROM trades ORDER BY id DESC LIMIT 100",
        conn
    )
    if history.empty:
        st.info("Nenhuma operação simulada registrada ainda.")
    else:
        st.dataframe(history, use_container_width=True, hide_index=True)

st.caption(f"Painel atualizado a cada {refresh_seconds}s. A estratégia avalia candles de 5 minutos fechados.")
st.caption("A hospedagem gratuita não garante execução 24/7. SQLite local pode ser perdido em reinicializações. Simulação não reproduz perfeitamente slippage, liquidez ou taxas reais.")
st.caption("Estratégia experimental, sem garantia de lucro e sem recomendação de investimento.")

with st.expander("Reiniciar simulação (apaga o histórico local)"):
    st.warning("O reset apaga a carteira e o histórico deste ambiente.")
    if st.button("Confirmar reset"):
        conn.close()
        if os.path.exists(DB):
            os.remove(DB)
        st.rerun()
