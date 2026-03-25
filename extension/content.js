/* content.js — Content Script for AI Polyglot Kit extension */

(function () {
  "use strict";

  const SKIP_TAGS = new Set([
    "SCRIPT", "STYLE", "CODE", "PRE", "NOSCRIPT",
    "SVG", "CANVAS", "TEXTAREA", "INPUT", "SELECT", "IFRAME",
  ]);

  let translatedState = false; // whether page is currently translated
  let scrollHandler = null;

  /* ---------- Tooltip CSS ---------- */

  function injectTooltipCSS() {
    if (document.getElementById("apk-tooltip-style")) return;
    const style = document.createElement("style");
    style.id = "apk-tooltip-style";
    style.textContent = `
      [data-apk-translated]:hover {
        position: relative;
      }
      [data-apk-translated]:hover::after {
        content: attr(data-apk-original);
        position: absolute;
        bottom: 100%;
        left: 0;
        background: #1a1a1a;
        color: #fff;
        padding: 4px 8px;
        border-radius: 4px;
        font-size: 12px;
        line-height: 1.4;
        white-space: pre-wrap;
        max-width: 320px;
        z-index: 999999;
        pointer-events: none;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
      }
    `;
    document.head.appendChild(style);
  }

  /* ---------- DOM Walker ---------- */

  function collectTextNodes() {
    const nodes = [];
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode(node) {
          // Skip if parent is a skipped tag
          const parent = node.parentElement;
          if (!parent) return NodeFilter.FILTER_REJECT;
          if (SKIP_TAGS.has(parent.tagName)) return NodeFilter.FILTER_REJECT;
          // Skip empty / whitespace-only
          if (!node.textContent.trim()) return NodeFilter.FILTER_REJECT;
          // Skip already translated
          if (parent.hasAttribute("data-apk-translated")) return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        },
      }
    );

    while (walker.nextNode()) {
      nodes.push(walker.currentNode);
    }
    return nodes;
  }

  /* ---------- Viewport detection ---------- */

  function isInViewport(el) {
    const rect = el.getBoundingClientRect();
    return (
      rect.bottom >= 0 &&
      rect.right >= 0 &&
      rect.top <= (window.innerHeight || document.documentElement.clientHeight) &&
      rect.left <= (window.innerWidth || document.documentElement.clientWidth)
    );
  }

  /* ---------- Translation ---------- */

  async function translateVisibleNodes(lang) {
    const allNodes = collectTextNodes();
    console.log("[APK:cs] collectTextNodes:", allNodes.length, "total text nodes");

    const visibleNodes = allNodes.filter((n) => {
      const el = n.parentElement;
      return el && isInViewport(el);
    });
    console.log("[APK:cs] Visible nodes:", visibleNodes.length, "of", allNodes.length);

    if (visibleNodes.length === 0) {
      console.warn("[APK:cs] No visible text nodes found — nothing to translate");
      return;
    }

    const texts = visibleNodes.map((n) => n.textContent);
    console.log("[APK:cs] First 3 texts:", texts.slice(0, 3));
    console.log("[APK:cs] Sending", texts.length, "texts to background, lang=", lang);

    // Send to background for translation
    const response = await chrome.runtime.sendMessage({
      action: "translate",
      texts,
      lang,
    });
    console.log("[APK:cs] Got response from background:", JSON.stringify(response).slice(0, 500));

    if (response.error) {
      console.error("[APK:cs] Translation error:", response.error);
      return;
    }

    const translations = response.translations;
    if (!translations) {
      console.error("[APK:cs] No translations in response:", response);
      return;
    }
    if (translations.length !== visibleNodes.length) {
      console.error("[APK:cs] Count mismatch: got", translations.length, "expected", visibleNodes.length);
      return;
    }

    // Apply translations inline
    let applied = 0;
    let skippedSame = 0;
    let skippedNoParent = 0;
    for (let i = 0; i < visibleNodes.length; i++) {
      const node = visibleNodes[i];
      const parent = node.parentElement;
      if (!parent) { skippedNoParent++; continue; }

      const original = node.textContent;
      const translated = translations[i];

      // Skip if translation is same as original
      if (translated === original) { skippedSame++; continue; }

      // Save original text
      parent.setAttribute("data-apk-original", original);
      parent.setAttribute("data-apk-translated", "true");

      // Replace text
      node.textContent = translated;
      applied++;
    }
    console.log(`[APK:cs] Applied: ${applied}, skipped (same): ${skippedSame}, skipped (no parent): ${skippedNoParent}`);
  }

  /* ---------- Scroll observer ---------- */

  function startScrollObserver(lang) {
    if (scrollHandler) {
      window.removeEventListener("scroll", scrollHandler, true);
    }

    let debounceTimer = null;
    scrollHandler = function () {
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        translateVisibleNodes(lang);
      }, 300);
    };

    window.addEventListener("scroll", scrollHandler, true);
  }

  function stopScrollObserver() {
    if (scrollHandler) {
      window.removeEventListener("scroll", scrollHandler, true);
      scrollHandler = null;
    }
  }

  /* ---------- Revert ---------- */

  function revert() {
    stopScrollObserver();
    translatedState = false;

    const elements = document.querySelectorAll("[data-apk-translated]");
    elements.forEach((el) => {
      const original = el.getAttribute("data-apk-original");
      if (original !== null) {
        // Find the text node and restore
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        const textNode = walker.nextNode();
        if (textNode) {
          textNode.textContent = original;
        }
      }
      el.removeAttribute("data-apk-original");
      el.removeAttribute("data-apk-translated");
    });
  }

  /* ---------- Message listener ---------- */

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    console.log("[APK:cs] Message received:", msg.action);

    if (msg.action === "startTranslation") {
      console.log("[APK:cs] Starting translation, lang=", msg.lang);
      injectTooltipCSS();
      translatedState = true;
      translateVisibleNodes(msg.lang)
        .then(() => {
          console.log("[APK:cs] translateVisibleNodes completed OK");
          startScrollObserver(msg.lang);
          sendResponse({ ok: true });
        })
        .catch((err) => {
          console.error("[APK:cs] translateVisibleNodes FAILED:", err);
          sendResponse({ ok: false, error: err.message });
        });
      return true; // async
    }

    if (msg.action === "revert") {
      revert();
      sendResponse({ ok: true });
      return false;
    }

    if (msg.action === "getState") {
      sendResponse({ translated: translatedState });
      return false;
    }
  });
})();
