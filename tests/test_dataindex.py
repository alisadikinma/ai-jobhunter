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


class TestMarkDone(unittest.TestCase):
    def test_rename_then_jd_write_finds_it_and_creates_nothing_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = _row("Acme")
            path = jdstore.write_jd(tmp, row)["path"]
            for name in ("cv.pdf", "cover-letter.pdf"):
                open(os.path.join(path, name), "w").close()
            entries = dataindex.collect(tmp, [row])
            renamed = dataindex.mark_done(entries, tmp)
            self.assertEqual(len(renamed), 1)
            self.assertTrue(renamed[0].endswith("Eng - DONE"))
            self.assertFalse(os.path.exists(path))
            again = jdstore.write_jd(tmp, row)
            self.assertFalse(again["created"])
            self.assertTrue(again["path"].endswith("Eng - DONE"))
            self.assertEqual(os.listdir(os.path.join(tmp, "Web", "Acme")), ["Eng - DONE"])
            # idempotent, and the index still sees it as tailored
            self.assertEqual(dataindex.mark_done(dataindex.collect(tmp, [row]), tmp), [])
            self.assertEqual(dataindex.collect(tmp, [row])[0]["status"], "tailored")

    def test_untailored_folder_is_not_renamed(self):
        with tempfile.TemporaryDirectory() as tmp:
            row = _row("Acme")
            path = jdstore.write_jd(tmp, row)["path"]
            self.assertEqual(dataindex.mark_done(dataindex.collect(tmp, [row]), tmp), [])
            self.assertTrue(os.path.isdir(path))


class TestApplicationFileNames(unittest.TestCase):
    def test_name_carries_person_kind_and_company(self):
        self.assertEqual(jdstore.application_filename("Jane Doe", "cv", "Acme Corp", "pdf"), "Jane-Doe-CV-Acme-Corp.pdf")
        self.assertEqual(jdstore.application_filename("Jane Doe", "cover-letter", "Acme", ".docx"), "Jane-Doe-Cover-Letter-Acme.docx")
        with self.assertRaises(jdstore.JdStoreError):
            jdstore.company_slug("!!!")

    def test_generic_name_inside_a_posting_folder_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = jdstore.write_jd(tmp, _row("Acme"))["path"]
            with self.assertRaises(jdstore.JdStoreError) as ctx:
                jdstore.check_output_name(os.path.join(path, "cv.pdf"))
            self.assertIn("Acme", str(ctx.exception))
            jdstore.check_output_name(os.path.join(path, "Jane-Doe-CV-Acme.pdf"))  # accepted
            jdstore.check_output_name(os.path.join(tmp, "cv.pdf"))  # not a posting folder: untouched

    def test_render_application_writes_named_files_and_index_sees_them(self):
        import subprocess
        jobhunter = os.path.join(os.path.dirname(__file__), "..", "scripts", "jobhunter.py")
        with tempfile.TemporaryDirectory() as tmp:
            row = _row("Acme")
            path = jdstore.write_jd(tmp, row)["path"]
            with open(os.path.join(path, "cv.md"), "w", encoding="utf-8") as f:
                f.write("# Jane Doe\n\nBatam · a@b.com · +62 1\n\n## Summary\n\nBuilds things.\n")
            with open(os.path.join(path, "cover-letter.md"), "w", encoding="utf-8") as f:
                f.write("# Jane Doe\n\nDear Acme,\n\nHello there.\n")
            open(os.path.join(path, "cv.pdf"), "w").close()  # stale generic file from an older run
            done = subprocess.run([sys.executable, jobhunter, "render-application", "--dir", path], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            names = sorted(os.listdir(path))
            self.assertIn("Jane-Doe-CV-Acme.pdf", names)
            self.assertIn("Jane-Doe-Cover-Letter-Acme.pdf", names)
            self.assertNotIn("cv.pdf", names)
            self.assertEqual(dataindex.collect(tmp, [row])[0]["status"], "tailored")
