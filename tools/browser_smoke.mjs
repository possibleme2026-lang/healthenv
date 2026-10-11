import { writeFileSync } from "node:fs";

const port = Number(process.env.CDP_PORT || 9222);
const targetUrl = process.env.HEALTHENV_URL || "http://127.0.0.1:8765";
const artifact = process.env.HEALTHENV_BROWSER_ARTIFACT || "artifacts/browser_smoke.json";

async function waitForTarget() {
  let lastError;
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try {
      const targets = await fetch(`http://127.0.0.1:${port}/json/list`).then((response) => response.json());
      const page = targets.find((target) => target.type === "page");
      if (page?.webSocketDebuggerUrl) return page;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
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
const failures = [];
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
  if (message.method === "Network.loadingFailed") failures.push(message.params);
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

try {
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
    source: "window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.error||e.message)));window.addEventListener('unhandledrejection',e=>window.__errs.push(String(e.reason)));",
  });
  await send("Page.navigate", { url: targetUrl });
  await evaluate("new Promise(r=>{if(document.readyState==='complete')r();else window.addEventListener('load',r,{once:true})})");
  await evaluate("new Promise(r=>setTimeout(r,800))");
  await evaluate("fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:'reset'})}).then(r=>r.json())");
  await send("Page.reload", { ignoreCache: true });
  await evaluate("new Promise(r=>{if(document.readyState==='complete')r();else window.addEventListener('load',r,{once:true})})");
  await evaluate("new Promise(r=>setTimeout(r,800))");
  const result = await evaluate(`(async()=>{
    const click=selector=>{const el=document.querySelector(selector);if(!el)throw new Error('missing '+selector);el.click()};
    const waitFor=async predicate=>{const deadline=Date.now()+5000;while(Date.now()<deadline){if(predicate())return;await new Promise(r=>setTimeout(r,50))}throw new Error('UI condition timed out')};
    click('[data-testid="record-o2-0607-sleep"]');
    await waitFor(()=>document.querySelector('#selectedCount')?.textContent.startsWith('1 '));
    click('[data-testid="record-o2-0608-sleep"]');
    await waitFor(()=>document.querySelector('#selectedCount')?.textContent.startsWith('2 '));
    const note=document.querySelector('[data-testid="care-note"]');
    note.value='The sleeping upper bound was 2 percentage points higher.';
    note.dispatchEvent(new Event('change',{bubbles:true}));
    const status=document.querySelector('[data-testid="workflow-status"]');
    status.value='review';
    status.dispatchEvent(new Event('change',{bubbles:true}));
    await new Promise(r=>setTimeout(r,300));
    click('[data-testid="submit-task"]');
    const deadline=Date.now()+5000;
    while(Date.now()<deadline && !document.querySelector('#result.pass')) await new Promise(r=>setTimeout(r,100));
    return {
      title:document.title,
      selected:document.querySelector('#selectedCount')?.textContent,
      resultClass:document.querySelector('#result')?.className,
      resultText:document.querySelector('#result')?.textContent.replace(/\\s+/g,' ').trim(),
      jsErrors:window.__errs||[],
      recordCount:document.querySelectorAll('.record').length,
      columns:getComputedStyle(document.querySelector('.grid')).gridTemplateColumns,
      viewport:document.documentElement.clientWidth
    };
  })()`);
  const passed =
    result.resultClass.includes("pass") &&
    result.resultText.includes("100%") &&
    result.resultText.includes("Strict success") &&
    result.selected.startsWith("2 ") &&
    result.jsErrors.length === 0 &&
    failures.length === 0;
  const report = {
    url: targetUrl,
    passed,
    ...result,
    networkFailures: failures,
  };
  writeFileSync(artifact, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.log(JSON.stringify(report, null, 2));
  if (!passed) process.exitCode = 1;
} finally {
  try {
    await send("Browser.close");
  } catch {
    ws.close();
  }
}
