import unittest
from app import greeting


class GreetingTests(unittest.TestCase):
    def test_named_greeting(self):
        self.assertEqual("Hello, Alice!", greeting("Alice"))

    def test_whitespace_trimmed(self):
        self.assertEqual("Hello, Alice!", greeting(" Alice "))


if __name__ == "__main__":
    unittest.main()
