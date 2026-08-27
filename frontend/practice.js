/* practice.js: the Challenges page, a dungeon run over the ntgen engine.
   Every number on screen (hearts, streak, score, boss pips) is a snapshot
   the server sent from /api/dungeon/*; this file renders those snapshots
   and posts answers. It never grades, never counts a heart or a point,
   and never sees an answer: a devtools tab shows only what's on screen. */

const S = {
  student: null,
  displayName: null,
  run: null,        // last run snapshot from the server
  problem: null,    // the problem currently on screen
  pending: null,    // the next problem, held until the student clicks on
  cosmetics: null,  // {color, title, ladder} from the server
};

const SCREENS = ["screen-login", "screen-placement", "screen-lobby",
                 "screen-run", "screen-death"];

function show(id) {
  for (const s of SCREENS) $(s).hidden = s !== id;
}

function feedback(msg, kind) {
  const el = $("run-feedback");
  el.textContent = msg;
  el.className = "feedback" + (kind ? " " + kind : "");
}

/* ---------------------------------------------------------------------------
   Login (same remembered-name flow as the lessons page)
--------------------------------------------------------------------------- */

function enter(login) {
  S.student = login.student;
  S.displayName = login.display_name;
  localStorage.setItem("nt_name", login.display_name);
  applyWho(login);
  // no placement yet means no unlocked skills to build rooms from; the
  // lessons page owns the diagnostic, so send the student there
  if (login.phase === "diagnostic") { show("screen-placement"); return; }
  openLobby();
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("login-name").value.trim();
  if (!name) return;
  const r = await api("/api/login", { name });
  if (serverDown(r.error)) { showServerWarning(); return; }
  if (r.error === "name_required") {
    toast("Type a name. Letters and numbers work best.");
    return;
  }
  if (r.error) { toast(`Couldn't log in (${r.error}).`); return; }
  enter(r);
});

$("switch-user").addEventListener("click", (e) => {
  e.preventDefault();
  localStorage.removeItem("nt_name");
  location.reload();
});

/* ---------------------------------------------------------------------------
   Lobby: records + the cosmetic ladder
--------------------------------------------------------------------------- */

async function openLobby() {
  document.body.classList.remove("boss-mode");
  const r = await api(`/api/dungeon/state?student=${encodeURIComponent(S.student)}`);
  if (serverDown(r.error)) { showServerWarning(); return; }
  if (r.error) { toast(`Couldn't open the dungeon (${r.error}).`); return; }
  renderLobby(r);
  show("screen-lobby");
}

function renderLobby(r) {
  $("rec-depth").textContent = r.records.best_depth;
  $("rec-runs").textContent = r.records.runs;
  $("rec-bosses").textContent = r.records.bosses_beaten;
  $("lobby-start").textContent = r.active ? "Resume your run" : "Enter the dungeon";
  S.cosmetics = r.cosmetics;
  renderCosmetics();
}

function cosButton(step, worn) {
  const b = document.createElement("button");
  b.type = "button";
  if (step.kind === "color") {
    b.className = `swatch swatch-${step.id}`;
    b.title = step.unlocked ? step.label
      : `${step.label}: beat ${step.at} boss${step.at === 1 ? "" : "es"}`;
  } else {
    b.className = "title-pill";
    b.textContent = step.unlocked ? step.label : `${step.label} · at ${step.at}`;
  }
  if (!step.unlocked) b.classList.add("locked");
  if (worn) b.classList.add("worn");
  b.addEventListener("click", () => {
    if (!step.unlocked) {
      toast(`Beat ${step.at} boss${step.at === 1 ? "" : "es"} to unlock ${step.label}.`);
      return;
    }
    equip(step.kind, worn ? null : step.id);   // click while worn = take off
  });
  return b;
}

function renderCosmetics() {
  const cos = S.cosmetics;
  const colors = $("cos-colors"), titles = $("cos-titles");
  colors.innerHTML = ""; titles.innerHTML = "";
  for (const step of cos.ladder) {
    const worn = cos[step.kind] === step.id;
    (step.kind === "color" ? colors : titles).appendChild(cosButton(step, worn));
  }
}

async function equip(kind, id) {
  const payload = { student: S.student };
  payload[kind] = id;
  const r = await api("/api/dungeon/cosmetic", payload);
  if (serverDown(r.error)) { showServerWarning(); return; }
  if (r.error) { toast(`Couldn't equip that (${r.error}).`); return; }
  S.cosmetics = r.cosmetics;
  renderCosmetics();
  // re-dress the header immediately: label looked up from the ladder the
  // server just sent, so nothing cosmetic is ever computed client-side
  const t = r.cosmetics.ladder.find(
    (s) => s.kind === "title" && s.id === r.cosmetics.title);
  applyWho({ display_name: S.displayName, color: r.cosmetics.color,
             title: t ? t.label : null });
}

$("lobby-start").addEventListener("click", startRun);

/* ---------------------------------------------------------------------------
   The run
--------------------------------------------------------------------------- */

async function startRun() {
  const r = await api("/api/dungeon/start", { student: S.student });
  if (serverDown(r.error)) { showServerWarning(); return; }
  if (r.error === "diagnostic_required") { show("screen-placement"); return; }
  if (r.error) { toast(`Couldn't start the run (${r.error}).`); return; }
  S.run = r.run;
  S.problem = r.problem;
  S.pending = null;
  S.cosmetics = r.cosmetics;
  $("reward-card").hidden = true;
  show("screen-run");
  renderHud();
  renderProblem();
}

const HEART_SVG =
  '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 14 C3 10.5 1 8 ' +
  '1 5.4 1 3.4 2.6 2 4.4 2 5.9 2 7.2 2.9 8 4.3 8.8 2.9 10.1 2 11.6 2 ' +
  '13.4 2 15 3.4 15 5.4 15 8 13 10.5 8 14 Z"/></svg>';

/* floor number and boss countdown are display arithmetic on the server's
   room snapshot: never a verdict, a heart, or a point, so they can live
   client-side without touching the grading contract */
function floorOf(room) {
  return Math.floor((room - 1) / 5) + 1;
}

/* pure flavor, cycling by floor; the server has never heard of these */
const BOSS_NAMES = [
  "Modulus, the Divider",
  "Sieve, the Endless",
  "Totient, the Counter",
  "The Euclid Warden",
  "Residue, the Keeper",
  "Primus, the Ancient",
];
function bossName(floor) {
  return BOSS_NAMES[(floor - 1) % BOSS_NAMES.length];
}

function renderCountdown(room) {
  const el = $("hud-countdown");
  el.innerHTML = "";
  // room % 5 rooms cleared in this block of five; the diamond is the boss
  const done = room % 5;
  for (let i = 0; i < 4; i++) {
    const sq = document.createElement("i");
    sq.className = "cd" + (i < done ? " on" : "");
    el.appendChild(sq);
  }
  const dia = document.createElement("i");
  dia.className = "cd-boss";
  el.appendChild(dia);
  const label = document.createElement("span");
  label.className = "cd-text";
  label.textContent = `boss in ${5 - done}`;
  el.appendChild(label);
}

function renderHud() {
  const run = S.run;
  const hearts = $("run-hearts");
  hearts.innerHTML = "";
  for (let i = 0; i < 3; i++) {
    const h = document.createElement("span");
    h.className = "heart" + (i < run.lives ? "" : " lost");
    h.innerHTML = HEART_SVG;
    hearts.appendChild(h);
  }
  $("run-room-num").textContent = String(run.room).padStart(2, "0");
  $("run-streak").textContent = `${run.streak} · x${run.multiplier}`;
  $("run-score").textContent = run.score;

  const isBoss = run.is_boss;
  document.body.classList.toggle("boss-mode", isBoss);
  $("room-card").classList.toggle("boss", isBoss);
  $("hud-countdown").hidden = isBoss;
  $("hud-boss-label").hidden = !isBoss;
  $("boss-intro").hidden = !isBoss;
  if (isBoss) {
    const floor = floorOf(run.room);
    $("boss-floor").textContent = `Floor ${floor} guardian`;
    $("boss-name").textContent = bossName(floor);
    if (run.boss) drawBossPips(run.boss);
  } else {
    renderCountdown(run.room);
  }
}

function drawBossPips(boss, shake) {
  const el = $("boss-pips");
  el.innerHTML = "";
  for (let i = 0; i < 3; i++) {
    const pip = document.createElement("i");
    pip.className = "pip";
    if (boss.results[i] === true) pip.classList.add("good");
    if (boss.results[i] === false) pip.classList.add("bad");
    el.appendChild(pip);
  }
  el.classList.remove("shake");
  if (shake) { void el.offsetWidth; el.classList.add("shake"); }
}

function renderProblem() {
  const p = S.problem;
  const run = S.run;
  if (run.is_boss && run.boss) {
    // the boss hides its topic; the pill tracks the gauntlet instead
    $("run-node").textContent =
      `Gauntlet · problem ${run.boss.results.length + 1} of 3`;
    $("room-floor").textContent = `room ${run.room}`;
  } else {
    $("run-node").textContent = p.node_name;
    $("room-floor").textContent = `floor ${floorOf(run.room)}`;
  }
  $("run-prompt").innerHTML = pretty(p.prompt);
  $("run-format").textContent = p.answer_format || "";
  $("run-answer").value = "";
  $("run-answer").disabled = false;
  $("run-submit").disabled = false;
  $("run-next").hidden = true;
  $("run-hint").hidden = true;
  feedback("", "");
  $("run-answer").focus();
}

function shakeHearts() {
  const el = $("run-hearts");
  el.classList.remove("shake");
  void el.offsetWidth;
  el.classList.add("shake");
}

/* hold the answered problem on screen; the next one waits behind a click
   (wrong answers) or a short beat (correct answers) */
function stageNext(problem, label) {
  S.pending = problem;
  $("run-answer").disabled = true;
  $("run-submit").disabled = true;
  if (label === null) {
    // correct answers flow: advance on their own after a short beat
    const expect = problem.problem_id;
    setTimeout(() => {
      if (S.pending && S.pending.problem_id === expect) advance();
    }, 750);
  } else {
    const next = $("run-next");
    next.textContent = label;
    next.hidden = false;
  }
}

function advance() {
  if (!S.pending) return;
  S.problem = S.pending;
  S.pending = null;
  renderHud();
  renderProblem();
}

$("run-next").addEventListener("click", advance);

function showReward(reward) {
  const card = $("reward-card");
  const swatch = reward.kind === "color"
    ? `<span class="swatch swatch-${reward.id} inline"></span> ` : "";
  card.innerHTML = `<div class="eyebrow">Trophy unlocked</div>
    <p>${swatch}<b>${escapeHtml(reward.label)}</b>
    ${reward.kind === "color" ? "is now a name color you can wear."
                              : "is now a title you can wear."}
    Equip it from the lobby.</p>`;
  card.hidden = false;
}

$("run-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const answer = $("run-answer").value.trim();
  if (!answer || !S.problem || S.pending) return;
  $("run-submit").disabled = true;
  const r = await api("/api/dungeon/answer", {
    student: S.student, problem_id: S.problem.problem_id, answer,
  });
  $("run-submit").disabled = false;
  if (serverDown(r.error)) { showServerWarning(); return; }
  if (r.error === "problem_expired") {
    // the shared problem slot was evicted (or the server restarted); the
    // run itself lives in the student file, so resuming re-serves the room
    toast("That problem expired. Back to the same room.");
    startRun();
    return;
  }
  if (r.error === "no_active_run") { openLobby(); return; }
  if (r.error) { toast(`Something went wrong (${r.error}).`); return; }

  if (r.grade === "unparseable") {
    feedback("Couldn't read that. Check the format and try again.", "info");
    return;
  }

  S.run = r.run;
  renderHud();

  if (r.newly_unlocked && r.newly_unlocked.length) {
    toast(`Your answers unlocked ${r.newly_unlocked.length} new ` +
          `lesson${r.newly_unlocked.length === 1 ? "" : "s"} on the map.`);
  }

  if (r.outcome === "dead") { showDeath(r); return; }

  if (r.grade === "correct") {
    if (r.outcome === "boss_won") {
      feedback(`Boss down! +${r.gained} points.`, "good");
      if (r.reward) showReward(r.reward);
      stageNext(r.problem, `Descend to room ${r.run.room}`);
    } else if (r.outcome === "boss_progress") {
      feedback(`Hit! +${r.gained} points.`, "good");
      drawBossPips(r.run.boss);
      stageNext(r.problem, null);
    } else {
      feedback(`Correct! +${r.gained} points (x${r.run.multiplier}).`, "good");
      stageNext(r.problem, null);
    }
  } else {
    if (r.hint) {
      $("run-hint").textContent = `Hint: ${r.hint}`;
      $("run-hint").hidden = false;
    }
    if (r.outcome === "boss_progress") {
      feedback("Miss. The boss is still up.", "bad");
      drawBossPips(r.run.boss, true);
      stageNext(r.problem, "Next attack");
    } else if (r.outcome === "boss_lost") {
      feedback("The boss holds the floor. That costs a heart.", "bad");
      shakeHearts();
      stageNext(r.problem, "Fight it again");
    } else {
      feedback("Wrong. That costs a heart.", "bad");
      shakeHearts();
      stageNext(r.problem, "Try this room again");
    }
  }
});

/* ---------------------------------------------------------------------------
   Death and flee
--------------------------------------------------------------------------- */

function showDeath(r) {
  document.body.classList.remove("boss-mode");
  const floor = floorOf(r.run.room);
  $("death-line").textContent = r.run.is_boss
    ? `${bossName(floor)} caught you in room ${r.run.room}, floor ${floor}.`
    : `Room ${r.run.room} took your last heart on floor ${floor}.`;
  $("death-depth").textContent = r.run.depth;
  $("death-score").textContent = r.run.score;
  $("death-record").textContent = r.records.best_depth;
  $("death-best").hidden = !r.new_best;
  S.run = null; S.problem = null; S.pending = null;
  show("screen-death");
}

$("death-retry").addEventListener("click", startRun);
$("death-lobby").addEventListener("click", openLobby);

/* two-step flee, same arm-then-confirm pattern as the reveal button */
let fleeTimer = null;

$("run-flee").addEventListener("click", async (e) => {
  e.preventDefault();
  const link = $("run-flee");
  if (!link.classList.contains("armed")) {
    link.classList.add("armed");
    link.textContent = "Really flee? The run ends. Click again.";
    fleeTimer = setTimeout(() => {
      link.classList.remove("armed");
      link.textContent = "Flee the dungeon";
    }, 4000);
    return;
  }
  clearTimeout(fleeTimer);
  link.classList.remove("armed");
  link.textContent = "Flee the dungeon";
  const r = await api("/api/dungeon/flee", { student: S.student });
  if (serverDown(r.error)) { showServerWarning(); return; }
  if (r.error && r.error !== "no_active_run") {
    toast(`Couldn't flee (${r.error}).`);
    return;
  }
  toast(r.new_best ? "You escaped with a new record depth." : "You escaped.");
  S.run = null; S.problem = null; S.pending = null;
  openLobby();
});

/* ---------------------------------------------------------------------------
   Boot
--------------------------------------------------------------------------- */

window.pageInit = async function () {
  const name = localStorage.getItem("nt_name");
  if (!name) { show("screen-login"); $("login-name").focus(); return; }
  const r = await api("/api/login", { name });
  if (serverDown(r.error)) { showServerWarning(); return; }
  if (r.error) { show("screen-login"); return; }
  enter(r);
};
