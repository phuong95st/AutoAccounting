"""
Google Sheets Database Adapter
Dữ liệu được lưu trữ và truy vấn tập trung 100% trên Google Sheets trực tuyến.
Hoàn toàn không sử dụng SQLite hay lưu trữ file cục bộ trên máy.
"""

import json
import re
import urllib.request
import urllib.parse
import urllib.error
import ssl
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import config

logger = config.logging if hasattr(config, 'logging') else None
ssl_ctx = ssl.create_default_context()

def _call_sheets_api(payload: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """Helper to send POST or GET requests to Google Apps Script Webhook."""
    webhook_url = config.GOOGLE_SHEETS_WEBHOOK_URL
    if not webhook_url:
        print("⚠️ Chưa cấu hình GOOGLE_SHEETS_WEBHOOK_URL trong .env")
        return None

    try:
        if payload is not None:
            # POST Request
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json"}
            )
        else:
            # GET Request
            query = urllib.parse.urlencode(params or {})
            full_url = f"{webhook_url}?{query}" if query else webhook_url
            req = urllib.request.Request(full_url)

        with urllib.request.urlopen(req, timeout=12, context=ssl_ctx) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except Exception as e:
        print(f"Lỗi kết nối Google Sheets: {e}")
        return None

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
    """Thêm một giao dịch vào Google Sheets."""
    now = datetime.now()
    d = tx_date or now.strftime("%Y-%m-%d")
    t = tx_time or now.strftime("%H:%M:%S")
    p_method = "transfer" if any(w in payment_method.lower() for w in ["ck", "transfer", "khoản"]) else "cash"

    item = {
        "date": d,
        "time": t,
        "type": tx_type.lower().strip(),
        "amount": amount,
        "category": category,
        "description": description,
        "payment_method": p_method,
        "source": source
    }

    res = _call_sheets_api(payload={"action": "add", "data": item})
    if res and res.get("status") == "success":
        return res.get("id", int(datetime.now().timestamp()))
    return int(datetime.now().timestamp())

def add_batch_transactions(items: List[Dict[str, Any]]) -> int:
    """Thêm nhiều giao dịch cùng lúc (từ sao kê ngân hàng) vào Google Sheets."""
    if not items:
        return 0
    res = _call_sheets_api(payload={"action": "add", "data": items})
    if res and res.get("status") == "success":
        return res.get("count", len(items))
    return len(items)

def delete_transaction(tx_id: int) -> bool:
    """Xóa giao dịch theo ID khỏi Google Sheets."""
    res = _call_sheets_api(payload={"action": "delete", "id": tx_id})
    return bool(res and res.get("status") == "success")

def get_today_summary() -> Dict[str, Any]:
    """Lấy tổng kết thu chi hôm nay trực tiếp từ Google Sheets."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    default_summary = {
        "date": today_str,
        "total_thu": 0,
        "total_chi": 0,
        "thu_cash": 0,
        "thu_transfer": 0,
        "chi_cash": 0,
        "chi_transfer": 0,
        "balance": 0,
        "count": 0
    }

    res = _call_sheets_api(params={"action": "today"})
    if res and "total_thu" in res:
        return res
    return default_summary

def get_month_summary(year: int, month: int) -> Dict[str, Any]:
    """Lấy báo cáo tài chính tháng trực tiếp từ Google Sheets."""
    default_res = {
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

    res = _call_sheets_api(params={"action": "month"})
    if not res:
        return default_res

    cat_chi_dict = res.get("categories_chi", {})
    cat_thu_dict = res.get("categories_thu", {})

    categories_chi = [{"category": k, "total": v, "count": 1} for k, v in cat_chi_dict.items()]
    categories_thu = [{"category": k, "total": v, "count": 1} for k, v in cat_thu_dict.items()]

    return {
        "year": year,
        "month": month,
        "total_thu": res.get("total_thu", 0),
        "total_chi": res.get("total_chi", 0),
        "thu_cash": res.get("thu_cash", 0),
        "thu_transfer": res.get("thu_transfer", 0),
        "chi_cash": res.get("chi_cash", 0),
        "chi_transfer": res.get("chi_transfer", 0),
        "balance": res.get("balance", 0),
        "categories_thu": categories_thu,
        "categories_chi": categories_chi
    }

def get_recent_transactions(limit: int = 10) -> List[Dict[str, Any]]:
    """Lấy danh sách các giao dịch gần nhất từ Google Sheets."""
    res = _call_sheets_api(params={"action": "recent"})
    if res and res.get("status") == "success":
        return res.get("items", [])[:limit]
    return []

def download_online_excel() -> Optional[Path]:
    """Tải trực tiếp file Excel của Google Sheets về máy."""
    sheets_url = config.GOOGLE_SHEETS_URL
    if not sheets_url:
        return None

    # Trích xuất Sheet ID từ URL (dạng https://docs.google.com/spreadsheets/d/<ID>/edit...)
    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', sheets_url)
    if not match:
        return None

    sheet_id = match.group(1)
    export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    out_file = config.REPORTS_DIR / f"SoQuy_NhaKhoa_GoogleSheets_{datetime.now().strftime('%Y_%m')}.xlsx"

    try:
        req = urllib.request.Request(export_url)
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            with open(out_file, "wb") as f:
                f.write(resp.read())
        return out_file
    except Exception as e:
        print(f"Không thể tải file trực tiếp từ Google Sheets: {e}")
        return None
