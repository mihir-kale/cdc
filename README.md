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
│       ├── components/  React components (LenderList)
│       └── lib/         API client and shared types
├── backend/             FastAPI service
│   ├── app/
│   │   ├── main.py      App definition and routes
│   │   ├── models.py    Pydantic schemas
│   │   └── data.py      Hardcoded placeholder lenders
│   ├── requirements.txt
│   └── requirements-dev.txt
├── data/
│   ├── raw/             Downloaded source datasets (git-ignored)
│   └── processed/       Cleaned and derived datasets (git-ignored)
├── notebooks/           Jupyter notebooks for exploration
├── .env.example
└── README.md
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
| `/lenders`         | List of lenders                    |
| `/lenders/{id}`    | A single lender, `404` if unknown  |
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

Open <http://localhost:3000>. The homepage fetches `GET /lenders` from the
backend and lists the returned lenders, so run the backend first or the list
will show a connection error.

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

- `notebooks/exploration.ipynb` — shared scratchpad for CFPB and other datasets.
- `notebooks/amishi_cfpb_exploration.ipynb` — Amishi's CFPB exploration.

Both load data via a path relative to the notebook location, for example
`../data/raw/paydayComplaints.csv`. That resolves correctly whether you launch
Jupyter from `backend/` (as above) or from `notebooks/` directly. If you launch
it from the repository root, use `--notebook-dir notebooks` and the paths will
not resolve — start from `backend/` or `notebooks/`.

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

Not started yet. Listed so everyone knows what the project is aiming at.

- CFPB complaint analysis
- Reddit and consumer sentiment analysis
- Lender and product reference data
- K-means lender clustering
- PCA visualization
- Bayesian complaint modeling
- Anomaly detection
- Monte Carlo financial simulation
- Financial Nutrition Label UI
