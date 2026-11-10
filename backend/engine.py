"""Priority-based evidence lead qualification engine with dynamic column mapping."""

import re
from datetime import datetime, timezone

# 1. Negative & Rejection Patterns
NEGATIVE = (
    r'\b(?:not\s+(?:interested|required|needed|willing|looking)'
    r'|no\s+(?:need|requirement|interest)'
    r'|don.t\s+(?:need|want)'
    r'|not\s+requested|wrong\s+number'
    r'|invalid\s+number|ringing\s+not\s+answered'
    r'|cancelled|canceled|mistakenly'
    r'|not\s+our\s+requirement'
    r'|epa\s+kiwwa|kemathi\s+n[ae]|ganan\s+wadi)\b'
)

# 2. Education-Specific Disqualification Patterns
EDU_MISMATCH = (
    r'\b(?:looking\s+for\s+(?:a\s+)?job'
    r'|job\s+(?:vacancy|opportunity)|apply\s+for\s+job|cv\s+submitted'
    r'|grade\s+[1-9]\b|11\s+years\s+old'
    r'|school\s+admission|school\s+student'
    r'|qs\s+courses'
    r'|already\s+selected\s+for\s+'
    r'(?:kelaniya|another)\s+university)\b'
)

# 3. Telecom Infrastructure Blockers (Broadband & Business)
INFRA_BLOCKER = (
    r'\b(?:(?:new\s+)?fdp\s+(?:pending|required|full|needed)'
    r'|(?:dp|distribution\s+point)\s+(?:full|pending|overflow|needed)'
    r'|no\s+(?:free\s+)?(?:dp|fdp|port)|no\s+dp\b'
    r'|cabinet\s+(?:full|pending|needed)'
    r'|out\s+of\s+coverage|no\s+coverage|distance\s+too\s+far'
    r'|no\s+(?:fiber|fibre|line)\s+(?:coverage|route|facility)'
    r'|no\s+telecom\s+line\s+is\s+available'
    r'|line\s+doesn.t\s+exsi?est)\b'
)

# 4. Ambiguous Intent / Undecided / Callback Later
FOLLOW_UP_AMBIGUOUS = (
    r'\b(?:(?:need|have)\s+to\s+ask\s+(?:father|mother|parents|family|boss|management|sister|daughter|son)'
    r'|discuss\s+with\s+(?:her|his)?\s*parents|will\s+discuss'
    r'|call\s+back\s+later|call\s+later|ask(?:ed)?\s+to\s+call\s+later|call\s+back\b'
    r'|will\s+decide\s+next\s+week|will\s+decide|decision\s+pending|still\s+thinking'
    r'|thinking\s+about\s+it|not\s+decided\s+yet|check\s+and\s+inform'
    r'|will\s+inform\s+later|will\s+inform|passe\s+call\s+karanna|passe\s+gannam'
    r'|check\s+with\s+available\s+dates|call\s+try\s+again|mother\s+said|father\s+said)\b'
)


def hit(text, pattern):
    return bool(re.search(pattern, text or '', re.I))


def is_iso_date_or_slug(val):
    """Check if a string value is an ISO Timestamp or Course Slug mistakenly placed in Name field."""
    s = str(val or '').strip()
    if not s:
        return True
    if re.match(r'^\d{4}-\d{2}-\d{2}T', s):
        return True
    if re.match(r'^(?:hnd_|cait_|uh_|bsc_|msc_)', s, re.I):
        return True
    return False


def has_positive_evidence(category, text):
    """Detect whether any positive intent signals exist in feedback text."""
    if category == 'education':
        return hit(
            text,
            r'\b(?:registered|registration|course\s+fee\s+paid|paid|payment|deposit|enrolled'
            r'|will\s+register|ready\s+to\s+register|will\s+apply|wants?\s+to\s+register'
            r'|interested|seeking|applying|apply|top[ -]?up|degree|hnd|cait|transcripts?)\b'
        )
    elif category == 'business':
        return hit(
            text,
            r'\b(?:applied|application|order|payment|paid|advance|deposit'
            r'|quotation|quote|proposal|site\s+survey|feasibility|meeting|visit'
            r'|dia|vpn|pabx|ftth|ffth|fth|fttb|fiber|fibre|leased\s+line)\b'
        )
    elif category == 'broadband':
        return hit(
            text,
            r'\b(?:applied|application|order|payment|paid|deposit|advance|\d+\s*[/=]'
            r'|migration|copper|megaline|fiber|fibre|ftth|ffth|fth|peotv|connection)\b'
        )
    return False


def detect_education_course(sheet_name, potential_course, text):
    """Identify course pathway (UH Degree, HND, or CAIT) from workbook metadata and feedback."""
    combined = f'{sheet_name} {potential_course} {text}'.lower()
    if hit(combined, r'(?:\buh\b|uh_|hertfordshire|bsc|beng|top[ -]?up\s+degree|degree)'):
        return 'UH Degree'
    if hit(combined, r'(?:\bhnd\b|hnd_|btec|higher\s+national\s+diploma)'):
        return 'HND'
    if hit(combined, r'(?:\bcait\b|cait_|applied\s+it)'):
        return 'CAIT'
    return ''


def check_2nd_call_priority(second_remarks):
    """Prioritize latest tele-calling follow-up remarks in Education UH sheets."""
    s2 = str(second_remarks or '').strip().lower()
    if not s2:
        return None

    # Rejection recorded on 2nd call overrides earlier positive inquiries
    if hit(s2, r'\b(?:reject(?:ed)?|not\s+interested|not\s+intersted|uni\s+selected|joined\s+onther\s+uni|selected\s+another\s+course|cut\s+the\s+call)\b'):
        return False, 0, 'Declined / Rejected on 2nd Call Follow-up', 'Declined / Not Interested'

    # Follow-up requested on 2nd call
    if hit(s2, r'\b(?:call\s+back\s+later|inform\s+later|will\s+inform|call\s+back|not\s+decided)\b'):
        return False, 35, 'Follow-up required on 2nd Call: Customer requested callback / will inform later', 'Follow-up Required'

    return None


def evaluate_education(text, course_tag):
    """Category-specific qualification logic for Education (CAIT, HND, UH)."""
    if hit(text, EDU_MISMATCH):
        return False, 0, '', 'Not a suitable education lead'

    tag_suffix = f' ({course_tag})' if course_tag else ''

    # Tier 1 (HOT): Confirmed Purchase / Registration / Fee Paid (Score 90)
    # Note: Transcripts sent is strictly excluded from Tier 1 and classified as WARM below.
    if hit(text, r'\b(?:registered|registration\s+(?:confirmed|completed|done)|course\s+fee\s+paid|paid|14\s+payment|next\s+week\s+payment|deposit|register(?:ed)?\s+for\s+new\s+batch|enrolled|admission\s+confirmed)\b'):
        return True, 90, f'Highest Priority: Customer registered or made a payment{tag_suffix}', 'Potential Lead'

    # Tier 2A (WARM): Direct Intent to Register (Score 70)
    if hit(text, r'\b(?:will\s+register|ready\s+to\s+register|will\s+apply|wants?\s+to\s+register|visiting\s+campus\s+to\s+register|coming\s+for\s+registration|enrolling\s+next\s+batch|joining\s+next\s+batch|join\s+the\s+next\s+batch)\b'):
        return True, 70, f'High Intent: Customer intends to register{tag_suffix}', 'Potential Lead'

    # Tier 2B (WARM): Transcripts Submitted (Pending Approval) (Score 70)
    if hit(text, r'\b(?:sent\s+(?:me\s+)?(?:his|her)?\s*transcripts?|transcripts?\s+(?:sent|submitted)|pending\s+approval)\b'):
        return True, 70, f'Warm Lead: Academic transcripts submitted (pending approval){tag_suffix}', 'Potential Lead'

    # Tier 2C (WARM): Academic Eligibility + Course Interest / Top-Up Pathway (Score 70)
    has_eligibility = hit(text, r'\b(?:nvq(?:\s+level\s+[4-7])?|slt\s+staff|staff\s+child|al\s+maths|a/l\s+(?:passed|maths|results|bio|commerce|tech)|pending\s+a/?l|icbt|hnd\s+completed|completed\s+diploma|german\s+tec)\b')
    has_course_interest = hit(text, r'\b(?:interested\s+in|looking\s+for|seeking|applying\s+for|inquired\s+about|wants?\s+(?:to\s+do|to\s+join)|top[ -]?up|degree|hnd|cait|foundation)\b')

    if has_eligibility and (has_course_interest or course_tag):
        return True, 70, f'High Intent / Qualified candidate (Academic eligibility with course interest){tag_suffix}', 'Potential Lead'

    # Academic eligibility alone without course interest (Score 30, below 50 cutoff)
    if has_eligibility:
        return False, 30, 'Eligibility noted (NVQ/AL/Staff): Pending course selection', 'Follow-up Required'

    # Tier 3 (WARM): Specific Course Interest, Intake Inquiry, or Callback Requested (Score 50)
    if hit(text, r'\b(?:interested\s+in|looking\s+for|seeking|applying\s+for|inquired\s+about)\s+.*?\b(?:cait|hnd|btec|uh|hertfordshire|degree|top[ -]?up|foundation|weekend|online)\b|\b(?:cait|btec|hnd|uh\b|hertfordshire|top[ -]?up\s+degree)\b'):
        return True, 50, f'Customer expressed specific course interest{tag_suffix}', 'Potential Lead'

    if hit(text, r'\b(?:next\s+intake|march\s+intake|october\s+intake|weekend\s+batch|evening\s+batch|intake\s+details)\b'):
        return True, 50, f'Customer inquired about upcoming intake / batch schedule{tag_suffix}', 'Potential Lead'

    if hit(text, r'\b(?:callback\s+requested|call\s+back|asked\s+to\s+call|call\s+tomorrow|call\s+after\s+\d+|wants\s+course\s+counselling)\b'):
        return True, 50, f'Callback requested for course counselling{tag_suffix}', 'Potential Lead'

    # Tier 4: Informational / WhatsApp (Score 20, below 50 cutoff)
    if hit(text, r'\b(?:sent\s+details|details\s+shared|whatsapp|wtsp|watsapp)\b'):
        return False, 20, 'Details sent via WhatsApp', 'Low intent / general inquiry excluded'

    return False, 0, '', 'Low intent / general inquiry excluded'


def evaluate_business(text):
    """Category-specific qualification logic for SME & Corporate Connectivity."""
    # Tier 1 (HOT): Confirmed Application, Order Placed, Contract Signed, Payment (Score 90)
    if hit(text, r'\b(?:payment\s+(?:collected|received|made)|paid|deposit\s+(?:collected|paid|received)|advance\s+(?:collected|paid)|(?:\d+(?:,\d+)?\s*(?:/=|rs\.?|lkr))\s*(?:collected|paid|received))\b'):
        return True, 90, 'Payment/Deposit collected', 'Potential Lead'

    if hit(text, r'\b(?:applied\s+for\s+an?\s+ff?tth|applied(?:\s+for)?|application\b.*?\b(?:submitted|collected)|order\s+(?:placed|confirmed)|(?:contract|agreement)\s+(?:signed|confirmed)|signed\s+(?:contract|agreement))\b'):
        return True, 90, 'Order/Application submitted or contract signed', 'Potential Lead'

    # Tier 2 (WARM): Visit Arranged, Quotation, Site Survey, Technical Feasibility (Score 70)
    # Note: "visit arranged" and "site visit arranged" are strictly classified as WARM (Score 70), not HOT.
    if hit(text, r'\b(?:site\s+survey(?:\s+(?:requested|arranged|done))?|visit\s+arranged|site\s+visit\s+arranged|customer\s+visit\s+on|visit\s+arranged\s+on|customer\s+will\s+give\s+date\s+for\s+site\s+visit|site\s+visit|technical\s+visit|meeting\s+arranged|appointment\s+scheduled)\b'):
        return True, 70, 'Warm Lead: Site visit arranged / site survey arranged or customer visit scheduled', 'Potential Lead'

    if hit(text, r'\b(?:(?:requested|wants?|needs?)\s+quotation|quotation\s+(?:requested|sent|needed)|requested\s+quote|proposal\s+(?:requested|sent)|commercial\s+proposal|feasibility\s+(?:check|requested|done|approved))\b'):
        return True, 70, 'Quotation/Commercial proposal requested or feasibility verified', 'Potential Lead'

    # Tier 3 (WARM): Specific Enterprise Product Request (Score 50)
    if hit(text, r'\b(?:dia\b|dedicated\s+internet(?: access)?|ip[ -]?vpn|leased\s+line|point\s+to\s+point|p2p\b|mpls\b|pabx\b|cloud\s+pbx|hosted\s+pbx|sip\s+trunk|hunting\s+line|e1\s+line|pri\s+line|enterprise\s+voice|biz\s+broadband|business\s+broadband|business\s+fiber|corporate\s+package|fiber|fibre|ftth|ffth|fth|fttb|fttc|fttx|need\s+telephone\s+wiring|need\s+voice\s+line|reconnection\s+of\s+fiber|connection\s+requested)\b'):
        return True, 50, 'Specific enterprise connectivity inquiry / Connection requested', 'Potential Lead'

    return False, 0, '', 'Low intent / general inquiry excluded'


def evaluate_broadband(text):
    """Category-specific qualification logic for Broadband & FTTH Migration."""
    # Infrastructure Hold Check
    if hit(text, INFRA_BLOCKER):
        return False, 0, 'Infrastructure blocker: Network capacity or coverage pending (DP Full / FDP Pending / No Coverage)', 'Infrastructure Hold'

    # Tier 1 (HOT): Confirmed Application, Order Placed, Payment Collected (Score 90)
    if hit(text, r'\b(?:payment\s+(?:collected|received|made|done)|paid|deposit\s+(?:collected|paid|received)|advance\s+(?:collected|paid|received)|(?:\d+(?:,\d+)?\s*(?:/=|rs\.?|lkr))\s*(?:collected|paid|received)|agreed\s+to\s+pay|payment\s+pending)\b'):
        return True, 90, 'Payment/Deposit collected', 'Potential Lead'

    if hit(text, r'\b(?:applied(?:\s+for)?|application\b.*?\b(?:submitted|collected)|order\s+(?:placed|confirmed))\b'):
        return True, 90, 'Order/Application submitted', 'Potential Lead'

    # Tier 2 (WARM): Migration Request, Ready to Connect, Visit Agreed (Score 70)
    if hit(text, r'\b(?:migration\s+(?:requested|confirmed|arranged)|(?:copper|megaline|lte)\s+(?:to\s+fiber|migration)|upgrade\s+(?:to\s+fiber|from\s+(?:copper|megaline|lte))|change\s+the\s+ownerhip|requests?\s+a\s+fiber|feasibility\s+approved|ready\s+to\s+(?:pay|connect|install)|visit\s+to\s+the\s+office|will\s+visit|need\s+to\s+visit|will\s+send\s+location)\b'):
        return True, 70, 'Fiber migration requested or customer ready for connection', 'Potential Lead'

    # Tier 3 (WARM): Specific Connection Request, PeoTV, or Package Inquiry (Score 50)
    if hit(text, r'\b(?:fiber|fibre|ftth|ffth|fth|fttb|fttc|fttx|peotv|new\s+connection|connection\s+requested)\b'):
        return True, 50, 'Specific connection request / Meeting arranged', 'Potential Lead'

    return False, 0, '', 'Low intent / general inquiry excluded'


def evaluate(
    category,
    feedback,
    extra='',
    call_status='',
    created_at='',
    potential_level='',
    potential_course='',
    sheet_name=''
):
    """
    Main lead qualification evaluation function.
    Guarantees all output scores are strictly clamped between 0 and 100.
    """
    fb = str(feedback or '').strip()
    extra = str(extra or '').strip()
    call = str(call_status or '').strip()
    p_level = str(potential_level or '').strip().upper()
    p_course = str(potential_course or '').strip()

    text = ' | '.join(
        value for value in (fb, extra, call, p_course) if value
    ).lower()

    if not text and not p_level:
        return False, 0, '', 'No feedback evidence'

    # 1. Already completed service check
    if hit(
        text,
        r'\b(?:already\s+(?:installed|connected|enrolled|have|available)'
        r'|installation\s+completed|connection\s+activated'
        r'|course\s+completed)\b'
    ):
        return False, 0, '', 'Already completed'

    # 2. Call status negative check (explicit wrong number or invalid number)
    if hit(call, r'\b(?:wrong\s+number|invalid\s+number)\b'):
        return False, 0, '', 'Declined / Not Interested'

    # 3. UH 2nd Call Remarks prioritization (latest call follow-up overrides earlier rounds)
    if category == 'education':
        second_call_result = check_2nd_call_priority(extra)
        if second_call_result is not None:
            return second_call_result

    # 4. Negative & Conflicting Evidence Check
    has_negative = hit(text, NEGATIVE)
    has_positive = has_positive_evidence(category, text)

    if has_negative:
        if has_positive:
            # Conflicting signals: positive intent exists alongside negative feedback
            return (
                False,
                25,
                'Conflicting evidence: Positive interest recorded alongside negative remarks (requires manual review)',
                'Manual Review - Conflicting Evidence'
            )
        else:
            return False, 0, '', 'Declined / Not Interested'

    # 5. Infrastructure Blocker Check for Broadband and Business
    if category in ['broadband', 'business'] and hit(text, INFRA_BLOCKER):
        return (
            False,
            0,
            'Infrastructure blocker: Network capacity or coverage pending (DP Full / FDP Pending / No Coverage)',
            'Infrastructure Hold'
        )

    # 6. Ambiguous Intent / Undecided / Callback Later Check
    if hit(text, FOLLOW_UP_AMBIGUOUS):
        # Only treat as Follow-up Required if no confirmed payment/registration/order
        is_confirmed = hit(
            text,
            r'\b(?:registered|course\s+fee\s+paid|paid|payment\s+collected|\d+\s*[/=]\s*collected|order\s+confirmed|contract\s+signed|agreement\s+signed)\b'
        )
        if not is_confirmed:
            return (
                False,
                35,
                'Follow-up required: Customer undecided / requested callback later',
                'Follow-up Required'
            )

    # 7. Category-Specific Evaluation
    course_tag = detect_education_course(sheet_name, p_course, text)

    if category == 'education':
        cat_selected, cat_score, cat_reason, cat_disp = evaluate_education(text, course_tag)
    elif category == 'business':
        cat_selected, cat_score, cat_reason, cat_disp = evaluate_business(text)
    elif category == 'broadband':
        cat_selected, cat_score, cat_reason, cat_disp = evaluate_broadband(text)
    else:
        return False, 0, '', 'Unknown category'

    if cat_disp in ['Not a suitable education lead', 'Infrastructure Hold']:
        return cat_selected, cat_score, cat_reason, cat_disp

    # 8. Potential Level Supporting Factor (Within 0-100 range)
    # Potential Level acts as a supporting adjustment, not an arbitrary 100-point jump
    support_delta = 0
    base_flag_reason = ''
    if p_level == 'H':
        if cat_score > 0:
            support_delta = 10
            base_flag_reason = ' (High Potential Flag)'
        else:
            cat_score = 100
            base_flag_reason = 'Marked as High Potential Lead (H)'
            cat_disp = 'Potential Lead'
    elif p_level == 'M':
        if cat_score > 0:
            support_delta = 5
        else:
            cat_score = 50
            base_flag_reason = 'Marked as Medium Potential Lead (M)'
            cat_disp = 'Potential Lead'
    elif p_level == 'L':
        if cat_score > 0:
            support_delta = -5

    total_score = max(0, min(100, cat_score + support_delta))
    reason = f'{cat_reason}{base_flag_reason}'.strip()

    # Cutoff threshold check (Score >= 50 qualifies as top lead)
    if total_score < 50:
        return False, total_score, reason, cat_disp

    # 9. Recency Penalty (Deduct 10 points if lead is older than 30 days)
    if created_at:
        try:
            date = datetime.fromisoformat(str(created_at).replace('Z', '+00:00'))
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - date).days
            if age > 30:
                total_score = max(0, total_score - 10)
                reason += ' (Historical lead)'
        except (ValueError, TypeError):
            pass

    if total_score < 50:
        return False, total_score, reason, 'Historical lead requires reconfirmation'

    return True, total_score, reason, 'Potential Lead'
