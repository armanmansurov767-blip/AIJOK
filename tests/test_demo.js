const fs = require('fs');
const html = fs.readFileSync(require('path').join(__dirname, '..', 'index.html'), 'utf8');
const code = html.match(/<script>([\s\S]*?)<\/script>/)[1];

const els = {};
function el(id) { if (!els[id]) els[id] = { id, innerHTML: '', textContent: '', value: '', className: '' }; return els[id]; }
const handlers = {};
global.document = { getElementById: el, addEventListener: (t, f) => { handlers[t] = f; } };
global.window = global;
global.matchMedia = () => ({ matches: false });
const timers = [];
global.setTimeout = (f, ms) => { timers.push({ f, ms }); return timers.length; };
global.clearTimeout = () => {};

// ---- stub of window.claude.use("sample") ----
const calls = [];
let respond = async () => ({ text: '{}' });
let useMode = 'ok';          // ok | none
const sampleFn = async (prompt, opts) => { calls.push({ prompt, opts }); return respond(prompt, opts); };
sampleFn.limits = () => ({ images: true });
global.claude = { use: async () => (useMode === 'none' ? null : sampleFn) };

const tick = () => new Promise(r => setImmediate(r));
let fails = 0;
const ok = (c, msg) => { if (!c) { fails++; console.log('FAIL', msg); } else console.log('ok  ', msg); };
function click(a, attrs = {}) {
  const node = { getAttribute: k => (k === 'data-a' ? a : attrs[k]) };
  handlers.click({ target: { closest: () => node } });
}
const typeText = v => handlers.input({ target: { id: 'ai-text', value: v, getAttribute: () => null } });
const json = o => ({ text: JSON.stringify(o) });
const F = (value, confidence = 'high') => ({ value, confidence });
const goodFields = {
  fio: F('Садыков Нурлан Ерболатович'), group: F('ИС-24/2'), course: F('2'),
  purpose: F('в связи с совпадением двух экзаменов по расписанию'), date: F('09.11.2026'), sign: F('есть')
};

(async () => {
  (0, eval)(code);
  let D = window.DocAgentDemo;
  D.setAuto(false);
  await tick();
  let s = D.state();
  const submitSample = i => { click('stusel', { 'data-i': String(i) }); click('submit'); };
  const staff = i => click('sel', { 'data-i': String(i) });
  const toPhase = (i, ph, max = 40) => { staff(i); let g = 0; while (D.state().R[i].phase !== ph && g++ < max) click('next'); return D.state(); };
  const nextN = n => { for (let i = 0; i < n; i++) click('next'); };
  const ai = () => D.state().DOCS.length - 1;

  // ===== initial state =====
  ok(s.aiState === 'ready', 'AI becomes ready when capability exists');
  ok(s.view === 'student' && els.layout.className === 'layout v-student', 'narrow screen starts on the student view');
  ok(els.stuCompose.innerHTML.includes('настоящий ИИ'), 'composer marks own application as AI');
  ok(els.inbox.innerHTML.includes('Пока пусто'), 'staff inbox empty before submission');
  ok(els.paper.innerHTML.includes('нет документа') && /Входящих заявлений пока нет/.test(els.status.textContent), 'staff screen empty state');
  ok(els.stuList.innerHTML.includes('ещё ничего не отправляли'), 'student list empty');
  ok(els.stuMail.innerHTML.includes('Писем пока нет'), 'student mailbox empty');
  ok(/Примеры 1–4 имитация/.test(els.flag.innerHTML), 'flag says examples are simulated');
  click('view', { 'data-v': 'both' });
  ok(els.layout.className === 'layout v-both' && els.tabs.innerHTML.includes('aria-pressed="true">Рядом'), 'switch to side-by-side');
  click('view', { 'data-v': 'staff' }); ok(els.layout.className === 'layout v-staff', 'switch to staff view');
  click('view', { 'data-v': 'student' });
  ok(els.stuCompose.innerHTML.includes('Справка с места учёбы') && els.stuCompose.innerHTML.includes('Тестова'), 'composer previews the sample application');
  ok(!els.stuCompose.innerHTML.includes('fld '), 'student preview has no agent highlights');

  // ===== doc 0: clean path, auto-selected on staff screen =====
  submitSample(0); s = D.state();
  ok(s.R[0].phase === 'intake' && s.sel === 0, 'submit starts the agent and opens it for staff');
  ok(els.stuList.innerHTML.includes('Принято, обрабатывается'), 'student sees "accepted, processing"');
  ok(els.stuCompose.innerHTML.includes('Заявление «Справка с места учёбы» отправлено'), 'student gets a sent note');
  ok(els.stuCompose.innerHTML.includes('Уже отправлено') && els.stuCompose.innerHTML.includes('data-a="submit" disabled'), 'sample cannot be sent twice');
  ok(els.inbox.innerHTML.includes('Справка с места учёбы'), 'staff inbox shows the application');
  s = toPhase(0, 'confirm');
  ok(s.R[0].phase === 'confirm' && s.R[0].manual === false && s.R[0].st.manual === 'skipped', 'doc0 reaches confirm without manual');
  ok(s.J.length === 1 && s.J[0].no === 'ВХ-001', 'doc0 journal entry ВХ-001');
  ok(/Айдана Ерлановна/.test(s.R[0].reply), 'reply uses name+patronymic');
  ok(els.stuList.innerHTML.includes('Сотрудник готовит ответ'), 'student sees "staff is preparing the reply"');
  ok(els.stuMail.innerHTML.includes('Писем пока нет'), 'no mail before staff confirms');
  ok(els.result.innerHTML.includes('data-a="send"'), 'confirm button is on the staff screen');
  ok(!els.stuCompose.innerHTML.includes('data-a="send"') && !els.stuList.innerHTML.includes('data-a="send"'), 'student screen has no confirm button');
  handlers.input({ target: { id: 'reply', value: s.R[0].reply + '\nДобавлено сотрудником.', getAttribute: () => null } });
  click('send'); s = D.state();
  ok(s.R[0].phase === 'done' && s.J[0].sent === true, 'doc0 sent');
  ok(els.stuMail.innerHTML.includes('новое письмо'), 'student mailbox shows new mail after send');
  ok(els.stuMail.innerHTML.includes('Заявление принято: Справка с места учёбы, ВХ-001'), 'mail subject has type and number');
  ok(els.stuMail.innerHTML.includes('Тестова Айдана Ерлановна') && els.stuMail.innerHTML.includes('Добавлено сотрудником.'), 'mail shows recipient and the staff-edited text');
  ok(els.stuList.innerHTML.includes('Ответ получен'), 'student status "reply received"');
  ok(els.tabs.innerHTML.includes('<span class="badge">1</span>'), 'student tab badge counts the mail');
  ok(!els.result.innerHTML.includes('mail-item'), 'mail is not duplicated on the staff screen');
  ok(/^\d\d:\d\d$/.test(s.R[0].sentAt), 'mail has a time');

  // ===== doc 1: missing fields =====
  submitSample(1); s = D.state();
  ok(s.sel === 0, 'staff selection is not stolen by a new submission');
  staff(1); let guard = 0;
  while (D.state().R[1].phase !== 'manual' && guard++ < 40) click('next');
  s = D.state();
  ok(s.R[1].phase === 'manual' && s.R[1].blocked, 'doc1 blocks at manual');
  ok(s.R[1].issues.join() === 'date,sign', 'doc1 issues date,sign');
  ok(els.stuList.innerHTML.includes('Проверяет сотрудник'), 'student sees "staff is checking"');
  ok(els.tabs.innerHTML.includes('Штаб<span class="badge">1</span>'), 'staff tab badge counts waiting work');
  ok(els.result.innerHTML.includes('data-a="resume" disabled'), 'resume disabled until fixed');
  els['fix-date'] = { value: 'abc' }; els['err-date'] = { textContent: '' };
  click('fix', { 'data-k': 'date' });
  ok(els['err-date'].textContent.includes('ДД.ММ.ГГГГ'), 'invalid date rejected');
  els['fix-date'].value = '10.11.2026'; click('fix', { 'data-k': 'date' });
  click('signok'); s = D.state();
  ok(s.R[1].fixed.date && s.R[1].fixed.sign, 'doc1 fixes applied');
  ok(!els.result.innerHTML.includes('data-a="resume" disabled'), 'resume enabled');
  click('resume'); s = D.state();
  ok(s.R[1].phase === 'journal', 'doc1 resumed to journal');
  s = toPhase(1, 'confirm', 10);
  ok(s.R[1].phase === 'confirm' && s.J.length === 2 && s.J[1].manual === true, 'doc1 reaches confirm with manual flag');
  click('send'); s = D.state(); ok(s.R[1].status === 'done', 'doc1 done');
  ok(els.stuMail.innerHTML.indexOf('Образцов') < els.stuMail.innerHTML.indexOf('Тестова'), 'newest mail first');

  // ===== doc 2: low confidence; doc 3 submitted while staff is busy =====
  submitSample(2);
  s = toPhase(2, 'manual');
  ok(s.R[2].issues.join() === 'group', 'doc2 issue group only');
  ok(els.result.innerHTML.includes('value="ПО-22"'), 'doc2 input prefilled with agent guess');
  submitSample(3);
  ok(D.state().sel === 2 && D.state().R[3].phase === 'intake', 'student submits while staff works on another application');
  ok(els.result.innerHTML.includes('value="ПО-22"'), 'staff form not disturbed by the new submission');
  els['fix-group'] = { value: 'ПО-22' }; els['err-group'] = { textContent: '' }; click('fix', { 'data-k': 'group' });
  click('resume');
  s = toPhase(2, 'confirm', 10);
  ok(s.R[2].phase === 'confirm', 'doc2 reaches confirm');

  // doc 3: agent works alone on timers
  handlers.change({ target: { id: 'auto', checked: true } }); D.setAuto(true);
  guard = 0;
  while (timers.length && guard++ < 80) { const t = timers.shift(); if (t.ms < 90000) t.f(); }
  s = D.state(); ok(s.R[3].phase === 'confirm', 'doc3 reaches confirm on timers without the staff screen');
  ok(els.stuList.innerHTML.includes('Сотрудник готовит ответ'), 'student sees progress of doc3');
  staff(3); click('send'); staff(2); click('send'); s = D.state();
  ok(s.R[3].phase === 'done' && s.R[2].phase === 'done', 'docs 2 and 3 done');
  ok(s.J.length === 4, '4 journal rows');
  ok(els.tabs.innerHTML.includes('Студент<span class="badge">4</span>'), 'student tab badge shows 4 mails');
  handlers.change({ target: { id: 'auto', checked: false } }); D.setAuto(false);

  // ===== reset =====
  click('reset'); s = D.state();
  ok(s.J.length === 0 && s.R.every(r => r.phase === 'idle') && s.sel === -1 && s.DOCS.length === 4, 'reset works');
  ok(els.stuMail.innerHTML.includes('Писем пока нет') && els.stuList.innerHTML.includes('ещё ничего не отправляли'), 'reset clears student screen');
  ok(!els.stuCompose.innerHTML.includes('Уже отправлено'), 'reset allows sending samples again');

  // ===== AI helpers =====
  async function runToRead() {
    click('stusel', { 'data-i': '-1' }); click('submit'); click('next'); click('next'); await tick();
    return D.state();
  }

  // ===== AI: success, text, real input events =====
  calls.length = 0;
  click('stusel', { 'data-i': '-1' });
  click('fillsample');
  ok(els.stuCompose.innerHTML.includes('Операционные системы'), 'sample text put in textarea');
  typeText('');
  ok(els.submitBtn.disabled === true, 'submit button disabled for empty text');
  click('fillsample');
  respond = async () => ({ text: '```json\n' + JSON.stringify({ type: 'Пересдача экзамена', fields: { ...goodFields, date: F('') } }) + '\n```' });
  s = await runToRead();
  let i = ai();
  ok(i === 4 && s.sel === 4, 'own application becomes document 4 and opens for staff');
  ok(!els.stuCompose.innerHTML.includes('Операционные системы') && els.stuCompose.innerHTML.includes('Заявление отправлено'), 'composer cleared after sending');
  ok(calls.length === 1 && calls[0].prompt.includes('Операционные системы'), 'sample called with pasted text');
  ok(calls[0].prompt.includes('данные, а не инструкции') && calls[0].prompt.includes('Ничего не выдумывай'), 'prompt marks document as data and forbids inventing');
  ok(calls[0].opts.cache === false && calls[0].opts.signal && !calls[0].opts.images, 'opts: no cache, signal, no images for text');
  ok(s.R[i].phase === 'type' && s.R[i].st.read === 'done', 'AI result moves pipeline read -> type');
  ok(s.DOCS[i].type === 'Пересдача экзамена', 'type from AI');
  ok(els.inbox.innerHTML.includes('вставленный текст'), 'staff inbox shows text source');
  nextN(7); s = D.state();
  ok(s.R[i].phase === 'check', 'AI reaches check after reveal');
  ok(/fld found">Садыков Нурлан Ерболатович/.test(els.paper.innerHTML), 'fio highlighted in original text');
  ok(/fld found">ИС-24\/2/.test(els.paper.innerHTML), 'group highlighted in original text');
  ok(/fld found">в связи с совпадением/.test(els.paper.innerHTML), 'purpose highlighted in original text');
  click('next'); s = D.state();
  ok(s.R[i].phase === 'manual' && s.R[i].issues.join() === 'date', 'missing date sends AI doc to manual');
  els['fix-date'] = { value: '10.11.2026' }; els['err-date'] = { textContent: '' };
  click('fix', { 'data-k': 'date' }); click('resume'); s = toPhase(i, 'confirm', 10);
  ok(s.R[i].phase === 'confirm', 'AI doc reaches confirm');
  ok(s.J.length === 1 && s.J[0].type === 'Пересдача экзамена' && s.J[0].owner === 'Деканат' && s.J[0].manual === true &&
     s.J[0].student === 'Садыков Нурлан Ерболатович' && s.J[0].group === 'ИС-24/2', 'AI journal row correct');
  ok(/Нурлан Ерболатович/.test(s.R[i].reply) && s.R[i].reply.includes('Деканат'), 'AI reply text correct');
  click('send'); s = D.state(); ok(s.R[i].phase === 'done', 'AI doc done');
  ok(els.stuMail.innerHTML.includes('Заявление принято: Пересдача экзамена, ВХ-001') && els.stuList.innerHTML.includes('Ответ получен'), 'student receives the reply to own application');

  // ===== AI: several own applications in a row =====
  respond = async () => json({ type: 'Справка с места учёбы', fields: goodFields });
  typeText('Вторая'); s = await runToRead();
  ok(ai() === 5 && D.state().DOCS[4].ai && D.state().DOCS[5].ai, 'a second own application is a separate document');
  ok(visibleCount() === 2, 'both own applications are listed');
  function visibleCount() { return (els.stuList.innerHTML.match(/<li>/g) || []).length; }

  // ===== AI: field normalisation =====
  click('reset');
  typeText('Заявление. Иванов');
  respond = async () => json({ type: 'Что-то непонятное', fields: {
    fio: { value: null, confidence: 'high' }, group: { value: 'ИС-1', confidence: 'weird' },
    course: F('2 курс'), purpose: F('', 'high'), date: F('9.11.2026'), sign: F('подпись видна') } });
  click('stusel', { 'data-i': '-1' }); typeText('Заявление. Иванов');
  s = await runToRead(); i = ai();
  const f4 = s.DOCS[i].fields;
  ok(s.DOCS[i].type === 'Другое' && s.DOCS[i].typeConf === 'low', 'unknown type becomes «Другое» with low confidence');
  ok(f4.fio.c === 'missing' && f4.fio.v === '', 'null value -> missing');
  ok(f4.group.c === 'low', 'invalid confidence -> low');
  ok(f4.course.v === '2' && f4.course.c === 'high', 'course "2 курс" -> 2');
  ok(f4.purpose.c === 'missing', 'empty value cannot be high');
  ok(f4.date.c === 'low', 'bad date format -> low');
  ok(f4.sign.v === 'есть' && f4.sign.c === 'high', 'sign normalised');

  // ===== AI: type «Другое» goes to staff, who choose a type =====
  click('reset');
  click('stusel', { 'data-i': '-1' }); typeText('Заявление');
  respond = async () => json({ type: 'Другое', fields: goodFields });
  s = await runToRead(); i = ai();
  nextN(8); s = D.state();
  ok(s.R[i].phase === 'manual' && s.R[i].issues.join() === 'type', '«Другое» -> manual with type issue');
  ok(els.result.innerHTML.includes('<select') && !els.result.innerHTML.includes('<option>Другое'), 'staff select has real types only');
  els['fix-type'] = { value: '' }; els['err-type'] = { textContent: '' };
  click('fix', { 'data-k': 'type' });
  ok(els['err-type'].textContent.length > 0, 'empty type rejected');
  els['fix-type'].value = 'Академический отпуск'; click('fix', { 'data-k': 'type' });
  click('resume'); s = toPhase(i, 'confirm', 10);
  ok(s.J[0].type === 'Академический отпуск' && s.J[0].owner === 'Деканат', 'staff-chosen type used in journal and owner');

  // ===== AI: clean path, all high, no manual =====
  click('reset');
  click('stusel', { 'data-i': '-1' }); typeText('Справка нужна. Иванова');
  respond = async () => json({ type: 'Справка с места учёбы', fields: goodFields });
  s = await runToRead(); i = ai(); nextN(8); s = D.state();
  ok(s.R[i].phase === 'journal' && s.R[i].manual === false && s.R[i].st.manual === 'skipped', 'all-high AI doc skips manual');
  click('next'); s = D.state();
  ok(s.J.length === 1 && s.J[0].owner === 'Учебная часть' && s.J[0].manual === false, 'owner is Учебная часть, no manual flag');

  // ===== AI: errors withdraw the application and give the text back =====
  async function failWith(err, expected, name) {
    click('reset'); click('stusel', { 'data-i': '-1' }); typeText('Какой-то текст');
    respond = async () => { throw err; };
    s = await runToRead();
    ok(s.DOCS[4].gone === true && s.R[4].phase === 'idle', name + ': application withdrawn');
    ok(s.aiError.includes(expected) && s.aiError.includes('не отправлено'), name + ': message "' + expected + '"');
    ok(els.stuCompose.innerHTML.includes(expected), name + ': shown on the student screen');
    ok(els.stuCompose.innerHTML.includes('Какой-то текст') && s.compSel === -1, name + ': pasted text kept for retry');
    ok(els.stuList.innerHTML.includes('ещё ничего не отправляли') && els.inbox.innerHTML.includes('Пока пусто') && s.sel === -1, name + ': nothing in the queues');
    ok(s.J.length === 0, name + ': nothing in the journal');
    typeText('Какой-то текст 2');
    ok(D.state().aiError === '', name + ': error cleared on typing');
  }
  await failWith({ code: 'rate_limited' }, 'Слишком много запросов', 'rate_limited');
  await failWith(new Error('boom'), 'boom', 'generic error');
  await failWith(Object.assign(new Error('x'), { name: 'AbortError' }), 'Превышено время', 'abort');
  click('reset'); click('stusel', { 'data-i': '-1' }); typeText('Текст');
  respond = async () => ({ text: 'Извините, не могу' });
  s = await runToRead();
  ok(s.aiError.includes('неожиданном формате') && s.R[4].phase === 'idle', 'non-JSON answer handled');
  ok(s.aiState === 'ready', 'AI stays ready after soft errors');
  // retry after failure works
  respond = async () => json({ type: 'Справка с места учёбы', fields: goodFields });
  click('submit'); click('next'); click('next'); await tick(); s = D.state();
  ok(s.DOCS.length === 6 && s.DOCS[4].gone && !s.DOCS[5].gone && s.R[5].phase === 'type' && s.sel === 5, 'retry after failure sends a fresh application');
  ok(s.aiError === '', 'error cleared after successful retry');
  respond = async () => ({ text: '{"type": ' });
  click('reset'); click('stusel', { 'data-i': '-1' }); typeText('Текст');
  s = await runToRead();
  ok(s.aiError.includes('неожиданном формате'), 'broken JSON handled');

  // ===== AI: empty input is not sent =====
  click('reset'); click('stusel', { 'data-i': '-1' });
  ok(els.stuCompose.innerHTML.includes('data-a="submit" disabled'), 'submit disabled for empty input');
  click('submit'); ok(D.state().DOCS.length === 4, 'empty input does not send');
  typeText('   \n  '); click('submit'); ok(D.state().DOCS.length === 4, 'whitespace input does not send');

  // ===== AI: image =====
  click('reset'); calls.length = 0;
  click('stusel', { 'data-i': '-1' });
  D.setInput('', { name: 'scan.jpg', size: 1000 });
  respond = async () => json({ type: 'Материальная помощь', fields: goodFields });
  s = await runToRead();
  ok(calls.length === 1 && calls[0].prompt.includes('Заявление дано как изображение') && !calls[0].prompt.includes('Текст заявления'), 'image prompt without text');
  ok(calls[0].opts.images && calls[0].opts.images[0].name === 'scan.jpg', 'image passed to sample');
  ok(els.paper.innerHTML.includes('<img class="scan" src="blob:test"'), 'scan shown on the staff screen');
  ok(s.DOCS[4].lines.length === 0 && s.DOCS[4].file === 'scan.jpg', 'no text highlights for image, file name kept');

  // ===== AI: file size limit =====
  click('reset'); click('stusel', { 'data-i': '-1' });
  handlers.change({ target: { id: 'ai-file', files: [{ name: 'big.jpg', size: 6 * 1024 * 1024 }] } });
  ok(D.state().aiError.includes('5 МБ') && els.stuCompose.innerHTML.includes('5 МБ'), 'file over 5 MB rejected');
  click('submit'); ok(D.state().DOCS.length === 4, 'rejected file is not sent');

  // ===== AI: XSS through the whole chain =====
  click('reset'); click('stusel', { 'data-i': '-1' });
  typeText('<script>alert(1)</script>\nЗаявление');
  respond = async () => json({ type: 'Справка с места учёбы', fields: { ...goodFields, fio: F('<img src=x onerror=alert(1)>') } });
  s = await runToRead(); i = ai(); nextN(7);
  ok(!els.paper.innerHTML.includes('<script>') && els.paper.innerHTML.includes('&lt;script&gt;'), 'pasted markup escaped on the staff screen');
  ok(!els.result.innerHTML.includes('<img src=x') && els.result.innerHTML.includes('&lt;img'), 'AI value escaped in result');
  nextN(1); toPhase(i, 'confirm', 10); click('send');
  ok(!els.stuMail.innerHTML.includes('<img src=x') && els.stuMail.innerHTML.includes('&lt;img'), 'mail on the student screen escapes markup');

  // ===== AI: reset while request is pending =====
  click('reset'); click('stusel', { 'data-i': '-1' }); typeText('Текст');
  let resolveLater;
  respond = () => new Promise(r => { resolveLater = r; });
  click('submit'); click('next'); click('next'); await tick();
  ok(D.state().R[4].aiPending === true && D.state().R[4].blocked, 'request pending blocks the pipeline');
  click('next'); ok(D.state().R[4].phase === 'read', 'next does nothing while pending');
  ok(els.stuList.innerHTML.includes('Принято, обрабатывается'), 'student sees the pending application as processing');
  click('reset');
  resolveLater(json({ type: 'Справка с места учёбы', fields: goodFields })); await tick();
  s = D.state();
  ok(s.DOCS.length === 4 && s.J.length === 0 && s.sel === -1 && s.R.every(r => r.phase === 'idle'), 'late answer after reset is ignored');

  // ===== AI: capability not granted =====
  click('reset'); click('stusel', { 'data-i': '-1' }); typeText('Текст');
  useMode = 'none';
  s = await runToRead();
  ok(s.aiState === 'off' && s.aiError.includes('разрешение'), 'not granted -> AI off with message');
  ok(els.stuCompose.innerHTML.includes('ИИ в этом окне недоступен') && els.stuCompose.innerHTML.includes('ИИ недоступен'), 'composer explains AI is off');
  ok(els.stuCompose.innerHTML.includes('data-a="submit" disabled'), 'cannot send own application when AI is off');
  const lenOff = D.state().DOCS.length;
  click('submit'); ok(D.state().DOCS.length === lenOff, 'send blocked when AI is off');
  click('stusel', { 'data-i': '1' }); click('submit');
  ok(D.state().R[1].phase === 'intake', 'samples still work when AI is off');
  useMode = 'ok';

  // ===== no capability at all / images unsupported (fresh evaluation) =====
  delete global.claude;
  (0, eval)(code); D = window.DocAgentDemo; D.setAuto(false); await tick();
  ok(D.state().aiState === 'off', 'no window.claude -> AI off');
  ok(/Демо-имитация/.test(els.flag.innerHTML), 'flag says pure simulation without AI');
  click('stusel', { 'data-i': '0' }); click('submit'); click('next'); click('next');
  ok(D.state().R[0].phase === 'type', 'simulated examples still work without AI');

  global.claude = { use: async () => { const f = async () => ({ text: '{}' }); f.limits = async () => ({ images: false }); return f; } };
  (0, eval)(code); D = window.DocAgentDemo; D.setAuto(false); await tick();
  click('stusel', { 'data-i': '-1' });
  ok(D.state().aiState === 'ready', 'ready with async limits()');
  ok(els.stuCompose.innerHTML.includes('ai-text') && !els.stuCompose.innerHTML.includes('ai-file'), 'no file input when images unsupported');

  console.log(fails ? ('FAILED ' + fails) : 'ALL OK');
  process.exit(fails ? 1 : 0);
})().catch(e => { console.log('CRASH', e && e.stack || e); process.exit(2); });
