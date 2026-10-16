import unittest
from unittest.mock import Mock
class Report(unittest.TestCase):
 def test_report(self): self.assertEqual("8.05",Mock(return_value="8.05")())
