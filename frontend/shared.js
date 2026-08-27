/* shared.js: plumbing every page uses: API access, toasts, math rendering,
   and the wrong-origin safety net.

   Load order on every page: shared.js first, then the page's own script,
   which may define window.pageInit. boot() below awaits a health probe, so
   by the time it resolves every later <script> has run and pageInit exists.

   Everything is graded on the server; no file in this frontend ever sees an
   answer key for a gradable problem. */

const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const opts = body
    ? { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) }
    : {};
  let r;
  try {
    r = await fetch(path, opts);
  } catch {
    return { error: "server_unreachable" };
  }
  let data = null;
  try { data = await r.json(); } catch { data = null; }
  // A static file server (Live Server etc.) answers /api/* with an HTML 404
  // or a 405, non-JSON either way. Surface that as its own condition so the
  // UI can explain it instead of blaming the student's input.
  if (data === null) return { error: r.ok ? "bad_response" : `http_${r.status}` };
  if (!r.ok && !data.error) data.error = `http_${r.status}`;
  return data;
}

function serverDown(err) {
  return err === "server_unreachable" || err === "bad_response"
      || /^http_(404|405|5\d\d)$/.test(err || "");
}

function toast(msg, ms = 3200) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.hidden = true; }, ms);
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* "23^45231" reads badly as plain text; superscript the exponent and swap
   ASCII comparators for real symbols. Problem prompts are plain text with
   digit-base carets: this is their entire math renderer. */
function pretty(prompt) {
  return escapeHtml(prompt)
    .replace(/(\d+)\^(-?\w+)/g, "$1<sup>$2</sup>")
    .replace(/&lt;=/g, "≤")
    .replace(/&gt;=/g, "≥");
}

/* Dress the header's identity chip. The server owns cosmetics: color is an
   id (CSS maps it to a hue), title arrives as a ready display label, both
   riding on /api/login so no page needs an extra request. Boss wins in the
   dungeon are what unlock them. */
function applyWho(login) {
  $("who").hidden = false;
  const n = $("who-name");
  n.textContent = login.display_name;
  n.className = login.color ? `name-${login.color}` : "";
  const t = $("who-title");
  if (t) {
    t.textContent = login.title || "";
    t.hidden = !login.title;
  }
}

/* ------------------------------------------ wrong-origin safety net */

const APP_ORIGIN = "http://127.0.0.1:5001";

function showServerWarning() {
  if ($("server-warning")) return;
  for (const s of document.querySelectorAll("body > section")) s.hidden = true;
  const sec = document.createElement("section");
  sec.innerHTML = `
    <div class="card login-card warn-card" id="server-warning">
      <h1>Can't reach the math server</h1>
      <p class="muted">
        This page was loaded from <code>${escapeHtml(location.origin)}</code>,
        which serves files but can't grade anything. That usually means it was
        opened through VS Code's Live Server instead of the app itself.
      </p>
      <p>Start the app server from the project folder:</p>
      <pre><code>python3 backend/app.py</code></pre>
      <p class="muted">This page will jump to the app by itself the moment the
         server is up.</p>
    </div>`;
  document.body.prepend(sec);
}

async function realServerUp() {
  // Cross-origin + no-cors: the opaque response tells us nothing except the
  // one thing we need: whether something is listening over there.
  try {
    await fetch(`${APP_ORIGIN}/api/health`, { mode: "no-cors" });
    return true;
  } catch {
    return false;
  }
}

function jumpToApp() {
  // Map whatever path this page was opened from (Live Server may be rooted
  // anywhere, file:// carries a filesystem path) onto the app's own URLs,
  // copying the path verbatim 404s on the app.
  const p = location.pathname;
  let target = "/";
  if (p.endsWith("/learn.html") || p.endsWith("/learn")) target = "/learn";
  else if (p.endsWith("/practice.html") || p.endsWith("/practice")) target = "/practice";
  location.replace(APP_ORIGIN + target + location.hash);
}

async function wrongOrigin() {
  // Opened via Live Server or another static host: nothing here can grade.
  // Jump to the real app if it's up; otherwise explain, and keep probing so
  // the page jumps by itself the moment the server starts.
  if (await realServerUp()) { jumpToApp(); return; }
  showServerWarning();
  const timer = setInterval(async () => {
    if (await realServerUp()) { clearInterval(timer); jumpToApp(); }
  }, 2000);
}

(async function boot() {
  // Before anything else: is the thing serving this page actually the app?
  const health = await api("/api/health");
  if (health.ok !== true) { wrongOrigin(); return; }
  if (typeof window.pageInit === "function") window.pageInit();
})();
