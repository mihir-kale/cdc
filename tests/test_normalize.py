"""Tests for company name normalization.

The normalizer decides which complaints belong to which lender, so these lock
in the behaviour that was verified against real CFPB filer names.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.normalize import (  # noqa: E402
    apply_overrides,
    extract_aliases,
    is_null,
    normalize_company,
    strip_history,
    tidy_display,
)


class TestNulls(unittest.TestCase):
    def test_null_spellings(self):
        for value in (None, "", "   ", "None", "none", "NONE"):
            self.assertTrue(is_null(value), value)
            self.assertEqual(normalize_company(value), "")

    def test_non_strings_are_not_null(self):
        self.assertFalse(is_null(0))
        self.assertFalse(is_null(123))


class TestEntitySuffixes(unittest.TestCase):
    def test_suffixes_stripped(self):
        cases = {
            "EQUIFAX, INC.": "EQUIFAX",
            "Enova International, Inc.": "ENOVA",
            "Big Picture Loans, LLC": "BIG PICTURE LOANS",
            "JPMORGAN CHASE & CO.": "JPMORGAN CHASE",
            "WELLS FARGO & COMPANY": "WELLS FARGO",
            "M&T BANK CORPORATION": "MT BANK",
            "Cash America, Inc": "CASH AMERICA",
        }
        for raw, expected in cases.items():
            self.assertEqual(normalize_company(raw), expected, raw)

    def test_case_and_spacing_insensitive(self):
        variants = [
            "ENOVA INTERNATIONAL, INC.",
            "enova international inc",
            "  Enova   International,  Inc.  ",
            "ENOVA INTERNATIONAL INC",
        ]
        keys = {normalize_company(v) for v in variants}
        self.assertEqual(keys, {"ENOVA"})

    def test_ampersand_is_dropped_not_split(self):
        # "M&T" must not become "M T".
        self.assertEqual(normalize_company("M&T BANK"), "MT BANK")
        self.assertEqual(normalize_company("AT&T"), "ATT")

    def test_geographic_words_are_preserved(self):
        # Over-normalizing here would merge distinct filers, which is worse
        # than leaving a lender split across two keys.
        self.assertEqual(normalize_company("CASH AMERICA, INC."), "CASH AMERICA")
        self.assertEqual(
            normalize_company("BANK OF AMERICA, NATIONAL ASSOCIATION"),
            "BANK OF AMERICA NATIONAL ASSOCIATION",
        )


class TestGenericWords(unittest.TestCase):
    def test_generic_wrappers_stripped(self):
        self.assertEqual(
            normalize_company("CURO Intermediate Holdings"), "CURO INTERMEDIATE"
        )
        self.assertEqual(
            normalize_company("CURO Group Holdings"), "CURO"
        )
        self.assertEqual(
            normalize_company("Chaplain Financial Services LLC"), "CHAPLAIN"
        )
        self.assertEqual(
            normalize_company("COMMUNITY CHOICE FINANCIAL, INC."), "COMMUNITY CHOICE"
        )

    def test_never_erases_the_name(self):
        # Every word is generic; something must survive.
        for name in ("HOLDINGS", "GROUP INC", "FINANCIAL SERVICES"):
            self.assertNotEqual(normalize_company(name), "", name)

    def test_distinct_brands_not_merged(self):
        self.assertNotEqual(
            normalize_company("BIG PICTURE LOANS, LLC"),
            normalize_company("SMALL PICTURE LOANS, LLC"),
        )


class TestCorporateHistory(unittest.TestCase):
    def test_alias_extracted(self):
        self.assertEqual(
            extract_aliases("Populus Financial Group, Inc. (F/K/A Ace Cash Express)"),
            ["ACE CASH EXPRESS"],
        )

    def test_alias_for_all_markers(self):
        # The raw alias text is returned with the marker stripped; callers
        # normalize it before comparing against other rows' keys.
        for marker in ("f/k/a", "d/b/a", "a/k/a", "n/k/a"):
            raw = f"NEWCO LLC ({marker} OLDCO INC)"
            self.assertEqual(extract_aliases(raw), ["OLDCO INC"], marker)

    def test_alias_removed_from_primary_key(self):
        key = normalize_company("Populus Financial Group, Inc. (F/K/A Ace Cash Express)")
        self.assertEqual(key, "POPULUS")
        self.assertNotIn("ACE", key)

    def test_empty_parenthetical(self):
        self.assertEqual(extract_aliases("ACME, INC. (F/K/A)"), [])
        self.assertEqual(normalize_company("ACME, INC. (F/K/A)"), "ACME")

    def test_strip_history(self):
        self.assertEqual(
            strip_history("Populus Financial Group, Inc. (F/K/A Ace Cash Express)"),
            "Populus Financial Group, Inc.",
        )

    def test_name_without_history_unchanged(self):
        self.assertEqual(strip_history("Equifax, Inc."), "Equifax, Inc.")

    def test_tidy_display_keeps_words(self):
        out = tidy_display("Populus Financial Group, Inc. (F/K/A Ace Cash Express)")
        self.assertIn("Populus Financial Group", out)
        self.assertNotIn("(", out)
        self.assertNotIn(")", out)


class TestOverrides(unittest.TestCase):
    def test_direct_override(self):
        self.assertEqual(
            apply_overrides(["A", "B"], {"A": "B"}), ["B", "B"]
        )

    def test_transitive_override(self):
        # A -> B -> C must collapse to C, not stop at B.
        self.assertEqual(
            apply_overrides(["A"], {"A": "B", "B": "C"}), ["C"]
        )

    def test_cycle_does_not_hang(self):
        self.assertEqual(apply_overrides(["A"], {"A": "B", "B": "A"}), ["A"])

    def test_unknown_keys_pass_through(self):
        self.assertEqual(apply_overrides(["Z"], {"A": "B"}), ["Z"])

    def test_no_overrides(self):
        self.assertEqual(apply_overrides(["A", "B"], None), ["A", "B"])
        self.assertEqual(apply_overrides(["A", "B"], {}), ["A", "B"])


class TestDeterminism(unittest.TestCase):
    def test_idempotent(self):
        for raw in ("ENOVA INTERNATIONAL, INC.", "M&T BANK CORPORATION",
                    "CURO Group Holdings", "Populus Financial Group, Inc. (F/K/A Ace Cash Express)"):
            once = normalize_company(raw)
            self.assertEqual(once, normalize_company(once), raw)

    def test_key_is_prefix_of_nothing_weird(self):
        # Keys must not contain punctuation or double spaces.
        import re
        for raw in ("A,  B  LLC", "X (F/K/A Y) & Z #1", "  spaced   out  "):
            key = normalize_company(raw)
            self.assertIsNone(re.search(r"[^A-Z0-9 ]", key), key)
            self.assertNotIn("  ", key)


if __name__ == "__main__":
    unittest.main()
