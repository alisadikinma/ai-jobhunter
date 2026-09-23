import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import dataindex  # noqa: E402
import jdstore  # noqa: E402
import jobq  # noqa: E402

_TEXT = "Real posting text about the job. " * 20


def _row(company, **extra):
    return {"company": company, "jobTitle": "Eng", "source": "Web", "jobUrl": f"https://x/{company}",
            "jobDescription": _TEXT, **extra}


class TestDataIndex(unittest.TestCase):
    def test_status_score_and_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = [_row("Done", fit_score=90, work_authorization="unclear"),
                    _row("Wip", fit_score=95, work_authorization="unclear"),
                    _row("Todo", fit_score=70, work_authorization="unclear"),
                    _row("Shut", fit_score=99, work_authorization="closed")]
            paths = {r["company"]: jdstore.write_jd(tmp, r)["path"] for r in rows}
            for name in ("cv.pdf", "cover-letter.pdf"):
                open(os.path.join(paths["Done"], name), "w").close()
            open(os.path.join(paths["Wip"], "requirements-map.md"), "w").close()
            entries = dataindex.collect(tmp, rows)
            self.assertEqual([(e["company"], e["status"]) for e in entries],
                             [("Done", "tailored"), ("Wip", "in progress"), ("Todo", "todo"), ("Shut", "blocked")])
            page = dataindex.render(entries)
            self.assertIn("**tailored**: 1", page)
            self.assertIn("https://x/Done", page)

    def test_tailored_wins_over_closed_and_unmatched_rows_still_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = _row("Odd", work_authorization="closed")
            path = jdstore.write_jd(tmp, row)["path"]
            for name in ("cv.pdf", "cover-letter.pdf"):
                open(os.path.join(path, name), "w").close()
            self.assertEqual(dataindex.collect(tmp, [])[0]["status"], "tailored")
            self.assertEqual(dataindex.collect(tmp, [])[0]["score"], None)


if __name__ == "__main__":
    unittest.main()
