import os
import time
import json
import logging
import threading
from typing import List, Dict, Optional
import sqlite3
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN not set")
BINANCE_API_BASE = os.getenv("BINANCE_API_BASE", "https://api.binance.com")
EXCHANGE_INFO = BINANCE_API_BASE + "/api/v3/exchangeInfo"
TICKER_ALL = BINANCE_API_BASE + "/api/v3/ticker/price"
TG_API_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
SYMBOL_TTL = 60 * 5
PRICE_REFRESH_SECONDS = int(os.getenv("PRICE_REFRESH_SECONDS", "5"))
SYMBOL_REFRESH_SECONDS = int(os.getenv("SYMBOL_REFRESH_SECONDS", "300"))
CHECK_INTERVAL = PRICE_REFRESH_SECONDS
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("crybot")
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=(429,500,502,503,504))
session.mount("https://", HTTPAdapter(max_retries=retries))

class AlertsDB:
    def __init__(self, path: str = "data.db"):
        self.path = path
        self._lock = threading.Lock()
        self._init_db()
    def _conn(self):
        return sqlite3.connect(self.path, check_same_thread=False)
    def _init_db(self):
        with self._lock, self._conn() as conn:
            c = conn.cursor()
            c.execute("CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, user_id INTEGER, symbol TEXT NOT NULL, base_asset TEXT NOT NULL, target REAL NOT NULL, direction TEXT NOT NULL, created_at INTEGER NOT NULL)")
            conn.commit()
    def add_alert(self, chat_id: int, user_id: int, symbol: str, base_asset: str, target: float, direction: str) -> int:
        with self._lock, self._conn() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO alerts (chat_id,user_id,symbol,base_asset,target,direction,created_at) VALUES (?,?,?,?,?,?,?)",(chat_id,user_id,symbol.lower(),base_asset.upper(),float(target),direction,int(time.time())))
            conn.commit()
            return c.lastrowid
    def remove_alert(self, alert_id: int, user_id: int) -> bool:
        with self._lock, self._conn() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM alerts WHERE id=? AND user_id=?",(alert_id,user_id))
            conn.commit()
            return c.rowcount > 0
    def list_alerts_for_chat(self, chat_id: int) -> List[Dict]:
        with self._lock, self._conn() as conn:
            c = conn.cursor()
            c.execute("SELECT id,symbol,base_asset,target,direction,created_at FROM alerts WHERE chat_id=? ORDER BY id DESC",(chat_id,))
            rows = c.fetchall()
            return [{"id":r[0],"symbol":r[1],"base_asset":r[2],"target":r[3],"direction":r[4],"created_at":r[5]} for r in rows]
    def get_all_alerts(self) -> List[Dict]:
        with self._lock, self._conn() as conn:
            c = conn.cursor()
            c.execute("SELECT id,chat_id,user_id,symbol,base_asset,target,direction,created_at FROM alerts ORDER BY id ASC")
            rows = c.fetchall()
            return [{"id":r[0],"chat_id":r[1],"user_id":r[2],"symbol":r[3],"base_asset":r[4],"target":r[5],"direction":r[6],"created_at":r[7]} for r in rows]

db = AlertsDB("data.db")
_symbol_map: Dict[str, str] = {}
_symbol_map_ts = 0
_price_cache: Dict[str, float] = {}
_price_cache_ts = 0
_symbol_lock = threading.Lock()
_price_lock = threading.Lock()

def refresh_symbol_map():
    global _symbol_map, _symbol_map_ts
    try:
        now = time.time()
        if _symbol_map and (now - _symbol_map_ts) < SYMBOL_TTL:
            return
        r = session.get(EXCHANGE_INFO, timeout=15)
        r.raise_for_status()
        data = r.json()
        mapping: Dict[str,str] = {}
        for s in data.get("symbols", []):
            if s.get("status") != "TRADING":
                continue
            if s.get("quoteAsset") != "USDT":
                continue
            base = s.get("baseAsset")
            pair = s.get("symbol")
            if base and pair:
                mapping[base.upper()] = pair
        with _symbol_lock:
            _symbol_map = mapping
            _symbol_map_ts = now
    except Exception:
        logger.exception("refresh_symbol_map failed")

def refresh_prices():
    global _price_cache, _price_cache_ts
    try:
        r = session.get(TICKER_ALL, timeout=20)
        r.raise_for_status()
        arr = r.json()
        prices: Dict[str,float] = {}
        for e in arr:
            sym = e.get("symbol","")
            if sym.endswith("USDT"):
                base = sym[:-4]
                try:
                    prices[base.upper()] = float(e.get("price"))
                except:
                    continue
        with _price_lock:
            _price_cache = prices
            _price_cache_ts = time.time()
    except Exception:
        logger.exception("refresh_prices failed")

def get_price_for_base(base: str) -> Optional[float]:
    baseu = base.upper()
    with _price_lock:
        if _price_cache and (time.time() - _price_cache_ts) <= PRICE_REFRESH_SECONDS:
            return _price_cache.get(baseu)
    refresh_prices()
    with _price_lock:
        return _price_cache.get(baseu)

def send_telegram_http(chat_id: int, text: str):
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        resp = session.post(TG_API_URL, json=payload, timeout=10)
        resp.raise_for_status()
    except Exception:
        logger.exception("send_telegram_http failed")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "/price <symbol> — get USD price for base coin (BTC or bitcoin works)\n/alert <symbol> <target> — set alert; prefix '<' for below e.g. /alert BTC <30000\n/alerts — list your alerts\n/removealert <id> — remove your alert\n/help — this help"
    await update.message.reply_text(text)

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /price <symbol>")
        return
    user_in = context.args[0].strip()
    refresh_symbol_map()
    base = user_in.upper() if user_in.upper() in _symbol_map else user_in.lower()
    if base.upper() in _symbol_map:
        price = get_price_for_base(base)
    else:
        price = get_price_for_base(user_in)
    if price is None:
        await update.message.reply_text("Price not available")
    else:
        await update.message.reply_text(f"{user_in.upper()} = ${price:,.8f}" if price < 1 else f"{user_in.upper()} = ${price:,.2f}")

async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /alert <symbol> <target>")
        return
    user_in = context.args[0].strip()
    raw = context.args[1].strip()
    direction = "above"
    if raw.startswith("<"):
        direction = "below"
        raw = raw[1:]
    try:
        target = float(raw)
    except:
        await update.message.reply_text("Invalid target")
        return
    refresh_symbol_map()
    base = user_in.upper() if user_in.upper() in _symbol_map else user_in.lower()
    base_asset = base.upper()
    if base_asset not in _symbol_map:
        await update.message.reply_text("Unknown or unsupported symbol on Binance")
        return
    aid = db.add_alert(update.effective_chat.id, update.effective_user.id, user_in.lower(), base_asset, target, direction)
    await update.message.reply_text(f"Alert #{aid} set: {user_in.upper()} {'<' if direction=='below' else '>'} {target}")

async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.list_alerts_for_chat(update.effective_chat.id)
    if not rows:
        await update.message.reply_text("No active alerts")
        return
    lines = [f"#{r['id']} {r['symbol'].upper()} ({r['base_asset']}) {'<' if r['direction']=='below' else '>'} {r['target']}" for r in rows]
    await update.message.reply_text("\n".join(lines))

async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /removealert <id>")
        return
    try:
        aid = int(context.args[0])
    except:
        await update.message.reply_text("Invalid ID")
        return
    user_id = update.effective_user.id
    ok = db.remove_alert(aid, user_id)
    if ok:
        await update.message.reply_text(f"Removed alert #{aid}")
    else:
        await update.message.reply_text("Alert not found or you are not the owner")

def check_loop_sync():
    while True:
        try:
            refresh_symbol_map()
            refresh_prices()
            alerts_all = db.get_all_alerts()
            if alerts_all:
                by_base: Dict[str, List[Dict]] = {}
                for a in alerts_all:
                    by_base.setdefault(a["base_asset"].upper(), []).append(a)
                with _price_lock:
                    prices_snapshot = dict(_price_cache)
                triggered = []
                for base, lst in by_base.items():
                    price = prices_snapshot.get(base)
                    if price is None:
                        continue
                    for a in lst:
                        if a["direction"] == "above" and price >= a["target"]:
                            triggered.append((a, price))
                        elif a["direction"] == "below" and price <= a["target"]:
                            triggered.append((a, price))
                for a, price in triggered:
                    msg = f"Alert #{a['id']}: *{a['symbol'].upper()}* ({a['base_asset']}) is ${price:,.8f} — target {a['target']} ({a['direction']})"
                    send_telegram_http(a["chat_id"], msg)
                    db.remove_alert(a["id"], a["user_id"])
        except Exception:
            logger.exception("check_loop_sync error")
        time.sleep(CHECK_INTERVAL)

def main():
    checker = threading.Thread(target=check_loop_sync, daemon=True)
    checker.start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("alert", cmd_alert))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("removealert", cmd_remove))
    app.run_polling()

if __name__ == "__main__":
    main()
