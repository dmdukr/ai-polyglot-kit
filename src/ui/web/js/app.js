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

  /** Hotkey capture state. */
  var currentHotkeyTarget = null;

  /** Enrollment timer handle. */
  var enrollTimer = null;

  /**
   * Main initialization — called when pywebview bridge is ready
   * or on DOMContentLoaded if bridge is already present.
   */
  async function init(bootstrap) {
    if (window.pywebview && window.pywebview.api) {
      bridgeReady = true;
      api = window.pywebview.api;
    }

    I18n.init(bootstrap);
    UiCore.init(bootstrap);

    setupTitlebar();
    setupI18n();
    setupModalActions();
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

    // Load initial data from backend — MUST await for translations to apply
    if (bridgeReady) {
      await loadConfig();
      await loadVersion();
    }

    console.log('[app.js] Settings UI initialized, bridge=' + bridgeReady);
  }

  // Wait for bridge: poll every 50ms (pywebviewready event is unreliable)
  function start() {
    var bootstrap = (typeof _BOOTSTRAP !== 'undefined') ? _BOOTSTRAP : null;
    if (window.pywebview && window.pywebview.api) {
      init(bootstrap);
    } else {
      var attempts = 0;
      var poll = setInterval(function () {
        attempts++;
        if (window.pywebview && window.pywebview.api) {
          clearInterval(poll);
          init(bootstrap);
        } else if (attempts > 100) { // 5 seconds
          clearInterval(poll);
          console.warn('[app.js] Bridge not found after 5s, running without it');
          init(bootstrap);
        }
      }, 50);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }


  // ============================================================
  // 1b. TITLEBAR (frameless window controls)
  // ============================================================

  function setupTitlebar() {
    var btnMin = document.getElementById('btn-minimize');
    var btnMax = document.getElementById('btn-maximize');
    var btnClose = document.getElementById('btn-close');

    if (btnMin) {
      btnMin.addEventListener('click', function () {
        if (api) api.window_minimize();
      });
    }
    if (btnMax) {
      btnMax.addEventListener('click', function () {
        if (api) api.window_maximize();
      });
    }
    if (btnClose) {
      btnClose.addEventListener('click', function () {
        if (api) api.window_close();
      });
    }
  }

  // ============================================================
  // 4. I18N
  // ============================================================

  function setupI18n() {
    var langSelect = document.getElementById('lang-select');
    if (langSelect) {
      langSelect.addEventListener('change', function () {
        I18n.setLang(this.value);
        refreshSliderLabels();
      });
    }
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
      await populateForm(config);
      console.log('[config] Config loaded from backend');
    } catch (e) {
      console.error('[config] Failed to load config:', e);
      console.warn('[config] Settings load error (non-critical):', e.message);
    }
  }

  /**
   * Populate all form fields from a config object.
   * @param {Object} config
   */
  async function populateForm(config) {
    // Declarative binding handles all data-cfg elements
    FormBind.populate(config);

    // Theme (external, not in AppConfig)
    var theme = config.theme || 'dark';
    UiCore.setTheme(theme);

    // Language (triggers i18n)
    if (config.language) {
      I18n.setLang(config.language);
      var langSelect = document.getElementById('lang-select');
      if (langSelect) langSelect.value = config.language;
    }

    // Hotkeys (custom capture UI)
    if (config.hotkeys) {
      setHotkeyDisplay('hotkey-record', config.hotkeys.record);
      setHotkeyDisplay('hotkey-feedback', config.hotkeys.feedback);
      setHotkeyDisplay('hotkey-cancel', config.hotkeys.cancel);
      setHotkeyDisplay('hotkey-paste-last', config.hotkeys.paste_last);
      setHotkeyDisplay('hotkey-translate', config.hotkeys.translate);
    } else if (config.hotkey) {
      setHotkeyDisplay('hotkey-record', config.hotkey);
    }

    refreshSliderLabels();
  }

  /**
   * Collect all form data into a config object for saving.
   * @returns {Object} config data
   */
  function collectFormData() {
    var config = FormBind.collect();

    // Theme
    config.theme = UiCore.theme;

    // Language
    config.language = I18n.lang;

    // Hotkeys (custom capture UI)
    config.hotkeys = {
      record: getHotkeyValue('hotkey-record'),
      feedback: getHotkeyValue('hotkey-feedback'),
      cancel: getHotkeyValue('hotkey-cancel'),
      paste_last: getHotkeyValue('hotkey-paste-last'),
      translate: getHotkeyValue('hotkey-translate')
    };
    config.hotkey = config.hotkeys.record;

    // Provider cards (dynamic structure)
    if (!config.providers) config.providers = {};
    config.providers.stt = collectProviderCards('stt-provider');
    config.providers.llm = collectProviderCards('llm-provider');
    config.providers.translation = collectProviderCards('translate-provider');

    return config;
  }

  /**
   * Save the current form data to the Python backend.
   */
  async function saveConfig() {
    if (!api) {
      UiCore.toast('Backend not connected', 'error');
      return;
    }
    var data = collectFormData();
    try {
      var result = await api.save_config(data);
      if (result) {
        UiCore.toast('Settings saved', 'success');
      } else {
        UiCore.toast('Failed to save settings', 'error');
      }
    } catch (e) {
      console.error('[config] Save failed:', e);
      UiCore.toast('Error saving settings: ' + e.message, 'error');
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
      UiCore.toast('Microphone test failed', 'error');
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
        UiCore.openModal('modal-import-dict');
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
        UiCore.toast('Failed to add term', 'error');
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
      UiCore.toast('Dictionary exported', 'success');
    } catch (e) {
      console.error('[dict] Export failed:', e);
      UiCore.toast('Export failed', 'error');
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
        UiCore.openModal('modal-add-replacement');
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
        UiCore.openModal('modal-import-replacements');
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

    UiCore.openModal('modal-add-replacement');
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
        UiCore.closeModal('modal-add-replacement');
        UiCore.toast(editId ? 'Replacement updated' : 'Replacement added', 'success');
      } catch (e) {
        console.error('[repl] Save failed:', e);
        UiCore.toast('Failed to save replacement', 'error');
      }
    } else {
      UiCore.closeModal('modal-add-replacement');
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
        UiCore.toast('Replacement deleted', 'success');
      } catch (e) {
        console.error('[repl] Delete failed:', e);
        UiCore.toast('Failed to delete replacement', 'error');
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
        UiCore.openModal('modal-add-app-instruction');
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
    bindIfExists('btn-app-instr-slack', function () { UiCore.openModal('modal-edit-script'); });
    bindIfExists('btn-app-instr-code', function () { UiCore.openModal('modal-edit-script'); });

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

    UiCore.openModal('modal-edit-script');
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

    UiCore.openModal('modal-edit-script');
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
      UiCore.toast('Script name is required', 'error');
      return;
    }

    var editId = modal ? modal.dataset.editId : '';

    if (api) {
      try {
        await api.save_script(editId || null, name, body);
        await loadScripts();
        UiCore.closeModal('modal-edit-script');
        UiCore.toast('Script saved', 'success');
      } catch (e) {
        console.error('[script] Save failed:', e);
        UiCore.toast('Failed to save script: ' + e.message, 'error');
      }
    } else {
      UiCore.closeModal('modal-edit-script');
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
      UiCore.toast('Script deleted', 'success');
    } catch (e) {
      console.error('[script] Delete failed:', e);
      UiCore.toast('Failed to delete script', 'error');
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
        UiCore.closeModal('modal-add-app-instruction');
        UiCore.toast('App rule saved', 'success');
      } catch (e) {
        console.error('[app-rule] Save failed:', e);
        UiCore.toast('Failed to save app rule', 'error');
      }
    } else {
      UiCore.closeModal('modal-add-app-instruction');
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
        UiCore.openModal('modal-confirm-delete-history');
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
        UiCore.openModal('modal-confirm-clear-history');
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
        UiCore.toast('Raw text copied', 'success');
      }
      var copyNorm = e.target.closest('.btn-copy-normalized');
      if (copyNorm) {
        copyToClipboard(copyNorm.dataset.text || '');
        UiCore.toast('Normalized text copied', 'success');
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
        UiCore.toast('Failed to delete entries', 'error');
        UiCore.closeModal('modal-confirm-delete-history');
        return;
      }
    }

    // Remove from DOM
    ids.forEach(function (id) {
      var item = document.querySelector('.history-item[data-id="' + id + '"]');
      if (item) item.remove();
    });
    updateBatchDeleteBtn();
    UiCore.closeModal('modal-confirm-delete-history');
    UiCore.toast(ids.length + ' entries deleted', 'success');
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
        UiCore.toast('Failed to clear history', 'error');
        UiCore.closeModal('modal-confirm-clear-history');
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
    UiCore.closeModal('modal-confirm-clear-history');
    UiCore.toast('History cleared', 'success');
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
        UiCore.toast('Re-normalized successfully', 'success');
        reloadHistory();
      }
    } catch (e) {
      console.error('[history] Re-normalize failed:', e);
      UiCore.toast('Re-normalization failed', 'error');
    }
  }


  // ============================================================
  // 12. MODALS
  // ============================================================

  function setupModalActions() {
    // Wire up specific button -> modal bindings from mockup
    var modalBindings = {
      'btn-add-app': 'modal-add-app',
      'btn-import-config': 'modal-import-config',
      'btn-reenroll': 'modal-enrollment',
      'btn-delete-profile': 'modal-confirm-delete-profile',
      'btn-delete-model': 'modal-confirm-delete-model',
      'btn-download-small': 'modal-download-model',
      'btn-download-large': 'modal-download-model',
      'btn-reset-all': 'modal-confirm-reset',
      'btn-audit-log': 'modal-audit-log',
      'btn-regen-secret': 'modal-confirm-regen-secret'
    };

    Object.keys(modalBindings).forEach(function (btnId) {
      bindIfExists(btnId, function () {
        UiCore.openModal(modalBindings[btnId]);
      });
    });

    // Check for updates buttons
    async function doCheckUpdate() {
      var checking = document.getElementById('update-checking');
      var upToDate = document.getElementById('update-up-to-date');
      var available = document.getElementById('update-available');
      if (checking) checking.style.display = '';
      if (upToDate) upToDate.style.display = 'none';
      if (available) available.style.display = 'none';
      UiCore.openModal('modal-check-update');
      try {
        var result = api ? await api.check_update() : null;
        if (checking) checking.style.display = 'none';
        if (result && result.available) {
          if (available) available.style.display = '';
          var verEl = document.getElementById('update-new-version');
          if (verEl) verEl.textContent = 'v' + result.version + ' ' + I18n.t('footer.updateAvailable');
          var installBtn = document.getElementById('update-install-btn');
          if (installBtn) {
            installBtn.onclick = function() {
              if (api && api.open_url) api.open_url(result.url);
            };
          }
          var link = document.getElementById('update-download-link');
          if (link) {
            link.onclick = function(e) {
              e.preventDefault();
              if (api && api.open_url) api.open_url(result.url);
            };
          }
        } else {
          if (upToDate) upToDate.style.display = '';
        }
      } catch (e) {
        if (checking) checking.style.display = 'none';
        if (upToDate) upToDate.style.display = '';
      }
    }
    bindIfExists('btn-check-update', doCheckUpdate);
    bindIfExists('btn-check-update-general', doCheckUpdate);

    // Confirmation action buttons
    bindIfExists('btn-confirm-delete-profile', async function () {
      if (api) {
        try {
          await api.delete_speaker_profile();
          UiCore.toast('Voice profile deleted', 'success');
        } catch (e) {
          UiCore.toast('Failed to delete profile', 'error');
        }
      }
      UiCore.closeModal('modal-confirm-delete-profile');
    });

    bindIfExists('btn-confirm-reset', async function () {
      if (api) {
        try {
          await api.reset_config();
          await loadConfig();
          UiCore.toast('Settings reset to defaults', 'success');
        } catch (e) {
          UiCore.toast('Failed to reset settings', 'error');
        }
      }
      UiCore.closeModal('modal-confirm-reset');
    });

    bindIfExists('btn-confirm-regen-secret', async function () {
      if (api) {
        try {
          var result = await api.regenerate_secret();
          if (result && result.secret) {
            var field = document.getElementById('secret-field');
            if (field) field.value = result.secret;
          }
          UiCore.toast('Shared secret regenerated', 'success');
        } catch (e) {
          UiCore.toast('Failed to regenerate secret', 'error');
        }
      }
      UiCore.closeModal('modal-confirm-regen-secret');
    });
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
        UiCore.toast('Extension installed in ' + (result.browser_name || browserId), 'success');
        await loadBrowsers();
      } else {
        // Show install instructions modal
        UiCore.openModal('modal-install-extension');
      }
    } catch (e) {
      console.error('[ext] Install failed:', e);
      UiCore.toast('Extension install failed', 'error');
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

      var ver = 'v' + (info.version || '');

      var versionEl = document.getElementById('version-text');
      if (versionEl) versionEl.textContent = 'Version ' + ver;

      var footerEl = document.getElementById('footer-version');
      if (footerEl) footerEl.textContent = ver;

      var updateModalVer = document.getElementById('update-modal-version');
      if (updateModalVer) updateModalVer.textContent = 'AI Polyglot Kit ' + ver;

      // Update badge
      var badge = document.getElementById('footer-update-badge');
      if (badge) {
        if (info.update_available && info.latest) {
          badge.style.display = '';
          var badgeText = badge.querySelector('.btn-text');
          if (badgeText) badgeText.textContent = 'v' + info.latest + ' available';
          badge.onclick = function(e) {
            e.preventDefault();
            // Navigate to General page
            var generalTab = document.querySelector('.sidebar-item[data-page="general"]');
            if (generalTab) generalTab.click();
          };
        } else {
          badge.style.display = 'none';
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
        UiCore.openModal('modal-hotkey');
      });
    });

    // Apply hotkey button
    bindIfExists('btn-apply-hotkey', function () {
      var display = document.getElementById('hotkey-display');
      if (currentHotkeyTarget && display && display.textContent !== '\u2014') {
        currentHotkeyTarget.textContent = display.textContent;
        currentHotkeyTarget.dataset.key = display.textContent;
      }
      UiCore.closeModal('modal-hotkey');
    });

    // Listen for key combos in hotkey capture modal
    document.addEventListener('keydown', function (e) {
      var modal = document.getElementById('modal-hotkey');
      if (!modal || !modal.classList.contains('show')) return;

      e.preventDefault();
      e.stopPropagation();

      if (e.key === 'Escape') {
        UiCore.closeModal('modal-hotkey');
        return;
      }
      if (e.key === 'Backspace') {
        var hotkeyDisplay = document.getElementById('hotkey-display');
        if (hotkeyDisplay) hotkeyDisplay.textContent = '\u2014';
        return;
      }

      // Use e.code for layout-independent key names (always English)
      var combo = [];

      // AltGr on Windows sends ctrlKey+altKey simultaneously with code=AltRight
      var isAltGr = e.code === 'AltRight' && e.ctrlKey;

      if (isAltGr) {
        // AltGr pressed alone — treat as single key
        combo.push('right_alt');
      } else {
        if (e.ctrlKey && e.code !== 'ControlLeft' && e.code !== 'ControlRight') combo.push('Ctrl');
        if (e.altKey && e.code !== 'AltLeft' && e.code !== 'AltRight') combo.push('Alt');
        if (e.shiftKey && e.code !== 'ShiftLeft' && e.code !== 'ShiftRight') combo.push('Shift');

        var modifiers = ['ControlLeft','ControlRight','AltLeft','AltRight','ShiftLeft','ShiftRight','MetaLeft','MetaRight'];
        if (modifiers.indexOf(e.code) === -1) {
          // Map e.code to readable English key name
          var keyName = e.code
            .replace('Key', '')       // KeyA → A
            .replace('Digit', '')     // Digit1 → 1
            .replace('Numpad', 'Num') // Numpad0 → Num0
            .replace('Arrow', '');    // ArrowUp → Up
          combo.push(keyName);
        } else if (e.code === 'AltRight') {
          combo.push('right_alt');
        } else if (e.code === 'AltLeft') {
          combo.push('Alt');
        } else if (e.code === 'ControlLeft' || e.code === 'ControlRight') {
          combo.push('Ctrl');
        } else if (e.code === 'ShiftLeft' || e.code === 'ShiftRight') {
          combo.push('Shift');
        }
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
          UiCore.toast('System detected: ' + (result.summary || ''), 'success');
        }
      } catch (e) {
        UiCore.toast('Detection failed', 'error');
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
          UiCore.toast('Model deleted', 'success');
        } catch (e) {
          UiCore.toast('Failed to delete model', 'error');
        }
      }
      UiCore.closeModal('modal-confirm-delete-model');
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
        UiCore.toast('Download failed: ' + e.message, 'error');
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
        UiCore.toast('Import successful', 'success');
        dropZone.style.borderColor = 'var(--success)';
      }
    } catch (e) {
      console.error('[import] Failed:', e);
      UiCore.toast('Import failed', 'error');
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
  /**
   * Remove all child nodes from an element.
   * @param {HTMLElement} el
   */
  function clearChildren(el) {
    while (el.firstChild) {
      el.removeChild(el.firstChild);
    }
  }


  // ---- Form helpers (non-declarative, still used by dynamic UI) ----

  function getSelectValue(id) {
    var el = document.getElementById(id);
    return el ? el.value : '';
  }

  function setInputValue(id, value) {
    var el = document.getElementById(id);
    if (el && value !== undefined) el.value = value;
  }

  function getInputValue(id) {
    var el = document.getElementById(id);
    return el ? el.value : '';
  }

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
