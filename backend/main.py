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
    return re.sub(
        r"[^a-z0-9]+", "_",
        str(value or "").lower()
    ).strip("_")


def as_text(value):
    if value is None:
        return ""

    if isinstance(value, datetime):
        return value.isoformat(sep=" ")

    return str(value).strip()


def first(record, names):
    for name in names:
        for key, value in record.items():
            if norm(key) == norm(name) and as_text(value):
                return as_text(value)
    return ""


def scan_header(rows):
    # Header may start on the first or second row.
    for rownum, row in enumerate(rows[:20], 1):
        cells = [norm(value) for value in row[:60]]

        if "full_name" in cells or "student_name" in cells or "customer_name" in cells or (
            any("name" in c for c in cells) and ("email" in cells or "phone_number" in cells or "phone" in cells)
        ):
            return rownum

    raise ValueError(
        "No valid name/email/phone header found in first 20 rows"
    )


def is_real_name(value):
    name = as_text(value).strip()

    if not name or len(name) < 3 or len(name) > 110:
        return False

    if re.match(
        r"^(?:\d+|\d{4}[-/]\d{1,2}|p\s*:|"
        r"\+?94\d+|0\d{9})$",
        name,
        re.I
    ):
        return False

    invalid_names = {
        "full_name",
        "name",
        "data_science",
        "robotics_ai",
        "electrical_electronic_engineering",
        "computing",
        "date"
    }

    if norm(name) in invalid_names:
        return False

    if "@" in name or "http" in name.lower():
        return False

    return any(char.isalpha() for char in name)


def phone_text(value):
    phone = as_text(value)

    if not phone or isinstance(value, datetime):
        return ""

    digits = re.sub(r"\D", "", phone)

    if 9 <= len(digits) <= 13:
        return phone

    return ""


def find_feedback_column(original, category):
    values = []

    for key, value in original.items():
        if norm(key) in {
            "customer_feedback",
            "feedback",
            "staff_feedback",
            "follow_up_feedback",
            "remarks"
        }:
            text = as_text(value)
            if text:
                values.append(text)

    # Unnamed feedback columns in source workbooks.
    if category == "business":
        additional = ["Column H", "Column I"]
    elif category == "broadband":
        additional = ["Column G", "Column H"]
    else:
        additional = ["Unnamed: 11", "Column L"]

    for key in additional:
        text = as_text(original.get(key, ""))
        if text and text not in values:
            values.append(text)

    return " | ".join(values)


def excel_col(col):
    letters = ""
    while col:
        col, remainder = divmod(col - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def get_rows(ws, category):
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

    # Preserve original Excel header ordering.
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
        original = dict(
            zip(
                headers,
                (as_text(value) for value in values)
            )
        )

        # Extract Name
        name = first(
            original,
            ["full_name", "student_name", "customer_name", "name", "Unnamed: 2"]
        )

        if not is_real_name(name):
            continue

        # Extract Phone
        raw_phone = first(
            original,
            ["phone_number", "phone", "mobile", "contact_number", "Unnamed: 5", "p:+94740217617"]
        )

        # CAIT sheet fallback for phone column
        if (
            not raw_phone
            and category == "education"
            and ws.title.strip().upper() == "CAIT"
        ):
            raw_phone = as_text(values[4] if len(values) > 4 else "")

        phone = phone_text(raw_phone)

        # Extract Email
        email = first(
            original,
            ["email", "email_address", "Unnamed: 3"]
        )

        if not phone and not email:
            continue

        feedback = find_feedback_column(original, category)

        if category == "education":
            extra = first(
                original,
                ["2nd Call Remarks", "2nd call round", "2nd Call Status", "1st Call Status"]
            )
            call = first(
                original,
                ["Call Status", "1st Call Status", "Not Answered"]
            )
        else:
            extra = ""
            call = ""

        created_at = first(original, ["created_time"])
        
        # Capture explicit Potential Level (H / M / L) and Potential Course
        potential_level = first(original, ["potential_level", "potential_level_10", "Unnamed: 10", "L"])
        potential_course = first(original, ["potential_course", "uh_all", "which_degree_program_are_you_interested_in", "please_mention_which_degree_program_you_want_to_apply_for", "Unnamed: 9"])

        selected, score, reason, disposition = evaluate(
            category,
            feedback,
            extra,
            call,
            created_at,
            potential_level=potential_level,
            potential_course=potential_course
        )

        # Key for unique check
        key = re.sub(r"\D", "", phone) or email.lower()

        output.append({
            "original": original,
            "name": name,
            "phone": phone,
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

    # Unique deduplication keeping highest priority score
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

    # Priority Sorting: Score Descending (High Priority First -> Lowest Last)
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

        # Header formatting
        for cell in ws[1]:
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = PatternFill("solid", fgColor="163A5F")
            cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")

        widths = {
            1: 15,  # Priority Score
            2: 30,  # Student / Customer Name
            3: 22,  # Phone Number
            4: 65,  # Why Top Lead?
            5: 70,  # Original Feedback
            6: 14   # Source Row
        }

        for index, header in enumerate(headers, 1):
            width = widths.get(index, min(36, max(15, len(header) + 3)))
            ws.column_dimensions[excel_col(index)].width = width

        # Data formatting
        for row in ws.iter_rows(min_row=2):
            row[0].alignment = Alignment(horizontal="center", vertical="top") # Priority Score
            row[2].number_format = "@" # Phone
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