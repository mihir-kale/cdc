"""Design tokens and scoped stylesheet for the Know Your Loan Streamlit app.
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
    # Two teals, one hue family. `primary` is the readable teal and carries
    # everything that has to pass contrast: white text on it, or teal text on the
    # page. `accent` is the brand teal, used where it is a large mark rather than
    # a background for text.
    #
    # The brand teal on its own does not pass: #26A8D6 is 2.74:1 against white
    # and 2.58:1 as text on the #F7F8FA page, both short of the 4.5:1 needed for
    # body text. Deriving #0E7490 from the same hue gives 5.36:1 and 5.04:1, so
    # the interface stays legible while still reading as teal.
    "primary": "#0E7490",
    "primary_hover": "#0A5F76",
    "primary_soft": "#E6F3F8",
    "accent": "#26A8D6",
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
    # Two families. Titillium Web carries body copy, Montserrat carries headings
    # and the wordmark. Both are declared as [[theme.fontFaces]] in
    # .streamlit/config.toml and served from static/fonts/, not fetched from a
    # CDN: Streamlit strips @import from injected HTML, and a page showing
    # household financial details should not call a font CDN on every view. The
    # system stack behind each is the fallback if the files never arrive, so a
    # blocked or slow request degrades to something legible.
    "font": (
        "'Titillium Web', -apple-system, BlinkMacSystemFont, 'Segoe UI', "
        "Roboto, 'Helvetica Neue', Arial, sans-serif"
    ),
    "font_display": (
        "'Montserrat', -apple-system, BlinkMacSystemFont, 'Segoe UI', "
        "Roboto, 'Helvetica Neue', Arial, sans-serif"
    ),
}

# Categorical palette for the five complaint types plus the uncovered remainder.
#
# These are identity colours, not judgement: which hue a slice gets says nothing
# about whether it is good or bad, so no red/green valence and no red/green pair.
# Five distinguishable hues at similar lightness, and the "other" remainder is
# deliberately neutral grey so it recedes -- it is the part of the data these
# five types do not cover, and it should not compete for attention.
def stylesheet() -> str:
    t = TOKENS
    return f"""
<style>
/* ------------------------------------------------------------------ base */
html, body, [data-testid="stAppViewContainer"]{{
background:{t['bg']};
font-family:{t['font']};
color:{t['text']};
}}
/* Cap the measure and centre it. Also the horizontal-overflow guard: the main
   block never exceeds maxw, and padding steps down on small screens. The
   top padding clears Streamlit's own toolbar, which was overlapping the
   product wordmark and clipping the top of the page heading. */
.block-container{{
max-width:{t['maxw']};
padding: 3.25rem 1.5rem{t['pad']} 1.5rem;
}}
@media (max-width: 768px) {{
.block-container{{ padding: 2.5rem 1rem 2rem 1rem; }}
}}
h1, h2, h3, h4, h5, h6{{ font-family:{t['font_display']}; }}
p, label, span, div, button, input, textarea, li, td, th{{
font-family:{t['font']};
}}
/* Nothing may introduce sideways scroll at 375px. Long lender names and the
   comparison rows wrap instead of pushing the page wide.

   `clip` rather than `hidden`: overflow-x:hidden on html/body silently promotes
   them to scroll containers, which clipped the top of the page heading. `clip`
   suppresses the horizontal overflow without creating a scroll box. */
html, body, [data-testid="stAppViewContainer"]{{ overflow-x: clip; }}
[data-testid="stAppViewContainer"] > *{{ min-width: 0; }}
p, li, td, .kyl-wrap{{ overflow-wrap: anywhere; word-break: break-word; }}

/* ------------------------------------------------------------ typography */
[data-testid="stHeadingContainer"] h1{{
  font-size: 2.25rem; line-height: 1.15; font-weight: 700; letter-spacing: -.02em;
color:{t['text']};
}}
h2, [data-testid="stHeadingContainer"] h2{{
  font-size: 1.5rem; line-height: 1.25; font-weight: 650; letter-spacing: -.01em;
color:{t['text']};
}}
h3, [data-testid="stHeadingContainer"] h3{{
font-size: 1.25rem; line-height: 1.3; font-weight: 600; color:{t['text']};
}}
p, li, label, input, textarea, .stSelectbox, .stTextInput{{ font-size: 0.95rem; }}
[data-testid="stCaptionContainer"], .stCaptionContainer p,
[data-testid="stWidgetLabel"] label{{ color: {t['muted']}; }}
a{{ color: {t['primary']}; }}
/* Muted supporting copy, used for disclaimers and method notes. */
.kyl-note{{
color:{t['muted']}; font-size: .875rem; line-height: 1.55; margin: .35rem 0 0;
}}

/* ------------------------------------------------------------------- nav */
/* Tabs are the navigation, styled from the accessibility attributes rather than a
   generated class, so the selected state survives a Streamlit upgrade.

   The target is [role="tab"], NOT button. Streamlit 1.64 renders each tab as a
   div[role="tab"] wrapping a markdown paragraph; there is no button element in
   the tablist at all. An earlier version of this file styled
   "[role=tablist] button", which matched nothing, so every rule below was dead
   and the tabs fell back to whatever the host theme happened to be. That is how
   they ended up white on white: with .streamlit/config.toml missing, the
   deployed app inherited a theme whose tab text is white while this app's own
   background is light.

   Colour is now set on the tab AND on its descendants, because the visible text
   is a paragraph inside a markdown container and an inherited colour can be
   overridden downstream. Verified in Chrome rather than assumed. */
[data-testid="stTabs"] [role="tablist"] {{
  gap: .4rem; border-bottom: 1px solid {t['border']}; padding-bottom: 0;
  overflow-x: auto; scrollbar-width: thin; flex-wrap: nowrap;
  -webkit-overflow-scrolling: touch;
}}
[data-testid="stTabs"] [role="tablist"] [role="tab"] {{
  flex: 1 1 auto; min-width: max-content; min-height: {t['tap']};
  display: flex; align-items: center;
  background: transparent;
  color: {t['muted']};
  border: 1px solid transparent; border-bottom: 2px solid transparent;
  border-radius: {t['radius_sm']} {t['radius_sm']} 0 0;
  font-size: .95rem; font-weight: 600; padding: .7rem 1.1rem;
  margin-bottom: -1px; cursor: pointer;
  transition: background-color .12s ease, color .12s ease;
}}
/* The label is a <p> inside the tab, so pin it rather than inherit into it. */
[data-testid="stTabs"] [role="tablist"] [role="tab"] p,
[data-testid="stTabs"] [role="tablist"] [role="tab"] span,
[data-testid="stTabs"] [role="tablist"] [role="tab"] div {{
  color: inherit; font: inherit;
}}
[data-testid="stTabs"] [role="tablist"] [role="tab"]:hover {{
  background: {t['primary_soft']}; color: {t['primary']};
}}
/* Selected: solid brand fill with white text. Never white on white. */
[data-testid="stTabs"] [role="tablist"] [role="tab"][aria-selected="true"] {{
  background: {t['primary']}; color: #FFFFFF;
  border-color: {t['primary']}; border-bottom-color: {t['primary']};
}}
[data-testid="stTabs"] [role="tablist"] [role="tab"][aria-selected="true"]:hover {{
  background: {t['primary_hover']}; color: #FFFFFF;
}}
[data-testid="stTabs"] [role="tablist"] [role="tab"]:focus-visible {{
  outline: 3px solid {t['primary']}; outline-offset: 2px;
}}
@media (max-width: 768px) {{
  [data-testid="stTabs"] [role="tablist"] [role="tab"] {{ flex: 0 0 auto; font-size: .875rem; }}
}}

/* ----------------------------------------------------------------- cards */
[data-testid="stVerticalBlockBorderWrapper"]{{
background:{t['card']}; border-color: {t['border']};
border-radius:{t['radius']};
}}
[data-testid="stMetric"]{{
background:{t['card']}; border: 1px solid {t['border']};
border-radius:{t['radius']}; padding: 1rem 1.1rem;
}}
[data-testid="stMetricLabel"] p{{ color: {t['muted']}; font-size: .8rem; font-weight: 500; }}
[data-testid="stMetricValue"]{{
font-size: 1.75rem; font-weight: 650; color:{t['text']}; letter-spacing: -.01em;
}}
[data-testid="stMetricDelta"]{{ font-size: .8rem; }}
/* A metric delta is a comparison, not a verdict: never green/red. */
[data-testid="stMetricDelta"] svg{{ fill: {t['muted']}; }}

/* ---------------------------------------------------------------- inputs */
/* White fill, grey border, visible blue focus. The old theme filled every
   input pale blue, which read as a disabled or errored field. */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stSelectbox"] input,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div{{
background:{t['card']} !important;
color:{t['text']} !important;
border-color:{t['border_strong']} !important;
border-radius:{t['radius_sm']} !important;
min-height:{t['tap']};
}}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus,
[data-testid="stSelectbox"] input:focus{{
border-color:{t['primary']} !important;
  box-shadow: 0 0 0 3px rgba(49, 87, 213, .22) !important;
  outline: none !important;
}}
[data-testid="stWidgetLabel"] label{{
font-size: .875rem; font-weight: 600; color:{t['text']};
}}
/* Persistent label even where Streamlit would hide it. */
[data-testid="stWidgetLabel"]{{ display: block !important; }}
/* The combobox dropdown: readable rows, visible selection. */
[data-testid="stSelectbox"] [role="listbox"]{{
background:{t['card']}; border-color: {t['border']}; border-radius: {t['radius_sm']};
  max-height: 320px;
}}
[data-testid="stSelectbox"] [role="option"]{{
color:{t['text']}; font-size: .95rem; min-height: {t['tap']};
  display: flex; align-items: center;
}}
[data-testid="stSelectbox"] [role="option"]:hover{{ background: {t['primary_soft']}; }}
[data-testid="stSelectbox"] [role="option"][aria-selected="true"]{{
background:{t['primary_soft']}; color: {t['primary']}; font-weight: 600;
}}

/* --------------------------------------------------------------- buttons */
/* Scoped to the button testid and never to .stButton generally, so a primary
   button can be styled without repainting every button in the app. */
[data-testid="stButton"] button{{
min-height:{t['tap']}; border-radius: {t['radius_sm']};
  font-size: .95rem; font-weight: 600; padding: .5rem 1rem;
background:{t['card']}; color: {t['text']};
border: 1px solid{t['border_strong']};
  transition: background-color .12s ease, border-color .12s ease, color .12s ease;
}}
[data-testid="stButton"] button:hover{{
background:{t['bg']}; border-color: {t['primary']}; color: {t['primary']};
}}
[data-testid="stButton"] button:focus-visible{{
outline: 3px solid{t['primary']}; outline-offset: 2px; border-color: {t['primary']};
}}
/* Primary variant only: an explicit, visible brand fill. The previous theme
   resolved this to #FFFFFF, producing a white button on a white page. */
[data-testid="stButton"] button[kind="primary"],
[data-testid="stButton"] button[data-testid="stBaseButton-primary"]{{
background:{t['primary']}; color: #FFFFFF; border: 1px solid {t['primary']};
}}
[data-testid="stButton"] button[kind="primary"]:hover,
[data-testid="stButton"] button[data-testid="stBaseButton-primary"]:hover{{
background:{t['primary_hover']}; color: #FFFFFF; border-color: {t['primary_hover']};
}}
[data-testid="stButton"] button:disabled{{
background:{t['bg']}; color: {t['muted']}; border-color: {t['border']};
  cursor: not-allowed;
}}

/* --------------------------------------------------------------- expander */
[data-testid="stExpander"]{{
background:{t['card']}; border: 1px solid {t['border']};
border-radius:{t['radius']}; overflow: hidden;
}}
[data-testid="stExpander"] summary{{
min-height:{t['tap']}; font-size: .95rem; font-weight: 600; color: {t['text']};
  align-items: center;
}}
[data-testid="stExpander"] summary:hover{{ color: {t['primary']}; }}
[data-testid="stExpander"] summary:focus-visible{{
outline: 3px solid{t['primary']}; outline-offset: -2px;
}}

/* --------------------------------------------------------- native alerts */
/* Streamlit's info/warning/success boxes, recoloured to the token set. */
[data-testid="stAlert"]{{ border-radius: {t['radius_sm']}; border: 1px solid; }}
[data-testid="stAlert"] p{{ font-size: .9rem; line-height: 1.5; }}

/* ------------------------------------------------------- kyl components */
/* Masthead. A teal band, the mark in a white tile on the left, the name and
   tagline beside it.

   The tile is not decoration. The shark's outline is near-black, and laid
   directly on the deep teal the outline disappears and the shape loses its
   edge; a white ground keeps the silhouette readable and looks deliberate.

   static/kyl-logo.png is new.png, which arrives already cropped to its content
   with the background removed at 287x234, so no trimming happens here. */
.kyl-header {{
  display: flex; align-items: center; gap: .9rem;
  background: {t['primary']};
  border-radius: {t['radius']};
  padding: .95rem 1.25rem;
  margin: 0 0 .9rem;
}}
.kyl-header-mark {{
  display: flex; align-items: center; justify-content: center;
  width: 3.25rem; height: 3.25rem; flex: 0 0 auto;
  background: #FFFFFF; border-radius: 10px;
}}
.kyl-header-mark img {{
  display: block; width: 2.5rem; height: auto;
}}
.kyl-header-text {{ display: block; min-width: 0; }}
/* Wordmark. The heaviest use of the display face. */
.kyl-mark{{
  font-family:{t['font_display']};
  font-size: 2.1rem; font-weight: 700; letter-spacing: -.02em;
  color: #FFFFFF; line-height: 1.1; margin: 0; display: block;
}}
/* Tagline on the band, so it is knocked back from the wordmark rather than
   competing with it. */
.kyl-tag{{
  color: rgba(255, 255, 255, .82); font-size: .95rem;
  margin: .2rem 0 0; display: block;
}}
.kyl-lede{{ color: {t['muted']}; font-size: 1.05rem; line-height: 1.6; margin: .6rem 0 0; }}

/* Section shell so every block sits on one card surface with one border. */
.kyl-card{{
background:{t['card']}; border: 1px solid {t['border']};
border-radius:{t['radius']}; padding: 1.25rem 1.35rem; margin: 0 0 1rem;
}}
.kyl-card > *:first-child{{ margin-top: 0; }}
.kyl-card > *:last-child{{ margin-bottom: 0; }}

/* Alerts. Rendered as HTML so dollar amounts are never parsed as LaTeX and
   bold markers never leak through as literal asterisks. */
.kyl-alert{{
  display: flex; gap: .7rem; align-items: flex-start;
border: 1px solid; border-radius:{t['radius_sm']};
  padding: .85rem 1rem; margin: .5rem 0; font-size: .9rem; line-height: 1.55;
}}
.kyl-alert b{{ font-weight: 650; }}
.kyl-alert-danger{{ background: {t['danger_soft']}; border-color: #FECDCA; color: #7A271A; }}
.kyl-alert-danger b{{ color: {t['danger']}; }}
.kyl-alert-warning{{ background: {t['warning_soft']}; border-color: #FEDF89; color: #7A2E0E; }}
.kyl-alert-warning b{{ color: {t['warning']}; }}
.kyl-alert-info{{ background: {t['primary_soft']}; border-color: #D6E0FF; color: #1B2C6B; }}
.kyl-alert-info b{{ color: {t['primary']}; }}
.kyl-alert-success{{ background: {t['success_soft']}; border-color: #A9E5C3; color: #054F31; }}
.kyl-alert-success b{{ color: {t['success']}; }}
@media (max-width: 768px) {{

}}

/* The uncomfortable statistics, given as a definition list so the figure and
   what it measures stay paired. */
.kyl-stats{{
  margin: .8rem 0 0; display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: .1rem 1.2rem; align-items: baseline;
}}
.kyl-stats dt{{
font-size: .875rem; line-height: 1.5; color:{t['text']};
padding: .4rem 0; border-bottom: 1px solid{t['border']};
}}
.kyl-stats dd{{
margin: 0; font-size: 1.05rem; font-weight: 700; color:{t['text']};
  font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap;
padding: .4rem 0; border-bottom: 1px solid{t['border']};
}}
.kyl-stats dt:last-of-type, .kyl-stats dd:last-of-type{{ border-bottom: none; }}
@media (max-width: 480px) {{
.kyl-stats{{ grid-template-columns: minmax(0, 1fr); gap: 0; }}
.kyl-stats dd{{ text-align: left; padding: 0 0 .45rem; border-bottom: 1px solid {t['border']}; }}
}}

/* Method C formulas on the Methodology page. The blocked one is struck through
   rather than omitted, because naming the rate we cannot compute is the clearest
   statement of what this data cannot do. */
.kyl-formula {{
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: .85rem; line-height: 1.6; color: {t['text']};
  background: {t['bg']}; border: 1px solid {t['border']};
  border-radius: {t['radius_sm']}; padding: .6rem .8rem; margin: .4rem 0;
  overflow-x: auto;
}}
.kyl-formula-blocked {{
  color: {t['muted']}; text-decoration: line-through;
  text-decoration-color: {t['border_strong']};
}}

/* --------------------------------------- the query column and the panels */
/* Two panels: a query on the left, read-only tool panels on the right. The
   query column is a control surface, so it is visually distinct from the
   results and does not look like another output. */
.kyl-chat-status {{
  border-left: 3px solid {t['primary']};
  padding: .1rem 0 .1rem .7rem; margin: .2rem 0 .6rem;
}}
.kyl-chat-empty {{
  border: 1px dashed {t['border_strong']}; border-radius: {t['radius']};
  padding: .8rem .9rem; margin-top: .4rem;
}}
.kyl-chat-ex {{ margin: .55rem 0 0; font-size: .9rem; }}
/* Key/value figures in the payoff panel. */
.kyl-figures {{
  display: grid; grid-template-columns: minmax(0, 1fr) auto;
  gap: .3rem .9rem; margin: .2rem 0 .6rem;
  font-variant-numeric: tabular-nums;
}}
.kyl-figures dt {{ color: {t['muted']}; font-size: .9rem; }}
.kyl-figures dd {{ margin: 0; text-align: right; font-weight: 600; }}
/* The analysis box that sits under each panel's figures. */
.kyl-analysis {{
  border: 1px solid {t['border']}; border-left: 3px solid {t['primary']};
  border-radius: {t['radius_sm']}; background: {t['primary_soft']};
  padding: .7rem .85rem; margin: .7rem 0 .2rem;
}}
.kyl-analysis-head {{
  font-size: .75rem; font-weight: 700; letter-spacing: .06em;
  text-transform: uppercase; color: {t['primary']}; margin: 0 0 .3rem;
}}
/* Cleared because the figures changed. Amber, not red: the data is fine, the
   analysis is simply out of date. */
.kyl-analysis-stale {{
  background: {t['warning_soft']}; border-left-color: {t['warning']};
}}
.kyl-analysis-stale .kyl-analysis-head {{ color: {t['warning']}; }}

/* ------------------------------------------------- the offer briefing (Ask) */
.kyl-chat {{
  border: 1px solid {t['border']}; border-radius: {t['radius']};
  background: {t['card']}; padding: 1rem 1.1rem; margin: .5rem 0 1rem;
}}
.kyl-chat-h {{
  font-size: .8rem; font-weight: 700; letter-spacing: .06em;
  text-transform: uppercase; color: {t['primary']};
  margin: .9rem 0 .35rem;
}}
.kyl-chat-h:first-child {{ margin-top: 0; }}
/* What is still missing from the pasted offer. Needs to read as an action, not
   as an error, so it is amber rather than red. */
.kyl-chat-needs {{
  margin-top: .8rem; padding: .5rem .7rem; border-radius: {t['radius_sm']};
  background: {t['warning_soft']}; border: 1px solid {t['warning']};
  color: {t['text']}; font-size: .9rem;
}}

/* ------------------------------------------------ the complaint profile (hero) */
/* Ordered as the product question is asked: what consumers report, then how it
   compares with peers, then how much evidence there is. */
.kyl-hero{{ margin: 0 0 .1rem; }}
.kyl-hero h2{{
  font-size: 1.6rem; font-weight: 700; letter-spacing: -.015em;
color:{t['text']}; margin: 0; overflow-wrap: anywhere;
}}
/* The query column's heading has to start on the same line as the first panel
   beside it. Streamlit puts ~19.92px of top margin on a bare h2 and its own rule
   outranks the reset in this sheet, so the margin is zeroed here specifically
   rather than across every heading, which would disturb the complaint detail
   headings that rely on theirs. */
.kyl-prompt h2{{ margin: 0 !important; }}

/* Heading for the match list under the lender field. */
.kyl-pick-head {{
  font-size: .72rem; font-weight: 700; letter-spacing: .05em;
  text-transform: uppercase; color:{t['muted']}; margin: .5rem 0 .3rem;
}}
.kyl-evidence-line{{
font-size: .95rem; color:{t['text']}; margin: .7rem 0 0;
}}
/* The denominator has to be understandable without opening Methodology. */
.kyl-denominator{{
font-size: .82rem; line-height: 1.55; color:{t['muted']};
  margin: .4rem 0 0; max-width: 68ch;
border-left: 2px solid{t['border']}; padding-left: .7rem;
}}
/* Sparse lenders get said out loud rather than implied by a small number. */
.kyl-sparse{{
background:{t['warning_soft']}; border: 1px solid #FEDF89;
border-radius:{t['radius']}; padding: .9rem 1.1rem; margin: .8rem 0 0;
}}
.kyl-sparse h3{{
margin: 0 0 .25rem; font-size: .95rem; font-weight: 700; color:{t['warning']};
}}
.kyl-sparse p{{ margin: 0; font-size: .875rem; line-height: 1.55; color: #7A2E0E; }}
.kyl-section-h{{
  font-size: .8rem; font-weight: 700; letter-spacing: .05em;
text-transform: uppercase; color:{t['muted']}; margin: 1.4rem 0 .3rem;
}}
/* One row per complaint type. The bar is a share of complaints, not a score:
   no colour scale, no threshold markers, nothing that reads as a grade. */
.kyl-crows{{ list-style: none; margin: 0; padding: 0; }}
.kyl-crow{{ border-bottom: 1px solid {t['border']}; }}
.kyl-crow:last-child{{ border-bottom: none; }}
.kyl-cdetail > summary{{
  list-style: none; cursor: pointer; display: grid;
  grid-template-columns: minmax(0, 15rem) minmax(0, 1fr) 7.5rem;
  gap: .3rem 1rem; align-items: center;
min-height:{t['tap']}; padding: .6rem .25rem;
}}
.kyl-cdetail > summary::-webkit-details-marker{{ display: none; }}
.kyl-cdetail > summary:hover{{ background: {t['bg']}; }}
.kyl-cdetail > summary:focus-visible{{
outline: 3px solid{t['primary']}; outline-offset: -2px;
}}
.kyl-clabel{{
font-size: .9rem; font-weight: 600; color:{t['text']}; line-height: 1.35;
  overflow-wrap: anywhere;
}}
.kyl-cbar{{
height: .7rem; background:{t['bg']}; border: 1px solid {t['border']};
  border-radius: 999px; overflow: hidden; display: block;
}}
/* A non-zero share must not render as nothing. Exact values sit beside it. */
.kyl-cbar-fill{{ display: block; height: 100%; background: {t['accent']}; min-width: 2px; }}
.kyl-cvalue{{
font-size: .85rem; color:{t['muted']}; text-align: right;
  font-variant-numeric: tabular-nums; white-space: nowrap;
}}
.kyl-cbody{{
  padding: .2rem .25rem 1rem; display: flex; flex-direction: column; gap: .1rem;
  max-width: 68ch;
}}
.kyl-dlabel{{
  font-size: .72rem; font-weight: 700; letter-spacing: .05em;
text-transform: uppercase; color:{t['muted']}; margin: .7rem 0 .1rem;
}}
.kyl-issues{{ margin: 0; padding-left: 1.1rem; }}
.kyl-issues li{{
font-size: .875rem; line-height: 1.55; color:{t['text']}; margin-bottom: .1rem;
}}
.kyl-issue-count{{
color:{t['muted']}; font-variant-numeric: tabular-nums; font-weight: 600;
}}
/* Model output is disclosure, never a headline. */
.kyl-advanced{{ margin-top: .8rem; }}
.kyl-advanced > summary{{
cursor: pointer; font-size: .78rem; font-weight: 600; color:{t['primary']};
  min-height: 2rem; display: flex; align-items: center;
}}
.kyl-advanced > summary:focus-visible{{
outline: 3px solid{t['primary']}; outline-offset: 1px;
}}
.kyl-watch{{ margin-top: 1.1rem; }}
.kyl-watch h3{{ margin: 0 0 .35rem; font-size: 1.05rem; }}
@media (max-width: 768px) {{
.kyl-cdetail > summary{{
    grid-template-columns: minmax(0, 1fr) auto;
  }}
.kyl-cbar{{ grid-column: 1 / -1; grid-row: 2; }}
}}

/* Verdict strip: one mark per complaint type.
   A solid mark means the model can separate this lender from peers on that type
   and a flat dash means it cannot. Direction is a glyph, not a hue, so the strip
   never reads as a traffic light, and the sparseness of the data is the most
   prominent thing about it. */
.kyl-strip-head{{
font-size: .875rem; line-height: 1.5; color:{t['text']}; margin: 0 0 .5rem;
}}
.kyl-strip{{ display: flex; gap: .3rem; }}
.kyl-mark-cell{{
  flex: 1 1 0; min-width: 0; height: 2.1rem;
  display: flex; align-items: center; justify-content: center;
border-radius:{t['radius_sm']};
background:{t['bg']}; border: 1px solid {t['border']};
color:{t['border_strong']};
}}
/* Only a real finding gets emphasis. Everything else stays flat, so a strip with
   three dashes in it looks like what it is: three dimensions we cannot call. */
.kyl-mark-cell.is-signal{{
background:{t['primary_soft']}; border-color: #B9C6F5; color: {t['primary']};
}}
.kyl-mark-glyph{{ font-size: 1rem; line-height: 1; font-weight: 700; }}
/* Available to assistive tech, invisible on screen: the glyph alone does not
   say which complaint type or which direction. */
.kyl-mark-visually-hidden{{
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}}

/* The query field's own label is redundant: the heading above it already says
   what the field is, and it read "Your question" against a heading that now says
   "Type in your offer". Streamlit's label_visibility="collapsed" still rendered
   it, so it is hidden here instead.

   Visually hidden rather than display:none, so the control keeps its accessible
   name; a screen reader still announces the field. Scoped to the widget's key
   class, which Streamlit derives from the key and which is therefore stable. */
.st-key-kyl_chat_query label {{
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}}

/* Result readout after a successful estimate. */
.kyl-outcome-lab{{ font-size: .8rem; font-weight: 700; letter-spacing: .04em;
text-transform: uppercase; color:{t['muted']}; margin-bottom: .2rem; }}
.kyl-outcome-val{{ font-size: 2.1rem; font-weight: 700; color: {t['text']};
  letter-spacing: -.02em; line-height: 1.15; }}
.kyl-outcome-note{{ font-size: .875rem; color: {t['muted']}; line-height: 1.6; margin-top: .5rem; }}
.kyl-list{{ margin: .4rem 0 0; padding-left: 1.1rem; }}
.kyl-list li{{ font-size: .875rem; line-height: 1.6; color: {t['muted']}; margin-bottom: .2rem; }}

.kyl-fine{{ font-size: .78rem; color: {t['muted']}; line-height: 1.6; }}
/* Respect reduced-motion: strip every transition and animation. */
@media (prefers-reduced-motion: reduce) {{
*, *::before, *::after{{
    animation-duration: .001ms !important; animation-iteration-count: 1 !important;
    transition-duration: .001ms !important; scroll-behavior: auto !important;
  }}
}}
</style>
"""
