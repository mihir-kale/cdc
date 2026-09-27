// Browser check for the pasted-offer flow.
//
// Separate from verify-ui.mjs because this one has to type a multi-line offer
// into a textarea, switch tabs, and read the composed briefing back out. That is
// the product's primary path now, and it cannot be exercised with AppTest.

import puppeteer from "puppeteer-core";
import { mkdirSync } from "node:fs";

const CHROME =
  process.env.CHROME_PATH ||
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const arg = (f, d) => {
  const i = process.argv.indexOf(f);
  return i > -1 ? process.argv[i + 1] : d;
};
const URL = arg("--url", "http://localhost:8899");
const OUT = arg("--out", "/tmp/opencode/shots");
mkdirSync(OUT, { recursive: true });

const OFFER = `Uprova Credit, LLC
Loan Amount: $300.00
APR: 391.00%
Finance Charge: $76.00
Total Repayment: $376.00
Term: 14 days`;

const results = [];
const check = (name, pass, detail = "") => {
  results.push({ name, pass: !!pass });
  console.log(`  [${pass ? "PASS" : "FAIL"}] ${name}${detail ? `  ${detail}` : ""}`);
};

const waitApp = async (page) => {
  await page.waitForSelector('[data-testid="stAppViewContainer"]', { timeout: 120000 });
  await page.waitForFunction(
    () => (document.body.innerText || "").includes("Know Your Lender"),
    { timeout: 120000, polling: 500 },
  );
  await new Promise((r) => setTimeout(r, 1200));
};

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "shell",
  args: ["--no-sandbox", "--disable-gpu", "--hide-scrollbars"],
});

try {
  const page = await browser.newPage();
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  await page.setViewport({ width: 1440, height: 1200 });
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 120000 });
  await waitApp(page);

  // Open the Ask tab.
  const opened = await page.evaluate(() => {
    const t = [...document.querySelectorAll('[role="tablist"] [role="tab"]')].find((x) =>
      /Check an offer|^Ask$/i.test(x.innerText || ""),
    );
    if (!t) return false;
    t.click();
    return true;
  });
  check("Ask tab opens", opened);
  await new Promise((r) => setTimeout(r, 2500));
  check(
    "tab shows the offer prompt",
    (await page.evaluate(() => document.body.innerText)).includes("Paste the offer"),
  );

  // Paste the offer.
  await page.click('[data-testid="stTextArea"] textarea');
  await page.type('[data-testid="stTextArea"] textarea', OFFER, { delay: 0 });
  await new Promise((r) => setTimeout(r, 1200));

  // Submit. The control is a form submit button, whose testid differs from a
  // plain stButton, so match both.
  const clicked = await page.evaluate(() => {
    const b = [
      ...document.querySelectorAll(
        '[data-testid="stButton"] button, [data-testid="stFormSubmitButton"] button',
      ),
    ].find((x) => /Check this offer/i.test(x.innerText || ""));
    if (!b) return false;
    b.click();
    return true;
  });
  check("submitted the offer", clicked);
  await new Promise((r) => setTimeout(r, 4000));

  const text = await page.evaluate(() => document.body.innerText);
  check("briefing names the lender", text.includes("Uprova Credit, LLC"));
  // innerText reflects CSS text-transform, and the section headings are
  // uppercased, so these have to be case-insensitive.
  check("briefing has the complaints section", /what people report about this lender/i.test(text));
  check("briefing reports the observed mix", text.includes("Fees & Costs") && text.includes("54.9%"));
  check("briefing includes Other", text.includes("Other reported issues"));
  check("briefing has the cost section", /what you would be paying/i.test(text));
  check("briefing shows the charge multiple", text.includes("25.3%"));
  check("briefing shows the total", text.includes("$376.00"));
  check("household section is opt-in only", text.includes("Include the household survey section"));
  check(
    "no risk score is claimed",
    !/risk score|credit score/i.test(text),
  );
  check("no ranking language", !/\b(best|worst|safest) lender\b/i.test(text));

  // The three original data tabs must still work.
  for (const label of ["Lender Complaint Profile", "Loan Payoff Calculator", "Methodology"]) {
    const ok = await page.evaluate((l) => {
      const t = [...document.querySelectorAll('[role="tablist"] [role="tab"]')].find(
        (x) => new RegExp(l, "i").test(x.innerText || ""),
      );
      if (!t) return false;
      t.click();
      return true;
    }, label);
    await new Promise((r) => setTimeout(r, 2000));
    const rendered = await page.evaluate(
      () => document.body.innerText.trim().length > 200,
    );
    check(`tab "${label}" still works`, ok && rendered);
  }

  await page.evaluate(() => {
    const t = [...document.querySelectorAll('[role="tablist"] [role="tab"]')].find((x) =>
      /Check an offer|^Ask$/i.test(x.innerText || ""),
    );
    if (t) t.click();
  });
  await new Promise((r) => setTimeout(r, 2500));
  await page.screenshot({ path: `${OUT}/briefing_1440.png`, fullPage: true });

  for (const w of [768, 375]) {
    await page.setViewport({ width: w, height: 1100 });
    await new Promise((r) => setTimeout(r, 1500));
    const of = await page.evaluate(() => ({
      s: document.documentElement.scrollWidth,
      c: document.documentElement.clientWidth,
    }));
    check(`no horizontal scroll at ${w}px`, of.s <= of.c + 1, `${of.s} vs ${of.c}`);
    await page.screenshot({ path: `${OUT}/briefing_${w}.png`, fullPage: w <= 768 });
  }

  check("no console errors", errors.length === 0, errors.slice(0, 2).join(" | "));
} finally {
  await browser.close();
}

const failed = results.filter((r) => !r.pass);
console.log(
  `\n  ${results.length - failed.length}/${results.length} passed` +
    (failed.length ? `  FAILED: ${failed.map((f) => f.name).join(", ")}` : ""),
);
process.exit(failed.length ? 1 : 0);
