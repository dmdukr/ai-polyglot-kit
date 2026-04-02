// form-bind.js — Declarative form <-> config binding
// Elements with [data-cfg] are automatically bound to config paths.
var FormBind = {
  populate: function(config) {
    document.querySelectorAll('[data-cfg]').forEach(function(el) {
      var path = el.getAttribute('data-cfg');
      var value = FormBind._resolve(config, path);
      if (value === undefined) return;
      FormBind._setValue(el, value);
    });
  },

  collect: function() {
    var config = {};
    document.querySelectorAll('[data-cfg]').forEach(function(el) {
      var path = el.getAttribute('data-cfg');
      var value = FormBind._getValue(el);
      FormBind._assign(config, path, value);
    });
    return config;
  },

  _resolve: function(obj, path) {
    return path.split('.').reduce(function(cur, key) {
      return (cur == null) ? undefined : cur[key];
    }, obj);
  },

  _assign: function(obj, path, value) {
    var parts = path.split('.');
    var target = parts.slice(0, -1).reduce(function(cur, key) {
      if (!cur[key]) cur[key] = {};
      return cur[key];
    }, obj);
    target[parts[parts.length - 1]] = value;
  },

  _getValue: function(el) {
    if (el.type === 'checkbox') return el.checked;
    if (el.type === 'range') {
      var divisor = parseFloat(el.getAttribute('data-divisor')) || 1;
      return parseFloat(el.value) / divisor;
    }
    if (el.type === 'number') return parseInt(el.value, 10) || 0;
    if (el.tagName === 'SELECT' && el.getAttribute('data-cfg-type') === 'int') {
      return parseInt(el.value, 10) || 0;
    }
    return el.value;
  },

  _setValue: function(el, value) {
    if (value === undefined || value === null) return;
    if (el.type === 'checkbox') {
      el.checked = !!value;
    } else if (el.type === 'range') {
      var divisor = parseFloat(el.getAttribute('data-divisor')) || 1;
      el.value = value * divisor;
      el.dispatchEvent(new Event('input'));
    } else {
      el.value = value;
    }
  }
};
