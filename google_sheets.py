import json
import logging
import threading
import urllib.request
import urllib.error
import ssl
from typing import Dict, Any, List, Optional
import config

logger = logging.getLogger(__name__)
ssl_ctx = ssl.create_default_context()

def _send_post(url: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except Exception as e:
        logger.warning(f"Google Sheets POST failed: {e}")
        return None

def _send_get(url: str, params: Dict[str, str]) -> Optional[Dict[str, Any]]:
    try:
        query_string = urllib.parse.urlencode(params)
        full_url = f"{url}?{query_string}" if params else url
        req = urllib.request.Request(full_url)
        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except Exception as e:
        logger.warning(f"Google Sheets GET failed: {e}")
        return None

def sync_transaction_async(tx_data: Dict[str, Any]):
    """Sync single transaction to Google Sheets in background thread (non-blocking)."""
    webhook_url = config.GOOGLE_SHEETS_WEBHOOK_URL
    if not webhook_url:
        return
    thread = threading.Thread(target=_send_post, args=(webhook_url, tx_data), daemon=True)
    thread.start()

def sync_batch_async(transactions: List[Dict[str, Any]]):
    """Sync multiple transactions to Google Sheets in a single batch request."""
    webhook_url = config.GOOGLE_SHEETS_WEBHOOK_URL
    if not webhook_url or not transactions:
        return
    thread = threading.Thread(target=_send_post, args=(webhook_url, transactions), daemon=True)
    thread.start()

def delete_transaction_online(tx_id: int) -> bool:
    """Delete a transaction by ID from Google Sheets."""
    webhook_url = config.GOOGLE_SHEETS_WEBHOOK_URL
    if not webhook_url:
        return False
    res = _send_post(webhook_url, {"action": "delete", "id": tx_id})
    return bool(res and res.get("status") == "success")

def get_today_summary_online() -> Optional[Dict[str, Any]]:
    """Query today's summary from Google Sheets."""
    webhook_url = config.GOOGLE_SHEETS_WEBHOOK_URL
    if not webhook_url:
        return None
    return _send_get(webhook_url, {"action": "today"})

def get_month_summary_online() -> Optional[Dict[str, Any]]:
    """Query month's summary from Google Sheets."""
    webhook_url = config.GOOGLE_SHEETS_WEBHOOK_URL
    if not webhook_url:
        return None
    return _send_get(webhook_url, {"action": "month"})

def get_recent_online() -> Optional[List[Dict[str, Any]]]:
    """Query recent transactions from Google Sheets."""
    webhook_url = config.GOOGLE_SHEETS_WEBHOOK_URL
    if not webhook_url:
        return None
    res = _send_get(webhook_url, {"action": "recent"})
    return res.get("items", []) if res else None
