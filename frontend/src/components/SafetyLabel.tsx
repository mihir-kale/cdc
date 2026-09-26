import type { DimensionScore, SafetyLabel as SafetyLabelData } from "@/lib/api";

/**
 * FinePrint — Payday Loan Safety Label.
 *
 * Design constraints worth preserving if this file is edited:
 *
 *  - No overall score, grade or rank. The five dimensions overlap, so any
 *    single number would hide that. The dependence analysis in
 *    `notebooks/cfpb_dimension_dependence.ipynb` is why.
 *  - No red/green. The CFPB has not classified any lender as safe or unsafe,
 *    so a traffic-light palette would assert something we cannot support. The
 *    scale is a single hue; the words carry the meaning.
 *  - Credible intervals stay secondary to the score, but are always present,
 *    because most dimensions are genuinely inconclusive.
 */

const COMPARISON_TEXT: Record<DimensionScore["comparison"], string> = {
  more: "More of these complaints than typical payday peers",
  fewer: "Fewer of these complaints than typical payday peers",
  similar: "Too close to typical payday peers to tell",
};

const EVIDENCE_STEPS = 4;

function plural(n: number, singular: string, pluralForm = `${singular}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? singular : pluralForm}`;
}

function evidenceStep(label: string): number {
  const order = [
    "Limited evidence",
    "Developing evidence",
    "Moderate evidence",
    "Stronger evidence",
  ];
  const index = order.indexOf(label);
  return index < 0 ? 1 : index + 1;
}

function DimensionRow({ dimension }: { dimension: DimensionScore }) {
  const { label, summary, score, comparison, complaints, prevalence, prevalence_lo90, prevalence_hi90 } =
    dimension;

  // Clamp so the meter can never render outside its track.
  const pct = Math.max(0, Math.min(100, score));

  return (
    <li className="border-t border-gray-200 py-5 first:border-t-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-sm font-semibold text-gray-900">
          <span title={summary} className="cursor-help border-b border-dotted border-gray-400">
            {label}
          </span>
        </h3>
        <p className="text-sm tabular-nums text-gray-500">
          <span className="text-2xl font-semibold text-gray-900">{score.toFixed(0)}</span>
          <span className="text-gray-400">/100</span>
        </p>
      </div>

      <p className="mt-1 text-xs text-gray-500">{summary}</p>

      <div className="relative mt-3 h-2.5 w-full overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-indigo-600"
          style={{ width: `${pct}%` }}
        />
        {/* The peer reference sits at 50 by construction of Method C. */}
        <div
          className="absolute top-0 h-full w-px bg-gray-400"
          style={{ left: "50%" }}
          aria-hidden="true"
        />
      </div>

      <div className="mt-1 flex justify-between text-[11px] text-gray-400">
        <span>More favorable</span>
        <span>Less favorable</span>
      </div>

      <p className="mt-2 text-xs text-gray-600">
        {COMPARISON_TEXT[comparison]}
        <span className="text-gray-400">
          {" "}
          — {plural(complaints, "complaint")}, estimated rate{" "}
          {(prevalence * 100).toFixed(1)}% (90% credible interval{" "}
          {(prevalence_lo90 * 100).toFixed(1)}–{(prevalence_hi90 * 100).toFixed(1)}%)
        </span>
      </p>
    </li>
  );
}

export default function SafetyLabel({ label }: { label: SafetyLabelData }) {
  const step = evidenceStep(label.evidence);
  const dimensions = Object.values(label.dimensions);

  return (
    <article className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
      <header>
        <h2 className="text-sm font-medium tracking-wide text-gray-500 uppercase">
          FinePrint — Payday Loan Safety Label
        </h2>
        <h3 className="mt-1 text-2xl font-bold text-gray-900">{label.name}</h3>
        <p className="mt-2 max-w-prose text-sm text-gray-600">
          {label.methodology.direction}
        </p>
      </header>

      <section className="mt-5 rounded-md bg-gray-50 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm text-gray-700">
              <span className="font-semibold tabular-nums">
                {label.n_complaints.toLocaleString()}
              </span>{" "}
              {label.n_complaints === 1 ? "CFPB payday complaint" : "CFPB payday complaints"}{" "}
              in this dataset
            </p>
            <p className="mt-1 text-xs text-gray-500">
              Evidence strength: <span className="font-medium text-gray-700">{label.evidence}</span>
            </p>
          </div>
          <div className="flex items-center gap-1" aria-hidden="true">
            {Array.from({ length: EVIDENCE_STEPS }, (_, i) => (
              <span
                key={i}
                className={`h-2 w-6 rounded-full ${
                  i < step ? "bg-indigo-600" : "bg-gray-200"
                }`}
              />
            ))}
          </div>
        </div>
        <p className="mt-2 text-xs text-gray-500">
          This describes how much complaint data supports the scores below, not how good or
          bad the lender is. More complaints usually means more customers, not more
          misconduct.
        </p>
      </section>

      <ul className="mt-6">
        {dimensions.map((dimension) => (
          <DimensionRow key={dimension.label} dimension={dimension} />
        ))}
      </ul>

      <p className="mt-4 text-xs text-gray-500">
        Scores are shown per dimension on purpose. FinePrint does not publish a single
        overall score, because the five dimensions overlap and combining them would
        hide that.
      </p>

      <section className="mt-6 border-t border-gray-200 pt-5">
        <h4 className="text-xs font-semibold tracking-wide text-gray-500 uppercase">
          How this is calculated
        </h4>
        <p className="mt-2 max-w-prose text-xs leading-relaxed text-gray-600">
          {label.methodology.summary}
        </p>
        <ul className="mt-3 max-w-prose space-y-1.5">
          {label.methodology.caveats.map((caveat) => (
            <li key={caveat} className="text-xs leading-relaxed text-gray-500">
              {caveat}
            </li>
          ))}
        </ul>
        <p className="mt-3 text-[11px] text-gray-400">Method: {label.method}</p>
      </section>
    </article>
  );
}
