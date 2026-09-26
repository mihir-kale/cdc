import LenderSearch from "@/components/LenderSearch";
import FinancialContext from "@/components/FinancialContext";
import ProductTabs from "@/components/ProductTabs";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-6 py-16">
      <header className="text-center">
        <h1 className="text-4xl font-bold tracking-tight">FinePrint</h1>
        <p className="mt-3 text-lg text-gray-600">
          Understand a payday loan before you take it.
        </p>
      </header>

      <ProductTabs
        tabs={[
          {
            id: "safety-label",
            label: "Lender safety label",
            content: (
              <section aria-labelledby="lender-safety-heading" className="flex flex-col gap-4">
                <div>
                  <h2
                    id="lender-safety-heading"
                    className="text-sm font-medium tracking-wide text-gray-500 uppercase"
                  >
                    About the lender
                  </h2>
                  <p className="mt-1 text-sm text-gray-600">
                    How does this lender&rsquo;s CFPB complaint profile compare with
                    modeled payday-loan peers?
                  </p>
                </div>
                <LenderSearch />
              </section>
            ),
          },
          {
            id: "household-context",
            label: "Household financial context",
            content: (
              <section aria-labelledby="household-context-heading" className="flex flex-col gap-4">
                <div>
                  <h2
                    id="household-context-heading"
                    className="text-sm font-medium tracking-wide text-gray-500 uppercase"
                  >
                    About the household
                  </h2>
                  <p className="mt-1 text-sm text-gray-600">
                    Where does a household like this one sit among surveyed households?
                  </p>
                </div>
                <FinancialContext />
              </section>
            ),
          },
        ]}
      />

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
        <p className="mt-2">
          The Household Financial Context section is a separate, independent analysis
          drawn from the CFPB National Financial Well-Being Survey. It describes a
          household, never a lender, and there is no overall FinePrint score combining
          the two.
        </p>
      </footer>
    </main>
  );
}
