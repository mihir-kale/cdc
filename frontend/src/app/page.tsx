import LenderList from "@/components/LenderList";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-8 px-6 py-16">
      <header className="text-center">
        <h1 className="text-4xl font-bold tracking-tight">FinePrint</h1>
        <p className="mt-3 text-lg text-gray-600">
          Understand a payday loan before you take it.
        </p>
      </header>

      <div className="flex flex-col items-center gap-3">
        <input
          type="search"
          placeholder="Search for a lender"
          aria-label="Search for a lender"
          className="w-full rounded border border-gray-300 px-4 py-2 outline-none focus:border-gray-500"
        />
        <button
          type="button"
          className="w-full rounded bg-gray-900 px-4 py-2 font-medium text-white hover:bg-gray-700"
        >
          Compare Lenders
        </button>
      </div>

      <section>
        <h2 className="mb-2 text-sm font-medium tracking-wide text-gray-500 uppercase">
          Backend connection check
        </h2>
        <LenderList />
      </section>
    </main>
  );
}
