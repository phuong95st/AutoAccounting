"""
=============================================================================
SUITE KIỂM THỬ TỰ ĐỘNG CHUYÊN NGHIỆP TRƯỚC KHI RELEASE AUTOACCOUNTING v2.0
QA AUTOMATED RELEASE VERIFICATION SUITE
=============================================================================
Bao phủ toàn bộ các tính năng mới của phiên bản v2.0:
1. Đa niên độ Google Sheets (Multi-Year Sheets).
2. Động cơ Chống trùng lặp dữ liệu thông minh (Deduplication Engine).
3. Bộ lệnh truy vấn mở rộng (/ngay, /khoang, /thang, /nam).
4. Phân giải ngày tháng linh hoạt (parse_user_date, parse_user_month, parse_vn_date).
5. Xử lý tin nhắn thoại, ảnh hóa đơn, sao kê ngân hàng.
6. Giả lập kiểm thử End-to-End Vercel Webhook và Telegram Bot.
"""

import sys
import io
import json
import unittest
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import config
import database
from ai_parser import GeminiParser, RuleEngine, rules_mgr, remove_accents
from bank_reconciler import BankStatementParser, ReportGenerator
import api.webhook as webhook_mod

TZ_VN = timezone(timedelta(hours=7))

class TestAutoAccountingV2Release(unittest.TestCase):

    # =========================================================================
    # MODULE 1: KIỂM THỬ XỬ LÝ & CHUẨN HÓA NGÀY THÁNG (DATE & TIME PARSING)
    # =========================================================================
    def test_01_parse_user_date_formats(self):
        """Kiểm thử phân tích các định dạng ngày người dùng nhập vào."""
        now_vn = datetime.now(TZ_VN)
        current_year = now_vn.year

        # DD/MM (mặc định năm hiện tại)
        self.assertEqual(database.parse_user_date("13/10"), f"{current_year:04d}-10-13")
        self.assertEqual(database.parse_user_date("05/02"), f"{current_year:04d}-02-05")
        self.assertEqual(database.parse_user_date("1-5"), f"{current_year:04d}-05-01")

        # DD/MM/YYYY
        self.assertEqual(database.parse_user_date("13/10/2026"), "2026-10-13")
        self.assertEqual(database.parse_user_date("01-01-2025"), "2025-01-01")

        # YYYY-MM-DD
        self.assertEqual(database.parse_user_date("2026-10-14"), "2026-10-14")
        self.assertEqual(database.parse_user_date("2025/12/31"), "2025-12-31")

        # Từ khóa ngôn ngữ tự nhiên
        today_str = now_vn.strftime("%Y-%m-%d")
        yesterday_str = (now_vn - timedelta(days=1)).strftime("%Y-%m-%d")
        self.assertEqual(database.parse_user_date("today"), today_str)
        self.assertEqual(database.parse_user_date("hôm nay"), today_str)
        self.assertEqual(database.parse_user_date("yesterday"), yesterday_str)
        self.assertEqual(database.parse_user_date("hôm qua"), yesterday_str)

        # Định dạng không hợp lệ
        self.assertIsNone(database.parse_user_date("abc/xyz"))
        self.assertIsNone(database.parse_user_date(""))
        self.assertIsNone(database.parse_user_date(None))

    def test_02_parse_user_month_formats(self):
        """Kiểm thử phân tích cú pháp tháng người dùng nhập vào."""
        now_vn = datetime.now(TZ_VN)
        current_year = now_vn.year

        # Chỉ có số tháng (1-12)
        self.assertEqual(database.parse_user_month("9"), (current_year, 9))
        self.assertEqual(database.parse_user_month("10"), (current_year, 10))
        self.assertEqual(database.parse_user_month("tháng 12"), (current_year, 12))
        self.assertEqual(database.parse_user_month("thang 08"), (current_year, 8))

        # MM/YYYY
        self.assertEqual(database.parse_user_month("10/2026"), (2026, 10))
        self.assertEqual(database.parse_user_month("05-2025"), (2025, 5))

        # YYYY-MM
        self.assertEqual(database.parse_user_month("2026-10"), (2026, 10))

        # Tháng không hợp lệ
        self.assertIsNone(database.parse_user_month("15"))
        self.assertIsNone(database.parse_user_month("xyz"))
        self.assertIsNone(database.parse_user_month(""))

    def test_03_utc_to_vn_date_normalization(self):
        """Kiểm thử chuẩn hóa múi giờ UTC ISO của Google Apps Script sang giờ Việt Nam."""
        # 17:00 UTC của ngày 13/10 chính là 00:00 ngày 14/10 theo GMT+7
        utc_iso = "2026-10-13T17:00:00.000Z"
        vn_date = database.parse_vn_date(utc_iso)
        self.assertEqual(vn_date, "2026-10-14")

    # =========================================================================
    # MODULE 2: ĐỘNG CƠ CHỐNG TRÙNG LẶP DỮ LIỆU (SMART DEDUPLICATION ENGINE)
    # =========================================================================
    def test_04_deduplication_exact_reimport(self):
        """Kiểm thử phát hiện trùng lặp khi import lại file sao kê đã nhập."""
        existing = [
            {
                "id": 1,
                "date": "2026-10-10",
                "type": "thu",
                "amount": 2000000,
                "payment_method": "transfer",
                "category": "Doanh thu Dịch vụ",
                "description": "KH NGUYEN VAN A CHUYEN TIEN",
                "source": "bank_statement"
            }
        ]

        incoming = [
            {
                "date": "2026-10-10",
                "type": "thu",
                "amount": 2000000,
                "payment_method": "transfer",
                "category": "Doanh thu Dịch vụ",
                "description": "KH NGUYEN VAN A CHUYEN TIEN",
                "source": "bank_statement"
            }
        ]

        unique, dups = database.reconcile_and_deduplicate(incoming, existing)
        self.assertEqual(len(unique), 0, "Bản ghi sao kê đã nhập phải bị loại bỏ")
        self.assertEqual(len(dups), 1, "Phải ghi nhận 1 bản ghi trùng")

    def test_05_deduplication_voice_vs_bank_statement(self):
        """
        Kiểm thử kịch bản thực tế của phòng khám nha khoa:
        Bác sĩ nói vào bot: 'Thu chị Quỳnh 500k khám răng' (chuyển khoản).
        Cuối tháng ngân hàng xuất sao kê: 'NGUYEN THI QUYNH chuyen tien kham rang'.
        Hệ thống phải tự nhận diện là TRÙNG và bỏ qua!
        """
        existing = [
            {
                "id": 12,
                "date": "2026-10-13",
                "type": "thu",
                "amount": 500000,
                "payment_method": "transfer",
                "category": "Doanh thu Dịch vụ",
                "description": "Thu chị Quỳnh 500.000 tiền khám răng",
                "source": "voice"
            }
        ]

        incoming = [
            {
                "date": "2026-10-13",
                "type": "thu",
                "amount": 500000,
                "payment_method": "transfer",
                "category": "Doanh thu Dịch vụ",
                "description": "NGUYEN THI QUYNH chuyen tien kham rang 131026",
                "source": "bank_statement"
            },
            {
                "date": "2026-10-14",
                "type": "thu",
                "amount": 1200000,
                "payment_method": "transfer",
                "category": "Doanh thu Dịch vụ",
                "description": "TRAN THI MAI CK TRAM RANG",
                "source": "bank_statement"
            }
        ]

        unique, dups = database.reconcile_and_deduplicate(incoming, existing)
        self.assertEqual(len(unique), 1, "Chỉ có 1 giao dịch mới (Trần Thị Mai)")
        self.assertEqual(unique[0]["amount"], 1200000)
        self.assertEqual(len(dups), 1, "Giao dịch chị Quỳnh phải bị bắt trùng")
        self.assertEqual(dups[0]["matched_existing"]["id"], 12)
        self.assertIn("quynh", dups[0]["reason"].lower())

    def test_06_deduplication_cash_never_matched_to_bank(self):
        """
        Kiểm thử quy tắc nghiệp vụ:
        Khách thanh toán TIỀN MẶT 500k thì KHÔNG BAO GIỜ bị nhận nhầm
        thành trùng lặp với giao dịch chuyển khoản trên sao kê ngân hàng.
        """
        existing = [
            {
                "id": 20,
                "date": "2026-10-13",
                "type": "thu",
                "amount": 500000,
                "payment_method": "cash", # Tiền mặt
                "category": "Doanh thu Dịch vụ",
                "description": "Khách tiền mặt khám răng",
                "source": "telegram"
            }
        ]

        incoming = [
            {
                "date": "2026-10-13",
                "type": "thu",
                "amount": 500000,
                "payment_method": "transfer",
                "category": "Doanh thu Dịch vụ",
                "description": "VU THI HOA CHUYEN KHOAN TRAM RANG",
                "source": "bank_statement"
            }
        ]

        unique, dups = database.reconcile_and_deduplicate(incoming, existing)
        self.assertEqual(len(unique), 1, "Tiền mặt không được coi là trùng với chuyển khoản sao kê")
        self.assertEqual(len(dups), 0)

    def test_07_deduplication_different_amount_or_type(self):
        """Kiểm thử khác số tiền hoặc khác loại thu/chi không bị bắt trùng."""
        existing = [
            {
                "id": 30,
                "date": "2026-10-13",
                "type": "chi", # Chi tiền
                "amount": 500000,
                "payment_method": "transfer",
                "category": "Chi phí",
                "description": "Trả tiền labo",
                "source": "telegram"
            }
        ]

        incoming = [
            {
                "date": "2026-10-13",
                "type": "thu", # Tiền vào
                "amount": 500000,
                "payment_method": "transfer",
                "category": "Doanh thu Dịch vụ",
                "description": "KH THANH TOAN TRAM RANG",
                "source": "bank_statement"
            }
        ]

        unique, dups = database.reconcile_and_deduplicate(incoming, existing)
        self.assertEqual(len(unique), 1)
        self.assertEqual(len(dups), 0)

    # =========================================================================
    # MODULE 3: TRUY VẤN TÀI CHÍNH ĐA CHIỀU (/ngay, /khoang, /thang, /nam)
    # =========================================================================
    def test_08_financial_queries_data_structure(self):
        """Kiểm thử cấu trúc trả về của các hàm truy vấn mở rộng."""
        # 1. Date summary
        day_res = database.get_date_summary("2026-10-13")
        self.assertIn("total_thu", day_res)
        self.assertIn("total_chi", day_res)
        self.assertIn("balance", day_res)
        self.assertIn("items", day_res)

        # 2. Range summary
        range_res = database.get_range_summary("2026-10-01", "2026-10-14")
        self.assertIn("total_thu", range_res)
        self.assertIn("total_chi", range_res)
        self.assertIn("balance", range_res)
        self.assertIn("categories_chi", range_res)
        self.assertIn("categories_thu", range_res)

        # 3. Month summary
        month_res = database.get_month_summary(2026, 10)
        self.assertIn("total_thu", month_res)
        self.assertIn("total_chi", month_res)
        self.assertIn("balance", month_res)

        # 4. Year summary
        year_res = database.get_year_summary(2026)
        self.assertIn("total_thu", year_res)
        self.assertIn("total_chi", year_res)
        self.assertIn("balance", year_res)
        self.assertIn("monthly_stats", year_res)
        self.assertEqual(len(year_res["monthly_stats"]), 12, "Báo cáo năm phải có đầy đủ 12 tháng")

    # =========================================================================
    # MODULE 4: VERCEL SERVERLESS WEBHOOK & TELEGRAM ENDPOINT SIMULATION
    # =========================================================================
    def test_09_wsgi_application_entrypoint(self):
        """Kiểm thử chuẩn WSGI application của Vercel."""
        # 1. GET / -> 200 OK Live message
        status_lines = []
        headers_list = []
        def start_response(status, headers):
            status_lines.append(status)
            headers_list.append(headers)

        environ_get = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/api/webhook",
            "wsgi.input": io.BytesIO()
        }
        resp = webhook_mod.application(environ_get, start_response)
        self.assertIn("200 OK", status_lines[0])
        self.assertIn("AutoAccounting Webhook is live", resp[0].decode("utf-8"))

        # 2. GET /favicon.ico -> 204 No Content
        status_lines.clear()
        environ_fav = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/favicon.ico",
            "wsgi.input": io.BytesIO()
        }
        resp_fav = webhook_mod.application(environ_fav, start_response)
        self.assertIn("204 No Content", status_lines[0])

    def test_10_webhook_telegram_commands_dispatch(self):
        """Kiểm thử bộ điều phối lệnh (command dispatcher) trong webhook."""
        sent_messages = []
        original_send = webhook_mod.send_telegram_message
        test_user_id = config.ALLOWED_TELEGRAM_USERS[0] if config.ALLOWED_TELEGRAM_USERS else 123456789
        unauth_user_id = 999999999
        try:
            webhook_mod.send_telegram_message = lambda cid, text, pm="Markdown": sent_messages.append({"chat_id": cid, "text": text})

            # Test /help command with authorized user
            update_help = {
                "message": {
                    "from": {"id": test_user_id, "first_name": "Dr. Phuong"},
                    "chat": {"id": test_user_id},
                    "text": "/help"
                }
            }
            webhook_mod.process_telegram_update(update_help)
            self.assertTrue(len(sent_messages) > 0)
            self.assertIn("CẨM NANG HƯỚNG DẪN", sent_messages[-1]["text"])

            # Test /id command with unauthorized user (should return user id info)
            sent_messages.clear()
            update_unauth_id = {
                "message": {
                    "from": {"id": unauth_user_id, "first_name": "New Assistant"},
                    "chat": {"id": unauth_user_id},
                    "text": "/id"
                }
            }
            webhook_mod.process_telegram_update(update_unauth_id)
            self.assertIn(str(unauth_user_id), sent_messages[-1]["text"])

            # Test /nam 2026 command
            sent_messages.clear()
            update_nam = {
                "message": {
                    "from": {"id": test_user_id, "first_name": "Dr. Phuong"},
                    "chat": {"id": test_user_id},
                    "text": "/nam 2026"
                }
            }
            webhook_mod.process_telegram_update(update_nam)
            self.assertIn("BÁO CÁO TÀI CHÍNH NĂM 2026", sent_messages[-1]["text"])

            # Test /ngay 13/10 command
            sent_messages.clear()
            update_ngay = {
                "message": {
                    "from": {"id": test_user_id, "first_name": "Dr. Phuong"},
                    "chat": {"id": test_user_id},
                    "text": "/ngay 13/10"
                }
            }
            webhook_mod.process_telegram_update(update_ngay)
            self.assertIn("BÁO CÁO THU CHI NGÀY 13/10", sent_messages[-1]["text"])

            # Test /khoang 01/10 14/10 command
            sent_messages.clear()
            update_khoang = {
                "message": {
                    "from": {"id": test_user_id, "first_name": "Dr. Phuong"},
                    "chat": {"id": test_user_id},
                    "text": "/khoang 01/10 14/10"
                }
            }
            webhook_mod.process_telegram_update(update_khoang)
            self.assertIn("BÁO CÁO TÀI CHÍNH TỪ 01/10", sent_messages[-1]["text"])

        finally:
            webhook_mod.send_telegram_message = original_send

    # =========================================================================
    # MODULE 5: KẾT NỐI GOOGLE SHEETS TRỰC TUYẾN & ĐỊNH DẠNG FILE MỞ RỘNG (ZIP/XLS/PDF)
    # =========================================================================
    def test_11_live_google_sheets_connection(self):
        """Kiểm thử tính khả dụng và phản hồi trực tiếp từ Webhook Google Sheets."""
        self.assertTrue(bool(config.GOOGLE_SHEETS_WEBHOOK_URL), "GOOGLE_SHEETS_WEBHOOK_URL phải được cấu hình")
        res = database._call_sheets_api(params={"action": "ping"})
        self.assertIsNotNone(res, "Google Sheets Webhook phải phản hồi")
        self.assertEqual(res.get("status"), "ok")

    def test_12_encrypted_zip_and_statement_formats(self):
        """Kiểm thử giải nén file ZIP ngân hàng có mật khẩu và lệnh /matkhau."""
        import pyzipper
        from bank_reconciler import BankStatementParser

        original_pwd = rules_mgr.get_statement_password()
        try:
            # 1. Test set/get password in rules_mgr
            rules_mgr.set_statement_password("testpass123")
            self.assertEqual(rules_mgr.get_statement_password(), "testpass123")

            # 2. Tạo một file zip có mật khẩu AES-256 chứa 1 file csv giao dịch giả lập
            sample_csv_content = (
                "Ngay,SoTien,NoiDung\n"
                "13/10/2026,1500000,Khach Hang Nguyen Van A CK lam rang\n"
            ).encode("utf-8")

            zip_path = BASE_DIR / "test_encrypted.zip"
            with pyzipper.AESZipFile(
                zip_path,
                "w",
                compression=pyzipper.ZIP_DEFLATED,
                encryption=pyzipper.WZ_AES
            ) as zf:
                zf.setpassword(b"testpass123")
                zf.writestr("statement.csv", sample_csv_content)

            extracted_files = []
            try:
                # Test giải nén với mật khẩu đúng (tự lấy từ rules_mgr)
                extracted_files, err, *_ = BankStatementParser.extract_zip_archive(zip_path, password=None)
                self.assertIsNone(err)
                self.assertTrue(len(extracted_files) > 0)
                self.assertTrue(any(f.name.endswith(".csv") for f in extracted_files))

                # Test parse_statement_file trên file zip
                txs, err, *_ = BankStatementParser.parse_statement_file(zip_path, password="testpass123")
                self.assertIsNone(err)
                self.assertEqual(len(txs), 1)
                self.assertEqual(txs[0]["amount"], 1500000)
                self.assertIn("lam rang", txs[0]["description"])
            finally:
                # Dọn dẹp
                if zip_path.exists():
                    zip_path.unlink()
                for f in extracted_files:
                    if f.exists():
                        f.unlink()

            # 3. Test xóa mật khẩu
            rules_mgr.set_statement_password("")
            self.assertEqual(rules_mgr.get_statement_password(), "")
        finally:
            rules_mgr.set_statement_password(original_pwd)

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("🚀 BẮT ĐẦU CHẠY SUITE KIỂM THỬ TỔNG THỂ CHO BẢN PHÁT HÀNH v2.0")
    print("=" * 70 + "\n")
    unittest.main(verbosity=2)
