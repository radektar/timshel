# Hero graph — redesign brief for Claude Design

The hero of the Malinche landing is a **live, force-directed knowledge graph** (Obsidian-style)
that plays a 7.7-second choreographed story, then settles. This brief hands it to Claude Design for
a **graphic redesign**: it describes *what the motif means* and *how it behaves*, then gives the
complete working code so a new look can be dropped onto the same skeleton.

---

## 1. What it represents (don't lose this)

The graph is the product's thesis made visual: **scattered recordings → one connected corpus →
an insight nobody asked for.**

- A dim cloud of ~500 small nodes = the raw, forgotten transcripts. Quiet, taupe, low-contrast.
- A few **terracotta nodes ignite** one by one = the moments that actually matter (real quotes,
  surfaced from the noise).
- **Arcs** connect those moments across time = Malinche linking them.
- A **gold "bloom"** flares above them = the synthesized hypothesis the system proposes.
- Overlay cards (quotes) and a final conclusion card spell out the story in words.

The narrative arc — *noise → connection → insight* — is the non-negotiable. Palette, geometry,
particle style, motion curves are all open.

---

## 2. Visual layers (back to front)

| Layer | Role | Current treatment |
|---|---|---|
| Hero background | dark stage | radial gradient `#20202B → #18161F → #110F16` |
| Mass nodes (~496) | forgotten transcripts | taupe dots `rgba(152,142,128,a)`, radius scales with degree |
| Links | latent structure | thin `rgba(124,112,98, .085)`, brighten on hover |
| Community nodes (6) | key moments | terracotta `#C24010` core + radial glow + breathing pulse |
| Arcs (6) | cross-time connections | quadratic-bezier `rgba(217,84,42,…)`, terracotta glow shadow |
| Bloom | the insight | gold burst `#F4DD8E` core, rings, gradient halo |
| Scrim | text legibility | left→right dark gradient so copy sits on solid dark |
| Greca frieze | brand motif | 16px terracotta step-pattern along the bottom edge |
| Overlay cards | quotes | dark glass cards, terracotta border, Fraunces body |
| Conclusion card | the hypothesis | darker card, gold border, Fraunces |

---

## 3. Choreography (timeline, ms from load)

```
3700–5560   community nodes ignite one by one (igniteT per node)
4300–5900   six arcs draw in sequence between them (quadratic beziers)
6700        BLOOM — gold insight flares above the cluster (T_BLOOM)
7100        conclusion card fades in (T_CONCL)
7700        last quote card auto-shows (T_AUTOCARD)
```

Physics: `d3VelocityDecay 0.42`, `charge -42 (distanceMax 340)`, `link distance 17 strength 0.08`,
custom gravity to centre `0.135`, `cooldownTime 17000`. Camera is **locked** (no zoom/pan/drag).
Layout is **deterministic** (seeded PRNG `seed = 20260621`) so the composition is identical every load.

`prefers-reduced-motion`: the engine fast-forwards (warmup ticks, START offset) so it lands on the
final settled frame with no animation.

---

## 4. Exact values in play (for re-tokenizing)

- **Terracotta family:** core `#C24010`, lit `#D9542A`, deep `#9A3009`/`rgba(194,64,16,…)`, highlight `#FAF3E2`
- **Gold / insight:** `#D6B033`, glow `#F4DD8E`, white-hot `#FFFBF0`, halo `rgba(214,176,51,…)`
- **Neutral mass:** node `rgba(152,142,128,…)`, link `rgba(124,112,98,…)`
- **Stage:** `#20202B`/`#18161F`/`#110F16`
- **Cream text:** `--cream #F4E9CF`, `--cream-hi #FAF3E2`
- **Type:** Fraunces (serif, card bodies) + Inter (UI)

These map onto the design-system tokens (`design-system/tokens.css`): `--terracotta`, `--terracotta-lit`,
`--gold`, `--cream(-hi)`, `--hero-dark`, `--obsidian`. A redesign should drive node/arc/bloom colors
from those tokens rather than hard-coded hex.

---

## 5. What's locked vs. open for redesign

**Keep:** the three-beat narrative (noise → connection → insight); camera locked; deterministic
layout; reduced-motion fallback; copy strings and their meaning; desktop overlay cards / mobile
hides them.

**Open:** particle shape & texture (dots vs. glyphs vs. grain); palette mapping; arc style (bezier
vs. straight vs. animated dash); bloom treatment; node-size/opacity ramps; easing curves; whether
hubs read differently; card chrome (glass, border, radius).

---

## 6. Full code

Renderer: [`force-graph`](https://github.com/vasturiano/force-graph) (canvas, d3-force under the
hood), loaded from `vendor/force-graph.min.js`. Everything below is self-contained.

### HTML

```html
<section class="hero-dark">
  <div id="hero-graph"></div>
  <div class="hero-scrim"></div>
  <div class="hero-greca" aria-hidden="true"></div>
  <div class="wrap hero-inner">
    <div class="hero-copy">
      <span class="eyebrow">Jeden system, nie stos plików</span>
      <h1>Masz transkrypty wszystkiego. <span class="accent">I nic z nich nie wynika.</span></h1>
      <p class="lead">Leżą w folderze i udają system. Malinche czyta je razem — łączy, zestawia
        i podsuwa to, czego sam już nie pamiętasz. Lokalnie, na Twoim Macu.</p>
      <div class="cta-row">
        <a class="btn btn-primary" href="#lista">Zapisz się na listę</a>
        <a class="btn btn-ghost-dark" href="https://github.com/radektar/malinche">Zobacz na GitHubie</a>
      </div>
      <div class="local">Działa lokalnie — audio nie opuszcza Maca</div>
    </div>
  </div>
  <div class="hero-concl" id="hero-concl">
    <div class="h">Hipoteza, którą system wysuwa</div>
    <div class="t">„Priorytet przesunął się z ceny na termin — między styczniem a majem.
      Twoja teza wymaga rewizji."</div>
  </div>
</section>
```

### CSS

```css
/* ---- hero: dark band with live force-graph ---- */
.hero-dark{position:relative;z-index:2;overflow:hidden;
  background:radial-gradient(120% 120% at 62% 38%, #20202B 0%, #18161F 46%, #110F16 100%);
  min-height:min(86vh,780px)}
#hero-graph{position:absolute;inset:0;z-index:1}
#hero-graph canvas{display:block}
.hero-scrim{position:absolute;inset:0;z-index:2;pointer-events:none;
  background:linear-gradient(90deg, rgba(15,13,20,.95) 0%, rgba(15,13,20,.72) 26%,
    rgba(15,13,20,.12) 50%, rgba(15,13,20,0) 62%)}
.hero-greca{position:absolute;left:0;right:0;bottom:0;height:16px;z-index:2;opacity:.14;
  pointer-events:none;background-repeat:repeat-x;background-position:center;background-size:auto 16px;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='56' height='16' viewBox='0 0 56 16'%3E%3Cpath d='M4 16 V12 H12 V8 H20 V5 H36 V8 H44 V12 H52 V16 Z' fill='%23C24010'/%3E%3C/svg%3E")}
.hero-inner{position:relative;z-index:3;display:flex;align-items:center;min-height:min(86vh,780px)}
.hero-copy{max-width:560px;padding-block:clamp(3rem,9vh,6rem)}
.hero-dark .eyebrow{color:#D9542A;display:inline-block;margin-bottom:1.3rem}
.hero-dark h1{color:var(--cream-hi);max-width:15ch}
.hero-dark h1 .accent{color:#D9542A}
.hero-dark .lead{color:#C9BBA6;margin-top:1.4rem}
.cta-row{display:flex;gap:.8rem;flex-wrap:wrap;margin-top:2rem}
.btn-ghost-dark{border-color:rgba(244,233,207,.28);color:var(--cream)}
.btn-ghost-dark:hover{border-color:rgba(244,233,207,.7);background:rgba(244,233,207,.06)}
.local{display:inline-flex;align-items:center;gap:.5rem;margin-top:1.5rem;font-size:.84rem;
  font-weight:600;color:var(--jade);letter-spacing:.02em}
.local::before{content:"";width:8px;height:8px;border-radius:50%;background:var(--jade);
  box-shadow:0 0 0 4px rgba(5,120,87,.18)}

/* hero overlay cards (desktop only) */
.hero-card{position:absolute;z-index:4;width:248px;background:rgba(28,24,32,.93);
  border:1px solid rgba(217,84,42,.34);border-radius:13px;padding:11px 14px;
  box-shadow:0 18px 50px -20px rgba(0,0,0,.75);backdrop-filter:blur(7px);
  opacity:0;transform:translateY(6px);transition:opacity .22s,transform .22s;pointer-events:none}
.hero-card.show{opacity:1;transform:translateY(0)}
.hero-card .d{font-size:11.5px;font-weight:600;letter-spacing:.02em;color:#D9542A;margin-bottom:5px}
.hero-card .d span{color:#9A8C7B;font-weight:500}
.hero-card .t{font-family:"Fraunces",Georgia,serif;font-size:15.5px;line-height:1.34;color:var(--cream-hi)}
.hero-concl{position:absolute;z-index:5;width:290px;background:rgba(16,14,20,.96);
  border:1px solid rgba(214,176,51,.42);border-radius:14px;padding:13px 16px;
  box-shadow:0 22px 60px -22px rgba(0,0,0,.85);
  opacity:0;transform:translateY(8px);transition:opacity .5s,transform .5s;pointer-events:none}
.hero-concl.show{opacity:1;transform:translateY(0)}
.hero-concl .h{font-size:11.5px;font-weight:700;letter-spacing:.04em;color:var(--gold);
  margin-bottom:7px;display:flex;align-items:center;gap:.45rem}
.hero-concl .h::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--gold);
  box-shadow:0 0 0 3px rgba(214,176,51,.2)}
.hero-concl .t{font-family:"Fraunces",Georgia,serif;font-size:16px;line-height:1.36;color:var(--cream)}
@media(max-width:980px){
  .hero-card,.hero-concl{display:none!important}
  .hero-scrim{background:linear-gradient(180deg, rgba(15,13,20,.55) 0%, rgba(15,13,20,.8) 58%,
    rgba(15,13,20,.92) 100%)}
  .hero-copy{max-width:none;text-align:center;margin-inline:auto;padding-block:clamp(4rem,12vh,7rem)}
  .hero-dark h1,.hero-dark .lead{margin-inline:auto}
}
```

### JavaScript

```html
<script src="vendor/force-graph.min.js"></script>
<script>
  // ---- hero: live force-directed knowledge graph (Obsidian-style) ----
  (function(){
    if(typeof ForceGraph==="undefined") return;
    var heroEl=document.querySelector(".hero-dark");
    var el=document.getElementById("hero-graph");
    if(!heroEl||!el) return;
    function dims(){ return {w:el.clientWidth||1200, h:el.clientHeight||760}; }
    var d0=dims(), W=d0.w, H=d0.h;
    var prefersReduce=window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    var seed=20260621;
    function rnd(){ seed=(seed*1103515245+12345)&0x7fffffff; return seed/0x7fffffff; }

    var CONTENT=[
      {d:"8 sty", src:"wywiad — uczestnik A",  t:"„Decyduje cena. Reszta się nie liczy."},
      {d:"22 lut",src:"wywiad — uczestnik B",  t:"„Budżet jest święty — najtaniej, jak się da."},
      {d:"30 mar",src:"nagranie — warsztat",   t:"„Nagle wszyscy mówią o terminie, nie o cenie."},
      {d:"14 maj",src:"dyktando — podsumowanie",t:"„Założenie o cenie chyba upadło. Liczy się czas."}
    ];
    var COMMP=[
      {fx:-80, fy:-150, ci:0,  igniteT:3700},
      {fx: 175,fy:-128, ci:1,  igniteT:4320},
      {fx:  6, fy:  46, ci:2,  igniteT:4940},
      {fx: 212,fy:  -6, ci:3,  igniteT:5560},
      {fx:  64,fy: -96, ci:-1, igniteT:4150},
      {fx: 150,fy: -44, ci:-1, igniteT:4820}
    ];

    var GX=0, GY=0;
    var nodes=[], links=[], commNodes=[];
    for(var i=0;i<COMMP.length;i++){ var c=COMMP[i];
      var n={id:"c"+i, kind:"comm", ci:c.ci, igniteT:c.igniteT, fx:c.fx, fy:c.fy, x:c.fx, y:c.fy, _hover:false};
      nodes.push(n); commNodes.push(n);
    }
    var MASS=496, hubCount=8, hubs=[];
    for(var i=0;i<MASS;i++){ var ang=rnd()*6.2832, rad=Math.sqrt(rnd())*360;
      nodes.push({id:"m"+i, kind:"mass", deg:0, x:GX+Math.cos(ang)*rad, y:GY+Math.sin(ang)*rad}); }
    var taken={};
    while(hubs.length<hubCount){ var hh=Math.floor(rnd()*MASS); if(!taken[hh]){taken[hh]=1;hubs.push(hh);} }
    for(var k=0;k<MASS;k++){ if(taken[k]) continue; var u=rnd();
      if(u<0.48){ var hb=hubs[Math.floor(rnd()*hubs.length)]; links.push({source:"m"+k,target:"m"+hb}); }
      else if(u<0.63){ var tgt=Math.floor(rnd()*MASS); if(tgt!==k&&!taken[tgt]) links.push({source:"m"+k,target:"m"+tgt}); } }
    for(var a=0;a<hubs.length;a++){ for(var b=a+1;b<hubs.length;b++){ if(rnd()<0.18) links.push({source:"m"+hubs[a],target:"m"+hubs[b]}); } }
    for(var cl=0;cl<4;cl++){ var anchor=Math.floor(rnd()*MASS), members=[anchor];
      for(var m=0;m<3;m++){ var mm=Math.floor(rnd()*MASS); if(mm!==anchor){ members.push(mm); links.push({source:"m"+anchor,target:"m"+mm}); } }
      for(var p=1;p<members.length;p++){ if(rnd()<0.5) links.push({source:"m"+members[p],target:"m"+members[(p%(members.length-1))+1]}); } }
    var degById={};
    links.forEach(function(l){ degById[l.source]=(degById[l.source]||0)+1; degById[l.target]=(degById[l.target]||0)+1; });
    nodes.forEach(function(n){ if(n.kind==="mass") n.deg=degById[n.id]||0; });
    var adj={};
    links.forEach(function(l){ (adj[l.source]=adj[l.source]||{})[l.target]=1; (adj[l.target]=adj[l.target]||{})[l.source]=1; });

    function gravity(cx,cy,strength){ var ns;
      function f(alpha){ for(var i=0;i<ns.length;i++){ var n=ns[i]; if(n.fx!=null) continue;
        n.vx+=(cx-n.x)*strength*alpha; n.vy+=(cy-n.y)*strength*alpha; } }
      f.initialize=function(_){ ns=_; }; return f; }
    function camX(){ return W>=980?-140:0; }
    function lockCam(){ try{ graph.zoom(1,0); graph.centerAt(camX(),0,0); }catch(e){} }
    function clampTick(){
      for(var i=0;i<nodes.length;i++){ var n=nodes[i]; if(n.fx!=null) continue;
        if(n.x<-360)n.x=-360; else if(n.x>360)n.x=360;
        if(n.y<-320)n.y=-320; else if(n.y>320)n.y=320; }
      if(Math.abs(graph.zoom()-1)>0.0005) lockCam();
    }

    var START=(typeof performance!=="undefined"?performance.now():0);
    if(prefersReduce) START-=100000;
    function T(){ return (typeof performance!=="undefined"?performance.now():0)-START; }
    function clamp(v,lo,hi){ return v<lo?lo:(v>hi?hi:v); }
    function ease(p){ return p<0?0:(p>1?1:(p*p*(3-2*p))); }
    var T_BLOOM=6700, T_CONCL=7100, T_AUTOCARD=7700;

    var hoverNode=null;
    function onHover(node){ hoverNode=node;
      commNodes.forEach(function(n){ n._hover=false; });
      if(node&&node.kind==="comm"&&node.ci>=0) node._hover=true;
      document.body.style.cursor=node?"pointer":"default";
    }

    var graph=ForceGraph()(el)
      .width(W).height(H)
      .backgroundColor("rgba(0,0,0,0)")
      .nodeLabel("")
      .enableZoomInteraction(false).enablePanInteraction(false).enableNodeDrag(false)
      .cooldownTime(prefersReduce?0:17000)
      .warmupTicks(prefersReduce?420:0)
      .d3VelocityDecay(0.42)
      .nodeCanvasObject(drawNode)
      .nodePointerAreaPaint(function(node,color,ctx,scale){ ctx.fillStyle=color;
        var r=(node.kind==="comm"?15:4.5)/scale; ctx.beginPath(); ctx.arc(node.x,node.y,r,0,6.2832); ctx.fill(); })
      .linkCanvasObject(drawLink)
      .onRenderFramePost(overlay)
      .onEngineTick(clampTick)
      .onEngineStop(lockCam)
      .onNodeHover(onHover);

    graph.d3Force("center", null);
    graph.d3Force("charge").strength(-42).distanceMax(340);
    graph.d3Force("link").distance(17).strength(0.08);
    graph.d3Force("gravity", gravity(GX,GY,0.135));
    graph.graphData({nodes:nodes, links:links});
    lockCam();

    var rT;
    addEventListener("resize",function(){ clearTimeout(rT); rT=setTimeout(function(){
      var d=dims(); W=d.w; H=d.h; graph.width(W).height(H); lockCam(); },180); },{passive:true});

    function drawNode(node,ctx,scale){
      if(node.kind==="comm"){ drawComm(node,ctx,scale); return; }
      var deg=node.deg||0;
      var r=(2.0+Math.min(deg,6)*0.7)/scale;
      var a=0.30+Math.min(deg,6)*0.085;
      if(hoverNode){ if(node===hoverNode) a=Math.min(a+0.6,0.97);
        else if(adj[hoverNode.id]&&adj[hoverNode.id][node.id]) a=Math.min(a+0.4,0.85); }
      ctx.beginPath(); ctx.arc(node.x,node.y,r,0,6.2832);
      ctx.fillStyle="rgba(152,142,128,"+a.toFixed(3)+")"; ctx.fill();
    }
    function drawComm(node,ctx,scale){
      var t=T(); var prog=ease((t-node.igniteT)/620);
      if(prog<=0){ ctx.beginPath(); ctx.arc(node.x,node.y,2.6/scale,0,6.2832);
        ctx.fillStyle="rgba(152,142,128,0.42)"; ctx.fill(); return; }
      var breath=1+0.11*Math.sin(t/680+node.x);
      var base=(node.ci>=0?5.4:4.2), r=base*breath/scale;
      ctx.save(); ctx.globalAlpha=prog;
      var gr=ctx.createRadialGradient(node.x,node.y,0,node.x,node.y,base*3.0/scale);
      gr.addColorStop(0,"rgba(217,84,42,0.55)"); gr.addColorStop(0.5,"rgba(194,64,16,0.20)"); gr.addColorStop(1,"rgba(194,64,16,0)");
      ctx.fillStyle=gr; ctx.beginPath(); ctx.arc(node.x,node.y,base*3.0/scale,0,6.2832); ctx.fill();
      ctx.strokeStyle="rgba(217,84,42,"+(0.5*prog)+")"; ctx.lineWidth=1.1/scale;
      ctx.beginPath(); ctx.arc(node.x,node.y,(base+4)*breath/scale,0,6.2832); ctx.stroke();
      ctx.fillStyle="#C24010"; ctx.beginPath(); ctx.arc(node.x,node.y,r,0,6.2832); ctx.fill();
      ctx.fillStyle="#FAF3E2"; ctx.beginPath(); ctx.arc(node.x,node.y,r*0.42,0,6.2832); ctx.fill();
      ctx.restore();
    }
    function drawLink(link,ctx,scale){
      var a=0.085; if(hoverNode&&(link.source===hoverNode||link.target===hoverNode)) a=0.4;
      ctx.beginPath(); ctx.moveTo(link.source.x,link.source.y); ctx.lineTo(link.target.x,link.target.y);
      ctx.strokeStyle="rgba(124,112,98,"+a+")"; ctx.lineWidth=(a>0.2?1.0:0.7)/scale; ctx.stroke();
    }

    var ARCS=[
      {a:0,b:4,start:4300},{a:4,b:1,start:4500},
      {a:1,b:5,start:5050},{a:5,b:2,start:5250},
      {a:2,b:3,start:5650},{a:0,b:2,start:5900}
    ];
    function qbezPartial(ctx,x0,y0,cx,cy,x1,y1,p){
      var steps=26,last=Math.max(1,Math.ceil(steps*p)); ctx.beginPath();
      for(var i=0;i<=last;i++){ var u=i/steps; if(u>p)u=p; var mu=1-u;
        var x=mu*mu*x0+2*mu*u*cx+u*u*x1, y=mu*mu*y0+2*mu*u*cy+u*u*y1;
        if(i===0)ctx.moveTo(x,y); else ctx.lineTo(x,y); }
      ctx.stroke();
    }

    var cardEls=[];
    CONTENT.forEach(function(c){ var x=document.createElement("div"); x.className="hero-card";
      x.innerHTML='<div class="d">'+c.d+' · <span>'+c.src+'</span></div><div class="t">'+c.t+'</div>';
      heroEl.appendChild(x); cardEls.push(x); });
    var conclEl=document.getElementById("hero-concl");

    function overlay(ctx, scale){
      scale=scale||1; var SC=1/scale; var t=T();
      var ccx=0,ccy=0; for(var i=0;i<commNodes.length;i++){ ccx+=commNodes[i].x; ccy+=commNodes[i].y; }
      ccx/=commNodes.length; ccy/=commNodes.length;
      var bgx=clamp(ccx,-40,300), bgy=clamp(ccy-150,-320,-90);

      ctx.save(); ctx.lineCap="round";
      ctx.shadowColor="rgba(194,64,16,0.6)"; ctx.shadowBlur=9;
      for(var i=0;i<ARCS.length;i++){ var arc=ARCS[i]; var p=ease((t-arc.start)/640); if(p<=0) continue;
        var A=commNodes[arc.a], B=commNodes[arc.b];
        var mx=(A.x+B.x)/2, my=(A.y+B.y)/2;
        var cx=mx+(bgx-mx)*0.32, cy=my+(bgy-my)*0.32;
        ctx.strokeStyle="rgba(217,84,42,"+(0.92*p).toFixed(3)+")"; ctx.lineWidth=2.0*SC;
        qbezPartial(ctx,A.x,A.y,cx,cy,B.x,B.y,p); }
      ctx.restore();

      var bp=ease((t-T_BLOOM)/950);
      if(bp>0){ ctx.save(); ctx.globalAlpha=bp; ctx.lineCap="round";
        ctx.strokeStyle="rgba(214,176,51,"+(0.5*bp)+")"; ctx.lineWidth=1.3*SC;
        [2,3].forEach(function(idx){ var nn=commNodes[idx]; ctx.beginPath(); ctx.moveTo(nn.x,nn.y); ctx.lineTo(bgx,bgy); ctx.stroke(); });
        var g=ctx.createRadialGradient(bgx,bgy,0,bgx,bgy,50*SC);
        g.addColorStop(0,"rgba(244,221,142,0.92)"); g.addColorStop(0.5,"rgba(214,176,51,0.32)"); g.addColorStop(1,"rgba(214,176,51,0)");
        ctx.fillStyle=g; ctx.beginPath(); ctx.arc(bgx,bgy,50*SC,0,6.2832); ctx.fill();
        ctx.strokeStyle="rgba(214,176,51,"+(0.5*bp)+")"; ctx.lineWidth=1.3*SC;
        ctx.beginPath(); ctx.arc(bgx,bgy,34*bp*SC,0,6.2832); ctx.stroke();
        ctx.strokeStyle="rgba(214,176,51,"+(0.2*bp)+")";
        ctx.beginPath(); ctx.arc(bgx,bgy,50*bp*SC,0,6.2832); ctx.stroke();
        ctx.fillStyle="#F4DD8E"; ctx.beginPath(); ctx.arc(bgx,bgy,6.0*bp*SC,0,6.2832); ctx.fill();
        ctx.fillStyle="#FFFBF0"; ctx.beginPath(); ctx.arc(bgx,bgy,2.6*bp*SC,0,6.2832); ctx.fill();
        ctx.restore(); }

      if(W<980) return;   // overlay cards desktop-only
      var activeCi=-1, hov=null;
      for(var i=0;i<commNodes.length;i++){ if(commNodes[i]._hover&&commNodes[i].ci>=0){ hov=commNodes[i]; break; } }
      if(hov) activeCi=hov.ci; else if(t>=T_AUTOCARD) activeCi=3;
      for(var ci=0;ci<CONTENT.length;ci++){ var elc=cardEls[ci];
        if(ci===activeCi){ var cn=null; for(var k=0;k<commNodes.length;k++){ if(commNodes[k].ci===ci){ cn=commNodes[k]; break; } }
          if(cn){ var sp=graph.graph2ScreenCoords(cn.x,cn.y), cw=248;
            elc.style.left=clamp(sp.x-cw/2, 540, W-cw-14)+"px";
            elc.style.top =clamp(sp.y+16, 96, H-120)+"px";
            elc.classList.add("show"); } }
        else elc.classList.remove("show"); }
      if(t>=T_CONCL){ var bs=graph.graph2ScreenCoords(bgx,bgy);
        conclEl.style.left=clamp(bs.x+62, 560, W-290-16)+"px";
        conclEl.style.top =clamp(bs.y+18, 70, 250)+"px";
        conclEl.classList.add("show"); }
    }
  })();
</script>
```

---

## 7. How to preview / hand off

Live reference: open `site/index.html` (the graph is the dark hero band at the top). The vendored
renderer is `site/vendor/force-graph.min.js`; a mirror lives at `design-system/vendor/`.

For a redesign, work on this brief's skeleton and re-skin the four draw functions
(`drawNode`, `drawComm`, `drawLink`, `overlay`) — that's where 100% of the look lives. The data
generation, physics, camera lock, and choreography timings can stay untouched.
