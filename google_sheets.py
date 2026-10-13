import json
import logging
import threading
import urllib.request
import urllib.error
import ssl
from typing import Dict, Any, List
import config

logger = logging.getLogger(__name__)
ssl_ctx = ssl.create_default_context()

def _send_post(url: str, payload: Dict[str, Any]):
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=8, context=ssl_ctx) as resp:
            res = resp.read().decode("utf-8")
            logger.info(f"Google Sheets sync response: {res}")
    except Exception as e:
        logger.warning(f"Google Sheets sync failed: {e}")

def sync_transaction_async(tx_data: Dict[str, Any]):
    """Sync single transaction to Google Sheets in background thread (non-blocking)."""
    webhook_url = config.GOOGLE_SHEETS_WEBHOOK_URL
    if not webhook_url:
        return

    # Run in daemon thread so user doesn't experience any delay
    thread = threading.Thread(target=_send_post, args=(webhook_url, tx_data), daemon=True)
    thread.start()

def sync_batch_async(transactions: List[Dict[str, Any]]):
    """Sync multiple transactions to Google Sheets."""
    webhook_url = config.GOOGLE_SHEETS_WEBHOOK_URL
    if not webhook_url:
        return

    def _batch_worker():
        for tx in transactions:
            _send_post(webhook_url, tx)

    thread = threading.Thread(target=_batch_worker, daemon=True)
    thread.start()
