import sqlite3
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

DB = "paper_trading.db"
API = "https://api.binance.com"

st.set_page_config(page_title="CRYPTO BOT 500", page_icon="₿", layout="wide")

def connect():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.execute("""CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, symbol TEXT, side TEXT,
        price REAL, qty REAL, quote_value REAL, pnl REAL, reason TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS state (
        symbol TEXT PRIMARY KEY, quote_balance REAL, qty REAL,
        entry_price REAL, stop_price REAL)""")
    c.commit()
    return c

def get_candles(symbol):
    r = requests.get(f"{API}/api/v3/klines",
        params={"symbol": symbol, "interval": "15m", "limit": 200}, timeout=15)
    r.raise_for_status()
    d = pd.DataFrame(r.json(), columns=[
        "open_time","open","high","low","close","volume","close_time",
        "quote_volume","trades","taker_base","taker_quote","ignore"])
    for col in ["open","high","low","close","volume"]:
        d[col] = pd.to_numeric(d[col])
    d["time"] = pd.to_datetime(d["open_time"], unit="ms", utc=True)
    d["sma20"] = d.close.rolling(20).mean()
    d["sma50"] = d.close.rolling(50).mean()
    delta = d.close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float("nan"))
    d["rsi"] = 100 - 100 / (1 + rs)
    return d.dropna().reset_index(drop=True)

def ensure(c, symbol, starting):
    if not c.execute("SELECT 1 FROM state WHERE symbol=?", (symbol,)).fetchone():
        c.execute("INSERT INTO state VALUES (?, ?, 0, 0, 0)", (symbol, starting))
        c.commit()

def state(c, symbol):
    return c.execute("SELECT quote_balance,qty,entry_price,stop_price FROM state WHERE symbol=?",
                     (symbol,)).fetchone()

def save_state(c, symbol, quote, qty, entry, stop):
    c.execute("UPDATE state SET quote_balance=?,qty=?,entry_price=?,stop_price=? WHERE symbol=?",
              (quote,qty,entry,stop,symbol))
    c.commit()

def log(c, symbol, side, price, qty, value, pnl, reason):
    c.execute("INSERT INTO trades(ts,symbol,side,price,qty,quote_value,pnl,reason) VALUES(?,?,?,?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(),symbol,side,price,qty,value,pnl,reason))
    c.commit()

st.title("CRYPTO BOT 500")
st.caption("Simulador experimental com dados públicos da Binance. Não envia ordens reais.")

with st.sidebar:
    st.header("Configurações")
    brl = st.number_input("Capital virtual (R$)", 100.0, 10000.0, 500.0, 50.0)
    fx = st.number_input("Cotação estimada USDT/BRL", 3.0, 10.0, 5.70, 0.01,
                         help="Ajuste conforme a cotação efetiva do USDT em reais.")
    allocation = st.slider("Alocação máxima por ativo (%)", 10, 50, 35) / 100
    stop_pct = st.slider("Stop de proteção (%)", 1.0, 8.0, 3.0, 0.5) / 100
    target_pct = st.slider("Alvo de saída (%)", 1.0, 15.0, 5.0, 0.5) / 100
    fee = st.number_input("Taxa estimada por lado (%)", 0.0, 1.0, 0.10, 0.01) / 100

capital_usdt = brl / fx
st.info(f"Capital virtual: R$ {brl:,.2f} ÷ R$ {fx:.2f}/USDT = **{capital_usdt:,.2f} USDT**. "
        "A cotação é uma estimativa editável, não uma conversão executada.")

st.warning("Estratégia experimental: compra se SMA20 > SMA50 e RSI entre 50 e 70; vende por stop, alvo ou sinal contrário. "
           "Isso não é recomendação de investimento nem garantia de resultado.")

c = connect()
symbols = ["BTCUSDT", "ETHUSDT"]
starting_each = capital_usdt / 2
cards = st.columns(2)
portfolio = 0.0
status_rows = []

for i, symbol in enumerate(symbols):
    with cards[i]:
        st.subheader(symbol.replace("USDT", "/USDT"))
        try:
            df = get_candles(symbol)
            last = df.iloc[-1]
            price = float(last.close)
            ensure(c, symbol, starting_each)
            quote, qty, entry, stop = map(float, state(c, symbol))
            up = last.sma20 > last.sma50 and 50 <= last.rsi <= 70
            down = last.sma20 < last.sma50 or last.rsi >= 75
            signal, reason = "AGUARDAR", "Nenhum sinal válido"

            if qty == 0 and up and quote > 10:
                spend = min(quote, capital_usdt * allocation)
                bought = spend * (1-fee) / price
                save_state(c, symbol, quote-spend, bought, price, price*(1-stop_pct))
                log(c, symbol, "COMPRA SIMULADA", price, bought, spend, 0,
                    "SMA20 acima da SMA50 e RSI entre 50 e 70")
                signal, reason = "COMPRA SIMULADA", "Tendência e momentum favoráveis"
                quote, qty, entry, stop = map(float, state(c, symbol))
            elif qty > 0 and (price <= stop or price >= entry*(1+target_pct) or down):
                gross = qty * price
                proceeds = gross * (1-fee)
                pnl = proceeds - qty*entry
                why = "Stop atingido" if price <= stop else (
                    "Alvo atingido" if price >= entry*(1+target_pct) else "Sinal contrário")
                save_state(c, symbol, quote+proceeds, 0, 0, 0)
                log(c, symbol, "VENDA SIMULADA", price, qty, gross, pnl, why)
                signal, reason = "VENDA SIMULADA", why
                quote, qty, entry, stop = map(float, state(c, symbol))

            equity = quote + qty*price
            portfolio += equity
            st.metric("Preço de referência", f"${price:,.2f}")
            st.metric("RSI (14)", f"{last.rsi:.1f}")
            st.metric("Patrimônio virtual", f"{equity:,.2f} USDT")
            st.write(f"**Sinal:** {signal}")
            st.caption(reason)
            st.line_chart(df.set_index("time")[["close","sma20","sma50"]].tail(80))
            status_rows.append({"Ativo":symbol, "Caixa (USDT)":quote, "Quantidade":qty,
                                "Preço de entrada":entry, "Stop":stop, "Patrimônio (USDT)":equity})
        except Exception as e:
            st.error(f"Falha ao consultar {symbol}: {e}")

st.divider()
st.subheader("Carteira simulada")
st.metric("Patrimônio total estimado", f"R$ {portfolio*fx:,.2f}",
          delta=f"{portfolio*fx-brl:,.2f} BRL vs. capital inicial")
if status_rows:
    st.dataframe(pd.DataFrame(status_rows), use_container_width=True, hide_index=True)
trades = pd.read_sql_query("SELECT * FROM trades ORDER BY id DESC", c)
st.subheader("Histórico de operações")
if trades.empty:
    st.write("Nenhuma operação simulada registrada ainda.")
else:
    st.dataframe(trades, use_container_width=True, hide_index=True)

st.caption("Atualize a página para consultar novos candles. Esta versão não executa ordens reais nem opera em segundo plano. "
           "O histórico fica no armazenamento local do ambiente e pode ser perdido em reinicializações da hospedagem.")
