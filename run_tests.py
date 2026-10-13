"""
Comprehensive Test Suite for AutoAccounting v1.0
QA Automation Test Suite covering all features and components.
"""

import sys
import os
import unittest
from datetime import datetime
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import config
from ai_parser import GeminiParser, RuleEngine, rules_mgr, remove_accents
import database
from bank_reconciler import BankStatementParser, ReportGenerator

class TestAutoAccounting(unittest.TestCase):

    def test_01_remove_accents_and_typos(self):
        """Test Vietnamese accent stripping and typo normalization."""
        raw = "hoa wa thap huog"
        norm = RuleEngine.normalize_typos(raw)
        unaccent = remove_accents(norm)
        self.assertIn("qua", unaccent)
        self.assertIn("huong", unaccent)

        raw_dent = "khach tram răn"
        norm_dent = RuleEngine.normalize_typos(raw_dent)
        unaccent_dent = remove_accents(norm_dent)
        self.assertIn("rang", unaccent_dent)

    def test_02_rule_engine_amount_parser(self):
        """Test amount parsing across various Vietnamese formats."""
        self.assertEqual(RuleEngine.parse_amount("70k"), 70000)
        self.assertEqual(RuleEngine.parse_amount("500k"), 500000)
        self.assertEqual(RuleEngine.parse_amount("1.2tr"), 1200000)
        self.assertEqual(RuleEngine.parse_amount("1tr5"), 1500000)
        self.assertEqual(RuleEngine.parse_amount("2 triệu"), 2000000)
        self.assertEqual(RuleEngine.parse_amount("150.000 đ"), 150000)

    def test_03_rule_engine_classification(self):
        """Test fallback rule engine categorizations."""
        # Chi
        res1 = RuleEngine.parse("- 70k hoa qua thap huong")
        self.assertIsNotNone(res1)
        self.assertEqual(res1["type"], "chi")
        self.assertEqual(res1["amount"], 70000)
        self.assertEqual(res1["category"], "Chi phí Tâm linh & Sinh hoạt")

        # Thu
        res2 = RuleEngine.parse("+ 500k khach tram rang")
        self.assertIsNotNone(res2)
        self.assertEqual(res2["type"], "thu")
        self.assertEqual(res2["amount"], 500000)
        self.assertEqual(res2["category"], "Doanh thu Dịch vụ")

        # Transfer (CK)
        res3 = RuleEngine.parse("+ 2tr ck khach Trang boc rang")
        self.assertIsNotNone(res3)
        self.assertEqual(res3["payment_method"], "transfer")

    def test_04_gemini_ai_parser(self):
        """Test Gemini AI text extraction."""
        res = GeminiParser.parse_text("- 450k labo rang su chi Nga")
        self.assertIsNotNone(res)
        self.assertEqual(res["type"], "chi")
        self.assertEqual(res["amount"], 450000)
        self.assertIn("Labo", res["category"])

    def test_05_rules_manager_teach(self):
        """Test dynamic rule learning."""
        keyword = "test_vat_tu_dac_biet"
        rules_mgr.teach(keyword, "chi", "Vật tư & Thuốc men")
        learned = [r for r in rules_mgr.rules.get("learned_rules", []) if r["keyword"] == keyword]
        self.assertTrue(len(learned) > 0)
        
        # Test that rule engine applies this learned rule
        res = RuleEngine.parse(f"- 100k mua {keyword}")
        self.assertIsNotNone(res)
        self.assertEqual(res["category"], "Vật tư & Thuốc men")

    def test_06_database_google_sheets_connection(self):
        """Test Google Sheets Database Adapter."""
        self.assertTrue(bool(config.GOOGLE_SHEETS_WEBHOOK_URL), "GOOGLE_SHEETS_WEBHOOK_URL must be configured")
        
        # Test add transaction
        tx_id = database.add_transaction(
            tx_type="chi",
            amount=55000,
            category="Chi phí Tâm linh & Sinh hoạt",
            description="[TEST QA] Mua hoa quả thắp hương",
            payment_method="cash",
            source="qa_test"
        )
        self.assertIsNotNone(tx_id)
        print(f"\n   [QA Result] Added test transaction to Google Sheets ID: #{tx_id}")

        # Test query today summary
        today = database.get_today_summary()
        self.assertIn("total_thu", today)
        self.assertIn("total_chi", today)

        # Test delete test transaction
        del_success = database.delete_transaction(tx_id)
        print(f"   [QA Result] Deleted test transaction #{tx_id} from Google Sheets: {del_success}")

    def test_07_excel_report_generator(self):
        """Test offline report generator fallback."""
        now = datetime.now()
        path = ReportGenerator.generate_monthly_excel(now.year, now.month)
        self.assertTrue(path.exists())
        self.assertTrue(path.stat().st_size > 0)

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🔍 BẮT ĐẦU CHẠY KIỂM THỬ TOÀN DIỆN AUTOACCOUNTING v1.0")
    print("="*60)
    unittest.main(verbosity=2)
