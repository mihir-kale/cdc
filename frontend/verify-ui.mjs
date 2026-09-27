// Real-browser verification for the Streamlit lender UI.
//
// Exists because AppTest cannot see layout, contrast, viewport behaviour or a
// genuine click on a Streamlit widget. It drives the system Chrome against a
// running `streamlit run app.py`, waits for the app to actually render, and
// reports what a person would see.
//
//   node verify-ui.mjs [--url http://localhost:8899] [--out DIR]
//
// Exits non-zero if any check fails, so it can gate a commit.

import puppeteer from "puppeteer-core";
import { mkdirSync } from "node:fs";

const CHROME =
  process.env.CHROME_PATH ||
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const arg = (flag, fallback) => {
  const i = process.argv.indexOf(flag);
  return i > -1 ? process.argv[i + 1] : fallback;
};
const URL = arg("--url", "http://localhost:8899");
const OUT = arg("--out", "/tmp/opencode/shots");
const WIDTHS = (arg("--widths", "1440,1024,768,375") || "").split(",").map(Number);

mkdirSync(OUT, { recursive: true });

const results = [];
const check = (name, pass, detail = "") => {
  results.push({ name, pass: !!pass, detail });
  console.log(
    `  [${pass ? "PASS" : "FAIL"}] ${name}${detail ? `  ${detail}` : ""}`,
  );
};

// Streamlit renders a skeleton until the websocket completes, so wait on real
// app content rather than a fixed sleep.
const waitForApp = async (page) => {
  await page.waitForSelector('[data-testid="stAppViewContainer"]', {
    timeout: 120000,
  });
  await page.waitForFunction(
    () => {
      const el = document.querySelector('[data-testid="stAppViewContainer"]');
      if (!el) return false;
      const txt = el.innerText || "";
      return txt.includes("Know Your Lender") && !txt.includes("Running");
    },
    { timeout: 120000, polling: 500 },
  );
  // Let the custom stylesheet settle.
  await new Promise((r) => setTimeout(r, 1200));
};

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "shell",
  args: ["--no-sandbox", "--disable-gpu", "--hide-scrollbars"],
});

try {
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));

  await page.setViewport({ width: 1440, height: 1200 });
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 120000 });
  await waitForApp(page);

  // ---- 1. Tabs must be legible: dark text when idle, white on brand fill when
  //         selected. This is the reported bug, so it is checked by computed
  //         style rather than by eye.
  const tabInfo = await page.evaluate(() => {
    const list = document.querySelector('[data-testid="stTabs"] [role="tablist"]');
    if (!list) return { error: "no [role=tablist] under stTabs" };
    const btns = [...list.querySelectorAll('[role="tab"]')];
    const read = (b) => {
      const cs = getComputedStyle(b);
      // The visible text may live on the button or a descendant.
      // The visible text is a <p> inside the tab div, so measure the leaf that
      // actually carries the glyphs rather than the container.
      const label = b.innerText.trim().slice(0, 40);
      const leaf =
        [...b.querySelectorAll("p, span, div")].find(
          (el) => el.children.length === 0 && (el.textContent || "").trim(),
        ) || b;
      const fg = getComputedStyle(leaf).color;
      // Streamlit leaves the tab and the tablist transparent, so contrast has to
      // be measured against whatever is actually painted behind them. Walk up
      // until an opaque background turns up, otherwise a transparent parent reads
      // as a 1.18:1 "failure" for perfectly legible dark text.
      const effectiveBg = (el) => {
        for (let n = el; n; n = n.parentElement) {
          const bg = getComputedStyle(n).backgroundColor;
          const alpha = /rgba\([^)]*,\s*([\d.]+)\)/.exec(bg);
          const a = alpha ? parseFloat(alpha[1]) : 1;
          if (a > 0.99) return bg;
        }
        return getComputedStyle(document.body).backgroundColor;
      };
      return {
        label,
        selected: b.getAttribute("aria-selected"),
        color: fg,
        background: cs.backgroundColor,
        effectiveBg: effectiveBg(b),
        fontSize: cs.fontSize,
        width: Math.round(b.getBoundingClientRect().width),
        height: Math.round(b.getBoundingClientRect().height),
      };
    };
    return {
      tablistBg: getComputedStyle(list).backgroundColor,
      pageBg: getComputedStyle(document.body).backgroundColor,
      count: btns.length,
      tabs: btns.map(read),
    };
  });

  if (tabInfo.error) {
    check("tablist found", false, tabInfo.error);
  } else {
    check("tablist found with 4 tabs", tabInfo.count === 4, `count=${tabInfo.count}`);

    const parse = (c) => {
      const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(c || "");
      return m ? [+m[1], +m[2], +m[3]] : null;
    };
    const lum = ([r, g, b]) => {
      const f = (v) => {
        v /= 255;
        return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    // Flatten any alpha against the page background before comparing.
    const over = (fg, bg) => {
      const a = /rgba\([^)]*,\s*([\d.]+)\)/.exec(fg)?.[1];
      if (!a) return fg;
      const f = parse(fg);
      const b = parse(bg) || [255, 255, 255];
      const al = +a;
      return `rgb(${f.map((v, i) => Math.round(v * al + b[i] * (1 - al))).join(", ")})`;
    };
    const ratio = (f, b) => {
      const L1 = lum(parse(over(f, b)) || [0, 0, 0]);
      const L2 = lum(parse(b) || [1, 1, 1]);
      return (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    };

    for (const t of tabInfo.tabs) {
      const sel = t.selected === "true";
      const bg = sel ? t.background : t.effectiveBg;
      const cr = ratio(t.color, bg);
      const min = 4.5; // body text, so AA for normal text
      check(
        `tab "${t.label}" contrast ${sel ? "selected" : "idle"}`,
        cr >= min,
        `ratio=${cr.toFixed(2)} color=${t.color} bg=${bg}`,
      );
      check(
        `tab "${t.label}" not white-on-white`,
        !(lum(parse(over(t.color, bg)) || [0, 0, 0]) > 0.9 &&
          lum(parse(bg) || [0, 0, 0]) > 0.9),
        `color=${t.color} bg=${bg}`,
      );
      check(
        `tab "${t.label}" meets 44px tap target`,
        t.height >= 44,
        `h=${t.height}px`,
      );
    }
  }

  // ---- 2. The picker: type a fragment, click a lender, profile appears beside it.
  await page.type('[data-testid="stTextInput"] input', "upr");
  await new Promise((r) => setTimeout(r, 2500));
  const btnInfo = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('[data-testid="stButton"] button')];
    return btns.map((b) => ({
      text: b.innerText.trim().slice(0, 60),
      h: Math.round(b.getBoundingClientRect().height),
      w: Math.round(b.getBoundingClientRect().width),
    }));
  });
  check(
    "search yields a lender button",
    btnInfo.some((b) => /Uprova/.test(b.text)),
    JSON.stringify(btnInfo.slice(0, 3)),
  );
  check(
    "no checkbox grid",
    (await page.$$('[data-testid="stDataFrame"]')).length === 0,
  );

  const clicked = await page.evaluate(() => {
    const b = [...document.querySelectorAll('[data-testid="stButton"] button')].find(
      (x) => /Uprova/.test(x.innerText),
    );
    if (!b) return false;
    b.click();
    return true;
  });
  check("clicked the lender", clicked);
  await new Promise((r) => setTimeout(r, 3000));

  const after = await page.evaluate(() => {
    const txt = document.body.innerText;
    const hero = document.querySelector(".kyl-hero-sub");
    return {
      hasHero: /What consumers report about/.test(txt),
      hasWatch: /What should I pay attention to\?/.test(txt),
      rows: document.querySelectorAll(".kyl-crow").length,
      sub: hero ? hero.innerText.trim() : null,
      selectedBtn: [...document.querySelectorAll('[data-testid="stButton"] button')]
        .filter((b) => getComputedStyle(b).backgroundColor !== "rgba(0, 0, 0, 0)")
        .map((b) => b.innerText.trim().slice(0, 30)),
    };
  });
  check("profile rendered after click", after.hasHero);
  check("six category rows", after.rows === 6, `rows=${after.rows}`);
  check("watch-for present", after.hasWatch);
  check(
    "selected lender shows complaint count",
    /175/.test(after.sub || ""),
    after.sub,
  );
  check(
    "chosen lender is visually marked",
    after.selectedBtn.some((t) => /Uprova/.test(t)),
    JSON.stringify(after.selectedBtn.slice(0, 3)),
  );

  // ---- 3. Side-by-side: picker and profile on the same row, not stacked.
  const layout = await page.evaluate(() => {
    const input = document.querySelector('[data-testid="stTextInput"]');
    const hero = document.querySelector(".kyl-hero-sub");
    if (!input || !hero) return null;
    const a = input.closest('[data-testid="stColumn"]')?.getBoundingClientRect();
    const b = hero.closest('[data-testid="stColumn"]')?.getBoundingClientRect();
    if (!a || !b) return null;
    return { ax: Math.round(a.x), bx: Math.round(b.x), aw: Math.round(a.width), bw: Math.round(b.width) };
  });
  check(
    "picker sits beside the profile",
    layout && layout.bx > layout.ax + layout.aw - 20,
    JSON.stringify(layout),
  );

  // ---- 4. No horizontal overflow at any width, and no clipped content.
  for (const w of WIDTHS) {
    await page.setViewport({ width: w, height: 1100 });
    await new Promise((r) => setTimeout(r, 1400));
    const of = await page.evaluate(() => ({
      scrollW: document.documentElement.scrollWidth,
      clientW: document.documentElement.clientWidth,
    }));
    check(
      `no horizontal scroll at ${w}px`,
      of.scrollW <= of.clientW + 1,
      `scrollW=${of.scrollW} clientW=${of.clientW}`,
    );
    await page.screenshot({
      path: `${OUT}/lender_${w}.png`,
      fullPage: w <= 768,
    });
  }
  await page.setViewport({ width: 1440, height: 1200 });
  await new Promise((r) => setTimeout(r, 1000));
  await page.screenshot({ path: `${OUT}/lender_1440_full.png`, fullPage: true });

  // ---- 5. Other tabs render and are clickable.
  for (const label of ["Household", "Payoff", "Methodology"]) {
    const ok = await page.evaluate((l) => {
      const b = [...document.querySelectorAll('[role="tablist"] [role="tab"]')].find(
        (x) => new RegExp(l, "i").test(x.innerText || x.textContent || ""),
      );
      if (!b) return false;
      b.click();
      return true;
    }, label);
    check(`tab "${label}" clickable`, ok);
    await new Promise((r) => setTimeout(r, 2200));
    const rendered = await page.evaluate(() => {
      const t = document.body.innerText;
      return t.trim().length > 200 && !/Traceback|Uncaught app execution/.test(t);
    });
    check(`tab "${label}" renders content`, rendered);
    await page.screenshot({ path: `${OUT}/tab_${label}.png` });
  }

  check(
    "no console errors",
    consoleErrors.length === 0,
    consoleErrors.slice(0, 3).join(" | "),
  );
} finally {
  await browser.close();
}

const failed = results.filter((r) => !r.pass);
console.log(
  `\n  ${results.length - failed.length}/${results.length} passed` +
    (failed.length ? `  FAILED: ${failed.map((f) => f.name).join(", ")}` : ""),
);
console.log(`  screenshots in ${OUT}`);
process.exit(failed.length ? 1 : 0);
