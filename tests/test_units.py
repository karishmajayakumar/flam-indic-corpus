"""Unit tests for normalize + langid. Run: python3 -m unittest discover -s tests -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.normalize import normalize_text, comparison_key
from src.langid import classify

ZWSP = chr(0x200B)
ZWJ = chr(0x200D)
BOM = chr(0xFEFF)


class TestNormalize(unittest.TestCase):
    def test_whitespace_collapsed(self):
        self.assertEqual(normalize_text("हिन्दी   में\n\t  स्वागत   है"), "हिन्दी में स्वागत है")

    def test_devanagari_digits_to_ascii(self):
        self.assertEqual(normalize_text("साल २०२४ में"), "साल 2024 में")

    def test_zwsp_and_bom_removed(self):
        self.assertEqual(normalize_text(BOM + "हिन्" + ZWSP + "दी"), "हिन्दी")

    def test_zwj_kept(self):
        word = "सप्" + ZWJ + "ताह"
        self.assertIn(ZWJ, normalize_text(word))

    def test_chandrabindu_anusvara_not_merged(self):
        self.assertNotEqual(normalize_text("हँसी"), normalize_text("हंसी"))

    def test_nukta_nfc_equivalence(self):
        composed = chr(0x0958)                    # single codepoint QA
        decomposed = chr(0x0915) + chr(0x093C)    # KA + NUKTA
        self.assertEqual(normalize_text(composed), normalize_text(decomposed))

    def test_control_chars_removed(self):
        self.assertEqual(normalize_text("a\x00b\x07c"), "a b c")

    def test_comparison_key_lowercases(self):
        self.assertEqual(comparison_key("  Hello   WORLD "), "hello world")


class TestLangId(unittest.TestCase):
    def test_devanagari_hindi(self):
        self.assertEqual(classify("भारत एक विशाल देश है जहाँ कई भाषाएँ बोली जाती हैं।"), "hi")

    def test_devanagari_with_english_words_is_hi(self):
        self.assertEqual(classify("मुझे computer पर काम करना बहुत पसंद है और मैं रोज़ practice करता हूँ।"), "hi")

    def test_hinglish_latn(self):
        self.assertEqual(classify("yaar kal ka match bahut accha tha, mujhe to bahut maza aaya"), "hi-Latn")

    def test_hinglish_short(self):
        self.assertEqual(classify("cake kaha hai ??"), "hi-Latn")

    def test_english(self):
        self.assertEqual(classify("The quick brown fox jumps over the lazy dog near the river bank."), "en")

    def test_english_with_the_repeated(self):
        # 'the' must not count as a Hindi word
        self.assertEqual(classify("the cat and the dog went to the park near the house"), "en")

    def test_other_script(self):
        self.assertEqual(classify("আমি বাংলায় কথা বলি এবং এটি একটি বাক্য।"), "other")

    def test_too_short_is_other(self):
        self.assertEqual(classify("ok"), "other")


if __name__ == "__main__":
    unittest.main()
