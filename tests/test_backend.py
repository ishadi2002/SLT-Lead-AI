import unittest
import re
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from main import (
    norm, as_text, first, is_real_name, phone_text,
    find_feedback_column, excel_col, safe_excel_value,
    scan_header, build_export
)


class BackendHelpersTests(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(norm("Full Name"), "full_name")
        self.assertEqual(norm("Customer-Feedback / Notes"), "customer_feedback_notes")
        self.assertEqual(norm(""), "")

    def test_as_text(self):
        self.assertEqual(as_text(None), "")
        self.assertEqual(as_text(" Hello "), "Hello")
        self.assertEqual(as_text(12345), "12345")
        dt = datetime(2026, 6, 25, 10, 30, 0)
        self.assertEqual(as_text(dt), "2026-06-25 10:30:00")

    def test_first(self):
        record = {
            "First Name": "",
            "Customer_Name": "Sunil Perera",
            "Full Name": "Other"
        }
        val = first(record, ["first_name", "customer_name", "full_name"])
        self.assertEqual(val, "Sunil Perera")

    def test_is_real_name_valid(self):
        self.assertTrue(is_real_name("Kamal Perera"))
        self.assertTrue(is_real_name("M. A. Nimal Silva"))
        self.assertTrue(is_real_name("Dilshan Bandara"))

    def test_is_real_name_invalid_dates_and_numbers(self):
        self.assertFalse(is_real_name("2026-06-25T13:46:41"))
        self.assertFalse(is_real_name("12th March 2026"))
        self.assertFalse(is_real_name("0712345678"))
        self.assertFalse(is_real_name("+94712345678"))

    def test_is_real_name_invalid_slugs_and_headers(self):
        self.assertFalse(is_real_name("hnd_computing"))
        self.assertFalse(is_real_name("degree_in_software_engineering"))
        self.assertFalse(is_real_name("full_name"))
        self.assertFalse(is_real_name("moratuwa"))
        self.assertFalse(is_real_name("colombo"))
        self.assertFalse(is_real_name("info@slt.lk"))

    def test_phone_text(self):
        # Plain 10-digit local number — returned as-is
        self.assertEqual(phone_text("0712345678"), "0712345678")
        # International format with spaces → normalised to +94... digits
        result = phone_text("+94 77 123 4567")
        self.assertTrue(result.startswith("+94"), f"Expected +94..., got {result!r}")
        self.assertEqual(len(re.sub(r"\D", "", result)), 11)
        # p: prefix stripped → valid number extracted
        self.assertNotEqual(phone_text("p:+94711375278"), "")
        self.assertNotEqual(phone_text("p:0771234567"), "")
        # Too short — rejected
        self.assertEqual(phone_text("1234"), "")
        self.assertEqual(phone_text(""), "")

    def test_find_feedback_column(self):
        original = {
            "Full Name": "Test Customer",
            "Customer Feedback": "Interested in fiber",
            "2nd Call Remarks": "Wants quotation"
        }
        res = find_feedback_column(original, "business")
        self.assertIn("Interested in fiber", res)
        self.assertIn("Wants quotation", res)

    def test_excel_col(self):
        self.assertEqual(excel_col(1), "A")
        self.assertEqual(excel_col(26), "Z")
        self.assertEqual(excel_col(27), "AA")
        self.assertEqual(excel_col(28), "AB")

    def test_safe_excel_value_formula_injection_defense(self):
        self.assertEqual(safe_excel_value("=1+1"), "'=1+1")
        self.assertEqual(safe_excel_value("+1234"), "'+1234")
        self.assertEqual(safe_excel_value("-5678"), "'-5678")
        self.assertEqual(safe_excel_value("@cmd"), "'@cmd")
        self.assertEqual(safe_excel_value("Regular Text"), "Regular Text")

    def test_scan_header_row_detection(self):
        # Row 1 is a title/date row, Row 2 is true headers
        rows = [
            ["Weekly Leads 12th March 2026", None, None],
            ["Full Name", "Phone Number", "Customer Feedback"],
            ["Sunil Silva", "0711111111", "Application collected"]
        ]
        header_idx = scan_header(rows)
        self.assertEqual(header_idx, 2)

    def test_build_export(self):
        sample_result = {
            "records": [
                {
                    "sheet": "Colombo Region",
                    "row": 2,
                    "score": 90,
                    "name": "Sunil Silva",
                    "phone": "0711111111",
                    "reason": "Order/Application submitted",
                    "feedback": "Application collected",
                    "headers": ["Customer Name", "Phone", "Notes"],
                    "original": {
                        "Customer Name": "Sunil Silva",
                        "Phone": "0711111111",
                        "Notes": "Application collected"
                    }
                }
            ]
        }
        buffer = build_export(sample_result)
        self.assertGreater(buffer.getbuffer().nbytes, 1000)


if __name__ == '__main__':
    unittest.main()
