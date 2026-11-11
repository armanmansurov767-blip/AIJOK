(function () {
  "use strict";
  var h = DA.h, mount = DA.mount, api = DA.api;
  var main = document.getElementById("main");
  var meta = { accept: [], max_files: 5, max_file_mb: 15, max_image_mb: 5, org: "" };
  var chosen = [];
  var MINE = "docagent.mine";

  var STEPS = [
    ["received", "Заявление принято"],
    ["processing", "Агент читает документ"],
    ["review", "Проверка сотрудником"],
    ["confirm", "Сотрудник готовит ответ"],
    ["sent", "Ответ отправлен"]
  ];

  function mine() { return DA.store(MINE) || []; }
  function remember(item) {
    var list = mine().filter(function (x) { return x.token !== item.token; });
    list.unshift(item);
    DA.store(MINE, list.slice(0, 20));
  }

  /* ---------- форма ---------- */

  function renderForm(errorText) {
    var fileInput = h("input", { type: "file", id: "file", multiple: true, accept: meta.accept.join(","),
      onchange: function () { addFiles(fileInput.files); fileInput.value = ""; } });
    var drop = h("label", { class: "drop", for: "file" },
      fileInput,
      h("b", null, "Выберите файлы или перетащите их сюда"),
      h("span", { class: "hint" }, "PDF, Word (DOCX), ODT, RTF, TXT, Excel (XLSX), фото JPG/PNG/WEBP. До " +
        meta.max_files + " файлов, каждый до " + meta.max_file_mb + " МБ, фото до " + meta.max_image_mb + " МБ."));
    ["dragenter", "dragover"].forEach(function (t) {
      drop.addEventListener(t, function (e) { e.preventDefault(); drop.classList.add("over"); });
    });
    ["dragleave", "drop"].forEach(function (t) {
      drop.addEventListener(t, function (e) { e.preventDefault(); drop.classList.remove("over"); });
    });
    drop.addEventListener("drop", function (e) { if (e.dataTransfer) addFiles(e.dataTransfer.files); });

    var list = h("ul", { class: "files", id: "fileList" });
    var text = h("textarea", { class: "input", id: "text", maxlength: "20000",
      placeholder: "Например:\nДекану факультета\nот студента группы ИС-24/2, 2 курса\nИванова Ивана Ивановича\n\nЗАЯВЛЕНИЕ\nПрошу…" });
    var name = h("input", { class: "input", id: "name", autocomplete: "name", maxlength: "150" });
    var email = h("input", { class: "input", id: "email", type: "email", autocomplete: "email", maxlength: "254" });
    var consent = h("input", { type: "checkbox", id: "consent" });
    var err = h("div", { class: "alert err", id: "err", role: "alert", hidden: !errorText }, errorText || "");
    var submit = h("button", { class: "btn primary", type: "submit", id: "submit" }, "Отправить");

    var form = h("form", { class: "card stack", novalidate: true, onsubmit: function (e) { e.preventDefault(); send(); } },
      h("h2", null, "Подать заявление или документ"),
      drop, list,
      h("div", null, h("label", { class: "lbl", for: "text" }, "Или вставьте текст заявления"), text),
      h("div", { class: "row" },
        h("div", { class: "spacer" }, h("label", { class: "lbl", for: "name" }, "Ваше имя (необязательно)"), name),
        h("div", { class: "spacer" }, h("label", { class: "lbl", for: "email" }, "Почта для ответа"), email)),
      h("p", { class: "hint" }, "Без почты ответ будет только на странице статуса: сохраните ссылку, которую получите после отправки."),
      h("label", { class: "check", for: "consent" }, consent,
        h("span", null, "Я согласен(на) на обработку персональных данных из заявления для его рассмотрения. Документы читает ИИ-агент, решение принимает сотрудник.")),
      err,
      h("div", { class: "row end" }, submit));

    var side = h("aside", { class: "col" },
      h("div", { class: "card" },
        h("h2", null, "Как это работает"),
        h("ol", { class: "how" },
          h("li", null, h("b", null, "Вы отправляете"), " заявление: файл, фото или текст."),
          h("li", null, h("b", null, "Агент читает"), " документ, определяет тип и данные."),
          h("li", null, h("b", null, "Сотрудник проверяет"), " и подтверждает ответ."),
          h("li", null, h("b", null, "Вы получаете ответ"), " на почту и на странице статуса."))),
      renderMine());

    mount(main, h("div", { class: "stu-grid" }, form, side));
    renderFiles();
  }

  function renderMine() {
    var items = mine();
    if (!items.length) return null;
    return h("div", { class: "card" },
      h("h2", null, "Мои обращения на этом устройстве"),
      h("ul", { class: "mine" }, items.map(function (x) {
        return h("li", null, h("a", { href: "/status/" + encodeURIComponent(x.token) },
          h("span", null, x.number), h("span", { class: "hint" }, DA.fmtDate(x.at))));
      })));
  }

  function addFiles(fileList) {
    var err = document.getElementById("err");
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
    err.hidden = !problems.length;
    err.textContent = problems.join(" ");
    renderFiles();
  }

  function renderFiles() {
    var list = document.getElementById("fileList");
    if (!list) return;
    mount(list, chosen.map(function (f, i) {
      return h("li", null,
        h("span", { class: "name", title: f.name }, f.name),
        h("small", null, DA.fmtSize(f.size)),
        h("button", { class: "btn small", type: "button", "aria-label": "Убрать файл " + f.name,
          onclick: function () { chosen.splice(i, 1); renderFiles(); } }, "Убрать"));
    }));
  }

  function send() {
    var err = document.getElementById("err");
    var text = document.getElementById("text").value.trim();
    var email = document.getElementById("email").value.trim();
    var problems = [];
    if (!chosen.length && text.length < 20) problems.push("Приложите файл или вставьте текст заявления.");
    if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) problems.push("Проверьте адрес почты.");
    if (!document.getElementById("consent").checked) problems.push("Отметьте согласие на обработку данных.");
    if (problems.length) { err.hidden = false; err.textContent = problems.join(" "); return; }
    err.hidden = true;
    var fd = new FormData();
    chosen.forEach(function (f) { fd.append("files", f, f.name); });
    fd.append("text", text);
    fd.append("email", email);
    fd.append("name", document.getElementById("name").value.trim());
    fd.append("consent", "on");
    var btn = document.getElementById("submit");
    btn.disabled = true;
    btn.textContent = "Отправляем…";
    api("POST", "/api/applications", fd, true).then(function (res) {
      remember({ token: res.token, number: res.number, at: new Date().toISOString() });
      chosen = [];
      renderSent(res);
    }, function (e) {
      btn.disabled = false;
      btn.textContent = "Отправить";
      err.hidden = false;
      err.textContent = e.message;
    });
  }

  function renderSent(res) {
    var url = location.origin + res.status_url;
    var input = h("input", { class: "input mono", readonly: true, value: url, "aria-label": "Ссылка на статус" });
    mount(main, h("div", { class: "card stack" },
      h("div", { class: "alert ok" }, "Обращение " + res.number + " отправлено. Агент уже начал его обрабатывать."),
      h("p", null, "Сохраните ссылку: по ней видно, что с обращением, и там же будет ответ."),
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
        h("div", { class: "alert err" }, e.status === 404 ? "Обращение не найдено. Проверьте ссылку." : e.message),
        h("a", { class: "btn", href: "/" }, "На главную")));
      if (e.status !== 404) pollTimer = setTimeout(function () { loadStatus(token); }, 10000);
    });
  }

  function renderStatus(token, s) {
    remember({ token: token, number: s.number, at: s.created_at });
    var order = STEPS.map(function (x) { return x[0]; });
    var cur = order.indexOf(s.status);
    var progress = null;
    if (s.status !== "returned") {
      progress = h("ol", { class: "progress" }, STEPS.map(function (st, i) {
        var cls = i < cur || s.status === "sent" ? "done" : (i === cur ? "now" : "");
        if (st[0] === "review" && cur > i && s.status !== "sent") cls = "done";
        return h("li", { class: cls }, h("span", { class: "pd" }, cls === "done" ? "✓" : String(i + 1)), h("span", null, st[1]));
      }));
    }
    var pillCls = s.status === "sent" ? "ok" : s.status === "returned" ? "warn" : s.status === "review" ? "human" : "run";
    var blocks = [
      h("div", { class: "row" }, h("h3", null, "Обращение " + s.number), h("span", { class: "pill " + pillCls }, s.status_label)),
      h("dl", { class: "kv" },
        h("dt", null, "Отправлено"), h("dd", null, DA.fmtDate(s.created_at)),
        s.reg_no ? [h("dt", null, "Рег. номер"), h("dd", { class: "mono" }, s.reg_no)] : null,
        s.type ? [h("dt", null, "Тип"), h("dd", null, s.type)] : null,
        s.owner ? [h("dt", null, "Рассматривает"), h("dd", null, s.owner)] : null,
        h("dt", null, "Документы"), h("dd", null, (s.files.length ? s.files.join(", ") : "") + (s.has_text ? (s.files.length ? ", " : "") + "текст" : ""))),
      progress
    ];
    if (s.status === "sent") {
      blocks.push(h("div", null,
        h("div", { class: "letter-head" }, "Ответ от " + DA.fmtDate(s.answered_at) + (s.email ? ", копия отправлена на вашу почту" : "")),
        h("div", { class: "letter" }, s.reply)));
    } else if (s.status === "returned") {
      blocks.push(h("div", { class: "alert warn" }, "Сотрудник вернул обращение на доработку."));
      blocks.push(h("div", { class: "letter" }, s.message));
      blocks.push(h("a", { class: "btn primary", href: "/" }, "Подать исправленное заявление"));
    } else {
      blocks.push(h("p", { class: "hint" }, "Страница обновляется сама. Ответ отправляется только после проверки сотрудником."));
    }
    mount(main, h("div", { class: "card stack" }, blocks), h("p", { class: "hint" }, h("a", { href: "/" }, "Подать новое обращение")));
  }

  /* ---------- старт ---------- */

  api("GET", "/api/meta").then(function (m) {
    meta = m;
    document.getElementById("org").textContent = m.org + ": приём заявлений и документов";
  }, function () {}).then(function () {
    var mt = location.pathname.match(/^\/status\/([A-Za-z0-9_-]+)$/);
    if (mt) loadStatus(mt[1]); else renderForm();
  });
})();
