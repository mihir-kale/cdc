# FinePrint

FinePrint is a consumer-facing tool that helps people understand and compare
payday lenders. It draws on CFPB complaint data, lender information,
Reddit/consumer discussions, and quantitative analysis to produce a plain-language
summary of what a loan really costs.

This repository is the shared starting point for the team. The models, scoring
methodology, data pipelines, and UI are all still to come — right now it is just
enough to run both halves of the stack and confirm they talk to each other.

## Tech stack

| Layer     | Tools                                            |
| --------- | ------------------------------------------------ |
| Frontend  | Next.js, TypeScript, Tailwind CSS                |
| Backend   | Python, FastAPI                                   |
| Data / ML | pandas, NumPy, scikit-learn                      |
| Notebooks | Jupyter                                          |
| VCS       | Git                                              |

## Project direction

```text
Data Sources
    ↓
Data Cleaning / Feature Engineering
    ↓
Statistical + ML Analysis
    ↓
Lender Nutrition Label
    ↓
Consumer-Facing UX
```

## Folder structure

```text
.
├── frontend/            Next.js + TypeScript + Tailwind app
│   └── src/
│       ├── app/         App Router pages and layout
│       ├── components/  React components (LenderSearch, SafetyLabel)
│       └── lib/         API client and shared types
├── backend/             FastAPI service
│   ├── app/
│   │   ├── main.py           App definition and routes
│   │   ├── models.py         Pydantic schemas
│   │   ├── label_store.py    Loads the generated artifact (stdlib only)
│   │   ├── safety_labels.py  Builds the artifact from the processed features
│   │   └── generated/
│   │       └── lender_safety_labels.json   Committed, ~380 KB
│   ├── requirements.txt
│   └── requirements-dev.txt
├── data/
│   ├── raw/             Downloaded source datasets (git-ignored)
│   └── processed/       Cleaned and derived datasets (git-ignored)
├── notebooks/           Jupyter notebooks for exploration
├── tests/               unittest suite
├── .env.example
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

There is deliberately **no overall score, grade or rank**. The five dimensions
overlap, so a single number would hide that, and empirical-Bayes shrinkage means
a lender with few complaints is reported near the middle rather than at an
extreme.

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

Requires Python 3.11 or 3.12 (developed against 3.12). Do **not** use Python 3.14 —
`ensurepip` is broken there, so `python3 -m venv` cannot create an environment.

```bash
cd backend
/usr/local/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

The API is then on <http://localhost:8000>. Useful URLs:

| Endpoint           | Purpose                            |
| ------------------ | ---------------------------------- |
| `/`                | Service name and version           |
| `/health`          | Liveness check, returns `{"status": "ok"}` |
| `/dataset`         | Lender count, complaint total, and the methodology text the UI discloses |
| `/lenders`         | All 482 lenders, for search (id, name, complaint count, evidence band) |
| `/lenders/{id}`    | One lender's full safety label, `404` if unknown |
| `/docs`            | Interactive OpenAPI docs           |

Verify it works:

```bash
curl http://localhost:8000/health
```

## Running the frontend

Requires Node.js 20+.

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. The homepage searches the lenders returned by
`GET /lenders` and shows the safety label for the one you select, so run the
backend first or the list will show a connection error.

To point the frontend at a different backend, copy the example env file and edit
it:

```bash
cp .env.example .env.local
```

Run that from inside `frontend/`.

| Variable              | Default                 | Purpose             |
| --------------------- | ----------------------- | ------------------- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend base URL    |

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

## Environment variables

Copy the example file to `.env` and fill in values as they are needed. Never
commit real credentials — `.env` is git-ignored.

```bash
cp .env.example .env
```

| Variable              | Purpose                          |
| --------------------- | -------------------------------- |
| `REDDIT_CLIENT_ID`    | Reddit API app credentials       |
| `REDDIT_CLIENT_SECRET`| Reddit API app secret             |
| `OPENAI_API_KEY`      | OpenAI API access                |

## Planned work

Done:

- CFPB complaint analysis — `notebooks/cfpb_*.ipynb`
- Bayesian complaint modeling — empirical-Bayes posteriors in
  `notebooks/cfpb_shrinkage.ipynb`
- Financial Nutrition Label UI — the five-dimension Payday Loan Safety Label
  described above

Not started:

- Reddit and consumer sentiment analysis
- Lender and product reference data (APR, state licensing)
- K-means lender clustering
- PCA visualization
- Anomaly detection
- Monte Carlo financial simulation
- Combining the safety label with a personal financial impact estimate
