# AGENTS.md

Working notes for whoever picks this up next. Written against the repo as of the
commit that introduced it. Read `README.md` first for what the product is; this
file is about the things that will bite you.

## Before you change anything

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py                      # product on :8501

cd backend && python -m unittest discover -s ../tests    # 185 tests
cd browser-checks && npm install && node verify-panels.mjs   # 32 checks, needs :8899
```

Both suites are required before you call a change done. The two things most
likely to break silently are the layout and the output guard, and neither is
covered by reading the code.

**Python 3.12 only.** On 3.14 `ensurepip` is broken so the venv cannot be
created at all. See the long comment at the top of `requirements.txt` for why
3.13+ is worse than a version bump.

## Invariants that are load-bearing

**`app.py` is named `app.py`, and so is the package.** Streamlit registers the
entrypoint in `sys.modules` under its own stem, so `import app.label_store`
resolves `app` to the script and dies with *"No module named 'app.label_store';
'app' is not a package"* — and it dies only on the deployed runtime, because
locally the backend package happens to win the name. That is why `app.py` loads
`label_store.py` and `financial_impact.py` by path with
`importlib.util.spec_from_file_location`. Do not "clean that up" into a normal
import.

**`financial_impact.py` is the only source of truth for the survey codebook.**
The panel, the API and the router's seeds all come from it. If you need an age
band, an income band or a feature order, read it from there. Two separate local
copies of the codebook already existed and both had drifted; do not add a third.

**The household model has nine features and the form must supply all of them.**
Five categorical, four numeric. `total_children`, `child_ratio` and
`PCTLT200FPL` were once hardcoded or absent, so a fifth of the feature vector
was constant. Household widgets carry **codes**, not list positions, and use
`format_func` for the label. `household_size` has exactly five bands — a number
input accepting 1–20 sends a code the model never saw.

**`router.py` restates the codebook as regexes.** It is a duplicate and it has
drifted before. Every code must be reachable by an ordinary phrasing and land in
its own band; `tests/test_chat.py::TestRouterCodebookParity` asserts this. When
you touch those patterns, run that class specifically — the rest of the suite
will not notice a mis-banded code.

**Method C is frozen.** All 2,410 lender-dimension outputs are fingerprinted
before and after any artifact change. Complaint enrichment was added without
moving them. If your change moves a score, that is the bug, not the test.

**The artifact is committed and served as-is.** Nothing retrains at startup or
per request. `tests/test_safety_labels.py` asserts the committed JSON still
matches what `python -m app.safety_labels` produces.

## Things the tests will not catch

**Streamlit renders module and function docstrings as visible Markdown.** A
docstring placed after other statements appeared mid-page as a wall of text
referencing the CFPB. There is a regression test that ASTs `app.py` for
docstrings in non-initial positions, because this is easy to reintroduce by
editing near the top of the file.

**Streamlit strips CSS `@import`.** Fonts are self-hosted in `static/fonts/` and
declared through `[[theme.fontFaces]]` in `.streamlit/config.toml`. `st.html`
is the only way to inject the stylesheet, because it does not parse Markdown —
which is also why dollar amounts render as `$10.00` instead of opening a maths
span.

**Do not style Streamlit by generated class name.** Scope on `data-testid`,
`role` or `aria-*`. The emotion hashes move between releases. The tab styling is
the cautionary example: an earlier sheet targeted `[role=tablist] button`, which
matches nothing in 1.64 — there is no button inside the tablist — so every rule
was dead and the tabs fell back to white-on-white.

**The full-bleed masthead fights Streamlit's own chrome.** Three things had to be
accounted for, none of them obvious:

- the space above the header is Streamlit's `6rem` padding on
  `[data-testid="stMainBlockContainer"]`, **not** the `.block-container` rule in
  `kyl_theme.py`, which does not match that element in 1.64. It also drops to
  `2.5rem` below Streamlit's breakpoint, so the breakout margin has a media
  query.
- Streamlit's toolbar is `position: absolute; z-index: 999990` with an opaque
  near-white background. Left alone it paints over the top of the band and
  leaves exactly the white strip the breakout was meant to remove.
- its chrome is ~2.4:1 on the teal and has to be knocked up to white (5.36:1).
  Set `color`, not `fill` — the menu button is one SVG whose paths include its own
  container, so painting every path white fills the button in as a solid square.

**Gap below the band is a margin, not padding.** `padding-bottom` only makes the
masthead taller and leaves the body text just as close to the teal.

**Contrast is checked, not assumed.** White on `#26A8D6` is 2.74:1 and fails;
`#0E7490` at 5.36:1 is what the brand teal is for.

**Verify claims about assets.** The shark was once given a white plate on the
stated grounds that its outline was near-black and would vanish on the teal. It
is pale blue and white (3.6:1 and 5.4:1) and its background is genuinely
transparent. Measure the pixels before writing a comment that justifies a
decision.

## The output guard is the safety property

`backend/app/chat/guard.py` rejects rankings, lender verdicts, risk and credit
scores, unsolicited advice, and figures absent from the tool output. The
browser checks assert the interface states none of these, including under a
prompt-injection attempt.

Two things to preserve:

- **System refusal strings are registered with the guard** on package import
  (`chat/__init__.py`), so a refusal is not flagged as a violation of its own
  rules.
- **Every panel must state its own limit**, and the guard requires it. Adding a
  panel means adding a limit string, not just figures.

If you add a tool, it goes in `tools.py` as the only path to the data, and the
guard needs to know about any new kind of claim it could make.

## There is no LLM endpoint

`_narrative_model()` and `_analysis_model()` return `None`; the deterministic
text renders. The seam is built and tested — a real `ChatModel` changes only the
prose, because the guard runs on the finished reply either way. Keep it that way:
a model that can only phrase tool output cannot invent a figure.

## Where things are not obvious

- `backend/app/label_store.py` is stdlib-only and imports nothing from its own
  package, so it loads standalone by path.
- `backend/app/payoff.py` is shared between the panel and `chat/tools.py`.
  Amortisation lives there so the two cannot disagree.
- `notebooks/` paths resolve only when Jupyter is launched from `backend/` or
  `notebooks/`, never from the repo root.
- The hosted app is private (303 on an unauthenticated request), so verify
  locally with `streamlit run` and the browser checks.
- `data/raw/paydayComplaints.csv` is not committed; retrieve it from `bc64848`.
  `wellbeing.csv` is.

## Housekeeping

- The Next.js frontend, its CI job and `render.yaml`'s Vercel counterpart were
  removed. The browser checks were **kept**, relocated to `browser-checks/`,
  because they drive `app.py` and not the frontend. Do not delete
  `browser-checks/` with a frontend.
- `frontend/AGENTS.md` and `frontend/CLAUDE.md` were Next.js-generated and went
  with it. This file replaces them.
- `snap_xgboost.json` at the repo root is unread by anything and does not
  reproduce from `SNAPModeltrain.py`. Safe to delete; left in place.
- When deleting code, check for zero references with an AST pass rather than
  grep. `app.py` carried 121 lines across four unreferenced functions that grep
  for a name would have found only if you already suspected them.
