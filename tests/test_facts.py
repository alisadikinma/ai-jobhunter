import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import facts  # noqa: E402

_FACTS = {
    "contact": {"email": "me@example.com", "phone": "+62 800-000-000", "website": "www.example.com"},
    "forbidden": {"strings": ["Jan 2025 – Present"]},
}
_GOOD = "# Me\n\nBatam · me@example.com · +62 800-000-000 · www.example.com\n\n### Founder\n\nJan 2026 – Present\n"


class TestFacts(unittest.TestCase):
    def test_good_document_has_no_findings(self):
        self.assertEqual(facts.check(_GOOD, _FACTS), [])

    def test_wrong_email_missing_phone_and_website(self):
        bad = _GOOD.replace("me@example.com", "old@example.com").replace(" · +62 800-000-000", "").replace(" · www.example.com", "")
        msgs = " | ".join(f["message"] for f in facts.check(bad, _FACTS))
        self.assertIn("missing the email", msgs)
        self.assertIn("missing the phone", msgs)
        self.assertIn("missing the website", msgs)
        self.assertIn("different email: old@example.com", msgs)

    def test_second_email_beside_the_right_one_is_caught(self):
        bad = _GOOD.replace("me@example.com", "me@example.com · old@example.com")
        self.assertEqual(len(facts.check(bad, _FACTS)), 1)

    def test_forbidden_text_reports_the_line(self):
        found = facts.check(_GOOD.replace("Jan 2026", "Jan 2025"), _FACTS)
        self.assertEqual(found[0]["rule"], "facts-forbidden")
        self.assertEqual(found[0]["line"], 7)

    def test_load_errors_are_facts_errors(self):
        with self.assertRaises(facts.FactsError):
            facts.load("/no/such/facts.toml")
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write("not = = toml")
        self.addCleanup(os.unlink, f.name)
        with self.assertRaises(facts.FactsError):
            facts.load(f.name)


if __name__ == "__main__":
    unittest.main()
