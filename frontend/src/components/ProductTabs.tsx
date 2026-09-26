"use client";

import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";

export type ProductTab = {
  /** Stable slug, used to wire each tab to its panel. */
  id: string;
  label: string;
  content: ReactNode;
};

/**
 * Product tabs.
 *
 * Each FinePrint product answers a different question, from a different dataset
 * and a different unit of analysis -- one describes a lender, the other
 * describes a household, and nothing combines them. They therefore get one tab
 * each instead of sharing a scrolling page, which stops the page from reading as
 * a single verdict about a single borrower.
 *
 * Accessibility notes: this is a real ARIA tablist, so arrow keys move between
 * tabs, Home/End jump to the ends, and only the selected tab is in the page tab
 * order. Both panels stay mounted and the inactive one is `hidden`, so a
 * half-typed lender search or a filled-in household profile survives a tab
 * switch instead of being thrown away.
 */
export default function ProductTabs({ tabs }: { tabs: ProductTab[] }) {
  const [active, setActive] = useState(0);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  function focusTab(index: number) {
    // Wraps in both directions, so Left from the first tab lands on the last.
    const next = (index + tabs.length) % tabs.length;
    setActive(next);
    tabRefs.current[next]?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    switch (event.key) {
      case "ArrowRight":
        event.preventDefault();
        focusTab(index + 1);
        break;
      case "ArrowLeft":
        event.preventDefault();
        focusTab(index - 1);
        break;
      case "Home":
        event.preventDefault();
        focusTab(0);
        break;
      case "End":
        event.preventDefault();
        focusTab(tabs.length - 1);
        break;
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div
        role="tablist"
        aria-label="FinePrint products"
        className="flex flex-wrap gap-1 border-b border-gray-200"
      >
        {tabs.map((tab, index) => {
          const selected = index === active;
          return (
            <button
              key={tab.id}
              ref={(node) => {
                tabRefs.current[index] = node;
              }}
              type="button"
              role="tab"
              id={`tab-${tab.id}`}
              aria-selected={selected}
              aria-controls={`panel-${tab.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => setActive(index)}
              onKeyDown={(event) => onKeyDown(event, index)}
              className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
                selected
                  ? "border-indigo-600 text-indigo-700"
                  : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {tabs.map((tab, index) => {
        const selected = index === active;
        return (
          <div
            key={tab.id}
            role="tabpanel"
            id={`panel-${tab.id}`}
            aria-labelledby={`tab-${tab.id}`}
            hidden={!selected}
            tabIndex={0}
            // `hidden` alone is not enough: it is a UA-origin `display: none`,
            // which any author-origin `display` utility beats. Keeping `flex` on
            // an inactive panel would leave it visible, so the layout classes go
            // on only while the panel is the selected one. The attribute stays
            // for semantics and for when the stylesheet fails to load.
            className={
              selected
                ? "flex flex-col gap-4 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-indigo-600"
                : "hidden"
            }
          >
            {tab.content}
          </div>
        );
      })}
    </div>
  );
}
