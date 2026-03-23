import sqlite3
import json
from datetime import datetime
from typing import Optional

DB_PATH = "stock_bot.db"

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            joined_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            symbol      TEXT NOT NULL COLLATE NOCASE,
            added_at    TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, symbol)
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            symbol      TEXT NOT NULL COLLATE NOCASE,
            target_price REAL NOT NULL,
            direction   TEXT NOT NULL CHECK(direction IN ('above','below')),
            active      INTEGER DEFAULT 1,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS portfolio (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            symbol      TEXT NOT NULL COLLATE NOCASE,
            shares      REAL NOT NULL,
            buy_price   REAL NOT NULL,
            added_at    TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, symbol)
        );
    """)
    conn.commit()
    conn.close()

# ── Users ──────────────────────────────────────────────────────────────────────

def upsert_user(user_id: int, username: str, first_name: str):
    conn = get_connection()
    conn.execute("""
        INSERT INTO users (user_id, username, first_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name
    """, (user_id, username, first_name))
    conn.commit()
    conn.close()

# ── Watchlist ──────────────────────────────────────────────────────────────────

def add_to_watchlist(user_id: int, symbol: str) -> bool:
    try:
        conn = get_connection()
        conn.execute("INSERT INTO watchlist (user_id, symbol) VALUES (?, ?)", (user_id, symbol.upper()))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False

def remove_from_watchlist(user_id: int, symbol: str) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM watchlist WHERE user_id=? AND symbol=?", (user_id, symbol.upper()))
    conn.commit()
    conn.close()
    return cur.rowcount > 0

def get_watchlist(user_id: int) -> list[str]:
    conn = get_connection()
    rows = conn.execute("SELECT symbol FROM watchlist WHERE user_id=? ORDER BY symbol", (user_id,)).fetchall()
    conn.close()
    return [r["symbol"] for r in rows]

# ── Alerts ─────────────────────────────────────────────────────────────────────

def add_alert(user_id: int, symbol: str, target_price: float, direction: str) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO alerts (user_id, symbol, target_price, direction) VALUES (?,?,?,?)",
        (user_id, symbol.upper(), target_price, direction)
    )
    conn.commit()
    alert_id = cur.lastrowid
    conn.close()
    return alert_id

def get_user_alerts(user_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM alerts WHERE user_id=? AND active=1 ORDER BY symbol",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_alert(alert_id: int, user_id: int) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM alerts WHERE id=? AND user_id=?", (alert_id, user_id))
    conn.commit()
    conn.close()
    return cur.rowcount > 0

def get_all_active_alerts() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM alerts WHERE active=1").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def deactivate_alert(alert_id: int):
    conn = get_connection()
    conn.execute("UPDATE alerts SET active=0 WHERE id=?", (alert_id,))
    conn.commit()
    conn.close()

# ── Portfolio ──────────────────────────────────────────────────────────────────

def add_to_portfolio(user_id: int, symbol: str, shares: float, buy_price: float) -> bool:
    try:
        conn = get_connection()
        conn.execute("""
            INSERT INTO portfolio (user_id, symbol, shares, buy_price)
            VALUES (?,?,?,?)
            ON CONFLICT(user_id, symbol) DO UPDATE SET
                shares = shares + excluded.shares,
                buy_price = ((buy_price * shares) + (excluded.buy_price * excluded.shares))
                            / (shares + excluded.shares)
        """, (user_id, symbol.upper(), shares, buy_price))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False

def remove_from_portfolio(user_id: int, symbol: str) -> bool:
    conn = get_connection()
    cur = conn.execute("DELETE FROM portfolio WHERE user_id=? AND symbol=?", (user_id, symbol.upper()))
    conn.commit()
    conn.close()
    return cur.rowcount > 0

def get_portfolio(user_id: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM portfolio WHERE user_id=? ORDER BY symbol", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
