/* ════════════════════════════════════════════════════════════════
   Landing — product UI builder. Mounts the REAL Konstelacja window,
   insight card, action states and menu-bar / notification signals
   into host nodes in the landing page. Logic lifted from the
   canonical product pages so the landing demos the live interface.
   ════════════════════════════════════════════════════════════════ */
(function(){
  "use strict";
  var REDUCE = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var STATIC = !!(window.LP_KONSTELACJA_STATIC);
  var uid = 0;

  /* ── digest data (8moons corpus); emergent enriched LONG ── */
  var CONNS = [
    { id:"contradiction", type:"contradiction", color:"#D9542A", label:"Sprzeczność w czasie",
      snippet:"Założenie o jakości przesunęło się w miesiąc — budżet 2× w górę.",
      thesis:"Założenie o jakości przesunęło się w miesiąc — z fundamentu projektu w pozycję do negocjacji pod presją budżetu.",
      notes:["Haetta — rozmowa z konstruktorem","8Moons — filmiki 2"],
      evidence:[
        { date:"17.06", note:"Haetta — rozmowa z konstruktorem", quote:"…projekt stoi na naturalnych materiałach i jakości dla świadomego klienta…" },
        { date:"18.06", note:"8Moons — filmiki 2", quote:"…budżet przekroczony 2×, rozważasz obniżenie jakości materiałów…" }
      ],
      directions:[
        "Co wymusiło zmianę założenia jakościowego — jednorazowy kompromis pod presją budżetu, czy trwała zmiana kierunku, którą warto nazwać wprost?",
        "Filary projektu — naturalne materiały, jakość dla świadomego klienta — bronić mimo budżetu, czy zrewidować i szukać oszczędności gdzie indziej?"
      ] },
    { id:"shared", type:"shared", color:"#D6B033", label:"Wspólny wątek",
      snippet:"Okna jako wąskie gardło wracają w dwóch notatkach.",
      thesis:"Okna wracają w obu notatkach jako to samo wąskie gardło — brak potwierdzeń od producentów napina sierpniowy termin z dwóch stron naraz.",
      notes:["Planowanie budowy domu — materiały okna dach","Przygotowania do Eight Moons — okna i fundamenty"],
      evidence:[
        { date:"09.06", note:"Planowanie budowy domu — materiały okna dach", quote:"…producenci okien nie odpowiadają, a bez nich dach i tak stoi w miejscu…" },
        { date:"14.06", note:"Przygotowania do Eight Moons — okna i fundamenty", quote:"…dostępność okien przed sierpniem niepewna — to blokuje fundamenty…" }
      ],
      directions:[
        "Poszukać alternatywnych producentów już teraz, zanim sierpniowy termin zacznie dyktować wybór za ciebie?",
        "Jak wyglądałby realny plan B na okna — i który element harmonogramu zwalnia, jeśli okna się obsuną?"
      ] },
    { id:"emergent", type:"emergent", color:"#E3C16B", label:"Emergentny pomysł",
      snippet:"Ten sam dylemat skali wraca w różnych projektach.",
      thesis:"Ten sam dylemat skali wraca w trzech projektach: skalować przez automatyzację, czy utrzymać ręczny udział kosztem zasięgu — i za każdym razem rozstrzygasz go od nowa, bez nazwanej zasady, która spinałaby te decyzje.",
      notes:["Strategia TekTutoreski","8Moons — filmiki 2","Harmonogram 2-tyg. projektu"],
      evidence:[
        { date:"03.06", note:"Strategia TekTutoreski", quote:"…automatyzacja daje zasięg, ale gubi to, za co ludzie cię cenią — ręczną, widoczną robotę…" },
        { date:"18.06", note:"8Moons — filmiki 2", quote:"…filmiki kręcone ręcznie biją te „produkcyjne”, choć skalują się zdecydowanie gorzej…" },
        { date:"24.06", note:"Harmonogram 2-tyg. projektu", quote:"…znowu zaplanowałem ręczny montaż, mimo że plan wyraźnie zakładał oddanie tego na zewnątrz…" }
      ],
      directions:[
        "Czy to jedna „zasada skalowania”, którą stosujesz wszędzie — a jeśli tak, jak brzmi wypowiedziana wprost, w jednym zdaniu?",
        "Gdzie hands-on realnie buduje jakość i przewagę, a gdzie tylko blokuje skalę z przyzwyczajenia?",
        "Czy da się te projekty rozdzielić na „świadomie ręczne” i „celowo zautomatyzowane”, zamiast rozstrzygać dylemat za każdym razem od zera?",
        "Co musiałoby być prawdą, żebyś oddał montaż albo produkcję bez poczucia, że tracisz to, co w tej pracy istotne?"
      ] }
  ];
  var TRANSCRIPTS = [
    ["Projekt BOS przygotowan…","26-06-24"],
    ["bie ogarnac powiedzmy s…","26-06-24"],
    ["Powtarzajaca sie instrukcj…","26-06-18"],
    ["Brak tresci audio","26-06-18"]
  ];
  var LLMS = [ { id:"claude", name:"Claude" }, { id:"openai", name:"ChatGPT" }, { id:"gemini", name:"Gemini" } ];
  var LLM = LLMS[0];

  /* role override hook — case pages set window.LP_KONSTELACJA_DATA before this
     script loads (role-specific insights). Main LP / template leave it unset
     and keep the default 8moons corpus above. Backward-compatible. */
  if (window.LP_KONSTELACJA_DATA){
    if (window.LP_KONSTELACJA_DATA.CONNS && window.LP_KONSTELACJA_DATA.CONNS.length) CONNS = window.LP_KONSTELACJA_DATA.CONNS;
    if (window.LP_KONSTELACJA_DATA.TRANSCRIPTS && window.LP_KONSTELACJA_DATA.TRANSCRIPTS.length) TRANSCRIPTS = window.LP_KONSTELACJA_DATA.TRANSCRIPTS;
  }

  function esc(s){ return s.replace(/&/g,"&amp;").replace(/</g,"&lt;"); }

  /* ── rail sigil (small, per-type) ── */
  function sigil(type, color){
    color = color || "#D9542A";
    var id = "sg" + (uid++);
    var defs =
      '<defs>' +
        '<radialGradient id="'+id+'n" cx="50%" cy="50%" r="50%">' +
          '<stop offset="0%" stop-color="'+color+'" stop-opacity=".5"/>' +
          '<stop offset="60%" stop-color="'+color+'" stop-opacity=".08"/>' +
          '<stop offset="100%" stop-color="'+color+'" stop-opacity="0"/>' +
        '</radialGradient>' +
        '<radialGradient id="'+id+'b" cx="50%" cy="50%" r="50%">' +
          '<stop offset="0%" stop-color="#F4DD8E" stop-opacity=".9"/>' +
          '<stop offset="55%" stop-color="#D6B033" stop-opacity=".3"/>' +
          '<stop offset="100%" stop-color="#D6B033" stop-opacity="0"/>' +
        '</radialGradient>' +
      '</defs>';
    function node(x,y){
      return '<circle cx="'+x+'" cy="'+y+'" r="7" fill="url(#'+id+'n)"/>' +
             '<circle cx="'+x+'" cy="'+y+'" r="2.5" fill="#C24010"/>' +
             '<circle cx="'+x+'" cy="'+y+'" r="1" fill="#FAF3E2"/>';
    }
    function bloom(x,y,r){
      r = r||3;
      return '<circle cx="'+x+'" cy="'+y+'" r="'+(r*2.6)+'" fill="url(#'+id+'b)"/>' +
             '<circle cx="'+x+'" cy="'+y+'" r="'+r+'" fill="#F4DD8E"/>' +
             '<circle cx="'+x+'" cy="'+y+'" r="'+(r*0.4)+'" fill="#FFFBF0"/>';
    }
    var p = "";
    if (type === "contradiction"){
      p += '<line x1="5" y1="16" x2="27" y2="16" stroke="'+color+'" stroke-opacity=".28" stroke-width="1" stroke-dasharray="2 4"/>';
      p += '<path d="M8 16 Q16 7 24 16" fill="none" stroke="'+color+'" stroke-opacity=".85" stroke-width="1.5" stroke-linecap="round"/>';
      p += '<path d="M8 16 Q16 25 24 16" fill="none" stroke="'+color+'" stroke-opacity=".85" stroke-width="1.5" stroke-linecap="round"/>';
      p += bloom(16,16,2.4);
      p += node(8,16) + node(24,16);
    } else if (type === "shared"){
      p += '<path d="M9 24 L16 9" fill="none" stroke="'+color+'" stroke-opacity=".7" stroke-width="1.4" stroke-linecap="round"/>';
      p += '<path d="M23 24 L16 9" fill="none" stroke="'+color+'" stroke-opacity=".7" stroke-width="1.4" stroke-linecap="round"/>';
      p += node(9,24) + node(23,24);
      p += bloom(16,9,3);
    } else {
      var nd = [[8,9],[25,12],[15,26]];
      nd.forEach(function(c){ p += '<path d="M16 16 L'+c[0]+' '+c[1]+'" fill="none" stroke="'+color+'" stroke-opacity=".55" stroke-width="1.3" stroke-linecap="round"/>'; });
      nd.forEach(function(c){ p += node(c[0],c[1]); });
      p += bloom(16,16,3);
    }
    return '<svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">'+defs+p+'</svg>';
  }

  /* ── full constellation (card stage / window) ── */
  var LAY = {
    contradiction:{nodes:[[82,86],[228,86]], arcs:[[0,1]], bloom:[155,86], split:true},
    shared:{nodes:[[110,98],[202,98]], arcs:[[0,1]], bloom:[156,40]},
    emergent:{nodes:[[78,60],[226,74],[150,124]], arcs:[[0,1],[1,2],[2,0]], bloom:[151,84]}
  };
  function nodeMarkup(x,y,r){
    return '<g class="c-node">'+
      '<circle cx="'+x+'" cy="'+y+'" r="'+(r*4.6)+'" fill="url(#glowTerra)"/>'+
      '<circle cx="'+x+'" cy="'+y+'" r="'+(r+3.6)+'" fill="none" stroke="rgba(217,84,42,.5)" stroke-width="1"/>'+
      '<circle cx="'+x+'" cy="'+y+'" r="'+r+'" fill="#C24010"/>'+
      '<circle cx="'+x+'" cy="'+y+'" r="'+(r*0.42)+'" fill="#FAF3E2"/></g>';
  }
  function bloomMarkup(x,y,s){
    s=s||1;
    return '<g class="c-bloom">'+
      '<circle cx="'+x+'" cy="'+y+'" r="'+(34*s)+'" fill="url(#glowGold)"/>'+
      '<circle cx="'+x+'" cy="'+y+'" r="'+(24*s)+'" fill="none" stroke="rgba(214,176,51,.5)" stroke-width="1.2"/>'+
      '<circle cx="'+x+'" cy="'+y+'" r="'+(34*s)+'" fill="none" stroke="rgba(214,176,51,.22)" stroke-width="1"/>'+
      '<circle cx="'+x+'" cy="'+y+'" r="'+(5.4*s)+'" fill="#F4DD8E"/>'+
      '<circle cx="'+x+'" cy="'+y+'" r="'+(2.4*s)+'" fill="#FFFBF0"/></g>';
  }
  function constellation(layoutKey, opts){
    opts = opts || {};
    var L = LAY[layoutKey], W = opts.w || 300, H = opts.h || 150, S = opts.scale || 1;
    var bx = L.bloom[0]*S, by = L.bloom[1]*S, parts = [];
    if(!opts.dim){
      if(L.split){
        var p1=L.nodes[0], p2=L.nodes[1];
        var x1=p1[0]*S, y1=p1[1]*S, x2=p2[0]*S, y2=p2[1]*S;
        var mx=(x1+x2)/2, my=(y1+y2)/2, spread=42*S;
        parts.push('<line x1="'+(x1-16*S)+'" y1="'+y1+'" x2="'+(x2+16*S)+'" y2="'+y2+'" stroke="rgba(224,99,58,.28)" stroke-width="1" stroke-dasharray="2 5"/>');
        parts.push('<path class="c-arc" pathLength="1" stroke-dasharray="1" filter="url(#arcGlow)" d="M'+x1+' '+y1+' Q'+mx+' '+(my-spread)+' '+x2+' '+y2+'"/>');
        parts.push('<path class="c-arc" pathLength="1" stroke-dasharray="1" filter="url(#arcGlow)" d="M'+x1+' '+y1+' Q'+mx+' '+(my+spread)+' '+x2+' '+y2+'"/>');
      } else {
        L.arcs.forEach(function(a){
          var p1=L.nodes[a[0]], p2=L.nodes[a[1]];
          var x1=p1[0]*S, y1=p1[1]*S, x2=p2[0]*S, y2=p2[1]*S;
          var mx=(x1+x2)/2, my=(y1+y2)/2, cx=mx+(bx-mx)*0.34, cy=my+(by-my)*0.34;
          parts.push('<path class="c-arc" pathLength="1" stroke-dasharray="1" filter="url(#arcGlow)" d="M'+x1+' '+y1+' Q'+cx+' '+cy+' '+x2+' '+y2+'"/>');
        });
        L.nodes.slice(0,2).forEach(function(p){ parts.push('<path class="c-bloomline" fill="none" stroke="rgba(214,176,51,.5)" stroke-width="1.1" stroke-linecap="round" d="M'+(p[0]*S)+' '+(p[1]*S)+' L'+bx+' '+by+'"/>'); });
      }
    }
    L.nodes.forEach(function(p){ parts.push(nodeMarkup(p[0]*S, p[1]*S, (opts.dim?3:6.4)*S)); });
    if(!opts.dim) parts.push(bloomMarkup(bx, by, S));
    var defs = '<defs>'+
      '<radialGradient id="glowTerra" cx="50%" cy="50%" r="50%"><stop offset="0%" stop-color="rgba(217,84,42,.55)"/><stop offset="50%" stop-color="rgba(194,64,16,.20)"/><stop offset="100%" stop-color="rgba(194,64,16,0)"/></radialGradient>'+
      '<radialGradient id="glowGold" cx="50%" cy="50%" r="50%"><stop offset="0%" stop-color="rgba(244,221,142,.92)"/><stop offset="50%" stop-color="rgba(214,176,51,.30)"/><stop offset="100%" stop-color="rgba(214,176,51,0)"/></radialGradient>'+
      '<filter id="arcGlow" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="0" stdDeviation="2.4" flood-color="rgba(194,64,16,.6)"/></filter>'+
    '</defs>';
    return '<svg class="constellation'+(opts.dim?' dim':'')+'" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">'+defs+parts.join('')+'</svg>';
  }

  function ico(name){
    var i = {
      zadanie: '<rect x="2.5" y="2.5" width="11" height="11" rx="2.6"/><path d="M5.4 8.2l2 2 3.4-3.9"/>',
      kalendarz: '<rect x="2.5" y="3.5" width="11" height="10" rx="1.6"/><path d="M2.5 6.4h11M5.6 2v3M10.4 2v3"/>',
      kopiuj: '<rect x="5" y="5" width="8.5" height="8.5" rx="1.6"/><path d="M10.4 5V3.5A1.4 1.4 0 0 0 9 2.1H3.5A1.4 1.4 0 0 0 2.1 3.5V9a1.4 1.4 0 0 0 1.4 1.4H5"/>',
      wave: '<rect x="0" y="4" width="1.5" height="3" rx=".7"/><rect x="3" y="2" width="1.5" height="7" rx=".7"/><rect x="6" y="0.5" width="1.5" height="10" rx=".7"/><rect x="9" y="3" width="1.5" height="5" rx=".7"/>',
      bookmark: '<path d="M3.5 2.5h9v11l-4.5-2.8-4.5 2.8z"/>'
    };
    var sw = (name === "wave") ? 'fill="currentColor"' : 'fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"';
    var vb = (name === "wave") ? "0 0 12 11" : "0 0 16 16";
    return '<svg viewBox="'+vb+'" '+sw+'>'+i[name]+'</svg>';
  }
  function brandIcon(id){
    if (id === "gemini") return '<svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 .6c.4 3.9 3.5 7 7.4 7.4-3.9.4-7 3.5-7.4 7.4-.4-3.9-3.5-7-7.4-7.4C4.5 7.6 7.6 4.5 8 .6Z"/></svg>';
    if (id === "openai") return '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.1"><ellipse cx="8" cy="8" rx="6.6" ry="2.7"/><ellipse cx="8" cy="8" rx="6.6" ry="2.7" transform="rotate(60 8 8)"/><ellipse cx="8" cy="8" rx="6.6" ry="2.7" transform="rotate(120 8 8)"/></svg>';
    var rays = "";
    for (var k=0;k<12;k++){ var a=k*Math.PI/6, c=Math.cos(a), s=Math.sin(a); rays += '<line x1="'+(8+c*1.4).toFixed(2)+'" y1="'+(8+s*1.4).toFixed(2)+'" x2="'+(8+c*7).toFixed(2)+'" y2="'+(8+s*7).toFixed(2)+'"/>'; }
    return '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.25" stroke-linecap="round">'+rays+'</svg>';
  }

  /* ════════════ DASHBOARD WINDOW ════════════ */
  var dashHost, currentIdx = 2, winRef;
  function readerInner(d){
    var chips = d.notes.map(function(n){ return '<button class="rchip" title="Otwórz w Obsidian: '+esc(n)+'"><span class="dia">◇</span>'+esc(n)+'<span class="arr">↗</span></button>'; }).join("");
    var ev = d.evidence.map(function(e){
      return '<div class="rev-row"><span class="rdate">'+e.date+'</span>'+
        '<div><p class="rquote"><span class="qm">„</span>'+esc(e.quote)+'<span class="qm">"</span></p>'+
        '<span class="rev-src" title="Otwórz w Obsidian: '+esc(e.note)+'"><span class="dia">◇</span>'+esc(e.note)+' ↗</span></div></div>';
    }).join("");
    var check = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5l3 3 6-7"/></svg>';
    var dirs = d.directions.map(function(x,i){ return '<li class="rdir" data-i="'+i+'" role="checkbox" aria-checked="false" tabindex="0"><span class="rdir-check">'+check+'</span><p class="rdir-line">'+esc(x)+'</p></li>'; }).join("");
    return '<div class="rhead"><span class="rsig">'+sigil(d.type,d.color)+'</span><span class="rtype" style="color:'+d.color+'">'+d.label+'</span><span class="reye"><span class="sp">✦</span> Nowy insight</span></div>'+
      '<p class="rthesis"><span class="qm">„</span>'+esc(d.thesis)+'<span class="qm">"</span></p>'+
      '<div class="rchips">'+chips+'</div>'+
      '<button class="rev-toggle"><span class="chev">⌄</span> Dowód <span class="en">· '+d.evidence.length+' zacytowane fragmenty</span></button>'+
      '<div class="revidence"><div class="rev-inner">'+ev+'</div></div>'+
      '<div class="rrule"></div>'+
      '<div class="rdir-h">Kierunki <span class="hint">— myśli do rozwinięcia</span><button class="selall" type="button">Zaznacz wszystkie</button></div>'+
      '<p class="rdir-sub">Zaznacz kierunki, które chcesz rozwinąć — wszystkie wybrane trafiają <b>razem</b> do podłączonego narzędzia LLM. Możesz też utworzyć z nich zadanie, wpis w kalendarzu albo skopiować.</p>'+
      '<ul class="rdirs">'+dirs+'</ul>';
  }
  function railMarkup(activeIdx){
    var items = CONNS.map(function(q,i){ return '<button class="dconn'+(i===activeIdx?" active":"")+'" data-i="'+i+'"><span class="sig">'+sigil(q.type,q.color)+'</span><span class="tx"><span class="lab">'+q.label+'</span><span class="snip">'+esc(q.snippet)+'</span></span></button>'; }).join("");
    var trs = TRANSCRIPTS.map(function(t){ return '<div class="act"><span class="wv">'+ico("wave")+'</span><span class="nm">'+esc(t[0])+'</span><span class="dt">'+t[1]+'</span></div>'; }).join("");
    return '<div class="dsh-rail"><div class="dsh-rail-h"><span>Połączenia</span><span class="n">3 niezobaczonych</span></div><div class="dsh-conn">'+items+'</div><div class="dsh-rail-foot"><h6>Ostatnie transkrypty</h6>'+trs+'</div></div>';
  }
  function selectBarMarkup(){
    var opts = LLMS.map(function(x){ return '<div class="llm-opt" data-llm="'+x.id+'"><span class="lmk">'+brandIcon(x.id)+'</span><span class="nm">'+x.name+'</span><span class="badge">podłączony</span></div>'; }).join("");
    var primary = '<div class="llmwrap"><button class="llm-go"><span class="llmmark">'+brandIcon(LLM.id)+'</span><span class="plab">Kontynuuj w '+LLM.name+'</span></button><button class="llm-sw" aria-label="Zmień narzędzie">⌄</button><div class="llm-menu"><div class="lh">Podłączone narzędzie</div>'+opts+'</div></div>';
    var secondary = '<button class="selact" data-act="Zadanie">'+ico("zadanie")+'Utwórz zadanie</button><button class="selact" data-act="Kalendarz">'+ico("kalendarz")+'Do kalendarza</button><button class="selact" data-act="Kopiuj">'+ico("kopiuj")+'Kopiuj</button>';
    return '<div class="dsh-select"><span class="selcount">0 wybranych</span><div class="selacts">'+primary+secondary+'</div></div>';
  }
  function buildWin(activeIdx){
    var d = CONNS[activeIdx];
    var win = document.createElement("div");
    win.className = "dsh";
    win.setAttribute("data-screen-label", "Konstelacja — " + d.type);
    win.innerHTML =
      '<div class="dsh-bar"><span class="tl t1"></span><span class="tl t2"></span><span class="tl t3"></span><span class="title">Malinche — <b>Konstelacja</b></span><span class="nav">połączenie '+(activeIdx+1)+' z '+CONNS.length+'</span></div>'+
      '<div class="dsh-main">'+railMarkup(activeIdx)+'<div class="dsh-reader"><div class="dsh-scroll">'+readerInner(d)+'</div>'+selectBarMarkup()+'<div class="dsh-foot"><span class="more"></span><span class="sp"></span><button class="f-dismiss">Odrzuć</button><span class="dot">·</span><button class="f-keep">'+ico("bookmark")+'Zachowaj</button><div class="dsh-toast"><span>✦</span><span class="tlab">Przekazano</span></div></div></div></div>';
    if (STATIC) staticWin(win, activeIdx); else wireWin(win, activeIdx);
    return win;
  }
  function staticWin(win, activeIdx){
    var d = CONNS[activeIdx];
    var dirs = win.querySelectorAll(".rdir");
    [0,1].forEach(function(i){ if(dirs[i]){ dirs[i].classList.add("sel"); dirs[i].setAttribute("aria-checked","true"); } });
    var sel = win.querySelector(".dsh-select"); if(sel) sel.classList.add("on");
    var sc = win.querySelector(".selcount"); if(sc) sc.textContent = "2 kierunki wybrane";
    var goLabel = win.querySelector(".llm-go .plab"); if(goLabel) goLabel.textContent = "Kontynuuj w " + LLM.name;
    var goMark = win.querySelector(".llm-go .llmmark"); if(goMark) goMark.innerHTML = brandIcon(LLM.id);
    var optA = win.querySelector('.llm-opt[data-llm="'+LLM.id+'"]'); if(optA) optA.classList.add('active');
  }
  function wireWin(win, activeIdx){
    var scroll = win.querySelector(".dsh-scroll"), selectBar = win.querySelector(".dsh-select"), selCount = win.querySelector(".selcount");
    var dirs = Array.prototype.slice.call(win.querySelectorAll(".rdir")), selall = win.querySelector(".selall");
    var toast = win.querySelector(".dsh-toast"), goLabel = win.querySelector(".llm-go .plab"), goMark = win.querySelector(".llm-go .llmmark");
    var menu = win.querySelector(".llm-menu"), more = win.querySelector(".dsh-foot .more");
    function updateMore(){ var rem = scroll.scrollHeight - scroll.clientHeight - scroll.scrollTop; more.textContent = rem > 24 ? "↓ przewiń, by zobaczyć resztę" : ""; }
    function selected(){ return dirs.filter(function(li){ return li.classList.contains("sel"); }); }
    function refreshLLM(){ goLabel.textContent = "Kontynuuj w " + LLM.name; goMark.innerHTML = brandIcon(LLM.id); win.querySelectorAll(".llm-opt").forEach(function(o){ o.classList.toggle("active", o.getAttribute("data-llm") === LLM.id); }); }
    function updateBar(){ var n = selected().length; selCount.textContent = (n===1)?"1 kierunek wybrany":(n+" kierunki wybrane"); selectBar.classList.toggle("on", n>0); selall.textContent = (n===dirs.length && n>0)?"Odznacz wszystkie":"Zaznacz wszystkie"; updateMore(); }
    win.querySelector(".rev-toggle").addEventListener("click", function(){ scroll.classList.toggle("rgrounded"); updateMore(); });
    dirs.forEach(function(li){ li.addEventListener("click", function(){ li.classList.toggle("sel"); li.setAttribute("aria-checked", li.classList.contains("sel")); updateBar(); }); });
    selall.addEventListener("click", function(){ var all = selected().length === dirs.length; dirs.forEach(function(li){ li.classList.toggle("sel", !all); li.setAttribute("aria-checked", String(!all)); }); updateBar(); });
    win.querySelector(".llm-sw").addEventListener("click", function(e){ e.stopPropagation(); menu.classList.toggle("on"); });
    win.querySelectorAll(".llm-opt").forEach(function(o){ o.addEventListener("click", function(e){ e.stopPropagation(); var id=o.getAttribute("data-llm"); LLM = LLMS.filter(function(x){ return x.id===id; })[0]; refreshLLM(); menu.classList.remove("on"); }); });
    document.addEventListener("click", function(){ menu.classList.remove("on"); });
    function handoff(btn, verbFn){ var n=selected().length; if(!n) return; win.querySelectorAll(".selact.done,.llmwrap.done").forEach(function(x){ x.classList.remove("done"); }); btn.classList.add("done"); toast.querySelector(".tlab").textContent = verbFn(n); toast.classList.add("on"); clearTimeout(win._tt); win._tt = setTimeout(function(){ toast.classList.remove("on"); btn.classList.remove("done"); }, 1900); }
    win.querySelector(".llm-go").addEventListener("click", function(){ handoff(win.querySelector(".llmwrap"), function(n){ return "Wysłano " + n + (n===1?" kierunek":" kierunki") + " do " + LLM.name; }); });
    var secMap = { "Zadanie": function(n){ return "Utworzono " + n + (n===1?" zadanie":" zadań"); }, "Kalendarz": function(n){ return "Dodano " + n + " do kalendarza"; }, "Kopiuj": function(n){ return "Skopiowano " + n + (n===1?" kierunek":" kierunki"); } };
    win.querySelectorAll(".selact[data-act]").forEach(function(b){ var a=b.getAttribute("data-act"); b.addEventListener("click", function(){ handoff(b, secMap[a]); }); });
    var keep = win.querySelector(".f-keep");
    keep.addEventListener("click", function(){ keep.classList.add("saved"); keep.lastChild.textContent = "Zachowane"; setTimeout(function(){ keep.classList.remove("saved"); keep.lastChild.textContent = "Zachowaj"; }, 1500); });
    win.querySelectorAll(".dconn").forEach(function(it){ it.addEventListener("click", function(){ var i=+it.getAttribute("data-i"); if(i===currentIdx) return; currentIdx=i; var fresh=buildWin(i); win.replaceWith(fresh); winRef=fresh; }); });
    scroll.addEventListener("scroll", updateMore);
    win._updateMore = updateMore;
    refreshLLM(); updateBar();
    setTimeout(updateMore, 60); setTimeout(updateMore, 320);
  }

  /* ════════════ INSIGHT CARD + STATES ════════════ */
  function chipsC(notes){ return notes.map(function(n){ return '<button class="ic-chip" title="Otwórz w Obsidian: '+esc(n)+'"><span class="dia">◇</span>'+esc(n)+'</button>'; }).join(''); }
  function dirsC(ds){ return '<ul class="ic-dir">'+ds.map(function(d){return '<li>'+esc(d)+'</li>';}).join('')+'</ul>'; }
  function renderCard(d, idx, total){
    var card = document.createElement('div'); card.className = 'icard';
    card.setAttribute('data-screen-label','Karta — '+d.type);
    var dshort = d.directions.slice(0,2).map(function(x){ return x.split(' — ')[0].replace(/ — .*/,''); });
    card.innerHTML =
      '<div class="ic-top"><span class="ic-eye"><span class="spark">✦</span> Nowy insight</span><span class="ic-count"><button class="nav prev" aria-label="Poprzedni">‹</button>'+(idx+1)+'/'+total+'<button class="nav next" aria-label="Następny">›</button></span></div>'+
      '<div class="ic-stage">'+constellation(d.type)+'</div>'+
      '<div class="ic-type" style="color:'+d.color+'"><span class="tdot" style="background:'+d.color+'"></span>'+d.label+'</div>'+
      '<p class="ic-rationale"><span class="q">„</span>'+esc(d.thesis)+'<span class="q">"</span></p>'+
      '<div class="ic-chips">'+chipsC(d.notes)+'</div>'+
      '<div class="ic-rule"></div>'+
      '<div class="ic-dir-h">Kierunki</div>'+dirsC(d.directions.slice(0,2))+
      '<div class="ic-actions"><button class="ic-btn ic-keep">Zachowaj</button><button class="ic-btn ic-dismiss">Odrzuć</button></div>'+
      '<div class="ic-flash"><span class="sp">✦</span><span class="lb">Zachowane</span></div>'+
      '<div class="greca"></div>';
    var svg = card.querySelector('.constellation');
    function play(){ if(REDUCE) return; svg.classList.remove('anim'); void svg.offsetWidth; svg.classList.add('anim'); }
    card._play = play;
    if(!STATIC){
      var stage = card.querySelector('.ic-stage');
      var rep = document.createElement('button'); rep.className = 'replay'; rep.innerHTML = '↻ odtwórz';
      rep.style.cssText = 'position:absolute;right:8px;bottom:8px;z-index:4'; rep.addEventListener('click', play);
      if(!REDUCE) stage.appendChild(rep);
      var flash = card.querySelector('.ic-flash');
      card.querySelector('.ic-keep').addEventListener('click', function(){ flash.classList.add('on'); setTimeout(function(){ flash.classList.remove('on'); }, 1150); });
      card.querySelector('.ic-dismiss').addEventListener('click', function(){ card.style.transition='opacity .3s'; card.style.opacity='.35'; setTimeout(function(){ card.style.opacity='1'; }, 700); });
    }
    return card;
  }
  function emptyCard(){
    var c = document.createElement('div'); c.className='icard'; c.style.paddingBottom='22px';
    c.innerHTML =
      '<div class="ic-top"><span class="ic-eye" style="color:#8C8273"><span class="spark" style="color:#8C8273;text-shadow:none">✦</span> Insight</span><span class="ic-count">0/0</span></div>'+
      '<div class="ic-empty"><div style="width:150px;height:88px;opacity:.5">'+constellation('shared',{dim:true})+'</div><div class="em-h">Brak nowych połączeń</div><p class="em-p">Malinche czyta dalej. Gdy coś zauważy — zobaczysz tu rozbłysk.</p></div>'+
      '<div class="greca"></div>';
    return c;
  }

  /* ════════════ HANDOFF CLOSE-UP (same dashboard language, action moment) ════════════ */
  function buildHandoff(){
    var d = CONNS[2];
    var thesis = "Ten sam dylemat skali wraca w trzech projektach — bez nazwanej zasady, która spinałaby te decyzje.";
    var check = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5l3 3 6-7"/></svg>';
    var dl = d.directions.slice(0,2).map(function(x){ return '<li class="rdir sel"><span class="rdir-check">'+check+'</span><p class="rdir-line">'+esc(x)+'</p></li>'; }).join('');
    var primary = '<div class="llmwrap"><button class="llm-go"><span class="llmmark">'+brandIcon(LLM.id)+'</span><span class="plab">Kontynuuj w '+LLM.name+'</span></button><button class="llm-sw" aria-label="Zmień narzędzie">⌄</button></div>';
    var sec = '<button class="selact">'+ico('zadanie')+'Zadanie</button><button class="selact">'+ico('kopiuj')+'Kopiuj</button>';
    var el = document.createElement('div'); el.className = 'dsh dcrop';
    el.setAttribute('data-screen-label','Handoff — kierunki');
    el.innerHTML =
      '<div class="rhead"><span class="rsig">'+sigil(d.type,d.color)+'</span><span class="rtype" style="color:'+d.color+'">'+d.label+'</span><span class="reye"><span class="sp">✦</span> Nowy insight</span></div>'+
      '<p class="rthesis" style="font-size:19px;max-width:none"><span class="qm">„</span>'+esc(thesis)+'<span class="qm">"</span></p>'+
      '<div class="rdir-h">Kierunki <span class="hint">— wybrane lecą razem</span></div>'+
      '<ul class="rdirs">'+dl+'</ul>'+
      '<div class="dsh-select on dcrop-bar"><span class="selcount">2 kierunki wybrane</span><div class="selacts">'+primary+sec+'</div></div>';
    return el;
  }

  /* ════════════ MOUNT ════════════ */
  function mount(){
    dashHost = document.getElementById("konstelacjaHost");
    if (dashHost){ dashHost.innerHTML = ""; winRef = buildWin(currentIdx); dashHost.appendChild(winRef); setTimeout(function(){ if(winRef._updateMore) winRef._updateMore(); }, 140); }

    var kartaHost = document.getElementById("kartaHost");
    if (kartaHost){ var c = renderCard(CONNS[0], 0, 3); kartaHost.appendChild(c); if(!REDUCE) requestAnimationFrame(c._play); }

    var keepHost = document.getElementById("keepHost");
    if (keepHost){ var k = renderCard(CONNS[1], 1, 3); k.querySelector('.ic-flash').classList.add('on'); keepHost.appendChild(k); }

    var emptyHost = document.getElementById("emptyHost");
    if (emptyHost){ emptyHost.appendChild(emptyCard()); }

    var handoffHost = document.getElementById("handoffHost");
    if (handoffHost){ handoffHost.innerHTML = ""; handoffHost.appendChild(buildHandoff()); }

    var menubarHost = document.getElementById("menubarHost");
    if (menubarHost){
      menubarHost.innerHTML =
        '<div class="mbwrap">'+
          '<div><div class="menubar"><span class="sysgly"></span><span class="sysgly"></span><span class="sysgly w"></span><span class="mb-mark"></span></div><div class="mb-label" style="margin-top:.55rem">Spoczynek — nic nie czeka</div></div>'+
          '<div><div class="menubar"><span class="sysgly"></span><span class="sysgly"></span><span class="sysgly w"></span><span class="mb-mark"><span class="mb-dot"></span></span></div><div class="mb-label" style="margin-top:.55rem">Czeka insight — złoty punkt + poświata</div></div>'+
        '</div>';
    }
    var notifHost = document.getElementById("notifHost");
    if (notifHost){
      notifHost.innerHTML =
        '<div class="notif"><div class="nicon"><span class="mb-dot"></span></div><div class="nbody"><div class="nmeta"><span class="napp">Malinche</span><span class="ntime">teraz</span></div><p class="ntitle">Założenie o jakości przesunęło się w miesiąc.</p><p class="ntext">17.06 projekt stał na naturalnych materiałach; 18.06 — budżet przekroczony 2×, rozważasz obniżenie jakości.</p></div></div>';
    }

    // reveal product surfaces on scroll
    if(!REDUCE && 'IntersectionObserver' in window){
      var io = new IntersectionObserver(function(es){ es.forEach(function(e){ if(e.isIntersecting){ e.target.classList.add('in'); io.unobserve(e.target); } }); }, {threshold:.12});
      document.querySelectorAll('.p-reveal').forEach(function(el){ io.observe(el); });
    } else {
      document.querySelectorAll('.p-reveal').forEach(function(el){ el.classList.add('in'); });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function(){ if(!STATIC && !window.LP_KONSTELACJA_NOAUTO) mount(); });
  else if(!STATIC && !window.LP_KONSTELACJA_NOAUTO) mount();

  window.LPKonstelacja = { mount: mount, build: buildWin };
})();
