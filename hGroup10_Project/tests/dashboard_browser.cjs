/* Offline browser regression: all HTTP requests are intercepted; no hardware.
 * Run with Node and an existing Playwright installation:
 *   node tests/dashboard_browser.cjs
 * Optional env: PYTHON, PLAYWRIGHT_MODULE, CHROME_PATH.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {execFileSync} = require("node:child_process");
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || "playwright-core");
const root = path.resolve(__dirname, "..");
const fixtures = JSON.parse(execFileSync(process.env.PYTHON || "python3", [
  "-B", path.join(__dirname, "test_dashboard.py"), "--fixtures",
], {encoding: "utf8", cwd: root}));

async function main() {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROME_PATH ? {executablePath: process.env.CHROME_PATH} : {}),
  });
  try {
    const page = await browser.newPage({viewport: {width: 1100, height: 700}});
    await page.clock.install();
    const errors = [];
    const commands = [];
    let documents = 0;
    let polls = 0;
    let fragment = "online";
    let failPoll = false;
    let holdPoll = false;
    let heldPoll;
    let holdCommand = false;
    let heldCommand;
    let commandResult = {ok: true, reason: "Command accepted by fake controller"};
    page.on("pageerror", error => errors.push(String(error)));
    await page.route("**/*", async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.hostname !== "dashboard.test") return route.abort();
      if (url.pathname === "/") {
        documents += 1;
        return route.fulfill({contentType: "text/html", body: fixtures.page});
      }
      if (url.pathname === "/api/dashboard") {
        polls += 1;
        if (holdPoll) { heldPoll = route; return; }
        const html = fixtures[fragment].replace(
          'id="pump-status"', `id="pump-status" data-generation="${polls}"`
        );
        return route.fulfill({status: failPoll ? 503 : 200, contentType: "text/html", body: html});
      }
      if (url.pathname.startsWith("/pump/") || url.pathname === "/auto/resume") {
        assert.equal(request.method(), "POST");
        assert.equal(request.headers().accept, "application/json");
        commands.push(url.pathname);
        if (holdCommand) { heldCommand = route; return; }
        return route.fulfill({json: commandResult});
      }
      if (["/static/dashboard.js", "/static/dashboard.css"].includes(url.pathname)) {
        return route.fulfill({
          contentType: url.pathname.endsWith(".js") ? "text/javascript" : "text/css",
          body: fs.readFileSync(path.join(root, "farm", url.pathname), "utf8"),
        });
      }
      return route.abort();
    });

    async function eventually(check) {
      for (let i = 0; i < 200; i++) {
        if (check()) return;
        await new Promise(resolve => setTimeout(resolve, 10));
      }
      assert(check(), "expected browser request did not arrive");
    }
    async function waitForPoll() {
      await eventually(() => polls > 0);
      await page.waitForFunction(n => document.getElementById("pump-status").dataset.generation === String(n), polls);
    }
    async function nextPoll() {
      const before = polls;
      await page.clock.runFor(5001);
      await eventually(() => polls > before);
      await waitForPoll();
    }
    async function settleCommand() {
      await page.waitForFunction(() => !document.querySelector('[aria-busy="true"]'));
      await page.clock.runFor(1);
      await page.waitForFunction(() => document.getElementById("pump-start-label").textContent !== "Waiting for connection");
    }
    const submit = selector => page.locator(selector).evaluate(form => {
      form.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}));
    });

    await page.goto("http://dashboard.test/");
    await page.clock.runFor(1);
    await waitForPoll();
    assert.equal(await page.locator('meta[http-equiv="refresh"]').count(), 0);

    // Scroll/focus must survive a real timed poll, including horizontal tables.
    await page.addStyleTag({content: "html {scroll-behavior:auto} #automation-audit table {min-width:1600px}"});
    const before = await page.evaluate(() => {
      window.savedStop = document.querySelector('form[action="/pump/off"] button');
      window.savedStop.focus({preventScroll: true});
      window.scrollTo(0, document.getElementById("history").offsetTop);
      const table = document.querySelector("#automation-audit .table-wrap");
      table.scrollLeft = 120;
      return {y: scrollY, left: table.scrollLeft};
    });
    fragment = "recovered";
    await nextPoll();
    const after = await page.evaluate(() => ({
      y: scrollY,
      left: document.querySelector("#automation-audit .table-wrap").scrollLeft,
      focus: document.activeElement === window.savedStop,
      same: document.querySelector('form[action="/pump/off"] button') === window.savedStop,
    }));
    assert.equal(after.y, before.y);
    assert.equal(after.left, before.left);
    assert(after.focus && after.same);
    console.log("PASS: polling preserves vertical/horizontal scroll, focus and buttons");

    fragment = "offline";
    await nextPoll();
    assert(await page.locator("#pump-start").isDisabled());
    assert((await page.locator("#sensor-alerts").innerText()).includes("MODBUS sensor offline"));
    assert((await page.locator("#sensor-readings").textContent()).includes("Offline - last known"));
    fragment = "recovered";
    await nextPoll();
    assert.equal(await page.locator("#pump-start").isDisabled(), false);
    assert((await page.locator("#sensor-readings").innerText()).includes("43.2"));
    assert(!(await page.locator("#sensor-alerts").innerText()).includes("MODBUS sensor offline"));
    console.log("PASS: offline/recovery alert, readings and Start eligibility update");

    fragment = "escaped";
    await nextPoll();
    assert.equal(await page.evaluate(() => window.injected), undefined);
    assert.equal(await page.locator("#history-summary script, #validation-history img").count(), 0);
    assert((await page.locator("#history-summary").innerText()).includes("<script>"));
    console.log("PASS: updated Selfcare and rejected payloads stay escaped");

    holdCommand = true;
    await submit('form[action="/pump/on"]');
    await submit('form[action="/pump/on"]');
    await page.waitForFunction(() => document.querySelector('[aria-busy="true"]'));
    // Flush the intercepted request before releasing it.
    await eventually(() => heldCommand);
    assert(heldCommand);
    assert.deepEqual(commands, ["/pump/on"]);
    assert.equal(await page.locator('form[action="/pump/off"] button').isDisabled(), false);
    holdCommand = false;
    await heldCommand.fulfill({json: commandResult});
    await settleCommand();
    assert((await page.locator("#action-status").innerText()).includes(commandResult.reason));
    assert.equal(documents, 1);
    console.log("PASS: command submits once, Stop stays available, no page navigation");

    commandResult = {ok: false, reason: "manual start refused: soil sensor offline"};
    await submit('form[action="/pump/on"]');
    await settleCommand();
    assert.equal(await page.locator("#action-status").innerText(), commandResult.reason);
    assert((await page.locator("#action-status").getAttribute("class")).includes("red-text"));

    fragment = "manual";
    await nextPoll();
    assert(await page.locator("#override-banner").isVisible());
    commandResult = {ok: true, reason: "Automatic control resumed"};
    fragment = "online";
    await submit('form[action="/auto/resume"]');
    await settleCommand();
    assert.equal(await page.locator("#override-banner").isVisible(), false);
    assert.equal(documents, 1);
    console.log("PASS: refusal feedback and Resume work without navigation");

    failPoll = true;
    await page.clock.runFor(5001);
    await page.waitForFunction(() => document.getElementById("update-status").textContent.includes("unavailable"));
    assert(await page.locator("#pump-start").isDisabled());
    assert.equal(await page.locator('form[action="/pump/off"] button').isDisabled(), false);
    assert((await page.locator("#sensor-readings").textContent()).includes("Moisture"));
    failPoll = false;
    await nextPoll();
    assert.equal(await page.locator("#pump-start").isDisabled(), false);
    console.log("PASS: failed update retains values, signals stale state and recovers");

    holdPoll = true;
    await page.clock.runFor(5001);
    await eventually(() => heldPoll);
    const pollCount = polls;
    await page.clock.runFor(5000);
    assert.equal(polls, pollCount, "slow request must not overlap another poll");
    holdPoll = false;
    await submit('form[action="/pump/off"]');
    await settleCommand();
    // The old response contains an offline state; it must never win the race.
    await heldPoll.fulfill({contentType: "text/html", body: fixtures.offline}).catch(() => {});
    assert.equal(await page.locator("#pump-start").isDisabled(), false);
    assert.equal(documents, 1);
    console.log("PASS: slow polls do not overlap or overwrite post-command state");

    holdCommand = true;
    heldCommand = null;
    await submit('form[action="/pump/off"]');
    await eventually(() => heldCommand);
    const commandCount = commands.length;
    await page.clock.runFor(8001);
    await page.waitForFunction(() => document.getElementById("action-status").textContent.includes("not resent"));
    holdCommand = false;
    await page.clock.runFor(5001);
    assert.equal(commands.length, commandCount);
    console.log("PASS: uncertain command outcome is reported, never automatically resent");

    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", {configurable: true, value: true});
      document.dispatchEvent(new Event("visibilitychange"));
    });
    const hiddenPolls = polls;
    await page.clock.runFor(15000);
    assert.equal(polls, hiddenPolls);
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", {configurable: true, value: false});
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await page.clock.runFor(1);
    await eventually(() => polls > hiddenPolls);
    await waitForPoll();
    assert.equal(documents, 1);
    assert.deepEqual(errors, []);
    console.log("PASS: hidden tab pauses polling and returning refreshes immediately");

    const beforeCentral = commands.length;
    fragment = "central_attack";
    await nextPoll();
    assert((await page.locator("#central-monitor").innerText()).includes("999"));
    assert.equal(await page.locator('#central-monitor [role="alert"]').count(), 1);
    assert.equal(await page.locator('#central-monitor svg circle[fill="#c0392b"]').count(), 1);
    assert((await page.locator("#sensor-readings").innerText()).includes("43.2"));
    await page.locator("#central-monitor").scrollIntoViewIfNeeded();
    if (process.env.DASHBOARD_SCREENSHOT) {
      await page.locator("#central-monitor").screenshot({path: process.env.DASHBOARD_SCREENSHOT});
    }
    fragment = "central_corrected";
    await nextPoll();
    assert.equal(await page.locator('#central-monitor [role="alert"]').count(), 0);
    assert((await page.locator("#central-monitor tbody").innerText()).includes("25"));
    // Old rejected values stay on the historical comparison, not as current readings.
    assert.equal(await page.locator('#central-monitor svg circle[fill="#c0392b"]').count(), 1);
    assert.equal(commands.length, beforeCentral, "Central updates must never submit pump commands");
    assert.equal(documents, 1);
    assert.deepEqual(errors, []);
    console.log("PASS: Central UPDATE/alert/chart/correction refresh live without pump commands");
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
