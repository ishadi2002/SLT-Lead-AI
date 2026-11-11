"""
Verify that the PHONE_IN_TEXT fallback correctly extracts phone numbers
embedded inside feedback text (the previously failing case).

For rows where column E is empty, the phone should be pulled from
feedback text like "Registered to CAIT | p:+94777933383 | Lihini".
"""
import sys, re
sys.path.insert(0, 'backend')

from openpyxl.reader.excel import load_workbook
from main import get_rows

EDU_PATH = (
    r"C:/Users/ishad/.gemini/antigravity/brain/"
    r"17fa487c-aa1f-43a7-a6bc-c16b9352e37a/.user_uploaded/"
    r"media_1794285292628_319783e4.xlsx"
)

PHONE_IN_TEXT = re.compile(r"p\s*:\s*(\+?(?:94|0)\d{9,10})", re.I)

wb = load_workbook(EDU_PATH, data_only=True)
empty_phone_count = 0
fallback_success = 0

for wsname in wb.sheetnames:
    ws = wb[wsname]
    rows = get_rows(ws, "education")

    for r in rows:
        fb = r.get("feedback", "")
        has_phone_in_feedback = bool(PHONE_IN_TEXT.search(fb))
        phone_populated = bool(r["phone"])

        if has_phone_in_feedback and not phone_populated:
            empty_phone_count += 1
            # Show first 5 failures for debugging (anonymised)
            if empty_phone_count <= 5:
                print(f"FAIL [{wsname}] feedback: {fb[:80]!r}")
        elif has_phone_in_feedback and phone_populated:
            fallback_success += 1

print()
print(f"Rows where feedback has p: phone AND phone field populated : {fallback_success}")
print(f"Rows where feedback has p: phone BUT phone field STILL EMPTY: {empty_phone_count}  ← must be 0")

# Also count overall empty phones
total = sum(len(get_rows(wb[ws], "education")) for ws in wb.sheetnames)
empty_total = sum(1 for ws in wb.sheetnames for r in get_rows(wb[ws], "education") if not r["phone"])
print(f"\nTotal records: {total}  |  Empty phone: {empty_total}")
