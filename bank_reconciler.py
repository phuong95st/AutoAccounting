import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
import database
from ai_parser import GeminiParser, RuleEngine
from config import REPORTS_DIR

class BankStatementParser:
    """Intelligent parser for Vietnamese bank statements (VCB, TCB, MB, ACB, VPB, BIDV...)."""

    @staticmethod
    def parse_excel_statement(file_path: Path) -> List[Dict[str, Any]]:
        wb = openpyxl.load_workbook(file_path, data_only=True)
        sheet = wb.active
        
        # 1. Scan for header row
        header_row_idx = None
        col_date = None
        col_desc = None
        col_in = None
        col_out = None
        col_amount = None

        for row_idx in range(1, min(25, sheet.max_row + 1)):
            row_vals = [str(sheet.cell(row=row_idx, column=c).value or '').lower().strip() for c in range(1, sheet.max_column + 1)]
            # Check if this row looks like header
            has_date = any(k in v for v in row_vals for k in ['ngày', 'date', 'thời gian'])
            has_money = any(k in v for v in row_vals for k in ['tiền', 'amount', 'ghi có', 'ghi nợ', 'phát sinh', 'số dư'])
            has_desc = any(k in v for v in row_vals for k in ['nội dung', 'diễn giải', 'mô tả', 'description', 'chi tiết'])

            if (has_date and has_money) or (has_date and has_desc):
                header_row_idx = row_idx
                for col_idx, val in enumerate(row_vals, start=1):
                    if any(k in val for k in ['ngày', 'date', 'thời gian']) and not col_date:
                        col_date = col_idx
                    elif any(k in val for k in ['nội dung', 'diễn giải', 'mô tả', 'description', 'chi tiết']) and not col_desc:
                        col_desc = col_idx
                    elif any(k in val for k in ['ghi có', 'tiền vào', 'phát sinh tăng', 'credit', 'thu', 'nhận']):
                        col_in = col_idx
                    elif any(k in val for k in ['ghi nợ', 'tiền ra', 'phát sinh giảm', 'debit', 'chi', 'gửi']):
                        col_out = col_idx
                    elif any(k in val for k in ['số tiền', 'amount', 'phát sinh']) and not col_amount:
                        col_amount = col_idx
                break

        if not header_row_idx:
            # Fallback assumption if no header found
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

            # Format date
            date_str = ""
            if isinstance(date_val, datetime):
                date_str = date_val.strftime("%Y-%m-%d")
            elif date_val:
                date_str = str(date_val).strip()

            desc_clean = str(desc_val or '').strip()

            # Read amount
            amt_in = 0
            amt_out = 0

            def clean_num(v):
                if not v:
                    return 0
                if isinstance(v, (int, float)):
                    return int(abs(v))
                s = str(v).replace(',', '').replace('.', '').replace('VND', '').replace('đ', '').strip()
                try:
                    return int(abs(float(s)))
                except:
                    return 0

            if col_in and col_out:
                amt_in = clean_num(sheet.cell(row=r, column=col_in).value)
                amt_out = clean_num(sheet.cell(row=r, column=col_out).value)
            elif col_amount:
                val = sheet.cell(row=r, column=col_amount).value
                num = clean_num(val)
                # Check if negative or positive
                try:
                    if float(str(val).replace(',', '')) < 0:
                        amt_out = num
                    else:
                        amt_in = num
                except:
                    amt_in = num

            if amt_in == 0 and amt_out == 0:
                continue

            tx_type = "thu" if amt_in > 0 else "chi"
            amount = amt_in if amt_in > 0 else amt_out

            # Classify category using rule engine or AI
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


class ReportGenerator:
    """Generates professional Excel reports with styling and charts."""

    @staticmethod
    def generate_monthly_excel(year: int, month: int) -> Path:
        summary = database.get_month_summary(year, month)
        transactions = database.get_transactions_by_month(year, month)

        wb = openpyxl.Workbook()
        ws_dash = wb.active
        ws_dash.title = "Tổng Quan"

        # Styles
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

        # ==========================================
        # SHEET 1: DASHBOARD
        # ==========================================
        ws_dash.merge_cells("A1:G1")
        ws_dash["A1"] = f"BÁO CÁO THU CHI PHÒNG KHÁM NHA KHOA"
        ws_dash["A1"].font = font_title
        ws_dash["A1"].alignment = align_center

        ws_dash.merge_cells("A2:G2")
        ws_dash["A2"] = f"Tháng {month:02d}/{year:04d} | Xuất ngày: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        ws_dash["A2"].font = font_subtitle
        ws_dash["A2"].alignment = align_center

        # Section 1: KPI Summary Card
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

        # Net Profit Row
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

        # Section 2: Detailed Category Breakdown
        # Chi phí
        ws_dash.cell(row=9, column=2, value="CHI TIẾT CHI PHÍ THEO DANH MỤC").font = font_header
        ws_dash.cell(row=9, column=2).fill = fill_header_orange
        ws_dash.merge_cells("B9:E9")
        ws_dash.cell(row=9, column=2).alignment = align_left

        headers_cat = ["Danh mục chi", "Số giao dịch", "Số tiền", "Tỷ trọng %"]
        for c_idx, h in enumerate(headers_cat, start=2):
            cell = ws_dash.cell(row=10, column=c_idx, value=h)
            cell.font = font_bold
            cell.fill = fill_subtotal
            cell.alignment = align_center
            cell.border = border_thin

        curr_r = 11
        tot_chi = summary["total_chi"] or 1
        for cat in summary["categories_chi"]:
            ws_dash.cell(row=curr_r, column=2, value=cat["category"]).font = font_regular
            ws_dash.cell(row=curr_r, column=2).border = border_thin

            ws_dash.cell(row=curr_r, column=3, value=cat["count"]).font = font_regular
            ws_dash.cell(row=curr_r, column=3).alignment = align_center
            ws_dash.cell(row=curr_r, column=3).border = border_thin

            c_amt = ws_dash.cell(row=curr_r, column=4, value=cat["total"])
            c_amt.font = font_regular
            c_amt.number_format = num_format_currency
            c_amt.alignment = align_right
            c_amt.border = border_thin

            c_pct = ws_dash.cell(row=curr_r, column=5, value=cat["total"] / tot_chi)
            c_pct.font = font_regular
            c_pct.number_format = '0.0%'
            c_pct.alignment = align_right
            c_pct.border = border_thin
            curr_r += 1

        # Doanh thu
        curr_r += 1
        ws_dash.cell(row=curr_r, column=2, value="CHI TIẾT DOANH THU").font = font_header
        ws_dash.cell(row=curr_r, column=2).fill = fill_header_green
        ws_dash.merge_cells(f"B{curr_r}:E{curr_r}")
        ws_dash.cell(row=curr_r, column=2).alignment = align_left
        curr_r += 1

        headers_cat_thu = ["Danh mục thu", "Số giao dịch", "Số tiền", "Tỷ trọng %"]
        for c_idx, h in enumerate(headers_cat_thu, start=2):
            cell = ws_dash.cell(row=curr_r, column=c_idx, value=h)
            cell.font = font_bold
            cell.fill = fill_subtotal
            cell.alignment = align_center
            cell.border = border_thin
        curr_r += 1

        tot_thu = summary["total_thu"] or 1
        for cat in summary["categories_thu"]:
            ws_dash.cell(row=curr_r, column=2, value=cat["category"]).font = font_regular
            ws_dash.cell(row=curr_r, column=2).border = border_thin

            ws_dash.cell(row=curr_r, column=3, value=cat["count"]).font = font_regular
            ws_dash.cell(row=curr_r, column=3).alignment = align_center
            ws_dash.cell(row=curr_r, column=3).border = border_thin

            c_amt = ws_dash.cell(row=curr_r, column=4, value=cat["total"])
            c_amt.font = font_regular
            c_amt.number_format = num_format_currency
            c_amt.alignment = align_right
            c_amt.border = border_thin

            c_pct = ws_dash.cell(row=curr_r, column=5, value=cat["total"] / tot_thu)
            c_pct.font = font_regular
            c_pct.number_format = '0.0%'
            c_pct.alignment = align_right
            c_pct.border = border_thin
            curr_r += 1

        # Adjust column widths for Sheet 1
        ws_dash.column_dimensions["A"].width = 4
        ws_dash.column_dimensions["B"].width = 32
        ws_dash.column_dimensions["C"].width = 18
        ws_dash.column_dimensions["D"].width = 22
        ws_dash.column_dimensions["E"].width = 22

        # ==========================================
        # SHEET 2: SỔ THU CHI CHI TIẾT
        # ==========================================
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
            except:
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

        # Column widths for Sheet 2
        col_widths = [8, 14, 12, 10, 18, 16, 26, 35, 14]
        for idx, w in enumerate(col_widths, start=1):
            ws_detail.column_dimensions[get_column_letter(idx)].width = w

        # Save file
        filename = f"BaoCao_ThuChi_NhaKhoa_{year:04d}_{month:02d}.xlsx"
        output_path = REPORTS_DIR / filename
        wb.save(output_path)
        return output_path
