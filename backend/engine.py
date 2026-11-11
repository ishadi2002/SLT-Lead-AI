"""
SLT Lead Qualification Engine — Powered by Google Gemini AI.

Each lead's feedback text is sent to Gemini with a structured prompt that
mirrors the original rule-based tiers exactly.  Gemini returns a JSON
decision that is parsed and returned with the same interface as before:

    evaluate(...) -> (selected: bool, score: int, reason: str, disposition: str)

Fallback: if the Gemini API key is missing or the call fails for any lead,
the original regex-based rules kick in automatically so the app never breaks.
"""

import os
import re
import json
import logging
from datetime import datetime, timezone
from functools import lru_cache

logger = logging.getLogger(__name__)

# ─── Gemini SDK ───────────────────────────────────────────────────────────────
try:
    import google.generativeai as genai
    _GEMINI_AVAILABLE = True
except ImportError:
    _GEMINI_AVAILABLE = False
    logger.warning("google-generativeai not installed — using rule-based fallback.")


@lru_cache(maxsize=1)
def _get_model():
    """Initialise and cache the Gemini model (called once per process)."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or not _GEMINI_AVAILABLE:
        return None
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        generation_config={
            "temperature": 0.1,          # low randomness → consistent decisions
            "response_mime_type": "application/json",
        },
    )


# ─── Gemini Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are an expert lead-qualification analyst for SLT (Sri Lanka Telecom).
Analyse the customer feedback text provided and decide whether this is a
qualified top lead.  You must reply ONLY with valid JSON — no markdown, no
explanation outside the JSON.

SCORING RULES (apply in order, stop at first match):

EDUCATION category
  Score 90  → customer registered, made a payment, paid deposit, enrolled, admission confirmed.
  Score 70  → will register, ready to register, intends to apply, transcripts submitted, NVQ/AL
              eligibility with course interest, top-up degree interest.
  Score 50  → specific course interest (CAIT/HND/UH/Hertfordshire), next-intake inquiry,
              callback requested for counselling.
  Score 20  → details sent via WhatsApp only.
  Score 0   → not interested, wrong number, job inquiry, school-age student, already enrolled elsewhere.

BUSINESS category
  Score 90  → payment collected, deposit paid, application submitted, order confirmed, contract signed.
  Score 70  → site survey arranged, visit scheduled, quotation requested, feasibility approved.
  Score 50  → specific enterprise product requested (DIA, IP-VPN, leased line, PABX, fiber, FTTH, FTTB).
  Score 0   → not interested, infrastructure blocker (DP full, FDP pending, no coverage).

BROADBAND category
  Score 90  → payment collected, application submitted, order placed.
  Score 70  → migration requested (copper→fiber), customer ready to connect, feasibility approved.
  Score 50  → fiber/FTTH/PeoTV/new connection requested.
  Score 0   → not interested, infrastructure blocker (DP full, FDP pending, out of coverage).

GLOBAL RULES (all categories)
  • If feedback contains BOTH positive AND negative signals → score 25, disposition "Manual Review - Conflicting Evidence", selected false.
  • If feedback contains undecided/callback language (call back later, will decide, need to ask family, will inform) WITHOUT a confirmed payment → score 35, disposition "Follow-up Required", selected false.
  • If the lead already has the service (already installed, already enrolled, course completed) → score 0.
  • Leads with score ≥ 50 are SELECTED (selected: true).
  • Leads with score < 50 are NOT selected (selected: false).
  • potential_level "H" adds 10 points to a non-zero score (or sets score to 100 if score was 0).
  • potential_level "M" adds 5 points to a non-zero score (or sets score to 50 if score was 0).
  • Scores are CLAMPED between 0 and 100.

OUTPUT FORMAT — reply only with this JSON object, nothing else:
{
  "selected": true or false,
  "score": integer 0-100,
  "reason": "one clear sentence explaining why this lead was selected or excluded",
  "disposition": "Potential Lead" | "Follow-up Required" | "Manual Review - Conflicting Evidence" | "Infrastructure Hold" | "Declined / Not Interested" | "Already completed" | "No feedback evidence"
}
"""


def _ask_gemini(category: str, feedback: str, extra: str, call_status: str,
                potential_level: str, potential_course: str, sheet_name: str) -> dict | None:
    """
    Send a single lead to Gemini and parse the JSON response.
    Returns a dict with keys selected/score/reason/disposition, or None on failure.
    """
    model = _get_model()
    if model is None:
        return None

    text_parts = [p for p in [feedback, extra, call_status, potential_course] if p]
    if not text_parts:
        return None

    user_message = (
        f"Category: {category.upper()}\n"
        f"Sheet / Campaign: {sheet_name}\n"
        f"Potential Level: {potential_level or 'N/A'}\n"
        f"Customer Feedback / Remarks:\n{chr(10).join(text_parts)}"
    )

    try:
        response = model.generate_content(
            [{"role": "user", "parts": [SYSTEM_PROMPT + "\n\n" + user_message]}]
        )
        raw = response.text.strip()

        # Strip markdown code fences if Gemini wraps the JSON anyway
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)

        # Validate required keys
        required = {"selected", "score", "reason", "disposition"}
        if not required.issubset(data.keys()):
            raise ValueError(f"Missing keys in Gemini response: {data}")

        data["selected"] = bool(data["selected"])
        data["score"] = max(0, min(100, int(data["score"])))
        return data

    except Exception as exc:
        logger.warning("Gemini call failed (%s) — falling back to rules.", exc)
        return None


# ─── Original Rule-Based Fallback (unchanged) ─────────────────────────────────

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

EDU_MISMATCH = (
    r'\b(?:looking\s+for\s+(?:a\s+)?job'
    r'|job\s+(?:vacancy|opportunity)|apply\s+for\s+job|cv\s+submitted'
    r'|grade\s+[1-9]\b|11\s+years\s+old'
    r'|school\s+admission|school\s+student'
    r'|qs\s+courses'
    r'|already\s+selected\s+for\s+'
    r'(?:kelaniya|another)\s+university)\b'
)

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


def has_positive_evidence(category, text):
    if category == 'education':
        return hit(text, r'\b(?:registered|registration|course\s+fee\s+paid|paid|payment|deposit|enrolled'
                         r'|will\s+register|ready\s+to\s+register|will\s+apply|wants?\s+to\s+register'
                         r'|interested|seeking|applying|apply|top[ -]?up|degree|hnd|cait|transcripts?)\b')
    elif category == 'business':
        return hit(text, r'\b(?:applied|application|order|payment|paid|advance|deposit'
                         r'|quotation|quote|proposal|site\s+survey|feasibility|meeting|visit'
                         r'|dia|vpn|pabx|ftth|ffth|fth|fttb|fiber|fibre|leased\s+line)\b')
    elif category == 'broadband':
        return hit(text, r'\b(?:applied|application|order|payment|paid|deposit|advance|\d+\s*[/=]'
                         r'|migration|copper|megaline|fiber|fibre|ftth|ffth|fth|peotv|connection)\b')
    return False


def detect_education_course(sheet_name, potential_course, text):
    combined = f'{sheet_name} {potential_course} {text}'.lower()
    if hit(combined, r'(?:\buh\b|uh_|hertfordshire|bsc|beng|top[ -]?up\s+degree|degree)'):
        return 'UH Degree'
    if hit(combined, r'(?:\bhnd\b|hnd_|btec|higher\s+national\s+diploma)'):
        return 'HND'
    if hit(combined, r'(?:\bcait\b|cait_|applied\s+it)'):
        return 'CAIT'
    return ''


def check_2nd_call_priority(second_remarks):
    s2 = str(second_remarks or '').strip().lower()
    if not s2:
        return None
    if hit(s2, r'\b(?:reject(?:ed)?|not\s+interested|not\s+intersted|uni\s+selected|joined\s+onther\s+uni|selected\s+another\s+course|cut\s+the\s+call)\b'):
        return False, 0, 'Declined / Rejected on 2nd Call Follow-up', 'Declined / Not Interested'
    if hit(s2, r'\b(?:call\s+back\s+later|inform\s+later|will\s+inform|call\s+back|not\s+decided)\b'):
        return False, 35, 'Follow-up required on 2nd Call: Customer requested callback / will inform later', 'Follow-up Required'
    return None


def _rule_evaluate_education(text, course_tag):
    if hit(text, EDU_MISMATCH):
        return False, 0, '', 'Not a suitable education lead'
    tag = f' ({course_tag})' if course_tag else ''
    if hit(text, r'\b(?:registered|registration\s+(?:confirmed|completed|done)|course\s+fee\s+paid|paid|14\s+payment|next\s+week\s+payment|deposit|register(?:ed)?\s+for\s+new\s+batch|enrolled|admission\s+confirmed)\b'):
        return True, 90, f'Highest Priority: Customer registered or made a payment{tag}', 'Potential Lead'
    if hit(text, r'\b(?:will\s+register|ready\s+to\s+register|will\s+apply|wants?\s+to\s+register|visiting\s+campus\s+to\s+register|coming\s+for\s+registration|enrolling\s+next\s+batch|joining\s+next\s+batch|join\s+the\s+next\s+batch)\b'):
        return True, 70, f'High Intent: Customer intends to register{tag}', 'Potential Lead'
    if hit(text, r'\b(?:sent\s+(?:me\s+)?(?:his|her)?\s*transcripts?|transcripts?\s+(?:sent|submitted)|pending\s+approval)\b'):
        return True, 70, f'Warm Lead: Academic transcripts submitted (pending approval){tag}', 'Potential Lead'
    has_eligibility = hit(text, r'\b(?:nvq(?:\s+level\s+[4-7])?|slt\s+staff|staff\s+child|al\s+maths|a/l\s+(?:passed|maths|results|bio|commerce|tech)|pending\s+a/?l|icbt|hnd\s+completed|completed\s+diploma|german\s+tec)\b')
    has_course_interest = hit(text, r'\b(?:interested\s+in|looking\s+for|seeking|applying\s+for|inquired\s+about|wants?\s+(?:to\s+do|to\s+join)|top[ -]?up|degree|hnd|cait|foundation)\b')
    if has_eligibility and (has_course_interest or course_tag):
        return True, 70, f'High Intent / Qualified candidate (Academic eligibility with course interest){tag}', 'Potential Lead'
    if has_eligibility:
        return False, 30, 'Eligibility noted (NVQ/AL/Staff): Pending course selection', 'Follow-up Required'
    if hit(text, r'\b(?:interested\s+in|looking\s+for|seeking|applying\s+for|inquired\s+about)\s+.*?\b(?:cait|hnd|btec|uh|hertfordshire|degree|top[ -]?up|foundation|weekend|online)\b|\b(?:cait|btec|hnd|uh\b|hertfordshire|top[ -]?up\s+degree)\b'):
        return True, 50, f'Customer expressed specific course interest{tag}', 'Potential Lead'
    if hit(text, r'\b(?:next\s+intake|march\s+intake|october\s+intake|weekend\s+batch|evening\s+batch|intake\s+details)\b'):
        return True, 50, f'Customer inquired about upcoming intake / batch schedule{tag}', 'Potential Lead'
    if hit(text, r'\b(?:callback\s+requested|call\s+back|asked\s+to\s+call|call\s+tomorrow|call\s+after\s+\d+|wants\s+course\s+counselling)\b'):
        return True, 50, f'Callback requested for course counselling{tag}', 'Potential Lead'
    if hit(text, r'\b(?:sent\s+details|details\s+shared|whatsapp|wtsp|watsapp)\b'):
        return False, 20, 'Details sent via WhatsApp', 'Low intent / general inquiry excluded'
    return False, 0, '', 'Low intent / general inquiry excluded'


def _rule_evaluate_business(text):
    if hit(text, r'\b(?:payment\s+(?:collected|received|made)|paid|deposit\s+(?:collected|paid|received)|advance\s+(?:collected|paid)|(?:\d+(?:,\d+)?\s*(?:/=|rs\.?|lkr))\s*(?:collected|paid|received))\b'):
        return True, 90, 'Payment/Deposit collected', 'Potential Lead'
    if hit(text, r'\b(?:applied\s+for\s+an?\s+ff?tth|applied(?:\s+for)?|application\b.*?\b(?:submitted|collected)|order\s+(?:placed|confirmed)|(?:contract|agreement)\s+(?:signed|confirmed)|signed\s+(?:contract|agreement))\b'):
        return True, 90, 'Order/Application submitted or contract signed', 'Potential Lead'
    if hit(text, r'\b(?:site\s+survey(?:\s+(?:requested|arranged|done))?|visit\s+arranged|site\s+visit\s+arranged|customer\s+visit\s+on|visit\s+arranged\s+on|customer\s+will\s+give\s+date\s+for\s+site\s+visit|site\s+visit|technical\s+visit|meeting\s+arranged|appointment\s+scheduled)\b'):
        return True, 70, 'Warm Lead: Site visit arranged / site survey arranged or customer visit scheduled', 'Potential Lead'
    if hit(text, r'\b(?:(?:requested|wants?|needs?)\s+quotation|quotation\s+(?:requested|sent|needed)|requested\s+quote|proposal\s+(?:requested|sent)|commercial\s+proposal|feasibility\s+(?:check|requested|done|approved))\b'):
        return True, 70, 'Quotation/Commercial proposal requested or feasibility verified', 'Potential Lead'
    if hit(text, r'\b(?:dia\b|dedicated\s+internet(?: access)?|ip[ -]?vpn|leased\s+line|point\s+to\s+point|p2p\b|mpls\b|pabx\b|cloud\s+pbx|hosted\s+pbx|sip\s+trunk|hunting\s+line|e1\s+line|pri\s+line|enterprise\s+voice|biz\s+broadband|business\s+broadband|business\s+fiber|corporate\s+package|fiber|fibre|ftth|ffth|fth|fttb|fttc|fttx|need\s+telephone\s+wiring|need\s+voice\s+line|reconnection\s+of\s+fiber|connection\s+requested)\b'):
        return True, 50, 'Specific enterprise connectivity inquiry / Connection requested', 'Potential Lead'
    return False, 0, '', 'Low intent / general inquiry excluded'


def _rule_evaluate_broadband(text):
    if hit(text, INFRA_BLOCKER):
        return False, 0, 'Infrastructure blocker: Network capacity or coverage pending (DP Full / FDP Pending / No Coverage)', 'Infrastructure Hold'
    if hit(text, r'\b(?:payment\s+(?:collected|received|made|done)|paid|deposit\s+(?:collected|paid|received)|advance\s+(?:collected|paid|received)|(?:\d+(?:,\d+)?\s*(?:/=|rs\.?|lkr))\s*(?:collected|paid|received)|agreed\s+to\s+pay|payment\s+pending)\b'):
        return True, 90, 'Payment/Deposit collected', 'Potential Lead'
    if hit(text, r'\b(?:applied(?:\s+for)?|application\b.*?\b(?:submitted|collected)|order\s+(?:placed|confirmed))\b'):
        return True, 90, 'Order/Application submitted', 'Potential Lead'
    if hit(text, r'\b(?:migration\s+(?:requested|confirmed|arranged)|(?:copper|megaline|lte)\s+(?:to\s+fiber|migration)|upgrade\s+(?:to\s+fiber|from\s+(?:copper|megaline|lte))|change\s+the\s+ownerhip|requests?\s+a\s+fiber|feasibility\s+approved|ready\s+to\s+(?:pay|connect|install)|visit\s+to\s+the\s+office|will\s+visit|need\s+to\s+visit|will\s+send\s+location)\b'):
        return True, 70, 'Fiber migration requested or customer ready for connection', 'Potential Lead'
    if hit(text, r'\b(?:fiber|fibre|ftth|ffth|fth|fttb|fttc|fttx|peotv|new\s+connection|connection\s+requested)\b'):
        return True, 50, 'Specific connection request / Meeting arranged', 'Potential Lead'
    return False, 0, '', 'Low intent / general inquiry excluded'


def _rule_based_evaluate(category, feedback, extra, call_status, created_at,
                         potential_level, potential_course, sheet_name):
    """Pure regex rule engine — used as fallback when Gemini is unavailable."""
    fb = str(feedback or '').strip()
    extra = str(extra or '').strip()
    call = str(call_status or '').strip()
    p_level = str(potential_level or '').strip().upper()
    p_course = str(potential_course or '').strip()

    text = ' | '.join(v for v in (fb, extra, call, p_course) if v).lower()

    if not text and not p_level:
        return False, 0, '', 'No feedback evidence'

    if hit(text, r'\b(?:already\s+(?:installed|connected|enrolled|have|available)'
                 r'|installation\s+completed|connection\s+activated|course\s+completed)\b'):
        return False, 0, '', 'Already completed'

    if hit(call, r'\b(?:wrong\s+number|invalid\s+number)\b'):
        return False, 0, '', 'Declined / Not Interested'

    if category == 'education':
        second_call_result = check_2nd_call_priority(extra)
        if second_call_result is not None:
            return second_call_result

    has_negative = hit(text, NEGATIVE)
    has_positive = has_positive_evidence(category, text)

    if has_negative:
        if has_positive:
            return False, 25, 'Conflicting evidence: Positive interest recorded alongside negative remarks (requires manual review)', 'Manual Review - Conflicting Evidence'
        return False, 0, '', 'Declined / Not Interested'

    if category in ['broadband', 'business'] and hit(text, INFRA_BLOCKER):
        return False, 0, 'Infrastructure blocker: Network capacity or coverage pending (DP Full / FDP Pending / No Coverage)', 'Infrastructure Hold'

    if hit(text, FOLLOW_UP_AMBIGUOUS):
        is_confirmed = hit(text, r'\b(?:registered|course\s+fee\s+paid|paid|payment\s+collected|\d+\s*[/=]\s*collected|order\s+confirmed|contract\s+signed|agreement\s+signed)\b')
        if not is_confirmed:
            return False, 35, 'Follow-up required: Customer undecided / requested callback later', 'Follow-up Required'

    course_tag = detect_education_course(sheet_name, p_course, text)

    if category == 'education':
        cat_selected, cat_score, cat_reason, cat_disp = _rule_evaluate_education(text, course_tag)
    elif category == 'business':
        cat_selected, cat_score, cat_reason, cat_disp = _rule_evaluate_business(text)
    elif category == 'broadband':
        cat_selected, cat_score, cat_reason, cat_disp = _rule_evaluate_broadband(text)
    else:
        return False, 0, '', 'Unknown category'

    if cat_disp in ['Not a suitable education lead', 'Infrastructure Hold']:
        return cat_selected, cat_score, cat_reason, cat_disp

    support_delta = 0
    base_flag_reason = ''
    if p_level == 'H':
        support_delta = 10 if cat_score > 0 else 0
        if cat_score == 0:
            cat_score = 100
            base_flag_reason = 'Marked as High Potential Lead (H)'
            cat_disp = 'Potential Lead'
        else:
            base_flag_reason = ' (High Potential Flag)'
    elif p_level == 'M':
        support_delta = 5 if cat_score > 0 else 0
        if cat_score == 0:
            cat_score = 50
            base_flag_reason = 'Marked as Medium Potential Lead (M)'
            cat_disp = 'Potential Lead'
    elif p_level == 'L':
        support_delta = -5 if cat_score > 0 else 0

    total_score = max(0, min(100, cat_score + support_delta))
    reason = f'{cat_reason}{base_flag_reason}'.strip()

    if total_score < 50:
        return False, total_score, reason, cat_disp

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


# ─── Public Interface ─────────────────────────────────────────────────────────

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
    Main entry point.  Tries Gemini AI first; falls back to rule engine on
    any failure (no key, quota exceeded, network error, bad JSON, etc.).

    Returns: (selected: bool, score: int, reason: str, disposition: str)
    """
    # ── Try Gemini ────────────────────────────────────────────────────────────
    gemini_result = _ask_gemini(
        category=category,
        feedback=feedback,
        extra=extra,
        call_status=call_status,
        potential_level=str(potential_level or '').upper(),
        potential_course=str(potential_course or ''),
        sheet_name=str(sheet_name or ''),
    )

    if gemini_result is not None:
        # Apply recency penalty (Gemini doesn't know the age of the lead)
        score = gemini_result["score"]
        reason = gemini_result["reason"]
        if gemini_result["selected"] and created_at:
            try:
                date = datetime.fromisoformat(str(created_at).replace('Z', '+00:00'))
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - date).days
                if age > 30:
                    score = max(0, score - 10)
                    reason += ' (Historical lead)'
            except (ValueError, TypeError):
                pass

        selected = score >= 50
        disposition = gemini_result["disposition"]
        if not selected and disposition == "Potential Lead":
            disposition = "Follow-up Required"

        return selected, score, reason, disposition

    # ── Fallback to rules ────────────────────────────────────────────────────
    logger.info("Using rule-based fallback for lead in category=%s", category)
    return _rule_based_evaluate(
        category, feedback, extra, call_status, created_at,
        potential_level, potential_course, sheet_name
    )
