/**
 * Thin client for the FinePrint backend.
 *
 * The API base URL comes from NEXT_PUBLIC_API_URL so the same code works
 * against a local backend now and a deployed one later. See
 * frontend/.env.example.
 */

export type Lender = {
  id: string;
  name: string;
  states: string[];
  product: string;
  apr_range: string;
  complaint_count: number;
};

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function fetchLenders(): Promise<Lender[]> {
  const response = await fetch(`${API_BASE_URL}/lenders`, {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`GET /lenders failed with status ${response.status}`);
  }

  return response.json();
}
