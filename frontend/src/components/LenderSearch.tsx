"use client";

import { useEffect, useMemo, useState } from "react";

import { fetchLender, fetchLenders, type LenderSummary, type SafetyLabel } from "@/lib/api";
import SafetyLabelView from "@/components/SafetyLabel";

/** Longest list rendered before the user is asked to narrow the query. */
const MAX_RESULTS = 25;

export default function LenderSearch() {
  const [lenders, setLenders] = useState<LenderSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<{ id: string; name: string } | null>(null);
  const [label, setLabel] = useState<SafetyLabel | null>(null);
  const [labelError, setLabelError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    fetchLenders()
      .then((data) => {
        if (active) setLenders(data);
      })
      .catch((err: Error) => {
        if (active) setLoadError(err.message);
      });

    return () => {
      active = false;
    };
  }, []);

  // Selecting a lender is the only thing that ever opens a label, so the previous
  // label is cleared here rather than inside the fetching effect. Resetting state
  // in an effect body would trigger a cascading render on every selection.
  function selectLender(lender: LenderSummary) {
    setLabel(null);
    setLabelError(null);
    setSelected({ id: lender.id, name: lender.name });
    setQuery(lender.name);
  }

  useEffect(() => {
    if (!selected) return;

    let active = true;

    fetchLender(selected.id)
      .then((data) => {
        if (active) setLabel(data);
      })
      .catch((err: Error) => {
        if (active) setLabelError(err.message);
      });

    return () => {
      active = false;
    };
  }, [selected]);

  const matches = useMemo(() => {
    if (!lenders) return [];
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return lenders.filter((lender) => lender.name.toLowerCase().includes(q));
  }, [lenders, query]);

  if (loadError) {
    return (
      <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-800">
        <p className="font-medium">Could not reach the backend.</p>
        <p className="mt-1 text-red-700">{loadError}</p>
        <p className="mt-2 text-red-700">
          Start it with <code>uvicorn app.main:app --reload</code> in{" "}
          <code>backend/</code>.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      <section>
        <label
          htmlFor="lender-search"
          className="mb-2 block text-sm font-medium text-gray-700"
        >
          Search for a lender
        </label>
        <input
          id="lender-search"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Start typing a lender name"
          autoComplete="off"
          className="w-full rounded border border-gray-300 px-4 py-2 outline-none focus:border-gray-500"
        />
        <p className="mt-2 text-xs text-gray-500">
          {lenders
            ? `Searches all ${lenders.length.toLocaleString()} payday lenders in the CFPB complaint data, including those with only a handful of complaints.`
            : "Loading lenders…"}
        </p>

        {query.trim() && !lenders && <p className="mt-2 text-sm text-gray-500">Loading lenders…</p>}

        {query.trim() && lenders && matches.length === 0 && (
          <p className="mt-3 text-sm text-gray-600">
            No lender matches “{query.trim()}”. Check the spelling, or try a shorter
            fragment of the name.
          </p>
        )}

        {matches.length > 0 && (
          <ul className="mt-3 max-h-80 divide-y overflow-y-auto rounded border border-gray-200">
            {matches.slice(0, MAX_RESULTS).map((lender) => (
              <li key={lender.id}>
                <button
                  type="button"
                  onClick={() => selectLender(lender)}
                  className="flex w-full items-baseline justify-between gap-3 px-4 py-3 text-left hover:bg-gray-50"
                >
                  <span className="font-medium text-gray-900">{lender.name}</span>
                  <span className="shrink-0 text-xs whitespace-nowrap text-gray-500">
                    {lender.n_complaints.toLocaleString()}{" "}
                    {lender.n_complaints === 1 ? "complaint" : "complaints"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {matches.length > MAX_RESULTS && (
          <p className="mt-2 text-xs text-gray-500">
            Showing the first {MAX_RESULTS} of {matches.length} matches. Keep typing to
            narrow the list.
          </p>
        )}
      </section>

      {labelError && (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-800">
          <p className="font-medium">Could not load the safety label.</p>
          <p className="mt-1 text-red-700">{labelError}</p>
        </div>
      )}

      {label && <SafetyLabelView label={label} />}

      {!label && !labelError && selected && (
        <p className="text-sm text-gray-500">Loading safety label…</p>
      )}
    </div>
  );
}
