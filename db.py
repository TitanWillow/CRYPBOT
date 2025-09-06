import sqlite3
import threading
import time
from typing import List, Dict, Any

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
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER,
                    symbol TEXT NOT NULL,
                    target REAL NOT NULL,
                    direction TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                """
            )
            c.execute("PRAGMA table_info(alerts)")
            cols = [row[1] for row in c.fetchall()]
            if "base_asset" not in cols:
                c.execute("ALTER TABLE alerts ADD COLUMN base_asset TEXT")
            conn.commit()

    def add_alert(self, chat_id: int, user_id: int, symbol: str, base_asset: str, target: float, direction: str) -> int:
        with self._lock, self._conn() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO alerts (chat_id, user_id, symbol, base_asset, target, direction, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chat_id, user_id, symbol.lower(), base_asset.upper(), float(target), direction, int(time.time())),
            )
            conn.commit()
            return c.lastrowid

    def remove_alert(self, alert_id: int, user_id: int) -> bool:
        with self._lock, self._conn() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM alerts WHERE id=? AND user_id=?", (alert_id, user_id))
            conn.commit()
            return c.rowcount > 0

    def list_alerts_for_chat(self, chat_id: int) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, symbol, base_asset, target, direction, created_at FROM alerts WHERE chat_id=? ORDER BY id DESC",
                (chat_id,),
            )
            rows = c.fetchall()
            return [
                {"id": r[0], "symbol": r[1], "base_asset": r[2], "target": r[3], "direction": r[4], "created_at": r[5]}
                for r in rows
            ]

    def get_all_alerts(self) -> List[Dict[str, Any]]:
        with self._lock, self._conn() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, chat_id, user_id, symbol, base_asset, target, direction, created_at FROM alerts ORDER BY id ASC"
            )
            rows = c.fetchall()
            return [
                {
                    "id": r[0],
                    "chat_id": r[1],
                    "user_id": r[2],
                    "symbol": r[3],
                    "base_asset": r[4],
                    "target": r[5],
                    "direction": r[6],
                    "created_at": r[7],
                }
                for r in rows
            ]
