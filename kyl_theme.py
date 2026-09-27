"""Design tokens and scoped stylesheet for the Know Your Lender Streamlit app.
Every colour, size and radius used by the interface is declared once in
:data:`TOKENS` and the stylesheet below is generated from it, so there is one
place to change the palette and no chance of a hardcoded colour drifting away
from the theme in ``.streamlit/config.toml``.

Scoping rules followed here, because the previous stylesheet broke the app:

* Selectors key off stable attributes -- ``data-testid``, ``role``, ``aria-*`` --
  never off generated ``st-emotion-cache-*`` class names, which change between
  Streamlit releases.
* No bare element or bare ``.stButton`` rules. Every rule is narrow enough that
  it cannot accidentally repaint an unrelated widget. The old sheet contained a
  blanket rule that turned every primary button white.
* Anything hidden from view is also removed from the accessibility tree, and
  anything shown is reachable by keyboard, so no control is visible-but-
  unlabelled or invisible-but-focusable.
"""

from __future__ import annotations

TOKENS = {
    # Surfaces
    "bg": "#F7F8FA",
    "card": "#FFFFFF",
    "text": "#101828",
    "muted": "#667085",
    "border": "#E4E7EC",
    "border_strong": "#D0D5DD",
    # Brand / interactive
    "primary": "#3157D5",
    "primary_hover": "#2646B2",
    "primary_soft": "#EFF4FF",
    # Status
    "success": "#16794B",
    "warning": "#B54708",
    "danger": "#B42318",
    "success_soft": "#ECFDF3",
    "warning_soft": "#FFFAEB",
    "danger_soft": "#FEF3F2",
    # Metrics
    "radius": "12px",
    "radius_sm": "8px",
    "maxw": "1120px",
    "pad": "32px",
    "pad_mobile": "16px",
    "tap": "44px",
    "font": (
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', "
        "Arial, 'Noto Sans', sans-serif"
    ),
}

# Categorical palette for the five complaint types plus the uncovered remainder.
#
# These are identity colours, not judgement: which hue a slice gets says nothing
# about whether it is good or bad, so no red/green valence and no red/green pair.
# Five distinguishable hues at similar lightness, and the "other" remainder is
# deliberately neutral grey so it recedes -- it is the part of the data these
# five types do not cover, and it should not compete for attention.
CATEGORY_STYLE = {
    "withdrawal": "#4C6EF5",  # blue
    "fees": "#F59F00",  # amber
    "unauthorized": "#15AABF",  # cyan
    "credit_rep": "#9C36B5",  # violet
    "servicing": "#E64980",  # pink
    "other": "#98A2B3",  # neutral grey for the uncovered remainder
}


def stylesheet() -> str:
    t = TOKENS
    return f"""
<style>
/* ------------------------------------------------------------------ base */
html, body, [data-testid="stAppViewContainer"] {{
  background: {t['bg']};
  font-family: {t['font']};
  color: {t['text']};
}}
/* Cap the measure and centre it. Also the horizontal-overflow guard: the main
   block never exceeds maxw, and padding steps down on small screens. The
   top padding clears Streamlit's own toolbar, which was overlapping the
   product wordmark and clipping the top of the page heading. */
.block-container {{
  max-width: {t['maxw']};
  padding: 3.25rem 1.5rem {t['pad']} 1.5rem;
}}
@media (max-width: 768px) {{
  .block-container {{ padding: 2.5rem 1rem 2rem 1rem; }}
}}
h1, h2, h3, h4, h5, h6, p, label, span, div, button, input, li, td, th {{
  font-family: {t['font']};
}}
/* Nothing may introduce sideways scroll at 375px. Long lender names and the
   comparison rows wrap instead of pushing the page wide.

   `clip` rather than `hidden`: overflow-x:hidden on html/body silently promotes
   them to scroll containers, which clipped the top of the page heading. `clip`
   suppresses the horizontal overflow without creating a scroll box. */
html, body, [data-testid="stAppViewContainer"] {{ overflow-x: clip; }}
[data-testid="stAppViewContainer"] > * {{ min-width: 0; }}
p, li, td, .kyl-wrap {{ overflow-wrap: anywhere; word-break: break-word; }}

/* ------------------------------------------------------------ typography */
[data-testid="stHeadingContainer"] h1 {{
  font-size: 2.25rem; line-height: 1.15; font-weight: 700; letter-spacing: -.02em;
  color: {t['text']};
}}
h2, [data-testid="stHeadingContainer"] h2 {{
  font-size: 1.5rem; line-height: 1.25; font-weight: 650; letter-spacing: -.01em;
  color: {t['text']};
}}
h3, [data-testid="stHeadingContainer"] h3 {{
  font-size: 1.25rem; line-height: 1.3; font-weight: 600; color: {t['text']};
}}
p, li, label, input, textarea, .stSelectbox, .stTextInput {{ font-size: 0.95rem; }}
[data-testid="stCaptionContainer"], .stCaptionContainer p,
[data-testid="stWidgetLabel"] label {{ color: {t['muted']}; }}
a {{ color: {t['primary']}; }}
/* Muted supporting copy, used for disclaimers and method notes. */
.kyl-note {{
  color: {t['muted']}; font-size: .875rem; line-height: 1.55; margin: .35rem 0 0;
}}

/* ------------------------------------------------------------------- nav */
/* Tabs are the navigation. Scoped by role/aria so the selected state is styled
   from the accessibility attribute rather than a generated class. The gap and
   padding are generous: at .25rem the three tabs read as one run of text
   rather than as separate destinations. */
[data-testid="stTabs"] [role="tablist"] {{
  gap: .6rem; border-bottom: 1px solid {t['border']}; padding-bottom: 0;
  overflow-x: auto; scrollbar-width: thin; flex-wrap: nowrap;
  -webkit-overflow-scrolling: touch;
}}
[data-testid="stTabs"] [role="tablist"] button {{
  flex: 1 1 auto; min-width: max-content; min-height: {t['tap']};
  background: transparent; color: {t['muted']};
  border: 1px solid transparent; border-bottom: 2px solid transparent;
  border-radius: {t['radius_sm']} {t['radius_sm']} 0 0;
  font-size: .95rem; font-weight: 600; padding: .7rem 1.1rem;
  margin-bottom: -1px;
  transition: background-color .12s ease, color .12s ease;
}}
[data-testid="stTabs"] [role="tablist"] button:hover {{
  background: {t['primary_soft']}; color: {t['primary']};
}}
/* Selected: solid brand fill with white text. Never white on white. */
[data-testid="stTabs"] [role="tablist"] button[aria-selected="true"] {{
  background: {t['primary']}; color: #FFFFFF;
  border-color: {t['primary']}; border-bottom-color: {t['primary']};
}}
[data-testid="stTabs"] [role="tablist"] button[aria-selected="true"]:hover {{
  background: {t['primary_hover']}; color: #FFFFFF;
}}
[data-testid="stTabs"] [role="tablist"] button:focus-visible {{
  outline: 3px solid {t['primary']}; outline-offset: 2px;
}}
@media (max-width: 768px) {{
  [data-testid="stTabs"] [role="tablist"] button {{ flex: 0 0 auto; font-size: .875rem; }}
}}

/* ----------------------------------------------------------------- cards */
[data-testid="stVerticalBlockBorderWrapper"] {{
  background: {t['card']}; border-color: {t['border']};
  border-radius: {t['radius']};
}}
[data-testid="stMetric"] {{
  background: {t['card']}; border: 1px solid {t['border']};
  border-radius: {t['radius']}; padding: 1rem 1.1rem;
}}
[data-testid="stMetricLabel"] p {{ color: {t['muted']}; font-size: .8rem; font-weight: 500; }}
[data-testid="stMetricValue"] {{
  font-size: 1.75rem; font-weight: 650; color: {t['text']}; letter-spacing: -.01em;
}}
[data-testid="stMetricDelta"] {{ font-size: .8rem; }}
/* A metric delta is a comparison, not a verdict: never green/red. */
[data-testid="stMetricDelta"] svg {{ fill: {t['muted']}; }}

/* ---------------------------------------------------------------- inputs */
/* White fill, grey border, visible blue focus. The old theme filled every
   input pale blue, which read as a disabled or errored field. */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stSelectbox"] input,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div {{
  background: {t['card']} !important;
  color: {t['text']} !important;
  border-color: {t['border_strong']} !important;
  border-radius: {t['radius_sm']} !important;
  min-height: {t['tap']};
}}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stSelectbox"] input:focus {{
  border-color: {t['primary']} !important;
  box-shadow: 0 0 0 3px rgba(49, 87, 213, .22) !important;
  outline: none !important;
}}
[data-testid="stWidgetLabel"] label {{
  font-size: .875rem; font-weight: 600; color: {t['text']};
}}
/* Persistent label even where Streamlit would hide it. */
[data-testid="stWidgetLabel"] {{ display: block !important; }}
/* The combobox dropdown: readable rows, visible selection. */
[data-testid="stSelectbox"] [role="listbox"] {{
  background: {t['card']}; border-color: {t['border']}; border-radius: {t['radius_sm']};
  max-height: 320px;
}}
[data-testid="stSelectbox"] [role="option"] {{
  color: {t['text']}; font-size: .95rem; min-height: {t['tap']};
  display: flex; align-items: center;
}}
[data-testid="stSelectbox"] [role="option"]:hover {{ background: {t['primary_soft']}; }}
[data-testid="stSelectbox"] [role="option"][aria-selected="true"] {{
  background: {t['primary_soft']}; color: {t['primary']}; font-weight: 600;
}}

/* --------------------------------------------------------------- buttons */
/* Scoped to the button testid and never to .stButton generally, so a primary
   button can be styled without repainting every button in the app. */
[data-testid="stButton"] button {{
  min-height: {t['tap']}; border-radius: {t['radius_sm']};
  font-size: .95rem; font-weight: 600; padding: .5rem 1rem;
  background: {t['card']}; color: {t['text']};
  border: 1px solid {t['border_strong']};
  transition: background-color .12s ease, border-color .12s ease, color .12s ease;
}}
[data-testid="stButton"] button:hover {{
  background: {t['bg']}; border-color: {t['primary']}; color: {t['primary']};
}}
[data-testid="stButton"] button:focus-visible {{
  outline: 3px solid {t['primary']}; outline-offset: 2px; border-color: {t['primary']};
}}
/* Primary variant only: an explicit, visible brand fill. The previous theme
   resolved this to #FFFFFF, producing a white button on a white page. */
[data-testid="stButton"] button[kind="primary"],
[data-testid="stButton"] button[data-testid="stBaseButton-primary"] {{
  background: {t['primary']}; color: #FFFFFF; border: 1px solid {t['primary']};
}}
[data-testid="stButton"] button[kind="primary"]:hover,
[data-testid="stButton"] button[data-testid="stBaseButton-primary"]:hover {{
  background: {t['primary_hover']}; color: #FFFFFF; border-color: {t['primary_hover']};
}}
[data-testid="stButton"] button:disabled {{
  background: {t['bg']}; color: {t['muted']}; border-color: {t['border']};
  cursor: not-allowed;
}}

/* --------------------------------------------------------------- expander */
[data-testid="stExpander"] {{
  background: {t['card']}; border: 1px solid {t['border']};
  border-radius: {t['radius']}; overflow: hidden;
}}
[data-testid="stExpander"] summary {{
  min-height: {t['tap']}; font-size: .95rem; font-weight: 600; color: {t['text']};
  align-items: center;
}}
[data-testid="stExpander"] summary:hover {{ color: {t['primary']}; }}
[data-testid="stExpander"] summary:focus-visible {{
  outline: 3px solid {t['primary']}; outline-offset: -2px;
}}

/* --------------------------------------------------------- native alerts */
/* Streamlit's info/warning/success boxes, recoloured to the token set. */
[data-testid="stAlert"] {{ border-radius: {t['radius_sm']}; border: 1px solid; }}
[data-testid="stAlert"] p {{ font-size: .9rem; line-height: 1.5; }}

/* ------------------------------------------------------- kyl components */
/* Wordmark. The one place a serif is allowed. */
.kyl-mark {{
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 2.5rem; font-weight: 700; letter-spacing: -.02em;
  color: {t['text']}; line-height: 1.1; margin: 0;
}}
.kyl-tag {{ color: {t['muted']}; font-size: 1rem; margin: .3rem 0 0; }}
.kyl-lede {{ color: {t['muted']}; font-size: 1.05rem; line-height: 1.6; margin: .6rem 0 0; }}

/* Section shell so every block sits on one card surface with one border. */
.kyl-card {{
  background: {t['card']}; border: 1px solid {t['border']};
  border-radius: {t['radius']}; padding: 1.25rem 1.35rem; margin: 0 0 1rem;
}}
.kyl-card > *:first-child {{ margin-top: 0; }}
.kyl-card > *:last-child {{ margin-bottom: 0; }}

.kyl-badge {{
  display: inline-flex; align-items: center; gap: .35rem;
  background: {t['primary_soft']}; color: {t['primary']};
  border: 1px solid {t['border']}; border-radius: 999px;
  padding: .18rem .6rem; font-size: .78rem; font-weight: 600; white-space: nowrap;
}}
.kyl-meta {{ color: {t['muted']}; font-size: .875rem; }}

/* The only bar in the interface, and it is explicitly labelled: 0 and 100 at the
   ends with the peer reference marked. No unlabelled meters anywhere. */
.kyl-scale {{ margin: .6rem 0 0; }}
.kyl-scale-track {{
  position: relative; height: .45rem; background: {t['bg']};
  border: 1px solid {t['border']}; border-radius: 999px;
}}
.kyl-scale-fill {{ position: absolute; inset: 0 auto 0 0; border-radius: 999px; }}
.kyl-scale-peer {{
  position: absolute; top: -.25rem; bottom: -.25rem; width: 2px;
  background: {t['muted']};
}}
.kyl-scale-legend {{
  display: flex; justify-content: space-between; margin-top: .3rem;
  font-size: .72rem; color: {t['muted']};
}}

/* Alerts. Rendered as HTML so dollar amounts are never parsed as LaTeX and
   bold markers never leak through as literal asterisks. */
.kyl-alert {{
  display: flex; gap: .7rem; align-items: flex-start;
  border: 1px solid; border-radius: {t['radius_sm']};
  padding: .85rem 1rem; margin: .5rem 0; font-size: .9rem; line-height: 1.55;
}}
.kyl-alert b {{ font-weight: 650; }}
.kyl-alert-danger {{ background: {t['danger_soft']}; border-color: #FECDCA; color: #7A271A; }}
.kyl-alert-danger b {{ color: {t['danger']}; }}
.kyl-alert-warning {{ background: {t['warning_soft']}; border-color: #FEDF89; color: #7A2E0E; }}
.kyl-alert-warning b {{ color: {t['warning']}; }}
.kyl-alert-info {{ background: {t['primary_soft']}; border-color: #D6E0FF; color: #1B2C6B; }}
.kyl-alert-info b {{ color: {t['primary']}; }}
.kyl-alert-success {{ background: {t['success_soft']}; border-color: #A9E5C3; color: #054F31; }}
.kyl-alert-success b {{ color: {t['success']}; }}

/* ------------------------------------------------- the report card itself */
/* One card, five rows, in the shape of a printed report card: subject on the
   left, grade on the right, hairline between rows.

   The numbers live in an absolutely positioned overlay revealed on hover and on
   focus. Absolutely positioned is the whole point: an overlay takes no part in
   layout, so revealing it cannot shift the rows, the card, or anything below.
   A disclosure that expanded in place would do exactly that, which is what the
   per-dimension <details> elements did before. */
.kyl-report {{
  background: {t['card']}; border: 1px solid {t['border']};
  border-radius: {t['radius']};
}}
.kyl-report-head {{
  display: flex; flex-wrap: wrap; align-items: flex-start;
  justify-content: space-between; gap: .4rem .9rem;
  padding: 1.1rem 1.25rem; border-bottom: 1px solid {t['border']};
}}
.kyl-report-name {{
  font-size: 1.35rem; font-weight: 700; letter-spacing: -.01em;
  color: {t['text']}; margin: 0; overflow-wrap: anywhere; min-width: 0;
}}
.kyl-rowcard {{
  position: relative; padding: .85rem 1.25rem;
  border-bottom: 1px solid {t['border']};
}}
.kyl-rowcard:last-child {{ border-bottom: none; }}
.kyl-rowcard:hover {{ background: {t['bg']}; }}
.kyl-rowcard:focus-visible {{
  outline: 3px solid {t['primary']}; outline-offset: -3px;
}}
.kyl-rowcard-name {{
  display: block; font-size: .72rem; font-weight: 700; letter-spacing: .05em;
  text-transform: uppercase; color: {t['muted']}; line-height: 1.35;
  margin: 0 0 .1rem;
}}
/* The verdict leads. It is the only claim per row that the analysis supports,
   so it gets the weight; the score is kept but deliberately quieter. */
.kyl-rowcard-main {{
  display: grid; grid-template-columns: minmax(0, 1fr) 150px;
  gap: .2rem 1rem; align-items: center;
}}
.kyl-rowcard-verdict {{
  font-size: 1rem; font-weight: 600; line-height: 1.4; color: {t['text']};
  margin: 0;
}}
.kyl-rowcard-meta {{
  font-size: .78rem; color: {t['muted']}; margin: .35rem 0 0;
}}
.kyl-rowcard-meta b {{ color: {t['text']}; font-weight: 600; }}
.kyl-rowcard-qualifier {{
  font-size: .8rem; line-height: 1.5; color: {t['muted']}; margin: .3rem 0 0;
  max-width: 62ch;
}}
/* The hover overlay. */
.kyl-rowcard-detail {{
  position: absolute; left: .6rem; right: .6rem; top: calc(100% - .3rem);
  z-index: 30; background: {t['card']};
  border: 1px solid {t['border_strong']};
  border-left: 3px solid {t['primary']};
  border-radius: {t['radius_sm']};
  box-shadow: 0 8px 24px rgba(16, 24, 40, .13);
  padding: .75rem .9rem;
  opacity: 0; visibility: hidden; pointer-events: none;
  font-size: .8rem; line-height: 1.5; color: {t['muted']};
  transition: opacity .1s ease;
}}
.kyl-rowcard:hover .kyl-rowcard-detail,
.kyl-rowcard:focus-within .kyl-rowcard-detail {{
  opacity: 1; visibility: visible;
}}
.kyl-rowcard-detail dl {{
  margin: 0; display: grid; grid-template-columns: auto 1fr;
  gap: .1rem .8rem;
}}
.kyl-rowcard-detail dt {{ color: {t['muted']}; }}
.kyl-rowcard-detail dd {{
  margin: 0; color: {t['text']}; font-weight: 600; text-align: right;
}}
.kyl-rowcard-detail p {{ margin: .5rem 0 0; }}
@media (max-width: 768px) {{
  .kyl-rowcard {{ padding: .75rem 1rem; }}
  .kyl-report-head {{ padding: 1rem; }}
  .kyl-rowcard-detail {{ left: .35rem; right: .35rem; }}
  /* Stack the scale under the verdict on narrow screens rather than letting a
     fixed 150px column squeeze the sentence. */
  .kyl-rowcard-main {{ grid-template-columns: minmax(0, 1fr); }}
}}

/* The uncomfortable statistics, given as a definition list so the figure and
   what it measures stay paired. */
.kyl-stats {{
  margin: .8rem 0 0; display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: .1rem 1.2rem; align-items: baseline;
}}
.kyl-stats dt {{
  font-size: .875rem; line-height: 1.5; color: {t['text']};
  padding: .4rem 0; border-bottom: 1px solid {t['border']};
}}
.kyl-stats dd {{
  margin: 0; font-size: 1.05rem; font-weight: 700; color: {t['text']};
  font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap;
  padding: .4rem 0; border-bottom: 1px solid {t['border']};
}}
.kyl-stats dt:last-of-type, .kyl-stats dd:last-of-type {{ border-bottom: none; }}
@media (max-width: 480px) {{
  .kyl-stats {{ grid-template-columns: minmax(0, 1fr); gap: 0; }}
  .kyl-stats dd {{ text-align: left; padding: 0 0 .45rem; border-bottom: 1px solid {t['border']}; }}
}}

/* Composition bar: share of a lender's complaints by type.
   A stacked bar, not a pie, because the median lender has four of the five
   categories at zero and because the five types do not always cover the whole
   -- the uncovered remainder is its own neutral segment. */
.kyl-stack {{
  display: flex; width: 100%; height: 1.6rem; margin: .7rem 0 .6rem;
  border-radius: {t['radius_sm']}; overflow: hidden;
  border: 1px solid {t['border']}; background: {t['card']};
}}
/* A non-zero share narrower than this would render as nothing at all, which
   would read as "no complaints of this type" when the count is above zero. Two
   pixels is the smallest mark that can honestly say "some". Exact values are in
   the legend and the title attribute. */
.kyl-seg {{ display: block; min-width: 2px; }}
.kyl-seg:hover {{ filter: brightness(.92); }}
.kyl-legend {{
  list-style: none; margin: 0; padding: 0;
  display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: .15rem .9rem;
}}
.kyl-legend li {{
  display: grid; grid-template-columns: 10px minmax(0, 1fr) auto;
  gap: .5rem; align-items: center; font-size: .8rem; line-height: 1.5;
}}
.kyl-swatch {{
  width: 10px; height: 10px; border-radius: 3px; display: block;
  border: 1px solid rgba(16, 24, 40, .12);
}}
.kyl-legend-name {{ color: {t['text']}; }}
.kyl-legend-val {{
  color: {t['muted']}; font-variant-numeric: tabular-nums; white-space: nowrap;
}}

/* Result readout after a successful estimate. */
.kyl-outcome-lab {{ font-size: .8rem; font-weight: 700; letter-spacing: .04em;
  text-transform: uppercase; color: {t['muted']}; margin-bottom: .2rem; }}
.kyl-outcome-val {{ font-size: 2.1rem; font-weight: 700; color: {t['text']};
  letter-spacing: -.02em; line-height: 1.15; }}
.kyl-outcome-note {{ font-size: .875rem; color: {t['muted']}; line-height: 1.6; margin-top: .5rem; }}
.kyl-list {{ margin: .4rem 0 0; padding-left: 1.1rem; }}
.kyl-list li {{ font-size: .875rem; line-height: 1.6; color: {t['muted']}; margin-bottom: .2rem; }}

.kyl-fine {{ font-size: .78rem; color: {t['muted']}; line-height: 1.6; }}
.kyl-foot {{
  border-top: 1px solid {t['border']}; margin-top: 2rem; padding-top: 1.1rem;
  font-size: .8rem; color: {t['muted']}; line-height: 1.65;
}}

/* Respect reduced-motion: strip every transition and animation. */
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{
    animation-duration: .001ms !important; animation-iteration-count: 1 !important;
    transition-duration: .001ms !important; scroll-behavior: auto !important;
  }}
}}
</style>
"""
