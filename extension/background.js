/* background.js — Service Worker for AI Polyglot Kit extension */

const API_BASE = "http://127.0.0.1:19378";
const BATCH_SIZE = 50;
const MAX_PARALLEL = 3;

/* ---------- Token management ---------- */

async function getToken() {
  const { apkToken } = await chrome.storage.local.get("apkToken");
  if (apkToken) {
    console.log("[APK:bg] Using cached token:", apkToken.slice(0, 8) + "...");
    return apkToken;
  }
  console.log("[APK:bg] No cached token, fetching new one");
  return fetchToken();
}

async function fetchToken() {
  console.log("[APK:bg] Fetching token from", `${API_BASE}/token`);
  const resp = await fetch(`${API_BASE}/token`, { signal: AbortSignal.timeout(5000) });
  if (!resp.ok) throw new Error(`Failed to fetch token: ${resp.status}`);
  const data = await resp.json();
  console.log("[APK:bg] Token response:", JSON.stringify(data));
  const token = data.token || data.access_token || "";
  if (token) await chrome.storage.local.set({ apkToken: token });
  return token;
}

async function clearToken() {
  console.log("[APK:bg] Clearing cached token");
  await chrome.storage.local.remove("apkToken");
}

/* ---------- Health check ---------- */

async function healthCheck() {
  try {
    const resp = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) });
    console.log("[APK:bg] Health check:", resp.ok ? "OK" : resp.status);
    return resp.ok;
  } catch (e) {
    console.log("[APK:bg] Health check failed:", e.message);
    return false;
  }
}

/* ---------- Translation ---------- */

async function translateBatch(texts, lang, token) {
  console.log(`[APK:bg] translateBatch: ${texts.length} texts, lang=${lang}`);
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const body = JSON.stringify({ texts, target_lang: lang });
  console.log("[APK:bg] POST /translate, body length:", body.length);

  const resp = await fetch(`${API_BASE}/translate`, {
    method: "POST",
    headers,
    body,
    signal: AbortSignal.timeout(60000),
  });

  console.log("[APK:bg] /translate response status:", resp.status);

  if (resp.status === 401 || resp.status === 403) {
    console.log("[APK:bg] Auth failed, refreshing token and retrying");
    await clearToken();
    const newToken = await fetchToken();
    const retry = await fetch(`${API_BASE}/translate`, {
      method: "POST",
      headers: { ...headers, Authorization: `Bearer ${newToken}` },
      body,
      signal: AbortSignal.timeout(60000),
    });
    if (!retry.ok) {
      const errText = await retry.text();
      console.error("[APK:bg] Retry failed:", retry.status, errText);
      throw new Error(`Translation failed: ${retry.status}`);
    }
    const retryData = await retry.json();
    console.log("[APK:bg] Retry OK, translations:", retryData.translations?.length);
    return retryData;
  }

  if (!resp.ok) {
    const errText = await resp.text();
    console.error("[APK:bg] Translation failed:", resp.status, errText);
    throw new Error(`Translation failed: ${resp.status} ${errText}`);
  }

  const data = await resp.json();
  console.log("[APK:bg] Translation OK, engine:", data.engine, "count:", data.translations?.length);
  return data;
}

function chunkArray(arr, size) {
  const chunks = [];
  for (let i = 0; i < arr.length; i += size) {
    chunks.push(arr.slice(i, i + size));
  }
  return chunks;
}

async function translateAll(texts, lang) {
  console.log(`[APK:bg] translateAll: ${texts.length} texts, lang=${lang}`);
  const token = await getToken();
  const batches = chunkArray(texts, BATCH_SIZE);
  const results = [];
  let done = 0;
  const total = batches.length;
  console.log(`[APK:bg] Split into ${total} batches of max ${BATCH_SIZE}`);

  // Process batches in groups of MAX_PARALLEL
  for (let i = 0; i < batches.length; i += MAX_PARALLEL) {
    const group = batches.slice(i, i + MAX_PARALLEL);
    const groupResults = await Promise.all(
      group.map((batch) => translateBatch(batch, lang, token))
    );

    for (const res of groupResults) {
      const translated = res.translations || res.texts || res;
      console.log("[APK:bg] Batch result: isArray=", Array.isArray(translated), "length=", translated?.length);
      if (Array.isArray(translated)) {
        results.push(...translated);
      }
      done++;
      // Report progress — fire and forget
      chrome.runtime.sendMessage({ action: "progress", done, total }).catch(() => {});
    }
  }

  console.log(`[APK:bg] translateAll done: ${results.length} results`);
  return results;
}

/* ---------- Message handler ---------- */

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  console.log("[APK:bg] Message received:", msg.action, "from:", sender?.tab?.id || "popup");

  if (msg.action === "health") {
    healthCheck().then((ok) => sendResponse({ connected: ok }));
    return true; // async response
  }

  if (msg.action === "translate") {
    console.log(`[APK:bg] translate request: ${msg.texts?.length} texts, lang=${msg.lang}`);
    translateAll(msg.texts, msg.lang)
      .then((translations) => {
        console.log(`[APK:bg] Sending ${translations.length} translations back`);
        sendResponse({ translations });
      })
      .catch((err) => {
        console.error("[APK:bg] Translation error:", err);
        sendResponse({ error: err.message });
      });
    return true;
  }

  if (msg.action === "clearToken") {
    clearToken().then(() => sendResponse({ ok: true }));
    return true;
  }
});
