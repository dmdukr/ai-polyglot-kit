// ============================================================
// AI Polyglot Kit — Settings SPA (app.js)
// Single-file vanilla JS controller for PyWebView settings UI.
// Communicates with Python backend via window.pywebview.api.
// ============================================================

(function () {
  'use strict';

  // ============================================================
  // 1. INITIALIZATION
  // ============================================================

  /** Whether the pywebview bridge is available. */
  var bridgeReady = false;

  /** Cached reference to the bridge API (or null). */
  var api = null;

  /** Current active page id (e.g. 'general'). */
  var activePage = 'general';

  /** Current language code ('en' | 'uk'). */
  var currentLang = 'en';

  /** Current theme ('dark' | 'light'). */
  var currentTheme = 'dark';

  /** Original English text cache for i18n restore (element -> text). */
  var origTexts = new Map();

  /** Hotkey capture state. */
  var currentHotkeyTarget = null;

  /** Enrollment timer handle. */
  var enrollTimer = null;

  /**
   * Main initialization — called when pywebview bridge is ready
   * or on DOMContentLoaded if bridge is already present.
   */
  function init() {
    if (window.pywebview && window.pywebview.api) {
      bridgeReady = true;
      api = window.pywebview.api;
    }

    setupNavigation();
    setupTheme();
    setupI18n();
    setupModals();
    setupHotkeyCapture();
    setupSliders();
    setupToggles();
    setupDictionary();
    setupReplacements();
    setupPerAppInstructions();
    setupHistory();
    setupSpeakerLock();
    setupAudio();
    setupProviderCards();
    setupBrowserExtension();
    setupOffline();
    setupNetwork();
    setupStats();
    setupFooter();
    setupImportDropZones();

    // Load initial data from backend
    if (bridgeReady) {
      loadConfig();
      loadVersion();
    }

    console.log('[app.js] Settings UI initialized, bridge=' + bridgeReady);
  }

  // Two possible entry points: pywebview bridge or plain DOM ready
  if (window.pywebview && window.pywebview.api) {
    // Bridge already available (rare, but handle it)
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
    } else {
      init();
    }
  } else {
    // Wait for pywebview to inject the bridge
    window.addEventListener('pywebviewready', init);
    // Fallback: if no bridge after 2s, init without it (dev/preview mode)
    setTimeout(function () {
      if (!bridgeReady) {
        console.warn('[app.js] pywebview bridge not available, running in preview mode');
        init();
      }
    }, 2000);
  }


  // ============================================================
  // 2. NAVIGATION
  // ============================================================

  function setupNavigation() {
    var sidebarItems = document.querySelectorAll('.sidebar-item');
    var contentPages = document.querySelectorAll('.content');

    sidebarItems.forEach(function (item) {
      item.addEventListener('click', function () {
        var targetPage = item.dataset.page;
        if (!targetPage) return;

        // Update sidebar active state
        sidebarItems.forEach(function (i) { i.classList.remove('active'); });
        item.classList.add('active');

        // Show target page, hide others
        contentPages.forEach(function (c) { c.classList.remove('active'); });
        var page = document.getElementById('page-' + targetPage);
        if (page) page.classList.add('active');

        activePage = targetPage;

        // Remember last active page
        try {
          localStorage.setItem('apk_last_page', targetPage);
        } catch (e) { /* localStorage may be unavailable in file:// */ }
      });
    });

    // Restore last active page
    try {
      var lastPage = localStorage.getItem('apk_last_page');
      if (lastPage) {
        var target = document.querySelector('.sidebar-item[data-page="' + lastPage + '"]');
        if (target) target.click();
      }
    } catch (e) { /* ignore */ }
  }


  // ============================================================
  // 3. THEME
  // ============================================================

  /** Dynamic stylesheet for pseudo-element styling (Chrome limitation). */
  var dynamicStyle = null;

  function setupTheme() {
    dynamicStyle = document.createElement('style');
    document.head.appendChild(dynamicStyle);

    var themeSelect = document.getElementById('theme-select');
    if (themeSelect) {
      themeSelect.addEventListener('change', function () {
        setTheme(this.value);
      });
    }
  }

  /**
   * Apply theme to the document.
   * @param {string} theme - 'dark' or 'light'
   */
  function setTheme(theme) {
    currentTheme = theme;
    document.documentElement.setAttribute('data-theme', theme);
    document.body.style.background = theme === 'light' ? '#ddd8ce' : '#16161e';

    // Inject CSS for range input pseudo-elements (only way Chrome respects them)
    var track = theme === 'light' ? '#d4cec4' : '#333348';
    var thumb = theme === 'light' ? '#a07010' : '#c49520';
    if (dynamicStyle) {
      dynamicStyle.textContent =
        'input[type="range"]::-webkit-slider-runnable-track{background:' + track + '!important}' +
        'input[type="range"]::-webkit-slider-thumb{background:' + thumb + '!important}';
    }

    try {
      localStorage.setItem('apk_theme', theme);
    } catch (e) { /* ignore */ }
  }


  // ============================================================
  // 4. I18N
  // ============================================================

  /**
   * Slider label translations (Ukrainian).
   * Keys are the English labels used in slider value displays.
   */
  var SLIDER_UK = {
    'Whisper': '\u0428\u0435\u043f\u0456\u0442',
    'Soft': '\u0422\u0438\u0445\u0438\u0439',
    'Quiet': '\u0422\u0438\u0445\u043e',
    'Clear voice': '\u0427\u0456\u0442\u043a\u0438\u0439 \u0433\u043e\u043b\u043e\u0441',
    'Loud': '\u0413\u0443\u0447\u043d\u0438\u0439',
    'Maximum': '\u041c\u0430\u043a\u0441\u0438\u043c\u0443\u043c',
    'Fastest': '\u041d\u0430\u0439\u0448\u0432\u0438\u0434\u0448\u0435',
    'Fast': '\u0428\u0432\u0438\u0434\u043a\u043e',
    'Good': '\u0414\u043e\u0431\u0440\u0435',
    'High': '\u0412\u0438\u0441\u043e\u043a\u0435',
    'Best': '\u041d\u0430\u0439\u043a\u0440\u0430\u0449\u0435',
    'Minimal': '\u041c\u0456\u043d\u0456\u043c\u0430\u043b\u044c\u043d\u0430',
    'Low': '\u041d\u0438\u0437\u044c\u043a\u0430',
    'Medium': '\u0421\u0435\u0440\u0435\u0434\u043d\u044f',
    'Balanced': '\u0417\u0431\u0430\u043b\u0430\u043d\u0441\u043e\u0432\u0430\u043d\u0435',
    'Very high': '\u0414\u0443\u0436\u0435 \u0432\u0438\u0441\u043e\u043a\u0435',
    'Stable': '\u0421\u0442\u0430\u0431\u0456\u043b\u044c\u043d\u043e',
    'Creative': '\u041a\u0440\u0435\u0430\u0442\u0438\u0432\u043d\u043e'
  };

  /** Translation dictionary loaded from the Python bridge. */
  var translations = {};

  function setupI18n() {
    var langSelect = document.getElementById('lang-select');
    if (langSelect) {
      langSelect.addEventListener('change', function () {
        setLang(this.value);
      });
    }
  }

  /**
   * Get slider label in the current language.
   * @param {string} key - English label
   * @returns {string}
   */
  function sliderLabel(key) {
    if (currentLang === 'uk' && SLIDER_UK[key]) return SLIDER_UK[key];
    return key;
  }

  /**
   * Load translations from the Python bridge for the given language.
   * Falls back to the embedded UK dictionary if bridge is unavailable.
   * @param {string} lang
   */
  async function loadTranslations(lang) {
    if (api) {
      try {
        var result = await api.get_translations(lang);
        if (result && typeof result === 'object') {
          translations = result;
          return;
        }
      } catch (e) {
        console.warn('[i18n] Bridge get_translations failed, using built-in fallback:', e);
      }
    }
    // No translations loaded from bridge — the walkAndTranslate function
    // will use data-i18n-uk attributes or origTexts map as fallback
    translations = {};
  }

  /**
   * Walk the DOM and translate all translatable elements.
   * Supports two mechanisms:
   *   1. [data-i18n] attribute: looked up in `translations` dict by key.
   *   2. Text-content matching: English text matched against embedded UK map.
   * @param {string} lang - 'en' or 'uk'
   */
  function walkAndTranslate(lang) {
    // Translate data-i18n keyed elements
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var key = el.getAttribute('data-i18n');
      if (!origTexts.has(el)) {
        origTexts.set(el, el.textContent.trim());
      }
      if (lang === 'en') {
        el.textContent = origTexts.get(el);
      } else if (translations[key]) {
        el.textContent = translations[key];
      }
    });

    // Translate placeholders with data-i18n-placeholder
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function (el) {
      var key = el.getAttribute('data-i18n-placeholder');
      if (!el.dataset.origPlaceholder) {
        el.dataset.origPlaceholder = el.placeholder;
      }
      if (lang === 'en') {
        el.placeholder = el.dataset.origPlaceholder;
      } else if (translations[key]) {
        el.placeholder = translations[key];
      }
    });

    // Also translate plain text elements by selector (mockup compatibility)
    var selectors = [
      '.page-title', '.card-title', '.form-label', '.form-hint',
      '.sidebar-section', '.modal-title', '.btn', '.btn-sm',
      '.btn-primary', '.btn-danger', '.btn-success', '.badge',
      '.stat-label', '.stat-value', '.proc-text', '.filter-chip',
      '.hotkey-capture-hint', '.enrollment-step div', '.model-name',
      '.model-desc', '.model-size', '.banner', '.btn-text',
      '.version-info div', 'option', 'th', '.history-expanded-label',
      '.app-name', '.import-drop div'
    ];

    document.querySelectorAll(selectors.join(',')).forEach(function (el) {
      if (!origTexts.has(el)) {
        origTexts.set(el, el.textContent.trim());
      }
      var original = origTexts.get(el);
      if (!original || el.childElementCount !== 0) return;

      if (lang === 'en') {
        el.textContent = original;
      } else {
        // Try translations dict by text content as key
        var translated = translations[original];
        if (translated) el.textContent = translated;
      }
    });

    // Translate plain placeholders
    document.querySelectorAll('input[placeholder], textarea[placeholder]').forEach(function (el) {
      if (!el.dataset.origPlaceholder) {
        el.dataset.origPlaceholder = el.placeholder;
      }
      var orig = el.dataset.origPlaceholder;
      if (lang === 'en') {
        el.placeholder = orig;
      } else {
        var translated = translations[orig];
        if (translated) el.placeholder = translated;
      }
    });

    // Update html lang attribute
    document.documentElement.lang = lang === 'uk' ? 'uk' : 'en';
  }

  /**
   * Refresh slider value labels after a language change.
   */
  function refreshSliderLabels() {
    var sliderConfigs = [
      { sliderId: 'cpu-slider', valueId: 'cpu-value', labels: ['Low', 'Balanced', 'High', 'Very high', 'Maximum'] },
      { sliderId: 'beam-slider', valueId: 'beam-value', labels: ['Fastest', 'Fast', 'Good', 'High', 'Best'] },
      { sliderId: 'whisper-temp-slider', valueId: 'whisper-temp-value', labels: ['Minimal', 'Low', 'Medium', 'High', 'Maximum'] },
      { sliderId: 'rms-slider', valueId: 'rms-value', labels: ['Whisper', 'Soft', 'Clear voice', 'Loud', 'Maximum'] }
    ];
    sliderConfigs.forEach(function (cfg) {
      var slider = document.getElementById(cfg.sliderId);
      var display = document.getElementById(cfg.valueId);
      if (slider && display) {
        display.textContent = sliderLabel(cfg.labels[slider.value]);
      }
    });
  }

  /**
   * Set the interface language.
   * @param {string} lang - 'en' or 'uk'
   */
  async function setLang(lang) {
    currentLang = lang;
    await loadTranslations(lang);
    walkAndTranslate(lang);
    refreshSliderLabels();

    try {
      localStorage.setItem('apk_lang', lang);
    } catch (e) { /* ignore */ }
  }


  // ============================================================
  // 5. CONFIG BRIDGE
  // ============================================================

  /**
   * Load the full config from the Python backend and populate all form fields.
   */
  async function loadConfig() {
    if (!api) return;
    try {
      var config = await api.get_config();
      if (!config) return;
      populateForm(config);
      console.log('[config] Config loaded from backend');
    } catch (e) {
      console.error('[config] Failed to load config:', e);
      showToast('Failed to load settings', 'error');
    }
  }

  /**
   * Populate all form fields from a config object.
   * @param {Object} config
   */
  function populateForm(config) {
    // -- General --
    if (config.theme) {
      setTheme(config.theme);
      setSelectValue('theme-select', config.theme);
    }
    if (config.language) {
      setSelectValue('lang-select', config.language);
      setLang(config.language);
    }
    if (config.tray_icon_style) {
      setSelectByText('tray-icon-select', config.tray_icon_style);
    }
    setBoolToggle('toggle-autostart', config.autostart);
    setBoolToggle('toggle-start-minimized', config.start_minimized);
    setBoolToggle('toggle-check-updates', config.check_updates);
    setBoolToggle('toggle-telemetry', config.telemetry);

    // Hotkeys
    if (config.hotkeys) {
      setHotkeyDisplay('hotkey-record', config.hotkeys.record);
      setHotkeyDisplay('hotkey-feedback', config.hotkeys.feedback);
      setHotkeyDisplay('hotkey-cancel', config.hotkeys.cancel);
      setHotkeyDisplay('hotkey-paste-last', config.hotkeys.paste_last);
      setHotkeyDisplay('hotkey-translate', config.hotkeys.translate);
      setInputValue('hold-time-input', config.hotkeys.min_hold_ms);
    }

    // Notifications
    setBoolToggle('toggle-sound-feedback', config.sound_feedback);
    setBoolToggle('toggle-show-overlay', config.show_overlay);
    if (config.overlay_position) {
      setSelectByText('overlay-position-select', config.overlay_position);
    }

    // -- Audio --
    if (config.audio) {
      setSelectValue('mic-select', config.audio.device_id);
      setBoolToggle('toggle-auto-switch', config.audio.auto_switch_device);
      setBoolToggle('toggle-rnnoise', config.audio.noise_suppression);
      setBoolToggle('toggle-agc', config.audio.agc);
      setSliderValue('rms-slider', config.audio.target_volume);
      setBoolToggle('toggle-duck', config.audio.duck_other_apps);
      setSliderValue('duck-slider', config.audio.duck_amount);
      setSelectValue('sample-rate-select', config.audio.sample_rate);
      setBoolToggle('toggle-save-recordings', config.audio.save_recordings);
      setInputValue('save-path-input', config.audio.save_path);
      setSelectValue('auto-delete-select', config.audio.auto_delete);
    }

    // -- STT / Dictation --
    if (config.stt) {
      setSelectValue('stt-mode-select', config.stt.mode);
      setSliderValue('beam-slider', config.stt.beam_size);
      setSliderValue('whisper-temp-slider', config.stt.temperature);
      setSliderValue('cpu-slider', config.stt.cpu_usage);
      if (config.stt.vad_sensitivity !== undefined) {
        setSelectValue('vad-select', config.stt.vad_sensitivity);
      }
    }

    // -- LLM --
    if (config.llm) {
      setBoolToggle('toggle-llm-enabled', config.llm.enabled);
      setBoolToggle('toggle-punctuation', config.llm.add_punctuation);
      setBoolToggle('toggle-grammar', config.llm.fix_grammar);
      setBoolToggle('toggle-terminology', config.llm.fix_terminology);
      setBoolToggle('toggle-capitalize', config.llm.capitalize);
      setBoolToggle('toggle-numbers', config.llm.number_formatting);
      setSliderValue('temp-slider', config.llm.temperature);
      setInputValue('max-tokens-input', config.llm.max_tokens);
      setSelectValue('feedback-mode-select', config.llm.feedback_mode);
    }

    // -- Dictation --
    if (config.dictation) {
      setBoolToggle('toggle-context-aware', config.dictation.context_aware);
      setSelectValue('default-style-select', config.dictation.default_style);
      setSelectValue('injection-method-select', config.dictation.injection_method);
      setBoolToggle('toggle-auto-fallback-clipboard', config.dictation.auto_fallback_clipboard);
      setInputValue('typing-speed-input', config.dictation.typing_speed);
      setBoolToggle('toggle-sanitize-terminal', config.dictation.sanitize_terminal);
      setBoolToggle('toggle-confirm-multiline', config.dictation.confirm_multiline_terminal);
    }

    // -- Speaker Lock --
    if (config.speaker_lock) {
      setBoolToggle('toggle-speaker-lock', config.speaker_lock.enabled);
      setSliderValue('speaker-thresh', config.speaker_lock.threshold);
      setSelectValue('speaker-timeout-select', config.speaker_lock.timeout_action);
      setBoolToggle('toggle-log-rejected', config.speaker_lock.log_rejected);
    }

    // -- Translate --
    if (config.translate) {
      setBoolToggle('toggle-page-translation', config.translate.enabled);
      setSelectValue('target-lang-select', config.translate.target_language);
      setBoolToggle('toggle-browser-dictation', config.translate.browser_dictation);
      setBoolToggle('toggle-page-context', config.translate.use_page_context);
    }

    // -- Network --
    if (config.network) {
      setInputValue('stt-timeout-input', config.network.stt_timeout);
      setInputValue('llm-timeout-input', config.network.llm_timeout);
      setInputValue('probe-timeout-input', config.network.probe_timeout);
      setBoolToggle('proxy-toggle', config.network.proxy_enabled);
      setInputValue('proxy-url-input', config.network.proxy_url);
      setInputValue('proxy-user-input', config.network.proxy_username);
      setInputValue('proxy-pass-input', config.network.proxy_password);
      setInputValue('listen-port-input', config.network.listen_port);
    }

    // -- History --
    if (config.history) {
      setBoolToggle('toggle-sensitive-mode', config.history.sensitive_mode);
      setInputValue('retention-input', config.history.retention_days);
      setBoolToggle('toggle-store-raw', config.history.store_raw);
      setBoolToggle('toggle-encrypt-history', config.history.encrypt);
    }

    // -- Offline --
    if (config.offline) {
      setSelectValue('active-stt-model-select', config.offline.active_stt_model);
      setSelectValue('active-llm-model-select', config.offline.active_llm_model);
      setBoolToggle('toggle-verify-integrity', config.offline.verify_integrity);
      setSelectValue('download-source-select', config.offline.download_source);
      setSliderValue('llm-offline-temp-slider', config.offline.llm_temperature);
    }

    refreshSliderLabels();
  }

  /**
   * Collect all form data into a config object for saving.
   * @returns {Object} config data
   */
  function collectFormData() {
    var config = {};

    // -- General --
    config.theme = getSelectValue('theme-select') || currentTheme;
    config.language = getSelectValue('lang-select') || currentLang;
    config.tray_icon_style = getSelectValue('tray-icon-select');
    config.autostart = getBoolToggle('toggle-autostart');
    config.start_minimized = getBoolToggle('toggle-start-minimized');
    config.check_updates = getBoolToggle('toggle-check-updates');
    config.telemetry = getBoolToggle('toggle-telemetry');

    // Hotkeys
    config.hotkeys = {
      record: getHotkeyValue('hotkey-record'),
      feedback: getHotkeyValue('hotkey-feedback'),
      cancel: getHotkeyValue('hotkey-cancel'),
      paste_last: getHotkeyValue('hotkey-paste-last'),
      translate: getHotkeyValue('hotkey-translate'),
      min_hold_ms: getInputInt('hold-time-input', 200)
    };

    // Notifications
    config.sound_feedback = getBoolToggle('toggle-sound-feedback');
    config.show_overlay = getBoolToggle('toggle-show-overlay');
    config.overlay_position = getSelectValue('overlay-position-select');

    // -- Audio --
    config.audio = {
      device_id: getSelectValue('mic-select'),
      auto_switch_device: getBoolToggle('toggle-auto-switch'),
      noise_suppression: getBoolToggle('toggle-rnnoise'),
      agc: getBoolToggle('toggle-agc'),
      target_volume: getSliderInt('rms-slider'),
      duck_other_apps: getBoolToggle('toggle-duck'),
      duck_amount: getSliderInt('duck-slider'),
      sample_rate: getSelectValue('sample-rate-select'),
      save_recordings: getBoolToggle('toggle-save-recordings'),
      save_path: getInputValue('save-path-input'),
      auto_delete: getSelectValue('auto-delete-select')
    };

    // -- STT --
    config.stt = {
      mode: getSelectValue('stt-mode-select'),
      beam_size: getSliderInt('beam-slider'),
      temperature: getSliderInt('whisper-temp-slider'),
      cpu_usage: getSliderInt('cpu-slider'),
      vad_sensitivity: getSelectValue('vad-select')
    };

    // Collect provider cards for STT
    config.stt.providers = collectProviderCards('stt-provider');

    // -- LLM --
    config.llm = {
      enabled: getBoolToggle('toggle-llm-enabled'),
      add_punctuation: getBoolToggle('toggle-punctuation'),
      fix_grammar: getBoolToggle('toggle-grammar'),
      fix_terminology: getBoolToggle('toggle-terminology'),
      capitalize: getBoolToggle('toggle-capitalize'),
      number_formatting: getBoolToggle('toggle-numbers'),
      temperature: getSliderFloat('temp-slider', 100),
      max_tokens: getInputInt('max-tokens-input', 512),
      feedback_mode: getSelectValue('feedback-mode-select')
    };

    // Collect provider cards for LLM
    config.llm.providers = collectProviderCards('llm-provider');

    // -- Dictation --
    config.dictation = {
      context_aware: getBoolToggle('toggle-context-aware'),
      default_style: getSelectValue('default-style-select'),
      injection_method: getSelectValue('injection-method-select'),
      auto_fallback_clipboard: getBoolToggle('toggle-auto-fallback-clipboard'),
      typing_speed: getInputInt('typing-speed-input', 0),
      sanitize_terminal: getBoolToggle('toggle-sanitize-terminal'),
      confirm_multiline_terminal: getBoolToggle('toggle-confirm-multiline')
    };

    // -- Speaker Lock --
    config.speaker_lock = {
      enabled: getBoolToggle('toggle-speaker-lock'),
      threshold: getSliderFloat('speaker-thresh', 100),
      timeout_action: getSelectValue('speaker-timeout-select'),
      log_rejected: getBoolToggle('toggle-log-rejected')
    };

    // -- Translate --
    config.translate = {
      enabled: getBoolToggle('toggle-page-translation'),
      target_language: getSelectValue('target-lang-select'),
      browser_dictation: getBoolToggle('toggle-browser-dictation'),
      use_page_context: getBoolToggle('toggle-page-context')
    };

    // Collect provider cards for Translation
    config.translate.providers = collectProviderCards('translate-provider');

    // -- Network --
    config.network = {
      stt_timeout: getInputInt('stt-timeout-input', 30),
      llm_timeout: getInputInt('llm-timeout-input', 30),
      probe_timeout: getInputInt('probe-timeout-input', 5),
      proxy_enabled: getBoolToggle('proxy-toggle'),
      proxy_url: getInputValue('proxy-url-input'),
      proxy_username: getInputValue('proxy-user-input'),
      proxy_password: getInputValue('proxy-pass-input'),
      listen_port: getInputInt('listen-port-input', 9876)
    };

    // -- History --
    config.history = {
      sensitive_mode: getBoolToggle('toggle-sensitive-mode'),
      retention_days: getInputInt('retention-input', 90),
      store_raw: getBoolToggle('toggle-store-raw'),
      encrypt: getBoolToggle('toggle-encrypt-history')
    };

    // -- Offline --
    config.offline = {
      active_stt_model: getSelectValue('active-stt-model-select'),
      active_llm_model: getSelectValue('active-llm-model-select'),
      verify_integrity: getBoolToggle('toggle-verify-integrity'),
      download_source: getSelectValue('download-source-select'),
      llm_temperature: getSliderFloat('llm-offline-temp-slider', 100)
    };

    return config;
  }

  /**
   * Save the current form data to the Python backend.
   */
  async function saveConfig() {
    if (!api) {
      showToast('Backend not connected', 'error');
      return;
    }
    var data = collectFormData();
    try {
      var result = await api.save_config(data);
      if (result) {
        showToast('Settings saved', 'success');
      } else {
        showToast('Failed to save settings', 'error');
      }
    } catch (e) {
      console.error('[config] Save failed:', e);
      showToast('Error saving settings: ' + e.message, 'error');
    }
  }


  // ============================================================
  // 6. PROVIDER CARDS
  // ============================================================

  function setupProviderCards() {
    // API key visibility toggles
    document.querySelectorAll('.btn-toggle-key').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var field = btn.parentElement.querySelector('.api-key-field');
        if (field) {
          field.type = field.type === 'password' ? 'text' : 'password';
        }
      });
    });

    // API key auto-detect on blur
    document.querySelectorAll('.api-key-field').forEach(function (field) {
      field.addEventListener('blur', function () {
        var key = field.value.trim();
        if (key && api) {
          detectProvider(field, key);
        }
      });
    });

    // Connection status check
    var checkAllBtn = document.getElementById('btn-check-all');
    if (checkAllBtn) {
      checkAllBtn.addEventListener('click', function () {
        checkAllConnections(checkAllBtn);
      });
    }
  }

  /**
   * Detect which provider an API key belongs to.
   * @param {HTMLElement} field - The API key input element
   * @param {string} key - The API key value
   */
  async function detectProvider(field, key) {
    if (!api) return;
    try {
      var result = await api.detect_provider(key);
      var card = field.closest('.provider-card');
      if (!card) return;

      var badge = card.querySelector('.provider-badge');
      if (badge && result) {
        badge.textContent = result.name || 'Unknown';
        badge.className = 'provider-badge' + (result.valid ? ' valid' : ' invalid');
      }

      // Auto-populate model select if provider detected
      if (result && result.provider_id) {
        loadModelsForProvider(card, result.provider_id);
      }
    } catch (e) {
      console.warn('[provider] Detection failed:', e);
    }
  }

  /**
   * Load available models for a detected provider.
   * @param {HTMLElement} card - Provider card element
   * @param {string} providerId - Provider identifier
   */
  async function loadModelsForProvider(card, providerId) {
    if (!api) return;
    try {
      var models = await api.fetch_models(providerId);
      var select = card.querySelector('.model-select');
      if (!select || !models) return;

      // Clear existing options except first placeholder
      while (select.options.length > 1) {
        select.remove(1);
      }

      models.forEach(function (model) {
        var opt = document.createElement('option');
        opt.value = model.id;
        opt.textContent = model.name;
        select.appendChild(opt);
      });
    } catch (e) {
      console.warn('[provider] Failed to load models:', e);
    }
  }

  /**
   * Collect provider card data for a given card group prefix.
   * Cards are expected to have ids like 'stt-provider-1', 'stt-provider-2', etc.
   * @param {string} prefix - e.g. 'stt-provider'
   * @returns {Array} providers in priority order
   */
  function collectProviderCards(prefix) {
    var providers = [];
    for (var i = 1; i <= 3; i++) {
      var card = document.getElementById(prefix + '-' + i);
      if (!card) continue;

      var apiKeyField = card.querySelector('.api-key-field');
      var modelSelect = card.querySelector('.model-select');
      var baseUrlField = card.querySelector('.base-url-field');

      providers.push({
        priority: i,
        api_key: apiKeyField ? apiKeyField.value.trim() : '',
        model: modelSelect ? modelSelect.value : '',
        base_url: baseUrlField ? baseUrlField.value.trim() : ''
      });
    }
    return providers;
  }

  /**
   * Check all provider connections.
   * @param {HTMLElement} btn - The "Check all" button
   */
  async function checkAllConnections(btn) {
    if (!api) return;
    var originalText = btn.textContent;
    btn.textContent = 'Checking...';
    btn.disabled = true;

    try {
      var results = await api.check_connections();
      if (results) {
        // Update connection status badges in the UI
        Object.keys(results).forEach(function (key) {
          var badge = document.getElementById('status-' + key);
          if (badge) {
            badge.textContent = results[key].status;
            badge.className = 'badge ' + (results[key].ok ? 'badge-success' : 'badge-error');
            if (results[key].latency) {
              var latencyEl = badge.parentElement.querySelector('.latency-value');
              if (latencyEl) latencyEl.textContent = results[key].latency + 'ms';
            }
          }
        });
      }
    } catch (e) {
      console.error('[provider] Connection check failed:', e);
    } finally {
      btn.textContent = originalText;
      btn.disabled = false;
    }
  }


  // ============================================================
  // 7. AUDIO
  // ============================================================

  function setupAudio() {
    // Mic test button
    var testBtn = document.getElementById('btn-test-mic');
    if (testBtn) {
      testBtn.addEventListener('click', function () {
        testMicrophone();
      });
    }

    // Refresh mic button
    var refreshBtn = document.getElementById('btn-refresh-mic');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', function () {
        refreshAudioDevices();
      });
    }

    // Load devices on init
    if (bridgeReady) {
      loadAudioDevices();
    }

    // Animate RMS bar (demo/feedback)
    animateRMS();
  }

  /**
   * Load audio devices from the backend and populate the mic select.
   */
  async function loadAudioDevices() {
    if (!api) return;
    try {
      var devices = await api.get_audio_devices();
      var select = document.getElementById('mic-select');
      if (!select || !devices) return;

      // Preserve current selection
      var current = select.value;

      // Clear and repopulate
      while (select.firstChild) {
        select.removeChild(select.firstChild);
      }
      devices.forEach(function (dev) {
        var opt = document.createElement('option');
        opt.value = dev.id || dev.device_id;
        opt.textContent = dev.name + (dev.is_default ? ' (Default)' : '');
        select.appendChild(opt);
      });

      // Restore selection
      if (current) select.value = current;
    } catch (e) {
      console.error('[audio] Failed to load devices:', e);
    }
  }

  /**
   * Refresh audio device list.
   */
  async function refreshAudioDevices() {
    var select = document.getElementById('mic-select');
    if (select) {
      select.style.borderColor = 'var(--accent-highlight)';
      setTimeout(function () { select.style.borderColor = ''; }, 500);
    }
    await loadAudioDevices();
  }

  /**
   * Test the currently selected microphone.
   */
  async function testMicrophone() {
    if (!api) {
      // Fallback animation for preview mode
      simulateRMS(30);
      return;
    }
    try {
      var deviceId = getSelectValue('mic-select');
      await api.test_audio(deviceId);
      // The backend sends RMS levels via a callback; simulate for now
      simulateRMS(30);
    } catch (e) {
      console.error('[audio] Mic test failed:', e);
      showToast('Microphone test failed', 'error');
    }
  }

  /**
   * Simulate RMS level animation for mic test feedback.
   * @param {number} iterations
   */
  function simulateRMS(iterations) {
    var i = 0;
    var interval = setInterval(function () {
      var fill = document.getElementById('rms-fill');
      if (fill) fill.style.width = (30 + Math.random() * 65) + '%';
      if (++i > iterations) clearInterval(interval);
    }, 100);
  }

  /**
   * Background RMS animation for the level bar.
   */
  function animateRMS() {
    var fill = document.getElementById('rms-fill');
    if (fill) fill.style.width = (15 + Math.random() * 55) + '%';
    requestAnimationFrame(function () {
      setTimeout(animateRMS, 100);
    });
  }


  // ============================================================
  // 8. DICTIONARY
  // ============================================================

  function setupDictionary() {
    var addBtn = document.getElementById('btn-add-dict');
    var input = document.getElementById('dict-input');

    if (addBtn) {
      addBtn.addEventListener('click', addDictWord);
    }
    if (input) {
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') addDictWord();
      });
    }

    // Delegated click handler for delete buttons
    document.addEventListener('click', function (e) {
      if (e.target.classList.contains('dict-del')) {
        var item = e.target.closest('.dict-item');
        if (item) {
          var term = item.querySelector('span');
          if (term && api) {
            deleteDictTerm(term.textContent.trim(), item);
          } else if (item) {
            item.remove();
            updateDictCount();
          }
        }
      }
    });

    // Search / filter
    var searchInput = document.getElementById('dict-search');
    if (searchInput) {
      searchInput.addEventListener('input', debounce(function () {
        filterDictionary(searchInput.value);
      }, 300));
    }

    // Import / Export buttons
    var importBtn = document.getElementById('btn-import-dict');
    if (importBtn) {
      importBtn.addEventListener('click', function () {
        openModal('modal-import-dict');
      });
    }

    var exportBtn = document.getElementById('btn-export-dict');
    if (exportBtn) {
      exportBtn.addEventListener('click', exportDictionary);
    }

    // Load dictionary from backend
    if (bridgeReady) {
      loadDictionary();
    }
  }

  /**
   * Load dictionary terms from the backend.
   * @param {string} [query] - Optional search query
   */
  async function loadDictionary(query) {
    if (!api) return;
    try {
      var terms = await api.get_dictionary(query || '');
      renderDictionaryList(terms);
    } catch (e) {
      console.error('[dict] Failed to load dictionary:', e);
    }
  }

  /**
   * Render the dictionary list from an array of term objects.
   * @param {Array} terms
   */
  function renderDictionaryList(terms) {
    var list = document.getElementById('dict-list');
    if (!list) return;

    // Clear existing items
    var items = list.querySelectorAll('.dict-item');
    items.forEach(function (item) { item.remove(); });

    if (!terms || !terms.length) return;

    terms.forEach(function (term) {
      appendDictItem(list, term.word || term.term || term, term.type || 'manual');
    });
    updateDictCount();
  }

  /**
   * Add a word to the dictionary.
   */
  async function addDictWord() {
    var input = document.getElementById('dict-input');
    if (!input) return;
    var word = input.value.trim();
    if (!word) return;

    if (api) {
      try {
        await api.add_dictionary_term(word, word, 'exact');
      } catch (e) {
        console.error('[dict] Failed to add term:', e);
        showToast('Failed to add term', 'error');
        return;
      }
    }

    var list = document.getElementById('dict-list');
    if (list) {
      appendDictItem(list, word, 'manual');
    }
    input.value = '';
    updateDictCount();
  }

  /**
   * Append a dictionary item row to the list using safe DOM methods.
   * @param {HTMLElement} list
   * @param {string} word
   * @param {string} type - 'manual' or 'auto'
   */
  function appendDictItem(list, word, type) {
    var row = document.createElement('div');
    row.className = 'form-row dict-item';
    row.style.padding = '6px 12px';

    var span = document.createElement('span');
    span.textContent = typeof word === 'string' ? word : String(word);

    var typeBadge = document.createElement('span');
    typeBadge.className = 'badge badge-sm';
    typeBadge.textContent = type || 'manual';
    typeBadge.style.marginLeft = '8px';

    var btn = document.createElement('button');
    btn.className = 'btn btn-sm btn-danger dict-del';
    btn.style.marginLeft = 'auto';
    btn.textContent = '\u2715';

    row.appendChild(span);
    row.appendChild(typeBadge);
    row.appendChild(btn);
    list.appendChild(row);
  }

  /**
   * Delete a dictionary term.
   * @param {string} word
   * @param {HTMLElement} itemEl
   */
  async function deleteDictTerm(word, itemEl) {
    if (api) {
      try {
        await api.delete_dictionary_term(word);
      } catch (e) {
        console.error('[dict] Failed to delete term:', e);
        return;
      }
    }
    if (itemEl) {
      itemEl.remove();
      updateDictCount();
    }
  }

  /**
   * Update the dictionary term count display.
   */
  function updateDictCount() {
    var count = document.querySelectorAll('.dict-item').length;
    var el = document.getElementById('dict-count');
    if (el) el.textContent = count + ' terms';
  }

  /**
   * Filter dictionary list by search text.
   * @param {string} query
   */
  function filterDictionary(query) {
    if (api) {
      loadDictionary(query);
      return;
    }
    // Client-side fallback
    var items = document.querySelectorAll('.dict-item');
    var q = query.toLowerCase();
    items.forEach(function (item) {
      var text = item.querySelector('span');
      if (text) {
        item.style.display = text.textContent.toLowerCase().indexOf(q) !== -1 ? '' : 'none';
      }
    });
  }

  /**
   * Export dictionary to JSON.
   */
  async function exportDictionary() {
    if (!api) return;
    try {
      await api.export_dictionary();
      showToast('Dictionary exported', 'success');
    } catch (e) {
      console.error('[dict] Export failed:', e);
      showToast('Export failed', 'error');
    }
  }


  // ============================================================
  // 9. REPLACEMENTS
  // ============================================================

  function setupReplacements() {
    var addBtn = document.getElementById('btn-add-repl');
    if (addBtn) {
      addBtn.addEventListener('click', function () {
        resetReplacementModal();
        var title = document.getElementById('replacement-modal-title');
        if (title) title.textContent = 'Add Replacement';
        openModal('modal-add-replacement');
      });
    }

    // Edit replacement buttons (delegated)
    document.addEventListener('click', function (e) {
      var editBtn = e.target.closest('.btn-edit-repl');
      if (editBtn) {
        openEditReplacement(editBtn);
      }
      var delBtn = e.target.closest('.btn-delete-repl');
      if (delBtn) {
        deleteReplacement(delBtn);
      }
    });

    // Import button
    var importBtn = document.getElementById('btn-import-repl');
    if (importBtn) {
      importBtn.addEventListener('click', function () {
        openModal('modal-import-replacements');
      });
    }

    // Search/filter replacements
    var searchInput = document.getElementById('repl-search');
    if (searchInput) {
      searchInput.addEventListener('input', debounce(function () {
        filterReplacements(searchInput.value);
      }, 300));
    }

    // Save replacement from modal
    var saveReplBtn = document.getElementById('btn-save-replacement');
    if (saveReplBtn) {
      saveReplBtn.addEventListener('click', saveReplacement);
    }

    // Load replacements from backend
    if (bridgeReady) {
      loadReplacements();
    }
  }

  /**
   * Load replacements from the backend.
   */
  async function loadReplacements() {
    if (!api) return;
    try {
      var replacements = await api.get_replacements();
      renderReplacementsTable(replacements);
    } catch (e) {
      console.error('[repl] Failed to load replacements:', e);
    }
  }

  /**
   * Render the replacements table body using safe DOM methods.
   * @param {Array} replacements
   */
  function renderReplacementsTable(replacements) {
    var tbody = document.getElementById('repl-tbody');
    if (!tbody || !replacements) return;
    clearChildren(tbody);

    replacements.forEach(function (repl) {
      var tr = document.createElement('tr');
      tr.dataset.id = repl.id || '';

      var tdTrigger = document.createElement('td');
      tdTrigger.textContent = repl.trigger;
      tr.appendChild(tdTrigger);

      var tdReplacement = document.createElement('td');
      tdReplacement.textContent = repl.replacement || repl.text;
      tr.appendChild(tdReplacement);

      var tdMatch = document.createElement('td');
      tdMatch.textContent = repl.match_mode === 'fuzzy' ? 'Fuzzy' : 'Strict';
      tr.appendChild(tdMatch);

      var tdSensitive = document.createElement('td');
      tdSensitive.textContent = repl.sensitive ? '\uD83D\uDD12' : '';
      tr.appendChild(tdSensitive);

      var tdActions = document.createElement('td');

      var editBtn = document.createElement('button');
      editBtn.className = 'btn btn-sm btn-edit-repl';
      editBtn.textContent = 'Edit';
      editBtn.dataset.id = String(repl.id || '');
      editBtn.dataset.trigger = String(repl.trigger || '');
      editBtn.dataset.text = String(repl.replacement || repl.text || '');
      editBtn.dataset.mode = String(repl.match_mode || 'fuzzy');
      editBtn.dataset.sensitive = repl.sensitive ? 'true' : 'false';
      tdActions.appendChild(editBtn);

      tdActions.appendChild(document.createTextNode(' '));

      var delBtn = document.createElement('button');
      delBtn.className = 'btn btn-sm btn-danger btn-delete-repl';
      delBtn.dataset.id = String(repl.id || '');
      delBtn.textContent = '\u2715';
      tdActions.appendChild(delBtn);

      tr.appendChild(tdActions);
      tbody.appendChild(tr);
    });

    // Update count
    var countEl = document.getElementById('repl-count');
    if (countEl) countEl.textContent = replacements.length + ' replacements';
  }

  /**
   * Reset the replacement modal form to empty state.
   */
  function resetReplacementModal() {
    setInputValue('repl-trigger', '');
    setInputValue('repl-text', '');
    var modeRadios = document.querySelectorAll('input[name="match-mode"]');
    if (modeRadios.length) modeRadios[0].checked = true;
    var sensitive = document.getElementById('repl-sensitive');
    if (sensitive) sensitive.checked = false;
    // Clear edit id
    var modal = document.getElementById('modal-add-replacement');
    if (modal) modal.dataset.editId = '';
  }

  /**
   * Open the edit replacement modal with pre-filled data.
   * @param {HTMLElement} btn
   */
  function openEditReplacement(btn) {
    var titleEl = document.getElementById('replacement-modal-title');
    if (titleEl) titleEl.textContent = 'Edit Replacement';

    setInputValue('repl-trigger', btn.dataset.trigger || '');
    setInputValue('repl-text', btn.dataset.text || '');

    var modeRadios = document.querySelectorAll('input[name="match-mode"]');
    modeRadios.forEach(function (r) {
      r.checked = r.value === (btn.dataset.mode || 'fuzzy');
    });

    var sensitive = document.getElementById('repl-sensitive');
    if (sensitive) sensitive.checked = btn.dataset.sensitive === 'true';

    var modal = document.getElementById('modal-add-replacement');
    if (modal) modal.dataset.editId = btn.dataset.id || '';

    openModal('modal-add-replacement');
  }

  /**
   * Save the current replacement (add or update).
   */
  async function saveReplacement() {
    var trigger = getInputValue('repl-trigger');
    var text = getInputValue('repl-text');
    if (!trigger) return;

    var mode = 'fuzzy';
    var modeRadios = document.querySelectorAll('input[name="match-mode"]');
    modeRadios.forEach(function (r) { if (r.checked) mode = r.value; });

    var sensitive = document.getElementById('repl-sensitive');
    var isSensitive = sensitive ? sensitive.checked : false;

    var modal = document.getElementById('modal-add-replacement');
    var editId = modal ? modal.dataset.editId : '';

    if (api) {
      try {
        await api.save_replacement({
          id: editId || undefined,
          trigger: trigger,
          text: text,
          match_mode: mode,
          sensitive: isSensitive
        });
        await loadReplacements();
        closeModal('modal-add-replacement');
        showToast(editId ? 'Replacement updated' : 'Replacement added', 'success');
      } catch (e) {
        console.error('[repl] Save failed:', e);
        showToast('Failed to save replacement', 'error');
      }
    } else {
      closeModal('modal-add-replacement');
    }
  }

  /**
   * Delete a replacement.
   * @param {HTMLElement} btn
   */
  async function deleteReplacement(btn) {
    var id = btn.dataset.id;
    if (!id) return;
    if (api) {
      try {
        await api.delete_replacement(id);
        var row = btn.closest('tr');
        if (row) row.remove();
        showToast('Replacement deleted', 'success');
      } catch (e) {
        console.error('[repl] Delete failed:', e);
        showToast('Failed to delete replacement', 'error');
      }
    }
  }

  /**
   * Filter replacements table by search text.
   * @param {string} query
   */
  function filterReplacements(query) {
    var rows = document.querySelectorAll('#repl-tbody tr');
    var q = query.toLowerCase();
    rows.forEach(function (row) {
      var text = row.textContent.toLowerCase();
      row.style.display = text.indexOf(q) !== -1 ? '' : 'none';
    });
  }


  // ============================================================
  // 10. PER-APP INSTRUCTIONS
  // ============================================================

  function setupPerAppInstructions() {
    // Add app rule button
    var addAppBtn = document.getElementById('btn-add-app-instr');
    if (addAppBtn) {
      addAppBtn.addEventListener('click', function () {
        openModal('modal-add-app-instruction');
      });
    }

    // New custom script button
    var newScriptBtn = document.getElementById('btn-new-script');
    if (newScriptBtn) {
      newScriptBtn.addEventListener('click', function () {
        openScriptEditor(null);
      });
    }

    // Delegated click for edit script buttons
    document.addEventListener('click', function (e) {
      var editBtn = e.target.closest('.btn-edit-script');
      if (editBtn) {
        openScriptEditor(editBtn.dataset);
      }
      var viewBtn = e.target.closest('.btn-view-preset');
      if (viewBtn) {
        openPresetViewer(viewBtn.dataset);
      }
    });

    // Script editor save button
    var saveScriptBtn = document.getElementById('btn-save-script');
    if (saveScriptBtn) {
      saveScriptBtn.addEventListener('click', saveScript);
    }

    // Character counter for script editor
    var scriptBody = document.getElementById('script-body');
    if (scriptBody) {
      scriptBody.addEventListener('input', function () {
        updateCharCounter(scriptBody);
      });
    }

    // Save app rule from modal
    var saveAppRuleBtn = document.getElementById('btn-save-app-rule');
    if (saveAppRuleBtn) {
      saveAppRuleBtn.addEventListener('click', saveAppRule);
    }

    // Open script editor from app instruction buttons (mockup bindings)
    bindIfExists('btn-app-instr-slack', function () { openModal('modal-edit-script'); });
    bindIfExists('btn-app-instr-code', function () { openModal('modal-edit-script'); });

    // Load data from backend
    if (bridgeReady) {
      loadScripts();
      loadAppRules();
    }
  }

  /**
   * Load scripts from the backend.
   */
  async function loadScripts() {
    if (!api) return;
    try {
      var scripts = await api.get_scripts();
      renderScripts(scripts);
    } catch (e) {
      console.error('[scripts] Failed to load:', e);
    }
  }

  /**
   * Load app rules from the backend.
   */
  async function loadAppRules() {
    if (!api) return;
    try {
      var rules = await api.get_app_rules();
      renderAppRules(rules);
    } catch (e) {
      console.error('[app-rules] Failed to load:', e);
    }
  }

  /**
   * Render scripts lists (presets and custom) using safe DOM methods.
   * @param {Array} scripts
   */
  function renderScripts(scripts) {
    if (!scripts) return;

    var presetList = document.getElementById('preset-scripts-list');
    var customList = document.getElementById('custom-scripts-list');

    if (presetList) {
      clearChildren(presetList);
      scripts.filter(function (s) { return s.builtin; }).forEach(function (s) {
        presetList.appendChild(createScriptRow(s, true));
      });
    }

    if (customList) {
      clearChildren(customList);
      scripts.filter(function (s) { return !s.builtin; }).forEach(function (s) {
        customList.appendChild(createScriptRow(s, false));
      });
    }
  }

  /**
   * Create a script row element using safe DOM methods.
   * @param {Object} script
   * @param {boolean} isPreset
   * @returns {HTMLElement}
   */
  function createScriptRow(script, isPreset) {
    var row = document.createElement('div');
    row.className = 'form-row script-row';
    row.dataset.scriptId = script.id;

    var info = document.createElement('div');
    var nameLabel = document.createElement('div');
    nameLabel.className = 'form-label';
    nameLabel.textContent = script.name;
    var descHint = document.createElement('div');
    descHint.className = 'form-hint';
    descHint.textContent = script.description || '';
    info.appendChild(nameLabel);
    info.appendChild(descHint);

    var actions = document.createElement('div');
    actions.style.display = 'flex';
    actions.style.alignItems = 'center';
    actions.style.gap = '8px';

    if (isPreset) {
      var badge = document.createElement('span');
      badge.className = 'badge';
      badge.textContent = 'Built-in';
      actions.appendChild(badge);

      var viewBtn = document.createElement('button');
      viewBtn.className = 'btn btn-sm btn-view-preset';
      viewBtn.dataset.id = script.id;
      viewBtn.dataset.name = script.name;
      viewBtn.dataset.body = script.body || '';
      viewBtn.textContent = 'View';
      actions.appendChild(viewBtn);
    } else {
      var editBtn = document.createElement('button');
      editBtn.className = 'btn btn-sm btn-edit-script';
      editBtn.dataset.id = script.id;
      editBtn.dataset.name = script.name;
      editBtn.dataset.body = script.body || '';
      editBtn.textContent = 'Edit';
      actions.appendChild(editBtn);

      var delBtn = document.createElement('button');
      delBtn.className = 'btn btn-sm btn-danger';
      delBtn.textContent = '\u2715';
      delBtn.addEventListener('click', function () { deleteScript(script.id); });
      actions.appendChild(delBtn);
    }

    row.appendChild(info);
    row.appendChild(actions);
    return row;
  }

  /**
   * Render app rules list using safe DOM methods.
   * @param {Array} rules
   */
  function renderAppRules(rules) {
    var container = document.getElementById('app-rules-list');
    if (!container || !rules) return;
    clearChildren(container);

    rules.forEach(function (rule) {
      var row = document.createElement('div');
      row.className = 'form-row app-rule-row';
      row.dataset.app = rule.app_name;

      var appNameEl = document.createElement('div');
      appNameEl.className = 'app-name';
      appNameEl.textContent = rule.app_name;
      row.appendChild(appNameEl);

      var scriptNameEl = document.createElement('div');
      scriptNameEl.textContent = rule.script_name || '';
      row.appendChild(scriptNameEl);

      var delBtn = document.createElement('button');
      delBtn.className = 'btn btn-sm btn-danger';
      delBtn.style.marginLeft = 'auto';
      delBtn.textContent = '\u2715';
      delBtn.addEventListener('click', function () { deleteAppRule(rule.app_name, row); });
      row.appendChild(delBtn);

      container.appendChild(row);
    });
  }

  /**
   * Open the script editor modal.
   * @param {Object|null} data - Script data or null for new script
   */
  function openScriptEditor(data) {
    var nameInput = document.getElementById('script-name');
    var bodyInput = document.getElementById('script-body');
    var modal = document.getElementById('modal-edit-script');

    if (nameInput) {
      nameInput.value = data ? (data.name || '') : '';
      nameInput.readOnly = false;
    }
    if (bodyInput) {
      bodyInput.value = data ? (data.body || '') : '';
      bodyInput.readOnly = false;
      updateCharCounter(bodyInput);
    }
    if (modal) modal.dataset.editId = data ? (data.id || '') : '';

    openModal('modal-edit-script');
  }

  /**
   * Open a read-only view of a preset script.
   * @param {Object} data
   */
  function openPresetViewer(data) {
    var nameInput = document.getElementById('script-name');
    var bodyInput = document.getElementById('script-body');

    if (nameInput) {
      nameInput.value = data.name || '';
      nameInput.readOnly = true;
    }
    if (bodyInput) {
      bodyInput.value = data.body || '';
      bodyInput.readOnly = true;
      updateCharCounter(bodyInput);
    }

    openModal('modal-edit-script');
  }

  /**
   * Update the character counter for the script body textarea.
   * @param {HTMLTextAreaElement} textarea
   */
  function updateCharCounter(textarea) {
    var counter = document.getElementById('script-char-counter');
    if (!counter || !textarea) return;
    var len = textarea.value.length;
    var max = parseInt(textarea.getAttribute('maxlength'), 10) || 500;
    counter.textContent = len + '/' + max;
    counter.classList.toggle('over-limit', len >= max);
  }

  /**
   * Save the current script from the editor modal.
   */
  async function saveScript() {
    var nameInput = document.getElementById('script-name');
    var bodyInput = document.getElementById('script-body');
    var modal = document.getElementById('modal-edit-script');

    if (!nameInput || !bodyInput) return;
    var name = nameInput.value.trim();
    var body = bodyInput.value;
    if (!name) {
      showToast('Script name is required', 'error');
      return;
    }

    var editId = modal ? modal.dataset.editId : '';

    if (api) {
      try {
        await api.save_script(editId || null, name, body);
        await loadScripts();
        closeModal('modal-edit-script');
        showToast('Script saved', 'success');
      } catch (e) {
        console.error('[script] Save failed:', e);
        showToast('Failed to save script: ' + e.message, 'error');
      }
    } else {
      closeModal('modal-edit-script');
    }
  }

  /**
   * Delete a custom script.
   * @param {string} scriptId
   */
  async function deleteScript(scriptId) {
    if (!api || !scriptId) return;
    try {
      await api.delete_script(scriptId);
      await loadScripts();
      showToast('Script deleted', 'success');
    } catch (e) {
      console.error('[script] Delete failed:', e);
      showToast('Failed to delete script', 'error');
    }
  }

  /**
   * Save an app rule from the modal.
   */
  async function saveAppRule() {
    var appSelect = document.getElementById('app-rule-app-select');
    var scriptSelect = document.getElementById('app-rule-script-select');
    if (!appSelect || !scriptSelect) return;

    var appName = appSelect.value;
    var scriptId = scriptSelect.value;
    if (!appName || !scriptId) return;

    if (api) {
      try {
        await api.save_app_rule(appName, scriptId);
        await loadAppRules();
        closeModal('modal-add-app-instruction');
        showToast('App rule saved', 'success');
      } catch (e) {
        console.error('[app-rule] Save failed:', e);
        showToast('Failed to save app rule', 'error');
      }
    } else {
      closeModal('modal-add-app-instruction');
    }
  }

  /**
   * Delete an app rule.
   * @param {string} appName
   * @param {HTMLElement} rowEl
   */
  async function deleteAppRule(appName, rowEl) {
    if (api) {
      try {
        await api.delete_app_rule(appName);
      } catch (e) {
        console.error('[app-rule] Delete failed:', e);
        return;
      }
    }
    if (rowEl) rowEl.remove();
  }


  // ============================================================
  // 11. HISTORY
  // ============================================================

  /** Current history pagination offset. */
  var historyOffset = 0;

  /** Number of history items per page. */
  var HISTORY_LIMIT = 50;

  function setupHistory() {
    // Expand history items (delegated)
    document.addEventListener('click', function (e) {
      var item = e.target.closest('.history-item');
      if (item && e.target.tagName !== 'INPUT' && e.target.tagName !== 'BUTTON') {
        var expanded = item.querySelector('.history-expanded');
        if (expanded) expanded.classList.toggle('show');
      }
    });

    // Batch delete checkbox tracking
    document.addEventListener('change', function (e) {
      if (e.target.classList.contains('history-checkbox')) {
        updateBatchDeleteBtn();
      }
    });

    // Batch delete button
    var batchBtn = document.getElementById('batch-delete-btn');
    if (batchBtn) {
      batchBtn.addEventListener('click', function () {
        openModal('modal-confirm-delete-history');
      });
    }

    // Confirm batch delete
    var confirmDeleteBtn = document.getElementById('btn-confirm-delete-history');
    if (confirmDeleteBtn) {
      confirmDeleteBtn.addEventListener('click', batchDeleteHistory);
    }

    // Filter chips
    document.querySelectorAll('.filter-chip').forEach(function (chip) {
      chip.addEventListener('click', function () {
        // Toggle active on this chip; if it's a time filter, deactivate others in the group
        var group = chip.dataset.filterGroup;
        if (group) {
          document.querySelectorAll('.filter-chip[data-filter-group="' + group + '"]').forEach(function (c) {
            if (c !== chip) c.classList.remove('active');
          });
        }
        chip.classList.toggle('active');
        reloadHistory();
      });
    });

    // Search
    var historySearch = document.getElementById('history-search');
    if (historySearch) {
      historySearch.addEventListener('input', debounce(function () {
        historyOffset = 0;
        reloadHistory();
      }, 400));
    }

    // Load more button
    var loadMoreBtn = document.getElementById('btn-load-more');
    if (loadMoreBtn) {
      loadMoreBtn.addEventListener('click', function () {
        historyOffset += HISTORY_LIMIT;
        loadHistory(true);
      });
    }

    // Clear all history
    var clearBtn = document.getElementById('btn-clear-history');
    if (clearBtn) {
      clearBtn.addEventListener('click', function () {
        openModal('modal-confirm-clear-history');
      });
    }

    var confirmClearBtn = document.getElementById('btn-confirm-clear-history');
    if (confirmClearBtn) {
      confirmClearBtn.addEventListener('click', clearAllHistory);
    }

    // History action buttons (delegated)
    document.addEventListener('click', function (e) {
      var copyRaw = e.target.closest('.btn-copy-raw');
      if (copyRaw) {
        copyToClipboard(copyRaw.dataset.text || '');
        showToast('Raw text copied', 'success');
      }
      var copyNorm = e.target.closest('.btn-copy-normalized');
      if (copyNorm) {
        copyToClipboard(copyNorm.dataset.text || '');
        showToast('Normalized text copied', 'success');
      }
      var reNorm = e.target.closest('.btn-re-normalize');
      if (reNorm) {
        reNormalize(reNorm.dataset.id);
      }
    });

    // Load history on init
    if (bridgeReady) {
      loadHistory(false);
    }
  }

  /**
   * Reload history from the beginning with current filters.
   */
  function reloadHistory() {
    historyOffset = 0;
    loadHistory(false);
  }

  /**
   * Load history entries from the backend.
   * @param {boolean} append - If true, append to existing list instead of replacing
   */
  async function loadHistory(append) {
    if (!api) return;

    var query = getInputValue('history-search') || '';
    var filters = getActiveHistoryFilters();

    try {
      var entries = await api.get_history(HISTORY_LIMIT, historyOffset, query, filters);
      renderHistoryEntries(entries, append);
    } catch (e) {
      console.error('[history] Failed to load:', e);
    }
  }

  /**
   * Get currently active history filter values.
   * @returns {Object}
   */
  function getActiveHistoryFilters() {
    var filters = {};
    var activeChips = document.querySelectorAll('.filter-chip.active');
    activeChips.forEach(function (chip) {
      var group = chip.dataset.filterGroup;
      var value = chip.dataset.filterValue;
      if (group && value) {
        filters[group] = value;
      }
    });
    return filters;
  }

  /**
   * Render history entries into the list using safe DOM methods.
   * @param {Array} entries
   * @param {boolean} append
   */
  function renderHistoryEntries(entries, append) {
    var container = document.getElementById('history-list');
    if (!container) return;

    if (!append) clearChildren(container);
    if (!entries || !entries.length) {
      if (!append) {
        var emptyMsg = document.createElement('div');
        emptyMsg.className = 'empty-state';
        emptyMsg.textContent = 'No history entries';
        container.appendChild(emptyMsg);
      }
      // Hide load more button
      var loadMoreBtn = document.getElementById('btn-load-more');
      if (loadMoreBtn) loadMoreBtn.style.display = 'none';
      return;
    }

    entries.forEach(function (entry) {
      container.appendChild(createHistoryItem(entry));
    });

    // Show/hide load more button
    var loadMoreBtnEl = document.getElementById('btn-load-more');
    if (loadMoreBtnEl) {
      loadMoreBtnEl.style.display = entries.length >= HISTORY_LIMIT ? '' : 'none';
    }
  }

  /**
   * Create a history item DOM element using safe DOM methods.
   * @param {Object} entry
   * @returns {HTMLElement}
   */
  function createHistoryItem(entry) {
    var item = document.createElement('div');
    item.className = 'history-item';
    item.dataset.id = entry.id;

    // Header
    var header = document.createElement('div');
    header.className = 'history-header';

    var checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'history-checkbox';
    checkbox.dataset.id = entry.id;
    header.appendChild(checkbox);

    var textDiv = document.createElement('div');
    textDiv.className = 'history-text';
    textDiv.textContent = entry.normalized_text || entry.text || '';
    header.appendChild(textDiv);

    var metaDiv = document.createElement('div');
    metaDiv.className = 'history-meta';

    var appSpan = document.createElement('span');
    appSpan.className = 'app-name';
    appSpan.textContent = entry.app || '';
    metaDiv.appendChild(appSpan);

    var timeSpan = document.createElement('span');
    timeSpan.className = 'history-time';
    timeSpan.textContent = entry.time || '';
    metaDiv.appendChild(timeSpan);

    header.appendChild(metaDiv);

    // Expanded panel
    var expanded = document.createElement('div');
    expanded.className = 'history-expanded';

    var rawDiv = document.createElement('div');
    var rawLabel = document.createElement('span');
    rawLabel.className = 'history-expanded-label';
    rawLabel.textContent = 'Raw STT: ';
    rawDiv.appendChild(rawLabel);
    rawDiv.appendChild(document.createTextNode(entry.raw_text || ''));
    expanded.appendChild(rawDiv);

    var normDiv = document.createElement('div');
    var normLabel = document.createElement('span');
    normLabel.className = 'history-expanded-label';
    normLabel.textContent = 'Normalized: ';
    normDiv.appendChild(normLabel);
    normDiv.appendChild(document.createTextNode(entry.normalized_text || ''));
    expanded.appendChild(normDiv);

    var actionsDiv = document.createElement('div');
    actionsDiv.className = 'history-actions';

    var copyRawBtn = document.createElement('button');
    copyRawBtn.className = 'btn btn-sm btn-copy-raw';
    copyRawBtn.dataset.text = entry.raw_text || '';
    copyRawBtn.textContent = 'Copy raw';
    actionsDiv.appendChild(copyRawBtn);

    var copyNormBtn = document.createElement('button');
    copyNormBtn.className = 'btn btn-sm btn-copy-normalized';
    copyNormBtn.dataset.text = entry.normalized_text || '';
    copyNormBtn.textContent = 'Copy normalized';
    actionsDiv.appendChild(copyNormBtn);

    var reNormBtn = document.createElement('button');
    reNormBtn.className = 'btn btn-sm btn-re-normalize';
    reNormBtn.dataset.id = String(entry.id);
    reNormBtn.textContent = 'Re-normalize';
    actionsDiv.appendChild(reNormBtn);

    expanded.appendChild(actionsDiv);

    item.appendChild(header);
    item.appendChild(expanded);
    return item;
  }

  /**
   * Update the batch delete button visibility and count.
   */
  function updateBatchDeleteBtn() {
    var checked = document.querySelectorAll('.history-checkbox:checked').length;
    var btn = document.getElementById('batch-delete-btn');
    if (btn) btn.style.display = checked > 0 ? 'inline-block' : 'none';
    var countEl = document.getElementById('delete-count');
    if (countEl) countEl.textContent = checked;
  }

  /**
   * Batch delete selected history entries.
   */
  async function batchDeleteHistory() {
    var checkboxes = document.querySelectorAll('.history-checkbox:checked');
    var ids = [];
    checkboxes.forEach(function (cb) { ids.push(cb.dataset.id); });

    if (!ids.length) return;

    if (api) {
      try {
        await api.delete_history(ids);
      } catch (e) {
        console.error('[history] Batch delete failed:', e);
        showToast('Failed to delete entries', 'error');
        closeModal('modal-confirm-delete-history');
        return;
      }
    }

    // Remove from DOM
    ids.forEach(function (id) {
      var item = document.querySelector('.history-item[data-id="' + id + '"]');
      if (item) item.remove();
    });
    updateBatchDeleteBtn();
    closeModal('modal-confirm-delete-history');
    showToast(ids.length + ' entries deleted', 'success');
  }

  /**
   * Clear all history.
   */
  async function clearAllHistory() {
    if (api) {
      try {
        await api.clear_all_history();
      } catch (e) {
        console.error('[history] Clear failed:', e);
        showToast('Failed to clear history', 'error');
        closeModal('modal-confirm-clear-history');
        return;
      }
    }
    var container = document.getElementById('history-list');
    if (container) {
      clearChildren(container);
      var emptyMsg = document.createElement('div');
      emptyMsg.className = 'empty-state';
      emptyMsg.textContent = 'No history entries';
      container.appendChild(emptyMsg);
    }
    closeModal('modal-confirm-clear-history');
    showToast('History cleared', 'success');
  }

  /**
   * Re-normalize a history entry.
   * @param {string} id
   */
  async function reNormalize(id) {
    if (!api || !id) return;
    try {
      var result = await api.re_normalize(id);
      if (result) {
        showToast('Re-normalized successfully', 'success');
        reloadHistory();
      }
    } catch (e) {
      console.error('[history] Re-normalize failed:', e);
      showToast('Re-normalization failed', 'error');
    }
  }


  // ============================================================
  // 12. MODALS
  // ============================================================

  function setupModals() {
    // Close buttons with data-close attribute
    document.querySelectorAll('[data-close]').forEach(function (el) {
      el.addEventListener('click', function () {
        closeModal(el.dataset.close);
      });
    });

    // Open buttons with data-open attribute
    document.querySelectorAll('[data-open]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        openModal(btn.getAttribute('data-open'));
      });
    });

    // Click overlay to close modal
    document.querySelectorAll('.modal-overlay').forEach(function (overlay) {
      overlay.addEventListener('click', function (e) {
        if (e.target === overlay) overlay.classList.remove('show');
      });
    });

    // Escape key to close topmost modal
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        var modals = document.querySelectorAll('.modal-overlay.show');
        if (modals.length) {
          modals[modals.length - 1].classList.remove('show');
        }
      }
    });

    // Wire up specific button -> modal bindings from mockup
    var modalBindings = {
      'btn-add-app': 'modal-add-app',
      'btn-import-config': 'modal-import-config',
      'btn-reenroll': 'modal-enrollment',
      'btn-delete-profile': 'modal-confirm-delete-profile',
      'btn-delete-model': 'modal-confirm-delete-model',
      'btn-download-small': 'modal-download-model',
      'btn-download-large': 'modal-download-model',
      'btn-check-update': 'modal-check-update',
      'btn-check-update-general': 'modal-check-update',
      'btn-reset-all': 'modal-confirm-reset',
      'btn-audit-log': 'modal-audit-log',
      'btn-regen-secret': 'modal-confirm-regen-secret'
    };

    Object.keys(modalBindings).forEach(function (btnId) {
      bindIfExists(btnId, function () {
        openModal(modalBindings[btnId]);
      });
    });

    // Confirmation action buttons
    bindIfExists('btn-confirm-delete-profile', async function () {
      if (api) {
        try {
          await api.delete_speaker_profile();
          showToast('Voice profile deleted', 'success');
        } catch (e) {
          showToast('Failed to delete profile', 'error');
        }
      }
      closeModal('modal-confirm-delete-profile');
    });

    bindIfExists('btn-confirm-reset', async function () {
      if (api) {
        try {
          await api.reset_config();
          await loadConfig();
          showToast('Settings reset to defaults', 'success');
        } catch (e) {
          showToast('Failed to reset settings', 'error');
        }
      }
      closeModal('modal-confirm-reset');
    });

    bindIfExists('btn-confirm-regen-secret', async function () {
      if (api) {
        try {
          var result = await api.regenerate_secret();
          if (result && result.secret) {
            var field = document.getElementById('secret-field');
            if (field) field.value = result.secret;
          }
          showToast('Shared secret regenerated', 'success');
        } catch (e) {
          showToast('Failed to regenerate secret', 'error');
        }
      }
      closeModal('modal-confirm-regen-secret');
    });
  }

  /**
   * Show a modal by its element id.
   * @param {string} id - Modal element id
   */
  function openModal(id) {
    var modal = document.getElementById(id);
    if (modal) modal.classList.add('show');
  }

  /**
   * Hide a modal by its element id.
   * @param {string} id - Modal element id
   */
  function closeModal(id) {
    var modal = document.getElementById(id);
    if (modal) modal.classList.remove('show');
  }


  // ============================================================
  // 13. STATS
  // ============================================================

  function setupStats() {
    if (bridgeReady) {
      loadStats();
    }
  }

  /**
   * Load statistics from the backend and populate stat cards.
   */
  async function loadStats() {
    if (!api) return;
    try {
      var stats = await api.get_stats();
      if (!stats) return;
      populateStats(stats);
    } catch (e) {
      console.error('[stats] Failed to load:', e);
    }
  }

  /**
   * Populate stat cards from data.
   * @param {Object} stats
   */
  function populateStats(stats) {
    // Summary stat cards
    setTextContent('stat-total-words', formatNumber(stats.total_words));
    setTextContent('stat-sessions', formatNumber(stats.sessions));
    setTextContent('stat-time-saved', formatDuration(stats.time_saved_seconds));
    setTextContent('stat-day-streak', stats.day_streak);
    setTextContent('stat-avg-accuracy', stats.avg_accuracy ? stats.avg_accuracy + '%' : '--');
    setTextContent('stat-speaker-rejections', stats.speaker_rejections);
    setTextContent('stat-avg-stt-latency', stats.avg_stt_latency ? stats.avg_stt_latency + 'ms' : '--');
    setTextContent('stat-avg-llm-latency', stats.avg_llm_latency ? stats.avg_llm_latency + 'ms' : '--');

    // Token usage table
    if (stats.token_usage) {
      renderTokenUsageTable(stats.token_usage);
    }

    // Top apps
    if (stats.top_apps) {
      renderTopApps(stats.top_apps);
    }

    // Replacements used
    if (stats.replacements_used) {
      renderReplacementsUsed(stats.replacements_used);
    }
  }

  /**
   * Render the token usage table using safe DOM methods.
   * @param {Array} usage - Array of {key, stt, llm, translate, total, remaining}
   */
  function renderTokenUsageTable(usage) {
    var tbody = document.getElementById('token-usage-tbody');
    if (!tbody) return;
    clearChildren(tbody);

    usage.forEach(function (row) {
      var tr = document.createElement('tr');

      var cells = [
        maskApiKey(row.key),
        formatNumber(row.stt),
        formatNumber(row.llm),
        formatNumber(row.translate),
        formatNumber(row.total),
        row.remaining === -1 ? 'Unlimited' : formatNumber(row.remaining)
      ];

      cells.forEach(function (cellText) {
        var td = document.createElement('td');
        td.textContent = cellText;
        tr.appendChild(td);
      });

      tbody.appendChild(tr);
    });
  }

  /**
   * Render top applications list using safe DOM methods.
   * @param {Array} apps
   */
  function renderTopApps(apps) {
    var container = document.getElementById('top-apps-list');
    if (!container) return;
    clearChildren(container);

    apps.forEach(function (app) {
      var row = document.createElement('div');
      row.className = 'stat-bar-row';

      var nameSpan = document.createElement('span');
      nameSpan.className = 'app-name';
      nameSpan.textContent = app.name;
      row.appendChild(nameSpan);

      var barDiv = document.createElement('div');
      barDiv.className = 'stat-bar';
      var fillDiv = document.createElement('div');
      fillDiv.className = 'stat-bar-fill';
      fillDiv.style.width = (app.percentage || 0) + '%';
      barDiv.appendChild(fillDiv);
      row.appendChild(barDiv);

      var valueSpan = document.createElement('span');
      valueSpan.className = 'stat-bar-value';
      valueSpan.textContent = formatNumber(app.words) + ' words';
      row.appendChild(valueSpan);

      container.appendChild(row);
    });
  }

  /**
   * Render replacements used list using safe DOM methods.
   * @param {Array} replacements
   */
  function renderReplacementsUsed(replacements) {
    var container = document.getElementById('replacements-used-list');
    if (!container) return;
    clearChildren(container);

    replacements.forEach(function (repl) {
      var row = document.createElement('div');
      row.className = 'stat-bar-row';

      var triggerSpan = document.createElement('span');
      triggerSpan.textContent = repl.trigger;
      row.appendChild(triggerSpan);

      var countSpan = document.createElement('span');
      countSpan.className = 'stat-bar-value';
      countSpan.textContent = repl.count + ' times';
      row.appendChild(countSpan);

      container.appendChild(row);
    });
  }


  // ============================================================
  // 14. BROWSER EXTENSION
  // ============================================================

  function setupBrowserExtension() {
    // Rescan browsers button
    bindIfExists('btn-rescan-browsers', function () {
      loadBrowsers();
    });

    // Install extension buttons (delegated)
    document.addEventListener('click', function (e) {
      var installBtn = e.target.closest('.btn-install-extension');
      if (installBtn) {
        installExtension(installBtn.dataset.browser);
      }
    });

    // Secret field visibility toggle
    var toggleSecretBtn = document.getElementById('btn-toggle-secret');
    if (toggleSecretBtn) {
      toggleSecretBtn.addEventListener('click', function () {
        var field = document.getElementById('secret-field');
        if (field) field.type = field.type === 'password' ? 'text' : 'password';
      });
    }

    // Load browsers on init
    if (bridgeReady) {
      loadBrowsers();
    }
  }

  /**
   * Load detected browsers from the backend.
   */
  async function loadBrowsers() {
    if (!api) return;
    try {
      var browsers = await api.find_browsers();
      renderBrowserList(browsers);
    } catch (e) {
      console.error('[ext] Failed to find browsers:', e);
    }
  }

  /**
   * Render the browser list with install status using safe DOM methods.
   * @param {Array} browsers
   */
  function renderBrowserList(browsers) {
    var container = document.getElementById('browser-list');
    if (!container || !browsers) return;
    clearChildren(container);

    browsers.forEach(function (browser) {
      var row = document.createElement('div');
      row.className = 'form-row browser-row';

      var labelDiv = document.createElement('div');
      labelDiv.className = 'form-label';
      labelDiv.textContent = browser.name;
      row.appendChild(labelDiv);

      var actionsDiv = document.createElement('div');
      actionsDiv.style.display = 'flex';
      actionsDiv.style.alignItems = 'center';
      actionsDiv.style.gap = '8px';

      var installed = browser.extension_installed;

      var badge = document.createElement('span');
      badge.className = 'badge' + (installed ? ' badge-success' : '');
      badge.textContent = installed ? 'Installed' : 'Not installed';
      actionsDiv.appendChild(badge);

      var installBtn = document.createElement('button');
      installBtn.className = 'btn btn-sm btn-install-extension';
      installBtn.dataset.browser = browser.id;
      installBtn.textContent = installed ? 'Reinstall' : 'Install';
      actionsDiv.appendChild(installBtn);

      row.appendChild(actionsDiv);
      container.appendChild(row);
    });
  }

  /**
   * Install the extension into a browser.
   * @param {string} browserId
   */
  async function installExtension(browserId) {
    if (!api || !browserId) return;
    try {
      var result = await api.install_extension(browserId);
      if (result && result.success) {
        showToast('Extension installed in ' + (result.browser_name || browserId), 'success');
        await loadBrowsers();
      } else {
        // Show install instructions modal
        openModal('modal-install-extension');
      }
    } catch (e) {
      console.error('[ext] Install failed:', e);
      showToast('Extension install failed', 'error');
    }
  }


  // ============================================================
  // 15. FOOTER
  // ============================================================

  function setupFooter() {
    // Cancel button
    var cancelBtn = document.getElementById('btn-cancel');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', function () {
        window.close();
      });
    }

    // Save button
    var saveBtn = document.getElementById('btn-save');
    if (saveBtn) {
      saveBtn.addEventListener('click', function () {
        saveConfig();
      });
    }
  }

  /**
   * Load and display the app version.
   */
  async function loadVersion() {
    if (!api) return;
    try {
      var info = await api.get_version();
      if (!info) return;

      var versionEl = document.getElementById('version-text');
      if (versionEl) versionEl.textContent = 'v' + (info.version || '');

      if (info.update_available) {
        var badge = document.getElementById('update-badge');
        if (badge) {
          badge.textContent = 'v' + info.latest + ' available';
          badge.style.display = '';
        }
      }
    } catch (e) {
      console.warn('[version] Failed to load:', e);
    }
  }


  // ============================================================
  // ADDITIONAL FEATURE SETUP
  // ============================================================

  /**
   * Setup slider input handlers with value displays.
   */
  function setupSliders() {
    var rmsLabels = ['Whisper', 'Soft', 'Clear voice', 'Loud', 'Maximum'];
    var beamLabels = ['Fastest', 'Fast', 'Good', 'High', 'Best'];
    var tempLabels = ['Minimal', 'Low', 'Medium', 'High', 'Maximum'];
    var cpuLabels = ['Low', 'Balanced', 'High', 'Very high', 'Maximum'];

    bindSlider('rms-slider', 'rms-value', function (val) { return sliderLabel(rmsLabels[val]); });
    bindSlider('duck-slider', 'duck-value', function (val) { return val + '%'; });
    bindSlider('temp-slider', 'temp-value', function (val) { return (val / 100).toFixed(1); });
    bindSlider('llm-offline-temp-slider', 'llm-offline-temp-value', function (val) { return (val / 100).toFixed(1); });
    bindSlider('beam-slider', 'beam-value', function (val) { return sliderLabel(beamLabels[val]); });
    bindSlider('whisper-temp-slider', 'whisper-temp-value', function (val) { return sliderLabel(tempLabels[val]); });
    bindSlider('cpu-slider', 'cpu-value', function (val) { return sliderLabel(cpuLabels[val]); });
    bindSlider('speaker-thresh', 'speaker-thresh-val', function (val) { return (val / 100).toFixed(2); });
  }

  /**
   * Bind a slider input to update a value display element.
   * @param {string} sliderId
   * @param {string} valueId
   * @param {Function} formatter
   */
  function bindSlider(sliderId, valueId, formatter) {
    var slider = document.getElementById(sliderId);
    if (slider) {
      slider.addEventListener('input', function () {
        var display = document.getElementById(valueId);
        if (display) display.textContent = formatter(this.value);
      });
    }
  }

  /**
   * Setup toggle switch interactions.
   */
  function setupToggles() {
    // Proxy toggle -> show/hide proxy fields
    var proxyToggle = document.getElementById('proxy-toggle');
    if (proxyToggle) {
      proxyToggle.addEventListener('change', function () {
        var fields = document.getElementById('proxy-fields');
        if (fields) fields.style.display = this.checked ? 'block' : 'none';
      });
    }
  }

  /**
   * Setup hotkey capture modal.
   */
  function setupHotkeyCapture() {
    // Clicking a hotkey button opens the capture modal
    document.querySelectorAll('.hotkey-input').forEach(function (el) {
      el.addEventListener('click', function () {
        currentHotkeyTarget = el;
        var actionName = document.getElementById('hotkey-action-name');
        if (actionName) actionName.textContent = el.dataset.action || '';
        var display = document.getElementById('hotkey-display');
        if (display) display.textContent = '\u2014';
        openModal('modal-hotkey');
      });
    });

    // Apply hotkey button
    bindIfExists('btn-apply-hotkey', function () {
      var display = document.getElementById('hotkey-display');
      if (currentHotkeyTarget && display && display.textContent !== '\u2014') {
        currentHotkeyTarget.textContent = display.textContent;
        currentHotkeyTarget.dataset.key = display.textContent;
      }
      closeModal('modal-hotkey');
    });

    // Listen for key combos in hotkey capture modal
    document.addEventListener('keydown', function (e) {
      var modal = document.getElementById('modal-hotkey');
      if (!modal || !modal.classList.contains('show')) return;

      e.preventDefault();
      e.stopPropagation();

      if (e.key === 'Escape') {
        closeModal('modal-hotkey');
        return;
      }
      if (e.key === 'Backspace') {
        var hotkeyDisplay = document.getElementById('hotkey-display');
        if (hotkeyDisplay) hotkeyDisplay.textContent = '\u2014';
        return;
      }

      var combo = [];
      if (e.ctrlKey) combo.push('Ctrl');
      if (e.altKey) combo.push('Alt');
      if (e.shiftKey) combo.push('Shift');
      if (['Control', 'Alt', 'Shift', 'Meta'].indexOf(e.key) === -1) {
        combo.push(e.key.length === 1 ? e.key.toUpperCase() : e.key);
      }
      if (combo.length) {
        var hotkeyDisplay = document.getElementById('hotkey-display');
        if (hotkeyDisplay) hotkeyDisplay.textContent = combo.join('+');
      }
    });
  }

  /**
   * Setup Speaker Lock enrollment flow.
   */
  function setupSpeakerLock() {
    // Start enrollment
    bindIfExists('btn-start-enroll', function () {
      var step1 = document.getElementById('enroll-step-1');
      var step2 = document.getElementById('enroll-step-2');
      if (step1) step1.style.display = 'none';
      if (step2) step2.style.display = 'block';

      if (api) {
        try { api.enroll_speaker(); } catch (e) { /* ignore */ }
      }

      var sec = 0;
      enrollTimer = setInterval(function () {
        sec++;
        var m = Math.floor(sec / 60);
        var s = sec % 60;
        var timerEl = document.getElementById('enroll-timer');
        if (timerEl) timerEl.textContent = m + ':' + String(s).padStart(2, '0');
        var rms = document.getElementById('enroll-rms');
        if (rms) rms.style.width = (20 + Math.random() * 60) + '%';
      }, 1000);
    });

    // Stop enrollment
    bindIfExists('btn-stop-enroll', function () {
      clearInterval(enrollTimer);
      var step2 = document.getElementById('enroll-step-2');
      var step3 = document.getElementById('enroll-step-3');
      if (step2) step2.style.display = 'none';
      if (step3) step3.style.display = 'block';
    });
  }

  /**
   * Setup offline model management.
   */
  function setupOffline() {
    // Detect & recommend button
    bindIfExists('btn-detect-system', async function () {
      if (!api) return;
      try {
        var result = await api.detect_system();
        if (result) {
          showToast('System detected: ' + (result.summary || ''), 'success');
        }
      } catch (e) {
        showToast('Detection failed', 'error');
      }
    });

    // Download model button in modal
    var downloadBtn = document.getElementById('btn-start-download');
    if (downloadBtn) {
      downloadBtn.addEventListener('click', function () {
        startModelDownload(downloadBtn);
      });
    }

    // Delete model confirmation
    bindIfExists('btn-confirm-delete-model', async function () {
      var modalEl = document.getElementById('modal-confirm-delete-model');
      var modelId = modalEl ? modalEl.dataset.modelId : null;
      if (api && modelId) {
        try {
          await api.delete_model(modelId);
          showToast('Model deleted', 'success');
        } catch (e) {
          showToast('Failed to delete model', 'error');
        }
      }
      closeModal('modal-confirm-delete-model');
    });
  }

  /**
   * Start a model download with progress simulation.
   * @param {HTMLElement} btn
   */
  async function startModelDownload(btn) {
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = 'Downloading...';

    var modelId = btn.dataset.modelId || '';

    if (api) {
      try {
        // The real download happens on the Python side; we monitor progress
        await api.download_model(modelId);
        var statusEl = document.getElementById('download-status');
        if (statusEl) {
          statusEl.textContent = 'Download complete!';
          statusEl.style.color = 'var(--success)';
        }
        btn.textContent = 'Done';
        btn.disabled = false;
        return;
      } catch (e) {
        console.error('[offline] Download failed:', e);
        showToast('Download failed: ' + e.message, 'error');
        btn.textContent = 'Retry';
        btn.disabled = false;
        return;
      }
    }

    // Simulation fallback for preview mode
    var pct = 0;
    var interval = setInterval(function () {
      pct += Math.random() * 8;
      if (pct >= 100) {
        pct = 100;
        clearInterval(interval);
        var statusEl = document.getElementById('download-status');
        if (statusEl) statusEl.textContent = 'Verifying SHA-256...';
        setTimeout(function () {
          var statusDone = document.getElementById('download-status');
          if (statusDone) {
            statusDone.textContent = 'Download complete!';
            statusDone.style.color = 'var(--success)';
          }
          btn.textContent = 'Done';
          btn.disabled = false;
        }, 1500);
      }
      var progress = document.getElementById('download-progress');
      if (progress) progress.style.width = pct + '%';
      var pctEl = document.getElementById('download-pct');
      if (pctEl) pctEl.textContent = Math.floor(pct) + '%';
      if (pct < 100) {
        var speed = (2 + Math.random() * 5).toFixed(1);
        var statusEl = document.getElementById('download-status');
        if (statusEl) statusEl.textContent = 'Downloading... ' + speed + ' MB/s';
      }
    }, 300);
  }

  /**
   * Setup network page interactions.
   */
  function setupNetwork() {
    // No additional setup needed — proxy toggle handled in setupToggles(),
    // check connections button handled in setupProviderCards()
  }

  /**
   * Setup import drop zones with visual feedback.
   */
  function setupImportDropZones() {
    document.querySelectorAll('.import-drop').forEach(function (drop) {
      // Click to browse
      drop.addEventListener('click', function () {
        if (api) {
          // Bridge handles file picker
          handleImportDrop(drop);
        } else {
          // Visual feedback for preview mode
          drop.style.borderColor = 'var(--success)';
          drop.style.background = 'rgba(76,175,80,0.05)';
          var textEl = drop.querySelector('div:nth-child(2)');
          if (textEl) textEl.textContent = 'File selected (preview)';
        }
      });

      // Drag and drop
      drop.addEventListener('dragover', function (e) {
        e.preventDefault();
        drop.classList.add('drag-over');
      });
      drop.addEventListener('dragleave', function () {
        drop.classList.remove('drag-over');
      });
      drop.addEventListener('drop', function (e) {
        e.preventDefault();
        drop.classList.remove('drag-over');
        handleImportDrop(drop);
      });
    });
  }

  /**
   * Handle file import from a drop zone.
   * @param {HTMLElement} dropZone
   */
  async function handleImportDrop(dropZone) {
    // The actual file handling is done by the Python bridge
    // which opens a native file dialog
    var importType = dropZone.dataset.importType;
    if (!api || !importType) return;

    try {
      var result;
      if (importType === 'replacements') {
        result = await api.import_replacements();
      } else if (importType === 'dictionary') {
        result = await api.import_dictionary();
      } else if (importType === 'config') {
        result = await api.import_config();
      }
      if (result && result.success) {
        showToast('Import successful', 'success');
        dropZone.style.borderColor = 'var(--success)';
      }
    } catch (e) {
      console.error('[import] Failed:', e);
      showToast('Import failed', 'error');
    }
  }


  // ============================================================
  // 16. UTILITY FUNCTIONS
  // ============================================================

  /**
   * Debounce a function call.
   * @param {Function} fn
   * @param {number} delay - Milliseconds
   * @returns {Function}
   */
  function debounce(fn, delay) {
    var timer = null;
    return function () {
      var context = this;
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(context, args);
      }, delay);
    };
  }

  /**
   * Format a number with locale-aware separators.
   * @param {number} n
   * @returns {string}
   */
  function formatNumber(n) {
    if (n === undefined || n === null) return '--';
    return Number(n).toLocaleString();
  }

  /**
   * Format seconds into a human-readable duration (e.g. "2h 15m").
   * @param {number} seconds
   * @returns {string}
   */
  function formatDuration(seconds) {
    if (!seconds || seconds <= 0) return '0m';
    var h = Math.floor(seconds / 3600);
    var m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return h + 'h ' + m + 'm';
    return m + 'm';
  }

  /**
   * Format bytes into a human-readable size.
   * @param {number} bytes
   * @returns {string}
   */
  function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    var units = ['B', 'KB', 'MB', 'GB', 'TB'];
    var i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + units[i];
  }

  /**
   * Mask an API key for display (show first 4 and last 4 chars).
   * @param {string} key
   * @returns {string}
   */
  function maskApiKey(key) {
    if (!key || key.length < 12) return key || '';
    return key.substring(0, 4) + '...' + key.substring(key.length - 4);
  }

  /**
   * Copy text to the clipboard.
   * @param {string} text
   */
  function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(function () {
        fallbackCopyToClipboard(text);
      });
    } else {
      fallbackCopyToClipboard(text);
    }
  }

  /**
   * Fallback clipboard copy using a temporary textarea.
   * @param {string} text
   */
  function fallbackCopyToClipboard(text) {
    var textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand('copy');
    } catch (e) { /* ignore */ }
    document.body.removeChild(textarea);
  }

  /**
   * Show a toast notification.
   * @param {string} message
   * @param {string} type - 'success', 'error', or 'info'
   */
  function showToast(message, type) {
    var container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.style.cssText =
        'position:fixed;top:16px;right:16px;z-index:10000;display:flex;flex-direction:column;gap:8px;pointer-events:none;';
      document.body.appendChild(container);
    }

    var borderColor = '#c49520';
    if (type === 'error') borderColor = '#f44336';
    if (type === 'success') borderColor = '#4caf50';

    var toast = document.createElement('div');
    toast.className = 'toast toast-' + (type || 'info');
    toast.style.cssText =
      'padding:10px 18px;border-radius:8px;font-size:13px;pointer-events:auto;' +
      'opacity:0;transform:translateX(20px);transition:all 0.3s ease;' +
      'background:var(--card-bg, #1e1e2e);border:1px solid ' + borderColor + ';' +
      'color:var(--text-primary, #e0dcd3);box-shadow:0 4px 12px rgba(0,0,0,0.3);';
    toast.textContent = message;

    container.appendChild(toast);

    // Animate in
    requestAnimationFrame(function () {
      toast.style.opacity = '1';
      toast.style.transform = 'translateX(0)';
    });

    // Auto-dismiss
    setTimeout(function () {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(20px)';
      setTimeout(function () {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 300);
    }, 3000);
  }

  /**
   * Remove all child nodes from an element.
   * @param {HTMLElement} el
   */
  function clearChildren(el) {
    while (el.firstChild) {
      el.removeChild(el.firstChild);
    }
  }


  // ---- Form helpers ----

  /**
   * Set a select element's value by id.
   * @param {string} id
   * @param {*} value
   */
  function setSelectValue(id, value) {
    var el = document.getElementById(id);
    if (el && value !== undefined) el.value = value;
  }

  /**
   * Set a select element's value by matching option text.
   * @param {string} id
   * @param {string} text
   */
  function setSelectByText(id, text) {
    var el = document.getElementById(id);
    if (!el || !text) return;
    for (var i = 0; i < el.options.length; i++) {
      if (el.options[i].textContent.trim() === text) {
        el.selectedIndex = i;
        return;
      }
    }
  }

  /**
   * Get a select element's value by id.
   * @param {string} id
   * @returns {string}
   */
  function getSelectValue(id) {
    var el = document.getElementById(id);
    return el ? el.value : '';
  }

  /**
   * Set an input element's value by id.
   * @param {string} id
   * @param {*} value
   */
  function setInputValue(id, value) {
    var el = document.getElementById(id);
    if (el && value !== undefined) el.value = value;
  }

  /**
   * Get an input element's value by id.
   * @param {string} id
   * @returns {string}
   */
  function getInputValue(id) {
    var el = document.getElementById(id);
    return el ? el.value : '';
  }

  /**
   * Get an input element's integer value.
   * @param {string} id
   * @param {number} fallback
   * @returns {number}
   */
  function getInputInt(id, fallback) {
    var val = parseInt(getInputValue(id), 10);
    return isNaN(val) ? (fallback || 0) : val;
  }

  /**
   * Set a toggle/checkbox by its container id.
   * @param {string} id - Container element id
   * @param {boolean} checked
   */
  function setBoolToggle(id, checked) {
    var el = document.getElementById(id);
    if (el) {
      var input = el.tagName === 'INPUT' ? el : el.querySelector('input[type="checkbox"]');
      if (input && checked !== undefined) input.checked = !!checked;
    }
  }

  /**
   * Get a toggle/checkbox state by its container id.
   * @param {string} id
   * @returns {boolean}
   */
  function getBoolToggle(id) {
    var el = document.getElementById(id);
    if (el) {
      var input = el.tagName === 'INPUT' ? el : el.querySelector('input[type="checkbox"]');
      return input ? input.checked : false;
    }
    return false;
  }

  /**
   * Set a slider (range input) value by id.
   * @param {string} id
   * @param {*} value
   */
  function setSliderValue(id, value) {
    var el = document.getElementById(id);
    if (el && value !== undefined) {
      el.value = value;
      el.dispatchEvent(new Event('input'));
    }
  }

  /**
   * Get a slider integer value.
   * @param {string} id
   * @returns {number}
   */
  function getSliderInt(id) {
    var el = document.getElementById(id);
    return el ? parseInt(el.value, 10) : 0;
  }

  /**
   * Get a slider float value with divisor.
   * @param {string} id
   * @param {number} divisor
   * @returns {number}
   */
  function getSliderFloat(id, divisor) {
    var el = document.getElementById(id);
    if (!el) return 0;
    return parseFloat(el.value) / (divisor || 1);
  }

  /**
   * Set text content of an element by id.
   * @param {string} id
   * @param {*} text
   */
  function setTextContent(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text !== undefined ? text : '';
  }

  /**
   * Set a hotkey display element's text and data attribute.
   * @param {string} id
   * @param {string} combo
   */
  function setHotkeyDisplay(id, combo) {
    var el = document.getElementById(id);
    if (el && combo) {
      el.textContent = combo;
      el.dataset.key = combo;
    }
  }

  /**
   * Get a hotkey value from a display element.
   * @param {string} id
   * @returns {string}
   */
  function getHotkeyValue(id) {
    var el = document.getElementById(id);
    return el ? (el.dataset.key || el.textContent.trim()) : '';
  }

  /**
   * Bind a click handler to an element by id, if it exists.
   * @param {string} id
   * @param {Function} handler
   */
  function bindIfExists(id, handler) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('click', handler);
  }

})();
