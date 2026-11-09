# SLT Meta Lead Qualification (local MVP)

A working React + FastAPI prototype for **Education / Business / Broadband** lead qualification from .xlsx workbooks.

## Output
- Choose category manually and upload weekly Excel file.
- Analyze **each category independently** using transparent evidence-first rules.
- Display name, original phone, original feedback, and **Why Top Lead?** (no score).
- Toggle **Show all original columns** to inspect original metadata on screen.
- Download `.xlsx` containing **all the original columns in their original order plus a new Why Top Lead? column**, one output worksheet per matching input worksheet.
- Avoid duplicates within a worksheet; business Master List is skipped if regional sheets exist.
- Phone numbers are treated as strings, and text beginning with Excel-formula operators is safely escaped on export.

## Requirements
Python 3.10+ and Node.js 18+.

## Start backend
```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## Start frontend (second terminal)
```bash
cd frontend
npm install
npm run dev
```
Open `http://127.0.0.1:5173` in browser.

## Recommended tests
1. Education: CAIT/HND/UH example; note that UH has header on row 2.
2. Business: SME workbook; Master List skipped to prevent region duplicates.
3. Broadband: Galle Geo workbook; unnamed feedback column G is supported.
4. Verify exact original fields and new Why Top Lead? column in downloaded Excel.

## Qualification policy
- Education: direct intent to register/apply, admission appointments, or specific course interest from contacted leads.
- Business: service request, business visit, or customer application/order.
- Broadband: application/payment evidence, specific connection request, installation or coverage milestone.
- Explicit rejection, unanswered calls without other evidence, and simple WhatsApp information-sending are **not** top leads.
- Historic data does not equal a current active lead: older timestamped feedback is marked for reconfirmation.
- Already-completed service installations are not counted as new opportunities.
- Output is a shortlist for *staff review*, not a guarantee of conversion. There is no external AI/Apify call.

## Privacy & operating notes
- Process files locally on your own computer. Uploaded data are held only in process memory; restart backend to clear.
- Do not deploy as-is to public internet: add login, role authorization, encryption, audit log, retention and access control under SLT policy.
- Rule patterns must be tested against staff-approved labeled examples before production.
- Avoid saving customer phone numbers to public source repositories.
