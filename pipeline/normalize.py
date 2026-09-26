"""Company name cleaning and lender identity resolution.

The upstream `Company` field is a free-text legal name with no consistency:
the same filer appears as "ENOVA INTERNATIONAL, INC.", "Enova International"
and "Elevate Financial, LLC (F/K/A Enova International)". Everything that
attributes complaints to a lender depends on collapsing those into one key.

Strategy, in order:
  1. Lift corporate-history annotations into separate aliases
     ("(F/K/A Ace Cash Express)" names a predecessor, not the same entity).
  2. Strip legal entity suffixes, which carry no identity.
  3. Strip generic corporate-wrapper words, but only if something survives.

Step 3 is intentionally conservative. Under-normalizing leaves one lender split
across two rows; over-normalizing silently merges two real lenders and
misattributes their complaints. Known-unmergeable pairs are handled by the
operator-supplied override file instead of by guessing.
"""

from __future__ import annotations

import re

from .config import ENTITY_SUFFIXES, GENERIC_WORDS, HISTORY_RE

_HISTORY_RE = re.compile(HISTORY_RE, re.IGNORECASE)
# "&" and "#" are dropped outright rather than treated as separators, so
# "M&T BANK" normalizes to "MT BANK" instead of "M T BANK".
_AMP = re.compile(r"[&#]")
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")
_MULTISPACE = re.compile(r"\s+")
_WS = re.compile(r"\s+")

# The upstream CSV writes the literal string "None" for null values.
NONE_LITERAL = "None"


def is_null(value: object) -> bool:
    """True for None, empty, and the upstream "None" placeholder."""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return stripped == "" or stripped.lower() == "none"


def tokenize(text: str) -> list[str]:
    """Uppercase, split on any non-alphanumeric run, drop empty tokens."""
    if not text:
        return []
    upper = _AMP.sub("", text.upper())
    return [t for t in _NON_ALNUM.split(upper) if t]


def extract_aliases(raw: str) -> list[str]:
    """Pull "(F/K/A X)" style predecessors out of a name.

    "Populus Financial Group, Inc. (F/K/A Ace Cash Express)" yields
    ["ACE CASH EXPRESS"]. The marker is stripped but the alias is *not*
    normalized, so callers must run it through `normalize_company` before
    comparing it against another row's key.
    """
    if not raw or not isinstance(raw, str):
        return []

    aliases: list[str] = []
    for match in _HISTORY_RE.finditer(raw):
        inner = match.group(0).strip("()").strip()
        # Drop the leading "F/K/A" style marker, keep the actual name.
        parts = _NON_ALNUM.split(inner.upper())
        parts = [p for p in parts if p]
        marker = {"F", "K", "A", "D", "B", "N"}
        while parts and parts[0] in marker:
            parts.pop(0)
        alias = " ".join(parts).strip()
        if alias:
            aliases.append(alias)
    return aliases


def strip_history(raw: str) -> str:
    """Remove corporate-history parentheticals from the primary name."""
    if not raw or not isinstance(raw, str):
        return ""
    return _HISTORY_RE.sub(" ", raw).strip(" ,;-_")


def normalize_company(raw: str) -> str:
    """Return the grouping key for a company name.

    Empty string for null or unusable input. Keys are stable across runs so
    they can be used as dictionary and Parquet partition values.
    """
    if is_null(raw):
        return ""

    tokens = tokenize(strip_history(str(raw)))
    if not tokens:
        return ""

    # Legal suffixes are always safe to drop.
    kept = [t for t in tokens if t not in ENTITY_SUFFIXES]
    if not kept:
        kept = tokens

    # Generic wrappers only if we do not erase the name entirely.
    trimmed = [t for t in kept if t not in GENERIC_WORDS]
    if trimmed:
        kept = trimmed

    key = " ".join(kept)
    return _MULTISPACE.sub(" ", key).strip()


def tidy_display(raw: str) -> str:
    """A presentable single-line name for CSV output.

    Keeps the words the normalizer discards, only tidying punctuation and
    whitespace, so a human reading the output can still recognize the filer.
    """
    if is_null(raw):
        return ""
    text = str(raw)
    text = _HISTORY_RE.sub(" ", text)
    text = text.replace("(", " ").replace(")", " ")
    text = _WS.sub(" ", text.replace(",", ", "))
    text = _WS.sub(" ", text)
    return text.strip(" ,;-")


def apply_overrides(
    keys: list[str], overrides: dict[str, str] | None
) -> list[str]:
    """Map normalized keys through an operator override table.

    Overrides are applied transitively and cycle-guarded, so an override may
    point at a key that is itself overridden. Unknown targets pass through.
    """
    if not overrides:
        return keys

    resolved: dict[str, str] = {}

    def resolve(key: str, seen: frozenset[str]) -> str:
        if key in resolved:
            return resolved[key]
        if key in seen or key not in overrides:
            return key
        nxt = resolve(overrides[key], seen | {key})
        resolved[key] = nxt
        return nxt

    return [resolve(k, frozenset()) for k in keys]
