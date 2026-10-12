import puppeteer from "puppeteer-core";

const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const URL = "http://localhost:5174/";
const SHOTS = "C:/Users/ADMINI~1/AppData/Local/Temp/opencode/rims-intro-test";

const errors = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function attachLogs(page) {
  page.on("console", (m) => {
    if (["error", "warning"].includes(m.type()))
      errors.push(`[console.${m.type()}] ${m.text()}`);
  });
  page.on("pageerror", (e) => errors.push(`[pageerror] ${e.message}`));
}

async function introState(page) {
  return page.evaluate(() => {
    const intro = document.querySelector(".intro");
    const img = document.querySelector(".intro-scene__img");
    const step0 = document.querySelector(".intro-scene--logo.is-active") != null;
    const ready = document.querySelector(".intro-ready") != null;
    const laptop = document.querySelector(".intro-laptop__screen") != null;
    return {
      hasIntro: intro != null,
      isFaded: intro?.classList.contains("is-faded") ?? false,
      isClosing: intro?.classList.contains("is-closing") ?? false,
      bodyOverflow: document.body.style.overflow,
      step0,
      ready,
      laptop,
      imgCount: document.images.length,
      imgLoaded:
        img == null
          ? "none"
          : img.complete && img.naturalWidth > 0
            ? `loaded(${img.naturalWidth}x${img.naturalHeight})`
            : "loading/error",
      logoImg: [...document.images].some((i) =>
        i.src.includes("rims-logo"),
      ),
      brandFallback: document.querySelector(".intro-social") != null,
    };
  });
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
await attachLogs(page);

// ---- 1. Normal / motion-enabled flight through the film ----------------
await page.goto(URL, { waitUntil: "load", timeout: 60000 });

await page.waitForSelector(".intro", { timeout: 15000 });
await sleep(1200);
console.log("T+1.2s:", JSON.stringify(await introState(page)));
await page.screenshot({ path: `${SHOTS}/01-logo-reveal.png` });

await sleep(2600);
console.log("T+3.8s:", JSON.stringify(await introState(page)));
await page.screenshot({ path: `${SHOTS}/02-day-scene.png` });

await sleep(5200);
console.log("T+9.0s:", JSON.stringify(await introState(page)));
await page.screenshot({ path: `${SHOTS}/03-ready-laptop.png` });

// Click through into the calculator.
const cta = await page.$(".intro-cta__button");
const label = cta ? await cta.evaluate((b) => b.textContent.trim()) : "MISSING";
console.log("CTA label:", JSON.stringify(label));
await cta.click();
await sleep(400);
await page.screenshot({ path: `${SHOTS}/04-morph.png` });
await sleep(1000);
console.log("T+after-click:", JSON.stringify(await introState(page)));

const post = await page.evaluate(() => {
  const active = document.activeElement;
  return {
    hasHeading: document.body.textContent.includes("Know your delivery cost"),
    leaflet: document.querySelectorAll(".leaflet-container").length,
    activeTag: active?.tagName,
    activePlaceholder: active?.getAttribute("placeholder"),
  };
});
console.log("Post-intro:", JSON.stringify(post));
await page.screenshot({ path: `${SHOTS}/05-calculator.png` });

// ---- 2. Search still works (real Nominatim) ----------------------------
try {
  const input = await page.$("input[role=combobox]");
  await input.type("Naivasha", { delay: 40 });
  await sleep(1200);
  const results = await page.evaluate(() => {
    const items = document.querySelectorAll("ul[role=listbox] li[role=option]");
    return [...items].slice(0, 3).map((li) => li.textContent.trim());
  });
  console.log("Search results:", JSON.stringify(results));
  if (results.length) {
    const first = await page.$("ul[role=listbox] li[role=option]");
    await first.click();
  }
} catch (e) {
  console.log("Search step failed:", e.message);
}
await sleep(500);
await page.screenshot({ path: `${SHOTS}/06-selected.png` });

// ---- 3. Reduce-motion path: static opening, no auto-advance ------------
await page.evaluate(() => sessionStorage.clear());
await page.emulateMediaFeatures([
  { name: "prefers-reduced-motion", value: "reduce" },
]);
await page.goto(URL, { waitUntil: "load", timeout: 60000 });
await page.waitForSelector(".intro", { timeout: 15000 });
await sleep(1000);
const reducedState = await page.evaluate(() => ({
  static: document.querySelector(".intro--static") != null,
  bodyOverflow: document.body.style.overflow,
  readyImmediately: document.querySelector(".intro-cta__button") != null,
}));
console.log("Reduced-motion:", JSON.stringify(reducedState));
await page.screenshot({ path: `${SHOTS}/07-reduced.png` });
await page.keyboard.press("Escape");
await sleep(500);
console.log("Reduced after Escape:", JSON.stringify(await introState(page)));

await browser.close();

console.log("\n=== CONSOLE/PAGE ERRORS ===");
if (errors.length) {
  const unique = [...new Set(errors)];
  unique.forEach((e) => console.log(e));
} else {
  console.log("(none)");
}