from __future__ import annotations
import json
import urllib.request
import urllib.parse
import ssl
import sys
import os
import traceback
from http.server import BaseHTTPRequestHandler
from datetime import datetime
from pathlib import Path

# Add root project directory to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

STARTUP_ERROR = None
BankStatementParser = None
try:
    import config
    import database
    from ai_parser import GeminiParser, RuleEngine, rules_mgr
    from bank_reconciler import BankStatementParser
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
            with urllib.request.urlopen(down_req, timeout=20, context=ssl_ctx) as down_resp:
                return down_resp.read()
    except Exception as e:
        print(f"Error downloading telegram file {file_id}: {e}")
        return None

def notify_sheets_error(chat_id: int):
    """Notify user when Google Sheets rejects or fails the transaction."""
    msg = (
        "❌ *CHƯA LƯU ĐƯỢC VÀO GOOGLE SHEETS!*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "• *Lý do:* Webhook Google Apps Script từ chối kết nối (lỗi 401 Unauthorized hoặc chưa mở quyền).\n\n"
        "👉 *Cách sửa nhanh (1 phút):*\n"
        "1. Mở file Google Sheets ➡️ *Tiện ích mở rộng* ➡️ *Apps Script*\n"
        "2. Bấm nút *Triển khai* (Deploy góc trên phải) ➡️ *Quản lý bản triển khai*\n"
        "3. Bấm biểu tượng ✏️ *(Chỉnh sửa)*\n"
        "4. Tại mục *Ai có quyền truy cập (Who has access)*: Đổi thành *Bất kỳ ai (Anyone)*\n"
        "5. Tại mục *Phiên bản (Version)*: Chọn *Phiên bản mới (New version)* ➡️ Bấm *Triển khai (Deploy)*"
    )
    send_telegram_message(chat_id, msg)

def extract_password_from_caption(caption: str) -> Optional[str]:
    """Trích xuất mật khẩu từ phần chú thích (caption) của tệp đính kèm."""
    if not caption:
        return None
    c = caption.strip()
    # 1. Có từ khóa tiền tố: pass: 123456, mk: 0303..., mat khau: ...
    m = re.search(r'(?:pass(?:word)?|mk|mat\s*khau|mật\s*khẩu)\s*[:=]?\s*(\S+)', c, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # 2. Hoặc toàn bộ caption chỉ là một chuỗi số (CCCD, Ngày sinh: 6 - 16 chữ số)
    if re.match(r'^\d{6,16}$', c):
        return c
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
    doc = message.get("document")

    # Check permissions
    if config.ALLOWED_TELEGRAM_USERS and user_id not in config.ALLOWED_TELEGRAM_USERS:
        if text == "/id":
            msg = (
                f"🆔 *THÔNG TIN TÀI KHOẢN:*\n"
                f"• User ID của bạn: `{user_id}`\n"
                f"• Chat ID: `{chat_id}`\n\n"
                f"_(Bạn chưa được cấp quyền sử dụng hệ thống. Hãy gửi ID `{user_id}` cho quản trị viên để được thêm vào danh sách cấp phép)_"
            )
            send_telegram_message(chat_id, msg)
            return
        send_telegram_message(chat_id, f"⛔ Bạn chưa được cấp quyền sử dụng hệ thống kế toán này. Gõ /id để xem Telegram User ID của bạn.")
        return

    # ==========================================
    # 1. CÁC LỆNH HỆ THỐNG & TRUY VẤN TÀI CHÍNH
    # ==========================================
    if text == "/start":
        welcome = (
            f"👋 *Xin chào {user.get('first_name', '')}! Tôi là Trợ Lý Kế Toán Phòng Khám Nha Khoa.*\n\n"
            "💡 *CÁCH GHI THU CHI NHANH (3 GIÂY):*\n"
            "• `+ 500k khach tram rang` ➡️ Thu tiền mặt\n"
            "• `+ 2tr ck khach Trang boc rang su` ➡️ Khách chuyển khoản\n"
            "• `- 70k hoa qua thap huong` ➡️ Chi tiền mua hoa quả\n"
            "• `- 1.2tr ck labo rang su chi Nga` ➡️ Chi tiền làm labo\n"
            "• 🎙 *Giọng nói:* Giữ nút Micro nói (VD: *'Thu chị Quỳnh 500k khám răng'*), AI tự nghe và ghi chép.\n"
            "• 📸 *Ảnh chụp:* Chụp hóa đơn/phiếu thu gửi vào đây để AI đọc tự động.\n\n"
            "📌 *CÁC LỆNH BÁO CÁO & TRUY VẤN:*\n"
            "• /today : Xem thu chi hôm nay\n"
            "• `/ngay [dd/mm]` : Xem thu chi ngày chỉ định (VD: `/ngay 13/10`)\n"
            "• `/khoang <từ> <đến>` : Xem thu chi theo khoảng (VD: `/khoang 01/10 14/10`)\n"
            "• `/thang [mm/yyyy]` : Xem báo cáo tháng chỉ định (VD: `/thang 9` hoặc `/thang 10/2026`)\n"
            "• `/nam [yyyy]` : Xem báo cáo tổng kết cả năm (VD: `/nam 2026`)\n"
            "• /ds : Xem 10 giao dịch vừa nhập gần nhất\n"
            "• `/xoa <id>` : Xóa giao dịch nếu nhập nhầm (VD: `/xoa 5`)\n"
            "• /sheet : Mở trực tiếp Sổ Quỹ Google Sheets online (mỗi năm 1 tab riêng)\n"
            "• /help : Xem cẩm nang hướng dẫn sử dụng chi tiết nhất\n\n"
            "🛡️ *ĐỐI SOÁT & CHỐNG TRÙNG LẶP:* Cuối tháng gửi file sao kê ngân hàng (.xlsx/.csv), hệ thống tự động nhận diện và bỏ qua các khoản đã nhập qua giọng nói/tin nhắn trước đó!\n\n"
            f"🆔 *Telegram ID của bạn:* `{user_id}`"
        )
        send_telegram_message(chat_id, welcome)

    elif text == "/help":
        help_msg = (
            "📖 *CẨM NANG HƯỚNG DẪN SỬ DỤNG BOT KẾ TOÁN NHA KHOA*\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⚡ *1. GHI NHẬN THU CHI NHANH (3 CÁCH):*\n\n"
            "• 💬 *Nhắn tin văn bản:*\n"
            "  - `+ 500k tram rang` ➡️ Thu tiền mặt\n"
            "  - `+ 2tr ck khach Trang boc su` ➡️ Thu chuyển khoản\n"
            "  - `- 70k hoa qua thap huong` ➡️ Chi tiền mặt\n"
            "  - `- 1.2tr ck labo rang su chi Nga` ➡️ Chi chuyển khoản\n\n"
            "• 🎙 *Giọng nói (Voice):* Giữ nút Micro nói tự nhiên:\n"
            "  - *\"Thu chị Quỳnh 500k khám răng\"*\n"
            "  - *\"Chi 150 nghìn mua găng tay y tế\"*\n"
            "  ➡️ Gemini AI tự nhận diện lời thoại và lưu ngay vào Google Sheets!\n\n"
            "• 📸 *Ảnh chụp hóa đơn:* Chụp ảnh phiếu thu/hóa đơn gửi vào bot để AI quét tự động.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📊 *2. CÁC LỆNH BÁO CÁO & TRA CỨU TÀI CHÍNH:*\n\n"
            "• /today : Xem nhanh tổng kết thu chi hôm nay.\n"
            "• `/ngay [dd/mm hoặc dd/mm/yyyy]` : Xem thu chi và danh sách giao dịch ngày chỉ định.\n"
            "  ↳ *Ví dụ:* `/ngay 13/10` hoặc `/ngay 13/10/2026`\n"
            "• `/khoang <từ ngày> <đến ngày>` : Xem thu chi theo khoảng thời gian bất kỳ.\n"
            "  ↳ *Ví dụ:* `/khoang 01/10 14/10` hoặc `/khoang 01/10/2026 14/10/2026`\n"
            "• `/thang [mm/yyyy hoặc mm]` : Báo cáo doanh thu, chi phí, lợi nhuận ròng của tháng.\n"
            "  ↳ *Ví dụ:* `/thang 9` hoặc `/thang 10/2026`\n"
            "• `/nam [yyyy]` : Báo cáo tài chính cả năm & bảng kết quả từng tháng (T01 ➔ T12).\n"
            "  ↳ *Ví dụ:* `/nam 2026` hoặc `/nam`\n"
            "• /ds : Xem 10 giao dịch vừa nhập gần nhất.\n"
            "• `/xoa <id>` : Xóa giao dịch nếu nhập nhầm (Ví dụ: `/xoa 12`).\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🛡️ *3. ĐỐI SOÁT SAO KÊ & CHỐNG TRÙNG LẶP:*\n\n"
            "• Hệ thống hỗ trợ đa dạng định dạng sao kê ngân hàng: `.xlsx`, `.xls`, `.pdf`, `.csv` và cả file nén `.zip` có mật khẩu!\n"
            "• 🔐 *Hỗ trợ giải nén file ZIP ngân hàng:*\n"
            "  - Bạn có thể nhập mật khẩu vào ô Chú thích (Caption) khi gửi file.\n"
            "  - Hoặc lưu mật khẩu 1 lần bằng lệnh `/matkhau <mật khẩu>` (ví dụ: `/matkhau 038095000000` hoặc ngày sinh).\n"
            "• ⚡ **Deduplication Engine**: Tự động so khớp số tiền, ngày, phương thức chuyển khoản và từ khóa diễn giải để **bỏ qua các giao dịch đã nhập qua giọng nói/tin nhắn trước đó**, tuyệt đối không bị cộng dồn doanh thu 2 lần!\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⚙️ *4. QUẢN TRỊ & TIỆN ÍCH:*\n\n"
            "• /sheet : Mở trực tiếp Sổ Quỹ Google Sheets online (mỗi năm 1 tab riêng).\n"
            "• `/matkhau [mật khẩu]` : Cài đặt mật khẩu mặc định để tự động mở file sao kê ZIP ngân hàng.\n"
            "• `/hoc <từ khóa> = <thu/chi>: <danh mục>` : Dạy từ mới cho AI.\n"
            "• /id : Xem Telegram User ID của bạn để cấu hình bảo mật."
        )
        send_telegram_message(chat_id, help_msg)

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

    elif text == "/today" or text.startswith("/ngay"):
        arg = text[5:].strip() if text.startswith("/ngay") else ""
        target_date = None
        if arg:
            target_date = database.parse_user_date(arg)
            if not target_date:
                send_telegram_message(
                    chat_id,
                    "⚠️ *Định dạng ngày chưa đúng!*\n\n"
                    "Bạn có thể nhập:\n"
                    "• `/ngay` : Xem hôm nay\n"
                    "• `/ngay 13/10` : Xem ngày 13 tháng 10 năm nay\n"
                    "• `/ngay 13/10/2026` : Xem ngày 13/10/2026"
                )
                return

        s = database.get_date_summary(target_date)
        d_raw = s.get("date", "")
        try:
            display_date = datetime.strptime(d_raw[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            display_date = d_raw

        profit_symbol = "🟢" if s.get("balance", 0) >= 0 else "🔴"
        lines = [
            f"📊 *BÁO CÁO THU CHI NGÀY {display_date}*\n",
            f"🟢 *TỔNG THU:* `{format_vnd(s.get('total_thu', 0))}`",
            f"  • Tiền mặt: `{format_vnd(s.get('thu_cash', 0))}`",
            f"  • Chuyển khoản: `{format_vnd(s.get('thu_transfer', 0))}`\n",
            f"🔴 *TỔNG CHI:* `{format_vnd(s.get('total_chi', 0))}`",
            f"  • Tiền mặt: `{format_vnd(s.get('chi_cash', 0))}`",
            f"  • Chuyển khoản: `{format_vnd(s.get('chi_transfer', 0))}`\n",
            f"{profit_symbol} *CHÊNH LỆCH TRONG NGÀY:* `{format_vnd(s.get('balance', 0))}`",
            f"📝 Tổng số giao dịch: {s.get('count', 0)}"
        ]

        items = s.get("items", [])
        if items:
            lines.append("\n📋 *DANH SÁCH GIAO DỊCH TRONG NGÀY:*")
            for it in items[:15]:
                t_type = str(it.get("type", "")).lower()
                sign = "🟢 +" if "thu" in t_type else "🔴 -"
                method = "💵" if "mặt" in str(it.get("payment_method", "")).lower() or "cash" in str(it.get("payment_method", "")).lower() else "💳"
                t_time = str(it.get("time", ""))[:5]
                time_str = f"{t_time} | " if t_time else ""
                lines.append(
                    f"`#{it.get('id')}` | {time_str}{sign}{format_vnd(int(it.get('amount', 0)))} {method}\n"
                    f"   ↳ _{it.get('category', '')}_: {it.get('description', '')}"
                )
            if len(items) > 15:
                lines.append(f"\n_...và {len(items) - 15} giao dịch khác. Mở /sheet để xem toàn bộ._")
        else:
            lines.append("\n_(Không có giao dịch nào phát sinh trong ngày này)_")

        send_telegram_message(chat_id, "\n".join(lines))

    elif text.startswith("/khoang"):
        raw_text = text[7:].strip()
        cleaned = raw_text.replace("den", " ").replace("đến", " ").replace("-", " ")
        parts = cleaned.split()
        if len(parts) < 2:
            send_telegram_message(
                chat_id,
                "⚠️ *Cú pháp xem theo khoảng thời gian:*\n"
                "`/khoang <từ ngày> <đến ngày>`\n\n"
                "*Ví dụ:*\n"
                "• `/khoang 01/10 14/10`\n"
                "• `/khoang 01/10/2026 14/10/2026`"
            )
            return

        start_date = database.parse_user_date(parts[0])
        end_date = database.parse_user_date(parts[1])

        if not start_date or not end_date:
            send_telegram_message(chat_id, "⚠️ Ngày nhập vào không đúng định dạng. Vui lòng nhập dạng `dd/mm` hoặc `dd/mm/yyyy`.")
            return

        if start_date > end_date:
            start_date, end_date = end_date, start_date

        s = database.get_range_summary(start_date, end_date)
        profit_symbol = "🟢" if s.get("balance", 0) >= 0 else "🔴"
        d1 = datetime.strptime(start_date, "%Y-%m-%d").strftime("%d/%m/%Y")
        d2 = datetime.strptime(end_date, "%Y-%m-%d").strftime("%d/%m/%Y")

        lines = [
            f"📅 *BÁO CÁO TÀI CHÍNH TỪ {d1} ĐẾN {d2}*\n",
            f"🟢 *TỔNG THU:* `{format_vnd(s.get('total_thu', 0))}`",
            f"  • Tiền mặt: `{format_vnd(s.get('thu_cash', 0))}`",
            f"  • Chuyển khoản: `{format_vnd(s.get('thu_transfer', 0))}`\n",
            f"🔴 *TỔNG CHI:* `{format_vnd(s.get('total_chi', 0))}`",
            f"  • Tiền mặt: `{format_vnd(s.get('chi_cash', 0))}`",
            f"  • Chuyển khoản: `{format_vnd(s.get('chi_transfer', 0))}`\n",
            f"{profit_symbol} *LỢI NHUẬN RÒNG:* `{format_vnd(s.get('balance', 0))}`",
            f"📝 Tổng số giao dịch: {s.get('count', 0)}\n",
            "📂 *CƠ CẤU CHI PHÍ LỚN NHẤT:*"
        ]

        if s.get("categories_chi"):
            for c in s["categories_chi"][:5]:
                lines.append(f"  • {c['category']}: `{format_vnd(c['total'])}`")
        else:
            lines.append("  _(Chưa có chi phí)_")

        if s.get("categories_thu"):
            lines.append("\n📈 *CƠ CẤU DOANH THU:*")
            for c in s["categories_thu"][:5]:
                lines.append(f"  • {c['category']}: `{format_vnd(c['total'])}`")

        send_telegram_message(chat_id, "\n".join(lines))

    elif text.startswith("/thang") or text.startswith("/baocao"):
        prefix_len = 7 if text.startswith("/baocao") else 6
        raw_m = text[prefix_len:].strip()
        now = datetime.now()
        year, month = now.year, now.month

        if raw_m:
            parsed_m = database.parse_user_month(raw_m)
            if not parsed_m:
                send_telegram_message(
                    chat_id,
                    "⚠️ *Định dạng tháng chưa đúng!*\n\n"
                    "Bạn có thể nhập:\n"
                    "• `/thang` : Xem tháng này\n"
                    "• `/thang 9` : Xem tháng 9 năm nay\n"
                    "• `/thang 09/2026` : Xem tháng 09/2026"
                )
                return
            year, month = parsed_m

        s = database.get_month_summary(year, month)
        profit_symbol = "🟢" if s.get("balance", 0) >= 0 else "🔴"
        msg_lines = [
            f"📈 *BÁO CÁO TÀI CHÍNH THÁNG {month:02d}/{year:04d}*\n",
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

        if s.get("categories_thu"):
            msg_lines.append("\n🏆 *NGUỒN THU CHÍNH:*")
            for c in s["categories_thu"][:5]:
                msg_lines.append(f"  • {c['category']}: `{format_vnd(c['total'])}`")

        msg_lines.append("\n👉 Gõ /sheet để mở bảng tính Google Sheets chi tiết.")
        send_telegram_message(chat_id, "\n".join(msg_lines))

    elif text.startswith("/nam"):
        raw_y = text[4:].strip()
        target_year = datetime.now().year
        if raw_y:
            if raw_y.isdigit() and len(raw_y) == 4:
                target_year = int(raw_y)
            else:
                send_telegram_message(chat_id, "⚠️ Cú pháp: `/nam [yyyy]` (Ví dụ: `/nam 2026` hoặc `/nam`)")
                return

        s = database.get_year_summary(target_year)
        profit_symbol = "🟢" if s.get("balance", 0) >= 0 else "🔴"
        lines = [
            f"🏆 *BÁO CÁO TÀI CHÍNH NĂM {target_year}*\n",
            f"🟢 *TỔNG THU CẢ NĂM:* `{format_vnd(s.get('total_thu', 0))}`",
            f"  • Tiền mặt: `{format_vnd(s.get('thu_cash', 0))}`",
            f"  • Chuyển khoản: `{format_vnd(s.get('thu_transfer', 0))}`\n",
            f"🔴 *TỔNG CHI CẢ NĂM:* `{format_vnd(s.get('total_chi', 0))}`",
            f"  • Tiền mặt: `{format_vnd(s.get('chi_cash', 0))}`",
            f"  • Chuyển khoản: `{format_vnd(s.get('chi_transfer', 0))}`\n",
            f"{profit_symbol} *LỢI NHUẬN RÒNG CẢ NĂM:* `{format_vnd(s.get('balance', 0))}`",
            f"📝 Tổng giao dịch: {s.get('count', 0)}\n",
            "📊 *KẾT QUẢ TỪNG THÁNG TRONG NĂM:*"
        ]

        has_active_month = False
        for m in s.get("monthly_stats", []):
            if m.get("count", 0) > 0 or m.get("total_thu", 0) > 0 or m.get("total_chi", 0) > 0:
                has_active_month = True
                m_icon = "🟢" if m.get("balance", 0) >= 0 else "🔴"
                lines.append(
                    f"  • *T{m['month']:02d}:* Thu `{format_vnd(m['total_thu'])}` | Chi `{format_vnd(m['total_chi'])}` ➡️ {m_icon} `{format_vnd(m['balance'])}`"
                )

        if not has_active_month:
            lines.append("  _(Năm này chưa có dữ liệu giao dịch)_")

        if s.get("categories_chi"):
            lines.append("\n📂 *TOP CHI PHÍ LỚN NHẤT TRONG NĂM:*")
            for c in s["categories_chi"][:5]:
                lines.append(f"  • {c['category']}: `{format_vnd(c['total'])}`")

        send_telegram_message(chat_id, "\n".join(lines))

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
                d_raw = str(t.get("date", ""))
                d_display = f"{d_raw[8:10]}/{d_raw[5:7]}" if len(d_raw) >= 10 else d_raw
                lines.append(
                    f"`#{t.get('id')}` | {d_display} | {sign}{format_vnd(int(t.get('amount', 0)))} {method}\n"
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

    elif text.startswith("/matkhau") or text.startswith("/pass"):
        prefix_len = 5 if text.startswith("/pass") else 8
        arg = text[prefix_len:].strip()
        if not arg:
            saved = rules_mgr.get_statement_password()
            if saved:
                masked = saved[:2] + "*" * (len(saved) - 4) + saved[-2:] if len(saved) > 4 else "••••"
                send_telegram_message(
                    chat_id,
                    f"🔐 *MẬT KHẨU SAO KÊ ZIP ĐÃ LƯU:*\n\n"
                    f"• Mật khẩu hiện tại: `{masked}`\n\n"
                    f"👉 Để đổi mật khẩu mới: `/matkhau <mật khẩu mới>`\n"
                    f"👉 Để xóa mật khẩu đã lưu: `/matkhau xoa`"
                )
            else:
                send_telegram_message(
                    chat_id,
                    "ℹ️ *Chưa lưu mật khẩu mở file sao kê ZIP!*\n\n"
                    "Khi tải sao kê từ app ngân hàng (Vietcombank, Techcombank, MBBank...), file tải về thường là .ZIP có mật khẩu (thường là CCCD hoặc Ngày sinh).\n\n"
                    "👉 Bạn hãy gõ: `/matkhau <mật khẩu_của_bạn>` (Ví dụ: `/matkhau 0123456789`)\n"
                    "Hệ thống sẽ lưu lại để tự động giải nén mọi file ZIP bạn gửi sau này!"
                )
        elif arg.lower() in ["xoa", "clear", "delete", "remove"]:
            rules_mgr.set_statement_password("")
            send_telegram_message(chat_id, "🗑️ Đã xóa mật khẩu sao kê ZIP đã lưu thành công.")
        else:
            rules_mgr.set_statement_password(arg)
            send_telegram_message(
                chat_id,
                f"🔐 *ĐÃ LƯU MẬT KHẨU SAO KÊ THÀNH CÔNG!*\n\n"
                f"• Mật khẩu giải nén: `{arg}`\n\n"
                "Từ nay, mỗi khi bạn gửi file nén `.ZIP` sao kê từ ứng dụng ngân hàng vào bot, hệ thống sẽ tự động giải nén và nạp giao dịch mà bạn không cần phải giải nén thủ công trên điện thoại nữa!"
            )

    # ==========================================
    # 2. XỬ LÝ FILE SAO KÊ NGÂN HÀNG (MULTI-FORMAT & DEDUPLICATION)
    # ==========================================
    elif doc:
        filename = (doc.get("file_name") or "").lower()
        caption = message.get("caption") or ""
        supported_exts = [".xlsx", ".xls", ".pdf", ".csv", ".zip"]

        if not any(filename.endswith(ext) for ext in supported_exts):
            send_telegram_message(chat_id, "⚠️ Vui lòng gửi file sao kê từ ngân hàng dạng: Excel (`.xlsx`, `.xls`), PDF (`.pdf`), `.csv` hoặc file nén `.zip`.")
            return

        send_telegram_message(chat_id, "📑 Đang phân tích sao kê & giải mã đối soát... Vui lòng chờ vài giây.")
        file_id = doc.get("file_id")
        doc_bytes = download_telegram_file(file_id)
        if not doc_bytes:
            send_telegram_message(chat_id, "❌ Không thể tải file sao kê từ Telegram.")
            return

        temp_path = config.DATA_DIR / f"temp_{doc.get('file_name')}"
        try:
            with open(temp_path, "wb") as f:
                f.write(doc_bytes)

            global BankStatementParser
            if BankStatementParser is None:
                try:
                    from bank_reconciler import BankStatementParser
                except Exception as e:
                    send_telegram_message(chat_id, f"❌ Không thể nạp module phân tích sao kê: {e}")
                    return

            candidate_pwd = extract_password_from_caption(caption)
            items, err_code = BankStatementParser.parse_statement_file(temp_path, password=candidate_pwd)

            if err_code in ["PASSWORD_REQUIRED", "BAD_PASSWORD"]:
                if err_code == "BAD_PASSWORD":
                    send_telegram_message(
                        chat_id,
                        "🔒 *MẬT KHẨU GIẢI NÉN KHÔNG ĐÚNG!*\n"
                        "━━━━━━━━━━━━━━━━━━\n"
                        "Mật khẩu sao kê đã lưu hoặc mật khẩu trong chú thích không mở được file ZIP này.\n\n"
                        "👉 *Cách xử lý:*\n"
                        "• Cập nhật lại mật khẩu đúng: `/matkhau <mật khẩu_mới>` (VD: Số CCCD hoặc Ngày sinh)\n"
                        "• Hoặc gửi lại file ZIP và điền mật khẩu vào ô **Chú thích (Caption)**."
                    )
                else:
                    send_telegram_message(
                        chat_id,
                        "🔒 *FILE ZIP ĐƯỢC BẢO VỆ BẰNG MẬT KHẨU!*\n"
                        "━━━━━━━━━━━━━━━━━━\n"
                        "File sao kê nén từ ứng dụng ngân hàng có đặt mật khẩu bảo vệ.\n\n"
                        "👉 *Cách xử lý nhanh (chỉ cần làm 1 lần):*\n"
                        "1. Gõ lệnh: `/matkhau <mật khẩu_của_bạn>` (VD: Số CCCD hoặc Ngày sinh) để lưu sẵn. Lần sau gửi file ZIP bot sẽ tự động mở!\n"
                        "2. Hoặc gửi lại file ZIP và điền mật khẩu vào ô **Chú thích (Caption)**."
                    )
                return

            if not items:
                send_telegram_message(chat_id, "⚠️ Không tìm thấy dòng giao dịch hợp lệ nào trong tệp sao kê.")
                return

            unique_items, duplicate_items = database.reconcile_and_deduplicate(items)

            total_in = 0
            total_out = 0
            for it in unique_items:
                if it["type"] == "thu":
                    total_in += it["amount"]
                else:
                    total_out += it["amount"]

            saved_count = 0
            if unique_items:
                saved_count = database.add_batch_transactions(unique_items)

            file_type_badge = filename.split('.')[-1].upper()
            msg_lines = [
                "🎉 *ĐỐI SOÁT & NHẬP SAO KÊ THÀNH CÔNG!*\n",
                f"• Định dạng tệp: *{file_type_badge}*",
                f"• Tổng số giao dịch trong file: *{len(items)}*",
                f"• ✅ Giao dịch mới đã lưu: *{saved_count}*",
                f"• 🛡️ *Giao dịch trùng lặp bỏ qua: {len(duplicate_items)}*",
            ]

            if duplicate_items:
                msg_lines.append("\n🔎 *BẢN GHI TRÙNG ĐƯỢC PHÁT HIỆN:*")
                for dup in duplicate_items[:5]:
                    st_it = dup["statement_item"]
                    ex_it = dup["matched_existing"]
                    st_sign = "+" if st_it.get("type") == "thu" else "-"
                    msg_lines.append(
                        f"  ↳ `{st_sign}{format_vnd(st_it.get('amount', 0))}` ngày {st_it.get('date')}: Khớp với GD `#{ex_it.get('id')}` ({ex_it.get('description', '')})"
                    )
                if len(duplicate_items) > 5:
                    msg_lines.append(f"  _(và {len(duplicate_items) - 5} giao dịch trùng khác đã tự động bỏ qua)_")

            msg_lines.extend([
                "\n━━━━━━━━━━━━━━━━━━",
                f"• 🟢 Tổng tiền vào (Thu mới): *{format_vnd(total_in)}*",
                f"• 🔴 Tổng tiền ra (Chi mới): *{format_vnd(total_out)}*",
                "━━━━━━━━━━━━━━━━━━",
                "👉 Gõ /sheet để mở bảng tính Google Sheets chi tiết."
            ])
            send_telegram_message(chat_id, "\n".join(msg_lines))
        except Exception as e:
            traceback.print_exc()
            send_telegram_message(chat_id, f"❌ Lỗi khi phân tích sao kê: {e}")
        finally:
            try:
                if temp_path.exists():
                    os.remove(temp_path)
            except Exception:
                pass

    # ==========================================
    # 3. XỬ LÝ TIN NHẮN THOẠI (VOICE MESSAGE)
    # ==========================================
    elif voice:
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
                    "Bạn hãy nói rõ hơn (VD: *'Thu chị Quỳnh 500k khám răng'* hoặc *'Chi 70k hoa quả'*), hoặc gõ text nhé."
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

                if not tx_id:
                    notify_sheets_error(chat_id)
                    return

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

    # ==========================================
    # 4. XỬ LÝ HÓA ĐƠN CHỤP ẢNH (GEMINI VISION OCR)
    # ==========================================
    elif photo:
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
                if not tx_id:
                    notify_sheets_error(chat_id)
                    return

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

    # ==========================================
    # 5. XỬ LÝ NHẬP TIỀN BẰNG TEXT
    # ==========================================
    elif text:
        parsed = GeminiParser.parse_text(text)
        if not parsed:
            send_telegram_message(
                chat_id,
                "🤔 Chưa nhận diện được số tiền hoặc nội dung thu chi.\n\n"
                "Bạn hãy nhập theo mẫu:\n"
                "• `+ 500k tram rang` (Thu tiền mặt)\n"
                "• `+ 1.5tr ck khach boc rang` (Thu chuyển khoản)\n"
                "• `- 70k hoa qua thap huong` (Chi tiền mặt)\n"
                "• `- 1.2tr ck labo rang su` (Chi chuyển khoản)\n"
                "• Hoặc gửi tin nhắn thoại để AI tự nghe và ghi chép."
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
            if not tx_id:
                notify_sheets_error(chat_id)
                return

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
