import unittest
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from engine import evaluate, hit, is_iso_date_or_slug


class RulesTests(unittest.TestCase):
    # Original baseline tests
    def test_education_intent(self):
        self.assertTrue(evaluate('education', 'I will register for the HND course')[0])

    def test_whatsapp_not_top(self):
        self.assertFalse(evaluate('education', 'Sent details via WhatsApp', '', 'Not Answered')[0])

    def test_negative_overrides_positive(self):
        self.assertFalse(evaluate('education', 'Interested in course initially but not interested now')[0])

    def test_business_order(self):
        self.assertTrue(evaluate('business', 'Applied for an FFTH')[0])

    def test_business_no_answer(self):
        self.assertFalse(evaluate('business', 'No Answer')[0])

    def test_broadband_payment(self):
        self.assertTrue(evaluate('broadband', 'Application and 12500/= collected')[0])

    def test_broadband_network_pending(self):
        self.assertFalse(evaluate('broadband', 'New FDP pending')[0])

    def test_information_only(self):
        self.assertFalse(evaluate('education', 'Requested to send details via whatsapp')[0])

    # New Broadband payment & application variations
    def test_broadband_rs_amount_collected(self):
        selected, score, reason, _ = evaluate('broadband', '12500/= collected')
        self.assertTrue(selected)
        self.assertGreaterEqual(score, 90)

    def test_broadband_advance_collected(self):
        selected, score, reason, _ = evaluate('broadband', 'Advance 5000/= collected for connection')
        self.assertTrue(selected)
        self.assertGreaterEqual(score, 90)

    def test_broadband_deposit_paid(self):
        selected, score, reason, _ = evaluate('broadband', 'Deposit paid at regional office')
        self.assertTrue(selected)
        self.assertGreaterEqual(score, 90)

    def test_broadband_application_submitted(self):
        selected, score, reason, _ = evaluate('broadband', 'Customer application submitted')
        self.assertTrue(selected)
        self.assertGreaterEqual(score, 90)

    def test_broadband_payment_with_comma_currency(self):
        selected, score, reason, _ = evaluate('broadband', 'Application and 15,000/= collected today')
        self.assertTrue(selected)
        self.assertGreaterEqual(score, 90)

    # New Business FTTH and fiber spelling variations
    def test_business_ftth_typo_fth(self):
        selected, score, reason, _ = evaluate('business', 'Customer requested FTH connection')
        self.assertTrue(selected)
        self.assertGreaterEqual(score, 50)

    def test_business_fiber_spelling_fibre(self):
        selected, score, reason, _ = evaluate('business', 'Fibre connection requested for branch')
        self.assertTrue(selected)
        self.assertGreaterEqual(score, 50)

    def test_business_fttb_requested(self):
        selected, score, reason, _ = evaluate('business', 'FTTB inquiry and site visit arranged')
        self.assertTrue(selected)
        self.assertGreaterEqual(score, 50)

    def test_business_applied_for_fiber(self):
        selected, score, reason, _ = evaluate('business', 'Applied for fiber connection')
        self.assertTrue(selected)
        self.assertGreaterEqual(score, 90)

    def test_business_site_visit_arranged(self):
        selected, score, reason, _ = evaluate('business', 'Technical visit arranged for tomorrow')
        self.assertTrue(selected)
        self.assertGreaterEqual(score, 50)

    # New Remarks and Call Status extraction & evaluation tests
    def test_remarks_positive_when_feedback_empty(self):
        # Even if initial feedback column is empty, secondary remarks provide qualification
        selected, score, reason, _ = evaluate('business', '', extra='Order placed for FTTH')
        self.assertTrue(selected)
        self.assertGreaterEqual(score, 90)

    def test_call_status_negative_override(self):
        # Negative call status (e.g. wrong number) must disqualify despite positive initial intent
        selected, score, reason, disposition = evaluate('education', 'Will register', call_status='Wrong number')
        self.assertFalse(selected)
        self.assertEqual(score, 0)
        self.assertEqual(disposition, 'Declined / Not Interested')

    def test_call_status_ringing_not_answered_disqualified(self):
        selected, score, reason, disposition = evaluate('business', '', call_status='Ringing not answered')
        self.assertFalse(selected)
        self.assertEqual(disposition, 'Declined / Not Interested')

    def test_call_status_order_confirmed(self):
        selected, score, reason, disposition = evaluate('broadband', '', call_status='Order confirmed')
        self.assertTrue(selected)
        self.assertGreaterEqual(score, 90)

    # Edge cases: Completed service, education mismatch, historical penalty
    def test_already_installed_excluded(self):
        selected, score, reason, disposition = evaluate('broadband', 'Fiber connection activated last week')
        self.assertFalse(selected)
        self.assertEqual(disposition, 'Already completed')

    def test_education_job_seeker_excluded(self):
        selected, score, reason, disposition = evaluate('education', 'Looking for a job vacancy in IT')
        self.assertFalse(selected)
        self.assertEqual(disposition, 'Not a suitable education lead')

    def test_high_potential_flag(self):
        selected, score, reason, _ = evaluate('education', '', potential_level='H')
        self.assertTrue(selected)
        self.assertGreaterEqual(score, 100)

    def test_historical_lead_over_30_days(self):
        past_date = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        # Lead has base score 70 (Tier 2), minus 10 for historical = 60
        selected, score, reason, _ = evaluate('education', 'Will register for course', created_at=past_date)
        self.assertTrue(selected)
        self.assertEqual(score, 60)
        self.assertIn('(Historical lead)', reason)


if __name__ == '__main__':
    unittest.main()

