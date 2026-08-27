/* learn.js: the curriculum page, now the hub. The skill-tree graph sits on
   the left (NTGraph, the same component /practice uses); the open lesson on
   the right. /learn shows a welcome panel; /learn#<id> opens one lesson.
   Content comes from /api/curriculum (parsed from backend/ntgen/curriculum.md,
   validated against the DAG).

   Lessons are gated: a lesson stays locked until every prerequisite is
   complete (a passed 2-of-3 practice round, or mastery the diagnostic
   inferred). Rounds are played right here, inside the lesson. New students
   run the 6-question placement diagnostic here too. The gate truth is the
   server's sticky unlocked set, the same one the problem-serving 403 reads;
   this file only renders it. If the state fetch fails the path renders
   neutral and open: a broken server should degrade to a readable book,
   not a locked door.

   The shell (graph column + main column) is built exactly once. graph.js
   keeps closure references to its SVG nodes, so the graph must never be
   destroyed by an innerHTML rebuild; render() swaps only #learn-main. */

let CUR = null;         // /api/curriculum payload, fetched once
let GRAPH = null;       // /api/graph payload {nodes, edges}, fetched once
let STATUS = null;      // FULL /api/state payload {nodes, frontier}, or null
let STUDENT = null;     // server-side student key from /api/login
let SHELL_BUILT = false;

/* Curriculum prose has variable-base powers (a^k, p^e, a^(p−1)) that the
   prompt renderer deliberately ignores; here every caret is math. */
function prettyLesson(text) {
  return escapeHtml(text)
    .replace(/(\w+)\^\(([^)]+)\)/g, "$1<sup>$2</sup>")
    .replace(/(\w+)\^(-?\w+)/g, "$1<sup>$2</sup>")
    .replace(/\)\^(-?\w+)/g, ")<sup>$1</sup>")
    .replace(/&lt;=/g, "≤")
    .replace(/&gt;=/g, "≥");
}

function feedback(elId, msg, kind) {
  const f = $(elId);
  f.textContent = msg;
  f.className = "feedback" + (kind ? " " + kind : "");
}

const PILL = {
  complete: ["Complete", "complete"],
  ready: ["Ready", "ready"],
  locked: ["Locked", "locked"],
};

/* Tri-state for a lesson, derived from server fields only: `completed`
   (passed round or inferred mastery) and `lesson_unlocked` (the sticky
   set). No prerequisite arithmetic happens on the client. */
function lessonState(id) {
  if (!STATUS || !STATUS.nodes[id]) return null;
  if (STATUS.nodes[id].completed) return "complete";
  if (STATUS.nodes[id].lesson_unlocked) return "ready";
  return "locked";
}

/* ------------------------------------------------ shell (built once) */

function buildShell() {
  $("curriculum-body").innerHTML = `<div class="learn-layout">
    <aside class="learn-side">
      <div class="map-head">
        <div>
          <div class="eyebrow">Skill map</div>
          <div class="map-sub">Click a node to open its lesson.</div>
        </div>
        <span class="map-count" id="learn-count"></span>
      </div>
      <div class="graph-pane card"><div id="graph-holder"></div></div>
      <div class="legend">
        <span><i class="dot mastered"></i> complete</span>
        <span><i class="dot frontier"></i> ready to practice</span>
        <span><i class="dot locked"></i> locked</span>
      </div>
    </aside>
    <main class="learn-main" id="learn-main"></main>
  </div>`;
  NTGraph.init($("graph-holder"), GRAPH, onNodeClick);
  SHELL_BUILT = true;
}

function paintAll() {
  if (!STATUS) return;   // state fetch failed: neutral path, no colours
  NTGraph.paint(STATUS);
  // "complete" counts lesson truth (passed round or inferred mastery),
  // not the graph's mastered colour: a lesson can be complete while the
  // model's belief still sits below 95%.
  const authored = GRAPH.nodes.filter((n) => n.authored);
  const done = authored.filter(
    (n) => STATUS.nodes[n.id] && STATUS.nodes[n.id].completed).length;
  $("learn-count").textContent = `${done} / ${authored.length} complete`;
}

function onNodeClick(id) {
  if (!CUR.lessons[id]) {
    toast("That skill is beyond the authored lessons for now.");
    return;
  }
  location.hash = id;   // render() fires via hashchange
}

/* Everything after login funnels through here; `status` is a payload we
   already hold (the diagnostic finish response) or null to fetch fresh. */
async function enterPath(status) {
  if (!CUR) {
    const r = await api("/api/curriculum");
    if (serverDown(r.error)) {
      toast("Lost the server. Is python3 backend/app.py still running?");
      return;
    }
    if (r.error) { toast("Couldn't load the lessons."); return; }
    CUR = r;
  }
  if (!GRAPH) {
    const g = await api("/api/graph");
    if (g.error) { toast("Couldn't load the skill map."); return; }
    GRAPH = g;
  }
  if (status) {
    STATUS = status;
  } else {
    const st = await api(`/api/state?student=${encodeURIComponent(STUDENT)}`);
    if (!st.error && st.nodes) STATUS = st;
  }
  if (!SHELL_BUILT) buildShell();
  paintAll();
  render();
}

/* ------------------------------------------------------- main column */

function welcomeHtml(c) {
  return `<div class="lesson">
    <div class="eyebrow">Lessons · number theory</div>
    <h1 class="lesson-title">Pick a lesson</h1>
    <p class="lede">${c.tiers.reduce((n, t) => n + t.lessons.length, 0)} lessons,
      one per node on the skill map, from divisibility up to Wilson's theorem.
      Every lesson ends with a practice round: get 2 of 3 right to complete
      it and unlock what it leads to. Click any node on the map to start.</p>
    <div class="card beyond"><h2>What lies beyond</h2>`
    + c.beyond.split("\n\n").map((p) => `<p class="tiny muted">${escapeHtml(p)}</p>`).join("")
    + `</div></div>`;
}

function roundCardHtml(st) {
  const done = st === "complete";
  return `<div class="card round-card">
    <div class="q-top">
      <span class="tag">Practice round</span>
      <span class="diag-right">
        <span class="pips" id="lr-pips" title="this round: 3 problems, 2 right completes the lesson"></span>
        <span class="muted tiny" id="lr-label"></span>
      </span>
    </div>
    <div id="lr-intro">
      <p class="muted">${done
        ? "Lesson complete. Practice again any time; it keeps sharpening the model's picture of what you know."
        : "Round of 3. Get 2 right to complete this lesson and unlock what it builds toward."}</p>
      <button class="primary" id="lr-start">${done ? "Practice again" : "Start round"}</button>
    </div>
    <div id="lr-play" hidden>
      <p class="prompt" id="lr-prompt"></p>
      <p class="tiny muted" id="lr-format"></p>
      <form id="lr-form" class="answer-form">
        <input id="lr-answer" type="text" autocomplete="off" spellcheck="false"
               placeholder="Your answer">
        <button type="submit" class="primary">Submit</button>
      </form>
      <p class="feedback" id="lr-feedback"></p>
      <div id="lr-hint" class="hint" hidden></div>
      <div id="lr-steps" class="steps" hidden></div>
      <button id="lr-reveal" class="ghost reveal"></button>
      <button id="lr-next" class="ghost" hidden></button>
    </div>
  </div>`;
}

function lessonHtml(c, id) {
  const l = c.lessons[id];
  const order = c.tiers.flatMap((t) => t.lessons);
  const i = order.indexOf(id);
  const prev = i > 0 ? c.lessons[order[i - 1]] : null;
  const next = i < order.length - 1 ? c.lessons[order[i + 1]] : null;
  const st = lessonState(id);
  const pill = st ? `<span class="pill ${PILL[st][1]}">${PILL[st][0]}</span>` : "";
  const prereqs = l.prereqs.length
    ? l.prereqs.map((p) => `<a class="chip" href="#${p}">`
        + `${escapeHtml(c.lessons[p] ? c.lessons[p].name : p)}</a>`).join(" ")
    : `<span class="muted">nothing: this is where the map starts</span>`;
  const sec = (label, cls, text) =>
    `<div class="lsec ${cls}"><div class="eyebrow">${label}</div>
     <p>${prettyLesson(text)}</p></div>`;
  return `<div class="lesson">
      <div class="eyebrow">Lesson ${l.number}</div>
      <h1 class="lesson-title">${escapeHtml(l.name)}</h1>
      <div class="lesson-meta">${pill}</div>
      <p class="tiny muted prereq-line">Builds on: ${prereqs}</p>
      <p class="lede">${prettyLesson(l.concept)}</p>
      ${sec("Key results", "keyres", l.key_results)}
      ${sec("Worked example", "worked", l.worked_example)}
      ${sec("Common mistakes", "mistakes", l.common_mistakes)}
      ${sec("What you'll be asked", "asked", l.problem_types)}
      ${l.note ? `<p class="tiny muted"><em>${prettyLesson(l.note)}</em></p>` : ""}
      ${st === "ready" || st === "complete" ? roundCardHtml(st) : ""}
      <div class="lesson-nav">
        <span>${prev ? `<a href="#${prev.id}">← ${prev.number} ${escapeHtml(prev.name)}</a>` : ""}</span>
        <span>${next ? `<a href="#${next.id}">${next.number} ${escapeHtml(next.name)} →</a>` : ""}</span>
      </div>
    </div>`;
}

/* The hard lock: shown in place of a locked lesson's content. It names
   every incomplete prerequisite; ones already open link straight to their
   lesson (the round is right there), ones still locked themselves link to
   their own locked panel, breadcrumbing back to the real blocker. */
function lockedHtml(c, id) {
  const l = c.lessons[id];
  const blockers = l.prereqs.filter(
    (p) => !(STATUS.nodes[p] && STATUS.nodes[p].completed));
  const rows = blockers.map((p) => {
    const name = escapeHtml(c.lessons[p] ? c.lessons[p].name : p.replace(/_/g, " "));
    const ready = STATUS.nodes[p] && STATUS.nodes[p].lesson_unlocked;
    return `<div class="locked-row">
      <span class="locked-row-name">${name}</span>
      ${ready
        ? `<a class="btn-link" href="#${p}">Go to this lesson →</a>`
        : `<a class="btn-link" href="#${p}">see what unlocks it →</a>`}
    </div>`;
  }).join("");
  return `<div class="lesson locked-panel">
      <div class="eyebrow">Lesson ${l.number}</div>
      <h1 class="lesson-title">${escapeHtml(l.name)}</h1>
      <div class="lesson-meta"><span class="pill locked">Locked</span></div>
      <p class="lede">This lesson opens when the ones it builds on are
        complete. A lesson is complete when you get 2 of 3 right in its
        practice round, or when the diagnostic already showed you know it.</p>
      <div class="card locked-list">
        <div class="eyebrow">Finish these first</div>
        ${rows}
      </div>
    </div>`;
}

/* --------------------------------------------------------------- render */

function render() {
  if (!SHELL_BUILT) return;   // hash nav during login/diagnostic is inert
  const id = location.hash.replace(/^#/, "");
  const active = id && CUR.lessons[id] ? id : null;
  // the gate: a locked lesson renders its locked panel, never its content
  const mainHtml = !active ? welcomeHtml(CUR)
    : lessonState(active) === "locked" ? lockedHtml(CUR, active)
    : lessonHtml(CUR, active);
  $("learn-main").innerHTML = mainHtml;
  NTGraph.select(active);   // null just clears the ring
  wireLesson(active);
  window.scrollTo(0, 0);
}

window.addEventListener("hashchange", render);

/* =====================================================================
   TEMPORARY DUPLICATION of practice.js's round + reveal protocol
   (practice.js drawPips/openPractice/submit/reveal). The upcoming
   practice-page revamp consolidates the two copies into one shared
   module; do not refactor practice.js now.
   ===================================================================== */

let ROUND = null;        // {problemId, node, round, quizPassed, done}
const LAST_ROUND = {};   // node -> last round payload seen (Continue labels)
let revealTimer = null;

/* The pips are the round, not a streak: pip i shows the graded result of
   round slot i (teal right, rose wrong, hollow pending), painted only from
   what the server returned; the 2-of-3 verdict is never computed here. */
function drawPips(round, shake) {
  const p = $("lr-pips");
  if (!p) return;
  p.innerHTML = "";
  const results = round ? round.results : [];
  for (let i = 0; i < 3; i++) {
    const dot = document.createElement("i");
    dot.className = "pip" +
      (results[i] === true ? " good" : results[i] === false ? " bad" : "");
    p.appendChild(dot);
  }
  if (shake) {
    p.classList.remove("shake");
    void p.offsetWidth;           // restart the animation
    p.classList.add("shake");
  }
}

/* Re-attach listeners to the freshly rendered lesson. Elements are new on
   every render, so plain addEventListener never double-binds. */
function wireLesson(id) {
  ROUND = null;   // leaving mid-round is safe: the server keeps the slots
  const start = $("lr-start");
  if (!start) return;   // welcome and locked panels have no round card
  const cached = LAST_ROUND[id];
  const midRound = cached && !cached.verdict &&
    cached.results.length > 0 && cached.results.length < 3;
  if (midRound) {
    // results.length + 1, NOT cached.index: /api/answer's index is the
    // slot just answered while /api/problem's is the next one to serve
    start.textContent = `Continue · problem ${cached.results.length + 1} of 3`;
  }
  start.addEventListener("click", () => openRound(id));
  $("lr-form").addEventListener("submit", submitRound);
  $("lr-reveal").addEventListener("click", revealClick);
  $("lr-next").addEventListener("click", nextClick);
  drawPips(midRound ? cached : null, false);
}

async function openRound(node) {
  const r = await api(`/api/problem?student=${encodeURIComponent(STUDENT)}&node=${node}`);
  if (serverDown(r.error)) {
    toast("Lost the server. Is python3 backend/app.py still running?");
    return;
  }
  if (r.error) { toast("That lesson can't serve problems yet."); return; }
  LAST_ROUND[node] = r.round;
  ROUND = { problemId: r.problem.problem_id, node: r.problem.node,
            round: r.round, quizPassed: r.quiz_passed, done: null };
  $("lr-intro").hidden = true;
  $("lr-play").hidden = false;
  $("lr-label").textContent = `Problem ${r.round.index} of 3`;
  $("lr-prompt").innerHTML = pretty(r.problem.prompt);
  $("lr-format").textContent = r.problem.answer_format || "";
  $("lr-answer").value = "";
  $("lr-answer").disabled = false;
  $("lr-answer").focus();
  $("lr-hint").hidden = true;
  $("lr-steps").hidden = true;
  $("lr-steps").innerHTML = "";
  disarmReveal();
  $("lr-reveal").hidden = false;
  $("lr-next").hidden = true;
  feedback("lr-feedback", "", "");
  drawPips(r.round, false);
}

async function submitRound(e) {
  e.preventDefault();
  if (!ROUND) return;
  disarmReveal();
  const answer = $("lr-answer").value.trim();
  if (!answer) {
    feedback("lr-feedback", 'Type an answer. "none" counts when nothing works.', "info");
    return;
  }
  const r = await api("/api/answer",
    { student: STUDENT, problem_id: ROUND.problemId, answer });

  if (serverDown(r.error)) {
    toast("Lost the server. Is python3 backend/app.py still running?");
    return;
  }
  if (r.error === "problem_expired") { openRound(ROUND.node); return; }

  if (r.grade === "unparseable") {
    // round slot untouched, same problem still live, text kept (5.3)
    feedback("lr-feedback", "Couldn't read that. Check the formatting and try again.", "info");
    return;
  }

  // one response repaints everything: graph colours, counter, and the
  // round card. The main column is deliberately NOT re-rendered mid-round;
  // the lesson pill catches up on the next render (Done or navigation).
  if (r.status) { STATUS = r.status; paintAll(); }
  NTGraph.ripple(r.moved);
  if (r.round) LAST_ROUND[ROUND.node] = r.round;
  const verdict = r.round ? r.round.verdict : null;
  const rightCount = r.round ? r.round.results.filter(Boolean).length : 0;

  if (r.grade === "correct") {
    drawPips(r.round, false);
    if (r.just_mastered) {
      ROUND.done = "mastered";
      const pm = r.status && r.status.nodes[ROUND.node]
        ? r.status.nodes[ROUND.node].p : 0.95;
      // mastery is the model talking, so it speaks violet, not plain green
      feedback("lr-feedback",
               `Mastered! The model is ${Math.round(pm * 100)}% sure you've got this.`,
               "mastered");
      $("lr-answer").disabled = true;
      $("lr-reveal").hidden = true;
      if (r.newly_unlocked.length) {
        NTGraph.celebrate(r.newly_unlocked);
        toast(`Unlocked: ${r.newly_unlocked.map((n) => n.replace(/_/g, " ")).join(", ")}`);
      }
      $("lr-next").textContent = "Done";
      $("lr-next").hidden = false;
    } else if (verdict === "passed") {
      endRoundPassed(r, ROUND.quizPassed
        ? "Round done. This lesson was already complete."
        : "Round passed! Lesson complete.");
    } else if (verdict === "failed") {
      // a correct final answer can still lose a round (two misses before it)
      feedback("lr-feedback",
               `Correct, but ${rightCount}/3 this round. Fresh problems, fresh round.`,
               "info");
      $("lr-next").textContent = "Retry round";
      $("lr-next").hidden = false;
    } else {
      feedback("lr-feedback", "Correct.", "good");
      // capture the node: a hash-navigation within 800ms must not pull a
      // problem for whatever lesson the student lands on next
      const n = ROUND.node;
      setTimeout(() => { if (ROUND && ROUND.node === n) openRound(n); }, 800);
    }
  } else {
    drawPips(r.round, true);      // the wrong slot is a visible mechanic
    if (r.hint) {
      $("lr-hint").textContent = r.hint;
      $("lr-hint").hidden = false;
    }
    // the problem is retired server-side, so there is nothing to reveal
    $("lr-reveal").hidden = true;
    if (verdict === "passed") {
      // two rights were already banked; a missed third can't undo them
      endRoundPassed(r, ROUND.quizPassed
        ? "Not quite, but the round is done. This lesson was already complete."
        : "Not quite, but 2 of 3. Lesson complete.");
    } else if (verdict === "failed") {
      feedback("lr-feedback",
               `Not quite. ${rightCount}/3 this round. Retry with fresh problems.`,
               "bad");
      $("lr-next").textContent = "Retry round";
      $("lr-next").hidden = false;
    } else {
      feedback("lr-feedback", "Not quite.", "bad");
      $("lr-next").textContent = "Next problem";
      $("lr-next").hidden = false;
    }
  }
}

/* The round settled at 2-of-3 or better: the lesson is complete. Input
   off, celebrate what unlocked, offer Done (which re-renders the lesson
   so the pill and card flip to their complete flavours). */
function endRoundPassed(r, msg) {
  ROUND.done = "round";
  feedback("lr-feedback", msg, ROUND.quizPassed ? "info" : "good");
  $("lr-answer").disabled = true;
  $("lr-reveal").hidden = true;
  if (r.newly_unlocked && r.newly_unlocked.length) {
    NTGraph.celebrate(r.newly_unlocked);
    toast(`Unlocked: ${r.newly_unlocked.map((n) => n.replace(/_/g, " ")).join(", ")}`);
  }
  $("lr-next").textContent = "Done";
  $("lr-next").hidden = false;
}

function nextClick() {
  if (!ROUND) return;
  if (ROUND.done === "mastered" || ROUND.done === "round") {
    render();   // pill flips, round card becomes its review flavour
  } else {
    openRound(ROUND.node);
  }
}

/* Two-step reveal confirm: first click arms and shows the cost, second
   surrenders. Submitting, 4 seconds, or a new problem disarms it. */
function disarmReveal() {
  clearTimeout(revealTimer);
  const b = $("lr-reveal");
  if (!b) return;
  b.classList.remove("armed");
  b.innerHTML = 'Stuck? Show the steps <span class="cost">(counts as a wrong answer this round)</span>';
}

function revealClick() {
  if (!ROUND || ROUND.done) return;
  const b = $("lr-reveal");
  if (!b.classList.contains("armed")) {
    b.classList.add("armed");
    b.textContent = "Click again to reveal. This round slot counts as wrong";
    clearTimeout(revealTimer);
    revealTimer = setTimeout(disarmReveal, 4000);
    return;
  }
  disarmReveal();
  revealRound();
}

async function revealRound() {
  const r = await api("/api/reveal",
    { student: STUDENT, problem_id: ROUND.problemId });
  if (serverDown(r.error)) {
    toast("Lost the server. Is python3 backend/app.py still running?");
    return;
  }
  if (r.error === "problem_expired") { openRound(ROUND.node); return; }
  if (r.error) { toast(`Couldn't reveal (${r.error}).`); return; }

  if (r.status) { STATUS = r.status; paintAll(); }
  NTGraph.ripple(r.moved);        // the drop propagates; show it
  if (r.round) LAST_ROUND[ROUND.node] = r.round;
  drawPips(r.round, true);        // the cost is a visible mechanic (5.3)
  ROUND.done = "revealed";
  $("lr-answer").disabled = true;
  $("lr-reveal").hidden = true;
  $("lr-hint").hidden = true;
  const verdict = r.round ? r.round.verdict : null;
  feedback("lr-feedback",
    verdict === "failed"
      ? "That counted as a wrong slot, so the round failed. Here's the full working."
      : verdict === "passed"
      ? "Two rights were already in, so the lesson stays complete. Here's the full working."
      : "That counted as a wrong slot this round. Here's the full working.",
    "info");

  const holder = $("lr-steps");
  holder.innerHTML = "";
  for (const line of r.steps) {
    const d = document.createElement("div");
    d.className = "step";
    d.innerHTML = pretty(line);
    holder.appendChild(d);
  }
  holder.hidden = false;

  $("lr-next").textContent = verdict === "failed" ? "Retry round" : "Next problem";
  $("lr-next").hidden = false;
}

/* =====================================================================
   TEMPORARY DUPLICATION of practice.js's diagnostic protocol (the
   6-question placement quiz). Consolidated by the practice revamp too.
   ===================================================================== */

let DIAG_P = null;   // the live diagnostic problem

function startDiag() {
  $("curriculum-body").innerHTML = `<div class="card q-card">
    <div class="q-top">
      <span class="tag" id="ld-node"></span>
      <span class="diag-right">
        <span class="diag-dots" id="ld-dots"></span>
        <span class="muted tiny" id="ld-progress"></span>
      </span>
    </div>
    <p class="prompt" id="ld-prompt"></p>
    <p class="tiny muted" id="ld-format"></p>
    <form id="ld-form" class="answer-form">
      <input id="ld-answer" type="text" autocomplete="off" spellcheck="false"
             placeholder="Your answer">
      <button type="submit" class="primary">Submit</button>
      <button type="button" id="ld-skip" class="ghost">Skip</button>
    </form>
    <p class="feedback" id="ld-feedback"></p>
    <p class="tiny muted">Never seen this before? Skip it; the quiz is finding
       where your lessons should start.</p>
  </div>`;
  $("ld-form").addEventListener("submit", (e) => { e.preventDefault(); submitDiag(false); });
  $("ld-skip").addEventListener("click", () => submitDiag(true));
  requestDiag();
}

function drawDiagDots(current, max) {
  const holder = $("ld-dots");
  holder.innerHTML = "";
  for (let i = 1; i <= max; i++) {
    const d = document.createElement("i");
    d.className = "ddot" + (i < current ? " done" : i === current ? " now" : "");
    holder.appendChild(d);
  }
}

async function requestDiag() {
  const r = await api("/api/diagnostic/start", { student: STUDENT });
  if (serverDown(r.error)) {
    toast("Lost the server. Is python3 backend/app.py still running?");
    return;
  }
  if (r.done) { finishDiag(r); return; }
  renderDiagQ(r);
}

function renderDiagQ(r) {
  DIAG_P = r.problem;
  $("ld-node").textContent = r.problem.node_name;
  drawDiagDots(r.question_number, r.max_questions);
  $("ld-progress").textContent = `Question ${r.question_number} of ${r.max_questions}`;
  $("ld-prompt").innerHTML = pretty(r.problem.prompt);
  $("ld-format").textContent = r.problem.answer_format || "";
  $("ld-answer").value = "";
  $("ld-answer").focus();
  feedback("ld-feedback", "", "");
}

async function submitDiag(skip) {
  const answer = $("ld-answer").value.trim();
  if (!skip && !answer) {
    feedback("ld-feedback", "Type an answer, or press Skip.", "info");
    return;
  }
  const payload = { student: STUDENT, problem_id: DIAG_P.problem_id };
  if (skip) payload.skip = true; else payload.answer = answer;
  const r = await api("/api/diagnostic/answer", payload);

  if (serverDown(r.error)) {
    toast("Lost the server. Is python3 backend/app.py still running?");
    return;
  }
  if (r.error === "problem_expired") { requestDiag(); return; }

  if (r.grade === "unparseable") {
    // not an attempt: same question, same count, text kept for fixing
    feedback("ld-feedback", "Couldn't read that. Check the formatting and try again.", "info");
    return;
  }
  if (r.done) { finishDiag(r); return; }
  // one answer moves many nodes; say so, since this is the model working
  const movedN = r.moved ? Object.keys(r.moved).length : 0;
  const movedTxt = movedN ? ` (updated ${movedN} skill${movedN === 1 ? "" : "s"})` : "";
  feedback("ld-feedback",
           (skip ? "Skipped." : (r.grade === "correct" ? "✓" : "✗")) + movedTxt,
           r.grade === "correct" ? "good" : "bad");
  setTimeout(() => renderDiagQ(r), 650);
}

async function finishDiag(r) {
  // the finish response carries the freshly calibrated status: build the
  // shell straight from it, no extra /api/state round-trip
  await enterPath(r.status);
  const s = r.summary || {};
  const known = (s.tested_pass ? s.tested_pass.length : 0)
    + (s.inferred_mastered ? s.inferred_mastered.length : 0);
  toast(known
    ? `Placement done. ${known} skill${known === 1 ? "" : "s"} already showing as known. Pick a ready lesson.`
    : "Placement done. The path starts at the first lesson.");
}

/* ---------------------------------------------------------------- login */

function showLogin() {
  $("learn-login").hidden = false;
  $("curriculum-body").innerHTML = "";
  $("learn-login-name").focus();
}

function enter(login) {
  STUDENT = login.student;
  localStorage.setItem("nt_name", login.display_name);
  applyWho(login);
  if (login.phase === "diagnostic") startDiag();
  else enterPath(null);
}

$("learn-login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("learn-login-name").value.trim();
  if (!name) return;
  const r = await api("/api/login", { name });
  if (serverDown(r.error)) { showServerWarning(); return; }
  if (r.error === "name_required") {
    toast("Type a name. Letters and numbers work best.");
    return;
  }
  if (r.error) { toast(`Couldn't log in (${r.error}).`); return; }
  $("learn-login").hidden = true;
  enter(r);
});

$("switch-user").addEventListener("click", (e) => {
  e.preventDefault();
  localStorage.removeItem("nt_name");
  location.reload();
});

window.pageInit = async function () {
  // no remembered name means no progress to gate on: ask for one first.
  // /api/login (not a raw state fetch) so a brand-new name gets a student
  // file here exactly as it would on the practice page.
  const name = localStorage.getItem("nt_name");
  if (!name) { showLogin(); return; }
  const r = await api("/api/login", { name });
  if (serverDown(r.error)) { showServerWarning(); return; }
  if (r.error) { showLogin(); return; }
  enter(r);
};
