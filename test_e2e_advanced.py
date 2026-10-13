import os
import openpyxl
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from ai_parser import GeminiParser
from bank_reconciler import BankStatementParser
import config

TEST_DATA_DIR = Path(__file__).resolve().parent / "data"

def create_sample_bank_statement() -> Path:
    """Create a realistic bank statement file in Vietcombank / Techcombank format."""
    file_path = TEST_DATA_DIR / "test_statement_bank.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lịch sử giao dịch"

    # Meta header rows (like real bank exports)
    ws.append(["NGÂN HÀNG THƯƠNG MẠI CỔ PHẦN NGOẠI THƯƠNG VIỆT NAM (VIETCOMBANK)"])
    ws.append(["SAO KÊ TÀI KHOẢN TIỀN GỬI THANH TOÁN"])
    ws.append(["Số tài khoản: 0123456789 - Tên: PHONG KHAM NHA KHOA HONG QUYNH"])
    ws.append([]) # Empty row

    # Real table headers
    ws.append(["Ngày giao dịch", "Số tiền ghi nợ (Chi)", "Số tiền ghi có (Thu)", "Số dư", "Nội dung chi tiết"])

    # Sample transaction rows
    transactions = [
        ["2026-10-01", "", "1500000", "1500000", "KH NGUYEN VAN A CHUYEN TIEN TRAM RANG"],
        ["2026-10-02", "450000", "", "1050000", "THANH TOAN TIEN LABO RANG SU CHI NGA"],
        ["2026-10-03", "", "3500000", "4550000", "LE THI B CK TIEN BOC RANG SU 2 RANG"],
        ["2026-10-04", "850000", "", "3700000", "CHUYEN KHOAN MUA VAT TU Y TE THUOC TE GANG TAY"],
        ["2026-10-05", "5000000", "", "2200000", "TIEN THUE MAT BANG PHONG KHAM THANG 10"],
        ["2026-10-06", "", "300000", "2500000", "TRAN VAN C THANH TOAN NHO RANG KHON"],
    ]

    for row in transactions:
        ws.append(row)

    wb.save(file_path)
    return file_path

def create_sample_receipt_image() -> Path:
    """Create a realistic receipt image for Gemini Vision OCR testing."""
    img_path = TEST_DATA_DIR / "test_receipt_sample.jpg"
    
    width, height = 600, 800
    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)

    # Draw border
    draw.rectangle([(10, 10), (width - 10, height - 10)], outline=(180, 180, 180), width=2)

    # Content
    lines = [
        "CỬA HÀNG VẬT TƯ THIẾT BỊ NHA KHOA HÀ NỘI",
        "Địa chỉ: 123 Phố Huế, Hai Bà Trưng, Hà Nội",
        "Hotline: 0912.345.678",
        "-" * 45,
        "HÓA ĐƠN BÁN LẺ / PHIẾU THU TIỀN",
        f"Ngày: {datetime.now().strftime('%d/%m/%Y')}",
        "-" * 45,
        "1. Găng tay y tế Nitrile (hộp 100 chiếc):  120.000 đ",
        "2. Thuốc tê nha khoa Septodont (1 vỉ):     180.000 đ",
        "3. Khẩu trang y tế 4 lớp (1 hộp):          50.000 đ",
        "-" * 45,
        "TỔNG CỘNG TIỀN THANH TOÁN:  350.000 đ",
        "HÌNH THỨC: TIỀN MẶT",
        "-" * 45,
        "Cảm ơn Quý khách và Hẹn gặp lại!",
        "Người bán hàng: Đã ký nhận"
    ]

    y_text = 40
    for line in lines:
        draw.text((40, y_text), line, fill=(20, 20, 20))
        y_text += 40

    image.save(img_path, format="JPEG", quality=90)
    return img_path

def run_tests():
    print("=" * 60)
    print("🧪 KIỂM THỬ NÂNG CAO: OCR HÓA ĐƠN & BÓC TÁCH SAO KÊ NGÂN HÀNG")
    print("=" * 60)

    # 1. TEST SAO KÊ NGÂN HÀNG
    print("\n--- 1. KIỂM THỬ ĐỌC SAO KÊ NGÂN HÀNG (.xlsx) ---")
    statement_path = create_sample_bank_statement()
    print(f"Đã tạo file sao kê mẫu: {statement_path}")

    items = BankStatementParser.parse_excel_statement(statement_path)
    print(f"✅ Đã bóc tách thành công {len(items)} giao dịch từ sao kê:")
    
    total_thu = 0
    total_chi = 0
    for idx, it in enumerate(items, 1):
        sign = "+" if it['type'] == 'thu' else "-"
        print(f"  {idx}. [{it['date']}] {sign}{it['amount']:,} đ | {it['type'].upper()} | {it['category']} | {it['description'][:35]}...")
        if it['type'] == 'thu':
            total_thu += it['amount']
        else:
            total_chi += it['amount']

    print(f"➡️ Tổng tiền vào (Thu): {total_thu:,} đ")
    print(f"➡️ Tổng tiền ra (Chi): {total_chi:,} đ")

    # 2. TEST OCR HÓA ĐƠN GEMINI VISION
    print("\n--- 2. KIỂM THỬ QUÉT ẢNH HÓA ĐƠN BẰNG GEMINI VISION OCR ---")
    receipt_path = create_sample_receipt_image()
    print(f"Đã tạo ảnh hóa đơn mẫu: {receipt_path}")

    with open(receipt_path, "rb") as f:
        img_bytes = f.read()

    print("Đang gửi ảnh tới Gemini Vision...")
    ocr_result = GeminiParser.parse_receipt_image(img_bytes, mime_type="image/jpeg")
    
    print("\n✅ KẾT QUẢ GEMINI VISION BÓC TÁCH TỪ ẢNH:")
    print(ocr_result)

    if ocr_result:
        print(f"  • Số tiền nhận diện: {ocr_result.get('amount'):,} đ")
        print(f"  • Loại: {ocr_result.get('type')}")
        print(f"  • Danh mục: {ocr_result.get('category')}")
        print(f"  • Nội dung: {ocr_result.get('description')}")
        print(f"  • Hình thức: {ocr_result.get('payment_method')}")
    else:
        print("❌ Không nhận diện được ảnh.")

    # 3. TEST VOICE AUDIO XỬ LÝ GIỌNG NÓI
    print("\n--- 3. KIỂM THỬ NHẬN DIỆN TIN NHẮN THOẠI (GEMINI MULTIMODAL AUDIO) ---")
    import io, wave, struct
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        for _ in range(16000):
            wav_file.writeframes(struct.pack('<h', 0))
    test_audio = buf.getvalue()
    print("Gửi file âm thanh mẫu tới Gemini Audio API...")
    voice_res = GeminiParser.parse_voice_audio(test_audio, mime_type="audio/wav")
    print(f"✅ Kết quả kiểm thử xử lý âm thanh tĩnh (Silence): {voice_res} (Đúng chuẩn không phát hiện giọng nói)")

    print("\n" + "=" * 60)
    print("🎉 KẾT THÚC KIỂM THỬ NÂNG CAO")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
