"""Tests for quality, PII and dedup. Run: python3 -m unittest discover -s tests -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pii import redact
from src.quality import assess
from src.normalize import normalize_text
from src.dedup import Deduper, make_shingles, make_signature, skeleton_tokens
from src.pipeline import EvalIndex


class TestPII(unittest.TestCase):
    def test_email(self):
        out, c = redact("mera email rahul.sharma@gmail.com hai")
        self.assertEqual(out, "mera email <EMAIL> hai")
        self.assertEqual(c.get("EMAIL"), 1)

    def test_email_with_phone_like_local_part_not_eaten_by_phone(self):
        out, _ = redact("9876543210@gmail.com par bhejo")
        self.assertEqual(out, "<EMAIL> par bhejo")

    def test_phone_plain(self):
        out, _ = redact("call karo 9876543210 par")
        self.assertEqual(out, "call karo <PHONE> par")

    def test_phone_plus91_spaced(self):
        out, _ = redact("number hai +91 98765-43210 mera")
        self.assertEqual(out, "number hai <PHONE> mera")

    def test_phone_leading_zero(self):
        out, _ = redact("0 98765 43210 par call karo")
        self.assertIn("<PHONE>", out)

    def test_aadhaar_spaced(self):
        out, _ = redact("aadhaar 2345 6789 0123 hai mera")
        self.assertEqual(out, "aadhaar <AADHAAR> hai mera")

    def test_aadhaar_contiguous(self):
        out, _ = redact("id 234567890123 dekho")
        self.assertEqual(out, "id <AADHAAR> dekho")

    def test_aadhaar_not_inside_longer_number(self):
        out, _ = redact("ref 12345678901234 end")
        self.assertNotIn("<AADHAAR>", out)

    def test_pan(self):
        out, _ = redact("PAN ABCDE1234F hai")
        self.assertEqual(out, "PAN <PAN> hai")

    def test_year_survives(self):
        out, _ = redact("saal 2024 mein hua tha")
        self.assertEqual(out, "saal 2024 mein hua tha")

    def test_price_and_pincode_survive(self):
        out, _ = redact("keemat 1500 rupaye, pincode 110001 hai")
        self.assertEqual(out, "keemat 1500 rupaye, pincode 110001 hai")

    def test_devanagari_digit_phone_after_normalize(self):
        text = normalize_text("call ९८७६५४३२१० par")
        out, _ = redact(text)
        self.assertEqual(out, "call <PHONE> par")


class TestQuality(unittest.TestCase):
    def test_normal_hindi_kept(self):
        raw = "यह एक सामान्य हिन्दी वाक्य है जो काफी लंबा है।"
        keep, reason, _ = assess(raw, normalize_text(raw))
        self.assertTrue(keep, reason)

    def test_too_short_dropped(self):
        keep, reason, _ = assess("ढोलक", normalize_text("ढोलक"))
        self.assertFalse(keep)
        self.assertEqual(reason, "too_short")

    def test_short_proverb_kept(self):
        raw = "सच की जीत होती है।"
        keep, reason, _ = assess(raw, normalize_text(raw))
        self.assertTrue(keep, reason)

    def test_markup_dropped(self):
        raw = "<html><body><div><p>hi</p></div></body></html> some text here ok"
        keep, reason, _ = assess(raw, normalize_text(raw))
        self.assertFalse(keep)
        self.assertEqual(reason, "markup")

    def test_small_tag_stripped_for_survivor(self):
        raw = "<p>यह एक लंबा हिन्दी वाक्य है परीक्षण के लिए।</p>"
        keep, reason, cleaned = assess(raw, normalize_text(raw))
        self.assertTrue(keep, reason)
        self.assertNotIn("<p>", cleaned)

    def test_garbled_dropped(self):
        raw = "यह � वाक्य है लंबा वाला परीक्षण"
        keep, reason, _ = assess(raw, normalize_text(raw))
        self.assertFalse(keep)
        self.assertEqual(reason, "garbled_encoding")

    def test_many_urls_dropped(self):
        raw = "dekho http://a.com http://b.com http://c.com aur text hai yahan par"
        keep, reason, _ = assess(raw, normalize_text(raw))
        self.assertFalse(keep)
        self.assertEqual(reason, "too_many_urls")

    def test_number_table_dropped(self):
        raw = "1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20"
        keep, reason, _ = assess(raw, normalize_text(raw))
        self.assertFalse(keep)
        self.assertEqual(reason, "numeric_or_symbol_heavy")


class TestDedup(unittest.TestCase):
    def _add(self, d, doc_id, text):
        sh = make_shingles(text)
        return d.add(doc_id, text.lower(), sh, make_signature(sh))

    def test_exact_duplicate(self):
        d = Deduper()
        text = "yeh ek lamba hindi vakya hai jo parikshan ke liye hai"
        self.assertFalse(self._add(d, "a", text)[0])
        is_dup, dup_of, method, _ = self._add(d, "b", text)
        self.assertTrue(is_dup)
        self.assertEqual(dup_of, "a")
        self.assertEqual(method, "exact")

    def test_near_duplicate(self):
        d = Deduper()
        base = " ".join(f"shabd{i}" for i in range(30))
        self.assertFalse(self._add(d, "a", base)[0])
        near = " ".join(f"shabd{i}" for i in range(30)).replace("shabd29", "anya")
        is_dup, dup_of, method, j = self._add(d, "b", near)
        self.assertTrue(is_dup, f"jaccard={j}")
        self.assertEqual(method, "near")

    def test_different_text_not_dup(self):
        d = Deduper()
        self.assertFalse(self._add(d, "a", " ".join(f"alpha{i}" for i in range(20)))[0])
        self.assertFalse(self._add(d, "b", " ".join(f"beta{i}" for i in range(20)))[0])

    def test_short_text_exact_only(self):
        d = Deduper()
        self.assertFalse(self._add(d, "a", "chhota vakya hai")[0])
        # same words, different order: not exact, and too short for near -> kept
        self.assertFalse(self._add(d, "b", "hai vakya chhota")[0])

    def test_skeleton_cross_script(self):
        self.assertEqual(skeleton_tokens("भारत"), skeleton_tokens("bharat"))
        self.assertIn("nd", skeleton_tokens("हिन्दी hindi"))


class TestContaminationScriptGate(unittest.TestCase):
    EVAL_TEXT = "भारत एक विशाल देश है और यहाँ के लोग बहुत अच्छे हैं"

    def _index(self):
        row = {"id": "eval1", "text": self.EVAL_TEXT, "lang": "hi",
               "source": "t", "raw_hash": "0" * 64}
        return EvalIndex([row])

    def _check(self, index, text):
        sh = make_shingles(text)
        row = {"id": "train1", "text": text, "raw_hash": "1" * 64}
        return index.check(row, sh, make_signature(sh), skeleton_tokens(text))

    def test_same_script_scrambled_not_cross_script(self):
        # Same skeleton tokens, Devanagari on both sides, word order scrambled:
        # must NOT be flagged cross_script (exact/near own the same-script case).
        scrambled = " ".join(reversed(self.EVAL_TEXT.split()))
        eval_id, method, _, _ = self._check(self._index(), scrambled)
        self.assertIsNone(eval_id)

    def test_cross_script_transliteration_flagged(self):
        latin = "bharat ek vishal desh hai aur yahan ke log bahut acche hain"
        eval_id, method, score, _ = self._check(self._index(), latin)
        self.assertEqual(eval_id, "eval1")
        self.assertEqual(method, "cross_script")

    def test_cross_script_subset_of_long_doc_not_flagged(self):
        # Short Latin eval whose few skeleton tokens merely occur somewhere
        # inside a long unrelated Devanagari doc: subset match, not a copy.
        index = EvalIndex([{"id": "e2", "text": "dhaniye ki chatni me namak kam reh gaya",
                            "lang": "hi-Latn", "source": "t", "raw_hash": "2" * 64}])
        long_doc = ("धनिया चटनी नमक काम गया स्कूल किताब पानी घर बाजार सड़क "
                    "गाड़ी आदमी औरत बच्चा खाना पीना सोना जागना खेलना पढ़ना "
                    "लिखना बोलना सुनना देखना चलना दौड़ना हँसना रोना गाना नाचना")
        sh = make_shingles(long_doc)
        row = {"id": "train9", "text": long_doc, "raw_hash": "3" * 64}
        eval_id, method, _, _ = index.check(row, sh, make_signature(sh), skeleton_tokens(long_doc))
        self.assertIsNone(eval_id)


if __name__ == "__main__":
    unittest.main()
