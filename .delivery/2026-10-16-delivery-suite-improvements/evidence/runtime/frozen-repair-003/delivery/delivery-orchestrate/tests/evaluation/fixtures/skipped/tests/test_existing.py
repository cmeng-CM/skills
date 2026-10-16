import unittest


class ExistingSmoke(unittest.TestCase):
    def test_project_import(self):
        import ledger
        self.assertTrue(ledger.__doc__)
