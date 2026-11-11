(function () {
  "use strict";
  var h = DA.h, mount = DA.mount, api = DA.api;
  var main = document.getElementById("main");
  var nav = document.getElementById("nav");
  var who = document.getElementById("who");

  var S = {
    me: null, view: "apps", filter: "open", q: "",
    items: [], counts: {}, sel: null, detail: null, tab: 0,
    edits: {}, typeEdit: null, busy: false
  };
  var listTimer = null, detailTimer = null;

  var PILL = { received: "new", processing: "run", review: "warn", confirm: "human", sent: "ok", returned: "crit" };
  var CONF = { high: ["Найдено", "ok"], low: ["Не уверен", "warn"], missing: ["Нет", "crit"], fixed: ["Исправлено", "human"] };
  var EVENTS = {
    submitted: "Студент отправил обращение", processing: "Агент начал обработку", read: "Агент прочитал документы",
    needs_review: "Нужна проверка сотрудником", registered: "Записано в журнал", draft_ready: "Готов проект ответа",
    fixed: "Исправлены поля", checked: "Сотрудник проверил", reply_edited: "Изменён текст ответа",
    sent: "Ответ подтверждён", returned: "Возвращено на доработку", mail: "Письмо студенту",
    reprocess: "Запущена переобработка", error: "Ошибка обработки"
  };
  var MAIL = {
    sent: ["Письмо отправлено студенту.", "ok"],
    not_configured: ["Почта не настроена: ответ виден студенту на странице статуса.", "warn"],
    no_address: ["Студент не указал почту: ответ виден на странице статуса.", "warn"],
    failed: ["Письмо не ушло (ошибка почтового сервера). Ответ виден на странице статуса.", "err"]
  };
  var FILTERS = [["open", "Открытые"], ["review", "Нужна проверка"], ["confirm", "Ждут подтверждения"],
    ["processing", "В обработке"], ["closed", "Закрытые"], ["", "Все"]];

  function fail(e) {
    if (e && e.status === 401) { S.me = null; renderLogin(); return; }
    DA.toast(e.message || String(e), "err");
  }

  /* ---------- вход ---------- */

  function renderLogin(msg) {
    clearTimeout(listTimer); clearTimeout(detailTimer);
    nav.hidden = true; who.hidden = true;
    var login = h("input", { class: "input", id: "login", autocomplete: "username", required: true });
    var pass = h("input", { class: "input", id: "password", type: "password", autocomplete: "current-password", required: true });
    var err = h("div", { class: "alert err", role: "alert", hidden: !msg }, msg || "");
    var btn = h("button", { class: "btn primary", type: "submit" }, "Войти");
    mount(main, h("div", { class: "login" }, h("form", { class: "card stack", onsubmit: function (e) {
      e.preventDefault();
      btn.disabled = true;
      api("POST", "/api/auth/login", { login: login.value.trim(), password: pass.value }).then(function (me) {
        S.me = me; start();
      }, function (e2) { btn.disabled = false; err.hidden = false; err.textContent = e2.message; pass.value = ""; pass.focus(); });
    } },
      h("h2", null, "Вход для сотрудников"),
      h("div", null, h("label", { class: "lbl", for: "login" }, "Логин"), login),
      h("div", null, h("label", { class: "lbl", for: "password" }, "Пароль"), pass),
      err, h("div", { class: "row end" }, btn))));
    login.focus();
  }

  /* ---------- шапка ---------- */

  function renderNav() {
    var waiting = (S.counts.review || 0) + (S.counts.confirm || 0);
    var tabs = [["apps", "Заявления", waiting], ["journal", "Журнал"], ["stats", "Сводка"]];
    if (S.me.role === "admin") tabs.push(["users", "Сотрудники"]);
    mount(nav, tabs.map(function (t) {
      return h("button", { class: "tab", type: "button", "aria-pressed": S.view === t[0] ? "true" : "false",
        onclick: function () { go(t[0]); } }, t[1], t[2] ? h("span", { class: "badge" }, String(t[2])) : null);
    }));
    mount(who, h("span", null, S.me.name),
      h("button", { class: "btn small", type: "button", onclick: function () { go("password"); } }, "Пароль"),
      h("button", { class: "btn small", type: "button", onclick: function () {
        api("POST", "/api/auth/logout", {}).then(function () { S.me = null; renderLogin(); }, fail);
      } }, "Выйти"));
    nav.hidden = false; who.hidden = false;
  }

  function go(view) {
    S.view = view;
    clearTimeout(detailTimer);
    renderNav();
    if (view === "apps") renderApps();
    else if (view === "journal") renderJournal();
    else if (view === "stats") renderStats();
    else if (view === "users") renderUsers();
    else if (view === "password") renderPassword();
  }

  function start() {
    renderNav();
    go("apps");
  }

  /* ---------- заявления ---------- */

  function renderApps() {
    var search = h("input", { class: "input", type: "search", placeholder: "Поиск: ФИО, группа, номер", value: S.q,
      "aria-label": "Поиск заявлений", oninput: function () { S.q = search.value; loadList(); } });
    var filters = h("div", { class: "filters", role: "group", "aria-label": "Фильтр" }, FILTERS.map(function (f) {
      return h("button", { class: "tab", type: "button", "aria-pressed": S.filter === f[0] ? "true" : "false",
        onclick: function () { S.filter = f[0]; renderApps(); } }, f[1]);
    }));
    mount(main, h("div", { class: "staff-grid" },
      h("section", { class: "col", "aria-label": "Входящие" },
        h("div", { class: "card stack" }, h("h2", null, "Входящие"), filters, search, h("div", { class: "inbox", id: "inbox" }))),
      h("section", { class: "col", id: "docCol", "aria-label": "Документ" }),
      h("section", { class: "col", id: "agentCol", "aria-label": "Результат агента" })));
    renderDetail();
    loadList();
  }

  function loadList() {
    clearTimeout(listTimer);
    var url = "/api/staff/applications?status=" + encodeURIComponent(S.filter) + "&q=" + encodeURIComponent(S.q);
    api("GET", url).then(function (res) {
      S.items = res.items; S.counts = res.counts;
      renderNav();
      renderInbox();
      if (S.sel === null && S.items.length && window.innerWidth > 760) select(S.items[0].id);
    }, fail).then(function () {
      if (S.me && S.view === "apps") listTimer = setTimeout(loadList, 10000);
    });
  }

  function renderInbox() {
    var box = document.getElementById("inbox");
    if (!box) return;
    if (!S.items.length) { mount(box, h("div", { class: "empty" }, "Здесь пока пусто.")); return; }
    mount(box, S.items.map(function (it) {
      return h("button", { class: "doc-card", type: "button", "aria-current": it.id === S.sel ? "true" : "false",
        onclick: function () { select(it.id); } },
        h("b", null, it.fio || "ФИО не определено"),
        h("small", null, it.number + (it.group ? " · " + it.group : "") + " · " + DA.fmtDate(it.created_at)),
        h("small", null, it.type || "тип ещё не определён"),
        h("span", { class: "pill " + (PILL[it.status] || "new") }, it.status_label + (it.status === "review" && it.issues ? " · " + it.issues : "")));
    }));
  }

  function select(id) {
    if (S.sel !== id) { S.edits = {}; S.typeEdit = null; S.tab = 0; }
    S.sel = id;
    renderInbox();
    loadDetail();
    if (window.innerWidth <= 760) {
      var col = document.getElementById("docCol");
      if (col) col.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function loadDetail() {
    clearTimeout(detailTimer);
    if (S.sel === null) return;
    var id = S.sel;
    api("GET", "/api/staff/applications/" + id).then(function (d) {
      if (S.sel !== id) return;
      S.detail = d;
      renderDetail();
      if (d.status === "received" || d.status === "processing") detailTimer = setTimeout(loadDetail, 2500);
    }, fail);
  }

  function setDetail(d, mailStatus) {
    S.detail = d; S.edits = {}; S.typeEdit = null;
    renderDetail();
    loadList();
    if (mailStatus && MAIL[mailStatus]) DA.toast(MAIL[mailStatus][0], MAIL[mailStatus][1]);
  }

  function act(method, url, body) {
    if (S.busy) return Promise.resolve();
    S.busy = true;
    return api(method, url, body).then(function (d) { S.busy = false; return d; }, function (e) { S.busy = false; throw e; });
  }

  /* --- документ --- */

  function highlighted(text, fields) {
    var marks = [];
    var low = text.toLowerCase();
    Object.keys(fields || {}).forEach(function (k) {
      var f = fields[k];
      if (!f || !f.v || f.v.length < 2 || k === "sign" || k === "course") return;
      var p = low.indexOf(f.v.toLowerCase());
      if (p >= 0) marks.push({ s: p, e: p + f.v.length, c: f.c });
    });
    marks.sort(function (a, b) { return a.s - b.s; });
    var out = [], pos = 0;
    marks.forEach(function (m) {
      if (m.s < pos) return;
      if (m.s > pos) out.push(text.slice(pos, m.s));
      out.push(h("mark", { class: m.c === "fixed" ? "fixed" : (m.c === "high" ? "high" : "low") }, text.slice(m.s, m.e)));
      pos = m.e;
    });
    out.push(text.slice(pos));
    return out;
  }

  function renderDoc(d) {
    var col = document.getElementById("docCol");
    if (!col) return;
    if (!d) { mount(col, h("div", { class: "card" }, h("p", null, "Выберите заявление в списке входящих."))); return; }
    var sources = d.files.map(function (f) { return { label: f.name, file: f }; });
    if (d.text_input) sources.push({ label: "Текст студента", text: d.text_input });
    if (S.tab >= sources.length) S.tab = 0;
    var src = sources[S.tab];
    var view = null, extra = null;
    if (!src) view = h("div", { class: "paper" }, "Нет документов.");
    else if (src.text !== undefined) view = h("div", { class: "paper" }, highlighted(src.text, d.fields));
    else if (src.file.kind === "pdf") {
      view = h("iframe", { src: "/api/staff/files/" + src.file.id, title: src.file.name });
      if (src.file.text) extra = h("details", { class: "card" }, h("summary", null, "Текстовый слой PDF"),
        h("div", { class: "paper" }, highlighted(src.file.text, d.fields)));
    } else if (src.file.kind === "image") view = h("img", { src: "/api/staff/files/" + src.file.id, alt: "Скан: " + src.file.name });
    else view = h("div", { class: "paper" }, src.file.text ? highlighted(src.file.text, d.fields) : "Текст не извлечён.");

    mount(col,
      h("div", { class: "card stack" },
        h("div", { class: "row" },
          h("h3", null, d.number), h("span", { class: "pill " + (PILL[d.status] || "new") }, d.status_label),
          h("span", { class: "spacer" }),
          d.reg_no ? h("span", { class: "mono hint" }, d.reg_no) : null),
        h("dl", { class: "kv" },
          h("dt", null, "Получено"), h("dd", null, DA.fmtDate(d.created_at)),
          h("dt", null, "Студент"), h("dd", null, [d.student_name, d.student_email].filter(Boolean).join(", ") || "не указал контакты"),
          d.summary ? [h("dt", null, "Кратко"), h("dd", null, d.summary)] : null),
        sources.length > 1 ? h("div", { class: "ftabs" }, sources.map(function (s, i) {
          return h("button", { class: "tab", type: "button", "aria-pressed": i === S.tab ? "true" : "false",
            onclick: function () { S.tab = i; renderDoc(S.detail); } }, s.label);
        })) : null,
        h("div", { class: "viewer" }, view),
        src && src.file && src.file.kind === "pdf" ? h("p", { class: "hint" }, "Если PDF не отображается, откройте или скачайте оригинал.") : null,
        src && src.file ? h("div", { class: "row" },
          h("a", { class: "btn small", href: "/api/staff/files/" + src.file.id + "?download=1" }, "Скачать оригинал"),
          h("span", { class: "hint" }, DA.fmtSize(src.file.size) + (src.file.pages ? ", страниц: " + src.file.pages : ""))) : null),
      extra);
  }

  /* --- результат агента --- */

  function fieldValue(d, k) {
    if (S.edits[k] !== undefined) return S.edits[k];
    var f = d.fields[k];
    return f ? f.v : "";
  }

  function renderAgent(d) {
    var col = document.getElementById("agentCol");
    if (!col) return;
    if (!d) { mount(col); return; }
    var blocks = [];
    if (d.status === "received" || d.status === "processing") {
      blocks.push(h("div", { class: "card" }, h("div", { class: "alert info" }, "Агент читает документы. Обычно это занимает до минуты.")));
      mount(col, blocks);
      return;
    }
    var editable = d.status === "review" || d.status === "confirm";
    var issues = {};
    d.issues_list.forEach(function (i) { issues[i.key] = i.reason; });

    // тип
    var typeSel = h("select", { class: "input", id: "fix-type", disabled: !editable, onchange: function () {
      S.typeEdit = typeSel.value; renderAgent(S.detail);
    } }, h("option", { value: "" }, "— выберите тип —"), d.types.map(function (t) {
      var cur = S.typeEdit !== null ? S.typeEdit : d.type;
      return h("option", { value: t, selected: t === cur }, t);
    }));
    var typeConf = d.type_confidence === "fixed" ? CONF.fixed : (d.type_confidence === "high" ? CONF.high : CONF.low);
    var typeBox = h("div", { class: "fld" + (issues.type ? " issue" : "") },
      h("div", { class: "fld-head" }, h("label", { for: "fix-type" }, h("b", null, "Тип документа")), h("span", { class: "pill " + typeConf[1] }, typeConf[0])),
      typeSel, issues.type ? h("div", { class: "reason" }, issues.type) : null,
      d.owner ? h("div", { class: "hint" }, "Рассматривает: " + d.owner) : null);

    var req = d.required || [];
    var fields = Object.keys(d.labels).map(function (k) {
      var f = d.fields[k] || { v: "", c: "missing" };
      var conf = CONF[f.c] || CONF.low;
      var input;
      if (k === "sign") {
        var cb = h("input", { type: "checkbox", id: "fix-sign", disabled: !editable,
          onchange: function () { S.edits.sign = cb.checked ? "есть" : ""; renderButtons(); } });
        cb.checked = fieldValue(d, "sign") === "есть";
        input = h("label", { class: "check", for: "fix-sign" }, cb, h("span", null, "Подпись есть"));
      } else {
        input = h("input", { class: "input", id: "fix-" + k, value: fieldValue(d, k), disabled: !editable,
          placeholder: k === "date" ? "ДД.ММ.ГГГГ" : "", oninput: function (e) { S.edits[k] = e.target.value; renderButtons(); } });
      }
      var confirmBtn = null;
      if (editable && f.c === "low" && f.v) {
        var marked = S.edits[k] !== undefined && S.edits[k] === f.v;
        confirmBtn = h("button", { class: "btn small", type: "button", disabled: marked,
          onclick: function () { S.edits[k] = f.v; renderAgent(S.detail); } }, marked ? "Отмечено как верное" : "Верно");
      }
      return h("div", { class: "fld" + (issues[k] ? " issue" : "") },
        h("div", { class: "fld-head" },
          h("label", { for: "fix-" + k }, h("b", null, d.labels[k]), req.indexOf(k) >= 0 ? "" : h("span", { class: "hint" }, " · необязательно")),
          h("span", { class: "pill " + conf[1] }, conf[0])),
        input,
        issues[k] || confirmBtn ? h("div", { class: "row" }, issues[k] ? h("div", { class: "reason spacer" }, issues[k]) : h("span", { class: "spacer" }), confirmBtn) : null);
    });

    var agentCard = h("div", { class: "card stack" },
      h("h2", null, "Что понял агент"),
      d.reader_note ? h("div", { class: "alert warn" }, d.reader_note) : null,
      d.reader ? h("p", { class: "hint" }, d.reader.indexOf("ai:") === 0 ? "Прочитано ИИ (" + d.reader.slice(3) + "). Уверенность оценивает сама модель." : "Прочитано правилами без ИИ.") : null,
      d.warnings.length ? h("ul", { class: "warnings" }, d.warnings.map(function (w) { return h("li", null, w); })) : null,
      typeBox, h("div", { class: "fields" }, fields),
      h("div", { class: "row end", id: "fixButtons" }));
    blocks.push(agentCard);

    // ответ
    if (d.status === "confirm") {
      var reply = h("textarea", { class: "input", id: "reply", rows: "9", maxlength: "5000" });
      reply.value = d.reply_text;
      blocks.push(h("div", { class: "card stack" },
        h("h2", null, "Проект ответа студенту"),
        h("p", null, "Проверьте и при необходимости исправьте текст. Студент получит его только после подтверждения."),
        reply,
        h("div", { class: "row end" },
          h("button", { class: "btn small", type: "button", onclick: function () {
            act("PUT", "/api/staff/applications/" + d.id + "/reply", { text: reply.value }).then(function (nd) {
              S.detail = nd; DA.toast("Черновик сохранён");
            }, fail);
          } }, "Сохранить черновик"),
          h("button", { class: "btn human", type: "button", onclick: function () {
            if (Object.keys(S.edits).length || S.typeEdit !== null) { DA.toast("Сначала сохраните исправления полей.", "warn"); return; }
            act("POST", "/api/staff/applications/" + d.id + "/send", { text: reply.value }).then(function (nd) {
              setDetail(nd, nd.mail_status);
            }, fail);
          } }, "Подтвердить и отправить"))));
    } else if (d.status === "sent") {
      blocks.push(h("div", { class: "card stack" },
        h("h2", null, "Ответ отправлен"),
        h("p", null, DA.fmtDate(d.sent_at) + (d.handled_by ? ", подтвердил(а): " + d.handled_by : "")),
        h("div", { class: "letter" }, d.reply_text)));
    } else if (d.status === "returned") {
      blocks.push(h("div", { class: "card stack" },
        h("h2", null, "Возвращено на доработку"),
        h("p", null, DA.fmtDate(d.sent_at) + (d.handled_by ? ", " + d.handled_by : "")),
        h("div", { class: "letter" }, d.student_message)));
    }

    // прочие действия
    if (editable) {
      var msg = h("textarea", { class: "input", id: "returnMsg", rows: "4", maxlength: "3000",
        placeholder: "Например: не хватает подписи и даты. Подпишите заявление и отправьте фото заново." });
      blocks.push(h("details", { class: "card" },
        h("summary", null, "Другие действия"),
        h("div", { class: "stack" },
          h("label", { class: "lbl", for: "returnMsg" }, "Вернуть студенту на доработку"), msg,
          h("div", { class: "row" },
            h("button", { class: "btn danger", type: "button", onclick: function () {
              act("POST", "/api/staff/applications/" + d.id + "/return", { message: msg.value }).then(function (nd) {
                setDetail(nd, nd.mail_status);
              }, fail);
            } }, "Вернуть на доработку"),
            h("span", { class: "spacer" }),
            h("button", { class: "btn", type: "button", onclick: function () {
              act("POST", "/api/staff/applications/" + d.id + "/reprocess").then(function (nd) { setDetail(nd); loadDetail(); }, fail);
            } }, "Прочитать заново")))));
    }

    blocks.push(h("details", { class: "card" },
      h("summary", null, "История"),
      h("ul", { class: "history" }, d.events.map(function (e) {
        var who = e.actor === "agent" ? "агент" : e.actor === "student" ? "студент" : e.actor.replace("staff:", "");
        var det = "";
        if (e.action === "mail") det = (MAIL[e.details] || [e.details])[0];
        else if (e.action === "registered") { try { det = JSON.parse(e.details).reg_no; } catch (x) { det = ""; } }
        return h("li", null, h("time", null, DA.fmtDate(e.at)),
          h("span", null, (EVENTS[e.action] || e.action) + " (" + who + ")" + (det ? ": " + det : "")));
      })),
      h("p", { class: "hint" }, h("a", { href: d.public_url, target: "_blank", rel: "noopener" }, "Страница статуса для студента"))));

    mount(col, blocks);
    renderButtons();
  }

  function renderButtons() {
    var box = document.getElementById("fixButtons");
    var d = S.detail;
    if (!box || !d) return;
    // Изменённое поле или подтверждённое сотрудником значение, в котором агент не был уверен.
    function pending(k) {
      var f = d.fields[k] || { v: "", c: "missing" };
      return S.edits[k] !== (f.v || "") || f.c === "low" || (f.c === "missing" && S.edits[k] !== "");
    }
    var dirty = Object.keys(S.edits).some(pending) ||
      (S.typeEdit !== null && S.typeEdit !== d.type) || (S.typeEdit !== null && d.type_confidence !== "fixed");
    var buttons = [];
    if (d.status === "review" || d.status === "confirm") {
      buttons.push(h("button", { class: "btn", type: "button", disabled: !dirty, onclick: function () {
        var changed = {};
        Object.keys(S.edits).forEach(function (k) { if (pending(k)) changed[k] = S.edits[k]; });
        act("PATCH", "/api/staff/applications/" + d.id + "/fields", { type: S.typeEdit, fields: changed }).then(function (nd) {
          setDetail(nd); DA.toast("Исправления сохранены");
        }, fail);
      } }, "Сохранить исправления"));
    }
    if (d.status === "review") {
      var blocked = d.issues_list.length > 0 || dirty;
      buttons.push(h("button", { class: "btn primary", type: "button", disabled: blocked,
        title: blocked ? "Сначала исправьте и сохраните отмеченные поля" : "", onclick: function () {
          act("POST", "/api/staff/applications/" + d.id + "/resume").then(function (nd) { setDetail(nd); }, fail);
        } }, "Продолжить: в журнал и ответ"));
    }
    mount(box, buttons);
  }

  function renderDetail() {
    renderDoc(S.detail && S.detail.id === S.sel ? S.detail : null);
    renderAgent(S.detail && S.detail.id === S.sel ? S.detail : null);
  }

  /* ---------- журнал ---------- */

  function renderJournal() {
    mount(main, h("div", { class: "view stack" }, h("div", { class: "card" }, h("p", null, "Загрузка…"))));
    api("GET", "/api/staff/journal").then(function (res) {
      var rows = res.items.slice().reverse();
      mount(main, h("div", { class: "view stack" },
        h("div", { class: "row" }, h("h2", null, "Журнал регистрации (" + rows.length + ")"), h("span", { class: "spacer" }),
          h("a", { class: "btn small", href: "/api/staff/journal?format=csv" }, "Скачать для Excel (CSV)")),
        rows.length ? h("div", { class: "table-wrap" }, h("table", { class: "tbl" },
          h("thead", null, h("tr", null, ["Рег. номер", "Дата", "Тип", "ФИО", "Группа", "Курс", "Ответственный", "Статус", "Проверка"].map(function (c) {
            return h("th", { scope: "col" }, c);
          }))),
          h("tbody", null, rows.map(function (r) {
            return h("tr", null,
              h("td", { class: "mono" }, r.reg_no), h("td", null, DA.fmtDate(r.registered_at)), h("td", { class: "wrap" }, r.type),
              h("td", { class: "wrap" }, h("a", { href: "#", onclick: function (e) { e.preventDefault(); S.filter = ""; S.sel = null; go("apps"); select(r.id); } }, r.fio)),
              h("td", null, r.group), h("td", null, r.course), h("td", null, r.owner), h("td", null, r.status),
              h("td", null, r.manual ? "сотрудник" : "авто"));
          })))) : h("div", { class: "card" }, h("p", null, "В журнале пока нет записей."))));
    }, fail);
  }

  /* ---------- сводка ---------- */

  function renderStats() {
    api("GET", "/api/staff/stats").then(function (s) {
      var st = s.by_status;
      var max = Math.max.apply(null, [1].concat(s.by_type.map(function (t) { return t.n; })));
      var auto = s.registered ? Math.round((s.registered - s.manual) / s.registered * 100) : 0;
      mount(main, h("div", { class: "view stack" },
        h("h2", null, "Сводка"),
        h("div", { class: "stats" },
          stat(s.total, "всего обращений"), stat(st.review || 0, "ждут проверки"), stat(st.confirm || 0, "ждут подтверждения ответа"),
          stat(st.sent || 0, "ответ отправлен"), stat(st.returned || 0, "возвращено на доработку"),
          stat(auto + "%", "зарегистрировано без ручных правок")),
        h("div", { class: "card stack" }, h("h3", null, "По типам"),
          s.by_type.length ? h("div", { class: "bars" }, s.by_type.map(function (t) {
            var fill = h("div", { class: "fill" });
            fill.style.width = Math.round(t.n / max * 100) + "%";
            return h("div", { class: "bar" }, h("span", null, t.type), h("div", { class: "track" }, fill), h("span", { class: "n" }, String(t.n)));
          })) : h("p", null, "Пока нет данных.")),
        h("div", { class: "card" }, h("h3", null, "Система"),
          h("dl", { class: "kv" },
            h("dt", null, "Чтение документов"), h("dd", null, s.ai ? "ИИ, модель " + s.model : "правила без ИИ (ключ API не задан)"),
            h("dt", null, "Почта"), h("dd", null, s.smtp ? "настроена" : "не настроена: ответы видны только на странице статуса")))));
    }, fail);
  }
  function stat(v, label) { return h("div", { class: "stat" }, h("b", null, String(v)), h("span", null, label)); }

  /* ---------- сотрудники ---------- */

  function renderUsers() {
    api("GET", "/api/staff/users").then(function (res) {
      var login = h("input", { class: "input", id: "nu-login", autocomplete: "off" });
      var name = h("input", { class: "input", id: "nu-name" });
      var role = h("select", { class: "input", id: "nu-role" }, h("option", { value: "staff" }, "сотрудник"), h("option", { value: "admin" }, "администратор"));
      var pass = h("input", { class: "input", id: "nu-pass", type: "password", autocomplete: "new-password" });
      mount(main, h("div", { class: "view stack" },
        h("h2", null, "Сотрудники"),
        h("div", { class: "table-wrap" }, h("table", { class: "tbl" },
          h("thead", null, h("tr", null, ["Логин", "Имя", "Роль", "Статус", ""].map(function (c) { return h("th", { scope: "col" }, c); }))),
          h("tbody", null, res.items.map(function (u) {
            return h("tr", null, h("td", { class: "mono" }, u.login), h("td", null, u.name),
              h("td", null, u.role === "admin" ? "администратор" : "сотрудник"), h("td", null, u.active ? "активен" : "отключён"),
              h("td", null, u.id === undefined ? null : h("div", { class: "row" },
                h("button", { class: "btn small", type: "button", onclick: function () {
                  act("PATCH", "/api/staff/users/" + u.id, { active: !u.active }).then(renderUsers, fail);
                } }, u.active ? "Отключить" : "Включить"),
                h("button", { class: "btn small", type: "button", onclick: function () {
                  var p = window.prompt("Новый пароль для " + u.login + " (не короче 10 символов, с заглавной буквой и цифрой):");
                  if (p) act("PATCH", "/api/staff/users/" + u.id, { password: p }).then(function () { DA.toast("Пароль изменён"); }, fail);
                } }, "Сменить пароль"))));
          })))),
        h("form", { class: "card stack", onsubmit: function (e) {
          e.preventDefault();
          act("POST", "/api/staff/users", { login: login.value.trim(), name: name.value.trim(), role: role.value, password: pass.value })
            .then(function () { DA.toast("Сотрудник добавлен"); renderUsers(); }, fail);
        } },
          h("h3", null, "Добавить сотрудника"),
          h("div", { class: "row" },
            h("div", { class: "spacer" }, h("label", { class: "lbl", for: "nu-login" }, "Логин (латиница)"), login),
            h("div", { class: "spacer" }, h("label", { class: "lbl", for: "nu-name" }, "Имя"), name)),
          h("div", { class: "row" },
            h("div", { class: "spacer" }, h("label", { class: "lbl", for: "nu-role" }, "Роль"), role),
            h("div", { class: "spacer" }, h("label", { class: "lbl", for: "nu-pass" }, "Пароль"), pass)),
          h("div", { class: "row end" }, h("button", { class: "btn primary", type: "submit" }, "Добавить")))));
    }, fail);
  }

  /* ---------- пароль ---------- */

  function renderPassword() {
    var old = h("input", { class: "input", id: "pw-old", type: "password", autocomplete: "current-password" });
    var nw = h("input", { class: "input", id: "pw-new", type: "password", autocomplete: "new-password" });
    mount(main, h("div", { class: "login" }, h("form", { class: "card stack", onsubmit: function (e) {
      e.preventDefault();
      act("POST", "/api/auth/password", { old: old.value, new: nw.value }).then(function () { DA.toast("Пароль изменён"); go("apps"); }, fail);
    } },
      h("h2", null, "Сменить пароль"),
      h("div", null, h("label", { class: "lbl", for: "pw-old" }, "Текущий пароль"), old),
      h("div", null, h("label", { class: "lbl", for: "pw-new" }, "Новый пароль"), nw),
      h("p", { class: "hint" }, "Не короче 10 символов, с заглавной буквой и цифрой."),
      h("div", { class: "row end" }, h("button", { class: "btn primary", type: "submit" }, "Сохранить")))));
  }

  api("GET", "/api/auth/me").then(function (me) { S.me = me; start(); }, function () { renderLogin(); });
})();
