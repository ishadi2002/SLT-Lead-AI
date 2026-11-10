"""SLT Excel Lead Qualification API - Priority Sorted Output."""

from collections import Counter
from io import BytesIO
from itertools import chain
from datetime import datetime
from typing import Annotated

import re
import uuid

from fastapi import (
    FastAPI, UploadFile, File, Form, HTTPException
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.reader.excel import load_workbook

from engine import evaluate


app = FastAPI(
    title="SLT Lead Qualifier",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

CATEGORIES = {"education", "business", "broadband"}
MAX_BYTES = 15 * 1024 * 1024
RESULTS = {}


def norm(value):
    """Normalize strings to clean snake_case for comparison."""
    return re.sub(
        r"[^a-z0-9]+", "_",
        str(value or "").lower()
    ).strip("_")


def as_text(value):
    """Convert Excel cell values safely to cleaned text."""
    if value is None:
        return ""

    if isinstance(value, datetime):
        return value.isoformat(sep=" ")

    return str(value).strip()


def first(record, names):
    """Locate the first populated value matching given alias column names."""
    for name in names:
        target_norm = norm(name)
        for key, value in record.items():
            if norm(key) == target_norm:
                txt = as_text(value)
                if txt:
                    return txt
    return ""


def scan_header(rows):
    """Scan first 20 rows to find header row index cleanly."""
    for rownum, row in enumerate(rows[:20], 1):
        cells = [norm(value) for value in row[:60] if value is not None]

        # Ignore rows containing pure date values
        has_date_headers = any(re.search(r'\d{1,2}(?:st|nd|rd|th)?_\w+_\d{4}', c) for c in cells if c)
        if has_date_headers:
            continue

        if "full_name" in cells or "student_name" in cells or "customer_name" in cells or (
            any("name" in c for c in cells) and (
                "email" in cells or "phone_number" in cells or "phone" in cells or "mobile" in cells or "contact" in cells
            )
        ):
            return rownum

    return 1


def is_real_name(value):
    """Strictly validate if extracted value is a real person/customer name."""
    name = as_text(value).strip()

    if not name or len(name) < 3 or len(name) > 110:
        return False

    # 1. Reject ISO & Written Text Dates
    date_pattern = (
        r"^(?:\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|"
        r"\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*|"
        r"\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\b)"
    )
    if re.search(date_pattern, name, re.I):
        return False

    # 2. Reject Phone numbers or numeric values
    if re.match(r"^(?:\d+|\d{4}[-/]\d{1,2}|p\s*:|\+?94\d+|0\d{9})$", name, re.I):
        return False

    # 3. Reject Course identifiers, slugs, and system headers
    norm_name = norm(name)
    if norm_name.startswith(("hnd_", "degree_", "course_", "bsc_", "msc_", "diploma_")):
        return False

    invalid_names = {
        "full_name", "name", "student_name", "customer_name", "applicant_name",
        "data_science", "robotics_ai", "electrical_electronic_engineering",
        "computing", "other_not_sure_yet", "date", "timestamp", "created_time",
        "phone", "mobile", "email", "remarks", "feedback", "status", "moratuwa",
        "colombo", "kandy", "galle", "jaffna", "kurunegala", "ratnapura"
    }

    if norm_name in invalid_names:
        return False

    if "@" in name or "http" in name.lower() or "www." in name.lower():
        return False

    return any(char.isalpha() for char in name)


def phone_text(value):
    """Extract and validate clean phone numbers."""
    phone = as_text(value)

    if not phone or isinstance(value, datetime):
        return ""

    digits = re.sub(r"\D", "", phone)

    if 9 <= len(digits) <= 13:
        return phone

    return ""


def find_feedback_column(original, category):
    """Extract and aggregate feedback notes across columns."""
    values = []

    feedback_keys = {
        "customer_feedback", "feedback", "staff_feedback",
        "follow_up_feedback", "remarks", "2nd_call_remarks",
        "1st_call_status", "comments", "notes"
    }

    for key, value in original.items():
        if norm(key) in feedback_keys:
            text = as_text(value)
            if text and text not in values:
                values.append(text)

    if category == "business":
        additional = ["Column H", "Column I", "Column G"]
    elif category == "broadband":
        additional = ["Column G", "Column H", "Column F"]
    else:
        additional = ["Unnamed: 11", "Column L", "Column K", "Column J"]

    for key in additional:
        text = as_text(original.get(key, ""))
        if text and text not in values:
            values.append(text)

    return " | ".join(values)


def excel_col(col):
    """Convert column number (1-based) to Excel letters."""
    letters = ""
    while col:
        col, remainder = divmod(col - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def get_rows(ws, category):
    """Extract and parse all customer records from a worksheet."""
    stream = ws.iter_rows(values_only=True)
    initial = []

    for _ in range(20):
        row = next(stream, None)
        if row is None:
            break
        initial.append(row)

    if not initial:
        return []

    header_row = scan_header(initial)

    headers = []
    seen = Counter()

    for col, value in enumerate(initial[header_row - 1], 1):
        raw = as_text(value)
        name = raw or f"Column {excel_col(col)}"

        seen[name] += 1
        if seen[name] == 1:
            headers.append(name)
        else:
            headers.append(f"{name} ({seen[name]})")

    output = []

    for row_number, values in enumerate(
        chain(initial[header_row:], stream),
        header_row + 1
    ):
        if not values or not any(values):
            continue

        original = dict(
            zip(
                headers,
                (as_text(value) for value in values)
            )
        )

        name = first(
            original,
            [
                "full_name", "student_name", "customer_name", "name",
                "applicant_name", "contact_person", "student", "customer"
            ]
        )

        if not is_real_name(name):
            name = ""
            for val in values:
                text_val = as_text(val)
                if is_real_name(text_val):
                    name = text_val
                    break

        raw_phone = first(
            original,
            [
                "phone_number", "phone", "mobile", "mobile_number",
                "contact_number", "contact_no", "telephone", "Unnamed: 5",
                "p:+94740217617", "Column E", "Column F"
            ]
        )

        if (
            not raw_phone
            and category == "education"
            and ws.title.strip().upper() == "CAIT"
        ):
            raw_phone = as_text(values[4] if len(values) > 4 else "")

        if not raw_phone:
            for val in values:
                p_cand = phone_text(val)
                if p_cand:
                    raw_phone = p_cand
                    break

        phone = phone_text(raw_phone)

        email = first(
            original,
            ["email", "email_address", "mail", "Unnamed: 3", "Column D"]
        )

        if not phone and not email:
            continue

        if not name:
            name = "Unknown Lead"

        feedback = find_feedback_column(original, category)

        extra = first(
            original,
            [
                "2nd Call Remarks", "2nd call round", "2nd Call Status",
                "1st Call Status", "Remarks", "Call Remarks",
                "Customer Remarks", "Comments", "Notes", "Follow Up Remarks"
            ]
        )
        call = first(
            original,
            [
                "Call Status", "1st Call Status", "2nd Call Status",
                "Call Outcome", "Not Answered", "Status", "Lead Status"
            ]
        )

        created_at = first(original, ["created_time", "created_at", "date", "timestamp"])

        potential_level = first(
            original,
            ["potential_level", "potential_level_10", "priority", "level", "Unnamed: 10", "L"]
        )
        potential_course = first(
            original,
            [
                "potential_course", "uh_all", "degree",
                "which_degree_program_are_you_interested_in",
                "please_mention_which_degree_program_you_want_to_apply_for",
                "what_programme_are_you_interested_in",
                "which_british_degree_program_are_you_interested_in",
                "what_programme_are_you_interested_in?",
                "which_british_degree_program_are_you_interested_in?",
                "course", "Unnamed: 9"
            ]
        )

        selected, score, reason, disposition = evaluate(
            category,
            feedback,
            extra,
            call,
            created_at,
            potential_level=potential_level,
            potential_course=potential_course,
            sheet_name=ws.title
        )

        key = re.sub(r"\D", "", phone) or email.lower()

        output.append({
            "original": original,
            "name": name,
            "phone": phone,
            "email": email,
            "feedback": feedback,
            "sheet": ws.title,
            "row": row_number,
            "key": key,
            "selected": selected,
            "score": score,
            "reason": reason,
            "disposition": disposition,
            "headers": headers
        })

    return output


def analyze(content, category):
    try:
        book = load_workbook(
            BytesIO(content),
            read_only=True,
            data_only=True
        )

    except Exception as exc:
        raise HTTPException(
            422,
            f"Cannot read workbook: {exc}"
        )

    all_rows = []
    warnings = []

    regional_exists = any(
        ws.title.strip().lower() != "master list"
        for ws in book.worksheets
    )

    for ws in book.worksheets:
        if (
            category == "business"
            and regional_exists
            and ws.title.strip().lower() == "master list"
        ):
            warnings.append("Business Master List skipped to prevent duplicates.")
            continue

        try:
            rows = get_rows(ws, category)
            all_rows.extend(rows)

        except ValueError as exc:
            warnings.append(f"{ws.title}: {exc}")

    book.close()

    if not all_rows:
        raise HTTPException(
            422,
            "No recognized customer rows found. Check category and Excel headers."
        )

    uniques = {}

    for record in all_rows:
        if category == "education":
            key = (record["sheet"], record["key"])
        else:
            key = record["key"]

        previous = uniques.get(key)

        if previous is None:
            uniques[key] = record

        elif (
            int(record["selected"]),
            record["score"],
            len(record["feedback"])
        ) > (
            int(previous["selected"]),
            previous["score"],
            len(previous["feedback"])
        ):
            uniques[key] = record

    items = list(uniques.values())
    selected = [record for record in items if record["selected"]]

    selected.sort(key=lambda record: record["score"], reverse=True)

    return {
        "records": selected,
        "total_rows": len(all_rows),
        "unique_rows": len(items),
        "excluded_rows": len(items) - len(selected),
        "warnings": warnings
    }


def safe_excel_value(value):
    text = as_text(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def build_export(result):
    wb = Workbook()
    wb.remove(wb.active)

    grouped = {}
    for item in result["records"]:
        grouped.setdefault(item["sheet"], []).append(item)

    for sheet_name, group in grouped.items():
        title = (sheet_name[:19] + " - Top Leads")[:31]
        ws = wb.create_sheet(title=title)

        original_headers = group[0]["headers"]

        front_headers = [
            "Priority Score",
            "Student / Customer Name",
            "Phone Number",
            "Why Top Lead?",
            "Disposition",
            "Original Feedback",
            "Source Row"
        ]

        headers = front_headers + original_headers
        ws.append(headers)

        for item in group:
            values = [
                item["score"],
                item["name"],
                item["phone"],
                item["reason"],
                item.get("disposition", "Potential Lead"),
                item["feedback"],
                item["row"]
            ]

            values += [
                item["original"].get(header, "")
                for header in original_headers
            ]

            ws.append([safe_excel_value(value) for value in values])

        ws.freeze_panes = "D2"
        ws.auto_filter.ref = ws.dimensions

        for cell in ws[1]:
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = PatternFill("solid", fgColor="163A5F")
            cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")

        widths = {
            1: 15, 2: 30, 3: 22, 4: 65, 5: 25, 6: 70, 7: 14
        }

        for index, header in enumerate(headers, 1):
            width = widths.get(index, min(36, max(15, len(header) + 3)))
            ws.column_dimensions[excel_col(index)].width = width

        for row in ws.iter_rows(min_row=2):
            row[0].alignment = Alignment(horizontal="center", vertical="top")
            row[2].number_format = "@"
            row[3].alignment = Alignment(wrap_text=True, vertical="top")
            row[4].alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[row[0].row].height = 45

    if not grouped:
        ws = wb.create_sheet("Top Leads")
        ws.append(["Result"])
        ws.append(["No leads met the evidence-based selection rules."])

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return buffer


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "categories": sorted(CATEGORIES)
    }


@app.post("/api/analyze")
async def analyze_file(
    category: Annotated[str, Form()],
    file: Annotated[UploadFile, File()]
):
    if category not in CATEGORIES:
        raise HTTPException(
            400,
            "Select Education, Business, or Broadband"
        )

    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(
            400,
            "Please upload an .xlsx Excel file"
        )

    content = await file.read(MAX_BYTES + 1)

    if len(content) > MAX_BYTES:
        raise HTTPException(
            413,
            "File too large; maximum is 15 MB"
        )

    result = analyze(content, category)

    token = str(uuid.uuid4())
    RESULTS[token] = result

    if len(RESULTS) > 15:
        del RESULTS[next(iter(RESULTS))]

    return {
        "analysis_id": token,
        "category": category,
        "total_rows": result["total_rows"],
        "unique_rows": result["unique_rows"],
        "top_leads": len(result["records"]),
        "excluded_rows": result["excluded_rows"],
        "warnings": result["warnings"],
        "rows": [
            {
                "sheet": record["sheet"],
                "row": record["row"],
                "score": record["score"],
                "name": record["name"],
                "phone": record["phone"],
                "reason": record["reason"],
                "disposition": record["disposition"],
                "original": record["original"]
            }
            for record in result["records"]
        ]
    }


@app.get("/api/export/{analysis_id}")
def export(analysis_id: str):
    result = RESULTS.get(analysis_id)

    if result is None:
        raise HTTPException(
            404,
            "Analysis expired. Upload the file again."
        )

    return StreamingResponse(
        build_export(result),
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition":
            'attachment; filename="SLT_Top_Leads.xlsx"'
        }
    )
