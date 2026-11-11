(function () {
  "use strict";
  var h = DA.h, mount = DA.mount, api = DA.api;
  var main = document.getElementById("main");
  var meta = { accept: [], max_files: 5, max_file_mb: 15, max_image_mb: 5, org: "", kinds: [] };
  var chosen = [];
  var autoWording = "";
  var MINE = "docagent.mine";

  var STEPS = [
    ["received", "Заявление принято"],
    ["processing", "Заявление обрабатывается"],
    ["review", "Проверка данных"],
    ["confirm", "Готовится ответ"],
    ["sent", "Ответ готов"]
  ];

  /* Готовые примеры. Все люди и данные вымышлены. Без text подставляется готовая формулировка вида. */
  var SAMPLES = [
    { title: "Справка с места учёбы", kind: "Справка с места учёбы", surname: "Тестова", first: "Айдана", group: "ИС-21" },
    { title: "Академический отпуск", kind: "Академический отпуск", surname: "Образцов", first: "Данияр", group: "ЭК-31" },
    { title: "Пересдача экзамена", kind: "Пересдача экзамена", surname: "Примерова", first: "Мария", group: "ПО-22",
      text: "Прошу разрешить мне пересдачу экзамена по дисциплине «Базы данных» в связи с совпадением двух экзаменов по расписанию." },
    { title: "Материальная помощь", kind: "Материальная помощь", surname: "Демонстров", first: "Ерлан", group: "ЮР-11" },
    { title: "Место в общежитии", kind: "Место в общежитии", surname: "Макетова", first: "Дана", group: "БД-23/1" },
    { title: "Пересдача: файл Word", kind: "Пересдача экзамена", surname: "Садыков", first: "Нурлан", group: "ИС-24/2", text: "",
      file: { url: "/static/samples/zayavlenie-peresdacha.docx", name: "заявление-пересдача.docx" } }
  ];

  function kindInfo(name) {
    for (var i = 0; i < meta.kinds.length; i++) if (meta.kinds[i].name === name) return meta.kinds[i];
    return null;
  }
  function today() {
    var d = new Date(), p = function (n) { return (n < 10 ? "0" : "") + n; };
    return p(d.getDate()) + "." + p(d.getMonth() + 1) + "." + d.getFullYear();
  }

  function mine() { return DA.store(MINE) || []; }
  function remember(item) {
    var list = mine().filter(function (x) { return x.token !== item.token; });
    list.unshift(item);
    DA.store(MINE, list.slice(0, 20));
  }

  /* ---------- форма ---------- */

  function field(id, label, input) {
    return h("div", { class: "spacer" },
      h("label", { class: "lbl", for: id }, label, h("span", { class: "req", "aria-hidden": "true" }, " *")),
      input);
  }

  function renderForm() {
    var fileInput = h("input", { type: "file", id: "file", multiple: true, accept: meta.accept.join(","),
      onchange: function () { addFiles(fileInput.files); fileInput.value = ""; } });
    var drop = h("label", { class: "drop", for: "file" },
      fileInput,
      h("b", null, "Прикрепить файл (необязательно)"),
      h("span", { class: "hint" }, "Скан, фото или документ: PDF, Word, ODT, RTF, TXT, Excel, JPG, PNG. До " +
        meta.max_files + " файлов, каждый до " + meta.max_file_mb + " МБ."));
    ["dragenter", "dragover"].forEach(function (t) {
      drop.addEventListener(t, function (e) { e.preventDefault(); drop.classList.add("over"); });
    });
    ["dragleave", "drop"].forEach(function (t) {
      drop.addEventListener(t, function (e) { e.preventDefault(); drop.classList.remove("over"); });
    });
    drop.addEventListener("drop", function (e) { if (e.dataTransfer) addFiles(e.dataTransfer.files); });

    var surname = h("input", { class: "input", id: "surname", autocomplete: "family-name", maxlength: "60", required: true, oninput: preview });
    var first = h("input", { class: "input", id: "first", autocomplete: "given-name", maxlength: "60", required: true, oninput: preview });
    var group = h("input", { class: "input", id: "group", maxlength: "20", required: true, placeholder: "например, ИС-24/2", oninput: preview });
    var kind = h("select", { class: "input", id: "kind", required: true, onchange: function () { setKind(kind.value); } },
      h("option", { value: "" }, "— выберите —"),
      meta.kinds.map(function (k) { return h("option", { value: k.name }, k.name); }));
    var text = h("textarea", { class: "input", id: "text", maxlength: "20000", rows: "5", oninput: preview,
      placeholder: "Сначала выберите вид заявления: текст подставится сам." });
    var err = h("div", { class: "alert err", id: "err", role: "alert", hidden: true });
    var submit = h("button", { class: "btn primary", type: "submit", id: "submit" }, "Отправить заявление");

    var samples = h("div", { class: "card stack" },
      h("h2", null, "Готовые примеры"),
      h("p", null, "Нажмите, чтобы заполнить форму примером. Данные вымышленные."),
      h("div", { class: "samples" }, SAMPLES.map(function (s) {
        return h("button", { class: "tab", type: "button", onclick: function () { useSample(s); } }, s.title);
      })));

    var form = h("form", { class: "card stack", novalidate: true, onsubmit: function (e) { e.preventDefault(); send(); } },
      h("h2", null, "Новое заявление"),
      h("div", { class: "row form-row" }, field("surname", "Фамилия", surname), field("first", "Имя", first)),
      h("div", { class: "row form-row" }, field("group", "Группа", group), field("kind", "Вид заявления", kind)),
      h("div", null,
        h("label", { class: "lbl", for: "text" }, "Текст заявления", h("span", { class: "req", "aria-hidden": "true" }, " *")),
        text,
        h("div", { class: "hint" }, "Готовую формулировку можно дополнить или изменить. Можно не писать, если приложите файл с заявлением.")),
      h("div", { id: "preview", hidden: true },
        h("div", { class: "lbl" }, "Так будет выглядеть заявление"),
        h("div", { class: "letter paper-preview", id: "previewText" })),
      drop,
      h("ul", { class: "files", id: "fileList" }),
      err,
      h("div", { class: "row end" }, submit));

    var side = h("aside", { class: "col" }, renderMine(),
      h("div", { class: "card" },
        h("h2", null, "Как это работает"),
        h("ol", { class: "how" },
          h("li", null, h("b", null, "Заполните"), " фамилию, имя, группу и выберите вид заявления."),
          h("li", null, h("b", null, "Отправьте"), " и сохраните ссылку на статус."),
          h("li", null, h("b", null, "Ответ"), " появится на странице статуса."))));

    mount(main, h("div", { class: "stu-grid" }, h("div", { class: "col" }, samples, form), side));
    renderFiles();
  }

  function setKind(name, body) {
    var sel = document.getElementById("kind");
    var text = document.getElementById("text");
    sel.value = name;
    var info = kindInfo(name);
    var wording = info ? info.wording : "";
    // Меняем текст, только если студент его не переписал сам.
    if (body !== undefined) text.value = body;
    else if (!text.value.trim() || text.value === autoWording) text.value = wording;
    autoWording = wording;
    preview();
  }

  function preview() {
    var box = document.getElementById("preview");
    if (!box) return;
    var kind = document.getElementById("kind").value;
    var body = document.getElementById("text").value.trim();
    if (!kind || !body) { box.hidden = true; return; }
    var info = kindInfo(kind) || {};
    var surname = document.getElementById("surname").value.trim() || "Фамилия";
    var first = document.getElementById("first").value.trim() || "Имя";
    var group = document.getElementById("group").value.trim().toUpperCase() || "…";
    document.getElementById("previewText").textContent = [
      info.addressee || "Декану факультета", "от студента группы " + group, surname + " " + first, "",
      "ЗАЯВЛЕНИЕ", "", body, "", "Дата: " + today()
    ].join("\n");
    box.hidden = false;
  }

  function useSample(s) {
    document.getElementById("surname").value = s.surname;
    document.getElementById("first").value = s.first;
    document.getElementById("group").value = s.group;
    document.getElementById("text").value = "";
    setKind(s.kind, s.text);
    chosen = [];
    renderFiles();
    hideErr();
    if (s.file) {
      fetch(s.file.url).then(function (r) { return r.blob(); }).then(function (b) {
        chosen = [new File([b], s.file.name, { type: b.type || "application/octet-stream" })];
        renderFiles();
      }, function () { showErr("Не удалось загрузить файл примера."); });
    }
    document.getElementById("surname").scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function renderMine() {
    var items = mine();
    if (!items.length) return null;
    return h("div", { class: "card" },
      h("h2", null, "Мои заявления на этом устройстве"),
      h("ul", { class: "mine" }, items.map(function (x) {
        return h("li", null, h("a", { href: "/status/" + encodeURIComponent(x.token) },
          h("span", null, x.kind || "Заявление"), h("span", { class: "hint" }, DA.fmtDate(x.at))));
      })));
  }

  function showErr(msg) { var e = document.getElementById("err"); if (e) { e.hidden = false; e.textContent = msg; } }
  function hideErr() { var e = document.getElementById("err"); if (e) e.hidden = true; }

  function addFiles(fileList) {
    var problems = [];
    Array.prototype.forEach.call(fileList || [], function (f) {
      var ext = (f.name.match(/\.[^.]+$/) || [""])[0].toLowerCase();
      if (meta.accept.indexOf(ext) < 0) { problems.push("«" + f.name + "»: такой формат не принимается."); return; }
      var isImage = [".jpg", ".jpeg", ".png", ".webp", ".gif"].indexOf(ext) >= 0;
      var lim = (isImage ? meta.max_image_mb : meta.max_file_mb) * 1024 * 1024;
      if (f.size > lim) { problems.push("«" + f.name + "» больше " + (lim / 1024 / 1024) + " МБ."); return; }
      if (chosen.length >= meta.max_files) { problems.push("Можно приложить не больше " + meta.max_files + " файлов."); return; }
      if (chosen.some(function (c) { return c.name === f.name && c.size === f.size; })) return;
      chosen.push(f);
    });
    if (problems.length) showErr(problems.join(" ")); else hideErr();
    renderFiles();
  }

  function renderFiles() {
    var list = document.getElementById("fileList");
    if (!list) return;
    list.hidden = !chosen.length;
    mount(list, chosen.map(function (f, i) {
      return h("li", null,
        h("span", { class: "name", title: f.name }, f.name),
        h("small", null, DA.fmtSize(f.size)),
        h("button", { class: "btn small", type: "button", "aria-label": "Убрать файл " + f.name,
          onclick: function () { chosen.splice(i, 1); renderFiles(); } }, "Убрать"));
    }));
  }

  function send() {
    var surname = document.getElementById("surname").value.trim();
    var first = document.getElementById("first").value.trim();
    var group = document.getElementById("group").value.trim();
    var kind = document.getElementById("kind").value;
    var text = document.getElementById("text").value.trim();
    var problems = [];
    if (!surname) problems.push("Укажите фамилию.");
    if (!first) problems.push("Укажите имя.");
    if (!group) problems.push("Укажите группу.");
    if (!kind) problems.push("Выберите вид заявления.");
    if (!chosen.length && text.length < 10) problems.push("Напишите текст заявления или приложите файл.");
    if (problems.length) { showErr(problems.join(" ")); return; }
    hideErr();
    var fd = new FormData();
    chosen.forEach(function (f) { fd.append("files", f, f.name); });
    fd.append("surname", surname);
    fd.append("first_name", first);
    fd.append("group", group);
    fd.append("kind", kind);
    fd.append("text", text);
    var btn = document.getElementById("submit");
    btn.disabled = true;
    btn.textContent = "Отправляем…";
    api("POST", "/api/applications", fd, true).then(function (res) {
      remember({ token: res.token, kind: res.kind, at: new Date().toISOString() });
      chosen = [];
      renderSent(res);
    }, function (e) {
      btn.disabled = false;
      btn.textContent = "Отправить заявление";
      showErr(e.message);
    });
  }

  function renderSent(res) {
    var url = location.origin + res.status_url;
    var input = h("input", { class: "input mono", readonly: true, value: url, "aria-label": "Ссылка на статус" });
    mount(main, h("div", { class: "card stack" },
      h("div", { class: "alert ok" }, "Заявление «" + res.kind + "» отправлено."),
      h("p", null, "Сохраните ссылку: по ней видно, что с заявлением, и там же появится ответ. На этом устройстве заявление также будет в списке «Мои заявления»."),
      h("div", { class: "linkbox" }, input,
        h("button", { class: "btn", type: "button", onclick: function () {
          input.select();
          var done = function () { DA.toast("Ссылка скопирована"); };
          if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, function () { document.execCommand("copy"); done(); });
          else { document.execCommand("copy"); done(); }
        } }, "Копировать")),
      h("div", { class: "row" },
        h("a", { class: "btn primary", href: res.status_url }, "Открыть статус"),
        h("a", { class: "btn", href: "/" }, "Подать ещё одно"))));
  }

  /* ---------- статус ---------- */

  var pollTimer = null;
  function loadStatus(token) {
    api("GET", "/api/public/" + encodeURIComponent(token)).then(function (s) {
      renderStatus(token, s);
      clearTimeout(pollTimer);
      if (s.status !== "sent" && s.status !== "returned") pollTimer = setTimeout(function () { loadStatus(token); }, 5000);
    }, function (e) {
      mount(main, h("div", { class: "card stack" },
        h("div", { class: "alert err" }, e.status === 404 ? "Заявление не найдено. Проверьте ссылку." : e.message),
        h("a", { class: "btn", href: "/" }, "На главную")));
      if (e.status !== 404) pollTimer = setTimeout(function () { loadStatus(token); }, 10000);
    });
  }

  function renderStatus(token, s) {
    remember({ token: token, kind: s.kind, at: s.created_at });
    var order = STEPS.map(function (x) { return x[0]; });
    var cur = order.indexOf(s.status);
    var progress = null;
    if (s.status !== "returned") {
      progress = h("ol", { class: "progress" }, STEPS.map(function (st, i) {
        var cls = i < cur || s.status === "sent" ? "done" : (i === cur ? "now" : "");
        return h("li", { class: cls }, h("span", { class: "pd" }, cls === "done" ? "✓" : String(i + 1)), h("span", null, st[1]));
      }));
    }
    var pillCls = s.status === "sent" ? "ok" : s.status === "returned" ? "warn" : s.status === "review" ? "human" : "run";
    var docs = s.files.slice();
    if (s.has_text) docs.unshift("текст заявления");
    var blocks = [
      h("div", { class: "row" }, h("h3", null, "Заявление «" + (s.kind || "заявление") + "»"), h("span", { class: "pill " + pillCls }, s.status_label)),
      h("dl", { class: "kv" },
        h("dt", null, "Студент"), h("dd", null, s.name + (s.group ? ", группа " + s.group : "")),
        h("dt", null, "Отправлено"), h("dd", null, DA.fmtDate(s.created_at)),
        s.reg_no ? [h("dt", null, "Рег. номер"), h("dd", { class: "mono" }, s.reg_no)] : null,
        s.owner ? [h("dt", null, "Рассматривает"), h("dd", null, s.owner)] : null,
        h("dt", null, "Приложено"), h("dd", null, docs.join(", "))),
      progress
    ];
    if (s.status === "sent") {
      blocks.push(h("div", null,
        h("div", { class: "letter-head" }, "Ответ от " + DA.fmtDate(s.answered_at)),
        h("div", { class: "letter" }, s.reply)));
    } else if (s.status === "returned") {
      blocks.push(h("div", { class: "alert warn" }, "Заявление вернули на доработку."));
      blocks.push(h("div", { class: "letter" }, s.message));
      blocks.push(h("a", { class: "btn primary", href: "/" }, "Подать исправленное заявление"));
    } else {
      blocks.push(h("p", { class: "hint" }, "Страница обновляется сама."));
    }
    mount(main, h("div", { class: "card stack" }, blocks), h("p", { class: "hint back" }, h("a", { href: "/" }, "На главную")));
  }

  /* ---------- старт ---------- */

  api("GET", "/api/meta").then(function (m) {
    meta = m;
    document.getElementById("org").textContent = m.org + ": приём заявлений";
  }, function () {}).then(function () {
    var mt = location.pathname.match(/^\/status\/([A-Za-z0-9_-]+)$/);
    if (mt) loadStatus(mt[1]); else renderForm();
  });
})();
