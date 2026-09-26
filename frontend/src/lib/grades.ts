/**
 * A-F bands for the Safety Label dimensions.
 *
 * Method C places a typical modelled payday peer at exactly 50 -- that is what
 * the reference tick on each meter marks -- so 50 is the one boundary in this
 * scale that means something on its own. It is where a lender stops being more
 * favorable than its peers and starts being less favorable, so the C/D cut sits
 * there rather than at some rounder number.
 *
 * The remaining cuts are placed in gaps in the observed distribution of all
 * 2,410 dimension-scores (482 lenders x 5) instead of at even intervals, so a
 * boundary never lands where the data is dense. Linear cuts would have been
 * worse than useless here: the distribution piles up around the peer reference
 * and has long tails, so A>=90/B>=80/.../F<60 puts 72.9% of every dimension in
 * F while the model simultaneously calls 91% of them indistinguishable from
 * peers.
 *
 * Resulting shares: A 18.3%, B 17.6%, C 34.7%, D 3.2%, E 5.8%, F 20.4%. C is the
 * widest band by design -- it is where the middle of the survey sits.
 *
 * Two things these bands are not:
 *
 *  - They are relative, not absolute. An F means "materially less favorable
 *    than modelled payday peers". It does not mean the lender is unsafe, and the
 *    CFPB has classified no lender as safe or unsafe. The descriptor text
 *    carries that distinction, which is also why the palette stays a single hue.
 *  - They are per dimension only. The five dimensions overlap, so there is
 *    deliberately no overall grade and no ranking. See
 *    `notebooks/cfpb_dimension_dependence.ipynb`.
 */

export type Grade = "A" | "B" | "C" | "D" | "E" | "F";

export type GradeBand = {
  grade: Grade;
  /** Inclusive lower bound on the 0-100 score. */
  min: number;
  /** Plain-language reading of the band, always phrased against peers. */
  descriptor: string;
};

/** Ordered high to low; `gradeFor` relies on that order. */
export const GRADE_BANDS: readonly GradeBand[] = [
  { grade: "A", min: 65, descriptor: "Much more favorable than peers" },
  { grade: "B", min: 57.5, descriptor: "More favorable than peers" },
  { grade: "C", min: 50, descriptor: "About average for peers" },
  { grade: "D", min: 40, descriptor: "Somewhat less favorable than peers" },
  { grade: "E", min: 30, descriptor: "Less favorable than peers" },
  { grade: "F", min: 0, descriptor: "Much less favorable than peers" },
];

/** Band containing `score`. Out-of-range scores are clamped, not rejected. */
export function gradeFor(score: number): GradeBand {
  const clamped = Math.max(0, Math.min(100, score));
  return (
    GRADE_BANDS.find((band) => clamped >= band.min) ??
    GRADE_BANDS[GRADE_BANDS.length - 1]
  );
}
