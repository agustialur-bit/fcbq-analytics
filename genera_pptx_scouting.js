const pptxgen = require("pptxgenjs");
const data = JSON.parse(process.argv[2]);

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
const C_RED_LT  = "FEF2F2";
const C_BLUE2   = "1e3a5f";

const makeShadow = () => ({ type:"outer", color:"000000", blur:8, offset:2, angle:45, opacity:0.08 });

let pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "Micki Analítica";
pres.title  = `Scouting ${data.nom_rival}`;

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 1 — PORTADA SCOUTING
// ══════════════════════════════════════════════════════════════════════════════
let s1 = pres.addSlide();
s1.background = { color: C_BLUE2 };

s1.addShape(pres.shapes.RECTANGLE, { x:0, y:0, w:10, h:0.08, fill:{ color:C_RED } });

s1.addText("INFORME DE SCOUTING", {
  x:0.6, y:0.7, w:8.8, h:0.6,
  fontSize:13, fontFace:"Calibri", bold:true, color:C_RED, charSpacing:6, align:"left"
});
s1.addText(data.nom_rival, {
  x:0.6, y:1.3, w:8.8, h:1.1,
  fontSize:38, fontFace:"Cambria", bold:true, color:C_WHITE, align:"left"
});
s1.addText(`${data.n_partits} partits analitzats · Temporada ${data.temporada || "actual"}`, {
  x:0.6, y:2.45, w:8.8, h:0.42,
  fontSize:13, fontFace:"Calibri", color:"8899BB", align:"left"
});

// Ràpid resum en 3 pills
const pills = data.pills || [];
pills.slice(0,3).forEach((p,i) => {
  s1.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x:0.6 + i*3.1, y:3.1, w:2.7, h:0.72,
    fill:{ color:C_BLUE, transparency:20 }, rectRadius:0.1
  });
  s1.addText(p.label, {
    x:0.6+i*3.1+0.1, y:3.12, w:2.5, h:0.28,
    fontSize:9, fontFace:"Calibri", color:"AABBCC", align:"center", margin:0
  });
  s1.addText(String(p.valor), {
    x:0.6+i*3.1+0.1, y:3.4, w:2.5, h:0.32,
    fontSize:16, fontFace:"Cambria", bold:true, color:C_WHITE, align:"center", margin:0
  });
});

s1.addText(`Proper enfrontament: ${data.data_propera || "pendent"}  ·  Micki Analítica`, {
  x:0.6, y:5.15, w:8.8, h:0.3,
  fontSize:10, fontFace:"Calibri", color:"445566", align:"left"
});

s1.addNotes("Portada del scouting. Pots editar el nom del rival i la data de l'enfrontament.");

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 2 — PERFIL OFENSIU: Zones de tir + estil
// ══════════════════════════════════════════════════════════════════════════════
let s2 = pres.addSlide();
s2.background = { color: C_BG };

s2.addText("Perfil ofensiu — " + data.nom_rival, {
  x:0.5, y:0.22, w:9, h:0.5,
  fontSize:22, fontFace:"Cambria", bold:true, color:C_DARK, align:"left", margin:0
});

// Zones de tir (6 zones representades com a targetes)
const zones = data.zones || [];
const zone_x = [0.5, 2.0, 3.5, 5.0, 6.5, 8.0];
zones.slice(0,6).forEach((z,i) => {
  const hotness = parseFloat(z.tc_pct) || 0;
  const bg = hotness >= 50 ? "FEF2F2" : (hotness >= 38 ? "FFFBEB" : C_BLUE_LT);
  const tc = hotness >= 50 ? C_RED : (hotness >= 38 ? C_AMBER : C_BLUE);
  s2.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x:zone_x[i], y:0.9, w:1.3, h:1.4,
    fill:{ color:bg }, rectRadius:0.08, shadow:makeShadow()
  });
  s2.addText(z.nom, {
    x:zone_x[i]+0.05, y:0.96, w:1.2, h:0.28,
    fontSize:8, fontFace:"Calibri", color:C_GRAY, align:"center", margin:0
  });
  s2.addText(z.tc_pct+"%", {
    x:zone_x[i]+0.05, y:1.24, w:1.2, h:0.5,
    fontSize:22, fontFace:"Cambria", bold:true, color:tc, align:"center", margin:0
  });
  s2.addText(z.tirs+" tirs", {
    x:zone_x[i]+0.05, y:1.75, w:1.2, h:0.28,
    fontSize:8, fontFace:"Calibri", color:C_GRAY, align:"center", margin:0
  });
});

// Llegenda calor
s2.addText("Roig ≥50%TC  ·  Groc ≥38%TC  ·  Blau <38%TC", {
  x:0.5, y:2.42, w:9, h:0.25,
  fontSize:8, fontFace:"Calibri", color:C_GRAY, align:"left", margin:0
});

// Gràfic distribució de tirs (barres)
const dist_labels = data.dist_labels || ["2pt", "3pt", "TL"];
const dist_vals   = data.dist_vals   || [];
if (dist_vals.length) {
  s2.addChart(pres.charts.BAR, [{
    name: data.nom_rival, labels: dist_labels, values: dist_vals
  }], {
    x:0.5, y:2.75, w:4.5, h:2.45, barDir:"col",
    chartColors:[C_RED,"AA2200","DD4422"],
    chartArea:{ fill:{ color:C_WHITE }, roundedCorners:true },
    catAxisLabelColor:C_GRAY, valAxisLabelColor:C_GRAY,
    valGridLine:{ color:C_BORDER, size:0.5 }, catGridLine:{ style:"none" },
    showValue:true, dataLabelColor:C_DARK, dataLabelFontSize:9,
    showLegend:false, showTitle:false
  });
  s2.addText("Distribució de tirs (%)", {
    x:0.5, y:5.15, w:4.5, h:0.25,
    fontSize:8, fontFace:"Calibri", color:C_GRAY, align:"center", margin:0
  });
}

// Barres d'estil ofensiu
const estil = data.estil || [];
estil.slice(0,5).forEach((e, i) => {
  const ey = 2.8 + i*0.48;
  s2.addText(e.label, {
    x:5.3, y:ey, w:2.5, h:0.28,
    fontSize:9, fontFace:"Calibri", color:C_DARK, align:"left", margin:0
  });
  s2.addText(String(e.valor), {
    x:8.8, y:ey, w:0.8, h:0.28,
    fontSize:9, fontFace:"Calibri", bold:true, color:C_DARK, align:"right", margin:0
  });
  // Barra de progrés visual
  const bar_w = Math.min((parseFloat(e.pct)||0)/100 * 3.2, 3.2);
  if (bar_w > 0) {
    s2.addShape(pres.shapes.RECTANGLE, {
      x:5.3, y:ey+0.28, w:3.2, h:0.1,
      fill:{ color:C_BORDER }
    });
    s2.addShape(pres.shapes.RECTANGLE, {
      x:5.3, y:ey+0.28, w:bar_w, h:0.1,
      fill:{ color:C_RED }
    });
  }
});

s2.addNotes("Les zones de tir mostren el % de conversió per zona. Roig = zona calenta del rival a neutralitzar.");

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 3 — JUGADORES CLAU RIVAL
// ══════════════════════════════════════════════════════════════════════════════
let s3 = pres.addSlide();
s3.background = { color: C_BG };

s3.addText("Jugadores clau — " + data.nom_rival, {
  x:0.5, y:0.22, w:9, h:0.5,
  fontSize:22, fontFace:"Cambria", bold:true, color:C_DARK, align:"left", margin:0
});

const jug_rivals = data.jugadores || [];

// Cards per jugadora (màx 5)
jug_rivals.slice(0,5).forEach((j, i) => {
  const cy = 0.88 + i * 0.95;
  s3.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x:0.5, y:cy, w:9.0, h:0.85,
    fill:{ color:C_WHITE }, rectRadius:0.08, shadow:makeShadow()
  });
  // Nom i arquetip
  s3.addText(j.nom, {
    x:0.7, y:cy+0.06, w:3.2, h:0.35,
    fontSize:13, fontFace:"Cambria", bold:true, color:C_DARK, align:"left", margin:0
  });
  s3.addText(j.arquetip||"", {
    x:0.7, y:cy+0.44, w:3.2, h:0.28,
    fontSize:9, fontFace:"Calibri", color:C_GRAY, align:"left", margin:0
  });
  // Stats: Pts/P, Usage, TS%, Net Rtg
  const stats = [
    { l:"Pts/P", v:j.pts_pp },
    { l:"Usage%", v:(j.usage||"—")+"%"},
    { l:"TS%", v:(j.ts||"—")+"%"},
    { l:"Net Rtg", v:j.net_rtg }
  ];
  stats.forEach((st, si) => {
    const sx = 4.1 + si * 1.3;
    s3.addText(String(st.v||"—"), {
      x:sx, y:cy+0.05, w:1.1, h:0.42,
      fontSize:18, fontFace:"Cambria", bold:true, color:C_DARK, align:"center", margin:0
    });
    s3.addText(st.l, {
      x:sx, y:cy+0.48, w:1.1, h:0.25,
      fontSize:8, fontFace:"Calibri", color:C_GRAY, align:"center", margin:0
    });
  });
  // Nota
  if (j.nota) {
    s3.addText("⚠ "+j.nota, {
      x:9.1, y:cy+0.06, w:0.4, h:0.7,
      fontSize:7, fontFace:"Calibri", color:C_AMBER, align:"center", valign:"middle", margin:0
    });
  }
});

// Zona de notes al peu
if (jug_rivals.length < 5) {
  const notes_y = 0.88 + jug_rivals.length * 0.95 + 0.1;
  if (notes_y < 4.8) {
    s3.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x:0.5, y:notes_y, w:9.0, h:5.35-notes_y,
      fill:{ color:C_WHITE }, rectRadius:0.08, shadow:makeShadow()
    });
    s3.addText("Notes sobre jugadores / observació de vídeo", {
      x:0.7, y:notes_y+0.08, w:8.6, h:0.28,
      fontSize:9, fontFace:"Calibri", bold:true, color:C_BLUE, margin:0
    });
    [notes_y+0.5, notes_y+0.85, notes_y+1.2].forEach(ly => {
      if (ly < 5.25) s3.addShape(pres.shapes.LINE, {
        x:0.7, y:ly, w:8.6, h:0, line:{ color:C_BORDER, width:0.5 }
      });
    });
  }
}

s3.addNotes("Pots afegir observacions de vídeo a la zona de notes. Les stats són mitjanes de temporada.");

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 4 — COMPARATIVA MANRESA vs RIVAL
// ══════════════════════════════════════════════════════════════════════════════
let s4 = pres.addSlide();
s4.background = { color: C_BG };

s4.addText("Manresa vs " + data.nom_rival + " — comparativa temporada", {
  x:0.5, y:0.22, w:9, h:0.5,
  fontSize:22, fontFace:"Cambria", bold:true, color:C_DARK, align:"left", margin:0
});

// Capçalera equips
s4.addText(data.nom_manresa || "Manresa", {
  x:0.5, y:0.85, w:4.35, h:0.35,
  fontSize:13, fontFace:"Calibri", bold:true, color:C_BLUE, align:"center", margin:0
});
s4.addText(data.nom_rival, {
  x:5.15, y:0.85, w:4.35, h:0.35,
  fontSize:13, fontFace:"Calibri", bold:true, color:C_RED, align:"center", margin:0
});

// Comparatives fila a fila
const comps = data.comparativa || [];
comps.forEach((c, i) => {
  const cy = 1.3 + i * 0.62;
  const bg = i%2===0 ? C_WHITE : "F8FAFC";
  s4.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x:0.5, y:cy, w:9.0, h:0.55,
    fill:{ color:bg }, rectRadius:0.06
  });
  // Label centre
  s4.addText(c.label, {
    x:4.0, y:cy+0.12, w:2.0, h:0.3,
    fontSize:9, fontFace:"Calibri", color:C_GRAY, align:"center", margin:0
  });
  // Valor Manresa
  const mans_win = parseFloat(c.manresa) >= parseFloat(c.rival);
  s4.addText(String(c.manresa), {
    x:0.5, y:cy+0.08, w:3.4, h:0.38,
    fontSize:20, fontFace:"Cambria", bold:true,
    color: mans_win ? C_BLUE : C_GRAY, align:"center", margin:0
  });
  // Valor rival
  s4.addText(String(c.rival), {
    x:6.1, y:cy+0.08, w:3.4, h:0.38,
    fontSize:20, fontFace:"Cambria", bold:true,
    color: mans_win ? C_GRAY : C_RED, align:"center", margin:0
  });
  // Barra visual comparativa
  const m_val = parseFloat(c.manresa)||0;
  const r_val = parseFloat(c.rival)||0;
  const total = m_val + r_val || 1;
  const m_w = (m_val/total)*3.3;
  const r_w = (r_val/total)*3.3;
  s4.addShape(pres.shapes.RECTANGLE, { x:0.6, y:cy+0.47, w:m_w, h:0.07, fill:{ color:C_BLUE } });
  s4.addShape(pres.shapes.RECTANGLE, { x:6.1, y:cy+0.47, w:r_w, h:0.07, fill:{ color:C_RED } });
});

s4.addNotes("Les barres de color indiquen quin equip domina cada mètrica. Blau = Manresa, vermell = rival.");

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 5 — ROTACIONS I QUINTETS RIVAL
// ══════════════════════════════════════════════════════════════════════════════
let s5 = pres.addSlide();
s5.background = { color: C_BG };

s5.addText("Rotacions i quintets — " + data.nom_rival, {
  x:0.5, y:0.22, w:9, h:0.5,
  fontSize:22, fontFace:"Cambria", bold:true, color:C_DARK, align:"left", margin:0
});

// Taula rotacions rival
const rots_rival = data.rotacions || [];
if (rots_rival.length) {
  const hdr = [["Jugadora","Min/P","Usage%","TS%","Pts/P","Arquetip"].map(c => ({
    text:c, options:{ bold:true, color:C_WHITE,
      fill:{ color:C_RED }, fontSize:9, fontFace:"Calibri", align:"center" }
  }))];
  const rrows = rots_rival.map((r,i) => {
    const bg = i%2===0 ? C_WHITE : "FFF5F5";
    return [r.nom, r.min_pp||"—", (r.usage||"—")+"%", (r.ts||"—")+"%", r.pts_pp||"—", r.arquetip||"—"].map((v,vi) => ({
      text:String(v),
      options:{ fill:{ color:bg }, fontSize:9, fontFace:"Calibri",
        color:C_DARK, align:vi===0?"left":"center" }
    }));
  });
  s5.addTable([...hdr, ...rrows], {
    x:0.5, y:0.88, w:9.0, colW:[2.5,0.85,0.85,0.85,0.85,2.1],
    border:{ pt:0.5, color:C_BORDER }, rowH:0.34
  });
}

// Quintets
const quintets_r = data.quintets || [];
if (quintets_r.length) {
  const q_y = 0.88 + 0.34*(rots_rival.length+1) + 0.25;
  if (q_y < 4.9) {
    s5.addText("Quintets més habituals", {
      x:0.5, y:q_y, w:9, h:0.3,
      fontSize:11, fontFace:"Calibri", bold:true, color:C_DARK, margin:0
    });
    quintets_r.slice(0,3).forEach((q,i) => {
      const qy2 = q_y + 0.38 + i*0.4;
      if (qy2 > 5.25) return;
      s5.addShape(pres.shapes.ROUNDED_RECTANGLE, {
        x:0.5, y:qy2, w:9.0, h:0.33,
        fill:{ color:i%2===0?C_WHITE:"FFF5F5" }, rectRadius:0.05
      });
      s5.addText(q.noms, {
        x:0.7, y:qy2+0.03, w:7.2, h:0.27,
        fontSize:9, fontFace:"Calibri", color:C_DARK, align:"left", margin:0
      });
      s5.addText("Min: "+String(q.min||"—"), {
        x:7.9, y:qy2+0.03, w:1.4, h:0.27,
        fontSize:9, fontFace:"Calibri", color:C_GRAY, align:"right", margin:0
      });
    });
  }
}

s5.addNotes("Les rotacions mostren els minuts per partit (Min/P) i les mètriques d'eficiència de cada jugadora rival.");

// ══════════════════════════════════════════════════════════════════════════════
// SLIDE 6 — PLA DE PARTIT (editable)
// ══════════════════════════════════════════════════════════════════════════════
let s6 = pres.addSlide();
s6.background = { color: C_BG };

s6.addText("Pla de partit — " + (data.nom_manresa||"Manresa") + " vs " + data.nom_rival, {
  x:0.5, y:0.22, w:9, h:0.5,
  fontSize:20, fontFace:"Cambria", bold:true, color:C_DARK, align:"left", margin:0
});

// 2 columnes: explotar / neutralitzar
s6.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x:0.5, y:0.88, w:4.35, h:4.35,
  fill:{ color:"F0FDF4" }, rectRadius:0.1, shadow:makeShadow()
});
s6.addText("Que podem explotar", {
  x:0.7, y:0.98, w:3.9, h:0.35,
  fontSize:12, fontFace:"Calibri", bold:true, color:C_GREEN, align:"left", margin:0
});
[1.48, 1.95, 2.42, 2.89, 3.36, 3.83, 4.3].forEach(y => {
  s6.addShape(pres.shapes.LINE, { x:0.7, y:y, w:3.95, h:0, line:{ color:"CCEECC", width:0.5 } });
});

s6.addShape(pres.shapes.ROUNDED_RECTANGLE, {
  x:5.15, y:0.88, w:4.35, h:4.35,
  fill:{ color:C_RED_LT }, rectRadius:0.1, shadow:makeShadow()
});
s6.addText("Que hem de neutralitzar", {
  x:5.35, y:0.98, w:3.9, h:0.35,
  fontSize:12, fontFace:"Calibri", bold:true, color:C_RED, align:"left", margin:0
});
[1.48, 1.95, 2.42, 2.89, 3.36, 3.83, 4.3].forEach(y => {
  s6.addShape(pres.shapes.LINE, { x:5.35, y:y, w:3.95, h:0, line:{ color:"FFCCCC", width:0.5 } });
});

s6.addNotes("Slide editable per a l'entrenadora. Escriu les claus tàctiques per al proper enfrontament.");

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
