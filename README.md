# CRYPBOT

CRYPBOT is a Telegram bot that provides **real-time crypto prices** and lets users set price alerts using the **Binance Public API**.  
It stores alerts in a local SQLite database and runs 24/7 as a background worker.

---

## ✨ Features
- `/price <symbol>` — Get current USD price (e.g. `/price BTC`, `/price ETH`).
- `/alert <symbol> <target>` — Set price alerts.  
  - Example: `/alert BTC 60000` → alert when price ≥ 60000  
  - Example: `/alert BTC <30000` → alert when price ≤ 30000
- `/alerts` — List your active alerts.
- `/removealert <id>` — Remove one of your alerts.
- `/help` — Show usage instructions.

---

## 🛠 Tech Stack
- Python 3.10+
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- SQLite (`data.db`)
- Binance Public API (`/api/v3/exchangeInfo`, `/api/v3/ticker/price`)

---

## 🚀 Local Setup

Clone the repo and install dependencies:

```bash
git clone https://github.com/TitanWillow/CRYPBOT.git
cd CRYPBOT

python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```
---

## Create a .env file:

cp .env.example .env

---

## Run the bot locally:

python bot.py
