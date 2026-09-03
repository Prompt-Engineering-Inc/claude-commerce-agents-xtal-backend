// Drive the running storefront through three turns in a headed browser, save a screenshot
// after each, and record per-turn timings measured inside the page: time from the chat
// request leaving the browser to the first byte, the first text_delta, the first ui
// event, and the end of the stream; plus every tool_call the agent made (name and input).
//
//   node scripts/demo_drive.js            # needs `npm install` (playwright) and the demo up
//   STOREFRONT_URL=http://localhost:3000 node scripts/demo_drive.js
//
// Output: docs/demo/NN-*.png and docs/demo/turns.json.

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const BASE = process.env.STOREFRONT_URL || "http://localhost:3000";
const OUT = path.resolve(__dirname, "..", "docs", "demo");
const TURNS = [
  "I need a warm shirt for a fall bonfire, under $80",
  "Compare the top two",
  "Which one has stretch?",
];

function instrumentFetch() {
  window.__turns = [];
  const original = window.fetch;
  window.fetch = async function (input, init) {
    const url = typeof input === "string" ? input : input.url;
    if (!url.includes("/api/chat")) return original.apply(this, arguments);
    const turn = { sent_at: Date.now(), first_byte_ms: null, first_text_ms: null, first_ui_ms: null, done_ms: null, first_event: {}, tool_calls: [], ui: [] };
    let pendingType = null;
    window.__turns.push(turn);
    const started = performance.now();
    const response = await original.apply(this, arguments);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const stream = new ReadableStream({
      async pull(controller) {
        const { done, value } = await reader.read();
        if (done) {
          turn.done_ms = Math.round(performance.now() - started);
          controller.close();
          return;
        }
        const now = Math.round(performance.now() - started);
        if (turn.first_byte_ms === null) turn.first_byte_ms = now;
        buffer += decoder.decode(value, { stream: true });
        let newline;
        while ((newline = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, newline);
          buffer = buffer.slice(newline + 1);
          if (line.startsWith("event: ")) {
            pendingType = line.slice(7).trim();
            if (!(pendingType in turn.first_event)) turn.first_event[pendingType] = now;
            if (pendingType === "text_delta" && turn.first_text_ms === null) turn.first_text_ms = now;
            if (pendingType === "ui" && turn.first_ui_ms === null) turn.first_ui_ms = now;
          } else if (line.startsWith("data: ") && pendingType) {
            try {
              const data = JSON.parse(line.slice(6));
              if (pendingType === "tool_call") turn.tool_calls.push({ at_ms: now, tool: data.tool, input: data.input });
              if (pendingType === "ui") turn.ui.push({ at_ms: now, component: data.component ?? data.tool ?? Object.keys(data)[0] });
            } catch (error) {
              // a malformed frame is not ours to fix
            }
          }
        }
        controller.enqueue(value);
      },
    });
    return new Response(stream, { status: response.status, headers: response.headers });
  };
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: false, slowMo: 40 });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.addInitScript(instrumentFetch);
  await page.goto(BASE, { waitUntil: "domcontentloaded" });
  const composer = page.locator("textarea").first();
  await composer.waitFor({ timeout: 60000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(OUT, "00-home.png") });

  for (const [index, message] of TURNS.entries()) {
    await composer.fill(message);
    await page.keyboard.press("Enter");
    await page.waitForFunction(
      (n) => window.__turns.length === n && window.__turns[n - 1].done_ms !== null,
      index + 1,
      { timeout: 240000 },
    );
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(OUT, `0${index + 1}-turn.png`) });
  }

  const turns = await page.evaluate(() => window.__turns);
  const record = { base_url: BASE, recorded_at: new Date().toISOString(), turns: TURNS.map((message, i) => ({ message, ...turns[i] })) };
  fs.writeFileSync(path.join(OUT, "turns.json"), JSON.stringify(record, null, 2));
  console.log(JSON.stringify(record, null, 2));
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
