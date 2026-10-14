import re
import csv
import zipfile
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

try:
    import xlrd
except ImportError:
    xlrd = None

try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import pyzipper
except ImportError:
    pyzipper = None

import config
import database
from ai_parser import GeminiParser, RuleEngine, rules_mgr, remove_accents
from config import REPORTS_DIR, DATA_DIR

def clean_statement_num(v: Any) -> int:
    """Chuyển đổi số tiền trong sao kê sang số nguyên dương."""
    if not v:
        return 0
    if isinstance(v, (int, float)):
        return int(abs(v))
    s = str(v).replace(',', '').replace('.', '').replace('VND', '').replace('đ', '').replace('+', '').strip()
    try:
        return int(abs(float(s)))
    except Exception:
        return 0

class BankStatementParser:
    """
    Intelligent Multi-Format Parser for Vietnamese Bank Statements.
    Hỗ trợ đọc sao kê tài khoản ngân hàng từ các định dạng:
    1. .xlsx (Excel hiện đại - openpyxl)
    2. .xls  (Excel 97-2003 - xlrd)
    3. .pdf  (Tài liệu PDF - pypdf kết hợp Gemini Multimodal Document AI)
    4. .csv  (Bảng dữ liệu phân tách dấu phẩy)
    5. .zip  (Tệp nén có mật khẩu hoặc không có mật khẩu từ ứng dụng ngân hàng)
    """

    @classmethod
    def parse_statement_file(cls, file_path: Union[str, Path], password: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Hàm điều phối phân tích tập tin sao kê dựa theo định dạng file.
        Returns:
            (transactions_list, error_code)
            - error_code: None nếu thành công, hoặc 'PASSWORD_REQUIRED', 'BAD_PASSWORD', 'UNSUPPORTED_FORMAT', 'EMPTY_FILE'
        """
        file_path = Path(file_path)
        ext = file_path.suffix.lower()

        # 1. TỆP NÉN .ZIP
        if ext == ".zip":
            extracted_files, err = cls.extract_zip_archive(file_path, password)
            if err:
                return [], err

            all_results = []
            for sub_file in extracted_files:
                sub_ext = sub_file.suffix.lower()
                if sub_ext in [".xlsx", ".xls", ".pdf", ".csv"]:
                    sub_items, _ = cls.parse_statement_file(sub_file, password)
                    all_results.extend(sub_items)

            # Dọn dẹp thư mục tạm
            if extracted_files:
                try:
                    temp_parent = extracted_files[0].parent
                    shutil.rmtree(temp_parent, ignore_errors=True)
                except Exception:
                    pass

            return all_results, None

        # 2. EXCEL HIỆN ĐẠI .XLSX
        elif ext == ".xlsx":
            return cls.parse_excel_statement(file_path), None

        # 3. EXCEL CŨ .XLS
        elif ext == ".xls":
            return cls.parse_xls_statement(file_path), None

        # 4. TÀI LIỆU .PDF
        elif ext == ".pdf":
            return cls.parse_pdf_statement(file_path), None

        # 5. DỮ LIỆU .CSV
        elif ext == ".csv":
            return cls.parse_csv_statement(file_path), None

        return [], "UNSUPPORTED_FORMAT"

    @staticmethod
    def extract_zip_archive(zip_path: Path, password: Optional[str] = None) -> Tuple[List[Path], Optional[str]]:
        """
        Giải nén tệp zip (hỗ trợ cả chuẩn ZipCrypto lẫn chuẩn AES-256 mã hóa của ngân hàng).
        Tự động thử các mật khẩu:
        1. Mật khẩu người dùng nhập trong Chú thích (Caption)
        2. Mật khẩu đã lưu mặc định trong rules_mgr
        3. Mật khẩu cấu hình trong .env (BANK_STATEMENT_PASSWORD)
        4. Thử giải nén không mật khẩu
        """
        # Thu thập các ứng viên mật khẩu
        passwords_to_try = []
        if password and password.strip():
            passwords_to_try.append(password.strip())

        saved_pass = rules_mgr.get_statement_password()
        if saved_pass and saved_pass not in passwords_to_try:
            passwords_to_try.append(saved_pass)

        if config.BANK_STATEMENT_PASSWORD and config.BANK_STATEMENT_PASSWORD not in passwords_to_try:
            passwords_to_try.append(config.BANK_STATEMENT_PASSWORD)

        # Luôn thử cả trường hợp không cần mật khẩu
        passwords_to_try.append(None)

        extract_dir = Path(tempfile.mkdtemp(prefix="bank_stmt_zip_"))
        extracted_files = []

        is_encrypted = False
        decrypt_success = False

        # Thử bằng pyzipper trước (hỗ trợ AES-256 mã hóa mạnh)
        for pwd in passwords_to_try:
            pwd_bytes = pwd.encode("utf-8") if pwd else None
            try:
                if pyzipper:
                    with pyzipper.AESZipFile(zip_path, 'r') as zf:
                        if pwd_bytes:
                            zf.setpassword(pwd_bytes)
                        zf.extractall(extract_dir)
                        decrypt_success = True
                        break
                else:
                    with zipfile.ZipFile(zip_path, 'r') as zf:
                        zf.extractall(extract_dir, pwd=pwd_bytes)
                        decrypt_success = True
                        break
            except (RuntimeError, zipfile.BadZipFile, Exception) as e:
                err_str = str(e).lower()
                if "password" in err_str or "encrypted" in err_str or "bad password" in err_str or "crc" in err_str:
                    is_encrypted = True
                continue

        if not decrypt_success:
            shutil.rmtree(extract_dir, ignore_errors=True)
            if is_encrypted:
                has_passwords_tried = any(p is not None for p in passwords_to_try)
                return [], "BAD_PASSWORD" if has_passwords_tried else "PASSWORD_REQUIRED"
            return [], "CORRUPTED_ZIP"

        # Quét tìm các file bảng tính / PDF bên trong
        for p in extract_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in [".xlsx", ".xls", ".pdf", ".csv"]:
                extracted_files.append(p)

        return extracted_files, None

    @staticmethod
    def parse_excel_statement(file_path: Path) -> List[Dict[str, Any]]:
        """Phân tích sao kê ngân hàng định dạng .xlsx bằng openpyxl."""
        wb = openpyxl.load_workbook(file_path, data_only=True)
        sheet = wb.active

        header_row_idx = None
        col_date = None
        col_desc = None
        col_in = None
        col_out = None
        col_amount = None

        for row_idx in range(1, min(25, sheet.max_row + 1)):
            row_vals = [remove_accents(str(sheet.cell(row=row_idx, column=c).value or '')).lower().strip() for c in range(1, sheet.max_column + 1)]
            has_date = any(k in v for v in row_vals for k in ['ngay', 'date', 'thoi gian'])
            has_money = any(k in v for v in row_vals for k in ['tien', 'amount', 'ghi co', 'ghi no', 'phat sinh', 'so du', 'sotien'])
            has_desc = any(k in v for v in row_vals for k in ['noi dung', 'dien giai', 'mo ta', 'description', 'chi tiet', 'noidung'])

            if (has_date and has_money) or (has_date and has_desc):
                header_row_idx = row_idx
                for col_idx, val in enumerate(row_vals, start=1):
                    if any(k in val for k in ['ngay', 'date', 'thoi gian']) and not col_date:
                        col_date = col_idx
                    elif any(k in val for k in ['noi dung', 'dien giai', 'mo ta', 'description', 'chi tiet', 'noidung']) and not col_desc:
                        col_desc = col_idx
                    elif any(k in val for k in ['ghi co', 'tien vao', 'phat sinh tang', 'credit', 'thu', 'nhan']):
                        col_in = col_idx
                    elif any(k in val for k in ['ghi no', 'tien ra', 'phat sinh giam', 'debit', 'chi', 'gui']):
                        col_out = col_idx
                    elif any(k in val for k in ['so tien', 'sotien', 'amount', 'phat sinh']) and not col_amount:
                        col_amount = col_idx
                break

        if not header_row_idx:
            header_row_idx = 1
            col_date = 1
            col_desc = 2
            col_in = 3
            col_out = 4

        results = []
        for r in range(header_row_idx + 1, sheet.max_row + 1):
            date_val = sheet.cell(row=r, column=col_date).value if col_date else None
            desc_val = sheet.cell(row=r, column=col_desc).value if col_desc else ''

            if not date_val and not desc_val:
                continue

            date_str = ""
            if isinstance(date_val, datetime):
                date_str = date_val.strftime("%Y-%m-%d")
            elif date_val:
                date_str = database.parse_vn_date(str(date_val).strip())

            desc_clean = str(desc_val or '').strip()
            amt_in = 0
            amt_out = 0

            if col_in and col_out:
                amt_in = clean_statement_num(sheet.cell(row=r, column=col_in).value)
                amt_out = clean_statement_num(sheet.cell(row=r, column=col_out).value)
            elif col_amount:
                val = sheet.cell(row=r, column=col_amount).value
                num = clean_statement_num(val)
                try:
                    if float(str(val).replace(',', '')) < 0:
                        amt_out = num
                    else:
                        amt_in = num
                except Exception:
                    amt_in = num

            if amt_in == 0 and amt_out == 0:
                continue

            tx_type = "thu" if amt_in > 0 else "chi"
            amount = amt_in if amt_in > 0 else amt_out

            parsed = RuleEngine.parse(f"{'+' if tx_type == 'thu' else '-'} {amount} {desc_clean}")
            category = parsed["category"] if parsed else ("Doanh thu Dịch vụ" if tx_type == "thu" else "Chi khác")

            results.append({
                "date": date_str,
                "type": tx_type,
                "amount": amount,
                "category": category,
                "description": desc_clean,
                "payment_method": "transfer",
                "source": "bank_statement"
            })

        return results

    @staticmethod
    def parse_xls_statement(file_path: Path) -> List[Dict[str, Any]]:
        """Phân tích sao kê ngân hàng định dạng cũ .xls bằng xlrd."""
        if not xlrd:
            return []

        try:
            wb = xlrd.open_workbook(file_path)
            sheet = wb.sheet_by_index(0)
        except Exception as e:
            print(f"Lỗi đọc file .xls: {e}")
            return []

        header_row_idx = None
        col_date = None
        col_desc = None
        col_in = None
        col_out = None
        col_amount = None

        for row_idx in range(min(25, sheet.nrows)):
            row_vals = [remove_accents(str(sheet.cell_value(row_idx, c) or '')).lower().strip() for c in range(sheet.ncols)]
            has_date = any(k in v for v in row_vals for k in ['ngay', 'date', 'thoi gian'])
            has_money = any(k in v for v in row_vals for k in ['tien', 'amount', 'ghi co', 'ghi no', 'phat sinh', 'so du', 'sotien'])
            has_desc = any(k in v for v in row_vals for k in ['noi dung', 'dien giai', 'mo ta', 'description', 'chi tiet', 'noidung'])

            if (has_date and has_money) or (has_date and has_desc):
                header_row_idx = row_idx
                for col_idx, val in enumerate(row_vals):
                    if any(k in val for k in ['ngay', 'date', 'thoi gian']) and col_date is None:
                        col_date = col_idx
                    elif any(k in val for k in ['noi dung', 'dien giai', 'mo ta', 'description', 'chi tiet', 'noidung']) and col_desc is None:
                        col_desc = col_idx
                    elif any(k in val for k in ['ghi co', 'tien vao', 'phat sinh tang', 'credit', 'thu', 'nhan']):
                        col_in = col_idx
                    elif any(k in val for k in ['ghi no', 'tien ra', 'phat sinh giam', 'debit', 'chi', 'gui']):
                        col_out = col_idx
                    elif any(k in val for k in ['so tien', 'sotien', 'amount', 'phat sinh']) and col_amount is None:
                        col_amount = col_idx
                break

        if header_row_idx is None:
            header_row_idx = 0
            col_date = 0
            col_desc = 1
            col_in = 2
            col_out = 3

        results = []
        for r in range(header_row_idx + 1, sheet.nrows):
            date_val = sheet.cell_value(r, col_date) if col_date is not None else None
            desc_val = sheet.cell_value(r, col_desc) if col_desc is not None else ''

            if not date_val and not desc_val:
                continue

            date_str = ""
            if sheet.cell_type(r, col_date) == xlrd.XL_CELL_DATE:
                try:
                    dt_tuple = xlrd.xldate_as_tuple(date_val, wb.datemode)
                    date_str = f"{dt_tuple[0]:04d}-{dt_tuple[1]:02d}-{dt_tuple[2]:02d}"
                except Exception:
                    date_str = database.parse_vn_date(str(date_val))
            elif date_val:
                date_str = database.parse_vn_date(str(date_val).strip())

            desc_clean = str(desc_val or '').strip()
            amt_in = 0
            amt_out = 0

            if col_in is not None and col_out is not None:
                amt_in = clean_statement_num(sheet.cell_value(r, col_in))
                amt_out = clean_statement_num(sheet.cell_value(r, col_out))
            elif col_amount is not None:
                val = sheet.cell_value(r, col_amount)
                num = clean_statement_num(val)
                try:
                    if float(str(val).replace(',', '')) < 0:
                        amt_out = num
                    else:
                        amt_in = num
                except Exception:
                    amt_in = num

            if amt_in == 0 and amt_out == 0:
                continue

            tx_type = "thu" if amt_in > 0 else "chi"
            amount = amt_in if amt_in > 0 else amt_out

            parsed = RuleEngine.parse(f"{'+' if tx_type == 'thu' else '-'} {amount} {desc_clean}")
            category = parsed["category"] if parsed else ("Doanh thu Dịch vụ" if tx_type == "thu" else "Chi khác")

            results.append({
                "date": date_str,
                "type": tx_type,
                "amount": amount,
                "category": category,
                "description": desc_clean,
                "payment_method": "transfer",
                "source": "bank_statement"
            })

        return results

    @staticmethod
    def parse_csv_statement(file_path: Path) -> List[Dict[str, Any]]:
        """Phân tích sao kê ngân hàng định dạng .csv."""
        results = []
        try:
            with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception:
            try:
                with open(file_path, "r", encoding="cp1258", errors="replace") as f:
                    reader = csv.reader(f)
                    rows = list(reader)
            except Exception as e:
                print(f"Lỗi đọc file .csv: {e}")
                return []

        header_idx = None
        col_date = None
        col_desc = None
        col_in = None
        col_out = None
        col_amount = None

        for idx, row in enumerate(rows[:25]):
            lowers = [remove_accents(c).lower().strip() for c in row]
            has_date = any(k in v for v in lowers for k in ['ngay', 'date', 'thoi gian'])
            has_money = any(k in v for v in lowers for k in ['tien', 'amount', 'ghi co', 'ghi no', 'phat sinh', 'so du', 'sotien'])
            has_desc = any(k in v for v in lowers for k in ['noi dung', 'dien giai', 'mo ta', 'description', 'chi tiet', 'noidung'])
            if (has_date and has_money) or (has_date and has_desc):
                header_idx = idx
                for c_idx, val in enumerate(lowers):
                    if any(k in val for k in ['ngay', 'date', 'thoi gian']) and col_date is None:
                        col_date = c_idx
                    elif any(k in val for k in ['noi dung', 'dien giai', 'mo ta', 'description', 'chi tiet', 'noidung']) and col_desc is None:
                        col_desc = c_idx
                    elif any(k in val for k in ['ghi co', 'tien vao', 'phat sinh tang', 'credit', 'thu', 'nhan']):
                        col_in = c_idx
                    elif any(k in val for k in ['ghi no', 'tien ra', 'phat sinh giam', 'debit', 'chi', 'gui']):
                        col_out = c_idx
                    elif any(k in val for k in ['so tien', 'sotien', 'amount', 'phat sinh']) and col_amount is None:
                        col_amount = c_idx
                break

        if header_idx is None:
            header_idx = 0
            col_date = 0
            col_desc = 1
            col_in = 2
            col_out = 3

        for row in rows[header_idx + 1:]:
            if not row or len(row) <= max(col_date or 0, col_desc or 0):
                continue

            date_raw = row[col_date].strip() if col_date is not None and col_date < len(row) else ""
            desc_clean = row[col_desc].strip() if col_desc is not None and col_desc < len(row) else ""
            if not date_raw and not desc_clean:
                continue

            date_str = database.parse_vn_date(date_raw)
            amt_in = clean_statement_num(row[col_in]) if col_in is not None and col_in < len(row) else 0
            amt_out = clean_statement_num(row[col_out]) if col_out is not None and col_out < len(row) else 0

            if amt_in == 0 and amt_out == 0 and col_amount is not None and col_amount < len(row):
                val = row[col_amount]
                num = clean_statement_num(val)
                if '-' in val:
                    amt_out = num
                else:
                    amt_in = num

            if amt_in == 0 and amt_out == 0:
                continue

            tx_type = "thu" if amt_in > 0 else "chi"
            amount = amt_in if amt_in > 0 else amt_out
            parsed = RuleEngine.parse(f"{'+' if tx_type == 'thu' else '-'} {amount} {desc_clean}")
            category = parsed["category"] if parsed else ("Doanh thu Dịch vụ" if tx_type == "thu" else "Chi khác")

            results.append({
                "date": date_str,
                "type": tx_type,
                "amount": amount,
                "category": category,
                "description": desc_clean,
                "payment_method": "transfer",
                "source": "bank_statement"
            })

        return results

    @staticmethod
    def parse_pdf_statement(file_path: Path) -> List[Dict[str, Any]]:
        """
        Phân tích sao kê ngân hàng định dạng PDF.
        Bước 1: Trích xuất nhanh bằng pypdf cục bộ (nếu là PDF văn bản có cấu trúc).
        Bước 2: Nếu PDF dạng bảng phức tạp hoặc scan ảnh, tự động kích hoạt Gemini Multimodal AI.
        """
        results = []

        # 1. Thử bóc tách nâng cao bằng pypdf (phân tích bảng theo tọa độ cột & dòng)
        if pypdf:
            try:
                reader = pypdf.PdfReader(str(file_path))
                
                # Cách 1: Phân tích tọa độ không gian (chính xác tuyệt đối cho sao kê bảng cột như Techcombank, VCB, MB, ACB...)
                coord_results = []
                for page in reader.pages:
                    items = []
                    def visitor(text, cm, tm, fontDict, fontSize):
                        if text.strip():
                            items.append({'x': tm[4], 'y': tm[5], 'text': text.strip()})
                    page.extract_text(visitor_text=visitor)
                    
                    rows = []
                    items.sort(key=lambda it: -it['y'])
                    for it in items:
                        matched_row = None
                        for r in rows:
                            if abs(r['y'] - it['y']) <= 3.5:
                                matched_row = r
                                break
                        if matched_row:
                            matched_row['items'].append(it)
                        else:
                            rows.append({'y': it['y'], 'items': [it]})
                            
                    for r in rows:
                        r_items = sorted(r['items'], key=lambda it: it['x'])
                        # Kiểm tra có ngày ở cột đầu
                        date_item = next((it for it in r_items if it['x'] < 110 and re.match(r'^\d{1,2}[/-]\d{1,2}[/-]\d{4}$', it['text'])), None)
                        if date_item:
                            date_str = database.parse_vn_date(date_item['text'])
                            # Phân loại Cột Nợ (Debit) và Cột Có (Credit) theo tọa độ bảng
                            debit_item = next((it for it in r_items if 520 <= it['x'] < 640 and re.match(r'^[1-9]\d{0,2}(?:[.,]\d{3})*$', it['text'])), None)
                            credit_item = next((it for it in r_items if 640 <= it['x'] < 745 and re.match(r'^[1-9]\d{0,2}(?:[.,]\d{3})*$', it['text'])), None)
                            desc_items = [it['text'] for it in r_items if 100 <= it['x'] < 520]
                            desc_clean = ' '.join(desc_items).strip()
                            
                            if debit_item:
                                amt = clean_statement_num(debit_item['text'])
                                tx_type = "chi"
                            elif credit_item:
                                amt = clean_statement_num(credit_item['text'])
                                tx_type = "thu"
                            else:
                                continue
                                
                            if amt > 0:
                                parsed = RuleEngine.parse(f"{'+' if tx_type == 'thu' else '-'} {amt} {desc_clean}")
                                category = parsed["category"] if parsed else ("Doanh thu Dịch vụ" if tx_type == "thu" else "Chi khác")
                                coord_results.append({
                                    "date": date_str,
                                    "type": tx_type,
                                    "amount": amt,
                                    "category": category,
                                    "description": desc_clean,
                                    "payment_method": "transfer",
                                    "source": "bank_statement"
                                })

                if coord_results:
                    return coord_results

                # Cách 2: Regex fallback nếu không khớp layout tọa độ chuẩn
                full_text = ""
                for page in reader.pages:
                    full_text += (page.extract_text() or "") + "\n"

                lines = full_text.splitlines()
                date_pattern = r'(\d{1,2}[/-]\d{1,2}[/-]\d{4})'
                for line in lines:
                    line_str = line.strip()
                    d_match = re.search(date_pattern, line_str)
                    if d_match:
                        date_str = database.parse_vn_date(d_match.group(1))
                        num_matches = re.findall(r'(\+|-)?\s*([1-9]\d{0,2}(?:[.,]\d{3})+)', line_str)
                        if num_matches:
                            sign, amt_str = num_matches[0]
                            amt = clean_statement_num(amt_str)
                            if amt > 0:
                                is_thu = sign == "+" or "có" in line_str.lower() or "cr" in line_str.lower() or "nhận" in line_str.lower()
                                tx_type = "thu" if is_thu else "chi"
                                desc = re.sub(date_pattern, '', line_str)
                                desc = re.sub(r'(\+|-)?\s*([1-9]\d{0,2}(?:[.,]\d{3})+)', '', desc)
                                desc_clean = re.sub(r'\s+', ' ', desc).strip()

                                parsed = RuleEngine.parse(f"{'+' if tx_type == 'thu' else '-'} {amt} {desc_clean}")
                                category = parsed["category"] if parsed else ("Doanh thu Dịch vụ" if tx_type == "thu" else "Chi khác")

                                results.append({
                                    "date": date_str,
                                    "type": tx_type,
                                    "amount": amt,
                                    "category": category,
                                    "description": desc_clean,
                                    "payment_method": "transfer",
                                    "source": "bank_statement"
                                })
            except Exception as e:
                print(f"Lỗi đọc PDF bằng pypdf: {e}")

        # 3. Nếu pypdf không lấy được dòng nào (hoặc PDF dạng bảng phức tạp / scan)
        # -> Chuyển giao ngay cho Gemini Multimodal Document AI
        if not results:
            try:
                pdf_bytes = file_path.read_bytes()
                results = GeminiParser.parse_pdf_statement(pdf_bytes)
            except Exception as e:
                print(f"Lỗi phân tích PDF bằng Gemini: {e}")

        return results


class ReportGenerator:
    """Generates professional Excel reports with styling and charts."""

    @staticmethod
    def generate_monthly_excel(year: int, month: int) -> Path:
        summary = database.get_month_summary(year, month)
        transactions = database.get_transactions_by_month(year, month)

        wb = openpyxl.Workbook()
        ws_dash = wb.active
        ws_dash.title = "Tổng Quan"

        font_title = Font(name="Arial", size=16, bold=True, color="1F497D")
        font_subtitle = Font(name="Arial", size=11, italic=True, color="595959")
        font_header = Font(name="Arial", size=11, bold=True, color="FFFFFF")
        font_bold = Font(name="Arial", size=11, bold=True)
        font_regular = Font(name="Arial", size=11)
        font_profit = Font(name="Arial", size=13, bold=True, color="006100")
        font_loss = Font(name="Arial", size=13, bold=True, color="9C0006")

        fill_header_dark = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
        fill_header_blue = PatternFill(start_color="2E75B6", end_color="2E75B6", fill_type="solid")
        fill_header_green = PatternFill(start_color="375623", end_color="375623", fill_type="solid")
        fill_header_orange = PatternFill(start_color="C65911", end_color="C65911", fill_type="solid")
        fill_subtotal = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
        fill_highlight = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")

        border_thin = Border(
            left=Side(style='thin', color='BFBFBF'),
            right=Side(style='thin', color='BFBFBF'),
            top=Side(style='thin', color='BFBFBF'),
            bottom=Side(style='thin', color='BFBFBF')
        )

        align_center = Alignment(horizontal="center", vertical="center")
        align_right = Alignment(horizontal="right", vertical="center")
        align_left = Alignment(horizontal="left", vertical="center")

        num_format_currency = '#,##0 "₫"'

        ws_dash.merge_cells("A1:G1")
        ws_dash["A1"] = f"BÁO CÁO THU CHI PHÒNG KHÁM NHA KHOA"
        ws_dash["A1"].font = font_title
        ws_dash["A1"].alignment = align_center

        ws_dash.merge_cells("A2:G2")
        ws_dash["A2"] = f"Tháng {month:02d}/{year:04d} | Xuất ngày: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        ws_dash["A2"].font = font_subtitle
        ws_dash["A2"].alignment = align_center

        headers_kpi = ["HẠNG MỤC", "TIỀN MẶT", "CHUYỂN KHOẢN", "TỔNG CỘNG"]
        for col_idx, h in enumerate(headers_kpi, start=2):
            cell = ws_dash.cell(row=4, column=col_idx, value=h)
            cell.font = font_header
            cell.fill = fill_header_dark
            cell.alignment = align_center

        kpi_data = [
            ("TỔNG THU (Doanh thu)", summary["thu_cash"], summary["thu_transfer"], summary["total_thu"]),
            ("TỔNG CHI (Chi phí)", summary["chi_cash"], summary["chi_transfer"], summary["total_chi"]),
        ]

        for r_idx, row in enumerate(kpi_data, start=5):
            c1 = ws_dash.cell(row=r_idx, column=2, value=row[0])
            c1.font = font_bold
            c1.border = border_thin

            for c_idx in range(3, 6):
                val = row[c_idx - 2]
                cell = ws_dash.cell(row=r_idx, column=c_idx, value=val)
                cell.font = font_bold
                cell.number_format = num_format_currency
                cell.alignment = align_right
                cell.border = border_thin

        ws_dash.cell(row=7, column=2, value="LỢI NHUẬN RÒNG (Thu - Chi)").font = font_bold
        ws_dash.cell(row=7, column=2).fill = fill_highlight
        ws_dash.cell(row=7, column=2).border = border_thin

        profit_cash = summary["thu_cash"] - summary["chi_cash"]
        profit_transfer = summary["thu_transfer"] - summary["chi_transfer"]
        profit_total = summary["balance"]

        for c_idx, p_val in enumerate([profit_cash, profit_transfer, profit_total], start=3):
            cell = ws_dash.cell(row=7, column=c_idx, value=p_val)
            cell.font = font_profit if p_val >= 0 else font_loss
            cell.fill = fill_highlight
            cell.number_format = num_format_currency
            cell.alignment = align_right
            cell.border = border_thin

        ws_dash.column_dimensions["A"].width = 4
        ws_dash.column_dimensions["B"].width = 32
        ws_dash.column_dimensions["C"].width = 18
        ws_dash.column_dimensions["D"].width = 22
        ws_dash.column_dimensions["E"].width = 22

        ws_detail = wb.create_sheet(title="Sổ Thu Chi Chi Tiết")
        headers_detail = ["ID", "Ngày", "Giờ", "Loại", "Số Tiền", "Hình Thức", "Danh Mục", "Nội Dung", "Nguồn"]

        for c_idx, h in enumerate(headers_detail, start=1):
            cell = ws_detail.cell(row=1, column=c_idx, value=h)
            cell.font = font_header
            cell.fill = fill_header_dark
            cell.alignment = align_center
            cell.border = border_thin

        for r_idx, tx in enumerate(transactions, start=2):
            raw_type = str(tx.get("type", "")).lower()
            t_type = "THU" if "thu" in raw_type else "CHI"
            raw_meth = str(tx.get("payment_method", "")).lower()
            p_method = "Chuyển khoản" if "khoản" in raw_meth or "transfer" in raw_meth else "Tiền mặt"

            c_id = ws_detail.cell(row=r_idx, column=1, value=tx.get("id", r_idx - 1))
            c_date = ws_detail.cell(row=r_idx, column=2, value=tx.get("date", ""))
            c_time = ws_detail.cell(row=r_idx, column=3, value=tx.get("time", ""))
            c_type = ws_detail.cell(row=r_idx, column=4, value=t_type)
            try:
                amt_val = int(tx.get("amount", 0))
            except Exception:
                amt_val = 0
            c_amt = ws_detail.cell(row=r_idx, column=5, value=amt_val)
            c_meth = ws_detail.cell(row=r_idx, column=6, value=p_method)
            c_cat = ws_detail.cell(row=r_idx, column=7, value=tx.get("category", ""))
            c_desc = ws_detail.cell(row=r_idx, column=8, value=tx.get("description", ""))
            c_src = ws_detail.cell(row=r_idx, column=9, value=tx.get("source", "telegram"))

            c_id.alignment = align_center
            c_date.alignment = align_center
            c_time.alignment = align_center
            c_type.alignment = align_center
            c_type.font = Font(name="Arial", size=10, bold=True, color="375623" if t_type == "THU" else "C65911")
            c_amt.number_format = num_format_currency
            c_amt.alignment = align_right
            c_amt.font = font_bold
            c_meth.alignment = align_center

            for cell in [c_id, c_date, c_time, c_type, c_amt, c_meth, c_cat, c_desc, c_src]:
                cell.border = border_thin

        col_widths = [8, 14, 12, 10, 18, 16, 26, 35, 14]
        for idx, w in enumerate(col_widths, start=1):
            ws_detail.column_dimensions[get_column_letter(idx)].width = w

        filename = f"BaoCao_ThuChi_NhaKhoa_{year:04d}_{month:02d}.xlsx"
        output_path = REPORTS_DIR / filename
        wb.save(output_path)
        return output_path
