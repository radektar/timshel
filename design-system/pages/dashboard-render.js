/* ============================================================
   Malinche — Insights Dashboard: dev screen renderer.
   Builds every window state from the shared constellation engine.
   ============================================================ */
(function () {
  "use strict";
  var ENG = window.MalincheConstellation;
  var DATA = ENG.DATA, QUEUE = ENG.QUEUE, constellation = ENG.constellation;
  var REDUCE = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ── helpers ── */
  function el(tag, cls) { var e = document.createElement(tag); if (cls) e.className = cls; return e; }
  function chips(notes) {
    return notes.map(function (n) {
      return '<button class="ic-chip" title="Otwórz w Obsidian: ' + n + '"><span class="dia">◇</span>' + n + '</button>';
    }).join("");
  }
  function dirsList(ds) { return '<ul class="win-dir">' + ds.map(function (d) { return "<li>" + d + "</li>"; }).join("") + "</ul>"; }
  function wv() {
    return '<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor"><rect x="1" y="5" width="1.5" height="6" rx=".7"/><rect x="4.2" y="2.5" width="1.5" height="11" rx=".7"/><rect x="7.4" y="0.8" width="1.5" height="14.4" rx=".7"/><rect x="10.6" y="4" width="1.5" height="8" rx=".7"/><rect x="13.4" y="6" width="1.5" height="4" rx=".7"/></svg>';
  }
  function frame(host, label, capHtml, stageCls) {
    var f = el("div", "frame"); if (label) f.setAttribute("data-screen-label", label);
    f.innerHTML = '<span class="cap">' + capHtml + "</span>";
    var st = el("div", "stage" + (stageCls ? " " + stageCls : "")); f.appendChild(st);
    host.appendChild(f); return st;
  }

  /* rail markup; opts: {active, keptIdx, tab} */
  function rail(activeIdx, keptIdx) {
    var items = QUEUE.map(function (q, i) {
      var cls = "conn-item" + (i === activeIdx ? " active" : "") + (keptIdx != null && i === keptIdx ? " kept" : "");
      return '<div class="' + cls + '"><span class="conn-dot" style="background:' + q.tcolor + '"></span>' +
        '<div class="conn-tx"><div class="conn-lab">' + q.label + '</div><div class="conn-snip">' + q.snippet + "</div></div></div>";
    }).join("");
    return '<div class="rail"><div class="rail-h"><span>Połączenia</span><span class="n">' +
      (keptIdx != null ? QUEUE.length - 1 : QUEUE.length) + ' niezobaczonych</span></div>' +
      '<div class="conn">' + items + '</div>' +
      '<div class="rail-foot"><h6>Ostatnie transkrypty</h6>' +
        actRow("Haetta — rozmowa z konstruktorem", "17.06") +
        actRow("8Moons — filmiki 2", "18.06") +
        actRow("Harmonogram 2-tyg. projektu", "03.06") + "</div></div>";
  }
  function actRow(name, t) { return '<div class="act"><span class="wv">' + wv() + "</span>" + name + '<span class="at">' + t + "</span></div>"; }

  /* reader content for a connection */
  function readerHTML(d, narrow) {
    var w = narrow ? 360 : 520, h = narrow ? 172 : 222, s = narrow ? 1.18 : 1.55;
    return '<div class="reader">' +
      '<div class="win-stage">' + constellation(d.layout, { w: w, h: h, scale: s }) +
        (REDUCE ? "" : '<span class="replaywrap"><button class="replay">↻ odtwórz</button></span>') + "</div>" +
      '<div class="win-type"><span class="tdot" style="background:' + d.tcolor + '"></span>' + d.label + "</div>" +
      '<p class="win-q"><span style="color:#9A8C7B">„</span>' + d.rationale + '<span style="color:#9A8C7B">"</span></p>' +
      '<div class="win-cols"><div class="win-side"><h5>Notatki</h5><div class="win-chips">' + chips(d.notes) + "</div></div>" +
        '<div class="win-side"><h5>Kierunki</h5>' + dirsList(d.directions) + "</div></div>" +
      '<div class="win-actions"><button class="ic-btn ic-keep">Zachowaj</button><button class="ic-btn ic-dismiss" style="margin-left:0">Odrzuć</button></div>' +
      '<div class="rd-flash"><span class="sp">✦</span><span class="lb">Zachowane</span><span class="sub">trafia do digestu · następne połączenie</span></div>' +
      "</div>";
  }

  function winBar(activeIdx, opts) {
    opts = opts || {};
    var nav = opts.navText != null ? opts.navText : ("połączenie " + (activeIdx + 1) + " z " + QUEUE.length);
    var right = opts.tabs
      ? '<span class="wtab"><button class="' + (opts.tab !== "act" ? "on" : "") + '">Połączenia</button><button class="' + (opts.tab === "act" ? "on" : "") + '">Aktywność</button></span><span class="wnav">' + nav + "</span>"
      : '<span class="wnav">' + nav + "</span>";
    return '<div class="win-bar"><span class="tl t1"></span><span class="tl t2"></span><span class="tl t3"></span>' +
      '<span class="wt">Malinche — <b>Konstelacja</b></span>' + right + "</div>";
  }

  /* full window. opts: {active, narrow, unfocused, keptIdx, flash, interactive, animate, tabs, tab, bodyHTML} */
  function buildWin(opts) {
    opts = opts || {};
    var active = opts.active == null ? 2 : opts.active;
    var d = QUEUE[active];
    var win = el("div", "win" + (opts.narrow ? " narrow" : "") + (opts.unfocused ? " unfocused" : ""));
    if (opts.label) win.setAttribute("data-screen-label", opts.label);
    var body = opts.bodyHTML != null ? opts.bodyHTML
      : '<div class="win-main">' + rail(active, opts.keptIdx) + readerHTML(d, opts.narrow) + "</div>";
    win.innerHTML = winBar(active, opts) + body;

    if (opts.flash) { var fl = win.querySelector(".rd-flash"); if (fl) fl.classList.add("on"); }

    var svgEl = win.querySelector(".constellation");
    function play() { if (REDUCE || !svgEl) return; svgEl.classList.remove("anim"); void svgEl.offsetWidth; svgEl.classList.add("anim"); }
    var rep = win.querySelector(".replay"); if (rep) rep.addEventListener("click", play);

    if (opts.interactive) {
      var keep = win.querySelector(".ic-keep");
      if (keep) keep.addEventListener("click", function () {
        var f = win.querySelector(".rd-flash"); if (f) { f.classList.add("on"); setTimeout(function () { f.classList.remove("on"); }, 1300); }
      });
      win.querySelectorAll(".conn-item").forEach(function (it, i) {
        if (i < 3) it.addEventListener("click", function () { swap(win, i); });
      });
    }
    if (opts.animate && !REDUCE && svgEl) {
      if ("IntersectionObserver" in window) {
        var io = new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) { play(); io.disconnect(); } }); }, { threshold: 0.2 });
        io.observe(win);
      } else requestAnimationFrame(play);
    }
    return win;
  }

  function swap(win, idx) {
    var d = QUEUE[idx];
    win.querySelectorAll(".conn-item").forEach(function (it, i) { it.classList.toggle("active", i === idx); });
    var nav = win.querySelector(".wnav"); if (nav) nav.textContent = "połączenie " + (idx + 1) + " z " + QUEUE.length;
    var rd = win.querySelector(".reader");
    var narrow = win.classList.contains("narrow");
    rd.innerHTML = readerHTML(d, narrow).replace(/^<div class="reader">|<\/div>$/g, "");
    var svgEl = rd.querySelector(".constellation");
    function play() { if (REDUCE || !svgEl) return; svgEl.classList.remove("anim"); void svgEl.offsetWidth; svgEl.classList.add("anim"); }
    if (!REDUCE) requestAnimationFrame(play);
    var rep = rd.querySelector(".replay"); if (rep) rep.addEventListener("click", play);
    var keep = rd.querySelector(".ic-keep");
    if (keep) keep.addEventListener("click", function () { var f = rd.querySelector(".rd-flash"); if (f) { f.classList.add("on"); setTimeout(function () { f.classList.remove("on"); }, 1300); } });
  }

  /* ════ 1 · chrome & layout ════ */
  (function () {
    var h = document.getElementById("s1Frames");
    var s1 = frame(h, "Okno — aktywne", '<b>Aktywne (focused)</b> · 860 px · <span class="st">stan domyślny</span> · klik w listę i Zachowaj działają', "wide");
    s1.appendChild(buildWin({ active: 2, interactive: true, animate: true, label: "Okno — aktywne" }));
    var s2 = frame(h, "Okno — nieaktywne", '<b>Nieaktywne (unfocused)</b> · przygaszone traffic-lights i kontrast — okno w tle', "wide");
    s2.appendChild(buildWin({ active: 0, unfocused: true }));
    var s3 = frame(h, "Okno — min. szerokość", '<b>Minimalna szerokość</b> · 620 px · próg resize — szyna i czytnik się zwężają, nic nie ginie');
    s3.appendChild(buildWin({ active: 1, narrow: true }));
  })();

  /* ════ 2 · three types ════ */
  (function () {
    var h = document.getElementById("s2Frames");
    [["contradiction", 0, "contradiction-over-time · oś czasu + soczewka"],
     ["shared", 1, "shared-thread · wspólny węzeł"],
     ["emergent", 2, "emergent-idea · triada"]].forEach(function (t) {
      var st = frame(h, "Czytnik — " + t[0], '<b>' + DATA[t[0]].label + "</b> · " + t[2], "wide");
      st.appendChild(buildWin({ active: t[1], animate: true }));
    });
  })();

  /* ════ 3 · actions ════ */
  (function () {
    var h = document.getElementById("s3Frames");
    var a = frame(h, "Zachowaj — rozbłysk", '<b>Zachowaj · moment</b> · mikro-rozbłysk + „zachowane" nad czytnikiem', "wide");
    a.appendChild(buildWin({ active: 2, flash: true }));
    var b = frame(h, "Zachowaj — następne", '<b>Zachowaj · po</b> · poprzednie znika z kolejki (✓), czytnik przechodzi do następnego', "wide");
    b.appendChild(buildWin({ active: 3, keptIdx: 2 }));
    var c = frame(h, "Odrzuć — następne", '<b>Odrzuć</b> · ciche zniknięcie — bez śladu, od razu następne połączenie (3/7 → 4/7)', "wide");
    c.appendChild(buildWin({ active: 3 }));
  })();

  /* ════ 4 · empty & transcribing ════ */
  (function () {
    var h = document.getElementById("s4Frames");
    // empty
    var est = frame(h, "Okno — pusty", '<b>Pusty</b> · korpus przejrzany — spokojny, nie smutny');
    var ewin = el("div", "win"); ewin.style.width = "440px";
    ewin.innerHTML = winBar(0, { navText: "0 połączeń" }) +
      '<div class="win-empty"><div style="width:176px;height:100px;opacity:.5">' + constellation("triad", { dim: true, w: 300, h: 150 }) + "</div>" +
        '<div class="em-h">Cisza w korpusie</div>' +
        '<p class="em-p">Wszystkie połączenia przejrzane. Malinche czyta dalej — gdy coś się zapali, wróci tu rozbłysk.</p></div>';
    est.appendChild(ewin);
    // transcribing skeleton
    var sst = frame(h, "Okno — transkrypcja (skeleton)", '<b>Transkrybuję…</b> · model pracuje — skeleton, dyskretny status, bez fałszywej treści', "wide");
    sst.appendChild(buildSkeleton());
  })();

  function buildSkeleton() {
    var win = el("div", "win");
    var railSk = '<div class="rail"><div class="rail-h"><span>Połączenia</span><span class="n">…</span></div><div class="conn">' +
      Array.from({ length: 5 }).map(function () {
        return '<div class="sk-row"><span class="sk-dot sk"></span><div style="min-width:0"><div class="sk" style="height:9px;width:62%;margin-bottom:6px"></div><div class="sk" style="height:8px;width:90%;margin-bottom:4px"></div><div class="sk" style="height:8px;width:72%"></div></div></div>';
      }).join("") + '</div><div class="rail-foot"><h6>Ostatnie transkrypty</h6>' +
      actRow("Haetta — rozmowa z konstruktorem", "teraz") + "</div></div>";
    var reader = '<div class="reader"><div class="transc-badge"><span class="pulse"></span>Transkrybuję „Haetta — rozmowa z konstruktorem"…</div>' +
      '<div class="sk sk-stage"></div>' +
      '<div class="sk sk-line" style="width:30%"></div>' +
      '<div class="sk sk-line" style="width:92%;height:18px"></div>' +
      '<div class="sk sk-line" style="width:80%;height:18px;margin-bottom:18px"></div>' +
      '<div><span class="sk sk-chip"></span><span class="sk sk-chip" style="width:150px"></span></div></div>';
    win.innerHTML = winBar(0, { navText: "skanuję korpus…" }) + '<div class="win-main">' + railSk + reader + "</div>";
    return win;
  }

  /* ════ 5 · activity ════ */
  (function () {
    var h = document.getElementById("s5Frames");
    var st = frame(h, "Okno — aktywność", '<b>Zakładka Aktywność</b> · ostatnie transkrypty i ile połączeń z nich wyrosło · reużywa PanelModel', "wide");
    var acts = [
      { t: "Haetta — rozmowa z konstruktorem", m: "audio · 14 min · 17.06", c: "2 połączenia" },
      { t: "8Moons — filmiki 2", m: "audio · 22 min · 18.06", c: "3 połączenia" },
      { t: "Planowanie budowy domu — materiały okna dach", m: "notatka · 05.06", c: "1 połączenie" },
      { t: "Harmonogram 2-tyg. projektu", m: "notatka · 03.06", c: "1 połączenie" },
      { t: "Strategia TekTutoreski", m: "notatka · 01.06", c: "1 połączenie" }
    ];
    var list = acts.map(function (a) {
      return '<div class="actv-item"><div class="actv-ic">' + wv() + '</div>' +
        '<div class="actv-tx"><div class="t">' + a.t + '</div><div class="m">' + a.m + "</div></div>" +
        '<div class="actv-meta"><span class="c">' + a.c + "</span>przetworzono</div></div>";
    }).join("");
    var body = '<div class="win-main">' + rail(2) +
      '<div class="reader"><div class="actv"><h4>Aktywność</h4><p class="sub">Z czego Malinche zbudowała tę konstelację — ostatnie 30 dni.</p>' +
      '<div class="actv-list">' + list + "</div></div></div></div>";
    st.appendChild(buildWin({ active: 2, tabs: true, tab: "act", bodyHTML: body, label: "Okno — aktywność" }));
  })();

  /* ════ 6 · entry flow ════ */
  (function () {
    var h = document.getElementById("s6Frames");
    var st = frame(h, "Wejście — powiadomienie → okno", '<b>Wejście</b> · powiadomienie niesie tezę → klik → okno otwiera się na tym połączeniu (nie na liście od zera)', "wide");
    var row = el("div", "flowrow");
    var d = DATA.contradiction;
    row.innerHTML =
      '<div class="notif"><div class="nicon"><span class="mb-dot"></span></div><div class="nbody">' +
        '<div class="nmeta"><span class="napp">Malinche</span><span class="ntime">teraz</span></div>' +
        '<p class="ntitle">Założenie o jakości przesunęło się w miesiąc.</p>' +
        '<p class="ntext">17.06 naturalne materiały; 18.06 — budżet 2× w górę, rozważasz obniżenie jakości.</p></div></div>' +
      '<div class="arrow-step"><span class="ar">→</span><span class="lb">klik otwiera okno na tym połączeniu</span></div>' +
      '<div class="winthumb"><div class="wb"><span class="tl" style="background:#FF5F57"></span><span class="tl" style="background:#FEBC2E"></span><span class="tl" style="background:#28C840"></span><span class="wt">Malinche — <b>Konstelacja</b></span></div>' +
        '<div class="tb"><div class="ts">' + constellation(d.layout, { w: 276, h: 74, scale: 0.58 }) + "</div>" +
        '<div class="ty" style="color:' + d.tcolor + '">' + d.label + "</div>" +
        '<p class="tq">' + d.rationale.slice(0, 96) + '…</p></div></div>';
    st.appendChild(row);
  })();

  /* ════ 7 · redline / spec ════ */
  (function () {
    var box = document.getElementById("specBox");
    box.innerHTML =
      '<div class="spec-grid">' +
        cell("Okno", [["szerokość", "<code>860</code> dflt · <code>620</code> min"], ["wysokość", "<code>560</code> dflt · resizable"], ["radius", '<span class="tok">13 px</span>'], ["chrome", "ciemny custom"], ["cień", '<span class="tok">--shadow-float</span>']]) +
        cell("Szyna (lista)", [["szerokość", "<code>236</code> / <code>192</code>"], ["typ", "NSTableView"], ["wiersz", "dot 7px + 2 linie"], ["aktywny", "gold rail 2.5px"], ["zachowane", "opacity .46 + ✓"]]) +
        cell("Czytnik", [["konstelacja", "<code>520×222</code> @1.55"], ["rationale", '<span class="tok">--font-display</span> 22px'], ["chip", '<span class="tok">--radius-pill</span>'], ["akcje", "Zachowaj / Odrzuć"], ["padding", "16 / 22 / 20"]]) +
        cell("Kolor (tokeny)", [['<span class="sw" style="background:#110F16"></span>tło', '<span class="tok">--obsidian</span>'], ['<span class="sw" style="background:#D6B033"></span>insight', '<code>#D6B033/#F4DD8E</code>'], ['<span class="sw" style="background:#C24010"></span>węzeł', '<span class="tok">--terracotta</span>'], ['<span class="sw" style="background:#46B17E"></span>Zachowaj', '<span class="tok">--status-local</span>'], ["text", '<span class="tok">--content-contrast</span>']]) +
      "</div>" +
      '<div class="spec-map"><h4>Mapowanie na AppKit</h4><ul>' +
        '<li><code>dashboard_window.py</code><span>NSWindow + ciemny titlebar; wzór po <code>status_panel.py</code>, ale samodzielne okno.</span></li>' +
        '<li><code>NSView.drawRect_</code><span>Konstelacja w Core Graphics — węzły (radial glow), łuki (quadratic bézier), złoty rozbłysk; layouty contradiction/thread/triad.</span></li>' +
        '<li><code>NSTableView</code><span>Lista połączeń w szynie; aktywny wiersz = highlight + gold rail; „zachowane" = wygaszony + znacznik.</span></li>' +
        '<li><code>PanelModel</code><span>Zakładka Aktywność reużywa istniejący model ostatnich transkryptów.</span></li>' +
        '<li>pipeline<span>Dowieźć pełne <code>rationale</code> / <code>directions</code> / <code>notes</code> do UI — dziś leci sama nazwa pliku.</span></li>' +
        '<li>a11y<span>Kontrast na ciemnym; <code>prefers-reduced-motion</code> → od razu stan końcowy; polskie diakrytyki.</span></li>' +
      "</ul></div>";
    function cell(title, rows) {
      return '<div class="spec-cell"><h4>' + title + "</h4><dl>" +
        rows.map(function (r) { return "<dt>" + r[0] + "</dt><dd>" + r[1] + "</dd>"; }).join("") + "</dl></div>";
    }
  })();
})();
