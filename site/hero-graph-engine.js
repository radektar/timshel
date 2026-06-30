/* ============================================================
   Malinche — reusable hero knowledge-graph engine
   Wraps the force-directed "noise → connection → insight" motif
   from the original landing so it can be themed (light / dark)
   and dropped into multiple hero layouts.

   Usage:
     var inst = MalincheGraph({
       host:      heroSectionEl,   // position:relative; cards mount here
       canvasEl:  divForCanvas,    // ForceGraph mounts here (fills host or panel)
       theme:     "light" | "dark",
       mass:      340,             // mass-node count
       camX:      -140, camY: 0,   // graph-space center offset
       zoom:      1,               // <1 to fit a smaller panel
       cards:     "tracked" | "none",
       seed:      20260621
     });
     inst.reveal();  // start choreography + physics (call on scroll-in)
     inst.pause(); inst.resume();
   Requires window.ForceGraph (vendor/force-graph.min.js).
   ============================================================ */
(function () {
  "use strict";

  var THEMES = {
    light: {
      mass: "60,54,46",
      massBaseA: 0.14, massStepA: 0.052, massMaxStep: 6,
      massHoverA: 0.82, massNeighborA: 0.55,
      link: "30,24,18", linkA: 0.05, linkHoverA: 0.26,
      commGlow: ["rgba(194,64,16,0.30)", "rgba(194,64,16,0.10)", "rgba(194,64,16,0)"],
      commRing: "194,64,16", commCore: "#C24010", commHi: "#FFFFFF",
      arc: "194,64,16", arcMaxA: 0.85, arcShadow: "rgba(194,64,16,0.22)", arcBlur: 5,
      bloomHalo: ["rgba(231,180,92,0.92)", "rgba(231,180,92,0.30)", "rgba(231,180,92,0)"],
      bloomRing: "201,148,58", bloomDot: "#D99A2E", bloomHot: "#FFFFFF", bloomSpoke: "201,148,58"
    },
    dark: {
      mass: "152,142,128",
      massBaseA: 0.30, massStepA: 0.085, massMaxStep: 6,
      massHoverA: 0.97, massNeighborA: 0.85,
      link: "124,112,98", linkA: 0.085, linkHoverA: 0.4,
      commGlow: ["rgba(217,84,42,0.55)", "rgba(194,64,16,0.20)", "rgba(194,64,16,0)"],
      commRing: "217,84,42", commCore: "#C24010", commHi: "#FAF3E2",
      arc: "217,84,42", arcMaxA: 0.92, arcShadow: "rgba(194,64,16,0.6)", arcBlur: 9,
      bloomHalo: ["rgba(244,221,142,0.92)", "rgba(214,176,51,0.32)", "rgba(214,176,51,0)"],
      bloomRing: "214,176,51", bloomDot: "#F4DD8E", bloomHot: "#FFFBF0", bloomSpoke: "214,176,51"
    }
  };

  var CONTENT = [
    { d: "8 sty",  src: "wywiad — uczestnik A",   t: "„Decyduje cena. Reszta się nie liczy." },
    { d: "22 lut", src: "wywiad — uczestnik B",   t: "„Budżet jest święty — najtaniej, jak się da." },
    { d: "30 mar", src: "nagranie — warsztat",    t: "„Nagle wszyscy mówią o terminie, nie o cenie." },
    { d: "14 maj", src: "dyktando — podsumowanie", t: "„Założenie o cenie chyba upadło. Liczy się czas." }
  ];
  var CONCL = {
    h: "Hipoteza, którą system wysuwa",
    t: "„Priorytet przesunął się z ceny na termin — między styczniem a majem. Twoja teza wymaga rewizji."
  };

  window.MalincheGraph = function (opts) {
    if (typeof ForceGraph === "undefined") return null;
    var host = opts.host, el = opts.canvasEl;
    if (!host || !el) return null;
    var TH = Object.assign({}, THEMES[opts.theme === "dark" ? "dark" : "light"]);
    if (opts.themeOverrides) Object.assign(TH, opts.themeOverrides);
    var MASS = opts.mass || 340;
    var SIZE = opts.nodeSizeScale || 1;
    var ZOOM = opts.zoom || 1;
    var CAMX = (opts.camX == null ? -140 : opts.camX);
    var CAMY = (opts.camY == null ? 0 : opts.camY);
    var CARDS = opts.cards || "none";
    var prefersReduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function dims() { return { w: el.clientWidth || 1200, h: el.clientHeight || 760 }; }
    var d0 = dims(), W = d0.w, H = d0.h;

    var seed = opts.seed || 20260621;
    function rnd() { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; }

    var COMMP = [
      { fx: -80, fy: -150, ci: 0,  igniteT: 3700 },
      { fx: 175, fy: -128, ci: 1,  igniteT: 4320 },
      { fx: 6,   fy: 46,   ci: 2,  igniteT: 4940 },
      { fx: 212, fy: -6,   ci: 3,  igniteT: 5560 },
      { fx: 64,  fy: -96,  ci: -1, igniteT: 4150 },
      { fx: 150, fy: -44,  ci: -1, igniteT: 4820 }
    ];

    var GX = 0, GY = 0;
    var nodes = [], links = [], commNodes = [];
    for (var i = 0; i < COMMP.length; i++) {
      var c = COMMP[i];
      var n = { id: "c" + i, kind: "comm", ci: c.ci, igniteT: c.igniteT, fx: c.fx, fy: c.fy, x: c.fx, y: c.fy, _hover: false };
      nodes.push(n); commNodes.push(n);
    }
    var hubCount = 8, hubs = [];
    for (var im = 0; im < MASS; im++) {
      var ang = rnd() * 6.2832, rad = Math.sqrt(rnd()) * 360;
      nodes.push({ id: "m" + im, kind: "mass", deg: 0, x: GX + Math.cos(ang) * rad, y: GY + Math.sin(ang) * rad });
    }
    var taken = {};
    while (hubs.length < hubCount) { var hh = Math.floor(rnd() * MASS); if (!taken[hh]) { taken[hh] = 1; hubs.push(hh); } }
    for (var k = 0; k < MASS; k++) {
      if (taken[k]) continue; var u = rnd();
      if (u < 0.48) { var hb = hubs[Math.floor(rnd() * hubs.length)]; links.push({ source: "m" + k, target: "m" + hb }); }
      else if (u < 0.63) { var tgt = Math.floor(rnd() * MASS); if (tgt !== k && !taken[tgt]) links.push({ source: "m" + k, target: "m" + tgt }); }
    }
    for (var a = 0; a < hubs.length; a++) { for (var b = a + 1; b < hubs.length; b++) { if (rnd() < 0.18) links.push({ source: "m" + hubs[a], target: "m" + hubs[b] }); } }
    for (var cl = 0; cl < 4; cl++) {
      var anchor = Math.floor(rnd() * MASS), members = [anchor];
      for (var mm2 = 0; mm2 < 3; mm2++) { var mmv = Math.floor(rnd() * MASS); if (mmv !== anchor) { members.push(mmv); links.push({ source: "m" + anchor, target: "m" + mmv }); } }
      for (var p = 1; p < members.length; p++) { if (rnd() < 0.5) links.push({ source: "m" + members[p], target: "m" + members[(p % (members.length - 1)) + 1] }); }
    }
    var degById = {};
    links.forEach(function (l) { degById[l.source] = (degById[l.source] || 0) + 1; degById[l.target] = (degById[l.target] || 0) + 1; });
    nodes.forEach(function (nn) { if (nn.kind === "mass") nn.deg = degById[nn.id] || 0; });
    var adj = {};
    links.forEach(function (l) { (adj[l.source] = adj[l.source] || {})[l.target] = 1; (adj[l.target] = adj[l.target] || {})[l.source] = 1; });

    function gravity(cx, cy, strength) {
      var ns;
      function f(alpha) { for (var i = 0; i < ns.length; i++) { var nd = ns[i]; if (nd.fx != null) continue; nd.vx += (cx - nd.x) * strength * alpha; nd.vy += (cy - nd.y) * strength * alpha; } }
      f.initialize = function (_) { ns = _; }; return f;
    }
    function lockCam() { if (!graph) return; try { graph.zoom(ZOOM, 0); graph.centerAt(CAMX, CAMY, 0); } catch (e) {} }
    function clampTick() {
      for (var i = 0; i < nodes.length; i++) { var nd = nodes[i]; if (nd.fx != null) continue;
        if (nd.x < -360) nd.x = -360; else if (nd.x > 360) nd.x = 360;
        if (nd.y < -320) nd.y = -320; else if (nd.y > 320) nd.y = 320; }
      if (graph && Math.abs(graph.zoom() - ZOOM) > 0.0005) lockCam();
    }

    var START = Infinity; // choreography held until reveal()
    function now() { return (typeof performance !== "undefined" ? performance.now() : Date.now()); }
    function T() { return now() - START; }
    function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }
    function ease(pp) { return pp < 0 ? 0 : (pp > 1 ? 1 : (pp * pp * (3 - 2 * pp))); }
    var T_BLOOM = 6700, T_CONCL = 7100, T_AUTOCARD = 7700;

    var hoverNode = null;
    function onHover(node) {
      hoverNode = node;
      commNodes.forEach(function (nn) { nn._hover = false; });
      if (node && node.kind === "comm" && node.ci >= 0) node._hover = true;
      document.body.style.cursor = node ? "pointer" : "default";
    }

    // Graph is built lazily on first reveal() so a fresh, running engine
    // drives the time-based choreography (matches the original landing).
    var graph = null;
    function build() {
      var d = dims(); W = d.w; H = d.h;
      graph = ForceGraph()(el)
        .width(W).height(H)
        .backgroundColor("rgba(0,0,0,0)")
        .nodeLabel("")
        .enableZoomInteraction(false).enablePanInteraction(false).enableNodeDrag(false)
        .cooldownTime(prefersReduce ? 0 : 17000)
        .warmupTicks(prefersReduce ? 420 : 0)
        .d3VelocityDecay(0.42)
        .nodeCanvasObject(drawNode)
        .nodePointerAreaPaint(function (node, color, ctx, scale) {
          ctx.fillStyle = color; var r = (node.kind === "comm" ? 15 : 4.5) / scale;
          ctx.beginPath(); ctx.arc(node.x, node.y, r, 0, 6.2832); ctx.fill();
        })
        .linkCanvasObject(drawLink)
        .onRenderFramePost(overlay)
        .onEngineTick(clampTick)
        .onEngineStop(lockCam)
        .onNodeHover(onHover);

      graph.d3Force("center", null);
      graph.d3Force("charge").strength(-42).distanceMax(340);
      graph.d3Force("link").distance(17).strength(0.08);
      graph.d3Force("gravity", gravity(GX, GY, 0.135));
      graph.graphData({ nodes: nodes, links: links });
      lockCam();
    }

    var rT;
    function onResize() {
      if (!graph) return;
      clearTimeout(rT);
      rT = setTimeout(function () { var d = dims(); W = d.w; H = d.h; graph.width(W).height(H); lockCam(); }, 180);
    }
    addEventListener("resize", onResize, { passive: true });

    function drawNode(node, ctx, scale) {
      if (node.kind === "comm") { drawComm(node, ctx, scale); return; }
      var deg = node.deg || 0;
      var r = (2.0 + Math.min(deg, TH.massMaxStep) * 0.7) * SIZE / scale;
      var al = TH.massBaseA + Math.min(deg, TH.massMaxStep) * TH.massStepA;
      if (hoverNode) {
        if (node === hoverNode) al = Math.min(al + 0.6, TH.massHoverA);
        else if (adj[hoverNode.id] && adj[hoverNode.id][node.id]) al = Math.min(al + 0.4, TH.massNeighborA);
      }
      ctx.beginPath(); ctx.arc(node.x, node.y, r, 0, 6.2832);
      ctx.fillStyle = "rgba(" + TH.mass + "," + al.toFixed(3) + ")"; ctx.fill();
    }
    function drawComm(node, ctx, scale) {
      var t = T(); var prog = ease((t - node.igniteT) / 620);
      if (prog <= 0) {
        ctx.beginPath(); ctx.arc(node.x, node.y, 2.6 / scale, 0, 6.2832);
        ctx.fillStyle = "rgba(" + TH.mass + ",0.42)"; ctx.fill(); return;
      }
      var breath = 1 + 0.11 * Math.sin(t / 680 + node.x);
      var base = (node.ci >= 0 ? 5.4 : 4.2) * SIZE, r = base * breath / scale;
      ctx.save(); ctx.globalAlpha = prog;
      var gr = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, base * 3.0 / scale);
      gr.addColorStop(0, TH.commGlow[0]); gr.addColorStop(0.5, TH.commGlow[1]); gr.addColorStop(1, TH.commGlow[2]);
      ctx.fillStyle = gr; ctx.beginPath(); ctx.arc(node.x, node.y, base * 3.0 / scale, 0, 6.2832); ctx.fill();
      ctx.strokeStyle = "rgba(" + TH.commRing + "," + (0.5 * prog) + ")"; ctx.lineWidth = 1.1 / scale;
      ctx.beginPath(); ctx.arc(node.x, node.y, (base + 4) * breath / scale, 0, 6.2832); ctx.stroke();
      ctx.fillStyle = TH.commCore; ctx.beginPath(); ctx.arc(node.x, node.y, r, 0, 6.2832); ctx.fill();
      ctx.fillStyle = TH.commHi; ctx.beginPath(); ctx.arc(node.x, node.y, r * 0.42, 0, 6.2832); ctx.fill();
      ctx.restore();
    }
    function drawLink(link, ctx, scale) {
      var al = TH.linkA; if (hoverNode && (link.source === hoverNode || link.target === hoverNode)) al = TH.linkHoverA;
      ctx.beginPath(); ctx.moveTo(link.source.x, link.source.y); ctx.lineTo(link.target.x, link.target.y);
      ctx.strokeStyle = "rgba(" + TH.link + "," + al + ")"; ctx.lineWidth = (al > 0.2 ? 1.0 : 0.7) / scale; ctx.stroke();
    }

    var ARCS = [
      { a: 0, b: 4, start: 4300 }, { a: 4, b: 1, start: 4500 },
      { a: 1, b: 5, start: 5050 }, { a: 5, b: 2, start: 5250 },
      { a: 2, b: 3, start: 5650 }, { a: 0, b: 2, start: 5900 }
    ];
    function qbezPartial(ctx, x0, y0, cx, cy, x1, y1, pp) {
      var steps = 26, last = Math.max(1, Math.ceil(steps * pp)); ctx.beginPath();
      for (var i = 0; i <= last; i++) {
        var uu = i / steps; if (uu > pp) uu = pp; var mu = 1 - uu;
        var x = mu * mu * x0 + 2 * mu * uu * cx + uu * uu * x1, y = mu * mu * y0 + 2 * mu * uu * cy + uu * uu * y1;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    // ---- overlay cards (tracked mode only) ----
    var cardEls = [], conclEl = null;
    if (CARDS === "tracked") {
      CONTENT.forEach(function (cc) {
        var x = document.createElement("div"); x.className = "hg-card";
        x.innerHTML = '<div class="d">' + cc.d + ' · <span>' + cc.src + '</span></div><div class="t">' + cc.t + '</div>';
        host.appendChild(x); cardEls.push(x);
      });
      conclEl = document.createElement("div"); conclEl.className = "hg-concl";
      conclEl.innerHTML = '<div class="h">' + CONCL.h + '</div><div class="t">' + CONCL.t + '</div>';
      host.appendChild(conclEl);
    }

    function overlay(ctx, scale) {
      scale = scale || 1; var SC = 1 / scale; var t = T();
      var ccx = 0, ccy = 0; for (var i = 0; i < commNodes.length; i++) { ccx += commNodes[i].x; ccy += commNodes[i].y; }
      ccx /= commNodes.length; ccy /= commNodes.length;
      var bgx = clamp(ccx, -40, 300), bgy = clamp(ccy - 150, -320, -90);

      ctx.save(); ctx.lineCap = "round";
      ctx.shadowColor = TH.arcShadow; ctx.shadowBlur = TH.arcBlur;
      for (var ia = 0; ia < ARCS.length; ia++) {
        var arc = ARCS[ia]; var p = ease((t - arc.start) / 640); if (p <= 0) continue;
        var A = commNodes[arc.a], B = commNodes[arc.b];
        var mx = (A.x + B.x) / 2, my = (A.y + B.y) / 2;
        var cx = mx + (bgx - mx) * 0.32, cy = my + (bgy - my) * 0.32;
        ctx.strokeStyle = "rgba(" + TH.arc + "," + (TH.arcMaxA * p).toFixed(3) + ")"; ctx.lineWidth = 2.0 * SC;
        qbezPartial(ctx, A.x, A.y, cx, cy, B.x, B.y, p);
      }
      ctx.restore();

      var bp = ease((t - T_BLOOM) / 950);
      if (bp > 0) {
        ctx.save(); ctx.globalAlpha = bp; ctx.lineCap = "round";
        ctx.strokeStyle = "rgba(" + TH.bloomSpoke + "," + (0.5 * bp) + ")"; ctx.lineWidth = 1.3 * SC;
        [2, 3].forEach(function (idx) { var nn = commNodes[idx]; ctx.beginPath(); ctx.moveTo(nn.x, nn.y); ctx.lineTo(bgx, bgy); ctx.stroke(); });
        var g = ctx.createRadialGradient(bgx, bgy, 0, bgx, bgy, 50 * SC);
        g.addColorStop(0, TH.bloomHalo[0]); g.addColorStop(0.5, TH.bloomHalo[1]); g.addColorStop(1, TH.bloomHalo[2]);
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(bgx, bgy, 50 * SC, 0, 6.2832); ctx.fill();
        ctx.strokeStyle = "rgba(" + TH.bloomRing + "," + (0.5 * bp) + ")"; ctx.lineWidth = 1.3 * SC;
        ctx.beginPath(); ctx.arc(bgx, bgy, 34 * bp * SC, 0, 6.2832); ctx.stroke();
        ctx.strokeStyle = "rgba(" + TH.bloomRing + "," + (0.2 * bp) + ")";
        ctx.beginPath(); ctx.arc(bgx, bgy, 50 * bp * SC, 0, 6.2832); ctx.stroke();
        ctx.fillStyle = TH.bloomDot; ctx.beginPath(); ctx.arc(bgx, bgy, 6.0 * bp * SC, 0, 6.2832); ctx.fill();
        ctx.fillStyle = TH.bloomHot; ctx.beginPath(); ctx.arc(bgx, bgy, 2.6 * bp * SC, 0, 6.2832); ctx.fill();
        ctx.restore();
      }

      if (CARDS !== "tracked") return;
      if (W < 980) { for (var z = 0; z < cardEls.length; z++) cardEls[z].classList.remove("show"); if (conclEl) conclEl.classList.remove("show"); return; }
      var activeCi = -1, hov = null;
      for (var ih = 0; ih < commNodes.length; ih++) { if (commNodes[ih]._hover && commNodes[ih].ci >= 0) { hov = commNodes[ih]; break; } }
      if (hov) activeCi = hov.ci; else if (t >= T_AUTOCARD) activeCi = 3;
      for (var ci = 0; ci < CONTENT.length; ci++) {
        var elc = cardEls[ci];
        if (ci === activeCi) {
          var cn = null; for (var kk = 0; kk < commNodes.length; kk++) { if (commNodes[kk].ci === ci) { cn = commNodes[kk]; break; } }
          if (cn) {
            var sp = graph.graph2ScreenCoords(cn.x, cn.y), cw = 248;
            elc.style.left = clamp(sp.x - cw / 2, Math.max(40, W * 0.46), W - cw - 14) + "px";
            elc.style.top = clamp(sp.y + 16, 96, H - 120) + "px";
            elc.classList.add("show");
          }
        } else elc.classList.remove("show");
      }
      if (conclEl && t >= T_CONCL) {
        var bs = graph.graph2ScreenCoords(bgx, bgy);
        conclEl.style.left = clamp(bs.x + 62, Math.max(40, W * 0.48), W - 290 - 16) + "px";
        conclEl.style.top = clamp(bs.y + 18, 70, 250) + "px";
        conclEl.classList.add("show");
      }
    }

    // ---- public controls ----
    var built = false, alive = true;
    function reveal() {
      if (!alive) return;
      if (!built) {
        built = true;
        START = now(); if (prefersReduce) START -= 100000;
        build(); // fresh running engine drives the choreography
      } else if (graph) {
        graph.resumeAnimation();
      }
    }
    function pause() { if (alive && graph) graph.pauseAnimation(); }
    function resume() { if (alive && graph) graph.resumeAnimation(); }
    function destroy() {
      alive = false; removeEventListener("resize", onResize);
      try { if (graph) { graph.pauseAnimation(); graph._destructor && graph._destructor(); } } catch (e) {}
    }
    return {
      get graph() { return graph; },
      reveal: reveal, pause: pause, resume: resume, destroy: destroy
    };
  };
})();
