"""Quick diagnostic: validate Education Excel extraction with actual file."""
import sys
sys.path.insert(0, 'backend')

from openpyxl.reader.excel import load_workbook
from main import get_rows

EDU_PATH = (
    r"C:/Users/ishad/.gemini/antigravity/brain/"
    r"17fa487c-aa1f-43a7-a6bc-c16b9352e37a/.user_uploaded/"
    r"media_1794285292628_319783e4.xlsx"
)

wb = load_workbook(EDU_PATH, data_only=True)

for wsname in wb.sheetnames:
    ws = wb[wsname]
    rows = get_rows(ws, "education")
    print(f"=== {wsname}: {len(rows)} records extracted ===")
    for r in rows[:5]:
        name = r["name"]
        phone = r["phone"]
        # Anonymise output
        name_safe  = (name[:3]  + "***") if name  else "(empty)"
        phone_safe = ("***" + phone[-4:]) if phone else "(empty)"
        print(
            f"  Name: {name_safe:<14} "
            f"Phone: {phone_safe:<12} "
            f"Score: {r['score']:<4} "
            f"Disp: {r['disposition']}"
        )
    print()

print("Done.")
