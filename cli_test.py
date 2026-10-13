"""
CLI Testing Tool for AutoAccounting
Cho phép bạn thử nghiệm nhanh tính năng ghi sổ, phân loại AI/Rule, xem báo cáo và xuất Excel
ngay trên máy tính mà không cần chờ cấu hình Telegram Bot.
"""

import sys
from datetime import datetime
import database
from ai_parser import GeminiParser, RuleEngine, rules_mgr
from bank_reconciler import ReportGenerator

def print_help():
    print("""
=====================================================
🏥 HỆ THỐNG QUẢN LÝ THU CHI PHÒNG KHÁM NHA KHOA
=====================================================
Nhập một trong các lệnh sau:
  • <text>      : Nhập giao dịch (Ví dụ: '- 70k hoa qua thap huong', '+ 500k khach nho rang')
  • /today      : Xem tổng kết hôm nay
  • /month      : Xem tổng kết tháng này
  • /excel      : Xuất file Excel báo cáo hoàn chỉnh
  • /ds         : Xem 10 giao dịch gần nhất
  • /hoc <kw> = <thu/chi>: <danhmuc> : Dạy từ khóa mới
  • /help       : Hiện bảng hướng dẫn này
  • exit / q    : Thoát chương trình
=====================================================
""")

def main():
    print_help()
    while True:
        try:
            line = input("\n[AutoAccounting] > ").strip()
            if not line:
                continue

            if line.lower() in ["exit", "quit", "q"]:
                print("Tạm biệt!")
                break

            if line == "/help":
                print_help()
            elif line == "/today":
                s = database.get_today_summary()
                print(f"\n--- BÁO CÁO HÔM NAY ({s['date']}) ---")
                print(f"🟢 Tổng Thu: {s['total_thu']:,} đ (TM: {s['thu_cash']:,} đ | CK: {s['thu_transfer']:,} đ)")
                print(f"🔴 Tổng Chi: {s['total_chi']:,} đ (TM: {s['chi_cash']:,} đ | CK: {s['chi_transfer']:,} đ)")
                print(f"💰 Chênh lệch: {s['balance']:,} đ ({s['count']} giao dịch)")
            elif line == "/month":
                now = datetime.now()
                s = database.get_month_summary(now.year, now.month)
                print(f"\n--- BÁO CÁO THÁNG {now.month:02d}/{now.year} ---")
                print(f"🟢 Tổng Thu: {s['total_thu']:,} đ")
                print(f"🔴 Tổng Chi: {s['total_chi']:,} đ")
                print(f"💰 Lợi nhuận ròng: {s['balance']:,} đ")
                print("Cơ cấu chi phí:")
                for c in s["categories_chi"]:
                    print(f"  • {c['category']}: {c['total']:,} đ ({c['count']} lần)")
            elif line == "/excel":
                now = datetime.now()
                p = database.download_online_excel() or ReportGenerator.generate_monthly_excel(now.year, now.month)
                print(f"✅ Đã tải/tạo file Excel thành công tại: {p}")

            elif line == "/ds":
                txs = database.get_recent_transactions(10)
                print("\n--- 10 GIAO DỊCH GẦN NHẤT ---")
                for t in txs:
                    sign = "+" if t["type"] == "thu" else "-"
                    print(f"#{t['id']} | {t['date']} | {sign}{t['amount']:,} đ [{t['payment_method']}] | {t['category']} | {t['description']}")
            elif line.startswith("/hoc "):
                raw = line[5:].strip()
                if "=" in raw and ":" in raw:
                    kw, rest = raw.split("=", 1)
                    t_type, cat = rest.split(":", 1)
                    rules_mgr.teach(kw.strip(), t_type.strip(), cat.strip())
                    print(f"✅ Đã học: Từ khóa '{kw.strip()}' -> Loại: {t_type.strip()}, Danh mục: '{cat.strip()}'")
                else:
                    print("Cú pháp: /hoc <từ khóa> = <thu/chi>: <danh mục>")
            else:
                # Parse transaction
                parsed = GeminiParser.parse_text(line)
                if not parsed:
                    print("❌ Không nhận diện được giao dịch. Vui lòng thử lại!")
                    continue

                tx_id = database.add_transaction(
                    tx_type=parsed["type"],
                    amount=parsed["amount"],
                    category=parsed["category"],
                    description=parsed.get("description", ""),
                    payment_method=parsed.get("payment_method", "cash"),
                    source="cli"
                )
                sign = "THU" if parsed["type"] == "thu" else "CHI"
                print(f"✅ Đã ghi nhận [ID #{tx_id}]:")
                print(f"   • Loại: {sign}")
                print(f"   • Số tiền: {parsed['amount']:,} đ")
                print(f"   • Danh mục: {parsed['category']}")
                print(f"   • Nội dung: {parsed.get('description', '')}")
                print(f"   • Hình thức: {parsed.get('payment_method')}")
                print(f"   • Động cơ xử lý: {parsed.get('engine')}")

        except (KeyboardInterrupt, EOFError):
            print("\nĐã thoát.")
            break
        except Exception as e:
            print(f"Lỗi: {e}")

if __name__ == "__main__":
    main()
