/* Общие помощники. Разметка строится через DOM (textContent), без innerHTML: данные из документов безопасны. */
(function () {
  "use strict";

  function h(tag, attrs) {
    var el = document.createElement(tag);
    var a = attrs || {};
    Object.keys(a).forEach(function (k) {
      var v = a[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.slice(0, 2) === "on" && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, String(v));
    });
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function add(el, c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) { c.forEach(function (x) { add(el, x); }); return; }
    el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
  function mount(el) { clear(el); for (var i = 1; i < arguments.length; i++) add(el, arguments[i]); return el; }

  function api(method, url, body, isForm) {
    var opts = { method: method, headers: { "X-Requested-With": "DocAgent" }, credentials: "same-origin" };
    if (body !== undefined && body !== null) {
      if (isForm) opts.body = body;
      else { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
    }
    return fetch(url, opts).then(function (r) {
      return r.text().then(function (t) {
        var data = null;
        try { data = t ? JSON.parse(t) : null; } catch (e) { data = null; }
        if (!r.ok) {
          var err = new Error((data && data.error) || ("Ошибка сервера (" + r.status + ")"));
          err.status = r.status;
          throw err;
        }
        return data;
      });
    }, function () {
      var err = new Error("Нет связи с сервером. Проверьте интернет и попробуйте ещё раз.");
      err.status = 0;
      throw err;
    });
  }

  function fmtDate(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d)) return iso;
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    return p(d.getDate()) + "." + p(d.getMonth() + 1) + "." + d.getFullYear() + " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }
  function fmtSize(b) {
    if (b < 1024) return b + " Б";
    if (b < 1024 * 1024) return Math.round(b / 1024) + " КБ";
    return (b / 1024 / 1024).toFixed(1).replace(".", ",") + " МБ";
  }
  function toast(msg, kind) {
    var el = h("div", { class: "toast alert " + (kind || "ok"), role: "status" }, msg);
    document.body.appendChild(el);
    setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 4000);
  }
  function store(key, val) {
    try {
      if (val === undefined) return JSON.parse(localStorage.getItem(key) || "null");
      localStorage.setItem(key, JSON.stringify(val));
    } catch (e) { return null; }
    return val;
  }

  window.DA = { h: h, clear: clear, mount: mount, api: api, fmtDate: fmtDate, fmtSize: fmtSize, toast: toast, store: store };
})();
