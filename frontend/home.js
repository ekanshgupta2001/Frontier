/* home.js: fills in the mastery progress bar. The bar always shows (the
   page defaults to 0 / 22); a remembered student's real numbers animate in,
   and any failure just leaves the zeros. */

window.pageInit = async function () {
  const name = localStorage.getItem("nt_name");
  if (!name) return;

  const [graph, state] = await Promise.all([
    api("/api/graph"),
    api(`/api/state?student=${encodeURIComponent(name)}`),
  ]);
  if (graph.error || state.error || !graph.nodes || !state.nodes) return;

  // Progress counts only authored nodes, the ones with real problem
  // templates, i.e. the skills a student can actually master today.
  const authored = graph.nodes.filter((n) => n.authored);
  if (!authored.length) return;
  const done = authored.filter((n) => {
    const s = state.nodes[n.id];
    return s && s.status === "mastered";
  }).length;

  $("prog-count").textContent = done;
  $("prog-total").textContent = authored.length;
  // width set in a later frame so the .6s ease actually plays
  requestAnimationFrame(() => {
    $("prog-fill").style.width = `${Math.round((done / authored.length) * 100)}%`;
  });
};
