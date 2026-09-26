# FinePrint

FinePrint is a consumer-facing tool that helps people understand payday loans. It
answers two separate questions:

1. **Is this lender risky?** — a five-dimension safety label built from CFPB
   consumer complaints, for all 482 canonical payday lenders.
2. **What does a household like mine look like?** — a household financial
   context assessment, derived from the CFPB National Financial Well-Being
   Survey.

These are deliberately kept apart. The first is about a lender, the second is
about a household. They are never combined, there is no overall FinePrint score,
and neither one is presented as predicting the other.

## Architecture

```text
                    FinePrint
                       │
                 Next.js frontend  (Vercel)
                       │
                     FastAPI  (Render)
                    ╱         ╲
        CFPB Safety Label    Household Financial
              482 lenders       Context
```

| Layer     | Tools                                                        |
| --------- | ------------------------------------------------------------ |
| Frontend  | Next.js 16, TypeScript, Tailwind CSS 4                       |
| Backend   | Python 3.12, FastAPI, Uvicorn                                |
| Models    | XGBoost (household context), pandas/NumPy                     |
| Analysis  | pandas, NumPy, SciPy, scikit-learn, Jupyter                   |
| VCS / CI  | Git, GitHub Actions                                          |

Both model artifacts are **pre-built and committed**, so the service starts
without running any data pipeline or training:

- `backend/app/generated/lender_safety_labels.json` — 482 lender labels (~380 KB)
- `backend/app/generated/financial_impact_model.json` — the household model (~610 KB)

## Folder structure

```text
.
├── frontend/            Next.js + TypeScript + Tailwind app
│   └── src/
│       ├── app/         App Router pages and layout
│       ├── components/  ProductTabs, LenderSearch, SafetyLabel, FinancialContext
│       └── lib/         API client, shared types, A–F grade bands
├── backend/             FastAPI service
│   ├── app/
│   │   ├── main.py                    App definition and routes
│   │   ├── models.py                  Pydantic schemas
│   │   ├── label_store.py             Loads the lender artifact (stdlib only)
│   │   ├── safety_labels.py           Builds the lender artifact offline
│   │   ├── financial_impact.py        Household context: codebook + inference
│   │   ├── train_financial_impact.py  Offline training and export
│   │   └── generated/                 Committed artifacts
│   ├── requirements.txt           Runtime dependencies
│   ├── requirements-test.txt      What CI installs
│   └── requirements-dev.txt       Adds notebooks and plotting
├── data/
│   ├── raw/             Downloaded source datasets (git-ignored)
│   └── processed/       Cleaned and derived datasets (git-ignored)
├── notebooks/           Jupyter notebooks for exploration
├── tests/               unittest suite
├── wellbeing.csv        CFPB NFWBS public-use file (training input)
├── render.yaml          Render blueprint for the backend
├── SNAPModeltrain.py    Teammate's model script (training only, 8-feature)
├── app.py               Streamlit prototype stub (not the product)
├── snap_xgboost.json    Artifact for app.py; not the served model
└── README.md
```

## The Payday Loan Safety Label

FinePrint shows a five-dimension safety label for each canonical payday lender,
derived from CFPB complaints:

| Dimension                      | Consumer-facing name                  |
| ------------------------------ | ------------------------------------- |
| `withdrawal_and_payment_control` | Withdrawal & Payment Control        |
| `fees_and_costs`               | Fees & Costs                           |
| `unauthorized_or_unrequested_loan` | Unauthorized / Unrequested Loans  |
| `credit_reporting`             | Credit Reporting                       |
| `servicing_and_payment_handling` | Servicing & Payment Handling         |

Each score is 0–100 and is the validated **Method C** value:

```text
Score_ic = 100 * BetaCDF(theta_peer_c | x_ic + alpha_c, n_i - x_ic + beta_c)
```

`theta_peer_c` is the median of the fitted Beta population for that dimension.
Higher scores mean a more favorable complaint profile relative to modeled
payday peers. The method was selected and validated in
`notebooks/cfpb_dimension_scoring.ipynb`; the dependence structure is documented
in `notebooks/cfpb_dimension_dependence.ipynb`.

The score stays 0–100 everywhere it is stored, served and tested. The UI is the
only place it is banded: each dimension is shown as a per-dimension **A–F** grade
instead of the number, using the peer-anchored cuts in `frontend/src/lib/grades.ts`.
Method C puts a typical peer at exactly 50, so 50 is the C/D boundary; the other
cuts sit in gaps in the observed distribution rather than at even intervals.
Across all 2,410 dimension-scores that yields A 18.3%, B 17.6%, C 34.7%, D 3.2%,
E 5.8%, F 20.4%. Evenly spaced cuts would have been actively misleading — they
put 72.9% of every dimension in F while the model calls 91% of them
indistinguishable from peers. The bands are relative: an F means "materially less
favorable than modeled peers", not "unsafe". The CFPB has classified no lender
either way, which is why the grades render in a single hue rather than the
red/green a letter scale conventionally implies.

There is deliberately **no overall score, grade or rank**, and the per-dimension
grade does not change that. The five dimensions overlap, so a single letter for
the lender would hide that, and empirical-Bayes shrinkage means a lender with few
complaints is reported near the middle rather than at an extreme.

### Regenerating the label data

The scores are computed offline and committed as JSON, so the running service
needs neither pandas nor scipy and the application never recomputes statistics
in the UI. To rebuild after the CFPB data changes:

```bash
cd backend
python -m app.safety_labels
```

This reads `data/processed/payday_shrunk_features.csv` (git-ignored) and writes
`app/generated/lender_safety_labels.json`. Then run the tests, which assert the
committed artifact matches what the script produces:

```bash
cd ..
python -m unittest discover -s tests -v
```

## Running the backend

Requires **Python 3.12**. Do **not** use Python 3.14 — `ensurepip` is broken
there, so `python3 -m venv` cannot create an environment.

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # or requirements.txt for runtime only
uvicorn app.main:app --reload
```

The API is then on <http://localhost:8000>. Endpoints:

| Endpoint                        | Purpose                                                       |
| ------------------------------- | ------------------------------------------------------------- |
| `/`                             | Service name and version                                      |
| `/health`                       | Liveness, plus whether both committed artifacts loaded        |
| `/dataset`                      | Lender count, complaint total, methodology text the UI shows  |
| `/lenders`                      | All 482 lenders, for search                                   |
| `/lenders/{id}`                 | One lender's full safety label, `404` if unknown              |
| `/financial-impact/inputs`      | Survey codebook for the household inputs                      |
| `/financial-impact/context`     | `POST` a household profile, get its context                   |
| `/docs`                         | Interactive OpenAPI docs                                      |

Verify it works:

```bash
curl http://localhost:8000/health
# {"status":"ok","artifacts":{"lender_safety_labels":true,"financial_impact_model":true}}
```

`/health` returns `503` if either artifact is missing, so a half-working deploy
fails visibly instead of serving partial results. It loads the artifacts but
never runs inference or retrains anything.

## Running the frontend

Requires Node.js 20+ (developed against 22).

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. The homepage is a two-tab product switcher:
**Lender safety label** (search and safety label) and **Household financial
context**. Each product gets its own tab because it answers a different question
from a different dataset and unit of analysis — one describes a lender, the other
describes a household, and nothing combines them. Sharing a scrolling page made
the two read as one verdict about one borrower. The tabs are a real ARIA tablist
(arrow keys, Home/End) and both panels stay mounted, so a half-typed search or a
filled-in household profile survives a tab switch. Start the backend first or the
search list will show a connection error.

| Variable              | Default                 | Purpose          |
| --------------------- | ----------------------- | ---------------- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend base URL |

Copy `.env.example` to `.env.local` to change it. The variable is inlined into
the client bundle at build time, so it is public by design — never put a secret
in it. The backend needs no secret or API key at all.

## Data science workspace

The backend virtualenv already includes pandas, NumPy, scikit-learn, matplotlib,
and Jupyter, so you can work in notebooks without a second environment.

```bash
cd backend
source .venv/bin/activate
jupyter lab --notebook-dir ../notebooks
```

## Notebooks

The validated CFPB analysis. These document how the production scores were
derived and checked; the application does not execute them.

- `notebooks/cfpb_company_identity.ipynb` — resolves raw CFPB filer names to 482
  canonical payday lenders.
- `notebooks/cfpb_lender_subproduct_features.ipynb` — per-lender complaint
  features and rates.
- `notebooks/cfpb_issue_taxonomy.ipynb` — assigns the 33 CFPB issue labels to the
  five score dimensions, and records the categories deliberately excluded.
- `notebooks/cfpb_shrinkage.ipynb` — fits the empirical-Bayes Beta-Binomial
  posteriors that supply the priors and the credible intervals.
- `notebooks/cfpb_dimension_scoring.ipynb` — compares the candidate scoring
  methods and selects Method C. This is the source of truth for the score.
- `notebooks/cfpb_dimension_dependence.ipynb` — audits how much the five
  dimensions overlap, and why they are not averaged.
- `notebooks/cfpb_narrative_coverage.ipynb` — how much complaint narrative text
  the dataset carries, and why it is not shipped to the browser.

Exploratory and provenance:

- `CFPB_RECONNAISSANCE.md` — factual inventory of the CFPB dataset and the repo
  state it was examined against.
- `notebooks/exploration.ipynb` — shared scratchpad for CFPB and other datasets.
- `notebooks/amishi_cfpb_exploration.ipynb` — Amishi's CFPB exploration.

The `cfpb_*` notebooks load data via a path relative to the notebook location,
for example `../data/processed/payday_shrunk_features.csv`. That resolves
correctly whether you launch Jupyter from `backend/` (as above) or from
`notebooks/` directly. If you launch it from the repository root, use
`--notebook-dir notebooks` and the paths will not resolve — start from `backend/`
or `notebooks/`.

## Where datasets go

- `data/raw/` — source files exactly as downloaded (CFPB complaint exports,
  lender listings, scraped Reddit threads). Contents are git-ignored, so add a
  fetch script rather than committing large files.
- `data/processed/` — cleaned, deduplicated, and feature-engineered outputs
  written by your scripts or notebooks. Also git-ignored.

`data/raw/paydayComplaints.csv` is the CFPB complaint extract currently in use
(38,375 rows, dated 2023-08-25 to 2026-09-25). It is not in git — see
"Getting the dataset" below.

Both directories are kept in the repo via `.gitkeep` so they exist on a fresh
clone.

### Getting the dataset

`data/raw/paydayComplaints.csv` is untracked, so a fresh clone will not have it.
It is present in commit `bc64848`; retrieve it with:

```bash
git show bc64848:paydayComplaints.csv > data/raw/paydayComplaints.csv
```

## Household Financial Context

The second half of FinePrint. It answers a different question from the safety
label — not "is this lender risky" but "where does a household like mine sit in
survey terms".

### What the model is

Amishi's `SNAPModeltrain.py`, from which this model is derived. It is a
gradient-boosted classifier over nine household variables from the CFPB National
Financial Well-Being Survey (`wellbeing.csv`, 6,394 households) that estimates
the survey item *"Any household member received SNAP benefits."* Weighted holdout
ROC-AUC **0.8805**.

Features: age band, education, household income, marital status, household size,
metro/non-metro, county poverty share, and presence of children in four age
bands. Input labels are transcribed from the official NFWBS public-use file
codebook and live in `backend/app/financial_impact.py`, which is the single
source of truth for both the API and the UI.

`SNAPModeltrain.py` is no longer identical to what is served; the nine-feature
description above applies to the served model only. See
[Two SNAP models](#two-snap-models).

### Two SNAP models

There are two SNAP classifiers in the repo. They are not interchangeable, and
their scores must not be quoted for one another.

|                     | Served                                  | Streamlit prototype        |
| ------------------- | --------------------------------------- | -------------------------- |
| Code                | `backend/app/train_financial_impact.py` | `SNAPModeltrain.py`        |
| Features            | 9, including `PCTLT200FPL`              | 8, `PCTLT200FPL` dropped   |
| Weighted holdout AUC| 0.8804976376                            | 0.8794848776               |
| Artifact            | `backend/app/generated/`                | `snap_xgboost.json`        |
| Covered by CI       | yes                                     | no                         |

The prototype dropped county poverty share in `bb582f8`. On the script's own
80/20 stratified split that costs 0.001 weighted ROC-AUC, so the smaller feature
set is defensible on accuracy. It is still a different model from the one the API
serves, and the UI does not consume it.

The checked-in `snap_xgboost.json` additionally does not reproduce from the
checked-in script: on that same split the committed artifact scores **0.8755**
where `SNAPModeltrain.py` as committed scores **0.8795**. That gap is orders of
magnitude larger than the architecture noise described under
[Training and inference](#training-and-inference) (~9e-08), so the artifact came
from some earlier configuration. Regenerate it with `python SNAPModeltrain.py`
before trusting its numbers.

### What it is not

SNAP receipt is used as a **proxy for household financial strain**. The model is
not a loan simulator, and the UI never claims it is:

- it does **not** predict what taking out a loan would do to your finances
- it does **not** estimate whether you would qualify for SNAP
- it does **not** predict that you personally would receive SNAP
- it says **nothing** about any lender, and changes **no** safety label score

There are deliberately no loan amount, APR, term or payment inputs, because no
model here can support them. A genuine "what would this loan do to my budget"
tool needs a different model; see Planned work.

Because a 2016 survey association is easy to over-read as a personal forecast,
the headline result is a **percentile within the survey population**, not a
probability. The raw model output is preserved in the API as
`model_association_rate` and shown in the UI only as a clearly-labelled
technical detail.

### Training and inference

Training is offline and reproducible; serving only infers.

```bash
cd backend
python -m app.train_financial_impact   # needs wellbeing.csv, ~5s
```

Retraining reproduces the committed model, and a test asserts it. The original
script retrained on every run and then discarded the model, since its
`save_model` call was commented out. `bb582f8` re-enabled that export in
`SNAPModeltrain.py`, which is why the repo now holds a second artifact; it
writes the root `snap_xgboost.json` via `model.get_booster().save_model()`, the
same export path described below, and never touches
`backend/app/generated/`.

The interesting part is *how* it asserts that. A byte-identical retrain is only
meaningful within one CPU architecture. XGBoost's histogram builder accumulates
gradients in parallel, and floating-point addition is not associative, so ARM and
x86-64 round differently. With byte-identical package versions, training on
macOS/arm64 and Linux/x86-64 produces two artifacts that differ in their
serialized bytes but agree to **8.9e-08** in predicted probability and produce
an **identical** weighted ROC-AUC (0.8804976376). Thread count makes no
difference on either platform, so this is architectural, not a race.

So the test asserts both halves of the invariant: byte-identical on the platform
that produced the artifact, and behaviourally identical everywhere (ROC-AUC
within 1e-9, every holdout prediction within 1e-6). Dropping a single tree from
300 to 299 moves AUC by 2.7e-05 and predictions by 5.9e-03, so the thresholds
sit with roughly four orders of magnitude of margin on both sides. The producing
platform is recorded in `financial_impact_context.json`.

### Why inference does not use scikit-learn

Two environment bugs shaped this, both documented in
`backend/app/financial_impact.py`:

1. **NumPy 2 removed `np.NaN`.** xgboost 2.0.3's categorical encoder still calls
   it, so the original script dies on any modern NumPy. Fixed by pinning
   `numpy<2`.
2. **scikit-learn 1.6's tag-system change broke XGBoost serialization in both
   directions.** On 1.6.x `save_model` works but `load_model` raises
   `'super' object has no attribute '__sklearn_tags__'`; on 1.9.x `save_model`
   itself raises `_estimator_type undefined`.

The fix is to bypass the sklearn wrapper: training exports via
`model.get_booster().save_model()`, and inference uses `xgboost.Booster` with
`DMatrix`. That path is bit-identical to `predict_proba` (max difference `0.0`,
verified across two different environment stacks) and means **the deployed
service does not need scikit-learn installed**.

A third bug surfaced while wiring this up and is worth knowing about: casting a
one-row inference frame with a bare `astype("category")` renumbers categories
from zero, so xgboost evaluates the wrong branch of every categorical split. A
real survey household scored `0.260` instead of `0.0060`. Fixed by declaring the
full codebook category set, and locked by a batch-parity test over the survey.

## Streamlit: status

`app.py` is a **Streamlit prototype, not the product.** It holds a loan payoff
timeline calculator (amortisation schedule and payoff date) under the "PayWatch"
title, and since `bb582f8` a SNAP predictor that loads `snap_xgboost.json` and
scores a household profile. It is useful for exploring those interactively, but
it is not deployed, not wired into the FastAPI service, and the Next.js app does
not use it. The survey model it scores with is the eight-feature prototype
described under [Two SNAP models](#two-snap-models), **not** the nine-feature
model the API serves.

Note the deliberate asymmetry: the payoff calculator in `app.py` is a real
arithmetic tool, whereas the Household Financial Context model is a *survey
association* and deliberately carries no loan terms. Do not read the existence
of one as implying the other. For the same reason, the prototype's "Predicted
Value" metric is a raw association rate and inherits none of the framing
discussed above; treat it as a debugging surface, not a user-facing result.

`app.py` is outside CI, which covers only `backend/` and `frontend/`. Nothing
there exercises the Streamlit inference path, so the categorical-casting
contract described under
[Why inference does not use scikit-learn](#why-inference-does-not-use-scikit-learn)
has to be kept in sync by hand.

**Nothing about the Streamlit code dictates the production architecture.**
`app.py` and `.streamlit/config.toml` are retained as a development and modelling
convenience for whoever works on these models next. They are not deployed, not
part of the product, and not required to run or serve FinePrint.

If you want to iterate on the model in Streamlit, install it separately — it is
deliberately absent from `requirements.txt`:

```bash
pip install streamlit
streamlit run app.py
```

Cleaning this up is left to a separate, deliberate change. Nothing in the repo
depends on these files.

## Environment variables

The backend needs **no secrets and no API keys**. The only setting is CORS.

| Variable                    | Where            | Purpose                                                       |
| --------------------------- | ---------------- | ------------------------------------------------------------- |
| `FINEPRINT_ALLOWED_ORIGINS` | backend          | Comma-separated browser origins. Defaults to `localhost:3000` |
| `NEXT_PUBLIC_API_URL`       | frontend         | Backend base URL. Defaults to `http://localhost:8000`         |

Never commit real credentials. `NEXT_PUBLIC_*` values are inlined into the client
bundle at build time and are public by design.

## Deployment

Intended target: **Vercel** for the frontend, **Render** for the backend, over
HTTPS. Both are prepared but **not yet deployed** — see below.

```
Browser ──HTTPS──> Vercel (Next.js) ──HTTPS──> Render (FastAPI)
                                                  ├── CFPB Safety Labels
                                                  └── Household Financial Context
```

### Backend on Render

`render.yaml` is a Render blueprint at the repo root.

1. In Render: **New → Blueprint**, point at this repository.
2. Render will prompt for `FINEPRINT_ALLOWED_ORIGINS`. Set it to the deployed
   frontend origin once you have one, e.g. `https://your-app.vercel.app`. It is
   left unset in the repo rather than guessed.
3. Deploy. Render reads `PYTHON_VERSION` (3.12.4), installs
   `backend/requirements.txt`, and starts
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT` with `backend/` as the
   working directory.

Nothing in the service depends on a developer's machine: both artifacts are
resolved relative to `app/generated/` via `__file__`, and `wellbeing.csv` is
needed only for training.

**One deploy risk, and it is smaller than it looks.** xgboost's manylinux wheel
bundles its own OpenMP runtime (`xgboost.libs/libgomp-d22c30c5.so.1.0.0`), so it
does not need a system `libgomp1`. Verified by installing xgboost 2.0.3 into a
bare `python:3.12-slim` image with no `libgomp1` package present: it imports and
`ldd` resolves the bundled copy. Since Render builds on Ubuntu x86-64 and gets
the same wheel, `render.yaml` needs no extra apt step. If the service somehow
fails to import xgboost, this is the fix:

```
apt-get update && apt-get install -y libgomp1 && pip install --no-cache-dir -r requirements.txt
```

Also note the free plan sleeps after inactivity, so the first request after a
quiet period can take ~30s.

### Frontend on Vercel

1. In Vercel: **Add New → Project**, import this repository.
2. Set **Root Directory** to `frontend`. Vercel detects Next.js; no
   `vercel.json` is needed.
3. Add one environment variable: `NEXT_PUBLIC_API_URL`, set to the Render
   service URL. No secrets.
4. Deploy.

Because `NEXT_PUBLIC_*` is inlined at build time, redeploy after changing it.

### Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

- **Backend** — Python 3.12, installs `requirements-test.txt`, runs the full
  unittest suite, then asserts both artifacts load.
- **Frontend** — Node 22, `npm ci`, lint, `tsc --noEmit`, production build.

It deliberately does **not** run the CFPB narrative pipeline or retrain models;
the committed artifacts are what production serves, and the suite verifies them
directly. Runs in about a minute.

## Planned work

Done:

- CFPB complaint analysis — `notebooks/cfpb_*.ipynb`
- Bayesian complaint modeling — empirical-Bayes posteriors in
  `notebooks/cfpb_shrinkage.ipynb`
- Payday Loan Safety Label UI — the five-dimension label described above
- Household Financial Context — the survey-based model described above, served
  behind FastAPI and surfaced in the Next.js app
- Vercel/Render deployment config and CI

Not started:

- **A real loan-impact simulation.** The current household model cannot answer
  "what would this loan do to my finances", and no amount, rate or term inputs
  were invented to pretend otherwise. This needs its own model.
- Reddit and consumer sentiment analysis
- Lender and product reference data (APR, state licensing)
- Combining the safety label with a personal impact estimate — deliberately not
  done, see above
- K-means lender clustering, PCA visualization, anomaly detection, Monte Carlo
