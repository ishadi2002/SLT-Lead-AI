import unittest
import sys
from io import BytesIO
from pathlib import Path
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from main import analyze, build_export


class RealWorkbookStructuresTest(unittest.TestCase):
    def test_education_real_workbook_structures(self):
        wb = Workbook()
        wb.remove(wb.active)

        # 1. CAIT Sheet
        ws_cait = wb.create_sheet("CAIT")
        ws_cait.append(["Center", "full_name", "email", "city", "phone_number", None, None, "Counselor", "Call Status", "Potential Course", "Potential Level", "Customer Feedback"])
        ws_cait.append([None, None, None, None, "2026-03-10", None, None, None, None, None, None, None])  # Date banner
        ws_cait.append(["Welisara", "Poorni Fonseka", "poorni@example.com", "Ragama", "p:+94766814324", None, None, "Pavani", "Answered", "CAIT", "H", "details shared, she will register for wed & thu new batch"])
        ws_cait.append(["Moratuwa", "Dilshan Bandara", "dilshan@example.com", "Colombo", "p:+94770263276", None, None, "Harshana", "Answered", "CAIT", "M", "He wants to register (0770263276)"])
        ws_cait.append(["Moratuwa", "Kavindya Perera", "kavindya@example.com", "Colombo", "p:+94775072250", None, None, "Harshana", "Answered", "CAIT", "L", "Have to discuss with her parents,Sent details via whatsapp"])
        ws_cait.append(["Moratuwa", "Kasun Chathuranga", "kasun@example.com", "Colombo", "p:+94712982651", None, None, "Harshana", "Not Answered", "CAIT", "L", "Not interested"])

        # 2. HND Sheet
        ws_hnd = wb.create_sheet("HND")
        ws_hnd.append(["what_was_your_a/l_stream?", "which_degree_program_are_you_interested_in?", "full_name", "email", "city", "phone_number", None, "Staff", "Call Status", "Potential Course", "Potential Level", "Customer Feedback", "2nd call round"])
        ws_hnd.append(["Maths", "hnd_in_computing", "Savija Rumeth", "savija@example.com", "Gampaha", "p:+94713065617", None, "Senuri", "Answered", "HND COM", "H", "I already contacted and he sent me his transcripts ...Pending approval", None])
        ws_hnd.append(["Arts", "hnd_in_electrical_&_electronics_engineering", "Nipuna Jeewantha", "nipuna@example.com", "Badulla", "p:+94707800860", None, "Lihini", "Answered", "HND EEE", "M", "SLT Staff - power and ac , nvq 4 - industrial electrical, NVQ 5- Electrical technology pending, sent details via watsapp", None])

        # 3. UH Sheet
        ws_uh = wb.create_sheet("UH")
        ws_uh.append(["what_was_your_al_stream?", "please_mention_which_degree_program_you_want_to_apply_for.", "full_name", "email", "city", "phone_number", None, "Agent", "1st Call Status", "UH All", "L", "Customer Feedback", None, "2nd Call Remarks"])
        ws_uh.append(["Maths", "data_science", "saarrankan test", "saar@example.com", "Colombo", "p:+94777137346", None, "Pavani", "Answered", "UH DS", "M", "AL Maths pending results, father is looking thi for her daughter, req to send details via wtsp", None, "rejected 09/04"])
        ws_uh.append(["Maths", "electrical_&_electronic_engineering", "Manesha Weraduwage", "manesha@example.com", "Galle", "p:+94777541389", None, "Pavani", "Answered", "UH EEE", "H", "AL Maths pending results, OL Eng A", None, "call back later 09/04"])

        buf = BytesIO()
        wb.save(buf)
        content = buf.getvalue()

        result = analyze(content, "education")
        self.assertGreater(result["total_rows"], 0)
        self.assertGreater(len(result["records"]), 0)

        # Check export generation
        export_buf = build_export(result)
        self.assertGreater(export_buf.getbuffer().nbytes, 1000)

    def test_broadband_real_workbook_structures(self):
        wb = Workbook()
        wb.remove(wb.active)

        ws = wb.create_sheet("Galle Geo")
        ws.append(["created_time", None, "full_name", "email", "phone_number", "city", None])  # Column G is unnamed feedback
        ws.append(["27th May", None, "Hiran Kanishka", "hiran@example.com", "p:+94767000305", "karapitiya", "Application and 12500/= collected"])
        ws.append(["28th May", None, "Jayani Iresha", "jayani@example.com", "p:+94773487846", "Galle", "New FDP pending"])
        ws.append(["30th May", None, "Deshapriya Sarath", "deshapriya@example.com", "p:+94759655850", "Galle", "Payment Done"])
        ws.append(["27th May", None, "Ngs Asanka", "asanka@example.com", "p:+94712902009", "Nakiyadeniya", "no need"])

        buf = BytesIO()
        wb.save(buf)
        content = buf.getvalue()

        result = analyze(content, "broadband")
        self.assertGreater(result["total_rows"], 0)
        self.assertGreaterEqual(len(result["records"]), 2)  # Hiran (collected) & Deshapriya (Payment Done)

    def test_business_real_workbook_structures(self):
        wb = Workbook()
        wb.remove(wb.active)

        # Branch sheet with Feedback in Column H
        ws_branch = wb.create_sheet("Maradana")
        ws_branch.append(["Date", "created_time", "select_your_nearest_slt-mobitel_branch:", "full_name", "phone_number", "city", "email", "Feedback"])
        ws_branch.append(["26th June 2026", "2026-06-26T13:31:32+05:30", "maradana", "Faz Mw", "p:+94777614949", "Colombo", "faz@example.com", "Applied for an FFTH"])
        ws_branch.append(["29th June 2026", "2026-06-29T20:51:17+05:30", "maradana", "Rayan Lakruwan", "p:+94759357357", "Colombo", "rayan@example.com", "visit arranged"])
        ws_branch.append(["28th June 2026", "2026-06-28T12:19:00+05:30", "maradana", "Nethmi Nadeesha", "p:+94782930769", "Kegalle", "nethmi@example.com", "Not Required"])

        # Master list with no feedback (should be skipped to prevent duplicates)
        ws_master = wb.create_sheet("Master List")
        ws_master.append(["Date", "created_time", "select_your_nearest_slt-mobitel_branch:", "full_name", "phone_number", "city", "email"])
        ws_master.append(["26th June 2026", "2026-06-26T13:31:32+05:30", "maradana", "Faz Mw", "p:+94777614949", "Colombo", "faz@example.com"])

        buf = BytesIO()
        wb.save(buf)
        content = buf.getvalue()

        result = analyze(content, "business")
        self.assertEqual(len(result["warnings"]), 1)  # Business Master List skipped warning
        self.assertEqual(len(result["records"]), 2)  # Faz Mw (HOT) & Rayan Lakruwan (WARM)


if __name__ == '__main__':
    unittest.main()
