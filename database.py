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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
import config

logger = config.logging if hasattr(config, 'logging') else None
ssl_ctx = ssl.create_default_context()
TZ_VN = timezone(timedelta(hours=7))

def parse_vn_date(val: Any) -> str:
    """Normalize date string to YYYY-MM-DD in Vietnam timezone."""
    if not val:
        return datetime.now(TZ_VN).strftime("%Y-%m-%d")
    s = str(val).strip()
    if "T" in s and s.endswith("Z"):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(TZ_VN)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    if re.match(r'^\d{4}-\d{2}-\d{2}', s):
        return s[:10]
    return s[:10]

def parse_vn_time(val: Any) -> str:
    """Normalize time string to HH:MM:ss in Vietnam timezone."""
    if not val:
        return datetime.now(TZ_VN).strftime("%H:%M:%S")
    s = str(val).strip()
    if "T" in s and s.endswith("Z"):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(TZ_VN)
            return dt.strftime("%H:%M:%S")
        except Exception:
            pass
    if re.match(r'^\d{2}:\d{2}', s):
        return s[:8]
    return s

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
    return None

def add_batch_transactions(items: List[Dict[str, Any]]) -> int:
    """Thêm nhiều giao dịch cùng lúc (từ sao kê ngân hàng) vào Google Sheets."""
    if not items:
        return 0
    res = _call_sheets_api(payload={"action": "add", "data": items})
    if res and res.get("status") == "success":
        return res.get("count", len(items))
    return 0

def delete_transaction(tx_id: int) -> bool:
    """Xóa giao dịch theo ID khỏi Google Sheets."""
    res = _call_sheets_api(payload={"action": "delete", "id": tx_id})
    return bool(res and res.get("status") == "success")

def get_recent_transactions(limit: int = 10) -> List[Dict[str, Any]]:
    """Lấy danh sách các giao dịch gần nhất từ Google Sheets."""
    res = _call_sheets_api(params={"action": "recent"})
    if res and res.get("status") == "success":
        items = res.get("items", [])
        for it in items:
            it["date"] = parse_vn_date(it.get("date"))
            it["time"] = parse_vn_time(it.get("time"))
        return items[:limit]
    return []

def get_transactions_by_month(year: int, month: int) -> List[Dict[str, Any]]:
    """Lấy danh sách các giao dịch trong tháng từ Google Sheets."""
    month_prefix = f"{year:04d}-{month:02d}"
    items = get_recent_transactions(limit=500)
    return [it for it in items if parse_vn_date(it.get("date")).startswith(month_prefix)]

def get_today_summary() -> Dict[str, Any]:
    """Lấy tổng kết thu chi hôm nay trực tiếp từ Google Sheets."""
    today_str = datetime.now(TZ_VN).strftime("%Y-%m-%d")
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
    if res and res.get("count", 0) > 0:
        return res

    # Fallback to compute from recent transactions in case Google Apps Script date comparison failed
    items = get_recent_transactions(limit=100)
    today_items = [it for it in items if parse_vn_date(it.get("date")) == today_str]
    if today_items:
        total_thu = 0
        total_chi = 0
        thu_cash = 0
        thu_transfer = 0
        chi_cash = 0
        chi_transfer = 0
        for it in today_items:
            amt = int(it.get("amount", 0))
            is_thu = str(it.get("type", "")).lower() == "thu"
            meth = str(it.get("payment_method", "")).lower()
            is_ck = any(k in meth for k in ["khoản", "transfer", "ck", "bank"])

            if is_thu:
                total_thu += amt
                if is_ck:
                    thu_transfer += amt
                else:
                    thu_cash += amt
            else:
                total_chi += amt
                if is_ck:
                    chi_transfer += amt
                else:
                    chi_cash += amt

        return {
            "date": today_str,
            "total_thu": total_thu,
            "total_chi": total_chi,
            "thu_cash": thu_cash,
            "thu_transfer": thu_transfer,
            "chi_cash": chi_cash,
            "chi_transfer": chi_transfer,
            "balance": total_thu - total_chi,
            "count": len(today_items)
        }

    return default_summary

def get_month_summary(year: int, month: int) -> Dict[str, Any]:
    """Lấy báo cáo tài chính tháng trực tiếp từ Google Sheets."""
    month_prefix = f"{year:04d}-{month:02d}"
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
    if res and (res.get("total_thu", 0) > 0 or res.get("total_chi", 0) > 0):
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

    # Fallback to compute from transactions
    month_items = get_transactions_by_month(year, month)
    if month_items:
        total_thu = 0
        total_chi = 0
        thu_cash = 0
        thu_transfer = 0
        chi_cash = 0
        chi_transfer = 0
        cat_chi = {}
        cat_thu = {}

        for it in month_items:
            amt = int(it.get("amount", 0))
            is_thu = str(it.get("type", "")).lower() == "thu"
            meth = str(it.get("payment_method", "")).lower()
            cat = str(it.get("category", "")).strip() or "Khác"
            is_ck = any(k in meth for k in ["khoản", "transfer", "ck", "bank"])

            if is_thu:
                total_thu += amt
                if is_ck:
                    thu_transfer += amt
                else:
                    thu_cash += amt
                cat_thu[cat] = cat_thu.get(cat, 0) + amt
            else:
                total_chi += amt
                if is_ck:
                    chi_transfer += amt
                else:
                    chi_cash += amt
                cat_chi[cat] = cat_chi.get(cat, 0) + amt

        categories_chi = [{"category": k, "total": v, "count": 1} for k, v in sorted(cat_chi.items(), key=lambda x: x[1], reverse=True)]
        categories_thu = [{"category": k, "total": v, "count": 1} for k, v in sorted(cat_thu.items(), key=lambda x: x[1], reverse=True)]

        return {
            "year": year,
            "month": month,
            "total_thu": total_thu,
            "total_chi": total_chi,
            "thu_cash": thu_cash,
            "thu_transfer": thu_transfer,
            "chi_cash": chi_cash,
            "chi_transfer": chi_transfer,
            "balance": total_thu - total_chi,
            "categories_thu": categories_thu,
            "categories_chi": categories_chi
        }

    return default_res

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
