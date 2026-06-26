const pptxgen = require("pptxgenjs");
const data = JSON.parse(process.argv[2]);

// ── Colors Micki Analítica ──────────────────────────────────────────────────
const C_BLUE    = "185FA5";
const C_BLUE_LT = "EBF4FC";
const C_DARK    = "1a2744";
const C_GRAY    = "6b7280";
const C_WHITE   = "FFFFFF";
const C_GREEN   = "16a34a";
const C_RED     = "dc2626";
const C_AMBER   = "d97706";
const C_BG      = "F8FAFC";
const C_BORDER  = "E2E8F0";

const makeShadow = () => ({ type:"outer", color:"000000", blur:8, offset:2, angle:45, opacity:0.08 });

let pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author  = "Micki Analítica";
pres.title   = `Post-Partit ${data.nom_a} vs ${data.nom_b}`;

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 1 — PORTADA
// ══════════════════════════════════════════════════════════════════════════════
let s1 = pres.addSlide();
s1.background = { color: C_DARK };

// Franja accent superior
s1.addShape(pres.shapes.RECTANGLE, { x:0, y:0, w:10, h:0.08, fill:{ color:C_BLUE } });

// Títol principal
s1.addText("ANÀLISI POST-PARTIT", {
  x:0.6, y:0.7, w:8.8, h:0.7,
  fontSize:13, fontFace:"Calibri", bold:true, color:C_BLUE,
  charSpacing:6, align:"left"
});
s1.addText(`${data.nom_a}  vs  ${data.nom_b}`, {
  x:0.6, y:1.35, w:8.8, h:1.1,
  fontSize:36, fontFace:"Cambria", bold:true, color:C_WHITE, align:"left"
});

// Marcador gran
s1.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x:0.6, y:2.55, w:3.8, h:1.5,
  fill:{ color:C_BLUE, transparency:15 }, rectRadius:0.12
});
s1.addText(`${data.score_a}`, {
  x:0.6, y:2.55, w:1.6, h:1.5,
  fontSize:54, fontFace:"Cambria", bold:true, color:C_WHITE, align:"center", valign:"middle"
});
s1.addText("—", {
  x:2.1, y:2.55, w:0.8, h:1.5,
  fontSize:36, fontFace:"Calibri", color:"8899BB", align:"center", valign:"middle"
});
s1.addText(`${data.score_b}`, {
  x:2.8, y:2.55, w:1.6, h:1.5,
  fontSize:54, fontFace:"Cambria", bold:true, color:"8899BB", align:"center", valign:"middle"
});

// Resultat
const guanya = data.score_a > data.score_b;
s1.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x:0.6, y:4.15, w:1.5, h:0.42,
  fill:{ color: guanya ? C_GREEN : C_RED }, rectRadius:0.06
});
s1.addText(guanya ? "VICTÒRIA" : "DERROTA", {
  x:0.6, y:4.15, w:1.5, h:0.42,
  fontSize:10, fontFace:"Calibri", bold:true, color:C_WHITE, align:"center", valign:"middle"
});

// Quarts
const quarts = data.quarts || [];
if (quarts.length) {
  let qtxt = quarts.map(q => `${q.label}  ${q.a}–${q.b}`).join("   |   ");
  s1.addText(qtxt, {
    x:0.6, y:4.65, w:8.8, h:0.35,
    fontSize:11, fontFace:"Calibri", color:"6688AA", align:"left"
  });
}

// Data i categoria
s1.addText(`${data.data || ""}  ·  FCBQ  ·  Micki Analítica`, {
  x:0.6, y:5.2, w:8.8, h:0.3,
  fontSize:10, fontFace:"Calibri", color:"445566", align:"left"
});

s1.addNotes("Portada del post-partit. Pots editar el marcador i el resultat si cal.");

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 2 — MÈTRIQUES CLAU (4 targetes + gràfic punts per quart)
// ══════════════════════════════════════════════════════════════════════════════
let s2 = pres.addSlide();
s2.background = { color: C_BG };

s2.addText("Mètriques clau del partit", {
  x:0.5, y:0.22, w:9, h:0.5,
  fontSize:22, fontFace:"Cambria", bold:true, color:C_DARK, align:"left", margin:0
});
s2.addText(data.nom_a, {
  x:0.5, y:0.72, w:9, h:0.28,
  fontSize:12, fontFace:"Calibri", color:C_BLUE, align:"left", margin:0
});

// 4 targetes de mètriques
const metriques = data.metriques || [];
const card_x = [0.5, 3.0, 5.5, 7.82];
const card_w  = 2.22;
metriques.slice(0,4).forEach((m, i) => {
  const cx = card_x[i];
  s2.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x:cx, y:1.1, w:card_w, h:1.45,
    fill:{ color:C_WHITE }, rectRadius:0.1,
    shadow: makeShadow()
  });
  s2.addText(m.label, {
    x:cx+0.15, y:1.18, w:card_w-0.3, h:0.3,
    fontSize:9, fontFace:"Calibri", color:C_GRAY, align:"left", margin:0
  });
  s2.addText(String(m.valor), {
    x:cx+0.15, y:1.48, w:card_w-0.3, h:0.6,
    fontSize:28, fontFace:"Cambria", bold:true, color:C_DARK, align:"left", margin:0
  });
  if (m.sub) {
    const subColor = m.sub.startsWith("+") ? C_GREEN : (m.sub.startsWith("-") ? C_RED : C_GRAY);
    s2.addText(m.sub, {
      x:cx+0.15, y:2.07, w:card_w-0.3, h:0.3,
      fontSize:9, fontFace:"Calibri", color:subColor, align:"left", margin:0
    });
  }
});

// Gràfic punts per quart (barres agrupades)
const quart_labels = quarts.map(q => q.label);
const vals_a = quarts.map(q => q.a);
const vals_b = quarts.map(q => q.b);
if (quart_labels.length > 0) {
  s2.addChart(pres.charts.BAR, [
    { name: data.nom_a, labels: quart_labels, values: vals_a },
    { name: data.nom_b, labels: quart_labels, values: vals_b }
  ], {
    x:0.5, y:2.75, w:9, h:2.55, barDir:"col", barGrouping:"clustered",
    chartColors: [C_BLUE, "CCDDEE"],
    chartArea:{ fill:{ color:C_WHITE }, roundedCorners:true },
    catAxisLabelColor: C_GRAY, valAxisLabelColor: C_GRAY,
    valGridLine:{ color:C_BORDER, size:0.5 }, catGridLine:{ style:"none" },
    showValue:true, dataLabelColor:C_DARK, dataLabelFontSize:9,
    showLegend:true, legendPos:"b", legendFontSize:10,
    showTitle:false
  });
}

s2.addNotes("Pots modificar qualsevol valor d'aquest slide directament a PowerPoint.");

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 3 — JUGADORES: USAGE% vs TS% + TAULA TOP 5
// ══════════════════════════════════════════════════════════════════════════════
let s3 = pres.addSlide();
s3.background = { color: C_BG };

s3.addText("Rendiment individual — " + data.nom_a, {
  x:0.5, y:0.22, w:9, h:0.5,
  fontSize:22, fontFace:"Cambria", bold:true, color:C_DARK, align:"left", margin:0
});

// Scatter Usage% vs TS%
const jugadores = data.jugadores || [];
if (jugadores.length > 0) {
  s3.addChart(pres.charts.SCATTER, [
    { name:"X", values: jugadores.map(j => j.usage) },
    { name:"Jugadores", values: jugadores.map(j => j.ts) }
  ], {
    x:0.5, y:0.85, w:5.0, h:3.8,
    chartColors:[C_BLUE],
    chartArea:{ fill:{ color:C_WHITE }, roundedCorners:true },
    catAxisLabelColor:C_GRAY, valAxisLabelColor:C_GRAY,
    valGridLine:{ color:C_BORDER, size:0.5 }, catGridLine:{ color:C_BORDER, size:0.5 },
    showLegend:false, showTitle:false,
    catAxisTitle:"Usage%", valAxisTitle:"TS%", showCatAxisTitle:true, showValAxisTitle:true,
  });
  s3.addText("Usage% → eix X   ·   TS% → eix Y", {
    x:0.5, y:4.68, w:5.0, h:0.25,
    fontSize:8, fontFace:"Calibri", color:C_GRAY, align:"center", margin:0
  });
}

// Taula top jugadores
const cols_jug = ["Jugadora","Pts","Usage%","TS%","Pts/Tir","+/-"];
const header_row = cols_jug.map(c => ({
  text:c, options:{ bold:true, color:C_WHITE,
    fill:{ color:C_BLUE }, fontSize:9, fontFace:"Calibri", align:"center" }
}));
const data_rows = jugadores.slice(0,8).map((j,i) => {
  const bg = i%2===0 ? C_WHITE : "F0F5FB";
  return [j.nom, j.pts, j.usage+"%", j.ts+"%", j.ppt, j.pm].map(v => ({
    text: String(v ?? "—"),
    options:{ fill:{ color:bg }, fontSize:9, fontFace:"Calibri",
              color:C_DARK, align:v===j.nom?"left":"center" }
  }));
});
if (data_rows.length) {
  s3.addTable([header_row, ...data_rows], {
    x:5.8, y:0.85, w:3.85, colW:[1.45,0.48,0.55,0.48,0.48,0.41],
    border:{ pt:0.5, color:C_BORDER },
    rowH:0.36
  });
}

// ROT
if (data.rot !== undefined) {
  const rot_color = data.rot >= 7.5 ? C_GREEN : (data.rot >= 5.5 ? C_AMBER : C_RED);
  const rot_label = data.rot >= 7.5 ? "Excel·lent" : (data.rot >= 5.5 ? "Bo" : "Millorable");
  s3.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x:5.8, y:4.55, w:3.85, h:0.75,
    fill:{ color:C_WHITE }, rectRadius:0.08, shadow:makeShadow()
  });
  s3.addText([
    { text:"ROT  ", options:{ color:C_GRAY, fontSize:11, fontFace:"Calibri" } },
    { text:String(data.rot.toFixed(1)), options:{ color:C_DARK, fontSize:20, fontFace:"Cambria", bold:true } },
    { text:`  /10  —  ${rot_label}`, options:{ color:rot_color, fontSize:11, fontFace:"Calibri", bold:true } }
  ], {
    x:5.8, y:4.55, w:3.85, h:0.75, align:"center", valign:"middle", margin:0
  });
}

s3.addNotes("El scatter mostra Usage% (quant usa la pilota) vs TS% (eficiència). La jugadora ideal: dalt a la dreta.");

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 4 — EFICIÈNCIA: TS%, Off/Def Rtg, Clutch, Post-TM
// ══════════════════════════════════════════════════════════════════════════════
let s4 = pres.addSlide();
s4.background = { color: C_BG };

s4.addText("Eficiència i situacions especials", {
  x:0.5, y:0.22, w:9, h:0.5,
  fontSize:22, fontFace:"Cambria", bold:true, color:C_DARK, align:"left", margin:0
});

// Barres comparatives Off/Def Rtg
const rtg_data = data.ratings || {};
const rtg_labels = ["Off Rtg", "Def Rtg", "Net Rtg", "TS%", "Ritme"];
const rtg_vals_a = rtg_data.vals_a || [];
const rtg_vals_b = rtg_data.vals_b || [];

if (rtg_vals_a.length) {
  s4.addChart(pres.charts.BAR, [
    { name:data.nom_a, labels:rtg_labels.slice(0, rtg_vals_a.length), values:rtg_vals_a },
    { name:data.nom_b, labels:rtg_labels.slice(0, rtg_vals_b.length), values:rtg_vals_b }
  ], {
    x:0.5, y:0.88, w:5.8, h:3.0, barDir:"bar", barGrouping:"clustered",
    chartColors:[C_BLUE,"CCDDEE"],
    chartArea:{ fill:{ color:C_WHITE }, roundedCorners:true },
    catAxisLabelColor:C_GRAY, valAxisLabelColor:C_GRAY,
    valGridLine:{ color:C_BORDER, size:0.5 }, catGridLine:{ style:"none" },
    showValue:true, dataLabelColor:C_DARK, dataLabelFontSize:9,
    showLegend:true, legendPos:"b", legendFontSize:10, showTitle:false
  });
}

// Targetes clutch + post-TM
const specials = data.specials || [];
specials.slice(0,4).forEach((sp, i) => {
  const col = i < 2 ? 6.5 : 8.3;
  const row = i % 2 === 0 ? 0.88 : 2.28;
  s4.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x:col, y:row, w:1.6, h:1.25,
    fill:{ color:C_WHITE }, rectRadius:0.08, shadow:makeShadow()
  });
  s4.addText(sp.label, {
    x:col+0.1, y:row+0.1, w:1.4, h:0.28,
    fontSize:8, fontFace:"Calibri", color:C_GRAY, align:"center", margin:0
  });
  s4.addText(String(sp.valor), {
    x:col+0.1, y:row+0.38, w:1.4, h:0.5,
    fontSize:22, fontFace:"Cambria", bold:true, color:C_DARK, align:"center", margin:0
  });
  if (sp.sub) {
    s4.addText(sp.sub, {
      x:col+0.1, y:row+0.9, w:1.4, h:0.25,
      fontSize:8, fontFace:"Calibri", color:C_GRAY, align:"center", margin:0
    });
  }
});

// Zona de notes clutch / TM
s4.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x:0.5, y:4.0, w:9.0, h:1.35,
  fill:{ color:C_WHITE }, rectRadius:0.1, shadow:makeShadow()
});
s4.addText("Notes tàctiques", {
  x:0.7, y:4.1, w:3.0, h:0.28,
  fontSize:9, fontFace:"Calibri", bold:true, color:C_BLUE, align:"left", margin:0
});
s4.addShape(pres.shapes.LINE, {
  x:0.7, y:4.5, w:8.6, h:0, line:{ color:C_BORDER, width:0.5 }
});
s4.addShape(pres.shapes.LINE, {
  x:0.7, y:4.85, w:8.6, h:0, line:{ color:C_BORDER, width:0.5 }
});
s4.addShape(pres.shapes.LINE, {
  x:0.7, y:5.2, w:8.6, h:0, line:{ color:C_BORDER, width:0.5 }
});

s4.addNotes("Afegeix les teves observacions tàctiques a la zona de notes del bas.");

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 5 — ROTACIONS I QUINTETS
// ══════════════════════════════════════════════════════════════════════════════
let s5 = pres.addSlide();
s5.background = { color: C_BG };

s5.addText("Rotacions i quintets — " + data.nom_a, {
  x:0.5, y:0.22, w:9, h:0.5,
  fontSize:22, fontFace:"Cambria", bold:true, color:C_DARK, align:"left", margin:0
});

// Taula minuts per jugadora
const rots = data.rotacions || [];
if (rots.length) {
  const rot_header = [["Jugadora","Min","Q1","Q2","Q3","Q4","+/-","Arquetip"].map(c => ({
    text:c, options:{ bold:true, color:C_WHITE,
      fill:{ color:C_BLUE }, fontSize:9, fontFace:"Calibri", align:"center" }
  }))];
  const rot_rows = rots.map((r,i) => {
    const bg = i%2===0 ? C_WHITE : "F0F5FB";
    const pm_color = r.pm >= 0 ? C_GREEN : C_RED;
    return [
      { text:r.nom, options:{ fill:{ color:bg }, fontSize:9, fontFace:"Calibri", color:C_DARK, align:"left" } },
      { text:String(r.min??"-"), options:{ fill:{ color:bg }, fontSize:9, fontFace:"Calibri", color:C_DARK, align:"center" } },
      { text:String(r.q1??"-"), options:{ fill:{ color:bg }, fontSize:9, fontFace:"Calibri", color:C_GRAY, align:"center" } },
      { text:String(r.q2??"-"), options:{ fill:{ color:bg }, fontSize:9, fontFace:"Calibri", color:C_GRAY, align:"center" } },
      { text:String(r.q3??"-"), options:{ fill:{ color:bg }, fontSize:9, fontFace:"Calibri", color:C_GRAY, align:"center" } },
      { text:String(r.q4??"-"), options:{ fill:{ color:bg }, fontSize:9, fontFace:"Calibri", color:C_GRAY, align:"center" } },
      { text:(r.pm>=0?"+":"")+String(r.pm??"-"), options:{ fill:{ color:bg }, fontSize:9, fontFace:"Calibri", color:pm_color, align:"center", bold:true } },
      { text:String(r.arquetip??"—"), options:{ fill:{ color:bg }, fontSize:8, fontFace:"Calibri", color:C_GRAY, align:"center" } },
    ];
  });
  s5.addTable([...rot_header, ...rot_rows], {
    x:0.5, y:0.88, w:9.0, colW:[2.1,0.6,0.6,0.6,0.6,0.6,0.65,2.25],
    border:{ pt:0.5, color:C_BORDER }, rowH:0.34
  });
}

// Quintets +/-
const quintets = data.quintets || [];
if (quintets.length) {
  const tit_y = 0.88 + 0.34*(rots.length+1) + 0.2;
  if (tit_y < 4.8) {
    s5.addText("Quintets +/−", {
      x:0.5, y:tit_y, w:9, h:0.3,
      fontSize:11, fontFace:"Calibri", bold:true, color:C_DARK, margin:0
    });
    quintets.slice(0,3).forEach((q,i) => {
      const qy = tit_y + 0.35 + i*0.42;
      if (qy > 5.2) return;
      const pm_c = q.pm >= 0 ? C_GREEN : C_RED;
      s5.addShape(pres.shapes.ROUNDED_RECTANGLE, {
        x:0.5, y:qy, w:9.0, h:0.36,
        fill:{ color:i%2===0?C_WHITE:"F0F5FB" }, rectRadius:0.05
      });
      s5.addText(q.noms, {
        x:0.7, y:qy+0.03, w:7.5, h:0.3,
        fontSize:9, fontFace:"Calibri", color:C_DARK, align:"left", margin:0
      });
      s5.addText((q.pm>=0?"+":"")+String(q.pm), {
        x:8.5, y:qy+0.03, w:0.9, h:0.3,
        fontSize:11, fontFace:"Cambria", bold:true, color:pm_c, align:"center", margin:0
      });
    });
  }
}

s5.addNotes("Els minuts per quart s'extreuen dels intervals reals de joc (Entra/Surt al play-by-play).");

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 6 — NOTES TÀCTIQUES (editable)
// ══════════════════════════════════════════════════════════════════════════════
let s6 = pres.addSlide();
s6.background = { color: C_BG };

s6.addText("Notes tàctiques i conclusions", {
  x:0.5, y:0.22, w:9, h:0.5,
  fontSize:22, fontFace:"Cambria", bold:true, color:C_DARK, align:"left", margin:0
});

// Caixa verda — punts positius
s6.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x:0.5, y:0.9, w:4.35, h:4.35,
  fill:{ color:"F0FDF4" }, rectRadius:0.1, shadow:makeShadow()
});
s6.addText("Que hem fet bé", {
  x:0.7, y:1.0, w:3.9, h:0.35,
  fontSize:12, fontFace:"Calibri", bold:true, color:C_GREEN, align:"left", margin:0
});
[1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5].forEach(y => {
  s6.addShape(pres.shapes.LINE, { x:0.7, y:y, w:3.95, h:0, line:{ color:"CCEECC", width:0.5 } });
});

// Caixa vermella — punts de millora
s6.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x:5.15, y:0.9, w:4.35, h:4.35,
  fill:{ color:"FFF5F5" }, rectRadius:0.1, shadow:makeShadow()
});
s6.addText("A millorar / treballar", {
  x:5.35, y:1.0, w:3.9, h:0.35,
  fontSize:12, fontFace:"Calibri", bold:true, color:C_RED, align:"left", margin:0
});
[1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5].forEach(y => {
  s6.addShape(pres.shapes.LINE, { x:5.35, y:y, w:3.95, h:0, line:{ color:"FFCCCC", width:0.5 } });
});

s6.addNotes("Slide editable per a l'entrenadora. Escriu les observacions directament a les línies.");

// ══════════════════════════════════════════════════════════════════════════════
pres.writeFile({ fileName: data.output_path })
  .then(() => {
    const { execSync } = require("child_process");
    try {
      execSync(`python3 /mnt/skills/public/pptx/scripts/rezip.py "${data.output_path}"`, {stdio:"inherit"});
    } catch(e) {}
    console.log("OK:" + data.output_path);
  })
  .catch(e => { console.error("ERR:" + e.message); process.exit(1); });
