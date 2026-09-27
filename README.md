# Know Your Loan

A consumer tool for payday loans. Someone has an offer in front of them, or a
lender's name, or a household profile, and wants to know what the public record
actually says. **Know Your Loan** answers with observed data and stated
arithmetic, and is explicit about what it cannot know.

It is a single Streamlit app, `app.py`. Three tools sit side by side because
they answer different questions from different data:

1. **Lender Complaint Profile** — what consumers reported to the CFPB about one
   lender, as a share of that lender's own payday-loan complaints, with a
   peer comparison only where the evidence supports one. 482 lenders,
   6,024 complaints.
2. **Household Financial Context** — where a household profile sits within the
   2016 CFPB National Financial Well-Being Survey. A survey association, not an
   eligibility estimate and not a forecast.
3. **Loan Payoff Calculator** — standard amortisation on a fixed rate and a
   level monthly payment.

A fourth panel, **Methodology**, says what the first three observe, calculate,
and cannot.

## What it deliberately does not do

These are the product, not omissions:

- **No lender ranking, and no overall score.** The five complaint categories
  overlap, so a single figure per lender would hide that. The CFPB has
  classified no lender either way.
- **No grades.** An earlier version of this repo banded each dimension A–F. It
  was removed: the bands put 72.9% of every dimension in F while the model
  simultaneously called 91% of them indistinguishable from peers, which is not
  a scale anyone should be shown.
- **No customer-level complaint rate.** The dataset has no lender-level count of
  customers, loans or transaction volume, so the denominator of the obvious rate
  is missing. Every share is stated as a share *of that lender's complaints*.
- **No advice about whether to borrow.** The output guard blocks it.
- **No household result presented as a prediction.** The headline is a
  percentile within the survey population, not a probability.

The two analyses are never combined. The household result says nothing about any
lender, and no lender result says anything about the reader.

## Architecture

```text
                    Know Your Loan  (Streamlit)
                            │
        app.py ────────────┼──────────── kyl_theme.py  (all CSS)
             │             │
             │             └── static/  (logo, self-hosted fonts)
             │
             ├── backend/app/label_store.py ──── lender_safety_labels.json
             │      482 lenders, 6,024 complaints, schema v2
             │
             ├── backend/app/financial_impact.py ─┐
             │      survey codebook + inference    ├── shared with FastAPI
             │                                     │
             └── backend/app/chat/                │
                    scope   may this be answered at all      │
                    tools   the only path to the data        │
                    router  query → which panels open        │
                    model   the Gemini client (optional)     │
                    guard   checks the finished reply        │
                    analysis, narrative, offer, orchestrator │
                                                          │
             backend/app/payoff.py ── amortisation ───────┘
```

`backend/app/main.py` is a FastAPI service that serves the same two artifacts.
It is not wired to `app.py`; both read the committed JSON, so the numbers agree
because the data is shared, not because one calls the other.

Both model artifacts are **pre-built and committed**, so nothing retrains at
startup or at request time:

| Artifact                                        | Size  | Contents                            |
| ----------------------------------------------- | ----- | ----------------------------------- |
| `backend/app/generated/lender_safety_labels.json` | 610 KB | 482 lenders, 33 CFPB issue labels   |
| `backend/app/generated/financial_impact_model.json` | 607 KB | 9-feature survey model            |

## Repository layout

```text
.
├── app.py                  The product. The whole interface.
├── kyl_theme.py            Every CSS rule, as one stylesheet()
├── requirements.txt        Runtime deps for app.py (Streamlit, xgboost)
├── render.yaml             FastAPI service blueprint
├── static/                 Logo and self-hosted fonts
├── backend/
│   ├── app/
│   │   ├── main.py                    FastAPI routes
│   │   ├── models.py                  Pydantic schemas
│   │   ├── label_store.py             Loads the lender artifact (stdlib only)
│   │   ├── safety_labels.py           Builds the lender artifact offline
│   │   ├── financial_impact.py        Survey codebook + inference
│   │   ├── train_financial_impact.py  Offline training and export
│   │   ├── payoff.py                  Amortisation and debt-trap maths
│   │   ├── chat/                      The assistant
│   │   └── generated/                 Committed artifacts
│   ├── requirements.txt           FastAPI runtime
│   ├── requirements-test.txt      What CI installs
│   └── requirements-dev.txt       Adds notebooks and plotting
├── browser-checks/         Real-Chrome checks for app.py (not shipped)
├── tests/                  unittest suite
├── notebooks/              How the CFPB analysis was derived
├── data/                   raw/ and processed/, git-ignored
├── wellbeing.csv           CFPB NFWBS public-use file (training input)
├── SNAPModeltrain.py       Teammate's original training script
├── CFPB_RECONNAISSANCE.md  Factual inventory of the CFPB dataset
└── AGENTS.md               Working notes for the next person
```

## Running the app

Requires **Python 3.12**. Do not use 3.14 — `ensurepip` is broken there, so
`python3.12 -m venv` cannot create an environment.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Streamlit serves on <http://localhost:8501>. `server.enableStaticServing` is on
in `.streamlit/config.toml`, which is what makes `static/` reachable at all.

### Verifying a change

```bash
# 206 unit tests
cd backend && python -m unittest discover -s ../tests

# 32 real-browser checks against a running app
cd browser-checks && npm install && node verify-panels.mjs
```

The browser checks need Chrome and expect the app on
<http://localhost:8899> (`--url` overrides). They drive the actual interface:
that a query opens the right panels, that a partial query opens only what it can
support, that editing a widget clears that panel's analysis, and that the
interface never states a verdict, a ranking, a score, or advice. They also
assert no horizontal scroll at 1024, 768 and 375px.

Neither suite is optional. The layout and the output guard are the two things
most likely to break silently.

## The two analyses

### Lender Complaint Profile

The five scored categories, and the CFPB issue labels behind them, are in the
artifact. Method C fits an empirical-Bayes Beta-Binomial posterior per category
against a fitted peer population, which places a typical peer at 50 on a 0–100
scale. Those numbers are **stored and used for the peer comparison only**; the
profile itself leads with the raw counts and shares.

Shrinkage is what stops a lender with two complaints from being reported as
extreme, and a comparison is only stated when the 90% credible interval sits
entirely on one side of the peer reference. Where it straddles, the app says the
data does not distinguish the lender from peers. Across all 2,410
lender-category observations, **91.1% are not distinguishable from typical
peers** and 95.2% rest on fewer than ten complaints. Only 4 of 482 lenders are
distinguishable across all five categories. That sparsity is the reason the
interface is worded the way it is, and the Methodology panel leads with it.

The five category counts plus a residual `other` reconcile to each lender's
total, and that identity is asserted for all 482 lenders in the test suite.

Regenerate after the CFPB data changes:

```bash
cd backend && python -m app.safety_labels
```

### Household Financial Context

A gradient-boosted classifier over the CFPB National Financial Well-Being Survey
estimating the survey item *"Any household member received SNAP benefits"*, used
as a proxy for financial strain. Nine features, weighted holdout ROC-AUC
**0.880497637560694** on an 80/20 stratified split, seed 42.

`app.py` loads `backend/app/financial_impact.py` **by path** and calls
`household_context()`, so the survey codebook, the feature order, the
categorical category sets and the served artifact are the same ones the API
uses. It does not keep its own copy. An earlier version did, and the copies had
drifted badly enough to matter:

- the local age bands read `55-64`, `65-74`, `75+`, `75+` where the survey
  declares `55-61`, `62-69`, `70-74`, `75 or older` — the form offered age
  ranges that do not exist in the training data
- it loaded a separate **eight**-feature prototype artifact, so the app scored a
  different model from the one the API serves
- `total_children` and `child_ratio` were pinned to `0`, and county poverty was
  never collected, so a fifth of the feature vector was constant and every
  household was quietly scored as childless
- `household_size` was a number input accepting 1–20 for a model trained on five
  bands

Household widgets now carry survey **codes** as their values and use
`format_func` for the label, so there is no index-to-code conversion to get
wrong. `backend/app/chat/router.py` restates the codebook as regexes to map a
typed range onto a code; that copy had drifted too — two age bands were
unreachable, `62-69` and `70-74` shared one pattern, and two income bands had no
pattern at all. `tests/test_chat.py::TestRouterCodebookParity` now asserts every
code is reachable and lands in its own band.

Known and not fixed: the survey has no "prefer not to say" option for marital
status, so the form has to assert something. It defaults to `Married`, matching
what shipped before.

Retrain offline:

```bash
cd backend && python -m app.train_financial_impact   # needs wellbeing.csv
```

Inference bypasses scikit-learn entirely, using `xgboost.Booster` with `DMatrix`,
so the running service does not need scikit-learn installed. That is not a
stylistic choice — NumPy 2 removed `np.NaN` and scikit-learn 1.6's tag-system
change broke XGBoost serialization in both directions. `numpy<2` is pinned
unconditionally for the same reason; see the comments in `requirements.txt`.

## The assistant

`backend/app/chat/` is a bounded assistant over the three tools. It is layered so
no single component is trusted:

| Module          | Role                                                        |
| --------------- | ----------------------------------------------------------- |
| `scope.py`      | Decides in Python whether a question may be answered at all   |
| `tools.py`      | The only path to the complaint data, survey model and maths   |
| `router.py`     | Decides which panels a query justifies opening               |
| `model.py`      | The Gemini client, plus deterministic stubs |
| `guard.py`      | Checks the finished reply                                    |
| `analysis.py`   | The "What this means" box beside each panel                  |
| `narrative.py`  | The lender narrative, and its required disclosure            |
| `offer.py`      | Deterministic offer parsing and implied APR                  |
| `briefing.py`   | The three-part offer briefing                                |
| `orchestrator.py` | Wires the above together                                   |

### Configuring the model

**With no key configured the app is complete and fully functional** — every
panel renders its deterministic text, and no network call is made. Adding a key
changes the prose and nothing else.

Paste a key into `.streamlit/secrets.toml` (copy `.streamlit/secrets.toml.example`),
or into **Settings → Secrets** on Streamlit Community Cloud:

```toml
[gemini]
api_key = "PASTE_YOUR_KEY_HERE"
# model = "gemini-3.8-flash"   # optional
```

For a local run without a secrets file, `GEMINI_API_KEY` or `GOOGLE_API_KEY` in
the environment is equivalent. Create a key at
<https://aistudio.google.com/apikey>.

The client is `google-genai`, the current GA SDK. (`google-generativeai` is the
deprecated predecessor and is not used.) The SDK is imported lazily, so the app
starts and runs without it.

`_narrative_model()` and `_analysis_model()` in `app.py` are the two hooks, and
both return the same cached client. A reply is used only if it survives the
guard; an API error, an empty reply, or a rejected reply all fall back to the
deterministic text, so **a broken or hostile model degrades the prose and
nothing else**.

The guard is the part that matters. It rejects rankings, lender verdicts, risk
and credit scores, unsolicited advice, and any figure that was not in the tool
output. Importing the package registers the system-authored refusal strings with
the guard, so a refusal is not mistaken for a violation of its own rules.

A query never fills in fields the user did not give. "I'm 35-44, income 50-75k"
opens the household panel showing what was understood and naming what was not,
because a percentile computed from guessed inputs is a number the user did not
ask for and cannot check.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request: Python 3.12,
`requirements-test.txt`, the full unittest suite, then an import check that both
artifacts load. It deliberately does not run the CFPB pipeline or retrain — the
committed artifacts are what ships, and the suite verifies them directly.

The browser checks are **not** in CI: they need Chrome and a running Streamlit
server. Run them locally before shipping any interface change.

## Notebooks

The validated CFPB analysis, documenting how the production numbers were derived.
The application does not execute them.

- `cfpb_company_identity.ipynb` — resolves raw CFPB filer names to 482 canonical lenders
- `cfpb_lender_subproduct_features.ipynb` — per-lender complaint features and rates
- `cfpb_issue_taxonomy.ipynb` — assigns the 33 CFPB issue labels to the five categories
- `cfpb_shrinkage.ipynb` — fits the Beta-Binomial posteriors
- `cfpb_dimension_scoring.ipynb` — compares candidate methods, selects Method C
- `cfpb_dimension_dependence.ipynb` — audits the five dimensions' overlap, and why they are not averaged
- `cfpb_narrative_coverage.ipynb` — how much complaint narrative exists, and why it is not shipped
- `amishi_cfpb_exploration.ipynb`, `exploration.ipynb` — exploratory and provenance

They load data relative to the notebook directory, so launch Jupyter from
`backend/` (`jupyter lab --notebook-dir ../notebooks`) or from `notebooks/`
directly. From the repository root the paths will not resolve.

## Datasets

`data/raw/` and `data/processed/` are git-ignored and kept in the repo only via
`.gitkeep`. `data/raw/README.md` records provenance for what is fetched.

The CFPB complaint extract is not committed. It is present in commit `bc64848`:

```bash
git show bc64848:paydayComplaints.csv > data/raw/paydayComplaints.csv
```

It has 38,375 rows dated 2023-08-25 to 2026-09-25. `wellbeing.csv` (6,394
households) *is* committed; 6,232 of them are modelled.

## Environment variables

The backend needs **no secrets**. Its only setting is CORS.

| Variable                    | Where   | Purpose                                                       |
| --------------------------- | ------- | ------------------------------------------------------------- |
| `FINEPRINT_ALLOWED_ORIGINS` | backend | Comma-separated browser origins. Defaults to `localhost:3000` |

`app.py` takes no configuration at all to run. The only credential it will ever
accept is a Gemini API key, and that is optional — see
[Configuring the model](#configuring-the-model). Never commit a real key:
`.streamlit/secrets.toml` is git-ignored and only `secrets.toml.example` is
tracked.

## Deployment

`app.py` targets Streamlit Community Cloud, which installs the root
`requirements.txt` at deploy time. **Choose Python 3.12** — Community Cloud
cannot change it afterwards, so correcting it means deleting and redeploying.
The failure mode on 3.13+ is slow and misleading: numpy 1.x has no wheel, so pip
builds from source for about three minutes and the deploy looks hung rather than
broken.

`render.yaml` deploys the FastAPI service, pinned to `PYTHON_VERSION` 3.12.4.
xgboost's manylinux wheel bundles its own OpenMP runtime, so no `libgomp1` apt
step is needed. The free plan sleeps, so the first request after a quiet period
can take ~30s.

## Known rough edges

- `AGE_BANDS` in older local copies ended `"75+", "75+"`; the codebook in
  `financial_impact.py` is correct. Do not reintroduce a local copy.
- `snap_xgboost.json` at the repo root is a teammate's prototype artifact that
  **nothing reads** — `app.py` used to, and no longer does. Its numbers do not
  reproduce from `SNAPModeltrain.py`. Left in place rather than deleted; safe to
  remove.
- The marital-status default asserts a status, because the survey offers no
  neutral option. See above.
- The household panel is 6,232 households from 2016. It does not describe 2026
  finances, and benefit rules and costs have changed.
- `backend/.venv/` and `node_modules/` exist locally and are git-ignored.
