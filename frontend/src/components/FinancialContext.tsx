"use client";

import { useEffect, useMemo, useState } from "react";

import {
  fetchHouseholdContext,
  fetchHouseholdInputOptions,
  type HouseholdContext,
  type HouseholdInputOptions,
  type HouseholdProfile,
} from "@/lib/api";

/**
 * Household Financial Context.
 *
 * Visually and conceptually separate from the Safety Label above it: a different
 * question, a different dataset, a different unit of analysis. This component
 * accepts no lender and emits nothing about lenders.
 *
 * The headline result is a percentile -- where a household like this one sat
 * among 6,232 surveyed households. The underlying model probability is kept but
 * shown only as a secondary technical detail, because "you have a 34% chance of
 * needing SNAP" is a much stronger claim than a 2016 survey association can
 * support. There are deliberately no loan amount, rate, term or payment inputs,
 * because no model here can speak to those.
 */

/** Starting values. Deliberately mid-range, and visibly editable. */
const INITIAL_PROFILE: HouseholdProfile = {
  age_band: 3,
  education: 2,
  household_income: 2,
  marital_status: 4,
  household_size: 3,
  metro_area: 1,
  county_poverty_share: 1,
  children_0_1: false,
  children_2_5: false,
  children_6_12: false,
  children_13_17: false,
};

/** Order the single-choice selects appear in. */
const FIELD_ORDER = [
  "age_band",
  "household_size",
  "household_income",
  "education",
  "marital_status",
  "metro_area",
  "county_poverty_share",
] as const;

const BAND_ACCENT: Record<HouseholdContext["context_band"], string> = {
  higher_strain: "bg-indigo-600",
  typical_strain: "bg-indigo-400",
  lower_strain: "bg-indigo-200",
};

function SelectField({
  label,
  value,
  onChange,
  options,
  id,
}: {
  label: string;
  value: number;
  onChange: (code: number) => void;
  options: { code: number; label: string }[];
  id: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-gray-700">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full rounded border border-gray-300 bg-white px-3 py-2 outline-none focus:border-gray-500"
      >
        {options.map((option) => (
          <option key={option.code} value={option.code}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export default function FinancialContext() {
  const [schema, setSchema] = useState<HouseholdInputOptions | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [profile, setProfile] = useState<HouseholdProfile>(INITIAL_PROFILE);
  const [result, setResult] = useState<HouseholdContext | null>(null);
  const [resultError, setResultError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let active = true;

    fetchHouseholdInputOptions()
      .then((data) => {
        if (active) setSchema(data);
      })
      .catch((err: Error) => {
        if (active) setSchemaError(err.message);
      });

    return () => {
      active = false;
    };
  }, []);

  function update<K extends keyof HouseholdProfile>(
    key: K,
    value: HouseholdProfile[K],
  ) {
    setProfile((current) => ({ ...current, [key]: value }));
  }

  function runAssessment(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setResultError(null);

    fetchHouseholdContext(profile)
      .then((data) => setResult(data))
      .catch((err: Error) => setResultError(err.message))
      .finally(() => setPending(false));
  }

  const childOptions = useMemo(
    () => schema?.inputs.children.options ?? [],
    [schema],
  );

  if (schemaError) {
    return (
      <div className="rounded border border-red-300 bg-red-50 p-4 text-sm text-red-800">
        <p className="font-medium">Could not load the household inputs.</p>
        <p className="mt-1 text-red-700">{schemaError}</p>
        <p className="mt-2 text-red-700">
          Start the backend with <code>uvicorn app.main:app --reload</code> in{" "}
          <code>backend/</code>.
        </p>
      </div>
    );
  }

  return (
    <article className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <h2 className="text-sm font-medium tracking-wide text-gray-500 uppercase">
        Household Financial Context
      </h2>
      <h3 className="mt-1 text-2xl font-bold text-gray-900">
        How does a household like yours compare?
      </h3>
      <p className="mt-2 max-w-prose text-sm text-gray-600">
        This is a separate question from the safety label above. The safety label
        describes a lender. This describes a household, using patterns from a
        national survey. The two are never combined.
      </p>

      {!schema ? (
        <p className="mt-4 text-sm text-gray-500">Loading inputs…</p>
      ) : (
        <form onSubmit={runAssessment} className="mt-5 flex flex-col gap-5">
          <div className="grid gap-4 sm:grid-cols-2">
            {FIELD_ORDER.map((key) => {
              const field = schema.inputs[key];
              if (!field) return null;
              return (
                <SelectField
                  key={key}
                  id={`household-${key}`}
                  label={field.label}
                  value={profile[key]}
                  onChange={(code) => update(key, code as never)}
                  options={field.options}
                />
              );
            })}
          </div>

          <fieldset>
            <legend className="mb-2 text-sm font-medium text-gray-700">
              {schema.inputs.children.label}
            </legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {childOptions.map((option) => {
                const field = option.field;
                if (!field) return null;
                const checked = Boolean(profile[field as keyof HouseholdProfile]);
                const id = `household-${field}`;
                return (
                  <label
                    key={field}
                    htmlFor={id}
                    className="flex cursor-pointer items-center gap-2 rounded border border-gray-200 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
                  >
                    <input
                      id={id}
                      type="checkbox"
                      checked={checked}
                      onChange={(event) =>
                        update(
                          field as keyof HouseholdProfile,
                          event.target.checked as never,
                        )
                      }
                      className="h-4 w-4 rounded border-gray-400"
                    />
                    {option.label}
                  </label>
                );
              })}
            </div>
          </fieldset>

          <div>
            <button
              type="submit"
              disabled={pending}
              className="rounded bg-gray-900 px-5 py-2.5 text-sm font-medium text-white outline-none hover:bg-gray-700 disabled:opacity-50"
            >
              {pending ? "Assessing…" : "Show household context"}
            </button>
          </div>
        </form>
      )}

      {resultError && (
        <div className="mt-5 rounded border border-red-300 bg-red-50 p-4 text-sm text-red-800">
          <p className="font-medium">Could not run the assessment.</p>
          <p className="mt-1 text-red-700">{resultError}</p>
        </div>
      )}

      {result && (
        <section className="mt-6 border-t border-gray-200 pt-5">
          <p className="text-sm font-medium text-gray-500">
            Where households like yours fell
          </p>
          <p className="mt-1 text-3xl font-bold text-gray-900">
            {result.survey_percentile}
            <span className="ml-1 text-base font-normal text-gray-500">
              out of 100
            </span>
          </p>
          <p className="mt-1 text-sm text-gray-700">{result.band_label}</p>

          <div
            className="relative mt-4 h-2.5 w-full overflow-hidden rounded-full bg-gray-100"
            role="img"
            aria-label={`Position ${result.survey_percentile} out of 100 among surveyed households`}
          >
            <div
              className={`h-full rounded-full ${BAND_ACCENT[result.context_band]}`}
              style={{ width: `${result.survey_percentile}%` }}
            />
          </div>
          <div className="mt-1 flex justify-between text-[11px] text-gray-400">
            <span>Least strained</span>
            <span>Most strained</span>
          </div>

          <p className="mt-4 max-w-prose text-sm text-gray-700">
            {result.summary}
          </p>

          <details className="mt-4 rounded-md bg-gray-50 p-4 text-sm">
            <summary className="cursor-pointer font-medium text-gray-700">
              How this is calculated
            </summary>
            <p className="mt-2 text-gray-600">{result.what_this_is}</p>
            <ul className="mt-3 list-disc space-y-1 pl-5 text-gray-600">
              {result.what_this_is_not.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            <dl className="mt-4 grid gap-1 text-xs text-gray-500">
              <div>
                <dt className="inline font-medium text-gray-600">Survey: </dt>
                <dd className="inline">
                  {result.methodology.survey} ({result.methodology.survey_year})
                </dd>
              </div>
              <div>
                <dt className="inline font-medium text-gray-600">
                  Households modelled:{" "}
                </dt>
                <dd className="inline">
                  {result.methodology.households_modelled.toLocaleString()}
                </dd>
              </div>
              <div>
                <dt className="inline font-medium text-gray-600">
                  Model accuracy (ROC-AUC):{" "}
                </dt>
                <dd className="inline">
                  {result.methodology.weighted_roc_auc.toFixed(3)}
                </dd>
              </div>
              <div>
                <dt className="inline font-medium text-gray-600">
                  Model association rate:{" "}
                </dt>
                <dd className="inline">
                  {(result.model_association_rate * 100).toFixed(1)}% — a
                  technical figure describing the model&rsquo;s output, not a
                  forecast about you
                </dd>
              </div>
            </dl>
            <p className="mt-3 text-xs text-gray-500">
              {result.methodology.relationship_to_safety_label}
            </p>
          </details>

          <details className="mt-3 text-sm">
            <summary className="cursor-pointer font-medium text-gray-700">
              Limitations
            </summary>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-gray-600">
              {result.caveats.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </details>
        </section>
      )}
    </article>
  );
}
