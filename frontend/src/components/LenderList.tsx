"use client";

import { useEffect, useState } from "react";

import { fetchLenders, type Lender } from "@/lib/api";

/**
 * Fetches the lender list from the backend to confirm the two halves of the
 * stack can talk to each other. No styling beyond the basics yet.
 */
export default function LenderList() {
  const [lenders, setLenders] = useState<Lender[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    fetchLenders()
      .then((data) => {
        if (active) setLenders(data);
      })
      .catch((err: Error) => {
        if (active) setError(err.message);
      });

    return () => {
      active = false;
    };
  }, []);

  if (error) {
    return (
      <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-800">
        <p className="font-medium">Could not reach the backend.</p>
        <p className="mt-1 text-red-700">{error}</p>
        <p className="mt-2 text-red-700">
          Start it with <code>uvicorn app.main:app --reload</code> in{" "}
          <code>backend/</code>.
        </p>
      </div>
    );
  }

  if (!lenders) {
    return <p className="text-sm text-gray-500">Loading lenders…</p>;
  }

  return (
    <ul className="divide-y rounded border border-gray-200">
      {lenders.map((lender) => (
        <li key={lender.id} className="px-4 py-3">
          <p className="font-medium">{lender.name}</p>
          <p className="text-sm text-gray-500">
            {lender.product} · APR {lender.apr_range} ·{" "}
            {lender.states.join(", ")}
          </p>
        </li>
      ))}
    </ul>
  );
}
