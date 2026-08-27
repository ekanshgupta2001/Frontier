/* graph.js: draws the DAG the server laid out, and recolors it on demand.
   All positions come precomputed from /api/graph; this file only places
   circles, draws curves, and swaps CSS classes. No layout math here.

   Since Phase 2B every node carries a continuous P(mastered) from the
   knowledge-tracing model: the fill colour interpolates on it (classes still
   drive stroke, pulse and click behaviour), and ripple() pulses the nodes a
   single answer moved, sized by how far they moved. */

const NTGraph = (() => {
  const SVG = "http://www.w3.org/2000/svg";
  let nodeEls = {};   // node id -> <g>
  let haloEls = {};   // node id -> blurred <circle> in the bloom layer
  let baseR = {};     // node id -> resting radius (paint() scales frontier)
  let edgeEls = [];   // [{el, from, to}]
  let onClick = null; // set by init
  let lastStatus = null;

  /* ---- continuous colour: locked navy -> frontier sage -> mastered teal.
     The sage midpoint sits at p = 0.5 and the teal endpoint at the 0.95
     mastery threshold, so the colour IS the model's belief.
     Keep these hexes in sync with --locked-fill/--frontier/--mastered
     in style.css. */
  function lerpHex(a, b, t) {
    const ca = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
    const cb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
    const c = ca.map((v, i) => Math.round(v + (cb[i] - v) * t));
    return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
  }

  function fillFor(p) {
    if (p >= 0.95) return "#45C4B0";
    if (p <= 0.5) return lerpHex("#182130", "#A3C585", p / 0.5);
    return lerpHex("#A3C585", "#45C4B0", (p - 0.5) / 0.45);
  }

  const pct = (p) => `${Math.round(p * 100)}%`;

  function el(name, attrs) {
    const e = document.createElementNS(SVG, name);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    return e;
  }

  // Both circles for a node (halo and body) must agree on this.
  function radius(n) {
    return n.authored ? 21 : 15;
  }

  // Node names are long ("Linear Diophantine equations"); two short lines
  // read better than one clipped one. The split point balances the two
  // lines by character count, not word count: a word-count midpoint gave
  // "Probabilistic primality" / "testing", and that 23-char line was the
  // map's one label-collision risk at the current font size.
  function labelLines(name) {
    if (name.length <= 14) return [name];
    const words = name.split(" ");
    let best = null;
    for (let i = 1; i < words.length; i++) {
      const a = words.slice(0, i).join(" ");
      const b = words.slice(i).join(" ");
      const widest = Math.max(a.length, b.length);
      if (!best || widest < best.widest) best = { widest, lines: [a, b] };
    }
    return best ? best.lines : [name];
  }

  // Frontier nodes (where the student currently is) render 20% larger so
  // the active edge of the map stands out at a glance.
  const FRONTIER_SCALE = 1.2;

  function init(holder, data, clickHandler) {
    onClick = clickHandler;
    nodeEls = {}; haloEls = {}; baseR = {}; edgeEls = [];
    const pos = {};
    for (const n of data.nodes) pos[n.id] = n;

    const svg = el("svg", { viewBox: "0 0 900 1300" });

    // bloom layer: one blurred circle per node, lit by paint(). It sits
    // under the edges so the mastered region glows behind the whole map.
    const defs = el("defs", {});
    const blur = el("filter", {
      id: "halo-blur", x: "-80%", y: "-80%", width: "260%", height: "260%",
    });
    blur.appendChild(el("feGaussianBlur", { stdDeviation: 9 }));
    defs.appendChild(blur);
    svg.appendChild(defs);
    const haloGroup = el("g", { class: "halos", filter: "url(#halo-blur)" });
    svg.appendChild(haloGroup);
    for (const n of data.nodes) {
      const r = radius(n);
      const halo = el("circle", { cx: n.x, cy: n.y, r: r * 1.7, opacity: 0 });
      haloGroup.appendChild(halo);
      haloEls[n.id] = halo;
    }

    // edges next, still under the nodes
    for (const [from, to] of data.edges) {
      const a = pos[from], b = pos[to];
      if (!a || !b) continue;
      const m = (a.y + b.y) / 2;
      const d = `M ${a.x} ${a.y} C ${a.x} ${m}, ${b.x} ${m}, ${b.x} ${b.y}`;
      const p = el("path", { d, class: "edge" });
      svg.appendChild(p);
      edgeEls.push({ el: p, from, to });
    }

    for (const n of data.nodes) {
      const g = el("g", { class: "node locked" });
      // RSA is the DAG's deepest confluence, so style it as the mastery gate
      if (n.id === "rsa") g.classList.add("gate");
      const r = radius(n);
      baseR[n.id] = r;
      g.appendChild(el("circle", { cx: n.x, cy: n.y, r }));
      // fog: locked nodes show a "?" until the frontier reaches them
      const glyph = el("text", { x: n.x, y: n.y + 4.5, class: "glyph" });
      glyph.textContent = "?";
      g.appendChild(glyph);
      const lines = labelLines(n.name);
      lines.forEach((line, i) => {
        // measured from the LARGEST the circle can get (the frontier
        // scale), so the label clears the node in every status
        const t = el("text", { x: n.x, y: n.y + r * FRONTIER_SCALE + 15 + i * 13 });
        t.textContent = line;
        g.appendChild(t);
      });
      // the inspector focus ring goes after the main circle on purpose, so
      // paint()'s querySelector("circle") still finds the node circle first
      g.appendChild(el("circle", { cx: n.x, cy: n.y, r: r + 6, class: "ring" }));
      const tip = el("title", {});
      g.appendChild(tip);
      // every node is inspectable, even locked ones; the side panel decides
      // what the click can actually do
      g.addEventListener("click", () => {
        if (onClick) onClick(n.id);
      });
      svg.appendChild(g);
      nodeEls[n.id] = g;
    }

    holder.innerHTML = "";
    holder.appendChild(svg);
  }

  /* status payload: {nodes: {id: {status, source, p, progress, ...}}, frontier} */
  function paint(status) {
    lastStatus = status;
    for (const [id, g] of Object.entries(nodeEls)) {
      const s = status.nodes[id];
      if (!s) continue;
      g.classList.remove("mastered", "frontier", "locked", "inferred", "clickable");
      g.classList.add(s.status);
      const inferred = s.status === "mastered" && s.source === "inferred";
      if (inferred) g.classList.add("inferred");
      // frontier nodes practise; mastered ones stay open for review
      if (s.status === "frontier" || s.status === "mastered") g.classList.add("clickable");

      // The model's belief, painted directly. Inferred mastery keeps its
      // dashed class-driven look: a guess must never render as measured.
      const circle = g.querySelector("circle");
      circle.style.fill = (!inferred && typeof s.p === "number") ? fillFor(s.p) : "";

      // the frontier is where the student is: those nodes sit 20% larger,
      // and shrink back once mastered (the CSS r transition eases it)
      const r = baseR[id] * (s.status === "frontier" ? FRONTIER_SCALE : 1);
      circle.setAttribute("r", r);

      // bloom: mastered glows teal (brighter the surer the model is),
      // frontier glows sage. Inferred gets none: a guess doesn't glow.
      const halo = haloEls[id];
      if (halo) {
        halo.setAttribute("r", r * 1.7);   // bloom tracks the circle's size
        if (s.status === "mastered" && !inferred) {
          halo.setAttribute("fill", "#45C4B0");
          halo.style.opacity = 0.16 + 0.34 * (typeof s.p === "number" ? s.p : 0.95);
        } else if (s.status === "frontier") {
          halo.setAttribute("fill", "#A3C585");
          halo.style.opacity = 0.32;
        } else {
          halo.style.opacity = 0;
        }
      }

      const tip = g.querySelector("title");
      if (s.status === "mastered") {
        tip.textContent = inferred
          ? `inferred at ${pct(s.p)}, not tested yet (click to prove it)`
          : `mastered at ${pct(s.p)}`;
      } else if (s.status === "frontier") {
        tip.textContent = `available now: ${s.progress} toward mastery`;
      } else {
        tip.textContent = `locked: master its prerequisites first (${pct(s.p)})`;
      }
    }
    for (const { el: p, to } of edgeEls) {
      const s = status.nodes[to];
      p.classList.remove("to-frontier", "to-mastered");
      if (!s) continue;
      if (s.status === "frontier") p.classList.add("to-frontier");
      else if (s.status === "mastered") p.classList.add("to-mastered");
    }
  }

  /* mark one node as the inspected one (indigo ring); paint() only touches
     status classes, so the selection survives repaints */
  let selectedId = null;
  function select(id) {
    if (selectedId && nodeEls[selectedId]) nodeEls[selectedId].classList.remove("selected");
    selectedId = id;
    if (nodeEls[id]) nodeEls[id].classList.add("selected");
  }

  /* the unlock moment: pop the newly available nodes (PROJECT.md 5.2) */
  function celebrate(ids) {
    for (const id of ids) {
      const g = nodeEls[id];
      if (!g) continue;
      g.classList.add("unlocking");
      setTimeout(() => g.classList.remove("unlocking"), 800);
      // the unlock travels down the edges that made it possible
      for (const e of edgeEls) {
        if (e.to !== id) continue;
        e.el.classList.add("unlock-edge");
        setTimeout(() => e.el.classList.remove("unlock-edge"), 800);
      }
    }
  }

  /* one answer moved these nodes: pulse each, sized by |delta|, tinted by
     direction. moved is the server's {node_id: delta} map. */
  function ripple(moved) {
    if (!moved) return;
    for (const [id, delta] of Object.entries(moved)) {
      const g = nodeEls[id];
      const mag = Math.abs(delta);
      if (!g || mag < 0.01) continue;
      const cls = mag >= 0.15 ? "moved-lg" : mag >= 0.05 ? "moved-md" : "moved-sm";
      g.classList.remove("moved-sm", "moved-md", "moved-lg", "down");
      void g.getBoundingClientRect();   // restart the animation
      g.classList.add(cls);
      if (delta < 0) g.classList.add("down");
      setTimeout(() => g.classList.remove(cls, "down"), 950);
      // the evidence travels: pulse the edges feeding this node (teal for
      // a gain, rose for a drop) so propagation is watchable, not claimed
      const edgeCls = delta < 0 ? "pulse-down" : "pulse-up";
      for (const e of edgeEls) {
        if (e.to !== id) continue;
        e.el.classList.remove("pulse-up", "pulse-down");
        void e.el.getBoundingClientRect();
        e.el.classList.add(edgeCls);
        setTimeout(() => e.el.classList.remove(edgeCls), 950);
      }
    }
  }

  return { init, paint, celebrate, ripple, select };
})();
