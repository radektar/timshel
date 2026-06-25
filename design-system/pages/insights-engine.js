/* ============================================================
   Malinche — constellation engine (reused 1:1 from
   insight-surface.html) + real digest data.

   Inline-SVG generator: nodes with radial glow, quadratic-bezier
   arcs, golden bloom. Layouts: contradiction / thread / triad.
   Entrance animation respects prefers-reduced-motion (callers
   toggle the `.anim` class). Ported natively to NSView.drawRect_
   (Core Graphics) — this prototype is the visual spec.

   Exposed on window.MalincheConstellation.
   ============================================================ */
(function (root) {
  "use strict";

  /* ── real data (digest na korpusie 8moons) — NIE lorem ── */
  var DATA = {
    contradiction: {
      type: "contradiction", label: "Sprzeczność w czasie", tcolor: "#E0633A",
      layout: "contradiction",
      snippet: "Założenie o jakości przesunęło się w miesiąc — budżet 2× w górę.",
      notes: ["Haetta — rozmowa z konstruktorem", "8Moons — filmiki 2"],
      rationale: "17.06 projekt stoi na naturalnych materiałach i jakości dla świadomego klienta; 18.06 — budżet przekroczony 2×, rozważasz obniżenie jakości materiałów.",
      directions: ["Co wymusiło zmianę założenia jakościowego?", "Czy filary projektu trzeba zrewidować, czy bronić mimo budżetu?"]
    },
    shared: {
      type: "shared", label: "Wspólny wątek", tcolor: "#D6B033",
      layout: "thread",
      snippet: "Okna jako wąskie gardło wracają w dwóch notatkach.",
      notes: ["Planowanie budowy domu — materiały okna dach", "Przygotowania do Eight Moons — okna i fundamenty"],
      rationale: "Okna wracają w obu notatkach jako krytyczne wąskie gardło — brak odpowiedzi producentów i niepewna dostępność przed sierpniem.",
      directions: ["Poszukać alternatywnych producentów już teraz?", "Jak wyglądałby plan B na okna?"]
    },
    emergent: {
      type: "emergent", label: "Emergentny pomysł", tcolor: "#E3C16B",
      layout: "triad",
      snippet: "Ten sam dylemat skali wraca w różnych projektach.",
      notes: ["Strategia TekTutoreski", "8Moons — filmiki 2", "Harmonogram 2-tyg. projektu"],
      rationale: "W różnych projektach wraca ten sam dylemat: skalować przez automatyzację, czy utrzymać ręczny udział kosztem skali.",
      directions: ["Czy to jedna „zasada skalowania”, którą stosujesz wszędzie?", "Gdzie hands-on buduje jakość, a gdzie tylko blokuje skalę?"]
    }
  };

  /* The window queue (N=7). First three are the full, clickable
     connections above; the rest are real, terse corpus rows that
     prove „przeglądasz korpus" — list-only, no lorem. */
  var QUEUE = [
    DATA.contradiction,
    DATA.shared,
    DATA.emergent,
    { type: "shared", label: "Wspólny wątek", tcolor: "#D6B033", layout: "thread",
      snippet: "Termin sierpień napina i okna, i montaż paneli — jeden deadline, dwa fronty.",
      notes: ["Przygotowania do Eight Moons — okna i fundamenty", "Harmonogram 2-tyg. projektu"],
      rationale: "Sierpniowy termin napina dwa fronty naraz — dostawę okien i montaż paneli; oba zależą od tej samej rezerwy czasu.",
      directions: ["Który front ma krótszy bufor czasowy?", "Czy przesunięcie montażu zwalnia okna?"] },
    { type: "contradiction", label: "Sprzeczność w czasie", tcolor: "#E0633A", layout: "contradiction",
      snippet: "Plan mówił hands-off; ostatnie notatki znów schodzą w ręczny montaż.",
      notes: ["Strategia TekTutoreski", "8Moons — filmiki 2"],
      rationale: "Plan zakładał oddanie montażu wykonawcy; ostatnie notatki znów opisują ręczną robotę krok po kroku — założenie hands-off się osuwa.",
      directions: ["Co ciągnie cię z powrotem do montażu ręcznego?", "Gdzie oddanie pracy realnie zawiodło?"] },
    { type: "emergent", label: "Emergentny pomysł", tcolor: "#E3C16B", layout: "triad",
      snippet: "Dokumentacja procesu mogłaby być produktem, nie tylko zapisem.",
      notes: ["Strategia TekTutoreski", "Harmonogram 2-tyg. projektu", "8Moons — filmiki 2"],
      rationale: "Zapisy procesu — harmonogramy, rozmowy, filmiki — same układają się w materiał, który mógłby być produktem, nie tylko notatką.",
      directions: ["Czy proces jest już półproduktem?", "Co odróżnia zapis od publikacji?"] },
    { type: "shared", label: "Wspólny wątek", tcolor: "#D6B033", layout: "thread",
      snippet: "Świadomy ekologicznie klient wraca jako kryterium w trzech projektach.",
      notes: ["Haetta — rozmowa z konstruktorem", "Planowanie budowy domu — materiały okna dach"],
      rationale: "Świadomy ekologicznie odbiorca wraca jako kryterium decyzji w trzech projektach — to nie nisza, lecz stała oś wyborów materiałowych.",
      directions: ["Czy to jeden segment, czy trzy różne?", "Gdzie ekologia podnosi koszt, a gdzie wartość?"] }
  ];

  /* ── constellation geometry per layout ── */
  var LAY = {
    contradiction: { nodes: [[82, 86], [228, 86]],          arcs: [[0, 1]], bloom: [155, 86], split: true },
    thread:        { nodes: [[110, 98], [202, 98]],          arcs: [[0, 1]], bloom: [156, 40] },
    triad:         { nodes: [[78, 60], [226, 74], [150, 124]], arcs: [[0, 1], [1, 2], [2, 0]], bloom: [151, 84] }
  };

  function nodeMarkup(x, y, r) {
    return '' +
      '<g class="c-node">' +
        '<circle cx="' + x + '" cy="' + y + '" r="' + (r * 4.6) + '" fill="url(#glowTerra)"/>' +
        '<circle cx="' + x + '" cy="' + y + '" r="' + (r + 3.6) + '" fill="none" stroke="rgba(217,84,42,.5)" stroke-width="1"/>' +
        '<circle cx="' + x + '" cy="' + y + '" r="' + r + '" fill="#C24010"/>' +
        '<circle cx="' + x + '" cy="' + y + '" r="' + (r * 0.42) + '" fill="#FAF3E2"/>' +
      '</g>';
  }
  function bloomMarkup(x, y, s) {
    s = s || 1;
    return '' +
      '<g class="c-bloom">' +
        '<circle cx="' + x + '" cy="' + y + '" r="' + (34 * s) + '" fill="url(#glowGold)"/>' +
        '<circle cx="' + x + '" cy="' + y + '" r="' + (24 * s) + '" fill="none" stroke="rgba(214,176,51,.5)" stroke-width="1.2"/>' +
        '<circle cx="' + x + '" cy="' + y + '" r="' + (34 * s) + '" fill="none" stroke="rgba(214,176,51,.22)" stroke-width="1"/>' +
        '<circle cx="' + x + '" cy="' + y + '" r="' + (5.4 * s) + '" fill="#F4DD8E"/>' +
        '<circle cx="' + x + '" cy="' + y + '" r="' + (2.4 * s) + '" fill="#FFFBF0"/>' +
      '</g>';
  }

  /* build a constellation SVG. opts: {w,h,scale,dim} */
  function constellation(layoutKey, opts) {
    opts = opts || {};
    var L = LAY[layoutKey];
    var W = opts.w || 300, H = opts.h || 150, S = opts.scale || 1;
    var bx = L.bloom[0] * S, by = L.bloom[1] * S;
    var parts = [];
    if (!opts.dim) {
      if (L.split) {
        var p1 = L.nodes[0], p2 = L.nodes[1];
        var x1 = p1[0] * S, y1 = p1[1] * S, x2 = p2[0] * S, y2 = p2[1] * S;
        var mx = (x1 + x2) / 2, my = (y1 + y2) / 2, spread = 42 * S;
        parts.push('<line class="c-axis" x1="' + (x1 - 16 * S) + '" y1="' + y1 + '" x2="' + (x2 + 16 * S) + '" y2="' + y2 + '" stroke="rgba(224,99,58,.28)" stroke-width="1" stroke-dasharray="2 5"/>');
        parts.push('<path class="c-arc" pathLength="1" stroke-dasharray="1" filter="url(#arcGlow)" d="M' + x1 + ' ' + y1 + ' Q' + mx + ' ' + (my - spread) + ' ' + x2 + ' ' + y2 + '"/>');
        parts.push('<path class="c-arc" pathLength="1" stroke-dasharray="1" filter="url(#arcGlow)" d="M' + x1 + ' ' + y1 + ' Q' + mx + ' ' + (my + spread) + ' ' + x2 + ' ' + y2 + '"/>');
      } else {
        L.arcs.forEach(function (a) {
          var p1 = L.nodes[a[0]], p2 = L.nodes[a[1]];
          var x1 = p1[0] * S, y1 = p1[1] * S, x2 = p2[0] * S, y2 = p2[1] * S;
          var mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
          var cx = mx + (bx - mx) * 0.34, cy = my + (by - my) * 0.34;
          parts.push('<path class="c-arc" pathLength="1" stroke-dasharray="1" filter="url(#arcGlow)" d="M' + x1 + ' ' + y1 + ' Q' + cx + ' ' + cy + ' ' + x2 + ' ' + y2 + '"/>');
        });
        L.nodes.slice(0, 2).forEach(function (p) {
          parts.push('<path class="c-bloomline" d="M' + (p[0] * S) + ' ' + (p[1] * S) + ' L' + bx + ' ' + by + '"/>');
        });
      }
    }
    L.nodes.forEach(function (p) {
      var r = (opts.dim ? 3 : 6.4) * S;
      parts.push(nodeMarkup(p[0] * S, p[1] * S, r));
    });
    if (!opts.dim) parts.push(bloomMarkup(bx, by, S));

    var defs = '' +
      '<defs>' +
        '<radialGradient id="glowTerra" cx="50%" cy="50%" r="50%">' +
          '<stop offset="0%" stop-color="rgba(217,84,42,.55)"/>' +
          '<stop offset="50%" stop-color="rgba(194,64,16,.20)"/>' +
          '<stop offset="100%" stop-color="rgba(194,64,16,0)"/>' +
        '</radialGradient>' +
        '<radialGradient id="glowGold" cx="50%" cy="50%" r="50%">' +
          '<stop offset="0%" stop-color="rgba(244,221,142,.92)"/>' +
          '<stop offset="50%" stop-color="rgba(214,176,51,.30)"/>' +
          '<stop offset="100%" stop-color="rgba(214,176,51,0)"/>' +
        '</radialGradient>' +
        '<filter id="arcGlow" x="-30%" y="-30%" width="160%" height="160%">' +
          '<feDropShadow dx="0" dy="0" stdDeviation="2.4" flood-color="rgba(194,64,16,.6)"/>' +
        '</filter>' +
      '</defs>';
    var cls = 'constellation' + (opts.dim ? ' dim' : '');
    return '<svg class="' + cls + '" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">' + defs + parts.join('') + '</svg>';
  }

  root.MalincheConstellation = {
    DATA: DATA, QUEUE: QUEUE, LAY: LAY,
    constellation: constellation,
    nodeMarkup: nodeMarkup, bloomMarkup: bloomMarkup
  };
})(window);
