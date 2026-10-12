import { readFileSync } from "node:fs";

// Drives each environment in the manifest through its real GUI and prints one
// JSON report to stdout. The Python driver owns process lifecycle; this file
// only owns browser interaction and assertions.

const [manifestPath] = process.argv.slice(2);
const port = Number(process.env.CDP_PORT || 9333);
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));

async function waitForTarget() {
  let lastError;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const targets = await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json());
      const page = targets.find((target) => target.type === "page");
      if (page?.webSocketDebuggerUrl) return page;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`CDP target not ready: ${lastError || "no page target"}`);
}

const target = await waitForTarget();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  ws.addEventListener("open", resolve, { once: true });
  ws.addEventListener("error", reject, { once: true });
});

let nextId = 0;
const pending = new Map();
let networkFailures = [];
ws.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    const { resolve, reject, timer } = pending.get(message.id);
    clearTimeout(timer);
    pending.delete(message.id);
    if (message.error) reject(new Error(JSON.stringify(message.error)));
    else resolve(message.result);
    return;
  }
  if (message.method === "Network.loadingFailed") networkFailures.push(message.params);
});

function send(method, params = {}) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`timeout: ${method}`));
    }, 30000);
    pending.set(id, { resolve, reject, timer });
    ws.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const response = await send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (response.exceptionDetails) {
    throw new Error(`Runtime.evaluate failed: ${JSON.stringify(response.exceptionDetails)}`);
  }
  return response.result.value;
}

async function waitFor(predicate, label, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await evaluate(`(${predicate.toString()})()`)) return;
    await new Promise((resolve) => setTimeout(resolve, 60));
  }
  throw new Error(`timed out waiting for ${label}`);
}

await send("Runtime.enable");
await send("Page.enable");
await send("Network.enable");
await send("Network.setCacheDisabled", { cacheDisabled: true });
await send("Network.clearBrowserCache");
await send("Emulation.setDeviceMetricsOverride", {
  width: 1440,
  height: 900,
  deviceScaleFactor: 1,
  mobile: false,
});
await send("Page.addScriptToEvaluateOnNewDocument", {
  source:
    "window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.error||e.message)));window.addEventListener('unhandledrejection',e=>window.__errs.push(String(e.reason)));",
});

const results = [];

for (const item of manifest.items) {
  const record = {
    task_id: item.task_id,
    surface: item.surface,
    category: item.category,
    status: item.status,
    passed: false,
    failure: null,
  };
  try {
    networkFailures = [];
    await send("Page.navigate", { url: item.url });
    await waitFor(() => document.querySelectorAll(".record").length > 0, `${item.task_id} records`);
    await evaluate("window.__errs=[]");

    // The surface must actually change the rendered layout, not just a data field.
    const probe = await evaluate(`(()=>{
      const host=document.querySelector('#records');
      return {
        tag:document.querySelector('#surfaceTag')?.textContent||'',
        title:document.querySelector('#appTitle')?.textContent||'',
        cls:host?.className||'',
        rows:document.querySelectorAll('.record').length,
        checkboxes:document.querySelectorAll('.record input[type=checkbox]').length,
        hasNote:!!document.querySelector('[data-testid="care-note"]'),
        statusOptions:[...document.querySelectorAll('[data-testid="workflow-status"] option')].map(o=>o.value)
      };
    })()`);
    record.rendered = probe;

    const layoutOk =
      item.surface === "vitals-dashboard"
        ? probe.cls.includes("cards")
        : item.surface === "clinical-ledger"
          ? probe.cls.includes("ledger")
          : !probe.cls.includes("cards") && !probe.cls.includes("ledger");
    if (!layoutOk) throw new Error(`layout class ${probe.cls} does not match surface ${item.surface}`);
    if (probe.tag !== item.surface) throw new Error(`surface tag ${probe.tag} != ${item.surface}`);
    if (probe.rows !== item.record_count)
      throw new Error(`rendered ${probe.rows} records, expected ${item.record_count}`);
    if (probe.checkboxes !== item.record_count)
      throw new Error(`rendered ${probe.checkboxes} checkboxes, expected ${item.record_count}`);
    if (!probe.hasNote) throw new Error("care note control missing");
    if (!probe.statusOptions.includes(item.status))
      throw new Error(`priority ${item.status} not selectable in the UI`);

    // Start from a clean state, then reload so the UI reflects it.
    await evaluate(
      "fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:'reset'})}).then(r=>r.json())"
    );
    await send("Page.reload", { ignoreCache: true });
    await waitFor(() => document.querySelectorAll(".record").length > 0, `${item.task_id} reload`);
    await evaluate("window.__errs=[]");

    const workflow = `(async()=>{
      const evidenceIds=${JSON.stringify(item.evidence)};
      const noteText=${JSON.stringify(item.note)};
      const statusValue=${JSON.stringify(item.status)};
      const expected=${item.expected_selected};
      const click=selector=>{const el=document.querySelector(selector);if(!el)throw new Error('missing '+selector);el.click()};
      const waitFor=async(predicate,label)=>{const deadline=Date.now()+6000;while(Date.now()<deadline){if(predicate())return;await new Promise(r=>setTimeout(r,50))}throw new Error('timed out waiting for '+label+' (selectedCount='+(document.querySelector('#selectedCount')?.textContent||'?')+', checked='+document.querySelectorAll('.record input:checked').length+')')};
      for(let index=0;index<evidenceIds.length;index+=1){
        click('[data-testid="record-'+evidenceIds[index]+'"]');
        await waitFor(()=>document.querySelector('#selectedCount')?.textContent.startsWith((index+1)+' '),'evidence '+(index+1)+' to register');
      }
      const note=document.querySelector('[data-testid="care-note"]');
      note.value=noteText;
      note.dispatchEvent(new Event('change',{bubbles:true}));
      const status=document.querySelector('[data-testid="workflow-status"]');
      status.value=statusValue;
      status.dispatchEvent(new Event('change',{bubbles:true}));
      await new Promise(r=>setTimeout(r,250));
      click('[data-testid="submit-task"]');
      const deadline=Date.now()+6000;
      while(Date.now()<deadline && !document.querySelector('#result.pass')) await new Promise(r=>setTimeout(r,100));
      return {
        selected:document.querySelector('#selectedCount')?.textContent||'',
        checked:document.querySelectorAll('.record input:checked').length,
        resultClass:document.querySelector('#result')?.className||'',
        resultText:(document.querySelector('#result')?.textContent||'').replace(/\\s+/g,' ').trim(),
        jsErrors:window.__errs||[]
      };
    })()`;
    const outcome = await evaluate(workflow);
    record.outcome = outcome;

    const failures = [];
    if (!outcome.resultClass.includes("pass")) failures.push("result not marked pass");
    if (!outcome.resultText.includes("100%")) failures.push("score is not 100%");
    if (!outcome.resultText.includes("Strict success")) failures.push("not a strict success");
    if (!outcome.selected.startsWith(`${item.expected_selected} `))
      failures.push(`selected count ${outcome.selected} != ${item.expected_selected}`);
    if (outcome.jsErrors.length) failures.push(`js errors: ${outcome.jsErrors.join(" | ")}`);
    if (networkFailures.length) failures.push(`network failures: ${networkFailures.length}`);
    if (failures.length) throw new Error(failures.join("; "));
    record.passed = true;
  } catch (error) {
    record.failure = String(error.message || error);
  }
  results.push(record);
}

const passed = results.filter((result) => result.passed).length;
const report = {
  sampled: results.length,
  passed,
  failed: results.length - passed,
  surfaces: [...new Set(results.map((r) => r.surface))].sort(),
  statuses: [...new Set(results.map((r) => r.status))].sort(),
  categories: [...new Set(results.map((r) => r.category))].sort(),
  results,
};

process.stdout.write(`${JSON.stringify(report)}\n`);
// The Python driver may run several chunks through one browser. Only the last
// chunk should close it; otherwise the next chunk finds no CDP target.
if (process.env.KEEP_BROWSER !== "1") {
  try {
    await send("Browser.close");
  } catch {
    ws.close();
  }
} else {
  try {
    ws.close();
  } catch {
    // best effort
  }
}
