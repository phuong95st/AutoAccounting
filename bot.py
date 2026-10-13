import os
import sys
import logging
from datetime import datetime
from pathlib import Path
from telegram import Update
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
        "💡 *CÁCH SỬ DỤNG NHANH HÀNG NGÀY:*\n"
        "Nhập dòng tiền cực nhanh trong 3 giây:\n"
        "• `+ 500k khach tram rang` ➡️ Thu tiền mặt\n"
        "• `+ 2tr ck khach Trang boc rang su` ➡️ Khách chuyển khoản\n"
        "• `- 70k hoa qua thap huong` ➡️ Chi tiền mặt mua hoa quả\n"
        "• `- 1.2tr labo rang su chi Nga` ➡️ Chi tiền làm labo\n"
        "• Chụp ảnh hóa đơn/phiếu thu gửi vào đây để AI đọc tự động.\n\n"
        "📌 *CÁC LỆNH BÁO CÁO & QUẢN LÝ:*\n"
        "• /today hoặc /ngay : Tổng kết thu chi hôm nay\n"
        "• /thang hoặc /baocao : Báo cáo doanh thu & chi phí tháng\n"
        "• /excel : Xuất file Excel báo cáo hoàn chỉnh gửi về máy\n"
        "• /ds : Xem 10 giao dịch gần nhất\n"
        "• /xoa `<id>` : Xóa giao dịch nếu nhập nhầm (VD: `/xoa 5`)\n"
        "• /hoc `<từ khóa> = <thu/chi>: <danh mục>` : Dạy quy tắc mới cho AI\n\n"
        "📥 *CUỐI THÁNG:* Bạn chỉ cần gửi file Excel sao kê ngân hàng vào đây, hệ thống sẽ tự động đối soát và phân loại!"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View today's financial summary."""
    s = database.get_today_summary()
    date_str = datetime.now().strftime("%d/%m/%Y")
    
    profit_symbol = "🟢" if s["balance"] >= 0 else "🔴"
    msg = (
        f"📊 *BÁO CÁO THU CHI HÔM NAY ({date_str})*\n\n"
        f"🟢 *TỔNG THU:* `{format_vnd(s['total_thu'])}`\n"
        f"  • Tiền mặt: `{format_vnd(s['thu_cash'])}`\n"
        f"  • Chuyển khoản: `{format_vnd(s['thu_transfer'])}`\n\n"
        f"🔴 *TỔNG CHI:* `{format_vnd(s['total_chi'])}`\n"
        f"  • Tiền mặt: `{format_vnd(s['chi_cash'])}`\n"
        f"  • Chuyển khoản: `{format_vnd(s['chi_transfer'])}`\n\n"
        f"{profit_symbol} *CHÊNH LỆCH TRONG NGÀY:* `{format_vnd(s['balance'])}`\n"
        f"📝 Tổng số giao dịch: {s['count']}"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def cmd_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View current month summary."""
    now = datetime.now()
    s = database.get_month_summary(now.year, now.month)
    
    profit_symbol = "🟢" if s["balance"] >= 0 else "🔴"
    msg_lines = [
        f"📈 *BÁO CÁO TÀI CHÍNH THÁNG {now.month:02d}/{now.year}*\n",
        f"🟢 *TỔNG THU:* `{format_vnd(s['total_thu'])}`",
        f"  • Tiền mặt: `{format_vnd(s['thu_cash'])}`",
        f"  • Chuyển khoản: `{format_vnd(s['thu_transfer'])}`\n",
        f"🔴 *TỔNG CHI:* `{format_vnd(s['total_chi'])}`",
        f"  • Tiền mặt: `{format_vnd(s['chi_cash'])}`",
        f"  • Chuyển khoản: `{format_vnd(s['chi_transfer'])}`\n",
        f"{profit_symbol} *LỢI NHUẬN RÒNG:* `{format_vnd(s['balance'])}`\n",
        "📂 *CƠ CẤU CHI PHÍ NỔI BẬT:*"
    ]

    if s["categories_chi"]:
        for c in s["categories_chi"][:5]:
            msg_lines.append(f"  • {c['category']}: `{format_vnd(c['total'])}` ({c['count']} lần)")
    else:
        msg_lines.append("  _(Chưa có chi phí nào)_")

    msg_lines.append("\n👉 Gõ /excel để tải file báo cáo Excel chi tiết.")
    await update.message.reply_text("\n".join(msg_lines), parse_mode=ParseMode.MARKDOWN)

async def cmd_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export and send Excel report."""
    now = datetime.now()
    await update.message.reply_text("⏳ Đang khởi tạo file Excel báo cáo tháng... Vui lòng đợi trong giây lát.")
    try:
        report_path = ReportGenerator.generate_monthly_excel(now.year, now.month)
        with open(report_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=report_path.name,
                caption=f"📊 Báo cáo Thu Chi Phòng Khám Nha Khoa Tháng {now.month:02d}/{now.year}."
            )
    except Exception as e:
        logger.error(f"Error exporting Excel: {e}")
        await update.message.reply_text(f"❌ Có lỗi khi tạo file Excel: {e}")

async def cmd_recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View recent transactions."""
    txs = database.get_recent_transactions(limit=10)
    if not txs:
        await update.message.reply_text("Chưa có giao dịch nào được ghi nhận.")
        return

    lines = ["📋 *10 GIAO DỊCH GẦN NHẤT:*\n"]
    for t in txs:
        sign = "🟢 +" if t["type"] == "thu" else "🔴 -"
        method = "💵" if t["payment_method"] == "cash" else "💳"
        lines.append(
            f"`#{t['id']}` | {t['date'][5:]} | {sign}{format_vnd(t['amount'])} {method}\n"
            f"   ↳ _{t['category']}_: {t['description'] or ''}"
        )
    lines.append("\n_Gõ `/xoa <id>` để xóa nếu có giao dịch nhập nhầm._")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a transaction by ID."""
    if not context.args:
        await update.message.reply_text("⚠️ Cú pháp: `/xoa <id>` (Ví dụ: `/xoa 15`)", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        tx_id = int(context.args[0])
        tx = database.get_transaction(tx_id)
        if not tx:
            await update.message.reply_text(f"❌ Không tìm thấy giao dịch với ID #{tx_id}.")
            return

        success = database.delete_transaction(tx_id)
        if success:
            sign = "Thu" if tx["type"] == "thu" else "Chi"
            await update.message.reply_text(
                f"🗑️ Đã xóa giao dịch `#{tx_id}`: {sign} {format_vnd(tx['amount'])} ({tx['description']}).",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("❌ Không thể xóa giao dịch.")
    except ValueError:
        await update.message.reply_text("⚠️ ID phải là chữ số. Ví dụ: `/xoa 12`", parse_mode=ParseMode.MARKDOWN)

async def cmd_teach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Teach new rule/keyword to the bot."""
    # Syntax: /hoc [keyword] = [thu/chi]: [category]
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

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input from user (e.g. '+ 500k tram rang', '- 70k hoa qua')."""
    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        return

    text = update.message.text.strip()
    if not text:
        return

    parsed = GeminiParser.parse_text(text)
    if not parsed:
        await update.message.reply_text(
            "🤔 Chưa nhận diện được số tiền hoặc nội dung thu chi.\n\n"
            "Bạn hãy nhập theo mẫu:\n"
            "• `+ 500k tram rang` (Thu tiền mặt)\n"
            "• `+ 1.5tr ck khach boc rang` (Thu chuyển khoản)\n"
            "• `- 70k hoa qua thap huong` (Chi tiền mặt)\n"
            "• `- 1.2tr ck labo rang su` (Chi chuyển khoản)"
        )
        return

    # Save to database
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
    engine_badge = "🤖 Gemini AI" if parsed.get("engine") == "gemini-ai" else "⚡ Rule Engine (Quy tắc)"

    msg = (
        f"✅ *ĐÃ GHI NHẬN GIAO DỊCH #{tx_id}*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• Loại: *{sign_text}*\n"
        f"• Số tiền: *{format_vnd(parsed['amount'])}*\n"
        f"• Danh mục: _{parsed['category']}_\n"
        f"• Nội dung: {parsed.get('description', '')}\n"
        f"• Hình thức: {method_text}\n"
        f"• Xử lý: _{engine_badge}_\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"_(Nhập nhầm? Gõ `/xoa {tx_id}` để xóa)_"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo (receipt / invoice OCR)."""
    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        return

    await update.message.reply_text("📸 Đang quét hóa đơn bằng Gemini Vision... Vui lòng chờ vài giây.")

    try:
        photo = update.message.photo[-1]  # Highest resolution
        file = await photo.get_file()
        file_bytes = await file.download_as_bytearray()

        parsed = GeminiParser.parse_receipt_image(bytes(file_bytes), mime_type="image/jpeg")
        if not parsed:
            await update.message.reply_text("⚠️ Không nhận diện được thông tin hóa đơn từ ảnh. Bạn vui lòng chụp rõ nét hơn hoặc nhập tay bằng text.")
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

        msg = (
            f"🧾 *ĐÃ QUÉT VÀ LƯU HÓA ĐƠN #{tx_id}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• Số tiền: *{format_vnd(parsed['amount'])}*\n"
            f"• Danh mục: _{parsed['category']}_\n"
            f"• Nội dung: {parsed.get('description', '')}\n"
            f"• Hình thức: {'💵 Tiền mặt' if parsed.get('payment_method') == 'cash' else '💳 Chuyển khoản'}\n"
            f"• Nguồn: _Gemini Vision OCR_\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"_(Nhập nhầm? Gõ `/xoa {tx_id}` để xóa)_"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        await update.message.reply_text(f"❌ Lỗi khi đọc ảnh: {e}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bank statement files (.xlsx, .xls, .csv)."""
    user_id = update.effective_user.id
    if not is_user_allowed(user_id):
        return

    doc = update.message.document
    filename = (doc.file_name or "").lower()

    if not (filename.endswith(".xlsx") or filename.endswith(".xls") or filename.endswith(".csv")):
        await update.message.reply_text("⚠️ Vui lòng gửi file sao kê dạng Excel (.xlsx, .xls) hoặc .csv từ ngân hàng.")
        return

    await update.message.reply_text("📑 Đang phân tích sao kê ngân hàng... Vui lòng đợi trong giây lát.")

    try:
        file = await doc.get_file()
        save_path = config.DATA_DIR / f"temp_statement_{doc.file_name}"
        await file.download_to_drive(save_path)

        # Parse statement
        items = BankStatementParser.parse_excel_statement(save_path)
        if not items:
            await update.message.reply_text("⚠️ Không tìm thấy dòng giao dịch hợp lệ nào trong file sao kê.")
            return

        total_in = 0
        total_out = 0
        saved_count = 0

        for it in items:
            database.add_transaction(
                tx_type=it["type"],
                amount=it["amount"],
                category=it["category"],
                description=it["description"],
                payment_method="transfer",
                source="bank_statement",
                user_id=user_id,
                tx_date=it["date"] if it.get("date") else None
            )
            saved_count += 1
            if it["type"] == "thu":
                total_in += it["amount"]
            else:
                total_out += it["amount"]

        # Clean up temporary file
        try:
            os.remove(save_path)
        except:
            pass

        msg = (
            f"🎉 *ĐÃ ĐỐI SOÁT & NHẬP SAO KÊ THÀNH CÔNG!*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• Số giao dịch đã nhập: *{saved_count}*\n"
            f"• 🟢 Tổng tiền vào (Thu): *{format_vnd(total_in)}*\n"
            f"• 🔴 Tổng tiền ra (Chi): *{format_vnd(total_out)}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👉 Gõ /excel để tải ngay báo cáo tổng hợp mới nhất!"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error handling document: {e}")
        await update.message.reply_text(f"❌ Lỗi khi phân tích file sao kê: {e}")

def main():
    token = config.TELEGRAM_BOT_TOKEN
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN":
        print("\n" + "="*60)
        print("⚠️ CHƯA CẤU HÌNH TELEGRAM BOT TOKEN!")
        print("Vui lòng mở file .env và điền TELEGRAM_BOT_TOKEN vào.")
        print("Cách lấy token miễn phí chỉ mất 1 phút:")
        print("1. Mở Telegram, tìm @BotFather")
        print("2. Gõ lệnh /newbot và làm theo hướng dẫn")
        print("3. Copy chuỗi Token nhận được dán vào file .env")
        print("="*60 + "\n")
        sys.exit(1)

    print("🚀 Khởi động AutoAccounting Telegram Bot...")
    app = Application.builder().token(token).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("ngay", cmd_today))
    app.add_handler(CommandHandler("thang", cmd_month))
    app.add_handler(CommandHandler("baocao", cmd_month))
    app.add_handler(CommandHandler("excel", cmd_excel))
    app.add_handler(CommandHandler("xuat", cmd_excel))
    app.add_handler(CommandHandler("ds", cmd_recent))
    app.add_handler(CommandHandler("xoa", cmd_delete))
    app.add_handler(CommandHandler("hoc", cmd_teach))
    app.add_handler(CommandHandler("rule", cmd_teach))

    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("✅ Bot đang lắng nghe tin nhắn...")
    app.run_polling()

if __name__ == "__main__":
    main()
