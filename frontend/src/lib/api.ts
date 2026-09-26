/**
 * Thin client for the FinePrint backend.
 *
 * The API base URL comes from NEXT_PUBLIC_API_URL so the same code works
 * against a local backend now and a deployed one later. See
 * frontend/.env.example.
 *
 * No statistical logic lives here. The backend serves scores that were derived
 * offline by `backend/app/safety_labels.py` and reviewed in
 * `notebooks/cfpb_dimension_scoring.ipynb`; this module only moves the numbers.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Search-result row. No scores, so the index stays small enough to filter. */
export type LenderSummary = {
  id: string;
  name: string;
  n_complaints: number;
  evidence: string;
};

export type DimensionScore = {
  label: string;
  summary: string;
  peer_rate: number;
  score: number;
  complaints: number;
  prevalence: number;
  prevalence_lo90: number;
  prevalence_hi90: number;
  comparison: "more" | "fewer" | "similar";
};

export type Methodology = {
  direction: string;
  summary: string;
  caveats: string[];
  evidence_bands: { min_complaints: number; label: string }[];
};

export type SafetyLabel = {
  id: string;
  name: string;
  n_complaints: number;
  evidence: string;
  method: string;
  methodology: Methodology;
  dimensions: Record<string, DimensionScore>;
};

export type DatasetSummary = {
  lender_count: number;
  total_complaints: number;
  method: string;
  methodology: Methodology;
  dimensions: Record<string, Omit<DimensionScore, "score" | "complaints" | "prevalence" | "prevalence_lo90" | "prevalence_hi90" | "comparison">>;
};

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });

  if (!response.ok) {
    throw new Error(`GET ${path} failed with status ${response.status}`);
  }

  return response.json();
}

export function fetchLenders(): Promise<LenderSummary[]> {
  return getJson<LenderSummary[]>("/lenders");
}

export function fetchLender(lenderId: string): Promise<SafetyLabel> {
  return getJson<SafetyLabel>(`/lenders/${encodeURIComponent(lenderId)}`);
}

export function fetchDataset(): Promise<DatasetSummary> {
  return getJson<DatasetSummary>("/dataset");
}
