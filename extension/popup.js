/* popup.js — AI Polyglot Kit extension popup logic */

(function () {
  "use strict";

  const statusEl = document.getElementById("status");
  const statusText = document.getElementById("status-text");
  const controlsEl = document.getElementById("controls");
  const langSelect = document.getElementById("lang-select");
  const translateBtn = document.getElementById("translate-btn");
  const progressEl = document.getElementById("progress");

  let isTranslated = false;

  /* ---------- Init ---------- */

  async function init() {
    // Restore saved language
    const { apkLang } = await chrome.storage.local.get("apkLang");
    if (apkLang) langSelect.value = apkLang;

    // Save language on change
    langSelect.addEventListener("change", () => {
      chrome.storage.local.set({ apkLang: langSelect.value });
    });

    // Check health
    const resp = await chrome.runtime.sendMessage({ action: "health" });
    if (resp && resp.connected) {
      setConnected();
      await checkPageState();
    } else {
      setDisconnected();
    }

    // Button handler
    translateBtn.addEventListener("click", onButtonClick);
  }

  /* ---------- Status ---------- */

  function setConnected() {
    statusEl.className = "status connected";
    statusText.textContent = "Connected to AI Polyglot Kit";
    controlsEl.classList.remove("hidden");
  }

  function setDisconnected() {
    statusEl.className = "status disconnected";
    statusText.textContent = "App not running \u2014 launch AI Polyglot Kit";
    controlsEl.classList.add("hidden");
  }

  /* ---------- Page state ---------- */

  async function checkPageState() {
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab || !tab.id) return;

      const resp = await chrome.tabs.sendMessage(tab.id, { action: "getState" });
      if (resp && resp.translated) {
        isTranslated = true;
        setRevertMode();
      } else {
        isTranslated = false;
        setTranslateMode();
      }
    } catch {
      // Content script may not be injected (e.g. chrome:// pages)
      isTranslated = false;
      setTranslateMode();
    }
  }

  /* ---------- Button modes ---------- */

  function setTranslateMode() {
    translateBtn.textContent = "Translate page";
    translateBtn.className = "btn primary";
  }

  function setRevertMode() {
    translateBtn.textContent = "Show original";
    translateBtn.className = "btn revert";
  }

  /* ---------- Actions ---------- */

  async function onButtonClick() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    console.log("[APK:popup] Button click, tab:", tab?.id, "url:", tab?.url);
    if (!tab || !tab.id) {
      console.error("[APK:popup] No active tab!");
      return;
    }

    if (isTranslated) {
      // Revert
      console.log("[APK:popup] Reverting...");
      try {
        await chrome.tabs.sendMessage(tab.id, { action: "revert" });
      } catch (e) {
        console.error("[APK:popup] Revert failed:", e);
      }
      isTranslated = false;
      setTranslateMode();
      progressEl.classList.add("hidden");
    } else {
      // Translate
      console.log("[APK:popup] Translating, lang=", langSelect.value);
      translateBtn.disabled = true;
      progressEl.textContent = "Translating...";
      progressEl.classList.remove("hidden");

      try {
        const result = await chrome.tabs.sendMessage(tab.id, {
          action: "startTranslation",
          lang: langSelect.value,
        });
        console.log("[APK:popup] Content script response:", result);
        isTranslated = true;
        setRevertMode();
        progressEl.textContent = "Done!";
        setTimeout(() => progressEl.classList.add("hidden"), 2000);
      } catch (e) {
        progressEl.textContent = "Error: " + e.message;
        console.error("[APK:popup] Translation failed:", e);
      }

      translateBtn.disabled = false;
    }
  }

  /* ---------- Progress listener ---------- */

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.action === "progress") {
      progressEl.textContent = `Translating batch ${msg.done} of ${msg.total}...`;
      progressEl.classList.remove("hidden");
    }
  });

  /* ---------- Start ---------- */

  init();
})();
