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

/*
 * Household Financial Context.
 *
 * A different question from the Safety Label: not "is this lender risky" but
 * "where does a household like mine sit in survey terms". Nothing here is
 * derived from a lender, and no value here feeds back into a safety label.
 */

export type InputOption = {
  code: number;
  label: string;
  /** Present only on checkbox groups; names the boolean field to set. */
  field?: string | null;
};

export type InputField = {
  survey_variable: string;
  label: string;
  control: "select" | "checkbox";
  options: InputOption[];
};

export type HouseholdInputOptions = {
  inputs: Record<string, InputField>;
  what_this_is: string;
  what_this_is_not: string[];
};

export type HouseholdProfile = {
  age_band: number;
  education: number;
  household_income: number;
  marital_status: number;
  household_size: number;
  metro_area: number;
  county_poverty_share: number;
  children_0_1: boolean;
  children_2_5: boolean;
  children_6_12: boolean;
  children_13_17: boolean;
};

export type HouseholdContextMethodology = {
  survey: string;
  survey_year: number;
  households_modelled: number;
  weighted_roc_auc: number;
  target: string;
  source_script: string;
  relationship_to_safety_label: string;
};

export type HouseholdContext = {
  context_band: "higher_strain" | "typical_strain" | "lower_strain";
  band_label: string;
  summary: string;
  /** Relative position among surveyed households; the consumer-facing result. */
  survey_percentile: number;
  /**
   * The raw model probability. Kept for traceability and shown only as a
   * secondary technical detail: a 2016 survey association is easy to misread as
   * a personal forecast, which is why the percentile leads instead.
   */
  model_association_rate: number;
  what_this_is: string;
  what_this_is_not: string[];
  methodology: HouseholdContextMethodology;
  caveats: string[];
};

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });

  if (!response.ok) {
    throw new Error(`GET ${path} failed with status ${response.status}`);
  }

  return response.json();
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`POST ${path} failed with status ${response.status}`);
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

export function fetchHouseholdInputOptions(): Promise<HouseholdInputOptions> {
  return getJson<HouseholdInputOptions>("/financial-impact/inputs");
}

export function fetchHouseholdContext(
  profile: HouseholdProfile,
): Promise<HouseholdContext> {
  return postJson<HouseholdContext>("/financial-impact/context", profile);
}
