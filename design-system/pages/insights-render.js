/* ============================================================
   Malinche — Insights UI prototype renderer.
   Builds: system menu (S), popover (A) + states, window (B) +
   states, using the shared constellation engine.
   ============================================================ */
(function () {
  "use strict";
  var ENG = window.MalincheConstellation;
  var DATA = ENG.DATA, QUEUE = ENG.QUEUE, constellation = ENG.constellation;
  var REDUCE = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var TYPES = [DATA.contradiction, DATA.shared, DATA.emergent];

  /* ── tiny SF-style monochrome glyphs for the menu ── */
  var ICO = {
    mark: '<span class="menu-mark"></span>',
    audio: svg('<rect x="2" y="6.5" width="1.7" height="3" rx=".8"/><rect x="5.2" y="3.5" width="1.7" height="9" rx=".8"/><rect x="8.4" y="1.5" width="1.7" height="13" rx=".8"/><rect x="11.6" y="5" width="1.7" height="6" rx=".8"/>', true),
    digest: svg('<rect x="2.5" y="1.5" width="11" height="13" rx="1.6"/><path d="M5 5h6M5 8h6M5 11h3.5"/>', false),
    gear: svg('<path d="M3 6h2M11 6h2M3 10.5h4M9.5 10.5h3.5"/><circle cx="6.6" cy="6" r="1.7"/><circle cx="8.4" cy="10.5" r="1.7"/>', false),
    power: svg('<path d="M8 1.6v6"/><path d="M4.2 4.2a5 5 0 1 0 7.6 0"/>', false)
  };
  // filled=true → solid fill, no stroke; filled=false → outline (stroke, no fill)
  function svg(inner, filled) {
    if (filled) return '<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor">' + inner + '</svg>';
    return '<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">' + inner + '</svg>';
  }

  /* ── chips / dirs helpers (reused grammar) ── */
  function chips(notes) {
    return notes.map(function (n) {
      return '<button class="ic-chip" title="Otwórz w Obsidian: ' + n + '"><span class="dia">◇</span>' + n + '</button>';
    }).join("");
  }
  function dirs(ds) {
    return '<ul class="ic-dir">' + ds.map(function (d) { return "<li>" + d + "</li>"; }).join("") + "</ul>";
  }

  /* ════════════ BLOCK S — system menu ════════════ */
  function menuMarkup(opts) {
    // opts: {light, status:{cls,dot,label}, count}
    var statusDot = opts.status.dot; // 'rest' | 'busy'
    return '<div class="menu' + (opts.light ? " light" : "") + '">' +
      '<div class="mi status disabled"><span class="dot ' + statusDot + '"></span><span class="lab">' + opts.status.label + '</span></div>' +
      '<div class="msep"></div>' +
      '<div class="mi hl"><span class="ico"><span class="spark-ico">✦</span></span><span class="lab">Nowy insight</span><span class="ct">(' + opts.count + ')</span></div>' +
      '<div class="mi"><span class="ico">' + ICO.mark + '</span><span class="lab">Otwórz Malinche</span></div>' +
      '<div class="msep"></div>' +
      '<div class="mi"><span class="ico">' + ICO.audio + '</span><span class="lab">Importuj audio…</span></div>' +
      '<div class="mi"><span class="ico">' + ICO.digest + '</span><span class="lab">Najnowszy digest…</span></div>' +
      '<div class="msep"></div>' +
      '<div class="mi"><span class="ico">' + ICO.gear + '</span><span class="lab">Ustawienia…</span><span class="sc">⌘,</span></div>' +
      '<div class="mi"><span class="ico">' + ICO.power + '</span><span class="lab">Zakończ Malinche</span><span class="sc">⌘Q</span></div>' +
      '</div>';
  }
  (function buildMenus() {
    var host = document.getElementById("menuFrames");
    var rest = { light: false, status: { dot: "rest", label: "Malinche — Spoczynek" }, count: 3 };
    var busy = { light: true, status: { dot: "busy", label: "Malinche — Transkrybuję…" }, count: 1 };
    [
      { cap: '<b>Spoczynek</b> · ciemne systemowe · jadeit · „Nowy insight (3)" = niezobaczone połączenia', o: rest },
      { cap: '<b>Transkrybuję…</b> · jasne systemowe · terakota · podświetlone wejścia do Insights', o: busy }
    ].forEach(function (m) {
      var f = el("div", "frame");
      f.setAttribute("data-screen-label", "Menu — " + m.o.status.label);
      f.innerHTML = '<span class="cap">' + m.cap + "</span>";
      var st = el("div", "stage");
      st.innerHTML = menuMarkup(m.o);
      f.appendChild(st); host.appendChild(f);
    });
  })();

  /* ════════════ BLOCK A — popover card ════════════ */
  function renderCard(d, idx, total) {
    var card = el("div", "icard");
    card.innerHTML =
      '<div class="ic-top">' +
        '<span class="ic-eye"><span class="spark">✦</span> Nowy insight</span>' +
        '<span class="ic-count"><button class="nav prev" aria-label="Poprzedni">‹</button>' + (idx + 1) + "/" + total + '<button class="nav next" aria-label="Następny">›</button></span>' +
      '</div>' +
      '<div class="ic-stage">' + constellation(d.layout) + '</div>' +
      '<div class="ic-type" style="color:' + d.tcolor + '"><span class="tdot" style="background:' + d.tcolor + '"></span>' + d.label + '</div>' +
      '<p class="ic-rationale"><span class="q">„</span>' + d.rationale + '<span class="q">"</span></p>' +
      '<div class="ic-chips">' + chips(d.notes) + '</div>' +
      '<div class="ic-rule"></div>' +
      '<div class="ic-dir-h">Kierunki</div>' + dirs(d.directions) +
      '<div class="ic-actions"><button class="ic-btn ic-keep">Zachowaj</button><button class="ic-btn ic-dismiss">Odrzuć</button></div>' +
      '<div class="ic-flash"><span class="sp">✦</span><span class="lb">Zachowane</span></div>' +
      '<div class="greca"></div>';

    var svgEl = card.querySelector(".constellation");
    function play() { if (REDUCE) return; svgEl.classList.remove("anim"); void svgEl.offsetWidth; svgEl.classList.add("anim"); }
    if (!REDUCE) requestAnimationFrame(play);

    var stage = card.querySelector(".ic-stage");
    if (!REDUCE) {
      var rep = el("button", "replay"); rep.innerHTML = "↻ odtwórz";
      rep.style.cssText = "position:absolute;right:8px;bottom:8px;z-index:4";
      rep.addEventListener("click", play); stage.appendChild(rep);
    }
    var flash = card.querySelector(".ic-flash");
    card.querySelector(".ic-keep").addEventListener("click", function () {
      flash.classList.add("on"); setTimeout(function () { flash.classList.remove("on"); }, 1150);
    });
    card.querySelector(".ic-dismiss").addEventListener("click", function () {
      card.style.transition = "opacity .3s"; card.style.opacity = ".3";
      setTimeout(function () { card.style.opacity = "1"; }, 700);
    });
    return card;
  }

  (function buildA() {
    var host = document.getElementById("aFrames");
    var caps = ["1/3 · contradiction-over-time", "2/3 · shared-thread", "3/3 · emergent-idea"];
    TYPES.forEach(function (d, i) {
      var f = el("div", "frame");
      f.setAttribute("data-screen-label", "Popover — " + d.type);
      f.innerHTML = '<span class="cap"><b>' + d.label + "</b> · " + caps[i] + "</span>";
      var st = el("div", "stage");
      st.appendChild(renderCard(d, i, TYPES.length));
      f.appendChild(st); host.appendChild(f);
    });
  })();

  (function buildAStates() {
    var host = document.getElementById("aStateFrames");

    // keep (frozen flash)
    var kf = frame("Popover — zachowano", '<b>Zachowaj</b> · mikro-rozbłysk + „zachowane"');
    var kCard = renderCard(DATA.contradiction, 0, TYPES.length);
    kCard.querySelector(".ic-flash").classList.add("on");
    kf.st.appendChild(kCard); host.appendChild(kf.f);

    // empty
    var ef = frame("Popover — pusty", '<b>Po przejrzeniu</b> · brak nowych połączeń');
    var eCard = el("div", "icard"); eCard.style.paddingBottom = "22px";
    eCard.innerHTML =
      '<div class="ic-top"><span class="ic-eye" style="color:#8C8273"><span class="spark" style="color:#8C8273;text-shadow:none">✦</span> Insight</span><span class="ic-count">0/0</span></div>' +
      '<div class="ic-empty"><div style="width:150px;height:88px;opacity:.5">' + constellation("thread", { dim: true }) + '</div>' +
        '<div class="em-h">Brak nowych połączeń</div>' +
        '<p class="em-p">Malinche czyta dalej. Gdy coś zauważy — zobaczysz tu rozbłysk.</p></div>' +
      '<div class="greca"></div>';
    ef.st.appendChild(eCard); host.appendChild(ef.f);

    // consequence — two-step desk scene
    var cf = el("div", "frame"); cf.style.flex = "1 1 100%";
    cf.setAttribute("data-screen-label", "Popover — konsekwencja (gaśnie)");
    cf.innerHTML = '<span class="cap"><b>Konsekwencja</b> · klikasz chip „Otwórz w Obsidian" → fokus wychodzi z apki → popover gaśnie. Czytasz z pamięci.</span>';
    var st = el("div", "stage wide");
    var row = el("div"); row.style.cssText = "display:flex;flex-wrap:wrap;gap:1.6rem;align-items:center;justify-content:center";
    row.appendChild(deskPopoverOpen());
    row.appendChild(arrowStep("popover\ngaśnie"));
    row.appendChild(deskPopoverGone());
    st.appendChild(row); cf.appendChild(st); host.appendChild(cf);
  })();

  // desk scene 1: popover open, cursor over chip
  function deskPopoverOpen() {
    var d = DATA.contradiction;
    var desk = el("div", "desk");
    desk.innerHTML = deskBar(true) +
      pmini(d, false) +
      cursorAt(305, 196);
    // position popover anchored under the (waiting) icon, top-right
    var p = desk.querySelector(".pmini");
    p.style.right = "14px"; p.style.top = "32px";
    return wrapCap(desk, "1 · popover otwarty, kursor na notatce");
  }
  // desk scene 2: obsidian front, popover ghost gone
  function deskPopoverGone() {
    var desk = el("div", "desk");
    desk.innerHTML = deskBar(false) +
      obsidian(212, 70, true) +
      pmini(DATA.contradiction, true);
    var p = desk.querySelector(".pmini");
    p.style.right = "14px"; p.style.top = "32px";
    return wrapCap(desk, "2 · Obsidian na wierzchu — popover zniknął");
  }

  /* mini popover markup */
  function pmini(d, ghost) {
    return '<div class="pmini' + (ghost ? " ghost" : "") + '">' +
      '<div class="pe"><span class="spark">✦</span> Nowy insight</div>' +
      '<div class="pstage">' + constellation(d.layout, { w: 184, h: 62, scale: 0.62 }) + '</div>' +
      '<p class="pq">' + d.rationale.slice(0, 78) + '…</p>' +
      '<span class="pchip"><span class="dia">◇</span>' + d.notes[0].split(" — ")[0] + '</span>' +
      '</div>';
  }

  /* ════════════ BLOCK B — window / dashboard ════════════ */
  function railMarkup(activeIdx) {
    var items = QUEUE.map(function (q, i) {
      return '<div class="conn-item' + (i === activeIdx ? " active" : "") + '">' +
        '<span class="conn-dot" style="background:' + q.tcolor + '"></span>' +
        '<div class="conn-tx">' +
          '<div class="conn-lab">' + q.label + "</div>" +
          '<div class="conn-snip">' + q.snippet + "</div>" +
        '</div></div>';
    }).join("");
    return '<div class="rail">' +
      '<div class="rail-h"><span>Połączenia</span><span class="n">' + QUEUE.length + " niezobaczonych</span></div>" +
      '<div class="conn">' + items + "</div>" +
      '<div class="rail-foot"><h6>Ostatnie transkrypty</h6>' +
        actRow("Haetta — rozmowa z konstruktorem", "17.06") +
        actRow("8Moons — filmiki 2", "18.06") +
        actRow("Harmonogram 2-tyg. projektu", "03.06") +
      '</div></div>';
  }
  function actRow(name, t) {
    return '<div class="act"><span class="wv">' + svg('<rect x="0" y="4" width="1.4" height="3" rx=".7"/><rect x="3" y="2" width="1.4" height="7" rx=".7"/><rect x="6" y="0.5" width="1.4" height="10" rx=".7"/><rect x="9" y="3" width="1.4" height="5" rx=".7"/>', true) + "</span>" + name + '<span class="at">' + t + "</span></div>";
  }

  function buildWindow(activeIdx, animate) {
    var d = QUEUE[activeIdx];
    var win = el("div", "win");
    win.setAttribute("data-screen-label", "Okno — żywa konstelacja");
    win.innerHTML =
      '<div class="win-bar"><span class="tl t1"></span><span class="tl t2"></span><span class="tl t3"></span>' +
        '<span class="wt">Malinche — <b>Konstelacja</b></span>' +
        '<span class="wnav">połączenie ' + (activeIdx + 1) + " z " + QUEUE.length + "</span></div>" +
      '<div class="win-main">' + railMarkup(activeIdx) +
        '<div class="reader">' +
          '<div class="win-stage">' + constellation(d.layout, { w: 520, h: 222, scale: 1.55 }) + (REDUCE ? "" : '<span class="replaywrap"><button class="replay">↻ odtwórz</button></span>') + "</div>" +
          '<div class="win-type"><span class="tdot" style="background:' + d.tcolor + '"></span>' + d.label + "</div>" +
          '<p class="win-q"><span style="color:#9A8C7B">„</span>' + d.rationale + '<span style="color:#9A8C7B">"</span></p>' +
          '<div class="win-cols"><div class="win-side"><h5>Notatki</h5><div class="win-chips">' + chips(d.notes) + "</div></div>" +
            '<div class="win-side"><h5>Kierunki</h5><ul class="win-dir">' + d.directions.map(function (x) { return "<li>" + x + "</li>"; }).join("") + "</ul></div></div>" +
          '<div class="win-actions"><button class="ic-btn ic-keep">Zachowaj</button><button class="ic-btn ic-dismiss" style="margin-left:0">Odrzuć</button></div>' +
        "</div>" +
      "</div>";

    var svgEl = win.querySelector(".constellation");
    function play() { if (REDUCE) return; svgEl.classList.remove("anim"); void svgEl.offsetWidth; svgEl.classList.add("anim"); }
    var rep = win.querySelector(".reader .replay");
    if (rep) rep.addEventListener("click", play);
    win.querySelector(".win-actions .ic-keep").addEventListener("click", play);

    // rail interactivity — clicking a full connection swaps the reader
    win.querySelectorAll(".conn-item").forEach(function (it, i) {
      if (i < TYPES.length) it.addEventListener("click", function () { swapReader(win, i); });
    });

    if (animate && !REDUCE) {
      if ("IntersectionObserver" in window) {
        var io = new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) { play(); io.disconnect(); } }); }, { threshold: 0.25 });
        io.observe(win);
      } else requestAnimationFrame(play);
    }
    win._play = play;
    return win;
  }

  function swapReader(win, idx) {
    var d = QUEUE[idx];
    win.querySelectorAll(".conn-item").forEach(function (it, i) { it.classList.toggle("active", i === idx); });
    win.querySelector(".wnav").textContent = "połączenie " + (idx + 1) + " z " + QUEUE.length;
    var reader = win.querySelector(".reader");
    reader.querySelector(".win-stage").innerHTML = constellation(d.layout, { w: 520, h: 222, scale: 1.55 }) + (REDUCE ? "" : '<span class="replaywrap"><button class="replay">↻ odtwórz</button></span>');
    reader.querySelector(".win-type").innerHTML = '<span class="tdot" style="background:' + d.tcolor + '"></span>' + d.label;
    reader.querySelector(".win-q").innerHTML = '<span style="color:#9A8C7B">„</span>' + d.rationale + '<span style="color:#9A8C7B">"</span>';
    var sides = reader.querySelectorAll(".win-side");
    sides[0].querySelector(".win-chips").innerHTML = chips(d.notes);
    sides[1].querySelector(".win-dir").innerHTML = d.directions.map(function (x) { return "<li>" + x + "</li>"; }).join("");
    var svgEl = reader.querySelector(".constellation");
    function play() { if (REDUCE) return; svgEl.classList.remove("anim"); void svgEl.offsetWidth; svgEl.classList.add("anim"); }
    if (!REDUCE) requestAnimationFrame(play);
    var rep = reader.querySelector(".replay");
    if (rep) rep.addEventListener("click", play);
  }

  (function buildB() {
    var host = document.getElementById("bMain");
    var f = el("div", "frame"); f.style.flex = "1 1 100%";
    f.innerHTML = '<span class="cap"><b>Stan po rozbłysku</b> · ~840 px, resizable · aktywne: emergent-idea (3/7) · klik w połączenie z listy przełącza czytnik</span>';
    var st = el("div", "stage wide");
    st.appendChild(buildWindow(2, true));
    f.appendChild(st); host.appendChild(f);
  })();

  (function buildBStates() {
    var host = document.getElementById("bStateFrames");

    // empty window
    var ef = el("div", "frame");
    ef.setAttribute("data-screen-label", "Okno — pusty");
    ef.innerHTML = '<span class="cap"><b>Pusty</b> · korpus przejrzany — spokojny, nie smutny</span>';
    var est = el("div", "stage");
    var ewin = el("div", "win"); ewin.style.width = "420px";
    ewin.innerHTML =
      '<div class="win-bar"><span class="tl t1"></span><span class="tl t2"></span><span class="tl t3"></span>' +
        '<span class="wt">Malinche — <b>Konstelacja</b></span><span class="wnav">0 połączeń</span></div>' +
      '<div class="win-empty"><div style="width:170px;height:96px;opacity:.5">' + constellation("triad", { dim: true, w: 300, h: 150 }) + "</div>" +
        '<div class="em-h">Cisza w korpusie</div>' +
        '<p class="em-p">Wszystkie połączenia przejrzane. Malinche czyta dalej — gdy coś się zapali, wróci tu rozbłysk.</p></div>';
    est.appendChild(ewin); ef.appendChild(est); host.appendChild(ef);

    // consequence — window persists beside Obsidian
    var cf = el("div", "frame"); cf.style.flex = "1 1 100%";
    cf.setAttribute("data-screen-label", "Okno — konsekwencja (trwa)");
    cf.innerHTML = '<span class="cap"><b>Konsekwencja</b> · klikasz chip → Obsidian otwiera się obok, a okno Malinche <b>trwa</b>. Czytasz tezę i notatkę jednocześnie — to czego popover nie umie.</span>';
    var st = el("div", "stage wide");
    var desk = el("div", "desk"); desk.style.width = "560px"; desk.style.height = "340px";
    desk.innerHTML = deskBar(false) + obsidian(18, 56, true) + wmini();
    var w = desk.querySelector(".wmini"); w.style.right = "16px"; w.style.bottom = "16px";
    var ob = desk.querySelector(".obs"); ob.style.left = "18px"; ob.style.top = "56px";
    st.appendChild(desk); cf.appendChild(st); host.appendChild(cf);
  })();

  /* mini reader window for B consequence */
  function wmini() {
    var d = DATA.emergent;
    return '<div class="wmini">' +
      '<div class="wb"><span class="tl" style="background:#FF5F57"></span><span class="tl" style="background:#FEBC2E"></span><span class="tl" style="background:#28C840"></span><span class="wt">Malinche — <b>Konstelacja</b></span></div>' +
      '<div class="wbody">' +
        '<div class="wstage">' + constellation(d.layout, { w: 212, h: 80, scale: 0.62 }) + "</div>" +
        '<div class="wty"><span class="tdot"></span>' + d.label + "</div>" +
        '<p class="wq">' + d.rationale.slice(0, 92) + '…</p>' +
        '<div class="wchips"><span class="wchip">◇ Strategia TekTutoreski</span><span class="wchip">◇ 8Moons</span></div>' +
      "</div></div>";
  }

  /* ════════════ shared mock helpers ════════════ */
  function deskBar(waiting) {
    return '<div class="desk-bar"><span class="sg"></span><span class="sg w"></span><span class="sg"></span>' +
      '<span class="desk-mark">' + (waiting ? '<span class="gd"></span>' : "") + "</span></div>";
  }
  function obsidian(left, top, withHighlight) {
    var hl = withHighlight ? " hgl" : "";
    var o = el("div", "obs");
    o.style.left = left + "px"; o.style.top = top + "px";
    o.innerHTML =
      '<div class="obs-bar"><span class="tl" style="background:#FF5F57"></span><span class="tl" style="background:#FEBC2E"></span><span class="tl" style="background:#28C840"></span>' +
        '<span class="ot"><span class="pur">◆</span> Haetta — rozmowa z konstruktorem.md</span></div>' +
      '<div class="obs-body"><div class="obs-side"><span class="fl on"></span><span class="fl"></span><span class="fl"></span><span class="fl"></span><span class="fl"></span></div>' +
        '<div class="obs-main"><h6>Rozmowa z konstruktorem</h6>' +
          '<div class="ln s1"></div><div class="ln s2"></div><div class="ln s3' + hl + '"></div><div class="ln s1"></div><div class="ln s4"></div></div></div>';
    return o.outerHTML;
  }
  function cursorAt(x, y) {
    return '<svg class="cursor" style="left:' + x + 'px;top:' + y + 'px" viewBox="0 0 16 16"><path d="M1 1 L1 12 L4 9.2 L6 13.6 L8 12.8 L6 8.4 L10 8.4 Z" fill="#fff" stroke="#1A1A1A" stroke-width="1" stroke-linejoin="round"/></svg>';
  }
  function arrowStep(label) {
    var s = el("div", "arrow-step");
    s.innerHTML = '<span class="ar">→</span><span class="lb">' + label.replace(/\n/g, "<br>") + "</span>";
    return s;
  }
  function wrapCap(deskEl, cap) {
    var box = el("div");
    box.style.cssText = "display:flex;flex-direction:column;gap:.55rem;align-items:center";
    box.appendChild(deskEl);
    var c = el("div"); c.style.cssText = "font-family:var(--font-mono);font-size:11px;color:var(--ink-soft);text-align:center;max-width:" + 430 + "px";
    c.textContent = cap; box.appendChild(c);
    return box;
  }

  /* ── dom helpers ── */
  function el(tag, cls) { var e = document.createElement(tag); if (cls) e.className = cls; return e; }
  function frame(label, capHtml) {
    var f = el("div", "frame"); f.setAttribute("data-screen-label", label);
    f.innerHTML = '<span class="cap">' + capHtml + "</span>";
    var st = el("div", "stage"); f.appendChild(st);
    return { f: f, st: st };
  }
})();
