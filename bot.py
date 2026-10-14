import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from telegram import Update, BotCommand
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

import config
import database
from ai_parser import GeminiParser, RuleEngine, rules_mgr
from bank_reconciler import BankStatementParser, ReportGenerator

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def format_vnd(amount: int) -> str:
    return f"{amount:,.0f}".replace(",", ".") + " ₫"

def is_user_allowed(user_id: int) -> bool:
    if not config.ALLOWED_TELEGRAM_USERS:
        return True
    return user_id in config.ALLOWED_TELEGRAM_USERS

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome and usage instructions."""
    user = update.effective_user
    msg = (
        f"👋 *Xin chào {user.first_name}! Tôi là Trợ Lý Kế Toán Phòng Khám Nha Khoa.*\n\n"
        "💡 *CÁCH GHI THU CHI NHANH (3 GIÂY):*\n"
        "• `+ 500k khach tram rang` ➡️ Thu tiền mặt\n"
        "• `+ 2tr ck khach Trang boc rang su` ➡️ Khách chuyển khoản\n"
        "• `- 70k hoa qua thap huong` ➡️ Chi tiền mua hoa quả\n"
        "• `- 1.2tr ck labo rang su chi Nga` ➡️ Chi tiền làm labo\n"
        "• 🎙 *Giọng nói:* Giữ nút Micro nói (VD: *'Thu chị Quỳnh 500k khám răng'*), AI tự nghe và ghi chép.\n"
        "• 📸 *Ảnh chụp:* Chụp ảnh hóa đơn/phiếu thu gửi vào đây để AI đọc tự động.\n\n"
        "📌 *CÁC LỆNH BÁO CÁO & TRUY VẤN TÀI CHÍNH:*\n"
        "• /today : Xem thu chi hôm nay\n"
        "• `/ngay [dd/mm]` : Xem thu chi ngày chỉ định (VD: `/ngay 13/10`)\n"
        "• `/khoang <từ> <đến>` : Xem thu chi theo khoảng (VD: `/khoang 01/10 14/10`)\n"
        "• `/thang [mm/yyyy]` : Xem báo cáo tháng chỉ định (VD: `/thang 9` hoặc `/thang 10/2026`)\n"
        "• `/nam [yyyy]` : Xem báo cáo tổng kết cả năm (VD: `/nam 2026`)\n"
        "• /ds : Xem 10 giao dịch vừa nhập gần nhất\n"
        "• `/xoa <id>` : Xóa giao dịch nếu nhập nhầm (VD: `/xoa 5`)\n"
        "• /sheet : Mở trực tiếp Sổ Quỹ Google Sheets online (mỗi năm 1 tab riêng)\n"
        "• /excel : Tải file Excel của Google Sheets về máy\n"
        "• `/hoc <từ khóa> = <thu/chi>: <danh mục>` : Dạy từ mới cho AI\n\n"
        "🛡️ *ĐỐI SOÁT & CHỐNG TRÙNG LẶP:* Cuối tháng bạn gửi file sao kê ngân hàng (.xlsx/.csv), hệ thống tự động nhận diện và bỏ qua các khoản đã nhập qua giọng nói/tin nhắn trước đó!\n\n"
        f"🆔 *Telegram ID của bạn:* `{user.id}`"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current user's Telegram ID."""
    user = update.effective_user
    chat = update.effective_chat
    await update.message.reply_text(
        f"🆔 *THÔNG TIN TÀI KHOẢN:*\n"
        f"• User ID của bạn: `{user.id}`\n"
        f"• Chat ID: `{chat.id}`\n\n"
        f"_(Nếu muốn bảo mật chỉ cho phép một mình bạn dùng bot, hãy dán ID `{user.id}` vào biến `ALLOWED_TELEGRAM_USERS` trong file `.env`)_",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detailed manual and command syntax reference."""
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
        "• /excel : Tải file Excel Sổ Quỹ mới nhất về máy.\n"
        "• `/matkhau [mật khẩu]` : Cài đặt mật khẩu mặc định để tự động mở file sao kê ZIP ngân hàng.\n"
        "• `/hoc <từ khóa> = <thu/chi>: <danh mục>` : Dạy từ khóa mới cho AI.\n"
        "• /id : Xem Telegram User ID của bạn để cấu hình bảo mật."
    )
    await update.message.reply_text(help_msg, parse_mode=ParseMode.MARKDOWN)

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View today's financial summary."""
    await cmd_day(update, context)

async def cmd_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View financial summary of a specific date or today.
    Syntax: /ngay [dd/mm/yyyy hoặc dd/mm] (Ví dụ: /ngay 13/10 hoặc /ngay)
    """
    args = context.args or []
    target_date = None
    if args:
        target_date = database.parse_user_date(" ".join(args))
        if not target_date:
            await update.message.reply_text(
                "⚠️ *Định dạng ngày chưa đúng!*\n\n"
                "Bạn có thể nhập:\n"
                "• `/ngay` : Xem hôm nay\n"
                "• `/ngay 13/10` : Xem ngày 13 tháng 10 năm nay\n"
                "• `/ngay 13/10/2026` : Xem ngày 13/10/2026",
                parse_mode=ParseMode.MARKDOWN
            )
            return

    s = database.get_date_summary(target_date)
    d_raw = s.get("date", "")
    try:
        dt_obj = datetime.strptime(d_raw[:10], "%Y-%m-%d")
        display_date = dt_obj.strftime("%d/%m/%Y")
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

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def cmd_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View transactions and financial summary in a date range.
    Syntax: /khoang <tu_ngay> <den_ngay> (VD: /khoang 01/10 14/10)
    """
    args = context.args or []
    raw_text = " ".join(args).strip()
    cleaned = raw_text.replace("den", " ").replace("đến", " ").replace("-", " ")
    parts = cleaned.split()
    if len(parts) < 2:
        await update.message.reply_text(
            "⚠️ *Cú pháp xem theo khoảng thời gian:*\n"
            "`/khoang <từ ngày> <đến ngày>`\n\n"
            "*Ví dụ:*\n"
            "• `/khoang 01/10 14/10`\n"
            "• `/khoang 01/10/2026 14/10/2026`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    start_date = database.parse_user_date(parts[0])
    end_date = database.parse_user_date(parts[1])

    if not start_date or not end_date:
        await update.message.reply_text("⚠️ Ngày nhập vào không đúng định dạng. Vui lòng nhập dạng `dd/mm` hoặc `dd/mm/yyyy`.", parse_mode=ParseMode.MARKDOWN)
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

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def cmd_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View month summary (current or specific month).
    Syntax: /thang [mm/yyyy hoặc mm] (VD: /thang 9 hoặc /thang 09/2026 hoặc /thang)
    """
    args = context.args or []
    now = datetime.now()
    year, month = now.year, now.month

    if args:
        parsed_m = database.parse_user_month(" ".join(args))
        if not parsed_m:
            await update.message.reply_text(
                "⚠️ *Định dạng tháng chưa đúng!*\n\n"
                "Bạn có thể nhập:\n"
                "• `/thang` : Xem tháng này\n"
                "• `/thang 9` : Xem tháng 9 năm nay\n"
                "• `/thang 09/2026` : Xem tháng 09/2026",
                parse_mode=ParseMode.MARKDOWN
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

    msg_lines.append("\n👉 Gõ /excel để tải file báo cáo Excel chi tiết.")
    await update.message.reply_text("\n".join(msg_lines), parse_mode=ParseMode.MARKDOWN)

async def cmd_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View annual financial report.
    Syntax: /nam [yyyy] (VD: /nam 2026 hoặc /nam)
    """
    args = context.args or []
    target_year = datetime.now().year
    if args:
        val = args[0].strip()
        if val.isdigit() and len(val) == 4:
            target_year = int(val)
        else:
            await update.message.reply_text("⚠️ Cú pháp: `/nam [yyyy]` (Ví dụ: `/nam 2026` hoặc `/nam`)", parse_mode=ParseMode.MARKDOWN)
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

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def cmd_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export and send live Excel file directly from Google Sheets."""
    now = datetime.now()
    await update.message.reply_text("⏳ Đang tải file Excel mới nhất từ Google Sheets... Vui lòng đợi trong giây lát.")
    try:
        report_path = database.download_online_excel()
        if not report_path or not report_path.exists():
            report_path = ReportGenerator.generate_monthly_excel(now.year, now.month)

        with open(report_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=report_path.name,
                caption=f"📊 Sổ Quỹ Thu Chi Phòng Khám Nha Khoa (Dữ liệu trực tuyến Google Sheets)."
            )
    except Exception as e:
        logger.error(f"Error exporting Excel: {e}")
        await update.message.reply_text(f"❌ Có lỗi khi tạo file Excel: {e}")

async def cmd_recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View recent transactions from Google Sheets."""
    txs = database.get_recent_transactions(limit=10)
    if not txs:
        await update.message.reply_text("Chưa có giao dịch nào được ghi nhận trên Google Sheets.")
        return

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
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a transaction by ID from Google Sheets."""
    if not context.args:
        await update.message.reply_text("⚠️ Cú pháp: `/xoa <id>` (Ví dụ: `/xoa 15`)", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        tx_id = int(context.args[0])
        success = database.delete_transaction(tx_id)
        if success:
            await update.message.reply_text(
                f"🗑️ Đã xóa giao dịch `#{tx_id}` trên Google Sheets thành công.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(f"❌ Không tìm thấy giao dịch `#{tx_id}` trên Google Sheets.")
    except ValueError:
        await update.message.reply_text("⚠️ ID phải là chữ số. Ví dụ: `/xoa 12`", parse_mode=ParseMode.MARKDOWN)

async def cmd_teach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Teach new rule/keyword to the bot."""
    raw_args = " ".join(context.args).strip()
    if "=" not in raw_args or ":" not in raw_args:
        help_msg = (
            "⚠️ *Cú pháp dạy từ khóa cho AI:*\n"
            "`/hoc <từ khóa> = <thu hoặc chi>: <tên danh mục>`\n\n"
            "*Ví dụ:*\n"
            "• `/hoc hoa qua = chi: Chi phí Tâm linh & Sinh hoạt`\n"
            "• `/hoc tay trang = thu: Doanh thu Dịch vụ`\n"
            "• `/hoc tien dien = chi: Chi phí Vận hành & Tiện ích`"
        )
        await update.message.reply_text(help_msg, parse_mode=ParseMode.MARKDOWN)
        return

    try:
        keyword_part, rest = raw_args.split("=", 1)
        tx_type_part, category_part = rest.split(":", 1)

        keyword = keyword_part.strip().lower()
        tx_type = tx_type_part.strip().lower()
        category = category_part.strip()

        if tx_type not in ["thu", "chi"]:
            await update.message.reply_text("⚠️ Loại chỉ được là `thu` hoặc `chi`.")
            return

        rules_mgr.teach(keyword, tx_type, category)
        await update.message.reply_text(
            f"🎓 *Đã ghi nhớ quy tắc thành công!*\n"
            f"• Từ khóa: `{keyword}`\n"
            f"• Loại: `{tx_type.upper()}`\n"
            f"• Danh mục: `{category}`\n\n"
            "AI và Bộ quy tắc Rule sẽ tự động áp dụng quy tắc này từ nay về sau.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi cú pháp: {e}")

def extract_password_from_caption(caption: Optional[str]) -> Optional[str]:
    """Trích xuất mật khẩu từ phần chú thích (caption) của tệp đính kèm."""
    if not caption:
        return None
    c = caption.strip()
    m = re.search(r'(?:pass|mk|mat\s*khau|mật\s*khẩu)\s*[:=]?\s*(\S+)', c, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    if re.match(r'^[a-zA-Z0-9@#\-_]{4,20}$', c):
        return c
    return None

async def cmd_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manage default password for bank statement zip files."""
    args = context.args or []
    if not args:
        saved = rules_mgr.get_statement_password()
        if saved:
            masked = saved[:2] + "*" * (len(saved) - 4) + saved[-2:] if len(saved) > 4 else "••••"
            await update.message.reply_text(
                f"🔐 *MẬT KHẨU SAO KÊ ZIP ĐÃ LƯU:*\n\n"
                f"• Mật khẩu hiện tại: `{masked}`\n\n"
                f"👉 Để đổi mật khẩu mới: `/matkhau <mật khẩu mới>`\n"
                f"👉 Để xóa mật khẩu đã lưu: `/matkhau xoa`",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                "ℹ️ *Chưa lưu mật khẩu mở file sao kê ZIP!*\n\n"
                "Khi tải sao kê từ app ngân hàng (Vietcombank, Techcombank, MBBank...), file tải về thường là .ZIP có mật khẩu (thường là CCCD hoặc Ngày sinh).\n\n"
                "👉 Bạn hãy gõ: `/matkhau <mật khẩu_của_bạn>` (Ví dụ: `/matkhau 0123456789`)\n"
                "Hệ thống sẽ lưu lại để tự động giải nén mọi file ZIP bạn gửi sau này!",
                parse_mode=ParseMode.MARKDOWN
            )
        return

    arg = args[0].strip()
    if arg.lower() in ["xoa", "clear", "delete", "remove"]:
        rules_mgr.set_statement_password("")
        await update.message.reply_text("🗑️ Đã xóa mật khẩu sao kê ZIP đã lưu thành công.", parse_mode=ParseMode.MARKDOWN)
    else:
        rules_mgr.set_statement_password(arg)
        await update.message.reply_text(
            f"🔐 *ĐÃ LƯU MẬT KHẨU SAO KÊ THÀNH CÔNG!*\n\n"
            f"• Mật khẩu giải nén: `{arg}`\n\n"
            "Từ nay, mỗi khi bạn gửi file nén `.ZIP` sao kê từ ứng dụng ngân hàng vào bot, hệ thống sẽ tự động giải nén và nạp giao dịch mà bạn không cần phải giải nén thủ công trên điện thoại nữa!",
            parse_mode=ParseMode.MARKDOWN
        )

async def cmd_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send link to online Google Sheets."""
    url = config.GOOGLE_SHEETS_URL
    if url:
        msg = (
            f"📊 *BẢNG TÍNH GOOGLE SHEETS SỔ QUỸ*\n\n"
            f"🔗 Bấm vào link dưới đây để mở xem trực tiếp trên iPhone/Máy tính:\n"
            f"[👉 Mở Google Sheets Sổ Quỹ]({url})"
        )
    else:
        msg = (
            "ℹ️ *Chưa gắn link Google Sheets trong file .env!*\n\n"
            "Bạn hãy dán link bảng tính vào biến `GOOGLE_SHEETS_URL` trong file `.env` để xem nhanh nhé."
        )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def notify_sheets_error_bot(update: Update):
    """Notify user when Google Sheets fails to save the transaction."""
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
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text transaction input."""
    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        await update.message.reply_text("⛔ Bạn chưa được cấp quyền sử dụng hệ thống này.")
        return

    text = update.message.text.strip()

    # Parse transaction
    parsed = GeminiParser.parse_text(text)
    if not parsed:
        await update.message.reply_text(
            "🤔 Chưa nhận diện được số tiền hoặc nội dung thu chi.\n\n"
            "Bạn hãy nhập theo mẫu:\n"
            "• `+ 500k tram rang` (Thu tiền mặt)\n"
            "• `+ 1.5tr ck khach boc rang` (Thu chuyển khoản)\n"
            "• `- 70k hoa qua thap huong` (Chi tiền mặt)\n"
            "• `- 1.2tr ck labo rang su` (Chi chuyển khoản)\n"
            "• Hoặc bấm giữ biểu tượng Micro để ghi âm giọng nói."
        )
        return

    # Add transaction to Google Sheets
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
        await notify_sheets_error_bot(update)
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
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle receipt photo with Gemini Vision OCR."""
    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        return

    photo = update.message.photo[-1]
    await update.message.reply_text("📸 Đang quét hóa đơn bằng Gemini Vision AI... Vui lòng đợi trong giây lát.")

    try:
        photo_file = await photo.get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        parsed = GeminiParser.parse_receipt_image(bytes(photo_bytes), mime_type="image/jpeg")
        if not parsed:
            await update.message.reply_text("⚠️ Không nhận diện được hóa đơn từ ảnh. Bạn vui lòng chụp lại rõ nét hơn hoặc nhập tay bằng text.")
            return

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
            await notify_sheets_error_bot(update)
            return

        is_thu = parsed.get("type") == "thu"
        sign_text = "🟢 THU VÀO" if is_thu else "🔴 CHI RA"

        msg = (
            f"🧾 *ĐÃ QUÉT VÀ LƯU HÓA ĐƠN #{tx_id}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• Loại: *{sign_text}*\n"
            f"• Số tiền: *{format_vnd(parsed['amount'])}*\n"
            f"• Danh mục: _{parsed['category']}_\n"
            f"• Nội dung: {parsed.get('description', '')}\n"
            f"• Hình thức: {'💵 Tiền mặt' if parsed.get('payment_method') == 'cash' else '💳 Chuyển khoản'}\n"
            f"• Nơi lưu: _Google Sheets Online_\n"
            f"• Nguồn: _Gemini Vision OCR_\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"_(Nhập nhầm? Gõ `/xoa {tx_id}` để xóa)_"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        await update.message.reply_text(f"❌ Lỗi khi đọc ảnh: {e}")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice memo / audio note using Gemini Multimodal Audio."""
    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        return

    voice = update.message.voice or update.message.audio
    if not voice:
        return

    await update.message.reply_text("🎙 Đang lắng nghe và xử lý giọng nói qua Gemini AI... Vui lòng chờ vài giây.")

    try:
        file = await voice.get_file()
        file_bytes = await file.download_as_bytearray()
        mime_type = getattr(voice, "mime_type", "audio/ogg") or "audio/ogg"

        parsed = GeminiParser.parse_voice_audio(bytes(file_bytes), mime_type=mime_type)
        if not parsed:
            await update.message.reply_text(
                "⚠️ Chưa nghe rõ số tiền hoặc nội dung thu chi từ tin nhắn thoại.\n\n"
                "Bạn vui lòng ghi âm lại rõ hơn (VD: *'Thu 500k trám răng tiền mặt'* hoặc *'Chi 70k hoa quả'*), hoặc nhập bằng text nhé."
            )
            return

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
            await notify_sheets_error_bot(update)
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
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error handling voice: {e}")
        await update.message.reply_text(f"❌ Lỗi khi xử lý giọng nói: {e}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bank statement files (.xlsx, .xls, .pdf, .csv, .zip) with Smart Deduplication & Password Unzipping."""
    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        return

    doc = update.message.document
    filename = (doc.file_name or "").lower()
    caption = update.message.caption or ""

    supported_exts = [".xlsx", ".xls", ".pdf", ".csv", ".zip"]
    if not any(filename.endswith(ext) for ext in supported_exts):
        await update.message.reply_text(
            "⚠️ Vui lòng gửi file sao kê từ ngân hàng dạng: Excel (`.xlsx`, `.xls`), PDF (`.pdf`), `.csv` hoặc file nén `.zip`."
        )
        return

    await update.message.reply_text("📑 Đang phân tích sao kê & giải mã đối soát... Vui lòng đợi trong giây lát.")

    try:
        file = await doc.get_file()
        save_path = config.DATA_DIR / f"temp_statement_{doc.file_name}"
        await file.download_to_drive(save_path)

        # Trích xuất mật khẩu từ chú thích hoặc cấu hình đã lưu
        candidate_pwd = extract_password_from_caption(caption)

        # Phân tích file sao kê
        res = BankStatementParser.parse_statement_file(save_path, password=candidate_pwd)
        items = res[0]
        err_code = res[1]
        diag = res[2] if len(res) > 2 else ""

        # Xóa file tạm
        try:
            if save_path.exists():
                os.remove(save_path)
        except Exception:
            pass

        if err_code:
            if err_code == "AES256_ENGINE_MISSING":
                await update.message.reply_text(
                    f"⚙️ *THIẾU ENGINE GIẢI MÃ AES-256!*\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"File sao kê được ngân hàng bảo vệ bằng chuẩn mã hóa AES-256 (Method 99), "
                    f"tuy nhiên module `pyzipper` chưa sẵn sàng trên máy chủ.\n\n"
                    f"🔍 *Chi tiết:* `{diag}`",
                    parse_mode=ParseMode.MARKDOWN
                )
            elif err_code == "BAD_PASSWORD":
                await update.message.reply_text(
                    f"🔒 *MẬT KHẨU GIẢI NÉN KHÔNG ĐÚNG!*\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"Mật khẩu sao kê đã lưu hoặc mật khẩu trong chú thích không mở được file ZIP này.\n\n"
                    f"👉 *Cách xử lý:*\n"
                    f"• Cập nhật lại mật khẩu đúng: `/matkhau <mật khẩu_mới>` (VD: Số CCCD hoặc Ngày sinh)\n"
                    f"• Hoặc gửi lại file ZIP và điền mật khẩu vào ô **Chú thích (Caption)**.\n\n"
                    f"🔍 *Chi tiết chẩn đoán:* `{diag}`",
                    parse_mode=ParseMode.MARKDOWN
                )
            elif err_code == "PASSWORD_REQUIRED":
                await update.message.reply_text(
                    f"🔒 *FILE ZIP ĐƯỢC BẢO VỆ BẰNG MẬT KHẨU!*\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"File sao kê nén từ ứng dụng ngân hàng có đặt mật khẩu bảo vệ.\n\n"
                    f"👉 *Cách xử lý nhanh (chỉ cần làm 1 lần):*\n"
                    f"1. Gõ lệnh: `/matkhau <mật khẩu_của_bạn>` (VD: Số CCCD hoặc Ngày sinh) để lưu sẵn. Lần sau gửi file ZIP bot sẽ tự động mở!\n"
                    f"2. Hoặc gửi lại file ZIP và điền mật khẩu vào ô **Chú thích (Caption)**.\n\n"
                    f"🔍 *Chi tiết chẩn đoán:* `{diag}`",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    f"❌ Không thể phân tích file sao kê (Mã lỗi: `{err_code}`).\n\n🔍 *Chi tiết:* `{diag}`",
                    parse_mode=ParseMode.MARKDOWN
                )
            return

        if not items:
            await update.message.reply_text("⚠️ Không tìm thấy dòng giao dịch hợp lệ nào trong tệp sao kê.")
            return

        # Smart Deduplication against Google Sheets records
        unique_items, duplicate_items = database.reconcile_and_deduplicate(items)

        total_in = 0
        total_out = 0
        for it in unique_items:
            if it["type"] == "thu":
                total_in += it["amount"]
            else:
                total_out += it["amount"]

        # Batch save unique items directly to Google Sheets
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
            "👉 Gõ /excel hoặc /sheet để xem sổ quỹ chi tiết!"
        ])
        await update.message.reply_text("\n".join(msg_lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error handling document: {e}")
        await update.message.reply_text(f"❌ Lỗi khi phân tích file sao kê: {e}")

async def post_init(application: Application):
    """Register command menu in Telegram UI."""
    commands = [
        BotCommand("today", "Xem nhanh thu chi hôm nay"),
        BotCommand("ngay", "Xem thu chi theo ngày (/ngay dd/mm)"),
        BotCommand("khoang", "Xem thu chi theo khoảng ngày"),
        BotCommand("thang", "Xem báo cáo tháng (/thang mm/yyyy)"),
        BotCommand("nam", "Xem báo cáo cả năm (/nam yyyy)"),
        BotCommand("ds", "Xem 10 giao dịch gần nhất"),
        BotCommand("sheet", "Mở Google Sheets Sổ Quỹ trực tuyến"),
        BotCommand("excel", "Tải file Excel về máy"),
        BotCommand("matkhau", "Lưu mật khẩu giải nén file ZIP"),
        BotCommand("xoa", "Xóa giao dịch nhập nhầm (/xoa <id>)"),
        BotCommand("hoc", "Dạy từ khóa mới cho AI"),
        BotCommand("help", "Xem cẩm nang hướng dẫn chi tiết"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Command menu registered successfully.")

def main():
    token = config.TELEGRAM_BOT_TOKEN
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN":
        print("\n" + "="*60)
        print("⚠️ CHƯA CẤU HÌNH TELEGRAM BOT TOKEN!")
        print("="*60 + "\n")
        sys.exit(1)

    print("🚀 Khởi động AutoAccounting Telegram Bot...")
    app = Application.builder().token(token).post_init(post_init).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("ngay", cmd_day))
    app.add_handler(CommandHandler("khoang", cmd_range))
    app.add_handler(CommandHandler("thang", cmd_month))
    app.add_handler(CommandHandler("baocao", cmd_month))
    app.add_handler(CommandHandler("nam", cmd_year))
    app.add_handler(CommandHandler("sheet", cmd_sheet))
    app.add_handler(CommandHandler("link", cmd_sheet))
    app.add_handler(CommandHandler("excel", cmd_excel))
    app.add_handler(CommandHandler("xuat", cmd_excel))
    app.add_handler(CommandHandler("ds", cmd_recent))
    app.add_handler(CommandHandler("xoa", cmd_delete))
    app.add_handler(CommandHandler("hoc", cmd_teach))
    app.add_handler(CommandHandler("rule", cmd_teach))
    app.add_handler(CommandHandler("matkhau", cmd_password))
    app.add_handler(CommandHandler("pass", cmd_password))
    app.add_handler(CommandHandler("id", cmd_id))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("✅ Bot đang lắng nghe tin nhắn...")
    app.run_polling()

if __name__ == "__main__":
    main()
