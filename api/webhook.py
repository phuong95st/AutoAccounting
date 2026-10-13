import json
import urllib.request
import urllib.parse
import ssl
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from datetime import datetime
from pathlib import Path

# Add root project directory to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

STARTUP_ERROR = None
try:
    import config
    import database
    from ai_parser import GeminiParser, RuleEngine, rules_mgr
except Exception:
    STARTUP_ERROR = traceback.format_exc()
    print(f"FATAL STARTUP ERROR: {STARTUP_ERROR}")

ssl_ctx = ssl.create_default_context()

def send_telegram_message(chat_id: int, text: str, parse_mode: str = "Markdown"):
    """Send message to user via Telegram Bot API."""
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8, context=ssl_ctx) as resp:
            pass
    except Exception as e:
        print(f"Error sending telegram message: {e}")

def format_vnd(amount: int) -> str:
    return f"{amount:,.0f}".replace(",", ".") + " ₫"

def download_telegram_file(file_id: str):
    """Download file bytes from Telegram Bot API."""
    token = config.TELEGRAM_BOT_TOKEN
    if not token or not file_id:
        return None
    url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not data.get("ok"):
                return None
            file_path = data.get("result", {}).get("file_path")
            if not file_path:
                return None
            down_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
            down_req = urllib.request.Request(down_url)
            with urllib.request.urlopen(down_req, timeout=15, context=ssl_ctx) as down_resp:
                return down_resp.read()
    except Exception as e:
        print(f"Error downloading telegram file {file_id}: {e}")
        return None

def process_telegram_update(update: dict):
    """Process incoming Telegram update dictionary."""
    message = update.get("message")
    if not message:
        return

    user = message.get("from", {})
    chat = message.get("chat", {})
    user_id = user.get("id")
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    voice = message.get("voice") or message.get("audio")
    photo = message.get("photo")

    # Check permissions
    if config.ALLOWED_TELEGRAM_USERS and user_id not in config.ALLOWED_TELEGRAM_USERS:
        send_telegram_message(chat_id, "⛔ Bạn chưa được cấp quyền sử dụng hệ thống kế toán này.")
        return

    # ==========================================
    # 1. CÁC LỆNH HỆ THỐNG
    # ==========================================
    if text == "/start" or text == "/help":
        welcome = (
            f"👋 *Xin chào {user.get('first_name', '')}! Tôi là Trợ Lý Kế Toán Phòng Khám Nha Khoa.*\n\n"
            "💡 *CÁCH GHI THU CHI NHANH:*\n"
            "• `+ 500k khach tram rang` ➡️ Thu tiền mặt\n"
            "• `+ 2tr ck khach Trang boc rang su` ➡️ Khách chuyển khoản\n"
            "• `- 70k hoa qua thap huong` ➡️ Chi tiền mua hoa quả\n"
            "• `- 1.2tr ck labo rang su chi Nga` ➡️ Chi tiền làm labo\n"
            "• 🎙 *Giọng nói:* Giữ nút Micro nói (VD: *'Thu 500k trám răng'*), AI tự nghe và ghi chép.\n"
            "• 📸 *Ảnh chụp:* Chụp hóa đơn/phiếu thu gửi vào đây để AI đọc tự động.\n\n"
            "📌 *CÁC LỆNH QUẢN TRỊ TRÊN GOOGLE SHEETS:*\n"
            "• /sheet : Mở trực tiếp Sổ Quỹ Google Sheets online\n"
            "• /today : Xem nhanh tổng kết thu chi hôm nay\n"
            "• /thang : Xem nhanh tổng kết doanh thu & chi phí tháng này\n"
            "• /ds : Xem 10 giao dịch vừa nhập gần nhất\n"
            "• /xoa `<id>` : Xóa giao dịch nếu nhập nhầm (VD: `/xoa 5`)\n"
            "• /hoc `<từ khóa> = <thu/chi>: <danh mục>` : Dạy từ mới cho AI\n\n"
            f"🆔 *Telegram ID của bạn:* `{user_id}`"
        )
        send_telegram_message(chat_id, welcome)

    elif text == "/id":
        msg = (
            f"🆔 *THÔNG TIN TÀI KHOẢN:*\n"
            f"• User ID của bạn: `{user_id}`\n"
            f"• Chat ID: `{chat_id}`\n\n"
            f"_(Nếu muốn bảo mật, dán ID `{user_id}` vào biến `ALLOWED_TELEGRAM_USERS` trong cài đặt Vercel)_"
        )
        send_telegram_message(chat_id, msg)

    elif text == "/sheet" or text == "/link":
        url = config.GOOGLE_SHEETS_URL
        if url:
            send_telegram_message(
                chat_id,
                f"📊 *BẢNG TÍNH GOOGLE SHEETS SỔ QUỸ*\n\n"
                f"🔗 Bấm vào link dưới đây để mở xem trực tiếp:\n"
                f"[👉 Mở Google Sheets Sổ Quỹ]({url})"
            )
        else:
            send_telegram_message(chat_id, "ℹ️ Chưa gắn GOOGLE_SHEETS_URL trong biến môi trường.")

    elif text == "/today" or text == "/ngay":
        s = database.get_today_summary()
        date_str = datetime.now().strftime("%d/%m/%Y")
        profit_symbol = "🟢" if s.get("balance", 0) >= 0 else "🔴"
        msg = (
            f"📊 *BÁO CÁO THU CHI HÔM NAY ({date_str})*\n\n"
            f"🟢 *TỔNG THU:* `{format_vnd(s.get('total_thu', 0))}`\n"
            f"  • Tiền mặt: `{format_vnd(s.get('thu_cash', 0))}`\n"
            f"  • Chuyển khoản: `{format_vnd(s.get('thu_transfer', 0))}`\n\n"
            f"🔴 *TỔNG CHI:* `{format_vnd(s.get('total_chi', 0))}`\n"
            f"  • Tiền mặt: `{format_vnd(s.get('chi_cash', 0))}`\n"
            f"  • Chuyển khoản: `{format_vnd(s.get('chi_transfer', 0))}`\n\n"
            f"{profit_symbol} *CHÊNH LỆCH TRONG NGÀY:* `{format_vnd(s.get('balance', 0))}`\n"
            f"📝 Tổng số giao dịch: {s.get('count', 0)}"
        )
        send_telegram_message(chat_id, msg)

    elif text == "/thang" or text == "/baocao":
        now = datetime.now()
        s = database.get_month_summary(now.year, now.month)
        profit_symbol = "🟢" if s.get("balance", 0) >= 0 else "🔴"
        msg_lines = [
            f"📈 *BÁO CÁO TÀI CHÍNH THÁNG {now.month:02d}/{now.year}*\n",
            f"🟢 *TỔNG THU:* `{format_vnd(s.get('total_thu', 0))}`",
            f"  • Tiền mặt: `{format_vnd(s.get('thu_cash', 0))}`",
            f"  • Chuyển khoản: `{format_vnd(s.get('thu_transfer', 0))}`\n",
            f"🔴 *TỔNG CHI:* `{format_vnd(s.get('total_chi', 0))}`",
            f"  • Tiền mặt: `{format_vnd(s.get('chi_cash', 0))}`",
            f"  • Chuyển khoản: `{format_vnd(s.get('chi_transfer', 0))}`\n",
            f"{profit_symbol} *LỢI NHUẬN RÒNG:* `{format_vnd(s.get('balance', 0))}`\n",
            "📂 *CƠ CẤU CHI PHÍ NỔI BẬT:*"
        ]
        if s.get("categories_chi"):
            for c in s["categories_chi"][:5]:
                msg_lines.append(f"  • {c['category']}: `{format_vnd(c['total'])}`")
        else:
            msg_lines.append("  _(Chưa có chi phí nào)_")
        msg_lines.append("\n👉 Gõ /sheet để mở bảng tính Google Sheets chi tiết.")
        send_telegram_message(chat_id, "\n".join(msg_lines))

    elif text == "/ds":
        txs = database.get_recent_transactions(limit=10)
        if not txs:
            send_telegram_message(chat_id, "Chưa có giao dịch nào trên Google Sheets.")
        else:
            lines = ["📋 *10 GIAO DỊCH GẦN NHẤT TRÊN GOOGLE SHEETS:*\n"]
            for t in txs:
                t_type = str(t.get("type", "")).lower()
                sign = "🟢 +" if "thu" in t_type else "🔴 -"
                method = "💵" if "mặt" in str(t.get("payment_method", "")).lower() or "cash" in str(t.get("payment_method", "")).lower() else "💳"
                d_str = str(t.get("date", ""))
                lines.append(
                    f"`#{t.get('id')}` | {d_str[5:]} | {sign}{format_vnd(int(t.get('amount', 0)))} {method}\n"
                    f"   ↳ _{t.get('category', '')}_: {t.get('description', '')}"
                )
            lines.append("\n_Gõ `/xoa <id>` để xóa nếu có giao dịch nhập nhầm._")
            send_telegram_message(chat_id, "\n".join(lines))

    elif text.startswith("/xoa"):
        parts = text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            send_telegram_message(chat_id, "⚠️ Cú pháp: `/xoa <id>` (Ví dụ: `/xoa 15`)")
        else:
            tx_id = int(parts[1])
            success = database.delete_transaction(tx_id)
            if success:
                send_telegram_message(chat_id, f"🗑️ Đã xóa giao dịch `#{tx_id}` trên Google Sheets thành công.")
            else:
                send_telegram_message(chat_id, f"❌ Không tìm thấy giao dịch `#{tx_id}` trên Google Sheets.")

    elif text.startswith("/hoc"):
        raw = text[4:].strip()
        if "=" in raw and ":" in raw:
            kw, rest = raw.split("=", 1)
            t_type, cat = rest.split(":", 1)
            rules_mgr.teach(kw.strip(), t_type.strip(), cat.strip())
            send_telegram_message(
                chat_id,
                f"🎓 *Đã ghi nhớ quy tắc thành công!*\n"
                f"• Từ khóa: `{kw.strip()}`\n"
                f"• Loại: `{t_type.strip().upper()}`\n"
                f"• Danh mục: `{cat.strip()}`"
            )
        else:
            send_telegram_message(chat_id, "⚠️ Cú pháp: `/hoc <từ khóa> = <thu/chi>: <danh mục>`")

    elif voice:
        # ==========================================
        # 2. XỬ LÝ TIN NHẮN THOẠI (VOICE MESSAGE)
        # ==========================================
        send_telegram_message(chat_id, "🎙 Đang lắng nghe và xử lý tin nhắn thoại qua Gemini AI...")
        file_id = voice.get("file_id")
        mime_type = voice.get("mime_type", "audio/ogg")
        audio_bytes = download_telegram_file(file_id)
        if not audio_bytes:
            send_telegram_message(chat_id, "❌ Không thể tải file âm thanh từ Telegram.")
        else:
            parsed = GeminiParser.parse_voice_audio(audio_bytes, mime_type=mime_type)
            if not parsed:
                send_telegram_message(
                    chat_id,
                    "⚠️ Chưa nghe rõ số tiền hoặc nội dung thu chi từ tin nhắn thoại.\n\n"
                    "Bạn hãy nói rõ hơn (VD: *'Thu 500k trám răng tiền mặt'* hoặc *'Chi 70k hoa quả'*), hoặc gõ text nhé."
                )
            else:
                tx_id = database.add_transaction(
                    tx_type=parsed.get("type", "chi"),
                    amount=parsed["amount"],
                    category=parsed["category"],
                    description=parsed.get("description", "Ghi âm giọng nói"),
                    payment_method=parsed.get("payment_method", "cash"),
                    source="voice",
                    user_id=user_id
                )
                is_thu = parsed.get("type") == "thu"
                sign_text = "🟢 THU VÀO" if is_thu else "🔴 CHI RA"
                method_text = "💵 Tiền mặt" if parsed.get("payment_method") == "cash" else "💳 Chuyển khoản"
                transcript = parsed.get("transcript", "")
                transcript_line = f"🎙 *Lời thoại:* \"_{transcript}_\"\n" if transcript else ""

                msg = (
                    f"✅ *ĐÃ GHI NHẬN GIAO DỊCH #{tx_id}*\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{transcript_line}"
                    f"• Loại: *{sign_text}*\n"
                    f"• Số tiền: *{format_vnd(parsed['amount'])}*\n"
                    f"• Danh mục: _{parsed['category']}_\n"
                    f"• Nội dung: {parsed.get('description', '')}\n"
                    f"• Hình thức: {method_text}\n"
                    f"• Nơi lưu: _Google Sheets Online_\n"
                    f"• Xử lý: _🎙 Gemini Voice AI_\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"_(Nhập nhầm? Gõ `/xoa {tx_id}` để xóa)_"
                )
                send_telegram_message(chat_id, msg)

    elif photo:
        # ==========================================
        # 3. XỬ LÝ HÓA ĐƠN CHỤP ẢNH (GEMINI VISION OCR)
        # ==========================================
        send_telegram_message(chat_id, "📸 Đang quét hóa đơn bằng Gemini Vision...")
        file_id = photo[-1].get("file_id")
        img_bytes = download_telegram_file(file_id)
        if not img_bytes:
            send_telegram_message(chat_id, "❌ Không thể tải ảnh từ Telegram.")
        else:
            parsed = GeminiParser.parse_receipt_image(img_bytes, mime_type="image/jpeg")
            if not parsed:
                send_telegram_message(chat_id, "⚠️ Không nhận diện được hóa đơn từ ảnh. Bạn vui lòng chụp rõ nét hơn hoặc nhập tay bằng text.")
            else:
                tx_id = database.add_transaction(
                    tx_type=parsed.get("type", "chi"),
                    amount=parsed["amount"],
                    category=parsed["category"],
                    description=parsed.get("description", "Hóa đơn chụp"),
                    payment_method=parsed.get("payment_method", "cash"),
                    source="ocr",
                    user_id=user_id
                )
                sign_text = "🟢 THU VÀO" if parsed.get("type") == "thu" else "🔴 CHI RA"
                method_text = "💵 Tiền mặt" if parsed.get("payment_method") == "cash" else "💳 Chuyển khoản"
                msg = (
                    f"🧾 *ĐÃ QUÉT VÀ LƯU HÓA ĐƠN #{tx_id}*\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"• Loại: *{sign_text}*\n"
                    f"• Số tiền: *{format_vnd(parsed['amount'])}*\n"
                    f"• Danh mục: _{parsed['category']}_\n"
                    f"• Nội dung: {parsed.get('description', '')}\n"
                    f"• Hình thức: {method_text}\n"
                    f"• Nơi lưu: _Google Sheets Online_\n"
                    f"• Nguồn: _Gemini Vision OCR_\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"_(Nhập nhầm? Gõ `/xoa {tx_id}` để xóa)_"
                )
                send_telegram_message(chat_id, msg)

    elif text:
        # ==========================================
        # 4. XỬ LÝ NHẬP TIỀN BẰNG TEXT
        # ==========================================
        parsed = GeminiParser.parse_text(text)
        if not parsed:
            send_telegram_message(
                chat_id,
                "🤔 Chưa nhận diện được số tiền hoặc nội dung thu chi.\n\n"
                "Bạn hãy nhập theo mẫu:\n"
                "• `+ 500k tram rang` (Thu tiền mặt)\n"
                "• `+ 1.5tr ck khach boc rang` (Thu chuyển khoản)\n"
                "• `- 70k hoa qua thap huong` (Chi tiền mặt)\n"
                "• `- 1.2tr ck labo rang su` (Chi chuyển khoản)"
            )
        else:
            tx_id = database.add_transaction(
                tx_type=parsed["type"],
                amount=parsed["amount"],
                category=parsed["category"],
                description=parsed.get("description", ""),
                payment_method=parsed.get("payment_method", "cash"),
                source="telegram",
                user_id=user_id
            )
            is_thu = parsed["type"] == "thu"
            sign_text = "🟢 THU VÀO" if is_thu else "🔴 CHI RA"
            method_text = "💵 Tiền mặt" if parsed["payment_method"] == "cash" else "💳 Chuyển khoản"
            engine_badge = "🤖 Gemini AI" if parsed.get("engine") == "gemini-ai" else "⚡ Rule Engine"

            msg = (
                f"✅ *ĐÃ GHI NHẬN GIAO DỊCH #{tx_id}*\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"• Loại: *{sign_text}*\n"
                f"• Số tiền: *{format_vnd(parsed['amount'])}*\n"
                f"• Danh mục: _{parsed['category']}_\n"
                f"• Nội dung: {parsed.get('description', '')}\n"
                f"• Hình thức: {method_text}\n"
                f"• Nơi lưu: _Google Sheets Online_\n"
                f"• Xử lý: _{engine_badge}_\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"_(Nhập nhầm? Gõ `/xoa {tx_id}` để xóa)_"
            )
            send_telegram_message(chat_id, msg)


def application(environ, start_response):
    """WSGI standard application entrypoint for Vercel Python runtime."""
    try:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "")

        # Gracefully handle browser / crawler favicon requests
        if "favicon" in path:
            start_response("204 No Content", [])
            return [b""]

        if method == "GET":
            start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8")])
            if STARTUP_ERROR:
                return [f"⚠️ Startup Error on Vercel:\n{STARTUP_ERROR}".encode("utf-8")]
            return ["🚀 AutoAccounting Webhook is live and running on Vercel!".encode("utf-8")]

        if method == "POST":
            content_length = int(environ.get("CONTENT_LENGTH", 0) or 0)
            post_data = environ["wsgi.input"].read(content_length) if content_length > 0 else b""
            if post_data:
                try:
                    update = json.loads(post_data.decode("utf-8"))
                    process_telegram_update(update)
                except Exception as e:
                    traceback.print_exc()

            start_response("200 OK", [("Content-Type", "application/json")])
            return [b'{"ok": true}']

        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"OK"]
    except Exception as e:
        traceback.print_exc()
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b'{"ok": true}']


class handler(BaseHTTPRequestHandler):
    """Hybrid handler supporting both WSGI and BaseHTTPRequestHandler."""
    def __new__(cls, *args, **kwargs):
        if len(args) == 2 and callable(args[1]):
            return application(args[0], args[1])
        return super().__new__(cls)

    def do_GET(self):
        if "favicon" in self.path:
            self.send_response(204)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        if STARTUP_ERROR:
            self.wfile.write(f"⚠️ Startup Error on Vercel:\n{STARTUP_ERROR}".encode("utf-8"))
        else:
            self.wfile.write("🚀 AutoAccounting Webhook is live and running on Vercel!".encode("utf-8"))

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            if post_data:
                update = json.loads(post_data.decode("utf-8"))
                process_telegram_update(update)
        except Exception as e:
            traceback.print_exc()

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')


# Expose both app and handler for Vercel
app = application
