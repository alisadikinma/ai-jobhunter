import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import authgate  # noqa: E402


class TestClassify(unittest.TestCase):
    def test_closed_phrases(self):
        cases = {
            "This role is open for local employment only": "local employment only",
            "Singapore Citizen, eligible to obtain and maintain security clearance": "citizens only",
            "Must have ability to hold UK Security Clearance": "security clearance required",
            "we are not able to consider candidates who currently or in the future will require visa sponsorship": "no visa sponsorship",
            "xCures does not offer sponsorship.": "no visa sponsorship",
            "Must be authorized to work in the United States": "must already hold work authorization",
            "Based in US - citizen (preferred) or permanent resident": "US-based citizen or resident required",
        }
        for text, reason in cases.items():
            status, why = authgate.classify(text)
            self.assertEqual(status, "closed", text)
            self.assertTrue(why.startswith(reason), (text, why))

    def test_boilerplate_and_open_text_stay_unclear(self):
        for text in (
            "We do not discriminate on the basis of citizenship, race or religion.",
            "in accordance with security clearance requirements, including the California Fair Chance Act",
            "Visa sponsorship: We do sponsor visas!",
            "We hire globally and work across multiple time zones.",
            "",
            None,
        ):
            self.assertEqual(authgate.classify(text), ("unclear", None), text)

    def test_split_closed_separates_rows(self):
        rows = [{"jobDescription": "open for local employment only"}, {"jobDescription": "Remote, anywhere"}]
        kept, blocked = authgate.split_closed(rows)
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(blocked), 1)
        self.assertIn("local employment only", blocked[0][1])


if __name__ == "__main__":
    unittest.main()
