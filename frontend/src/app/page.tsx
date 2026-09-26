import LenderSearch from "@/components/LenderSearch";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-6 py-16">
      <header className="text-center">
        <h1 className="text-4xl font-bold tracking-tight">FinePrint</h1>
        <p className="mt-3 text-lg text-gray-600">
          Understand a payday loan before you take it.
        </p>
      </header>

      <LenderSearch />

      <footer className="mt-auto border-t border-gray-200 pt-6 text-xs leading-relaxed text-gray-500">
        <p>
          FinePrint analyzes CFPB consumer complaints for payday loans. Each dimension
          compares the pattern of complaints associated with a lender against modeled
          payday-loan peers. Statistical shrinkage reduces extreme estimates when
          relatively little complaint data is available.
        </p>
        <p className="mt-2">
          CFPB complaints are consumer-submitted reports and do not necessarily indicate
          verified wrongdoing. Complaint volume is used to communicate evidence
          strength; a lender is not penalized simply for having more complaints because
          FinePrint does not currently have lender-level customer or loan-volume
          denominators.
        </p>
      </footer>
    </main>
  );
}
