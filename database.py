"""
Google Sheets Database Adapter
Dữ liệu được lưu trữ và truy vấn tập trung 100% trên Google Sheets trực tuyến.
Mỗi năm được lưu trữ trong một Tab (Sheet) riêng (VD: 2026, 2025, 2027).
Hỗ trợ chống trùng lặp thông minh khi nhập sao kê ngân hàng và hỗ trợ truy vấn nâng cao.
"""

import json
import re
import unicodedata
import urllib.request
import urllib.parse
import urllib.error
import ssl
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import config

logger = config.logging if hasattr(config, 'logging') else None
ssl_ctx = ssl.create_default_context()
TZ_VN = timezone(timedelta(hours=7))

def remove_vn_accents(s: str) -> str:
    """Loại bỏ dấu tiếng Việt để so sánh chuỗi không dấu."""
    if not s:
        return ""
    s = s.replace("đ", "d").replace("Đ", "d")
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return s.lower().strip()

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
    # Check DD/MM/YYYY or DD-MM-YYYY
    m = re.match(r'^(\d{1,2})[/-](\d{1,2})[/-](\d{4})', s)
    if m:
        d, m_val, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{m_val:02d}-{d:02d}"
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

def parse_user_date(val: str) -> Optional[str]:
    """Chuyển đổi các định dạng ngày người dùng nhập vào chuẩn YYYY-MM-DD."""
    if not val:
        return None
    s = val.strip().lower()
    now_vn = datetime.now(TZ_VN)

    if s in ["hom nay", "hôm nay", "today"]:
        return now_vn.strftime("%Y-%m-%d")
    if s in ["hom qua", "hôm qua", "yesterday"]:
        return (now_vn - timedelta(days=1)).strftime("%Y-%m-%d")

    # Format: DD/MM/YYYY hoặc DD-MM-YYYY
    m1 = re.match(r'^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$', s)
    if m1:
        d, m, y = int(m1.group(1)), int(m1.group(2)), int(m1.group(3))
        return f"{y:04d}-{m:02d}-{d:02d}"

    # Format: DD/MM hoặc DD-MM (mặc định năm hiện tại)
    m2 = re.match(r'^(\d{1,2})[/-](\d{1,2})$', s)
    if m2:
        d, m = int(m2.group(1)), int(m2.group(2))
        return f"{now_vn.year:04d}-{m:02d}-{d:02d}"

    # Format: YYYY-MM-DD hoặc YYYY/MM/DD
    m3 = re.match(r'^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$', s)
    if m3:
        y, m, d = int(m3.group(1)), int(m3.group(2)), int(m3.group(3))
        return f"{y:04d}-{m:02d}-{d:02d}"

    return None

def parse_user_month(val: str) -> Optional[Tuple[int, int]]:
    """Chuyển đổi chuỗi tháng (VD: '10/2026', '10', '2026-10') thành (year, month)."""
    if not val:
        return None
    s = val.strip().lower()
    now_vn = datetime.now(TZ_VN)

    # Dạng 'thang 10' hoặc 'tháng 10'
    s = re.sub(r'^(thang|tháng)\s*', '', s).strip()

    # Format: MM/YYYY hoặc MM-YYYY
    m1 = re.match(r'^(\d{1,2})[/-](\d{4})$', s)
    if m1:
        m, y = int(m1.group(1)), int(m1.group(2))
        if 1 <= m <= 12:
            return (y, m)

    # Format: YYYY-MM hoặc YYYY/MM
    m2 = re.match(r'^(\d{4})[/-](\d{1,2})$', s)
    if m2:
        y, m = int(m2.group(1)), int(m2.group(2))
        if 1 <= m <= 12:
            return (y, m)

    # Format: chỉ có số tháng M hoặc MM (mặc định năm hiện tại)
    if s.isdigit():
        m = int(s)
        if 1 <= m <= 12:
            return (now_vn.year, m)

    return None

def _call_sheets_api(payload: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """Gửi yêu cầu POST hoặc GET tới Google Apps Script Webhook."""
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

        with urllib.request.urlopen(req, timeout=14, context=ssl_ctx) as resp:
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
) -> Optional[int]:
    """Thêm một giao dịch vào Google Sheets (tự động phân bổ vào Sheet năm tương ứng)."""
    now = datetime.now(TZ_VN)
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
    """Thêm nhiều giao dịch cùng lúc vào Google Sheets."""
    if not items:
        return 0
    res = _call_sheets_api(payload={"action": "add", "data": items})
    if res and res.get("status") == "success":
        return res.get("count", len(items))
    return 0

def delete_transaction(tx_id: int) -> bool:
    """Xóa giao dịch theo ID khỏi Google Sheets trên tất cả các tab năm."""
    res = _call_sheets_api(payload={"action": "delete", "id": tx_id})
    return bool(res and res.get("status") == "success")

def get_recent_transactions(limit: int = 10) -> List[Dict[str, Any]]:
    """Lấy danh sách các giao dịch gần nhất từ Google Sheets."""
    res = _call_sheets_api(params={"action": "recent", "limit": str(limit)})
    if res and res.get("status") == "success":
        items = res.get("items", [])
        for it in items:
            it["date"] = parse_vn_date(it.get("date"))
            it["time"] = parse_vn_time(it.get("time"))
        return items[:limit]
    return []

def get_transactions_in_range(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """Lấy toàn bộ giao dịch trong một khoảng thời gian từ Google Sheets."""
    res = _call_sheets_api(params={"action": "range", "start_date": start_date, "end_date": end_date})
    if res and res.get("items") is not None:
        items = res.get("items", [])
        for it in items:
            it["date"] = parse_vn_date(it.get("date"))
            it["time"] = parse_vn_time(it.get("time"))
        return items
    # Fallback to recent transactions
    all_rec = get_recent_transactions(limit=500)
    return [it for it in all_rec if start_date <= parse_vn_date(it.get("date")) <= end_date]

def get_transactions_by_month(year: int, month: int) -> List[Dict[str, Any]]:
    """Lấy danh sách các giao dịch trong tháng từ Google Sheets."""
    start_date = f"{year:04d}-{month:02d}-01"
    end_date = f"{year:04d}-{month:02d}-31"
    return get_transactions_in_range(start_date, end_date)

def get_date_summary(target_date: Optional[str] = None) -> Dict[str, Any]:
    """Lấy tổng kết thu chi của một ngày cụ thể (mặc định hôm nay)."""
    date_str = target_date or datetime.now(TZ_VN).strftime("%Y-%m-%d")
    default_summary = {
        "date": date_str,
        "total_thu": 0,
        "total_chi": 0,
        "thu_cash": 0,
        "thu_transfer": 0,
        "chi_cash": 0,
        "chi_transfer": 0,
        "balance": 0,
        "count": 0,
        "items": []
    }

    res = _call_sheets_api(params={"action": "day", "date": date_str})
    if res and ("total_thu" in res or res.get("count", 0) > 0):
        # Format items dates
        for it in res.get("items", []):
            it["date"] = parse_vn_date(it.get("date"))
            it["time"] = parse_vn_time(it.get("time"))
        return res

    # Fallback: tính toán từ các giao dịch gần đây nếu API Apps Script chưa cập nhật
    items = get_recent_transactions(limit=200)
    day_items = [it for it in items if parse_vn_date(it.get("date")) == date_str]
    if day_items:
        total_thu = 0
        total_chi = 0
        thu_cash = 0
        thu_transfer = 0
        chi_cash = 0
        chi_transfer = 0
        for it in day_items:
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
            "date": date_str,
            "total_thu": total_thu,
            "total_chi": total_chi,
            "thu_cash": thu_cash,
            "thu_transfer": thu_transfer,
            "chi_cash": chi_cash,
            "chi_transfer": chi_transfer,
            "balance": total_thu - total_chi,
            "count": len(day_items),
            "items": day_items
        }

    return default_summary

def get_today_summary() -> Dict[str, Any]:
    """Lấy tổng kết thu chi hôm nay."""
    today_str = datetime.now(TZ_VN).strftime("%Y-%m-%d")
    return get_date_summary(today_str)

def get_range_summary(start_date: str, end_date: str) -> Dict[str, Any]:
    """Lấy báo cáo tổng hợp trong khoảng thời gian từ start_date đến end_date."""
    default_res = {
        "start_date": start_date,
        "end_date": end_date,
        "total_thu": 0,
        "total_chi": 0,
        "thu_cash": 0,
        "thu_transfer": 0,
        "chi_cash": 0,
        "chi_transfer": 0,
        "balance": 0,
        "count": 0,
        "categories_thu": [],
        "categories_chi": [],
        "items": []
    }

    res = _call_sheets_api(params={"action": "range", "start_date": start_date, "end_date": end_date})
    if res and ("total_thu" in res or res.get("count", 0) > 0):
        cat_chi_dict = res.get("categories_chi", {})
        cat_thu_dict = res.get("categories_thu", {})
        res["categories_chi"] = [{"category": k, "total": v, "count": 1} for k, v in sorted(cat_chi_dict.items(), key=lambda x: x[1], reverse=True)]
        res["categories_thu"] = [{"category": k, "total": v, "count": 1} for k, v in sorted(cat_thu_dict.items(), key=lambda x: x[1], reverse=True)]
        return res

    # Fallback to compute from items
    items = get_transactions_in_range(start_date, end_date)
    if items:
        total_thu = 0
        total_chi = 0
        thu_cash = 0
        thu_transfer = 0
        chi_cash = 0
        chi_transfer = 0
        cat_chi = {}
        cat_thu = {}

        for it in items:
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

        return {
            "start_date": start_date,
            "end_date": end_date,
            "total_thu": total_thu,
            "total_chi": total_chi,
            "thu_cash": thu_cash,
            "thu_transfer": thu_transfer,
            "chi_cash": chi_cash,
            "chi_transfer": chi_transfer,
            "balance": total_thu - total_chi,
            "count": len(items),
            "categories_thu": [{"category": k, "total": v, "count": 1} for k, v in sorted(cat_thu.items(), key=lambda x: x[1], reverse=True)],
            "categories_chi": [{"category": k, "total": v, "count": 1} for k, v in sorted(cat_chi.items(), key=lambda x: x[1], reverse=True)],
            "items": items
        }

    return default_res

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
        "count": 0,
        "categories_thu": [],
        "categories_chi": []
    }

    res = _call_sheets_api(params={"action": "month", "month": month_prefix})
    if res and ("total_thu" in res or res.get("total_thu", 0) > 0 or res.get("total_chi", 0) > 0):
        cat_chi_dict = res.get("categories_chi", {})
        cat_thu_dict = res.get("categories_thu", {})
        categories_chi = [{"category": k, "total": v, "count": 1} for k, v in sorted(cat_chi_dict.items(), key=lambda x: x[1], reverse=True)]
        categories_thu = [{"category": k, "total": v, "count": 1} for k, v in sorted(cat_thu_dict.items(), key=lambda x: x[1], reverse=True)]
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
            "count": res.get("count", 0),
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
            "count": len(month_items),
            "categories_thu": [{"category": k, "total": v, "count": 1} for k, v in sorted(cat_thu.items(), key=lambda x: x[1], reverse=True)],
            "categories_chi": [{"category": k, "total": v, "count": 1} for k, v in sorted(cat_chi.items(), key=lambda x: x[1], reverse=True)]
        }

    return default_res

def get_year_summary(year: Optional[int] = None) -> Dict[str, Any]:
    """Lấy báo cáo tài chính cả năm từ Google Sheets."""
    target_year = year or datetime.now(TZ_VN).year
    default_res = {
        "year": target_year,
        "total_thu": 0,
        "total_chi": 0,
        "thu_cash": 0,
        "thu_transfer": 0,
        "chi_cash": 0,
        "chi_transfer": 0,
        "balance": 0,
        "count": 0,
        "monthly_stats": [{"month": m, "total_thu": 0, "total_chi": 0, "balance": 0, "count": 0} for m in range(1, 13)],
        "categories_thu": [],
        "categories_chi": []
    }

    res = _call_sheets_api(params={"action": "year", "year": str(target_year)})
    if res and ("total_thu" in res or res.get("count", 0) > 0):
        cat_chi_dict = res.get("categories_chi", {})
        cat_thu_dict = res.get("categories_thu", {})
        res["categories_chi"] = [{"category": k, "total": v, "count": 1} for k, v in sorted(cat_chi_dict.items(), key=lambda x: x[1], reverse=True)]
        res["categories_thu"] = [{"category": k, "total": v, "count": 1} for k, v in sorted(cat_thu_dict.items(), key=lambda x: x[1], reverse=True)]
        return res

    # Fallback to compute from range
    start_date = f"{target_year:04d}-01-01"
    end_date = f"{target_year:04d}-12-31"
    year_items = get_transactions_in_range(start_date, end_date)
    if year_items:
        total_thu = 0
        total_chi = 0
        thu_cash = 0
        thu_transfer = 0
        chi_cash = 0
        chi_transfer = 0
        monthly = [{"month": m, "total_thu": 0, "total_chi": 0, "balance": 0, "count": 0} for m in range(1, 13)]
        cat_chi = {}
        cat_thu = {}

        for it in year_items:
            amt = int(it.get("amount", 0))
            is_thu = str(it.get("type", "")).lower() == "thu"
            meth = str(it.get("payment_method", "")).lower()
            cat = str(it.get("category", "")).strip() or "Khác"
            is_ck = any(k in meth for k in ["khoản", "transfer", "ck", "bank"])
            d_str = parse_vn_date(it.get("date"))
            try:
                m_idx = int(d_str[5:7]) - 1
            except Exception:
                m_idx = 0

            if is_thu:
                total_thu += amt
                if is_ck:
                    thu_transfer += amt
                else:
                    thu_cash += amt
                cat_thu[cat] = cat_thu.get(cat, 0) + amt
                if 0 <= m_idx < 12:
                    monthly[m_idx]["total_thu"] += amt
                    monthly[m_idx]["count"] += 1
            else:
                total_chi += amt
                if is_ck:
                    chi_transfer += amt
                else:
                    chi_cash += amt
                cat_chi[cat] = cat_chi.get(cat, 0) + amt
                if 0 <= m_idx < 12:
                    monthly[m_idx]["total_chi"] += amt
                    monthly[m_idx]["count"] += 1

        for m_obj in monthly:
            m_obj["balance"] = m_obj["total_thu"] - m_obj["total_chi"]

        return {
            "year": target_year,
            "total_thu": total_thu,
            "total_chi": total_chi,
            "thu_cash": thu_cash,
            "thu_transfer": thu_transfer,
            "chi_cash": chi_cash,
            "chi_transfer": chi_transfer,
            "balance": total_thu - total_chi,
            "count": len(year_items),
            "monthly_stats": monthly,
            "categories_thu": [{"category": k, "total": v, "count": 1} for k, v in sorted(cat_thu.items(), key=lambda x: x[1], reverse=True)],
            "categories_chi": [{"category": k, "total": v, "count": 1} for k, v in sorted(cat_chi.items(), key=lambda x: x[1], reverse=True)]
        }

    return default_res

def reconcile_and_deduplicate(
    statement_items: List[Dict[str, Any]],
    existing_items: Optional[List[Dict[str, Any]]] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    CƠ CHẾ PHÁT HIỆN & CHỐNG TRÙNG LẶP DỮ LIỆU THÔNG MINH
    
    So sánh danh sách giao dịch từ file sao kê ngân hàng với các giao dịch đã ghi nhận
    trước đó trên Google Sheets (qua giọng nói, tin nhắn nhanh, hóa đơn ảnh).

    Tiêu chí nhận diện trùng:
    1. Cùng chiều giao dịch (THU == THU hoặc CHI == CHI)
    2. Cùng số tiền chính xác (amount == amount)
    3. Ngày phát sinh lân cận (trong vòng +/- 2 ngày đối soát ngân hàng)
    4. Phương thức chuyển khoản (Transfer) hoặc có trùng lặp từ khóa mô tả (tên khách hàng, dịch vụ).
    
    Returns:
        (unique_items, duplicate_items)
        - unique_items: Danh sách giao dịch mới an toàn để thêm vào Google Sheets.
        - duplicate_items: Danh sách giao dịch bị trùng lặp kèm thông tin bản ghi gốc.
    """
    if not statement_items:
        return [], []

    # Nếu chưa truyền existing_items, tự động lấy các giao dịch trong khoảng thời gian của file sao kê
    if existing_items is None:
        dates = [it.get("date") for it in statement_items if it.get("date")]
        if dates:
            min_date = min(dates)
            max_date = max(dates)
            try:
                # Mở rộng biên độ 3 ngày trước và sau để đối soát độ trễ giao dịch ngân hàng
                dt_min = datetime.strptime(min_date[:10], "%Y-%m-%d") - timedelta(days=3)
                dt_max = datetime.strptime(max_date[:10], "%Y-%m-%d") + timedelta(days=3)
                existing_items = get_transactions_in_range(dt_min.strftime("%Y-%m-%d"), dt_max.strftime("%Y-%m-%d"))
            except Exception:
                existing_items = get_recent_transactions(limit=500)
        else:
            existing_items = get_recent_transactions(limit=500)

    matched_existing_ids = set()
    unique_items = []
    duplicate_items = []

    for st in statement_items:
        st_amt = int(st.get("amount", 0))
        st_type = str(st.get("type", "")).lower().strip()
        st_date_str = parse_vn_date(st.get("date"))
        st_desc = remove_vn_accents(str(st.get("description", "")))
        st_words = set(re.findall(r'\b\w{3,}\b', st_desc))

        is_duplicate = False
        matched_record = None
        match_reason = ""

        try:
            st_dt = datetime.strptime(st_date_str, "%Y-%m-%d").date()
        except Exception:
            st_dt = date.today()

        for ex in existing_items:
            ex_id = ex.get("id")
            if ex_id in matched_existing_ids:
                continue

            ex_amt = int(ex.get("amount", 0))
            ex_type = str(ex.get("type", "")).lower().strip()
            if ex_amt != st_amt or ex_type != st_type:
                continue

            ex_date_str = parse_vn_date(ex.get("date"))
            try:
                ex_dt = datetime.strptime(ex_date_str, "%Y-%m-%d").date()
            except Exception:
                ex_dt = st_dt

            days_diff = abs((st_dt - ex_dt).days)
            if days_diff > 2:
                continue

            # Tính điểm trùng khớp (Matching Score)
            score = 0
            reasons = []

            ex_source = str(ex.get("source", "")).lower()
            ex_meth = str(ex.get("payment_method", "")).lower()
            ex_desc = remove_vn_accents(str(ex.get("description", "")))
            ex_words = set(re.findall(r'\b\w{3,}\b', ex_desc))

            # Trường hợp 1: Tệp sao kê đã từng được import trước đó
            if ex_source == "bank_statement":
                score = 100
                reasons.append("Bản ghi sao kê đã được nhập trước đó")

            # Trường hợp 2: Giao dịch nhập tay/giọng nói trước đó
            else:
                # Nếu giao dịch trước đó đã được ghi nhận rõ là Tiền mặt thì KHÔNG trùng với sao kê ngân hàng
                is_cash = any(k in ex_meth for k in ["cash", "tiền mặt", "tien mat", "mat"]) and not any(k in ex_meth for k in ["transfer", "khoản", "ck", "bank"])
                if is_cash:
                    continue

                # Nếu giao dịch trước đó đã được đánh dấu chuyển khoản
                is_ck = any(k in ex_meth for k in ["transfer", "khoản", "ck", "bank"])
                if is_ck:
                    score += 40
                    reasons.append("Cùng hình thức Chuyển khoản")

                # Chênh lệch ngày
                if days_diff == 0:
                    score += 30
                    reasons.append("Cùng ngày giao dịch")
                elif days_diff == 1:
                    score += 20
                    reasons.append("Chênh lệch 1 ngày đối soát")
                else:
                    score += 10

                # Trùng lặp từ khóa trong diễn giải (tên bệnh nhân, tên dịch vụ)
                common_words = st_words.intersection(ex_words)
                # Loại bỏ các từ quá phổ biến trong sao kê ngân hàng
                common_words = {w for w in common_words if w not in ["chuyen", "tien", "khach", "thanh", "toan", "ngan", "hang", "vietcombank", "techcombank", "mbbank"]}
                if common_words:
                    score += 40
                    reasons.append(f"Khớp từ khóa: {', '.join(common_words)}")

            # Nếu tổng điểm >= 60 -> Xác định là bản ghi trùng lặp
            if score >= 60:
                is_duplicate = True
                matched_record = ex
                matched_existing_ids.add(ex_id)
                match_reason = " & ".join(reasons)
                break

        if is_duplicate:
            duplicate_items.append({
                "statement_item": st,
                "matched_existing": matched_record,
                "reason": match_reason
            })
        else:
            unique_items.append(st)

    return unique_items, duplicate_items

def download_online_excel() -> Optional[Path]:
    """Tải trực tiếp file Excel của Google Sheets về máy."""
    sheets_url = config.GOOGLE_SHEETS_URL
    if not sheets_url:
        return None

    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', sheets_url)
    if not match:
        return None

    sheet_id = match.group(1)
    export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    out_file = config.REPORTS_DIR / f"SoQuy_NhaKhoa_GoogleSheets_{datetime.now(TZ_VN).strftime('%Y_%m')}.xlsx"

    try:
        req = urllib.request.Request(export_url)
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as resp:
            with open(out_file, "wb") as f:
                f.write(resp.read())
        return out_file
    except Exception as e:
        print(f"Không thể tải file trực tiếp từ Google Sheets: {e}")
        return None

_gas_features_cache = None

def get_gas_features() -> List[str]:
    """Kiểm tra các tính năng được hỗ trợ bởi phiên bản Google Apps Script hiện tại."""
    global _gas_features_cache
    if _gas_features_cache is not None:
        return _gas_features_cache
    try:
        res = _call_sheets_api(params={"action": "ping"})
        if res and isinstance(res.get("features"), list):
            _gas_features_cache = res["features"]
        else:
            _gas_features_cache = []
    except Exception:
        _gas_features_cache = []
    return _gas_features_cache

def save_setting(key: str, value: str) -> bool:
    """Lưu cấu hình hệ thống (key-value) lên Google Sheets PropertiesService nếu script hỗ trợ."""
    if "settings" not in get_gas_features():
        # Phiên bản Apps Script trên Google Sheets chưa được người dùng deploy bản mới, không gửi để tránh tạo dòng rác
        return False
    try:
        res = _call_sheets_api(payload={"action": "set_setting", "key": key, "value": value})
        return bool(res and res.get("status") == "success")
    except Exception as e:
        print(f"Lỗi khi lưu cấu hình lên Google Sheets: {e}")
        return False

def get_setting(key: str) -> Optional[str]:
    """Truy vấn cấu hình hệ thống (key-value) từ Google Sheets PropertiesService nếu script hỗ trợ."""
    if "settings" not in get_gas_features():
        return None
    try:
        res = _call_sheets_api(params={"action": "get_setting", "key": key})
        if res and res.get("status") == "ok":
            return res.get("value")
    except Exception as e:
        print(f"Lỗi khi đọc cấu hình từ Google Sheets: {e}")
    return None


