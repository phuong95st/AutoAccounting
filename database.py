import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Any
from config import DB_PATH

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                type TEXT NOT NULL CHECK(type IN ('thu', 'chi')),
                amount INTEGER NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                payment_method TEXT DEFAULT 'cash' CHECK(payment_method IN ('cash', 'transfer')),
                source TEXT DEFAULT 'telegram',
                user_id INTEGER,
                notes TEXT
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trans_date ON transactions(date);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trans_type ON transactions(type);")
        conn.commit()

def add_transaction(
    tx_type: str,
    amount: int,
    category: str,
    description: str,
    payment_method: str = "cash",
    source: str = "telegram",
    user_id: Optional[int] = None,
    tx_date: Optional[str] = None,
    tx_time: Optional[str] = None,
    notes: Optional[str] = None
) -> int:
    now = datetime.now()
    d = tx_date or now.strftime("%Y-%m-%d")
    t = tx_time or now.strftime("%H:%M:%S")
    tx_type = tx_type.lower().strip()
    payment_method = "transfer" if "transfer" in payment_method.lower() or "ck" in payment_method.lower() else "cash"

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO transactions (date, time, type, amount, category, description, payment_method, source, user_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (d, t, tx_type, amount, category, description, payment_method, source, user_id, notes))
        conn.commit()
        return cursor.lastrowid

def delete_transaction(tx_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        conn.commit()
        return cursor.rowcount > 0

def get_transaction(tx_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_recent_transactions(limit: int = 10) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM transactions 
            ORDER BY date DESC, time DESC, id DESC 
            LIMIT ?
        """, (limit,))
        return [dict(r) for r in cursor.fetchall()]

def get_today_summary() -> Dict[str, Any]:
    today = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                type,
                payment_method,
                SUM(amount) as total,
                COUNT(id) as count
            FROM transactions
            WHERE date = ?
            GROUP BY type, payment_method
        """, (today,))
        rows = cursor.fetchall()

    summary = {
        "date": today,
        "total_thu": 0,
        "total_chi": 0,
        "thu_cash": 0,
        "thu_transfer": 0,
        "chi_cash": 0,
        "chi_transfer": 0,
        "balance": 0,
        "count": 0
    }

    for r in rows:
        t = r["type"]
        method = r["payment_method"]
        tot = r["total"] or 0
        cnt = r["count"] or 0
        summary["count"] += cnt

        if t == "thu":
            summary["total_thu"] += tot
            if method == "transfer":
                summary["thu_transfer"] += tot
            else:
                summary["thu_cash"] += tot
        elif t == "chi":
            summary["total_chi"] += tot
            if method == "transfer":
                summary["chi_transfer"] += tot
            else:
                summary["chi_cash"] += tot

    summary["balance"] = summary["total_thu"] - summary["total_chi"]
    return summary

def get_month_summary(year: int, month: int) -> Dict[str, Any]:
    month_prefix = f"{year:04d}-{month:02d}"
    with get_connection() as conn:
        cursor = conn.cursor()
        # Overall totals
        cursor.execute("""
            SELECT 
                type,
                payment_method,
                SUM(amount) as total,
                COUNT(id) as count
            FROM transactions
            WHERE date LIKE ?
            GROUP BY type, payment_method
        """, (f"{month_prefix}%",))
        totals = cursor.fetchall()

        # Breakdown by category
        cursor.execute("""
            SELECT 
                type,
                category,
                SUM(amount) as total,
                COUNT(id) as count
            FROM transactions
            WHERE date LIKE ?
            GROUP BY type, category
            ORDER BY total DESC
        """, (f"{month_prefix}%",))
        categories = cursor.fetchall()

    res = {
        "year": year,
        "month": month,
        "total_thu": 0,
        "total_chi": 0,
        "thu_cash": 0,
        "thu_transfer": 0,
        "chi_cash": 0,
        "chi_transfer": 0,
        "balance": 0,
        "categories_thu": [],
        "categories_chi": []
    }

    for r in totals:
        t = r["type"]
        method = r["payment_method"]
        tot = r["total"] or 0
        if t == "thu":
            res["total_thu"] += tot
            if method == "transfer":
                res["thu_transfer"] += tot
            else:
                res["thu_cash"] += tot
        elif t == "chi":
            res["total_chi"] += tot
            if method == "transfer":
                res["chi_transfer"] += tot
            else:
                res["chi_cash"] += tot

    res["balance"] = res["total_thu"] - res["total_chi"]

    for c in categories:
        item = {"category": c["category"], "total": c["total"], "count": c["count"]}
        if c["type"] == "thu":
            res["categories_thu"].append(item)
        else:
            res["categories_chi"].append(item)

    return res

def get_transactions_by_month(year: int, month: int) -> List[Dict[str, Any]]:
    month_prefix = f"{year:04d}-{month:02d}"
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM transactions
            WHERE date LIKE ?
            ORDER BY date ASC, time ASC, id ASC
        """, (f"{month_prefix}%",))
        return [dict(r) for r in cursor.fetchall()]

# Initialize tables when module is imported
init_db()
