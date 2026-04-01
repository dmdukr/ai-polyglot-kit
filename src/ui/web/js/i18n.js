// i18n.js — single i18n module for Settings SPA
var I18n = {
  lang: 'uk',
  data: {},

  init: function(bootstrap) {
    this.lang = (bootstrap && bootstrap.lang) || 'uk';
    if (bootstrap && bootstrap.translations) {
      this.data = bootstrap.translations;
    } else if (typeof _EMBEDDED_I18N !== 'undefined') {
      this.data = _EMBEDDED_I18N;
    }
    this.apply(this.lang);
  },

  apply: function(lang) {
    this.lang = lang;
    var tr = this.data[lang] || {};
    document.querySelectorAll('[data-i18n]').forEach(function(el) {
      var key = el.getAttribute('data-i18n');
      if (tr[key]) el.textContent = tr[key];
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(function(el) {
      var key = el.getAttribute('data-i18n-placeholder');
      if (tr[key]) el.placeholder = tr[key];
    });
    document.documentElement.lang = lang;
  },

  setLang: function(lang) {
    this.apply(lang);
    if (window.pywebview && window.pywebview.api && window.pywebview.api.set_language) {
      window.pywebview.api.set_language(lang);
    }
  },

  t: function(key) {
    var tr = this.data[this.lang] || {};
    return tr[key] || key;
  }
};
