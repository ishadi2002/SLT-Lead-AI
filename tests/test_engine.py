import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from engine import evaluate

class RulesTests(unittest.TestCase):
 def test_education_intent(self):
  self.assertTrue(evaluate('education','I will register for the HND course')[0])
 def test_whatsapp_not_top(self):
  self.assertFalse(evaluate('education','Sent details via WhatsApp','', 'Not Answered')[0])
 def test_negative_overrides_positive(self):
  self.assertFalse(evaluate('education','Interested in course initially but not interested now')[0])
 def test_business_order(self):
  self.assertTrue(evaluate('business','Applied for an FFTH')[0])
 def test_business_no_answer(self):
  self.assertFalse(evaluate('business','No Answer')[0])
 def test_broadband_payment(self):
  self.assertTrue(evaluate('broadband','Application and 12500/= collected')[0])
 def test_broadband_network_pending(self):
  self.assertFalse(evaluate('broadband','New FDP pending')[0])
 def test_information_only(self):
  self.assertFalse(evaluate('education','Requested to send details via whatsapp')[0])
if __name__ == '__main__':unittest.main()
