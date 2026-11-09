"""Priority-based evidence lead qualification engine with dynamic column mapping."""

import re
from datetime import datetime, timezone
import pandas as pd

NEGATIVE = (
    r'\b(?:not\s+(?:interested|required|needed|willing|looking)'
    r'|no\s+(?:need|requirement|interest)'
    r'|don.t\s+(?:need|want)'
    r'|not\s+requested|wrong\s+number'
    r'|invalid\s+number|ringing\s+not\s+answered'
    r'|cancelled|canceled|mistakenly'
    r'|not\s+our\s+requirement)\b'
)

EDU_MISMATCH = (
    r'\b(?:looking\s+for\s+(?:a\s+)?job'
    r'|job\s+(?:vacancy|opportunity)'
    r'|grade\s+[1-9]\b'
    r'|school\s+admission|school\s+student'
    r'|qs\s+courses'
    r'|already\s+selected\s+for\s+'
    r'(?:kelaniya|another)\s+university)\b'
)


def hit(text, pattern):
    return bool(re.search(pattern, text or '', re.I))


def is_iso_date_or_slug(val):
    """Check if a string value is an ISO Timestamp or Course Slug mistakenly placed in Name field."""
    s = str(val or '').strip()
    if not s:
        return True
    # ISO Timestamp format regex (e.g. 2026-06-25T13:46:41+05:30)
    if re.match(r'^\d{4}-\d{2}-\d{2}T', s):
        return True
    # Course Slugs regex (e.g. hnd_in_electrical_&_electronics...)
    if re.match(r'^(?:hnd_|cait_|uh_|bsc_|msc_)', s, re.I):
        return True
    return False


def extract_dynamic_fields(row):
    """
    Dynamically extracts customer name, email, phone, and city from a row
    regardless of index shifts or raw Google Form column changes.
    """
    row_dict = {str(k).strip(): (v if pd.notna(v) else '') for k, v in row.items()}
    
    name = ''
    email = ''
    phone = ''
    city = ''
    
    # 1. Identify Email
    for k, v in row_dict.items():
        if 'email' in k.lower() and str(v).strip():
            email = str(v).strip()
            break

    # 2. Identify Phone Number
    for k, v in row_dict.items():
        if ('phone' in k.lower() or 'mobile' in k.lower() or 'contact' in k.lower()) and str(v).strip():
            phone = str(v).strip()
            break

    # 3. Identify Full Name (Validating against timestamps & course slugs)
    for k, v in row_dict.items():
        k_lower = k.lower()
        if ('full_name' in k_lower or 'student' in k_lower or 'customer name' in k_lower or 'name' in k_lower) and 'course' not in k_lower:
            val_str = str(v).strip()
            if not is_iso_date_or_slug(val_str):
                name = val_str
                break

    # 4. Fallback search across row values if Name is shifted into another column
    if not name:
        for k, v in row_dict.items():
            val_str = str(v).strip()
            # If value looks like a real human name (2+ words, no '@', no phone digits, not slug/date)
            if (
                val_str 
                and not is_iso_date_or_slug(val_str)
                and '@' not in val_str 
                and not re.search(r'\d{5,}', val_str) 
                and len(val_str.split()) >= 2
                and 'sent' not in val_str.lower()
                and 'call' not in val_str.lower()
            ):
                name = val_str
                break

    return {
        'name': name if name else 'N/A',
        'email': email,
        'phone': phone,
        'city': city
    }


def evaluate(
    category,
    feedback,
    extra='',
    call_status='',
    created_at='',
    potential_level='',
    potential_course=''
):
    fb = str(feedback or '').strip()
    extra = str(extra or '').strip()
    p_level = str(potential_level or '').strip().upper()
    p_course = str(potential_course or '').strip()

    text = ' | '.join(
        value for value in (fb, extra, p_course) if value
    ).lower()

    if not text and not p_level:
        return False, 0, '', 'No feedback evidence'

    if hit(text, NEGATIVE):
        return False, 0, '', 'Declined / Not Interested'

    if hit(
        text,
        r'\b(?:already\s+(?:installed|connected|enrolled)'
        r'|installation\s+completed|connection\s+activated'
        r'|course\s+completed)\b'
    ):
        return False, 0, '', 'Already completed'

    score = 0
    reason = ''

    # Base score from explicit potential level (H=100, M=50, L=10)
    if p_level == 'H':
        score += 100
        reason = 'Marked as High Potential Lead (H)'
    elif p_level == 'M':
        score += 50
        reason = 'Marked as Medium Potential Lead (M)'
    elif p_level == 'L':
        score += 10

    # EDUCATION CATEGORY SCORING & PRIORITY
    if category == 'education':
        if hit(text, EDU_MISMATCH):
            return False, 0, '', 'Not a suitable education lead'

        # Tier 1: Highest Priority (Registered / Paid / Batch Confirmed) - Score 90-120
        if hit(text, r'\b(?:registered|registration\s+confirmed|paid|payment|deposit|register\s+for\s+new\s+batch)\b'):
            score += 90
            reason = 'Highest Priority: Customer registered or made a payment'

        # Tier 2: Intent to Register / Qualifications (NVQ / AL Maths / ICBT / SLT Staff) - Score 60-80
        elif hit(text, r'\b(?:will\s+register|ready\s+to\s+register|nvq|slt\s+staff|al\s+maths|icbt|hnd\s+completed)\b'):
            score += 70
            reason = 'High Intent / Qualified candidate (NVQ/AL Maths/Staff/Intends to register)'

        # Tier 3: Specific Course Request / Seeking Top-up / Degree - Score 40-50
        elif hit(text, r'\b(?:looking\s+for|interested\s+in|seeking|top[ -]?up|degree|hnd|foundation|weekend|online)\b'):
            score += 40
            reason = 'Customer expressed specific course interest'

        # Tier 4: Details Shared via WhatsApp / Called - Score 20
        elif hit(text, r'\b(?:sent\s+details|details\s+shared|whatsapp|wtsp|watsapp)\b'):
            score += 20
            reason = 'Details sent via WhatsApp'

    # BUSINESS / BROADBAND SCORING
    elif category in ['business', 'broadband']:
        if hit(text, r'\b(?:application\s+(?:submitted|collected)|order\s+(?:placed|confirmed)|payment\s+collected)\b'):
            score += 90
            reason = 'Order/Application submitted'
        elif hit(text, r'\b(?:fiber|ftth|connection\s+requested|visit\s+arranged)\b'):
            score += 50
            reason = 'Specific connection request / Meeting arranged'

    # Threshold score for filtering true top leads (Score >= 50)
    if score < 50:
        return False, 0, '', 'Low intent / general inquiry excluded'

    # Deduct points if lead is older than 30 days
    if created_at:
        try:
            date = datetime.fromisoformat(str(created_at).replace('Z', '+00:00'))
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - date).days
            if age > 30:
                score -= 10
                reason += ' (Historical lead)'
        except (ValueError, TypeError):
            pass

    return True, score, reason, 'Potential Lead'