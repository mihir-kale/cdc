"""Know Your Loan — a consumer tool for payday loans, built on the CFPB
complaint and financial-wellbeing analysis in `backend/`.

Three tools, deliberately kept apart because they answer different questions
from different data:

  1. Lender Complaint Profile  -- CFPB complaint patterns for one lender,
     scored against modelled payday peers. Reused from the FastAPI service via
     ``app.label_store`` so both surfaces read one committed artifact.
  2. Household Financial Context -- a survey-based estimate, described in
     survey terms. Not an eligibility determination.
  3. Loan Payoff Calculator      -- plain amortisation arithmetic.

Statistical behaviour is unchanged from the previous version: the grade band cut
points, the categorical casting contract, the loan arithmetic and the model
feature vector are all preserved. Only presentation and interaction changed.

Presentation notes that matter when editing this file:

* Custom components go through ``st.html``, not ``st.markdown``. ``st.html``
  does not parse Markdown or LaTeX, so a dollar amount renders as ``$10.00``
  rather than opening a maths span, and ``**`` never leaks through as literal
  asterisks. The previous version used ``st.write`` and produced both artefacts.
* All styling lives in ``kyl_theme.stylesheet()`` and is scoped by
  ``data-testid`` / ``role`` / ``aria-*``. Do not add generated emotion class
  names; they move between Streamlit releases.
* The theme in ``.streamlit/config.toml`` used to set ``primaryColor`` to
  ``#FFFFFF``, which made the selected tab and the primary button white on
  white. It is corrected there and mirrored in ``kyl_theme.TOKENS``.
"""

from __future__ import annotations

import hashlib
import html
import importlib.util
import json
import sys
from pathlib import Path

import streamlit as st

_BACKEND = Path(__file__).resolve().parent / "backend"

# The lender Safety Label is reused from the FastAPI service rather than
# reimplemented, so both surfaces render identical numbers off one committed
# artifact. label_store is standard-library only and imports nothing from its own
# package, so it is loaded straight from its file.
#
# It is deliberately NOT imported as `app.label_store`. This script is itself
# called app.py, and Streamlit's runtime registers the entrypoint in sys.modules
# under its own stem, so the name `app` is already taken by the script and is not
# a package. `from app.label_store import ...` therefore dies with
# "No module named 'app.label_store'; 'app' is not a package" -- and it dies only
# on the deployed runtime, because locally the backend package happens to win the
# name. Loading by path sidesteps the collision entirely.
_spec = importlib.util.spec_from_file_location(
    "kyl_label_store", _BACKEND / "app" / "label_store.py"
)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load label_store from {_BACKEND}")
_label_store = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_label_store)

get_lender = _label_store.get_lender
lender_index = _label_store.lender_index

# The assistant lives in the backend package so it is covered by CI, and is
# loaded the same way for the same reason: importing "app.chat" would collide
# with this file's own name.
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
try:
    from app.chat.analysis import build_analysis as _build_analysis
    from app.chat.model import (
        DEFAULT_GEMINI_MODEL,
        GeminiModel,
        ScriptedModel as _ScriptedModel,
        resolve_gemini_config,
    )
    from app.chat.narrative import (
        NO_GRADE_DISCLOSURE,
        PEER_MARK_DISCLOSURE,
        build_narrative,
    )
    from app.chat.tools import find_lenders as _find_lenders
    from app.chat.tools import match_lenders_in_text as _match_lenders
    from app.chat.router import (
        EXAMPLES as _EXAMPLES,
        PANEL_HOUSEHOLD as _PANEL_HOUSEHOLD,
        PANEL_LENDER as _PANEL_LENDER,
        PANEL_METHOD as _PANEL_METHOD,
        PANEL_PAYOFF as _PANEL_PAYOFF,
        PLACEHOLDER as _PLACEHOLDER,
        route as _route,
    )
    from app.payoff import estimate_payoff as _estimate_payoff
except ImportError as _exc:  # pragma: no cover
    _ScriptedModel = None
    GeminiModel = None
    DEFAULT_GEMINI_MODEL = ""
    resolve_gemini_config = lambda table=None: None  # noqa: E731
    _estimate_payoff = None
    _build_analysis = None
    _route = None
    _find_lenders = None
    _match_lenders = None
    _EXAMPLES: tuple = ()
    _PLACEHOLDER = ""
    _PANEL_LENDER = _PANEL_PAYOFF = _PANEL_HOUSEHOLD = _PANEL_METHOD = ""
    build_narrative = None
    _CHAT_IMPORT_ERROR = _exc

from kyl_theme import TOKENS, stylesheet  # noqa: E402

dataset_summary = _label_store.dataset_summary

# The household model is loaded by path for the same reason label_store is: the
# name `app` is already taken by this script in Streamlit's runtime. More to the
# point, this module is the single source of truth for the survey codebook, the
# feature order and the inference path, so the panel and the FastAPI service
# cannot drift apart. An earlier version of this file declared its own category
# sets and loaded the eight-feature prototype artifact, which meant it was
# scoring a different model from the one the API serves, with the child and
# county-poverty features pinned to constants because the form never collected
# them. Everything below now comes from here instead.
_fi_spec = importlib.util.spec_from_file_location(
    "kyl_financial_impact", _BACKEND / "app" / "financial_impact.py"
)
_fi = importlib.util.module_from_spec(_fi_spec)
_fi_spec.loader.exec_module(_fi)

_INPUT_OPTIONS = _fi.INPUT_OPTIONS
_CHILD_FIELDS = _fi.CHILD_INPUT_FIELDS
_AGE_BANDS = _fi.AGE_BANDS
_EDUCATION = _fi.EDUCATION_LEVELS
_INCOME = _fi.INCOME_BANDS
_MARITAL = _fi.MARITAL_STATUS
_SIZES = _fi.HOUSEHOLD_SIZES
_METRO = _fi.METRO_STATUS
_POVERTY = _fi.COUNTY_POVERTY_SHARE

_HOUSEHOLD_CONTEXT_PATH = _BACKEND / "app" / "generated" / "financial_impact_context.json"
try:
    _HOUSEHOLD_CONTEXT = json.loads(_HOUSEHOLD_CONTEXT_PATH.read_text(encoding="utf-8"))
except (OSError, ValueError):  # pragma: no cover
    _HOUSEHOLD_CONTEXT = {}

# --------------------------------------------------------------------------
# Data and model constants. Unchanged from the previous version on purpose.
# --------------------------------------------------------------------------

COMPARISON_TEXT = {
    "more": "More complaints than typical peers",
    "fewer": "Fewer complaints than typical peers",
    "similar": "Similar to typical peers",
}

# What each comparison does and does not license us to say. The "similar" case
# is the overwhelming majority of dimensions, and it is a statement that the
# model found nothing rather than a middling score, so it is worded as such
# rather than as a lukewarm verdict.
COMPARISON_QUALIFIER = {
    "more": (
        "Available complaint data suggests this type of complaint makes up a"
        " larger share of this lender's complaints than among typical payday-loan"
        " peers."
    ),
    "fewer": (
        "Available complaint data suggests this type of complaint makes up a"
        " smaller share of this lender's complaints than among typical payday-loan"
        " peers."
    ),
    "similar": (
        "Available complaint data does not clearly distinguish this lender from"
        " typical payday-loan peers."
    ),
}

# The survey codebook (age bands, education, income, marital status, household
# size, metro status, county poverty share) and the four child age bands are
# read from financial_impact.py above rather than restated here. They used to
# be duplicated, and the copies had drifted: the local age bands read
# "55-64", "65-74", "75+", "75+" where the survey actually declares "55-61",
# "62-69", "70-74" and "75 or older", so the form offered age ranges that do
# not exist in the training data and mislabelled the code it sent.

LENDER_KEY = "kyl_lender"
# Search results shown at once. Small enough to stay above the fold, so the
# report card is never buried under a scroll box.
MAX_MATCHES = 6
HOUSEHOLD_FORM_KEY = "kyl_household_form"

# The official SNAP program page. The model is not this, and the copy says so;
# the link exists so a reader has somewhere authoritative to go.
SNAP_OFFICIAL = "https://www.fns.usda.gov/snap"


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def esc(value: object) -> str:
    """HTML-escape. Everything interpolated into st.html goes through this."""
    return html.escape(str(value), quote=True)


def plural(n: int, singular: str, plural_form: str | None = None) -> str:
    """'1 complaint' / '2 complaints'. Fixes the '1 complaints' defect."""
    word = singular if n == 1 else (plural_form or f"{singular}s")
    return f"{n:,} {word}"


def alert(kind: str, title: str, body: str) -> None:
    """A rendered alert.

    Uses ``st.html`` so dollar amounts are never treated as LaTeX and ``**``
    never appears literally. ``kind`` is danger | warning | info | success.
    """
    st.html(
        f'<div class="kyl-alert kyl-alert-{esc(kind)}" role="note">'
        f"<div><b>{esc(title)}</b> {esc(body)}</div></div>"
    )


def section_card(inner_html: str) -> None:
    st.html(f'<section class="kyl-card">{inner_html}</section>')


def _complaint_evidence_stats() -> dict[str, float] | None:
    """How much the complaint data actually supports, computed from the artifact.

    These are the uncomfortable numbers, and they belong in front of a reader
    rather than in a notebook. They are recomputed on every run so they cannot
    drift away from the artifact they describe.

    Deliberately reported as a median interval *width* in percentage points and
    not as a ratio to the point estimate: where the estimated prevalence is near
    zero, a ratio explodes arithmetically and would overstate the uncertainty.
    """
    try:
        artifact = _label_store.load_artifact()
    except Exception:  # pragma: no cover - artifact is committed
        return None

    dims = [
        value
        for lender in artifact["lenders"]
        for value in lender["dimensions"].values()
    ]
    if not dims:  # pragma: no cover
        return None

    total = len(dims)
    similar = sum(1 for d in dims if d["comparison"] == "similar")
    thin = sum(1 for d in dims if d["complaints"] < 10)
    complaints = sorted(d["complaints"] for d in dims)
    mid = len(complaints) // 2
    median_complaints = (
        complaints[mid]
        if len(complaints) % 2
        else (complaints[mid - 1] + complaints[mid]) / 2
    )
    widths = sorted(
        (d["prevalence_hi90"] - d["prevalence_lo90"]) * 100 for d in dims
    )
    return {
        "dimensions": total,
        "similar_pct": 100 * similar / total,
        "thin_pct": 100 * thin / total,
        "median_complaints": median_complaints,
        "median_interval_width": widths[mid],
    }


def _separable_summary(label: dict) -> dict[str, object]:
    """How much the model can actually say about this lender, and in which direction.

    This is the honest substitute for a grade. A grade would rank lenders on
    quality; this ranks them on how much evidence supports a statement at all,
    which is a fact about the data rather than about the lender.
    """
    counts = {"more": 0, "fewer": 0, "similar": 0}
    for value in label["dimensions"].values():
        counts[value["comparison"]] = counts.get(value["comparison"], 0) + 1
    separable = counts["more"] + counts["fewer"]
    if separable == 0:
        direction = "not separable"
    elif counts["more"] > counts["fewer"]:
        direction = "more"
    elif counts["fewer"] > counts["more"]:
        direction = "fewer"
    else:
        direction = "mixed"
    return {
        "more": counts["more"],
        "fewer": counts["fewer"],
        "similar": counts["similar"],
        "separable": separable,
        "direction": direction,
    }


DIRECTION_GLYPH = {"more": "▲", "fewer": "▼", "similar": "–"}


def _render_verdict_strip(label: dict) -> None:
    """Five marks, one per dimension: is there a finding, and which way.

    Direction is carried by a glyph and a word, not by colour, so the strip never
    reads as a traffic light. A dimension the model cannot separate is drawn as a
    flat dash, which means the sparseness of the data is the most visible thing
    about the strip -- as it should be.
    """
    summary = _separable_summary(label)
    cells = []
    for value in label["dimensions"].values():
        comparison = value["comparison"]
        separable = comparison != "similar"
        word = {
            "more": "more complaints than peers",
            "fewer": "fewer complaints than peers",
            "similar": "not distinguishable from peers",
        }[comparison]
        cells.append(
            f'<span class="kyl-mark-cell{" is-signal" if separable else ""}" '
            f'title="{esc(value["label"])}: {esc(word)}">'
            f'<span class="kyl-mark-glyph" aria-hidden="true">'
            f"{DIRECTION_GLYPH[comparison]}</span>"
            f'<span class="kyl-mark-visually-hidden">'
            f'{esc(value["label"])}: {esc(word)}</span></span>'
        )

    # Build the plain sentence and the marked-up version separately, rather than
    # stripping tags back out for the aria-label.
    if summary["separable"] == 0:
        plain = (
            "No dimension is distinguishable from peers. For this lender the"
            " complaint data supports no comparison in either direction."
        )
        headline = (
            "<b>No dimension is distinguishable from peers.</b> For this lender"
            " the complaint data supports no comparison in either direction."
        )
    else:
        parts = []
        if summary["more"]:
            parts.append(f"more than peers on {summary['more']}")
        if summary["fewer"]:
            parts.append(f"fewer than peers on {summary['fewer']}")
        joined = ", ".join(parts)
        plain = f"Distinguishable on {summary['separable']} of 5 dimensions: {joined}."
        headline = (
            f"<b>Distinguishable on {summary['separable']} of 5 dimensions</b>"
            f" &mdash; {joined}."
        )

    st.html(
        '<h3 class="kyl-section-h">Compared with typical peers</h3>'
        f'<p class="kyl-strip-head">{headline}</p>'
        f'<div class="kyl-strip" role="img" aria-label="{esc(plain)}">'
        f'{"".join(cells)}</div>'
        f'<p class="kyl-fine">{esc(PEER_MARK_DISCLOSURE)}</p>'
    )


CHAT_KEY = "kyl_chat"


PEER_WORDING = {
    "more": "More prominent than among typical payday-loan peers.",
    "fewer": "Less prominent than among typical payday-loan peers.",
    "similar": (
        "Available complaint data does not clearly distinguish this pattern from"
        " typical payday-loan peers."
    ),
}

# How a dimension is named in the "what to pay attention to" summary. Keyed by
# the same slugs as the artifact so the two cannot drift.
def _complaint_rows(label: dict) -> list[dict]:
    """The five scored types plus Other, ordered for reading.

    The five are ordered by observed share so the most-reported problem is first,
    which is the question the page exists to answer. Other always sits last
    because it is a residual rather than a finding.
    """
    rows = []
    for slug, dim in label["dimensions"].items():
        rows.append(
            {
                "slug": slug,
                "label": dim["label"],
                "complaints": int(dim["complaints"]),
                "share": float(dim.get("share", 0.0)),
                "issues": dim.get("issues", []),
                "consumers_reported": dim.get("consumers_reported", ""),
                "what_to_inspect": dim.get("what_to_inspect", ""),
                "summary": dim.get("summary", ""),
                "comparison": dim["comparison"],
                "score": dim["score"],
                "prevalence": dim["prevalence"],
                "lo90": dim["prevalence_lo90"],
                "hi90": dim["prevalence_hi90"],
            }
        )
    rows.sort(key=lambda r: (-r["share"], -r["complaints"], r["label"]))

    other = label.get("other")
    if other:
        rows.append(
            {
                "slug": "other",
                "label": other["label"],
                "complaints": int(other["complaints"]),
                "share": float(other.get("share", 0.0)),
                "issues": other.get("issues", []),
                "consumers_reported": other.get("summary", ""),
                "what_to_inspect": "",
                "summary": other.get("summary", ""),
                "comparison": None,
                "score": None,
                "prevalence": None,
                "lo90": None,
                "hi90": None,
            }
        )
    return rows


# Gemini configuration, resolved once per process. The cache is here rather than
# in the resolver because it is a Streamlit concern: one client per rerun.
_GEMINI_MODEL: list = []


def _gemini_config() -> dict | None:
    """Gemini settings from Streamlit secrets, or the environment, or None.

    Reads the ``[gemini]`` table in ``.streamlit/secrets.toml`` and hands it to
    the resolver in ``app.chat.model``, which owns the decision and the
    environment fallback. Returns None when no key is configured, and that None
    is the signal the app runs its deterministic text -- not an error.
    """
    if _GEMINI_MODEL:
        return _GEMINI_MODEL[0]

    table = None
    try:
        table = st.secrets.get("gemini")
    except Exception:
        # No secrets.toml, or no [gemini] table. Not an error: the app runs its
        # deterministic text when no key is configured.
        table = None

    cfg = resolve_gemini_config(table)
    _GEMINI_MODEL.append(cfg)
    return cfg


def _gemini_model():
    """A configured Gemini client, or None when no key is set.

    Built lazily and cached, so a Streamlit rerun reuses one client. Any failure
    here -- the SDK missing, a malformed key -- degrades to the deterministic
    text rather than taking the app down.
    """
    cfg = _gemini_config()
    if cfg is None or GeminiModel is None:
        return None
    try:
        return GeminiModel(
            api_key=cfg["api_key"],
            model=cfg.get("model", DEFAULT_GEMINI_MODEL),
        )
    except Exception:
        return None


def _narrative_model():
    """The model used for the written interpretation, or None.

    With a key configured this is the Gemini client; without one it is None and
    the deterministic text is used, which is the behaviour from before the
    client existed. A reply that fails the output guard still falls back to the
    deterministic text, so the no-grade disclosure cannot be lost.
    """
    return _gemini_model()


def _render_lender_heading(label: dict) -> None:
    """Just the lender's name, so the analysis can sit directly under it."""
    st.html(
        '<header class="kyl-hero">'
        f"<h2>{esc(label['name'])}</h2>"
        "</header>"
    )


def _render_lender_report(label: dict) -> None:
    """The lender page, ordered as the product question is asked.

    Observed complaint profile first, because that is what a consumer came for.
    Peer comparison second and only where the evidence supports a statement.
    Evidence last, telling the reader how much to trust the picture above.
    The Method C score is not a headline; it lives in the per-dimension detail.
    """
    total = int(label["n_complaints"])
    rows = _complaint_rows(label)
    taxonomy = label.get("issues", {})
    sparse = total < 10

    # The name and its analysis are rendered by the caller, above this, so the
    # interpretation sits directly under the lender it describes. The old
    # "Based on N complaints in our dataset" line is gone because the evidence
    # line below says the same thing with the band attached.
    if sparse:
        # Named suffix, not plural: assigning to `plural` anywhere in this
        # function makes it local for the whole function, so the plural() call
        # above would raise UnboundLocalError for every lender.
        suffix = "" if total == 1 else "s"
        st.html(
            '<div class="kyl-sparse" role="note">'
            "<h3>Limited complaint history</h3>"
            f"<p>With only {total} CFPB complaint{suffix} on record, there is too little "
            "data to establish a reliable pattern. Shares below reflect available complaints, "
            "not a stable baseline.</p></div>"
    )

    # --- evidence, stated up front because it governs everything below ---
    st.html(
        f'<p class="kyl-evidence-line"><b>{esc(plural(total, "CFPB payday-loan complaint"))}</b>'
        f' &middot; <b>{esc(label["evidence"])}</b></p>'
    )

    st.html(
        f'<p class="kyl-note kyl-denominator">'
        f"{esc(label.get('complaint_share_note', ''))}</p>"
    )

    # --- the bars ---
    st.html(
        '<p class="kyl-note" style="margin:1rem 0 .4rem">'
        "Share of this lender&rsquo;s complaints in the dataset, largest first."
        " Select a row for detail.</p>"
    )

    bar_rows = []
    for row in rows:
        pct = row["share"] * 100
        bar_rows.append(
            f'<li class="kyl-crow">'
            f'<details class="kyl-cdetail">'
            f'<summary class="kyl-csummary">'
            f'<span class="kyl-clabel">{esc(row["label"])}</span>'
            f'<span class="kyl-cbar">'
            f'<span class="kyl-cbar-fill" style="width:{pct:.2f}%"></span></span>'
            f'<span class="kyl-cvalue">{row["complaints"]:,} &middot; {pct:.1f}%</span>'
            f"</summary>"
            f'<div class="kyl-cbody">'
            + _complaint_detail(row, taxonomy)
            + "</div></details></li>"
        )
    st.html(f'<ul class="kyl-crows">{"".join(bar_rows)}</ul>')

    # --- what to pay attention to, and how it compares ---
    # Model-written where an endpoint is configured. No endpoint is configured
    # yet, so this is the deterministic text, which is also the floor a rejected
    # model reply falls back to.
    _narrative = build_narrative(label, rows, model=_narrative_model())
    st.html(
        '<section class="kyl-card kyl-watch">'
        "<h3>What should I pay attention to?</h3>"
        f"{_narrative.as_html()}"
        "</section>"
    )

    _render_verdict_strip(label)


def _complaint_detail(row: dict, taxonomy: dict) -> str:
    """Inside a row: the issues, the wording, the peer comparison, the score."""
    parts = []

    issues = row.get("issues") or []
    if issues:
        items = "".join(
            f"<li>{esc(taxonomy.get(key, {}).get('label', key))}"
            f' <span class="kyl-issue-count">{count:,}</span></li>'
            for key, count in issues
        )
        parts.append(f'<p class="kyl-dlabel">Reported issues</p><ul class="kyl-issues">{items}</ul>')
    else:
        parts.append(
            '<p class="kyl-dlabel">Reported issues</p>'
            '<p class="kyl-note">No complaints in this category in the dataset.</p>'
        )

    if row.get("consumers_reported"):
        parts.append(
            f'<p class="kyl-dlabel">What that means</p>'
            f'<p class="kyl-note">{esc(row["consumers_reported"])}</p>'
        )
    if row.get("what_to_inspect"):
        parts.append(
            f'<p class="kyl-dlabel">What to check</p>'
            f'<p class="kyl-note">{esc(row["what_to_inspect"])}</p>'
        )

    if row["slug"] == "other":
        parts.append(
            '<p class="kyl-fine">These complaints sit outside the five types'
            " Know Your Loan scores separately, so no peer comparison is made for"
            " them.</p>"
        )
        return "".join(parts)

    comparison = row["comparison"]
    parts.append(
        f'<p class="kyl-dlabel">Compared with typical peers</p>'
        f'<p class="kyl-note">{esc(PEER_WORDING[comparison])}</p>'
    )

    # Method C is model output, so it is disclosure rather than a headline.
    parts.append(
        '<details class="kyl-advanced"><summary>Model detail</summary>'
        f'<p class="kyl-fine">Method C posterior, peer-referenced:'
        f' {row["score"]:.1f} of 100, where 50 is a typical peer. Posterior'
        f' estimate {row["prevalence"] * 100:.1f}% of this lender&rsquo;s'
        f' complaints, 90% credible interval {row["lo90"] * 100:.1f}&ndash;'
        f'{row["hi90"] * 100:.1f}%. This is a model output on a relative scale,'
        " not a grade and not a measure of lender quality.</p></details>"
    )
    return "".join(parts)



def _household_facts(inputs: dict) -> dict:
    """Score a household profile without drawing anything.

    Split from the render so the panel can decide what to show before it draws,
    and so the analysis box beside it can be given the same figures.

    The call goes through financial_impact.household_context, which is the same
    entry point the FastAPI service uses, so the feature order, the categorical
    category sets and the artifact are shared rather than restated. Percentile
    and band come back already computed; this function only reshapes them for
    the panel and keeps the raw rate for the model detail disclosure.
    """
    ctx = _fi.household_context(inputs)
    rate = float(ctx["model_association_rate"])
    return {
        "rate": rate * 100,
        "percentile": ctx.get("survey_percentile"),
        "band": ctx.get("band_label", ""),
        "summary": ctx.get("summary", ""),
        "caveats": ctx.get("caveats", []),
        "year": _HOUSEHOLD_CONTEXT.get("survey_year", "a national"),
    }


def _render_household(f: dict) -> None:
    """The household panel, read-only.

    The headline is the percentile within the survey, not the association rate.
    A 2016 survey association is easy to over-read as a personal forecast, and a
    percentage invites exactly that reading; "82nd of 6,394 surveyed
    households" does not. The rate itself is what the model actually outputs, so
    it is kept and shown -- but only behind a disclosure, as a technical detail.
    """
    pctile, band, summary, year = f["percentile"], f["band"], f["summary"], f["year"]
    caveats = f.get("caveats") or []
    section_card(
        '<p class="kyl-outcome-lab">Where this household sits in the survey</p>'
        f'<p class="kyl-outcome-val">{pctile}<span class="kyl-outcome-suffix">th'
        " percentile</span></p>"
        f'<p class="kyl-outcome-note"><b>{esc(band)}.</b> {esc(summary)}</p>'
        '<p class="kyl-note" style="margin-top:.7rem">A survey association from'
        f" {esc(year)}, not an eligibility determination and not a personal"
        " forecast. What that means, and what it does not, is in the Methodology"
        " panel.</p>"
    )
    if caveats:
        st.html(
            '<details class="kyl-advanced"><summary>What this reading assumes'
            "</summary><ul class=\"kyl-list kyl-fine\">"
            + "".join(f"<li>{esc(c)}</li>" for c in caveats)
            + "</ul></details>"
        )
    st.html(
        '<details class="kyl-advanced"><summary>Model detail</summary>'
        '<p class="kyl-fine">Raw model output, the share of modelled peer'
        f' households expected to have reported SNAP receipt: {f["rate"]:.1f}%.'
        " That figure is an association rate within survey data. It is not a"
        " probability that you would receive benefits, and it is not a score."
        "</p></details>"
    )
    st.html(
        '<p class="kyl-note">For an actual determination, eligibility is set by'
        " your state agency. Official program information: "
        f'<a href="{esc(SNAP_OFFICIAL)}" target="_blank" rel="noopener noreferrer">'
        "USDA Food and Nutrition Service &mdash; SNAP</a>.</p>"
    )


def _render_methodology() -> None:
    """What Know Your Loan observes, what it calculates, and what it cannot.

    Kept out of the three product tabs so each of those reads as a clean answer
    to one question. The uncomfortable sparsity statistics lead, because they
    are the reason the interface is worded the way it is.
    """
    st.html(
        '<div style="margin:1.5rem 0 1rem">'
        "<h2>Methodology</h2>"
        '<p class="kyl-note">What Know Your Loan directly observes, what it can'
        " calculate from that, and where the data stops.</p></div>"
    )

    stats = _complaint_evidence_stats()
    total_dims = int(stats["dimensions"]) if stats else 0
    n_distinct = 4
    n_lenders = dataset_summary()["lender_count"]

    left, right = st.columns(2, gap="large")

    with left:
        st.markdown("#### What Know Your Loan directly observes")
        st.markdown(
            "Counts and categories of CFPB payday-loan complaints associated with"
            " each lender, taken from the consumer complaint database. This is"
            " observed data. It is not modelled, and nothing on a lender page is"
            " inferred from it beyond arithmetic on these counts."
        )
        st.markdown(
            "<ul>"
            "<li>The lender's total payday-loan complaint count.</li>"
            "<li>The count in each of five complaint categories.</li>"
            "<li>The underlying CFPB issue label behind each of those counts.</li>"
            "<li>A residual category for complaints outside the five.</li>"
            "</ul>"
        )

        st.markdown("#### What Know Your Loan can calculate directly")
        st.markdown(
            "The composition of a lender's own complaints, which is what the"
            " profile leads with:"
        )
        st.html(
            '<p class="kyl-formula">ComplaintShare(i,c) ='
            " Complaints(i,c) / TotalPaydayComplaints(i)</p>",
        )
        st.markdown(
            "The five category counts and the residual add up to the lender's"
            " total, and their shares sum to one. That identity is asserted for"
            " every lender in the test suite."
        )

        st.markdown("#### What Know Your Loan cannot calculate")
        st.markdown(
            "A customer-level complaint rate. We do not have customer counts,"
            " loans originated, transaction volume or market share for any lender"
            " in this dataset, so the denominator of the obvious rate is missing:"
        )
        st.html(
            '<p class="kyl-formula kyl-formula-blocked">ComplaintRate ='
            " Complaints / Customers or Loans &mdash; not computable here</p>",
        )
        st.markdown(
            "This is why a share on a lender page is always stated as a share"
            " **of that lender's complaints**. A lender with 40% of its complaints"
            " about fees is not thereby a lender where 40% of customers"
            " experienced a fee problem, and the two statements are not"
            " interchangeable."
        )

    with right:
        st.markdown("#### Why Bayesian modelling is still used")
        st.markdown(
            "Because deciding whether an observed pattern is unusual requires"
            " more than comparing two numbers. Method C fits a Beta-Binomial"
            " posterior for each category, referenced to a fitted peer population"
            " whose median is the reference rate. A typical peer sits at 50 on"
            " that scale."
        )
        st.markdown(
            "Shrinkage is what stops a lender with two complaints from being"
            " reported as extreme. Its estimate is pulled toward the peer"
            " reference in proportion to how little data supports it, and a"
            " comparison is only stated when the 90% credible interval sits"
            " entirely on one side of the reference. Where it straddles it, the"
            " page says the data does not distinguish the lender from peers."
        )
        st.markdown(
            "The model is not used to produce the complaint profile, and it does"
            " not rank lenders. It only decides whether a peer comparison is"
            " responsible to make."
        )

        if stats:
            st.html(
                '<section class="kyl-card">'
                "<h3>How much the data supports</h3>"
                '<p class="kyl-note">Across all'
                f" {total_dims:,} lender-category observations in the dataset,"
                " measured on the current model:</p>"
                '<dl class="kyl-stats">'
                f"<dt>Observations not distinguishable from typical peers</dt>"
                f"<dd>{stats['similar_pct']:.1f}%</dd>"
                f"<dt>Observations resting on fewer than 10 complaints</dt>"
                f"<dd>{stats['thin_pct']:.1f}%</dd>"
                f"<dt>Median complaints behind a single observation</dt>"
                f"<dd>{stats['median_complaints']:.0f}</dd>"
                f"<dt>Median width of the 90% credible interval</dt>"
                f"<dd>{stats['median_interval_width']:.0f} percentage points</dd>"
                "</dl>"
                f'<p class="kyl-fine">Most observations are sparse, and the'
                f" median one carries no observed complaints at all. Only {n_distinct}"
                f" of {n_lenders} lenders are distinguishable across all five"
                " categories.</p></section>"
            )

        st.markdown("#### What that means for this product")
        st.markdown(
            "Know Your Loan therefore does not rank lenders by overall quality, and it"
            " publishes no overall score. It shows the observed complaint pattern,"
            " and makes a peer comparison only where the available evidence"
            " supports one. That is a limitation of what public complaint data"
            " can establish, not a claim that lender quality is unmeasurable in"
            " principle &mdash; it would need exposure denominators this dataset"
            " does not contain."
        )

        summary = dataset_summary()
        st.markdown("#### Complaint data caveats")
        for caveat in summary["methodology"]["caveats"]:
            st.markdown(f"- {caveat}")

        ctx = _HOUSEHOLD_CONTEXT
        st.markdown("#### Household Financial Context")
        if ctx:
            st.markdown(
                f'A separate analysis, from a different source. A'
                f' gradient-boosted classifier over the'
                f' {esc(ctx["households_modelled"])} households in the'
                f' {esc(ctx["survey"])} ({esc(ctx["survey_year"])}) estimating the'
                f' survey item "{esc(ctx["target"])}" as a proxy for financial'
                f' strain. Weighted holdout ROC-AUC'
                f' <b>{ctx["weighted_roc_auc"]:.4f}</b> on an 80/20 stratified'
                f" split, seed {esc(ctx['seed'])}."
            )
            st.markdown(
                "It is a survey association, not an eligibility determination and"
                " not a personal forecast, and it says nothing about any lender."
                " The two analyses are never combined and there is no overall"
                " Know Your Loan score."
            )
            st.markdown("**Caveats**")
            for caveat in ctx.get("caveats", []):
                st.markdown(f"- {caveat}")

        st.markdown("#### Loan Payoff Calculator")
        st.markdown(
            "Standard amortisation. Monthly interest is principal x APR / 12;"
            " payoff time solves the standard annuity equation, rounded up to a"
            " whole month. It is arithmetic on the numbers entered, not a quote,"
            " an offer, a rate comparison, or financial advice, and it ignores"
            " fees, missed payments and any rate change."
        )

        st.markdown("#### Sources")
        st.markdown(
            '<ul class="kyl-list">'
            "<li>CFPB consumer complaint database, payday loan products.</li>"
            "<li>CFPB National Financial Well-Being Survey, public-use file.</li>"
            f'<li>Official SNAP program information:'
            f' <a href="{esc(SNAP_OFFICIAL)}" target="_blank"'
            f' rel="noopener noreferrer">USDA Food and Nutrition Service</a>.</li>'
            "</ul>",
            unsafe_allow_html=True,
        )
        st.markdown(
            '<p class="kyl-fine">Complaints are consumer-submitted reports and do'
            " not necessarily indicate verified wrongdoing. A complaint is an"
            " allegation by a consumer, not a finding about the lender, and this"
            " interface describes what was reported rather than what occurred."
            "</p>",
            unsafe_allow_html=True,
        )


# --------------------------------------------------------------------------
# Page shell
# --------------------------------------------------------------------------

st.set_page_config(
    page_title="Know Your Loan",
    page_icon=":bar_chart:",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(stylesheet(), unsafe_allow_html=True)

# The one place a serif is used: the wordmark.
# The logo is served from static/, which is only reachable because
# server.enableStaticServing is on in .streamlit/config.toml. If it ever fails to
# load the alt text stands in for it, so the masthead never collapses.
st.html(
    # A teal band rather than plain text on the page, so the brand colour does
    # some work instead of appearing only in buttons and focus rings. The mark
    # goes straight onto it: the shark is drawn in pale blue and white, which
    # both clear the deep teal, and its background is already transparent.
    # The band is full-bleed, so its content needs an inner wrapper constrained
    # to the same 1120px column the page below uses, otherwise the wordmark
    # would sit against the viewport edge while everything else is inset.
    '<header class="kyl-header">'
    '<div class="kyl-header-inner">'
    '<span class="kyl-header-mark">'
    '<img src="app/static/kyl-logo.png" alt="" width="52" height="42">'
    "</span>"
    '<span class="kyl-header-text">'
    '<span class="kyl-mark">Know Your Loan</span>'
    '<span class="kyl-tag">Three independent tools for payday-loan questions</span>'
    "</span>"
    "</div>"
    "</header>"
)

EXAMPLES = _EXAMPLES
PLACEHOLDER = _PLACEHOLDER
PANEL_LENDER, PANEL_PAYOFF, PANEL_HOUSEHOLD, PANEL_METHOD = (
    _PANEL_LENDER,
    _PANEL_PAYOFF,
    _PANEL_HOUSEHOLD,
    _PANEL_METHOD,
)


def _route_query(text: str):
    return _route(text)


def _analysis_box(
    panel: str, fingerprint: str, build, *, from_query: bool
) -> None:
    """One panel's analysis box, invalidated when its figures move.

    Two ways in, one set of results: the query on the left, or the widgets in the
    panel. Both feed the same figures, and the analysis is keyed to a fingerprint
    of them. When a figure changes the stored analysis is thrown away and the box
    asks to be regenerated, rather than continuing to describe numbers that are no
    longer on screen. A stale analysis beside fresh figures is worse than none,
    because it reads as a description of what is displayed.

    ``from_query`` is what separates the two cases. When the panel's values are
    still the ones the query supplied, the analysis is generated immediately:
    that is the whole point of asking in natural language. Once a person has
    changed something themselves, nothing is generated until they press the
    button, because regenerating on every keystroke would narrate a half-typed
    figure.
    """
    key = f"{CHAT_KEY}_{panel}_analysis"
    fp_key = f"{key}_fp"

    if st.session_state.get(fp_key) != fingerprint:
        st.session_state.pop(key, None)
        st.session_state[fp_key] = fingerprint
        if from_query:
            st.session_state[key] = build()

    stored = st.session_state.get(key)
    if stored is not None:
        st.html(stored)
        if st.button(
            "Regenerate analysis",
            key=f"{key}_regen",
            help="Re-run the analysis against the figures currently shown.",
        ):
            st.session_state[key] = build()
            st.rerun()
        return

    st.html(
        '<div class="kyl-analysis kyl-analysis-stale">'
        '<p class="kyl-analysis-head">What this means</p>'
        '<p class="kyl-note">The figures above have changed since this was'
        " last read, so the analysis was cleared rather than left describing the"
        " old ones. Press regenerate to read the new ones.</p></div>"
    )
    if st.button("Regenerate analysis", key=f"{key}_regen2"):
        st.session_state[key] = build()
        st.rerun()


def _fingerprint(**parts) -> str:
    return "|".join(f"{k}={parts[k]!r}" for k in sorted(parts))


def _analysis_model():
    """The model used for the per-panel analysis, or None.

    The same seam and the same client as the lender narrative. A panel whose
    reply the guard rejects falls back to its deterministic text, so enabling
    the model cannot remove a limit statement.
    """
    return _gemini_model()


def _payoff_figures(offer):
    """Turn a parsed offer into the payoff figures, or None if it cannot."""
    if offer.principal is None or offer.principal <= 0:
        return None
    apr = offer.apr if offer.apr is not None else 0.0
    payment = offer.payment
    if payment is None and offer.principal and offer.apr is not None:
        # A single-payment structure has no periodic payment to read, so the
        # cost is the finance charge over the term instead.
        return {
            "principal": offer.principal,
            "apr": apr,
            "term_days": offer.term_days,
            "finance_charge": offer.finance_charge,
            "total_repayment": offer.total_repayment,
            "status": "single_payment",
        }
    if payment is None:
        return None
    est = _estimate_payoff(offer.principal, apr, float(payment))
    return {
        "principal": offer.principal,
        "apr": apr,
        "payment": float(payment),
        "status": est.status,
        "months": est.months,
        "years": est.years,
        "total_paid": est.total_paid,
        "total_interest": est.total_interest,
        "interest_share": est.interest_share,
        "monthly_interest": est.monthly_interest,
        "finance_charge": offer.finance_charge,
        "total_repayment": offer.total_repayment,
        "term_days": offer.term_days,
    }


def _render_payoff(p: dict) -> None:
    """The payoff panel, read-only."""
    if p.get("status") == "single_payment":
        rows = [("Loan amount", f"${p['principal']:,.2f}")]
        if p.get("finance_charge") is not None:
            rows.append(("Finance charge", f"${p['finance_charge']:,.2f}"))
        if p.get("total_repayment") is not None:
            rows.append(("Total repayment", f"${p['total_repayment']:,.2f}"))
        if p.get("term_days"):
            rows.append(("Term", f"{p['term_days']} days"))
        if p.get("apr") is not None:
            rows.append(("Annual percentage rate", f"{p['apr']:g}%"))
        st.html(
            '<dl class="kyl-figures">'
            + "".join(
                f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in rows
            )
            + "</dl>"
        )
        if p.get("finance_charge") and p.get("principal"):
            st.html(
                '<p class="kyl-note">That is '
                f"${p['finance_charge'] / p['principal'] * 100:,.2f} in charges"
                f" for every $100 borrowed.</p>"
            )
        return

    if p.get("status") == "interest_not_covered":
        alert(
            "danger",
            "Debt trap warning:",
            f"a ${p['payment']:,.2f} monthly payment does not cover the"
            f" ${p['monthly_interest']:,.2f} of interest accruing each month at"
            f" {p['apr']:g}%. The balance would grow rather than shrink.",
        )
        return
    if p.get("status") != "ok" or p.get("months") is None:
        st.html(
            '<p class="kyl-note">Not enough of the offer could be read to work'
            " out a payoff. An amount and a rate, or a payment, are needed.</p>"
        )
        return

    rows = [
        ("Loan amount", f"${p['principal']:,.2f}"),
        ("Monthly payment", f"${p['payment']:,.2f}"),
        ("Annual percentage rate", f"{p['apr']:g}%"),
        ("Payoff time", f"{p['months']} months (~{p['years']} years)"),
        ("Total repaid", f"${p['total_paid']:,.2f}"),
        ("Total interest", f"${p['total_interest']:,.2f}"),
        ("Interest share", f"{p['interest_share']:.1f}%"),
    ]
    st.html(
        '<dl class="kyl-figures">'
        + "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in rows)
        + "</dl>"
    )


def _lender_analysis(label: dict) -> str:
    """The analysis box on the lender panel."""
    rows = _complaint_rows(label)
    top = next((r for r in rows if r["slug"] != "other" and r["complaints"] > 0), None)
    facts = {
        "name": label["name"],
        "n_complaints": label["n_complaints"],
        "evidence": label["evidence"],
    }
    if top is not None:
        facts["top_category"] = top["label"]
        facts["top_share"] = round(top["share"] * 100, 1)
        facts["top_guidance"] = top.get("what_to_inspect", "")
    return _build_analysis("lender", facts, model=_analysis_model()).as_html()


def _household_analysis(f: dict) -> str:
    # band_label is the codebook's own band sentence, not the panel's long
    # summary: the analysis line sits under the panel and repeating the summary
    # there read as the same sentence twice.
    facts = {
        "band_label": f["band"],
        "percentile": f["percentile"],
        "rate": f["rate"],
    }
    return _build_analysis("household", facts, model=_analysis_model()).as_html()


def _payoff_analysis(p: dict) -> str:
    facts = {
        k: p[k]
        for k in (
            "principal", "apr", "payment", "months", "total_paid",
            "total_interest", "interest_share", "total_repayment",
        )
        if p.get(k) is not None
    }
    return _build_analysis("payoff", facts, model=_analysis_model()).as_html()


# ==========================================================================
# The interface: a query on the left, four read-only panels on the right
# ==========================================================================
# The query box decides which panels open. The panels display. The analysis box
# beside each panel explains it. There is no free-form answer surface, so there
# is nowhere for a model to volunteer advice about whether to take the loan, and
# nothing on screen is a figure the user did not supply.
_query_col, panels_col = st.columns([1, 2], gap="large")

with _query_col:
    # No top margin. The panels column starts with the first expander, which has
    # none, so a margin here put the heading a line lower than the panel it sits
    # beside. Both columns now begin at the same y.
    st.html(
        '<div class="kyl-prompt" style="margin:0 0 .6rem">'
        "<h2>Type in your offer</h2>"
        f'<p class="kyl-note">{esc(PLACEHOLDER)}</p>'
        "</div>"
    )

    with st.form(f"{CHAT_KEY}_form", border=False):
        # No visible label. The heading above already says what the field is, and
        # the panel now leads with an offer rather than a question, so a second
        # "Your question" contradicted it. Collapsed rather than hidden outright
        # so the control keeps its accessible name.
        _query = st.text_area(
            "Your question",
            placeholder="Uprova Credit, $300 at 391% for 14 days",
            height=120,
            key=f"{CHAT_KEY}_query",
            label_visibility="collapsed",
        )
        _submitted = st.form_submit_button("Analyze with AI", type="primary")

    if _submitted and _query.strip():
        st.session_state[CHAT_KEY] = _query.strip()
        st.rerun()

    _query_now = st.session_state.get(CHAT_KEY, "")
    _route = _route_query(_query_now) if _query_now else None

    # Every panel widget's key carries this token, so a new query produces new
    # widgets whose `value` is honoured. A keyed widget otherwise keeps its
    # session value across reruns and ignores a changed index, which left the
    # panels showing the previous query's figures and made every one of them look
    # hand-edited, so no analysis was ever generated for a new query.
    _TOKEN = hashlib.sha1((_query_now or "").encode("utf-8")).hexdigest()[:8]

    if st.session_state.get(f"{CHAT_KEY}_seeded_query") != _query_now:
        st.session_state[f"{CHAT_KEY}_seeded_query"] = _query_now
        for _panel in ("lender", "household", "payoff"):
            st.session_state.pop(f"{CHAT_KEY}_{_panel}_analysis", None)
            # The fingerprint has to go too. Clearing only the analysis left a
            # panel with a stored fingerprint and no analysis, and since the
            # fingerprint matched, the regenerate branch never ran again: the
            # panel was stuck on the cleared state for the rest of the session.
            st.session_state.pop(f"{CHAT_KEY}_{_panel}_analysis_fp", None)

    if _route is None:
        # One st.html call. Splitting the wrapper leaves Streamlit to auto-close
        # the unclosed div, which renders as a stray element under the button.
        st.html(
            '<div class="kyl-chat-empty">'
            f'<p class="kyl-note">{esc(PLACEHOLDER)}</p>'
            + "".join(
                f'<p class="kyl-chat-ex"><b>{esc(_ex)}</b><br>'
                f'<span class="kyl-fine">{esc(_desc)}</span></p>'
                for _ex, _desc in EXAMPLES
            )
            + "</div>"
        )
    else:
        st.html(
            '<div class="kyl-chat-status">'
            + "".join(f'<p class="kyl-note">{esc(n)}</p>' for n in _route.notes)
            + '<p class="kyl-fine">Open panels: '
            f"{esc(', '.join(_route.panels) if _route.panels else 'none')}.</p>"
            "</div>"
        )
        if _query_now:
            if st.button("Clear", key=f"{CHAT_KEY}_clear"):
                st.session_state.pop(CHAT_KEY, None)
                st.rerun()

# --- panel bodies, computed once and rendered read-only ---
_lender_label = None
if _route is not None and _route.has_lender:
    _lender_label = get_lender(_route.lender_id)

_payoff = None
if _route is not None and _route.offer.principal is not None:
    _payoff = _payoff_figures(_route.offer)

with panels_col:
    # --- 1. Lender complaint profile ---
    with st.expander(
        "Lender Complaint Profile",
        expanded=bool(_route and PANEL_LENDER in _route.panels),
    ):
        # Picking from the match list has to change what the field shows.
        # Streamlit refuses a write to a widget's session value once the widget
        # exists, so the field's key carries the pick: a new pick is a new key,
        # which is a new widget created with the chosen name as its value.
        if st.session_state.pop(f"{CHAT_KEY}_lender_pick", None) is not None:
            st.session_state[f"{CHAT_KEY}_lender_pick_n"] = (
                st.session_state.get(f"{CHAT_KEY}_lender_pick_n", 0) + 1
            )
        _pick_n = st.session_state.get(f"{CHAT_KEY}_lender_pick_n", 0)
        _picked_name = st.session_state.get(f"{CHAT_KEY}_lender_picked_name", "")

        _manual_lender = st.text_input(
            "Lender name",
            value=_picked_name
            or (_route.lender_name or "" if _route and _route.has_lender else ""),
            placeholder="Start typing a lender name",
            key=f"{CHAT_KEY}_lender_manual_{_TOKEN}_{_pick_n}",
        )
        if _picked_name:
            # Consumed: the widget now holds it, so the seed is not needed again
            # and a later rerun must not re-seed the field.
            st.session_state.pop(f"{CHAT_KEY}_lender_picked_name", None)

        _from_query = bool(
            _route and _route.has_lender and _route.lender_name == _manual_lender
        )
        _lender_id = _route.lender_id if (_route and _route.has_lender) else None
        if not _from_query and _manual_lender.strip():
            # find_lenders, not match_lenders_in_text. The field is a type-ahead,
            # so what someone types is a fragment of a name ("upr"), and the
            # fragment has to be looked for inside each name. The other function
            # answers the opposite question, a name inside a sentence, which is
            # what the query box needs and what this field was wrongly given.
            _found = _find_lenders(query=_manual_lender.strip(), limit=6)
            _hits = _found["data"]["lenders"] if _found.get("ok") else []
            if len(_hits) == 1:
                _lender_id = _hits[0]["id"]
            elif len(_hits) > 1:
                _lender_id = None
                st.html(
                    '<p class="kyl-pick-head">Matches for '
                    f"{esc(_manual_lender.strip())!r}</p>"
                )
                # The top three, as choices rather than a comma-separated list of
                # names to compare by eye. Beyond three the list stops being a
                # decision, and typing more narrows it anyway.
                for _col, _hit in zip(
                    st.columns(3), _hits[:3]
                ):
                    with _col:
                        if st.button(
                            _hit["name"],
                            key=f"{CHAT_KEY}_pick_{_hit['id']}_{_pick_n}",
                            width="stretch",
                            help=f"{_hit['n_complaints']} complaints"
                            f" · {_hit['evidence']}",
                        ):
                            st.session_state[f"{CHAT_KEY}_lender_pick"] = _hit["name"]
                            st.session_state[f"{CHAT_KEY}_lender_picked_name"] = _hit["name"]
                            st.rerun()
            else:
                _lender_id = None
                st.html(
                    '<p class="kyl-note">No lender in the dataset matches'
                    f" {esc(_manual_lender.strip())!r}.</p>"
                )

        _lender_label = get_lender(_lender_id) if _lender_id else None
        if _lender_label is not None:
            # Name, then the interpretation of it, then the evidence it rests on.
            # The analysis belongs directly under the name it describes; at the
            # bottom of the panel it read as a footnote to the bars.
            _render_lender_heading(_lender_label)
            _analysis_box(
                "lender",
                _fingerprint(lender=_lender_id, n=_lender_label["n_complaints"]),
                lambda: _lender_analysis(_lender_label),
                # The same rule as the other two panels: generate straight away
                # while the name is the one the query supplied, and clear to the
                # regenerate prompt once it has been typed over. Hardcoding True
                # here made the lender panel the only one whose analysis could
                # never go stale, which read as the cleared box being broken.
                from_query=_from_query,
            )
            _render_lender_report(_lender_label)
        else:
            st.html(
                '<p class="kyl-note">Name a lender above, or in your query, to'
                " see what consumers reported about them to the CFPB.</p>"
            )

    # --- 2. Household financial context ---
    with st.expander(
        "Household Financial Context",
        expanded=bool(_route and PANEL_HOUSEHOLD in _route.panels),
    ):
        # Deliberately not a form. Inside one, a change does not reach the script
        # until it is submitted, so the analysis box could not clear the moment a
        # figure moved, which is the behaviour this panel is required to have.
        if True:
            # Every widget works in survey codes, not list positions. The
            # previous version had selectboxes over label lists and a
            # number_input for household size, then converted index -> code; that
            # is where "the panel disagrees with its own seed" bugs came from,
            # and the number_input was worse than cosmetic because it could send
            # PPHHSIZE=20 for a model trained on codes 1-5. format_func puts the
            # label in front of the user while the value underneath stays the
            # code the booster was trained on.
            _seed = dict(_route.household) if _route else {}

            def _default(field: str, fallback: int) -> int:
                value = _seed.get(field, fallback)
                return value if isinstance(value, int) else fallback

            _c1, _c2 = st.columns(2)
            with _c1:
                _age = st.selectbox(
                    "Age group", sorted(_AGE_BANDS),
                    index=sorted(_AGE_BANDS).index(_default("age_band", 2)),
                    format_func=lambda c: _AGE_BANDS[c],
                    key=f"{CHAT_KEY}_age_{_TOKEN}",
                )
                _edu = st.selectbox(
                    "Highest education", sorted(_EDUCATION),
                    index=sorted(_EDUCATION).index(_default("education", 3)),
                    format_func=lambda c: _EDUCATION[c],
                    key=f"{CHAT_KEY}_edu_{_TOKEN}",
                )
                _marital = st.selectbox(
                    "Marital status", sorted(_MARITAL),
                    # Default 1 ("Married"), preserving the pre-codebook default.
                    # The survey has no "prefer not to say" option, so any default
                    # asserts something; this one at least matches what shipped
                    # before rather than silently changing it.
                    index=sorted(_MARITAL).index(_default("marital_status", 1)),
                    format_func=lambda c: _MARITAL[c],
                    key=f"{CHAT_KEY}_marital_{_TOKEN}",
                )
            with _c2:
                _income = st.selectbox(
                    "Household income", sorted(_INCOME),
                    index=sorted(_INCOME).index(_default("household_income", 4)),
                    format_func=lambda c: _INCOME[c],
                    key=f"{CHAT_KEY}_income_{_TOKEN}",
                )
                _metro = st.selectbox(
                    "Live in a city or metro area", sorted(_METRO),
                    index=sorted(_METRO).index(_default("metro_area", 1)),
                    format_func=lambda c: _METRO[c],
                    key=f"{CHAT_KEY}_metro_{_TOKEN}",
                )
                _size = st.selectbox(
                    "People in household", sorted(_SIZES),
                    index=sorted(_SIZES).index(_default("household_size", 3)),
                    format_func=lambda c: _SIZES[c],
                    key=f"{CHAT_KEY}_size_{_TOKEN}",
                )
                _poverty = st.selectbox(
                    "Poverty in your county", sorted(_POVERTY),
                    index=sorted(_POVERTY).index(_default("county_poverty_share", -5)),
                    format_func=lambda c: _POVERTY[c],
                    key=f"{CHAT_KEY}_poverty_{_TOKEN}",
                )
            # The four child-presence columns. These are real model inputs, not
            # decoration: the previous panel pinned total_children to 0 and
            # child_ratio to 0.0, so a fifth of the feature vector was constant
            # and the model was quietly scoring every household as childless.
            st.markdown("Children in your household")
            _ccols = st.columns(len(_CHILD_FIELDS))
            _children: dict[str, int] = {}
            for _i, (_field, _column) in enumerate(_CHILD_FIELDS.items()):
                with _ccols[_i]:
                    _children[_field] = int(
                        st.checkbox(
                            _fi.CHILD_AGE_LABELS[_column],
                            value=False,
                            key=f"{CHAT_KEY}_child_{_field}_{_TOKEN}",
                        )
                    )

        _hinputs = {
            "age_band": _age,
            "education": _edu,
            "household_income": _income,
            "marital_status": _marital,
            "household_size": _size,
            "metro_area": _metro,
            "county_poverty_share": _poverty,
            **_children,
        }
        _hfacts = _household_facts(_hinputs)
        _render_household(_hfacts)
        _analysis_box(
            "household",
            _fingerprint(**{k: v for k, v in sorted(_hinputs.items())}),
            lambda: _household_analysis(_hfacts),
            from_query=_hinputs == {
                "age_band": _default("age_band", 2),
                "education": _default("education", 3),
                "household_income": _default("household_income", 4),
                "marital_status": _default("marital_status", 1),
                "household_size": _default("household_size", 3),
                "metro_area": _default("metro_area", 1),
                "county_poverty_share": _default("county_poverty_share", -5),
                **{f: 0 for f in _CHILD_FIELDS},
            },
        )

    # --- 3. Loan payoff ---
    with st.expander(
        "Loan Payoff Calculator",
        expanded=bool(_route and PANEL_PAYOFF in _route.panels),
    ):
        # Not a form, for the same reason as the household panel above.
        if True:
            _seed_p = float(_route.offer.principal or 0.0) if _route else 0.0
            _seed_a = float(_route.offer.apr or 0.0) if _route else 0.0
            _seed_m = float(_route.offer.payment or 0.0) if _route else 0.0
            _p1, _p2, _p3 = st.columns(3)
            with _p1:
                _principal = st.number_input(
                    "Loan amount", min_value=0.0, max_value=10_000_000.0,
                    value=_seed_p, step=50.0, format="%.2f", key=f"{CHAT_KEY}_principal_{_TOKEN}",
                )
            with _p2:
                _apr = st.number_input(
                    "APR %", min_value=0.0, max_value=5000.0,
                    value=_seed_a, step=0.5, format="%.2f", key=f"{CHAT_KEY}_apr_{_TOKEN}",
                )
            with _p3:
                _payment = st.number_input(
                    "Monthly payment", min_value=0.0, max_value=10_000_000.0,
                    value=_seed_m, step=5.0, format="%.2f", key=f"{CHAT_KEY}_payment_{_TOKEN}",
                )

        if _principal > 0 and (_apr > 0 or _payment > 0):
            _po = _estimate_payoff(_principal, _apr, _payment)
            _pay = {
                "principal": _principal, "apr": _apr, "payment": _payment,
                "status": _po.status, "months": _po.months, "years": _po.years,
                "total_paid": _po.total_paid, "total_interest": _po.total_interest,
                "interest_share": _po.interest_share,
                "monthly_interest": _po.monthly_interest,
            }
            _render_payoff(_pay)
            _analysis_box(
                "payoff",
                _fingerprint(principal=_principal, apr=_apr, payment=_payment),
                lambda: _payoff_analysis(_pay),
                from_query=(
                    _principal == _seed_p and _apr == _seed_a and _payment == _seed_m
                ),
            )
        else:
            st.html(
                '<p class="kyl-note">Enter an amount and a rate above, or add'
                " them to your query, to see what the loan would cost.</p>"
            )

    # --- 4. Methodology ---
    with st.expander(
        "Methodology",
        expanded=bool(_route and PANEL_METHOD in _route.panels),
    ):
        _render_methodology()
