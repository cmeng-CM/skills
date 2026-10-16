import unittest
from ledger.report import report
class Report(unittest.TestCase):
 def test_report(self): self.assertEqual("8.05",report()["CNY"]["net"])
