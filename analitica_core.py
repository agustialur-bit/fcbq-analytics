# -*- coding: utf-8 -*-
"""Motor compartit d'Analítica de bàsquet: esquema/persistència SQLite, càlculs
(possessions, on/off, usage rate, arquetips, win shares, zones de tir...) i estil
visual comuns. Aquest mòdul no sap res de d'on vénen les dades (FCBQ, feb.es...);
cada app fa el seu propi fetch+normalització i després crida aquestes funcions.

Totes les funcions que toquen la base de dades usen la variable de mòdul DB_PATH,
que cada app ha d'establir amb set_db_path(...) abans de cridar init_db()/migrate_db()
i qualsevol altra funció de persistència. Això permet que dues apps diferents (amb
BDs diferents) comparteixin exactament el mateix codi de càlcul sense barrejar dades.
"""
import sqlite3
import itertools
import pandas as pd
from datetime import datetime

# ══════════════════════════════════════════════════
# CONFIGURACIÓ DE BASE DE DADES (per app)
# ══════════════════════════════════════════════════
DB_PATH = None

def set_db_path(path):
    global DB_PATH
    DB_PATH = path


# ══════════════════════════════════════════════════
# ESTIL COMPARTIT
# ══════════════════════════════════════════════════
COLOR_A, COLOR_B = "#185FA5", "#993C1D"

MICKI_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

/* ── Paleta central ── Tots els colors de l'app es defineixen aquí un sol cop.
   Per canviar la identitat visual, només cal tocar aquestes variables. */
:root{
    --c-bg:#EBF4FC;          /* fons general de l'app */
    --c-bg-soft:#D6E8F7;     /* fons sidebar, capçaleres de taula, hover */
    --c-border:#B5D4F4;      /* vores i separadors suaus */
    --c-text:#1a2744;        /* text principal sobre fons clar */
    --c-white:#ffffff;
    --c-accent:#185FA5;      /* blau principal (accions, accent) */
    --c-accent-dark:#0C447C; /* blau fosc (hover/seleccionat) */
    --c-accent-mid:#378ADD;  /* blau mitjà (hovers, placeholders, captions) */
    --c-btn-bg:#85B7EB;      /* fons botons per defecte */
    --c-btn-text:#042C53;    /* text botons per defecte */
    --c-dark-bg:#232840;     /* fons inputs (tema fosc per defecte, fora del sidebar) */
    --c-dark-text:#e8eaf0;   /* text sobre --c-dark-bg */
    --c-dark-border:#2d3450;
    --c-panel-dark:#13161e;  /* fons expander (base, abans de l'override clar) */
    --c-border-dark:#1f2330; /* vores sobre panells foscos */
    --c-input-text:#000000;  /* text forçat als inputs del sidebar */
}

/* ── Base ── */
html,body,[class*="css"]{font-family:'Inter',sans-serif;color:var(--c-dark-text)!important;}
.stApp{background:var(--c-bg)!important;color:var(--c-text)!important;}
.main .block-container{padding-top:1.5rem!important;}
p, span, div, label, h1, h2, h3, h4{color:var(--c-text);}

/* ── Sidebar ── */
[data-testid="stSidebar"]{background:var(--c-bg-soft)!important;border-right:1px solid var(--c-border)!important;}

/* ── Pestanyes grans estil NBA ── */
.stTabs [data-baseweb="tab-list"]{
    background:var(--c-bg-soft)!important;
    border-radius:12px!important;
    padding:6px!important;
    gap:4px!important;
    border:1px solid var(--c-border)!important;
}
.stTabs [data-baseweb="tab"]{
    border-radius:8px!important;
    font-size:14px!important;
    font-weight:600!important;
    color:var(--c-accent)!important;
    padding:10px 18px!important;
    letter-spacing:0.02em!important;
    transition:all 0.2s!important;
}
.stTabs [data-baseweb="tab"]:hover{
    background:var(--c-border)!important;
    color:var(--c-accent-dark)!important;
}
.stTabs [aria-selected="true"]{
    background:var(--c-accent)!important;
    color:var(--c-white)!important;
    box-shadow:0 2px 8px rgba(24,95,165,0.4)!important;
}

/* ── Botons ── */
.stButton button{
    background:var(--c-btn-bg)!important;
    color:var(--c-btn-text)!important;
    border:none!important;
    border-radius:8px!important;
    font-weight:700!important;
    font-size:13px!important;
    padding:8px 20px!important;
    transition:all 0.2s!important;
}
.stButton button:hover{
    background:var(--c-accent-mid)!important;
    color:var(--c-white)!important;
}
/* Download button */
a[data-testid="stDownloadButton"] button,
div[data-testid="stDownloadButton"] button{
    background:var(--c-btn-bg)!important;
    color:var(--c-btn-text)!important;
    font-weight:700!important;
    border:none!important;
    border-radius:8px!important;
}
a[data-testid="stDownloadButton"] button:hover,
div[data-testid="stDownloadButton"] button:hover{
    background:var(--c-accent-mid)!important;
    color:var(--c-white)!important;
}

/* ── DataFrames ── */
div[data-testid="stDataFrame"]{
    border-radius:10px!important;
    overflow:hidden!important;
    border:1px solid var(--c-border-dark)!important;
}
div[data-testid="stDataFrame"] th{
    background:var(--c-bg-soft)!important;
    color:var(--c-accent)!important;
}
div[data-testid="stDataFrame"] td{
    background:var(--c-bg)!important;
    color:var(--c-text)!important;
}

/* ── Inputs i selects ── */
.stSelectbox>div>div,
.stMultiSelect>div>div,
.stTextInput>div>div,
.stTextInput input,
.stSelectbox input,
input, textarea, select{
    border-radius:8px!important;
    background:var(--c-dark-bg)!important;
    border-color:var(--c-dark-border)!important;
    color:var(--c-dark-text)!important;
}
/* Text dins dels camps de selecció */
[data-baseweb="select"] [data-baseweb="tag"],
[data-baseweb="select"] input,
[data-baseweb="select"] div,
[data-baseweb="input"] input{
    color:var(--c-dark-text)!important;
    background:var(--c-bg-soft)!important;
}
/* Placeholder text */
input::placeholder, textarea::placeholder{color:var(--c-accent-mid)!important;}
/* Dropdown options */
[data-baseweb="popover"] li,
[data-baseweb="menu"] li{
    background:var(--c-dark-bg)!important;
    color:var(--c-dark-text)!important;
}
[data-baseweb="popover"] li:hover,
[data-baseweb="menu"] li:hover{
    background:var(--c-border)!important;
}

/* ── Expanders ── */
.stExpander{
    border:1px solid var(--c-border-dark)!important;
    border-radius:10px!important;
    background:var(--c-panel-dark)!important;
}

/* ── Mètriques ── */
div[data-testid="stMetric"]{
    background:var(--c-white)!important;
    border-radius:10px!important;
    padding:12px!important;
    border:1px solid var(--c-border-dark)!important;
}

/* ── Info/Warning boxes ── */
div[data-testid="stAlert"]{
    border-radius:8px!important;
    border:1px solid var(--c-border-dark)!important;
}

/* ── Plotly charts fons transparent ── */
.js-plotly-plot .plotly .modebar{background:transparent!important;}

/* ── Captions i text secundari ── */
.stCaption, small{color:var(--c-accent-mid)!important;}

/* ── Separadors ── */
hr{border-color:var(--c-border)!important;}

/* ── Fix sidebar i expanders ── */
[data-testid="stSidebar"],
[data-testid="stSidebar"] *,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] div{
    color:var(--c-text)!important;
}
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] textarea,
[data-testid="stSidebar"] [data-baseweb="input"] div,
[data-testid="stSidebar"] [data-baseweb="input"] input,
[data-testid="stSidebar"] [data-baseweb="base-input"] div,
[data-testid="stSidebar"] [data-baseweb="base-input"] input,
[data-testid="stSidebar"] div[data-testid="stTextInput"] input,
[data-testid="stSidebar"] div[class*="Input"],
[data-testid="stSidebar"] div[class*="input"]{
    background:var(--c-white)!important;
    color:var(--c-input-text)!important;
    border:1px solid var(--c-border)!important;
}
/* Extra força per text visible dins inputs del sidebar (cobreix versions de Streamlit
   on data-baseweb="base-input" en lloc de "input", i evita que el text quedi del mateix
   color que el fons) */
[data-testid="stSidebar"] input[type="text"],
[data-testid="stSidebar"] input[type="url"],
[data-testid="stSidebar"] div[data-testid="stTextInput"] input,
[data-testid="stSidebar"] [data-baseweb="base-input"] input,
[data-testid="stSidebar"] input:not([type="checkbox"]):not([type="radio"]){
    background:var(--c-white)!important;
    color:var(--c-input-text)!important;
    -webkit-text-fill-color:var(--c-input-text)!important;
    caret-color:var(--c-input-text)!important;
}

/* Expanders — tot el contingut interior visible */
div[data-testid="stExpander"]{
    background:var(--c-white)!important;
    border:1px solid var(--c-border)!important;
    border-radius:10px!important;
}
div[data-testid="stExpander"] *,
div[data-testid="stExpander"] p,
div[data-testid="stExpander"] span,
div[data-testid="stExpander"] div,
div[data-testid="stExpander"] td,
div[data-testid="stExpander"] th,
div[data-testid="stExpander"] label{
    color:var(--c-text)!important;
    background:var(--c-white)!important;
}
div[data-testid="stExpander"] summary{
    color:var(--c-text)!important;
    background:var(--c-bg)!important;
}
/* Força fons blanc pur al contingut de l'expander */
div[data-testid="stExpander"] > div:last-child{
    background:var(--c-white)!important;
}
div[data-testid="stExpander"] summary:hover{
    background:var(--c-bg-soft)!important;
}
/* DataFrames dins expanders i globals */
div[data-testid="stExpander"] div[data-testid="stDataFrame"] *,
div[data-testid="stDataFrame"] *,
div[data-testid="stDataFrame"] td,
div[data-testid="stDataFrame"] th,
div[data-testid="stDataFrame"] span,
div[data-testid="stDataFrame"] div,
.dvn-scroller *,
.dvn-cell *,
[role="gridcell"] *,
[role="columnheader"] *{
    color:var(--c-text)!important;
}
/* Headers del dataframe */
div[data-testid="stDataFrame"] th,
div[data-testid="stDataFrame"] [role="columnheader"]{
    background:var(--c-bg-soft)!important;
    color:var(--c-accent-dark)!important;
}
/* Files alternatives */
div[data-testid="stDataFrame"] [role="gridcell"]{
    background:var(--c-white)!important;
    color:var(--c-text)!important;
}

/* ── Fix desplegables BaseWeb (selectbox, multiselect) ── */
/* Fons i text del camp tancat */
div[data-baseweb="select"] > div:first-child{
    background:var(--c-white)!important;
    border-color:var(--c-border)!important;
}
/* Text valor seleccionat i placeholder */
div[data-baseweb="select"] span,
div[data-baseweb="select"] div,
div[data-baseweb="select"] p,
div[data-baseweb="select"] input{
    color:var(--c-text)!important;
    background:transparent!important;
}
/* Llista desplegada - fons de cada opció */
ul[data-baseweb="menu"],
ul[data-baseweb="menu"] li,
ul[data-baseweb="menu"] li *,
div[data-baseweb="popover"],
div[data-baseweb="popover"] *,
li[role="option"],
li[role="option"] *{
    background:var(--c-white)!important;
    color:var(--c-text)!important;
}
/* Opció hover */
li[role="option"]:hover,
li[role="option"]:hover *{
    background:var(--c-bg-soft)!important;
    color:var(--c-accent-dark)!important;
}
/* Opció seleccionada */
li[aria-selected="true"],
li[aria-selected="true"] *{
    background:var(--c-border)!important;
    color:var(--c-accent-dark)!important;
    font-weight:600!important;
}
/* Tags del multiselect */
span[data-baseweb="tag"],
span[data-baseweb="tag"] *{
    background:var(--c-accent)!important;
    color:var(--c-white)!important;
}
</style>
"""

# Paleta Python (mateixos valors que les variables CSS de dalt, per als
# helpers que generen HTML/gràfics des de Python)
C_BG        = "#EBF4FC"
C_BG_SOFT   = "#D6E8F7"
C_BORDER    = "#B5D4F4"
C_TEXT      = "#1a2744"
C_TEXT_MUTED= "#6b7280"
C_LABEL     = "#9ca3af"
C_CARD_BORDER = "#e2e4e8"
C_WHITE     = "#ffffff"
C_ACCENT    = "#185FA5"
C_ACCENT_DARK = "#0C447C"
C_ACCENT_MID  = "#378ADD"
C_CHART_TEXT  = "#374151"
C_CHART_GRID  = "#f3f4f6"
C_SUCCESS   = "#16a34a"
C_WARNING   = "#d97706"
C_ERROR     = "#dc2626"

def card(label, value, sub="", color=C_ACCENT):
    return f"""<div style="background:{C_WHITE};border:0.5px solid {C_CARD_BORDER};border-radius:10px;padding:14px 16px;text-align:center;margin-bottom:8px">
    <div style="font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:{C_LABEL};margin-bottom:4px">{label}</div>
    <div style="font-size:28px;font-weight:600;color:{color};line-height:1.1">{value}</div>
    <div style="font-size:11px;color:{C_LABEL};margin-top:3px">{sub}</div></div>"""

def sec(s):
    return f'<div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:{C_TEXT_MUTED};border-left:3px solid {C_ACCENT};padding-left:8px;margin:24px 0 10px;border-radius:0">{s}</div>'

def badge(text, color, bg):
    return f'<span style="background:{bg};color:{color};font-size:10px;font-weight:600;padding:2px 7px;border-radius:20px;letter-spacing:.04em">{text}</span>'

def chart_style(fig, h=280, title=""):
    if title:
        fig.update_layout(title=dict(text=title, font=dict(color=C_CHART_TEXT, size=13, family="Inter"), x=0))
    fig.update_layout(
        paper_bgcolor=C_WHITE, plot_bgcolor=C_WHITE,
        font=dict(color=C_CHART_TEXT, family="Inter", size=12),
        legend=dict(bgcolor=C_WHITE, bordercolor=C_CARD_BORDER, borderwidth=1, title="",
                    orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(showgrid=False, color=C_LABEL, linecolor=C_CARD_BORDER),
        yaxis=dict(showgrid=True, gridcolor=C_CHART_GRID, color=C_LABEL, linecolor=C_CARD_BORDER),
        margin=dict(l=0, r=0, t=40 if title else 10, b=0), height=h)
    return fig

def eff_color(p):
    if p >= 55: return C_SUCCESS
    if p >= 35: return C_WARNING
    return C_ERROR

def shot_map_svg(zones, width=300, height=280):
    pts = [
        {"val":1, "label":"1pt",  "cy":248, "made":zones[0][0], "miss":zones[0][1]},
        {"val":2, "label":"2pts", "cy":175, "made":zones[1][0], "miss":zones[1][1]},
        {"val":3, "label":"3pts", "cy":76,  "made":zones[2][0], "miss":zones[2][1]},
    ]
    max_t = max((z["made"]+z["miss"] for z in pts), default=1) or 1
    cx = width // 2
    L = [f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" style="width:100%;display:block">']
    L.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="#f9fafb" rx="8"/>')
    L.append(f'<rect x="20" y="15" width="{width-40}" height="{height-15}" fill="none" stroke="#e5e7eb" stroke-width="1"/>')
    L.append(f'<rect x="{cx-52}" y="170" width="104" height="90" fill="none" stroke="#d1d5db" stroke-width="1"/>')
    L.append(f'<path d="M 28 170 A {cx-28} {cx-28} 0 0 1 {width-28} 170" fill="none" stroke="#d1d5db" stroke-width="1" stroke-dasharray="5,3"/>')
    L.append(f'<line x1="28" y1="115" x2="28" y2="{height}" stroke="#d1d5db" stroke-width="1" stroke-dasharray="5,3"/>')
    L.append(f'<line x1="{width-28}" y1="115" x2="{width-28}" y2="{height}" stroke="#d1d5db" stroke-width="1" stroke-dasharray="5,3"/>')
    L.append(f'<path d="M {cx-28} 260 A 28 28 0 0 1 {cx+28} 260" fill="none" stroke="#d1d5db" stroke-width="1"/>')
    L.append(f'<circle cx="{cx}" cy="242" r="5" fill="none" stroke="#9ca3af" stroke-width="1.5"/>')
    L.append(f'<line x1="20" y1="125" x2="{width-20}" y2="125" stroke="#eff0f1" stroke-width="0.5" stroke-dasharray="4,4"/>')
    L.append(f'<line x1="20" y1="215" x2="{width-20}" y2="215" stroke="#eff0f1" stroke-width="0.5" stroke-dasharray="4,4"/>')
    for z in pts:
        t = z["made"] + z["miss"]
        if t == 0:
            L.append(f'<circle cx="{cx}" cy="{z["cy"]}" r="20" fill="#f3f4f6"/>')
            L.append(f'<text x="{cx}" y="{z["cy"]}" text-anchor="middle" dominant-baseline="middle" font-size="9" fill="#9ca3af">—</text>')
            continue
        p = round(z["made"]/t*100)
        col = eff_color(p)
        r_out = 18 + round((t/max_t)*30)
        r_in  = round(r_out * 0.55)
        L.append(f'<circle cx="{cx}" cy="{z["cy"]}" r="{r_out}" fill="{col}" fill-opacity="0.12" stroke="{col}" stroke-width="1.5" stroke-opacity="0.35"/>')
        L.append(f'<circle cx="{cx}" cy="{z["cy"]}" r="{r_in}" fill="{col}" fill-opacity="0.88"/>')
        L.append(f'<text x="{cx}" y="{z["cy"]}" text-anchor="middle" dominant-baseline="middle" font-size="11" font-weight="600" fill="white">{p}%</text>')
        L.append(f'<text x="{cx}" y="{z["cy"]+r_out+11}" text-anchor="middle" font-size="9" fill="{col}" font-weight="500">{z["made"]}/{t}</text>')
        L.append(f'<text x="{cx+r_out+7}" y="{z["cy"]}" dominant-baseline="middle" font-size="9" fill="#9ca3af">{z["label"]}</text>')
    L.append('</svg>')
    return "\n".join(L)


# ══════════════════════════════════════════════════
# BASE DE DADES
# ══════════════════════════════════════════════════
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS partits (
        match_id TEXT PRIMARY KEY, data_consulta TEXT,
        nom_a TEXT, nom_b TEXT, id_equip_a TEXT, id_equip_b TEXT,
        score_a INTEGER, score_b INTEGER, total_jugades INTEGER
    );
    CREATE TABLE IF NOT EXISTS jugades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT,
        num INTEGER, quart INTEGER, min_num REAL, temps TEXT,
        id_equip TEXT, dorsal TEXT, jugador TEXT, accio TEXT,
        marcador TEXT, punts INTEGER, team_action INTEGER
    );
    CREATE TABLE IF NOT EXISTS stats_jugador (
        id INTEGER PRIMARY KEY AUTOINCREMENT, match_id TEXT, data_consulta TEXT,
        jugador TEXT, equip_nom TEXT, punts INTEGER,
        cistelles_2 INTEGER, cistelles_3 INTEGER, tirs_lliures INTEGER,
        faltes INTEGER, accions INTEGER, impacte INTEGER, pts_per_min REAL,
        minuts REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS shots_zones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id TEXT, data_consulta TEXT, equip_nom TEXT, jugador TEXT,
        val1_made INTEGER, val1_miss INTEGER,
        val2_made INTEGER, val2_miss INTEGER,
        val3_made INTEGER, val3_miss INTEGER
    );
    CREATE TABLE IF NOT EXISTS timeouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id TEXT, data_consulta TEXT,
        equip_nom TEXT, quart INTEGER,
        min_timeout REAL, min_cistella REAL,
        segons_resposta REAL,
        jugadora TEXT, accio TEXT,
        va_anotar INTEGER, dins_24s INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS equips (
        id_equip TEXT PRIMARY KEY, nom TEXT
    );
    CREATE TABLE IF NOT EXISTS tirs_fcbq (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id TEXT, data_consulta TEXT,
        equip_nom TEXT, x REAL, y REAL, fet INTEGER
    );
    """)
    con.commit(); con.close()

def migrate_db():
    """Migració automàtica: afegir columnes noves si no existeixen a BDs antigues."""
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("ALTER TABLE stats_jugador ADD COLUMN minuts REAL DEFAULT 0")
        con.commit()
    except Exception:
        pass
    try:
        con.execute("ALTER TABLE stats_jugador ADD COLUMN usage_rate REAL DEFAULT 0")
        con.commit()
    except Exception:
        pass
    try:
        con.execute("ALTER TABLE timeouts ADD COLUMN dins_24s INTEGER DEFAULT 0")
        con.commit()
    except Exception:
        pass
    con.close()

def save_nom_equip(id_equip, nom):
    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT OR REPLACE INTO equips (id_equip, nom) VALUES (?,?)", (str(id_equip), nom))
    con.commit(); con.close()

def load_noms_equips():
    con = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql("SELECT id_equip, nom FROM equips", con)
        con.close(); return dict(zip(df["id_equip"], df["nom"]))
    except:
        con.close(); return {}

def partit_exists(match_id):
    con = sqlite3.connect(DB_PATH)
    r = con.execute("SELECT 1 FROM partits WHERE match_id=?", (match_id,)).fetchone()
    con.close(); return r is not None

def save_partit(match_id, df, nom_a, nom_b, id_a, id_b, score_a, score_b):
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM partits WHERE match_id=?", (match_id,))
    con.execute("DELETE FROM jugades WHERE match_id=?", (match_id,))
    con.execute("DELETE FROM stats_jugador WHERE match_id=?", (match_id,))
    con.execute("DELETE FROM shots_zones WHERE match_id=?", (match_id,))
    con.execute("INSERT INTO partits VALUES (?,?,?,?,?,?,?,?,?)",
        (match_id, datetime.now().strftime("%Y-%m-%d %H:%M"),
         nom_a, nom_b, str(id_a), str(id_b), score_a, score_b, len(df)))
    rows = [(match_id, int(r["num"]), int(r["quart"]) if r["quart"]!="" else 0,
             float(r["min_num"]), str(r["temps"]), str(r["idEquip"]), str(r["dorsal"]),
             str(r["jugador"]), str(r["accio"]), str(r["marcador"]), int(r["punts"]),
             int(r.get("teamAction",0) or 0)) for _,r in df.iterrows()]
    con.executemany("INSERT INTO jugades (match_id,num,quart,min_num,temps,id_equip,dorsal,jugador,accio,marcador,punts,team_action) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit(); con.close()

MINS_PER_QUART = 10

def calc_minuts_reals(df):
    """Calcula els minuts reals jugats per cada jugador usant Entra/Surt del camp."""
    players = {}
    quart_max = int(df["quart"].max()) if not df.empty else 1
    for _, m in df.iterrows():
        nom = m.get("jugador","")
        if not nom or str(nom) in ("","nan"): continue
        idmove_str = str(m.get("accio",""))
        min_ = float(m.get("min_num", 0))
        # min_num és el minut DINS del quart (cronòmetre enrere: 10→0)
        quart = int(m.get("quart", 1)) if m.get("quart","") != "" else 1
        t = (quart - 1) * MINS_PER_QUART + (MINS_PER_QUART - min_ if min_ <= MINS_PER_QUART else min_)
        t = max(0, min(t, quart * MINS_PER_QUART))

        if nom not in players:
            players[nom] = {"intervals": [], "entrada": None}

        if "Entra al camp" in idmove_str:
            players[nom]["entrada"] = t
        elif "Surt del camp" in idmove_str:
            if players[nom]["entrada"] is not None:
                players[nom]["intervals"].append((players[nom]["entrada"], t))
                players[nom]["entrada"] = None
            else:
                inici_quart = (quart - 1) * MINS_PER_QUART
                players[nom]["intervals"].append((inici_quart, t))
        elif "Final de període" in idmove_str:
            if players[nom]["entrada"] is not None:
                fi = quart * MINS_PER_QUART
                if fi > players[nom]["entrada"]:
                    players[nom]["intervals"].append((players[nom]["entrada"], fi))
                players[nom]["entrada"] = None

    # Tanca intervals oberts (jugadores que acaben el partit sense "Surt del camp")
    fi_partit = quart_max * MINS_PER_QUART
    for nom, p in players.items():
        if p["entrada"] is not None and fi_partit > p["entrada"]:
            p["intervals"].append((p["entrada"], fi_partit))

    minuts = {}
    for nom, p in players.items():
        total = sum(fi - ini for ini, fi in p["intervals"])
        minuts[nom] = round(total, 1)
    return minuts

def calc_usage_rate(df_jug, df_equip_on_pista):
    """Calcula l'Usage Rate d'una jugadora.
    df_jug = accions de la jugadora
    df_equip_on_pista = accions de l'equip mentre la jugadora és a pista
    """
    tc_jug = int(df_jug["accio"].str.contains(
        "Cistella de 2|Cistella de 3|Intent fallat de 2|Intent fallat de 3|fallat de 2|fallat de 3",
        case=False, na=False).sum())
    tl_jug = int(df_jug["accio"].str.contains(
        "Cistella de 1|Intent fallat de 1", case=False, na=False).sum())

    tc_eq = int(df_equip_on_pista["accio"].str.contains(
        "Cistella de 2|Cistella de 3|Intent fallat de 2|Intent fallat de 3|fallat de 2|fallat de 3",
        case=False, na=False).sum())
    tl_eq = int(df_equip_on_pista["accio"].str.contains(
        "Cistella de 1|Intent fallat de 1", case=False, na=False).sum())

    num_jug = tc_jug + 0.44 * tl_jug
    den_eq  = tc_eq  + 0.44 * tl_eq
    if den_eq == 0: return 0
    return round(num_jug / den_eq * 100, 1)

def save_stats_jugador(match_id, data_consulta, df, teams, team_names):
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM stats_jugador WHERE match_id=?", (match_id,))
    minuts_reals = calc_minuts_reals(df)
    # Detecta nom de columna de jugador
    col_jug_fn = "jugador" if "jugador" in df.columns else "jugadora"
    # Unifica columna per facilitar el codi
    df = df.copy()
    df["jugador"] = df[col_jug_fn].fillna("")
    rows = []
    for jug in df["jugador"].unique():
        if not jug or str(jug) in ("","nan"): continue
        dj = df[df["jugador"]==jug]
        eq_id = dj["idEquip"].iloc[0]
        eq_nom = team_names.get(str(eq_id),"?")
        punts   = int(dj["punts"].sum())
        cist2   = int(dj["accio"].str.contains("Cistella de 2",case=False,na=False).sum())
        cist3   = int(dj["accio"].str.contains("Cistella de 3",case=False,na=False).sum())
        tl      = int(dj["accio"].str.contains("Cistella de 1",case=False,na=False).sum())
        faltes  = int(dj["accio"].str.contains("falta",case=False,na=False).sum())
        accions = len(dj)
        rival = [t for t in teams if t!=eq_id]
        rival_id = rival[0] if rival else None

        # Determina el nom de la columna de jugador
        col_jug = "jugador" if "jugador" in df.columns else "jugadora"

        # Usa intervals reals (Entra/Surt) per calcular el +/-
        MINS_Q = 10
        intervals_imp = []; en_pista_imp = {}
        # Detecta si la jugadora comença a pista (primer event és Surt sense Entra previ)
        primer_event = df[df["jugador"]==jug].sort_values("num").iloc[0] if not df[df["jugador"]==jug].empty else None
        if primer_event is not None:
            primer_accio = str(primer_event.get("accio",""))
            primer_quart = int(primer_event.get("quart",1))
            if "Surt" in primer_accio and "camp" in primer_accio:
                # Comença a pista des de l'inici del quart
                en_pista_imp[jug] = (primer_quart-1)*MINS_Q
        for _, row_imp in df.sort_values("num").iterrows():
            jug_imp = str(row_imp.get(col_jug, ""))
            if jug_imp != str(jug): continue
            accio_imp = str(row_imp.get("accio",""))
            quart_imp = int(row_imp.get("quart",1))
            min_imp = float(row_imp.get("min_num",0))
            t_imp = (quart_imp-1)*MINS_Q + (MINS_Q - min_imp if min_imp <= MINS_Q else min_imp)
            t_imp = max(0, min(t_imp, quart_imp*MINS_Q))
            if "Entra" in accio_imp and "camp" in accio_imp:
                en_pista_imp[jug] = t_imp
            elif "Surt" in accio_imp and "camp" in accio_imp:
                ti = en_pista_imp.pop(jug, (quart_imp-1)*MINS_Q)
                if t_imp > ti: intervals_imp.append((ti, t_imp))
            elif "Final de període" in accio_imp or "Final període" in accio_imp:
                fi_imp = quart_imp * MINS_Q
                if jug in en_pista_imp:
                    ti = en_pista_imp.pop(jug)
                    if fi_imp > ti: intervals_imp.append((ti, fi_imp))
        for ti_o in en_pista_imp.values():
            fi_o = df["quart"].max() * MINS_Q if not df.empty else 40
            if fi_o > ti_o: intervals_imp.append((ti_o, fi_o))
        # Normalitza intervals (elimina np.int64)
        intervals_imp = [(float(ti), float(tf)) for ti, tf in intervals_imp]

        if not intervals_imp:
            # Fallback: rang de num
            n_min,n_max = dj["num"].min(),dj["num"].max()
            dr = df[(df["num"]>=n_min)&(df["num"]<=n_max)]
            pf = int(dr[dr["idEquip"]==eq_id]["punts"].sum())
            pc = int(dr[dr["idEquip"]==rival_id]["punts"].sum()) if rival_id else 0
        else:
            df_t = df.copy()
            df_t["t_abs"] = df_t.apply(
                lambda r: (int(r["quart"])-1)*10+(10-float(r["min_num"]))
                if float(r.get("min_num",0))<=10 else float(r.get("min_num",0)), axis=1)
            pf = pc = 0
            for ti_r,tf_r in intervals_imp:
                df_i = df_t[(df_t["t_abs"]>=ti_r)&(df_t["t_abs"]<=tf_r)]
                pf += int(df_i[df_i["idEquip"]==eq_id]["punts"].sum())
                if rival_id:
                    pc += int(df_i[df_i["idEquip"]==rival_id]["punts"].sum())
        impacte = pf - pc
        min_jug = minuts_reals.get(jug, 0)
        pts_min = round(punts/min_jug, 2) if min_jug > 0 else 0.0
        # Usage Rate
        usage = 0.0
        if intervals_imp:
            df_t_us = df.copy()
            df_t_us["t_abs"] = df_t_us.apply(
                lambda r: (int(r["quart"])-1)*10+(10-float(r["min_num"]))
                if float(r.get("min_num",0))<=10 else float(r.get("min_num",0)), axis=1)
            mask_on_us = df_t_us["t_abs"].apply(
                lambda t: any(ti<=t<=tf for ti,tf in intervals_imp))
            df_eq_on = df_t_us[mask_on_us & (df_t_us["idEquip"]==eq_id)]
            usage = calc_usage_rate(dj, df_eq_on)
        else:
            usage = calc_usage_rate(dj, df[df["idEquip"]==eq_id])
        rows.append((match_id,data_consulta,jug,eq_nom,punts,cist2,cist3,tl,faltes,accions,impacte,pts_min,round(usage,1)))
    # Afegir minuts a cada row
    rows_amb_min = [r + (minuts_reals.get(r[2], 0),) for r in rows]
    con.executemany("INSERT INTO stats_jugador (match_id,data_consulta,jugador,equip_nom,punts,cistelles_2,cistelles_3,tirs_lliures,faltes,accions,impacte,pts_per_min,minuts,usage_rate) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows_amb_min)
    con.commit(); con.close()

def save_shots_zones(match_id, data_consulta, df, team_names):
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM shots_zones WHERE match_id=?", (match_id,))
    players_list = [("__equip__", eq) for eq in df["idEquip"].unique() if eq and str(eq)!="0"]
    for jug in df["jugador"].unique():
        if jug and str(jug) not in ("","nan"):
            eq_id = df[df["jugador"]==jug]["idEquip"].iloc[0]
            players_list.append((jug, eq_id))
    for jug, eq_id in players_list:
        dj = df[df["idEquip"]==eq_id] if jug=="__equip__" else df[df["jugador"]==jug]
        eq_nom = team_names.get(str(eq_id),"?")
        v1m = int(dj["accio"].str.contains("Cistella de 1|Tir lliure convertit",case=False,na=False).sum())
        v1x = int(dj["accio"].str.contains("Intent fallat de 1",case=False,na=False).sum())
        v2m = int(dj["accio"].str.contains("Cistella de 2",case=False,na=False).sum())
        v2x = int(dj["accio"].str.contains("Intent fallat de 2|fall.*2|2.*fall",case=False,na=False).sum())
        v3m = int(dj["accio"].str.contains("Cistella de 3",case=False,na=False).sum())
        v3x = int(dj["accio"].str.contains("Intent fallat de 3|fall.*3|3.*fall",case=False,na=False).sum())
        con.execute("INSERT INTO shots_zones (match_id,data_consulta,equip_nom,jugador,val1_made,val1_miss,val2_made,val2_miss,val3_made,val3_miss) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (match_id,data_consulta,eq_nom,jug,v1m,v1x,v2m,v2x,v3m,v3x))
    con.commit(); con.close()

def save_timeouts(match_id, data_consulta, df, team_names):
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM timeouts WHERE match_id=?", (match_id,))
    results = analyze_timeouts(df, team_names)
    for r in results:
        con.execute(
            "INSERT INTO timeouts (match_id,data_consulta,equip_nom,quart,min_timeout,min_cistella,segons_resposta,jugadora,accio,va_anotar,dins_24s) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (match_id,data_consulta,r['equip_nom'],r['quart'],r['min_timeout'],
             r['min_cistella'],r['segons_resposta'],r['jugadora'],r['accio'],
             r['va_anotar'],r.get('dins_24s',0)))
    con.commit(); con.close()

def save_tirs_fcbq(match_id, data_consulta, equip_local, equip_visitant, tirs_local, tirs_visit):
    con_t = sqlite3.connect(DB_PATH)
    con_t.execute("DELETE FROM tirs_fcbq WHERE match_id=?", (match_id,))
    rows = []
    for t in tirs_local:
        rows.append((match_id, data_consulta, equip_local, float(t['x']), float(t['y']), 1 if t.get('fet') else 0))
    for t in tirs_visit:
        rows.append((match_id, data_consulta, equip_visitant, float(t['x']), float(t['y']), 1 if t.get('fet') else 0))
    con_t.executemany("INSERT INTO tirs_fcbq (match_id,data_consulta,equip_nom,x,y,fet) VALUES (?,?,?,?,?,?)", rows)
    con_t.commit(); con_t.close()

def load_jugades_db(match_id):
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM jugades WHERE match_id=? ORDER BY num", con, params=(match_id,))
    con.close()
    return df.rename(columns={"id_equip":"idEquip","team_action":"teamAction"})

def load_partits_db():
    con = sqlite3.connect(DB_PATH)
    try: df = pd.read_sql("SELECT * FROM partits ORDER BY data_consulta DESC", con)
    except: df = pd.DataFrame()
    con.close(); return df

def load_stats_jugador_db():
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM stats_jugador ORDER BY data_consulta", con)
    con.close(); return df

def load_shots_zones_db():
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM shots_zones ORDER BY data_consulta", con)
    con.close(); return df

def load_timeouts_db():
    con = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql("SELECT * FROM timeouts ORDER BY data_consulta, min_timeout", con)
    except:
        df = pd.DataFrame()
    con.close(); return df

def load_tirs_fcbq(match_id=None, equip_nom=None):
    con_t = sqlite3.connect(DB_PATH)
    q = "SELECT * FROM tirs_fcbq WHERE 1=1"
    params = []
    if match_id: q += " AND match_id=?"; params.append(match_id)
    if equip_nom: q += " AND equip_nom=?"; params.append(equip_nom)
    df_t = pd.read_sql(q, con_t, params=params)
    con_t.close()
    return df_t

def delete_partit_db(match_id):
    con = sqlite3.connect(DB_PATH)
    for tbl in ["partits","jugades","stats_jugador","shots_zones","timeouts"]:
        con.execute(f"DELETE FROM {tbl} WHERE match_id=?", (match_id,))
    con.commit(); con.close()


# ── Funcions de temps morts ────────────────────────────────────────────────
def analyze_timeouts(df, team_names):
    results = []
    moves = df.to_dict('records')
    for i, m in enumerate(moves):
        if 'Temps mort' not in str(m.get('accio','')):
            continue
        eq_id  = m.get('idEquip','')
        quart  = int(m.get('quart',1)) if m.get('quart','') != '' else 1
        min_to = float(m.get('min_num',0))
        min_abs_to = (quart-1)*MINS_PER_QUART + min_to
        eq_nom = team_names.get(str(eq_id),'?')
        va_anotar = 0; jugadora = ''; accio_cist = ''; mins_cist = None
        for j in range(i+1, len(moves)):
            nm = moves[j]
            q_next = int(nm.get('quart',1)) if nm.get('quart','') != '' else 1
            if q_next != quart: break
            move_str = str(nm.get('accio',''))
            if nm.get('idEquip','') == eq_id and any(c in move_str for c in ['Cistella de 1','Cistella de 2','Cistella de 3']):
                min_cist = float(nm.get('min_num',0))
                mins_cist = (q_next-1)*MINS_PER_QUART + min_cist
                jugadora = str(nm.get('jugador',''))
                accio_cist = move_str
                va_anotar = 1
                break
        # Calcula diferència en MINUTS de joc (no de vídeo)
        # min_abs_to i mins_cist són en minuts absoluts de joc
        if mins_cist is not None:
            diff_min = mins_cist - min_abs_to  # positiu = cistella DESPRÉS del TM
            segons = round(diff_min * 60, 1)
            dins_24s = (diff_min >= 0 and diff_min * 60 <= 24)
        else:
            segons = None
            dins_24s = False
        results.append({'equip_nom':eq_nom,'quart':quart,'min_timeout':round(min_abs_to,2),
            'min_cistella':round(mins_cist,2) if mins_cist else None,
            'segons_resposta':segons,'jugadora':jugadora,'accio':accio_cist,
            'va_anotar':va_anotar,'dins_24s':dins_24s})
    return results


# ══════════════════════════════════════════════════
# HELPERS DE PARTIT
# ══════════════════════════════════════════════════
def get_teams(df):
    return [t for t in df["idEquip"].unique() if t and t!="0"]

def get_teams_ordered(df):
    """Retorna [equip_local, equip_visitant] usant el marcador per detectar qui és qui.
    El primer número del marcador API és sempre el local."""
    teams = get_teams(df)
    if len(teams) < 2:
        return teams

    # Agafa l'últim marcador vàlid
    last_score = None
    for _, r in df.iloc[::-1].iterrows():
        marc = str(r.get("marcador",""))
        if "-" in marc:
            try:
                sa, sb = int(marc.split("-")[0]), int(marc.split("-")[1])
                last_score = (sa, sb)
                break
            except: pass

    if last_score is None:
        return teams

    # Calcula punts totals per equip
    pts = {}
    for tid in teams:
        pts[tid] = int(df[df["idEquip"]==tid]["punts"].sum())

    sa, sb = last_score
    # L'equip local és el que té pts més propers a sa
    t0, t1 = teams[0], teams[1]
    if abs(pts.get(t0,0) - sa) <= abs(pts.get(t1,0) - sa):
        return [t0, t1]  # t0 és local
    else:
        return [t1, t0]  # t1 és local

def score_evo(df):
    rows=[]
    for _,r in df.iterrows():
        marc=str(r["marcador"])
        if "-" in marc:
            try:
                sa,sb=int(marc.split("-")[0]),int(marc.split("-")[1])
                rows.append({"num":r["num"],"quart":r["quart"],"temps":r["temps"],"scoreA":sa,"scoreB":sb,"diff":sa-sb,
                             "min_num":r.get("min_num",0)})
            except: pass
    return pd.DataFrame(rows)

def final_score(sdf):
    if sdf.empty: return 0, 0
    last=sdf.iloc[-1]
    try: return int(last["scoreA"]), int(last["scoreB"])
    except: return 0, 0

def estat_marc(row, teams):
    marc=str(row.get("marcador",""))
    if "-" not in marc: return "desconegut"
    try:
        sa,sb=int(marc.split("-")[0]),int(marc.split("-")[1])
        diff=(sa-sb) if row["idEquip"]==teams[0] else (sb-sa)
        return "Guanyant" if diff>0 else ("Empatat" if diff==0 else "Perdent")
    except: return "desconegut"

def get_shot_counts(df_sub):
    v1m=int(df_sub["accio"].str.contains("Cistella de 1|Tir lliure convertit",case=False,na=False).sum())
    v1x=int(df_sub["accio"].str.contains("Intent fallat de 1",case=False,na=False).sum())
    v2m=int(df_sub["accio"].str.contains("Cistella de 2",case=False,na=False).sum())
    v2x=int(df_sub["accio"].str.contains("Intent fallat de 2|fall.*2|2.*fall",case=False,na=False).sum())
    v3m=int(df_sub["accio"].str.contains("Cistella de 3",case=False,na=False).sum())
    v3x=int(df_sub["accio"].str.contains("Intent fallat de 3|fall.*3|3.*fall",case=False,na=False).sum())
    return v1m,v1x,v2m,v2x,v3m,v3x


# ══════════════════════════════════════════════════
# INTERVALS, QUINTETS, ON/OFF
# ══════════════════════════════════════════════════
def get_intervals_jugadores_global(df):
    """Retorna dict jugadora -> [(t_ini, t_fi, equip_id)] en minuts absoluts de partit."""
    MINS_Q = 10
    intervals = {}
    en_pista  = {}
    col_j = "jugador" if "jugador" in df.columns else "jugadora"

    for jug_x in df[col_j].unique():
        if not jug_x or str(jug_x) in ("","nan"): continue
        df_jx = df[df[col_j]==jug_x].sort_values("num")
        if df_jx.empty: continue
        primer_acc = str(df_jx.iloc[0].get("accio",""))
        primer_q   = int(df_jx.iloc[0].get("quart",1))
        primer_ei  = str(df_jx.iloc[0].get("idEquip",""))
        if "Surt" in primer_acc and "camp" in primer_acc:
            en_pista[jug_x] = ((primer_q-1)*MINS_Q, primer_ei)

    for _, row in df.sort_values("num").iterrows():
        jug = row.get(col_j, "")
        if not jug or str(jug) in ("","nan"): continue
        accio = str(row.get("accio",""))
        quart = int(row.get("quart",1)) if row.get("quart","") != "" else 1
        min_dins = float(row.get("min_num", 0))
        if min_dins > MINS_Q:
            t_min = min_dins
        else:
            t_min = (quart-1)*MINS_Q + (MINS_Q - min_dins)
        t_min = max(0, min(t_min, quart * MINS_Q))
        eq_id = str(row.get("idEquip",""))
        if "Entra al camp" in accio:
            en_pista[jug] = (t_min, eq_id)
        elif "Surt del camp" in accio:
            ini_t = en_pista.pop(jug, ((quart-1)*MINS_Q, eq_id))
            t_ini_real = ini_t[0]; eq_real = ini_t[1]
            if t_min > t_ini_real:
                intervals.setdefault(jug, []).append((t_ini_real, t_min, eq_real))
        elif "Final de període" in accio:
            fi = quart * MINS_Q
            for j, (ti, ei) in list(en_pista.items()):
                if fi > ti:
                    intervals.setdefault(j, []).append((ti, fi, ei))
            en_pista = {}
    for j, (ti, ei) in en_pista.items():
        fi = df["quart"].max() * MINS_Q if not df.empty else 40
        if fi > ti:
            intervals.setdefault(j, []).append((ti, fi, ei))
    return intervals


def calc_pm_combinacions(df_orig, mode="quintets"):
    """Calcula +/- per combinacions de jugadores (quintets o parelles).
    mode: 'quintets' o 'parelles'
    Retorna llista de dicts: {combinacio, equip, minuts, pf, pc, pm, pm_min}
    """
    MINS_Q = 10
    col_j = "jugador" if "jugador" in df_orig.columns else "jugadora"
    df_orig = df_orig.copy()
    df_orig["jugador"] = df_orig[col_j].fillna("")
    intervals_jug = get_intervals_jugadores_global(df_orig)

    # Construeix línia temporal d'esdeveniments (canvis de pista) per equip
    teams = get_teams_ordered(df_orig)
    if len(teams) < 2: return []

    # Per cada equip, construeix una llista de "punts de canvi" (timestamps)
    results = {}  # key: (equip, frozenset(jugadores)) -> [minuts, pf, pc]

    df_t = df_orig.copy()
    df_t["t_abs"] = df_t.apply(
        lambda r: (int(r["quart"])-1)*10+(10-float(r["min_num"]))
        if float(r.get("min_num",0))<=10 else float(r.get("min_num",0)), axis=1)

    for eq_id in teams:
        rival_id = [t for t in teams if t != eq_id][0]
        # Jugadores d'aquest equip amb intervals
        jugs_eq = [j for j,ivs in intervals_jug.items()
                   if ivs and str(ivs[0][2]) == str(eq_id)]
        if not jugs_eq: continue

        # Recull tots els punts de canvi (inicis i finals d'intervals)
        canvis = set([0.0])
        max_t = float(df_orig["quart"].max() * MINS_Q) if not df_orig.empty else 40.0
        canvis.add(max_t)
        for j in jugs_eq:
            for ti,tf,_ in intervals_jug[j]:
                canvis.add(round(ti,2)); canvis.add(round(tf,2))
        canvis = sorted(canvis)

        # Per cada microinterval entre canvis consecutius, determina qui és a pista
        for i in range(len(canvis)-1):
            t0, t1 = canvis[i], canvis[i+1]
            if t1 - t0 < 0.01: continue
            tm = (t0+t1)/2
            en_pista_ara = []
            for j in jugs_eq:
                for ti,tf,_ in intervals_jug[j]:
                    if ti <= tm < tf:
                        en_pista_ara.append(j)
                        break

            if mode == "quintets":
                if len(en_pista_ara) != 5: continue
                combos = [tuple(sorted(en_pista_ara))]
            else:  # parelles
                if len(en_pista_ara) < 2: continue
                combos = [tuple(sorted(c)) for c in itertools.combinations(en_pista_ara, 2)]

            # Punts en aquest microinterval
            df_i = df_t[(df_t["t_abs"]>=t0)&(df_t["t_abs"]<t1)]
            pf_i = int(df_i[df_i["idEquip"]==eq_id]["punts"].sum())
            pc_i = int(df_i[df_i["idEquip"]==rival_id]["punts"].sum())
            durada = t1-t0

            for combo in combos:
                key = (str(eq_id), combo)
                if key not in results:
                    results[key] = [0.0, 0, 0]
                results[key][0] += durada
                results[key][1] += pf_i
                results[key][2] += pc_i

    rows = []
    for (eq_id, combo), (mins_c, pf_c, pc_c) in results.items():
        if mins_c < 0.5: continue
        rows.append({
            "equip": eq_id,
            "combinacio": combo,
            "minuts": round(mins_c,1),
            "pf": pf_c,
            "pc": pc_c,
            "pm": pf_c - pc_c,
            "pm_min": round((pf_c-pc_c)/mins_c, 3) if mins_c>0 else 0
        })
    return rows


def calc_possessions(df_equip):
    """Calcula les possessions estimades d'un equip."""
    tc_int = int(df_equip["accio"].str.contains(
        "Cistella de 2|Cistella de 3|Intent fallat de 2|Intent fallat de 3|"
        "Tir de 2|Tir de 3|fallat de 2|fallat de 3",
        case=False, na=False).sum())
    tl_int = int(df_equip["accio"].str.contains(
        "Cistella de 1|Intent fallat de 1", case=False, na=False).sum())
    return tc_int + 0.44 * tl_int

def calc_eficiencies(df_orig, teams, team_names):
    """Calcula eficiència ofensiva i defensiva per equip."""
    result = {}
    for i, tid in enumerate(teams[:2]):
        rival_id = teams[1-i] if len(teams) > 1 else None
        df_eq  = df_orig[df_orig["idEquip"] == tid]
        df_riv = df_orig[df_orig["idEquip"] == rival_id] if rival_id else pd.DataFrame()
        pts_of = int(df_eq["punts"].sum())
        pts_def = int(df_riv["punts"].sum()) if not df_riv.empty else 0
        poss_of  = calc_possessions(df_eq)
        poss_def = calc_possessions(df_riv) if not df_riv.empty else 1
        off_rtg = round(pts_of  / poss_of  * 100, 1) if poss_of  > 0 else 0
        def_rtg = round(pts_def / poss_def * 100, 1) if poss_def > 0 else 0
        net_rtg = round(off_rtg - def_rtg, 1)
        result[tid] = {
            "nom": team_names.get(tid, "?"),
            "pts_of": pts_of, "pts_def": pts_def,
            "poss_of": round(poss_of, 1), "poss_def": round(poss_def, 1),
            "off_rtg": off_rtg, "def_rtg": def_rtg, "net_rtg": net_rtg
        }
    return result

def calc_onoff_raw(df_orig, jugadora, equip_id, teams):
    """Calcula punts/possessions ON i OFF en brut (sense convertir a ràtio) a partir
    dels intervals reals Entra/Surt d'una jugadora en UN partit. Bloc de construcció
    compartit per calc_onoff() (rating d'un partit) i calc_onoff_agregat() (multi-partit)."""
    rival_id = next((t for t in teams if t != equip_id), None)
    if rival_id is None: return None

    MINS_Q = 10
    col_j = "jugador" if "jugador" in df_orig.columns else "jugadora"

    # Calcula intervals reals de la jugadora
    intervals_on = []; en_pista = {}
    df_jug_rows = df_orig[df_orig[col_j]==jugadora]
    if df_jug_rows.empty: return None

    # Detecta si comença a pista
    primer = df_jug_rows.sort_values("num").iloc[0]
    if "Surt" in str(primer.get("accio","")) and "camp" in str(primer.get("accio","")):
        en_pista[jugadora] = (int(primer.get("quart",1))-1)*MINS_Q

    for _,row in df_orig.sort_values("num").iterrows():
        if str(row.get(col_j,"")) != str(jugadora): continue
        acc = str(row.get("accio",""))
        q = int(row.get("quart",1))
        m = float(row.get("min_num",0))
        t = (q-1)*MINS_Q + (MINS_Q-m if m<=MINS_Q else m)
        t = max(0, min(t, q*MINS_Q))
        if "Entra" in acc and "camp" in acc:
            en_pista[jugadora] = t
        elif "Surt" in acc and "camp" in acc:
            ti = en_pista.pop(jugadora, (q-1)*MINS_Q)
            if t > ti: intervals_on.append((float(ti), float(t)))
        elif "Final de període" in acc:
            if jugadora in en_pista:
                ti = en_pista.pop(jugadora)
                fi = float(q*MINS_Q)
                if fi > ti: intervals_on.append((float(ti), fi))
    for ti_o in en_pista.values():
        fi_o = float(df_orig["quart"].max()*MINS_Q)
        if fi_o > ti_o: intervals_on.append((float(ti_o), fi_o))

    if not intervals_on: return None

    # Precalcula t_abs
    df_t = df_orig.copy()
    df_t["t_abs"] = df_t.apply(
        lambda r: (int(r["quart"])-1)*10+(10-float(r["min_num"]))
        if float(r.get("min_num",0))<=10 else float(r.get("min_num",0)), axis=1)

    # Construeix màscara ON (intervals reals)
    mask_on = df_t["t_abs"].apply(
        lambda t: any(ti<=t<=tf for ti,tf in intervals_on))

    df_on_eq  = df_t[mask_on  & (df_t["idEquip"]==equip_id)]
    df_on_riv = df_t[mask_on  & (df_t["idEquip"]==rival_id)]
    df_off_eq = df_t[~mask_on & (df_t["idEquip"]==equip_id)]
    df_off_riv= df_t[~mask_on & (df_t["idEquip"]==rival_id)]

    return {
        "pts_on":      int(df_on_eq["punts"].sum()),  "poss_on":      calc_possessions(df_on_eq),
        "pts_on_riv":  int(df_on_riv["punts"].sum()), "poss_on_riv":  calc_possessions(df_on_riv),
        "pts_off":     int(df_off_eq["punts"].sum()), "poss_off":     calc_possessions(df_off_eq),
        "pts_off_riv": int(df_off_riv["punts"].sum()),"poss_off_riv": calc_possessions(df_off_riv),
    }

def calc_onoff(df_orig, jugadora, equip_id, teams):
    """Calcula On/Off Rating d'una jugadora usant intervals reals (un sol partit)."""
    MIN_POSS = 4  # mínim de possessions per considerar el rating vàlid

    raw = calc_onoff_raw(df_orig, jugadora, equip_id, teams)
    if raw is None: return None

    def rtg(pts, poss, pts_r, poss_r):
        # Si poques possessions, rating no fiable
        if poss < MIN_POSS: return None, None, None
        off  = round(pts/poss*100, 1)
        deff = round(pts_r/poss_r*100, 1) if poss_r >= MIN_POSS else None
        net  = round(off-deff, 1) if deff is not None else None
        return off, deff, net

    on_off,  on_def,  on_net  = rtg(raw["pts_on"],  raw["poss_on"],  raw["pts_on_riv"],  raw["poss_on_riv"])
    off_off, off_def, off_net = rtg(raw["pts_off"], raw["poss_off"], raw["pts_off_riv"], raw["poss_off_riv"])

    if on_net is None or off_net is None:
        diff = None
    else:
        diff = round(on_net - off_net, 1)
        # Cap de valors poc raonables (>50 punts/100 poss és sospitós)
        if abs(diff) > 50 and not (raw["poss_on"] >= 8 and raw["poss_off"] >= 8):
            diff = None  # marca com no fiable

    return {
        "on_off_rtg":  on_off,  "on_def_rtg":  on_def,  "on_net_rtg":  on_net,
        "off_off_rtg": off_off, "off_def_rtg": off_def, "off_net_rtg": off_net,
        "diff": diff,
        "on_poss":  round(raw["poss_on"], 1),
        "off_poss": round(raw["poss_off"], 1),
    }

def calc_onoff_agregat(df_partits, min_poss_on=150, min_poss_off=150):
    """On/Off Rating agregat de TOTS els partits disponibles, ponderat per possessions:
    suma punts i possessions ON/OFF de tots els partits abans de dividir, en comptes de
    fer la mitjana dels Net Ratings de cada partit per separat (que faria pesar igual un
    partit de pocs minuts que un de molts). Marca "fiable" segons un llindar mínim de
    possessions de temporada (per defecte 150 ON i 150 OFF), configurable."""
    # Clau d'agregació = nom d'equip (no idEquip): l'idEquip que ve del scraping és un
    # identificador intern PER PARTIT, no estable entre partits — agregar-hi per idEquip
    # crea una fila diferent per jugadora a cada partit en lloc de sumar-les totes juntes.
    acumulat = {}       # (equip_nom, jugadora) -> sumes en brut

    for _, p in df_partits.iterrows():
        df_m = load_jugades_db(p['match_id'])
        if df_m.empty: continue
        teams_m = get_teams_ordered(df_m)
        if len(teams_m) < 2: continue

        tn_m = {}
        if len(teams_m) >= 1: tn_m[str(teams_m[0])] = p['nom_a']
        if len(teams_m) >= 2: tn_m[str(teams_m[1])] = p['nom_b']

        col_j_m = "jugador" if "jugador" in df_m.columns else "jugadora"
        df_m = df_m.copy()
        df_m["jugador"] = df_m[col_j_m].fillna("")

        for jug in df_m["jugador"].unique():
            if not jug or str(jug) in ("", "nan"): continue
            eq_id = str(df_m[df_m["jugador"]==jug]["idEquip"].iloc[0])
            raw = calc_onoff_raw(df_m, jug, eq_id, teams_m)
            if raw is None: continue

            key = (tn_m.get(eq_id, "?"), jug)
            if key not in acumulat:
                acumulat[key] = {"pts_on":0,"poss_on":0.0,"pts_on_riv":0,"poss_on_riv":0.0,
                                  "pts_off":0,"poss_off":0.0,"pts_off_riv":0,"poss_off_riv":0.0,
                                  "partits":0}
            a = acumulat[key]
            a["pts_on"]      += raw["pts_on"];      a["poss_on"]      += raw["poss_on"]
            a["pts_on_riv"]  += raw["pts_on_riv"];  a["poss_on_riv"]  += raw["poss_on_riv"]
            a["pts_off"]     += raw["pts_off"];     a["poss_off"]     += raw["poss_off"]
            a["pts_off_riv"] += raw["pts_off_riv"]; a["poss_off_riv"] += raw["poss_off_riv"]
            a["partits"]     += 1

    resultats = []
    for (eq_nom, jug), a in acumulat.items():
        net_on  = round(100 * (a["pts_on"]  - a["pts_on_riv"])  / a["poss_on"],  1) if a["poss_on"]  > 0 else None
        net_off = round(100 * (a["pts_off"] - a["pts_off_riv"]) / a["poss_off"], 1) if a["poss_off"] > 0 else None
        onoff_agr = round(net_on - net_off, 1) if (net_on is not None and net_off is not None) else None
        fiable = a["poss_on"] >= min_poss_on and a["poss_off"] >= min_poss_off
        resultats.append({
            "jugadora": jug, "equip_nom": eq_nom,
            "partits": a["partits"],
            "poss_on": round(a["poss_on"], 1), "poss_off": round(a["poss_off"], 1),
            "net_on": net_on, "net_off": net_off, "onoff_agregat": onoff_agr,
            "fiable": fiable,
        })
    return resultats

def calc_context_bloc(df_partits, top_n_bloc=3, llindar_concentrat=65):
    """Per cada jugadora, identifica amb quines companyes comparteix més % dels seus
    minuts ON (reutilitza calc_pm_combinacions mode 'parelles' i get_intervals_jugadores_global,
    acumulat de tots els partits). Marca "context concentrat" si el % compartit amb la
    companya més freqüent supera el llindar (per defecte 65%)."""
    # Clau d'agregació = nom d'equip (no idEquip, que és un identificador intern PER
    # PARTIT i no estable entre partits — vegeu comentari a calc_onoff_agregat()).
    parelles_acum = {}    # (equip_nom, frozenset({j1,j2})) -> minuts acumulats
    on_total_acum = {}    # (equip_nom, jugadora) -> minuts ON totals acumulats

    for _, p in df_partits.iterrows():
        df_m = load_jugades_db(p['match_id'])
        if df_m.empty: continue
        teams_m = get_teams_ordered(df_m)
        if len(teams_m) < 2: continue

        tn_m = {}
        if len(teams_m) >= 1: tn_m[str(teams_m[0])] = p['nom_a']
        if len(teams_m) >= 2: tn_m[str(teams_m[1])] = p['nom_b']

        col_j_m = "jugador" if "jugador" in df_m.columns else "jugadora"
        df_m = df_m.copy()
        df_m["jugador"] = df_m[col_j_m].fillna("")

        # Minuts ON totals per jugadora (independent de companyes)
        intervals_m = get_intervals_jugadores_global(df_m)
        for jug, ivs in intervals_m.items():
            if not ivs: continue
            eq_nom = tn_m.get(str(ivs[0][2]), "?")
            key = (eq_nom, jug)
            on_total_acum[key] = on_total_acum.get(key, 0.0) + sum(tf-ti for ti,tf,_ in ivs)

        # Minuts compartits per parella
        for r in calc_pm_combinacions(df_m, mode="parelles"):
            eq_nom = tn_m.get(str(r["equip"]), "?")
            key = (eq_nom, frozenset(r["combinacio"]))
            parelles_acum[key] = parelles_acum.get(key, 0.0) + r["minuts"]

    resultats = []
    for (eq_nom, jug), min_on_total in on_total_acum.items():
        if min_on_total <= 0: continue
        companyes = []
        for (eq_par, combo), min_par in parelles_acum.items():
            if eq_par != eq_nom or jug not in combo: continue
            altra = [j for j in combo if j != jug][0]
            # min() perquè calc_pm_combinacions() i get_intervals_jugadores_global() usen
            # reconstruccions de microintervals independents; poden diferir per soroll
            # d'arrodoniment de dècimes, però la parella mai pot superar el total individual.
            pct = min(round(min_par / min_on_total * 100, 1), 100.0)
            companyes.append((altra, round(min_par, 1), pct))
        companyes.sort(key=lambda x: -x[1])
        top_companyes = companyes[:top_n_bloc]
        pct_top = top_companyes[0][2] if top_companyes else 0.0

        resultats.append({
            "jugadora": jug, "equip_nom": eq_nom,
            "min_on_total": round(min_on_total, 1),
            "bloc_habitual": ", ".join(f"{c[0]} ({c[2]}%)" for c in top_companyes),
            "pct_bloc_top": pct_top,
            "context_concentrat": pct_top >= llindar_concentrat,
            "_top_companya": top_companyes[0][0] if top_companyes else None,
        })
    return resultats

def calc_onoff_bloc_split(df_orig, jugadora, companys, equip_id, teams):
    """Divideix les possessions ON d'una jugadora (UN partit) en dos blocs: 'amb_bloc'
    (almenys una de les companyes donades també és a pista) i 'sense_bloc' (cap de les
    companyes donades és a pista). Reutilitza el patró de microintervals de
    calc_lineup_impact(). Retorna punts/possessions en brut (equip i rival) de cada bloc,
    pensat per acumular entre partits abans de dividir."""
    rival_id = next((t for t in teams if t != equip_id), None)
    if rival_id is None or not companys: return None

    MINS_Q = 10
    intervals_jug = get_intervals_jugadores_global(df_orig)
    ivs_jugadora = [(ti, tf) for ti, tf, ei in intervals_jug.get(jugadora, []) if str(ei) == str(equip_id)]
    if not ivs_jugadora: return None

    df_t = df_orig.copy()
    df_t["t_abs"] = df_t.apply(
        lambda r: (int(r["quart"])-1)*10+(10-float(r["min_num"]))
        if float(r.get("min_num",0))<=10 else float(r.get("min_num",0)), axis=1)

    canvis = set()
    for ti, tf in ivs_jugadora:
        canvis.add(round(ti, 2)); canvis.add(round(tf, 2))
    for comp in companys:
        for ti, tf, ei in intervals_jug.get(comp, []):
            if str(ei) != str(equip_id): continue
            for ti_j, tf_j in ivs_jugadora:
                if tf > ti_j and ti < tf_j:
                    canvis.add(round(max(ti, ti_j), 2)); canvis.add(round(min(tf, tf_j), 2))
    canvis = sorted(canvis)

    amb_bloc_ivs, sense_bloc_ivs = [], []
    for i in range(len(canvis)-1):
        t0, t1 = canvis[i], canvis[i+1]
        if t1 - t0 < 0.01: continue
        tm = (t0+t1)/2
        if not any(ti <= tm < tf for ti, tf in ivs_jugadora): continue
        company_present = any(
            any(ti <= tm < tf for ti, tf, ei in intervals_jug.get(comp, []) if str(ei) == str(equip_id))
            for comp in companys)
        (amb_bloc_ivs if company_present else sense_bloc_ivs).append((t0, t1))

    def sum_pts_poss(intervals):
        if not intervals: return {"pts":0, "poss":0.0, "pts_riv":0, "poss_riv":0.0}
        mask = df_t["t_abs"].apply(lambda t: any(ti <= t < tf for ti,tf in intervals))
        df_eq  = df_t[mask & (df_t["idEquip"]==equip_id)]
        df_riv = df_t[mask & (df_t["idEquip"]==rival_id)]
        return {"pts": int(df_eq["punts"].sum()), "poss": calc_possessions(df_eq),
                "pts_riv": int(df_riv["punts"].sum()), "poss_riv": calc_possessions(df_riv)}

    return {"amb_bloc": sum_pts_poss(amb_bloc_ivs), "sense_bloc": sum_pts_poss(sense_bloc_ivs)}

def calc_context_onoff(df_partits, min_poss_seg=40):
    """Combina la companya habitual (calc_context_bloc) amb l'On/Off segmentat amb/sense
    aquest bloc (calc_onoff_bloc_split), acumulat de tots els partits, i deriva un
    indicador de fiabilitat de context (🟢/🟡/🔴/⚪) a partir de com de consistent és el
    Net Rating de la jugadora amb i sense la seva companya més freqüent."""
    bloc_info = calc_context_bloc(df_partits)
    resultats = []

    for info in bloc_info:
        jug = info["jugadora"]
        top_companya = info["_top_companya"]

        if top_companya is None:
            resultats.append({**info, "net_amb_bloc": None, "net_sense_bloc": None,
                "poss_amb_bloc": 0.0, "poss_sense_bloc": 0.0, "fiabilitat_context": "⚪ Dades insuficients"})
            continue

        acum_amb   = {"pts":0, "poss":0.0, "pts_riv":0, "poss_riv":0.0}
        acum_sense = {"pts":0, "poss":0.0, "pts_riv":0, "poss_riv":0.0}
        for _, p in df_partits.iterrows():
            df_m = load_jugades_db(p['match_id'])
            if df_m.empty: continue
            teams_m = get_teams_ordered(df_m)
            if len(teams_m) < 2: continue
            col_j_m = "jugador" if "jugador" in df_m.columns else "jugadora"
            df_m = df_m.copy()
            df_m["jugador"] = df_m[col_j_m].fillna("")
            if jug not in df_m["jugador"].values: continue

            # idEquip és un identificador intern PER PARTIT (no estable entre partits),
            # cal resoldre'l fresc a cada partit en lloc de reutilitzar-lo de l'agregat.
            eq_id_m = str(df_m[df_m["jugador"]==jug]["idEquip"].iloc[0])
            split = calc_onoff_bloc_split(df_m, jug, [top_companya], eq_id_m, teams_m)
            if split is None: continue
            for k in acum_amb:   acum_amb[k]   += split["amb_bloc"][k]
            for k in acum_sense: acum_sense[k] += split["sense_bloc"][k]

        def net(a):
            return round(100*(a["pts"]-a["pts_riv"])/a["poss"], 1) if a["poss"] > 0 else None

        net_amb, net_sense = net(acum_amb), net(acum_sense)
        fiable_amb   = acum_amb["poss"]   >= min_poss_seg
        fiable_sense = acum_sense["poss"] >= min_poss_seg

        if net_amb is not None and net_sense is not None and fiable_amb and fiable_sense:
            diferencia = abs(net_amb - net_sense)
            if diferencia <= 5 and not info["context_concentrat"]:
                semafor = "🟢 Mèrit individual"
            elif diferencia <= 10:
                semafor = "🟡 Context parcial"
            else:
                semafor = "🔴 Molt lligat al context"
        elif info["context_concentrat"]:
            semafor = "🟡 Context concentrat (dades insuf. per segmentar)"
        else:
            semafor = "⚪ Dades insuficients"

        resultats.append({
            **info,
            "net_amb_bloc": net_amb, "net_sense_bloc": net_sense,
            "poss_amb_bloc": round(acum_amb["poss"], 1), "poss_sense_bloc": round(acum_sense["poss"], 1),
            "fiabilitat_context": semafor,
        })
    return resultats

def calc_onoff_ts(df_orig, jugadora, equip_id, teams):
    """Calcula el TS% de l'EQUIP quan la jugadora és ON vs OFF (intervals reals)."""
    MINS_Q = 10
    MIN_TC = 4  # mínim de tirs intentats per considerar el TS% fiable

    col_j = "jugador" if "jugador" in df_orig.columns else "jugadora"

    intervals_on = []; en_pista = {}
    df_jug_rows = df_orig[df_orig[col_j]==jugadora]
    if df_jug_rows.empty: return None

    primer = df_jug_rows.sort_values("num").iloc[0]
    if "Surt" in str(primer.get("accio","")) and "camp" in str(primer.get("accio","")):
        en_pista[jugadora] = (int(primer.get("quart",1))-1)*MINS_Q

    for _,row in df_orig.sort_values("num").iterrows():
        if str(row.get(col_j,"")) != str(jugadora): continue
        acc = str(row.get("accio","")); q = int(row.get("quart",1))
        m = float(row.get("min_num",0))
        t = (q-1)*MINS_Q + (MINS_Q-m if m<=MINS_Q else m)
        t = max(0, min(t, q*MINS_Q))
        if "Entra" in acc and "camp" in acc:
            en_pista[jugadora] = t
        elif "Surt" in acc and "camp" in acc:
            ti = en_pista.pop(jugadora, (q-1)*MINS_Q)
            if t > ti: intervals_on.append((float(ti), float(t)))
        elif "Final de període" in acc:
            if jugadora in en_pista:
                ti = en_pista.pop(jugadora)
                fi = float(q*MINS_Q)
                if fi > ti: intervals_on.append((float(ti), fi))
    for ti_o in en_pista.values():
        fi_o = float(df_orig["quart"].max()*MINS_Q)
        if fi_o > ti_o: intervals_on.append((float(ti_o), fi_o))

    if not intervals_on: return None

    df_t = df_orig.copy()
    df_t["t_abs"] = df_t.apply(
        lambda r: (int(r["quart"])-1)*10+(10-float(r["min_num"]))
        if float(r.get("min_num",0))<=10 else float(r.get("min_num",0)), axis=1)

    mask_on = df_t["t_abs"].apply(lambda t: any(ti<=t<=tf for ti,tf in intervals_on))

    df_on_eq  = df_t[mask_on  & (df_t["idEquip"]==equip_id)]
    df_off_eq = df_t[~mask_on & (df_t["idEquip"]==equip_id)]

    def ts_pct(df_e):
        pts = int(df_e["punts"].sum())
        tc_int = int(df_e["accio"].str.contains(
            "Cistella de 2|Cistella de 3|Intent fallat de 2|Intent fallat de 3|"
            "Tir de 2|Tir de 3|fallat de 2|fallat de 3",
            case=False, na=False).sum())
        tl_int = int(df_e["accio"].str.contains(
            "Cistella de 1|Intent fallat de 1", case=False, na=False).sum())
        denom = 2 * (tc_int + 0.44*tl_int)
        if tc_int < MIN_TC:
            return None, tc_int, pts
        ts = round(pts/denom*100, 1) if denom > 0 else 0
        return ts, tc_int, pts

    ts_on, tc_on, pts_on = ts_pct(df_on_eq)
    ts_off, tc_off, pts_off = ts_pct(df_off_eq)

    diff_ts = round(ts_on - ts_off, 1) if (ts_on is not None and ts_off is not None) else None

    return {
        "ts_on": ts_on, "ts_off": ts_off, "diff_ts": diff_ts,
        "tc_on": tc_on, "tc_off": tc_off,
        "pts_on": pts_on, "pts_off": pts_off,
    }

def calc_lineup_impact(df_orig, jugadores_on, jugadores_off, equip_id, teams, quart_ini=None, quart_fi=None):
    """Generalitza calc_onoff() a un lineup de diverses jugadores.
    jugadores_on = han d'estar TOTES a pista; jugadores_off = cap d'elles pot ser-hi.
    Reutilitza el patró de microintervals de calc_pm_combinacions()/get_intervals_jugadores_global()."""
    rival_id = next((t for t in teams if t != equip_id), None)
    if rival_id is None: return None

    MINS_Q = 10
    MIN_POSS = 4
    intervals_jug = get_intervals_jugadores_global(df_orig)
    jugs_eq = [j for j, ivs in intervals_jug.items() if ivs and str(ivs[0][2]) == str(equip_id)]
    if not jugs_eq: return None

    df_t = df_orig.copy()
    df_t["t_abs"] = df_t.apply(
        lambda r: (int(r["quart"])-1)*10+(10-float(r["min_num"]))
        if float(r.get("min_num",0))<=10 else float(r.get("min_num",0)), axis=1)

    t_min_range = float((quart_ini-1)*MINS_Q) if quart_ini else 0.0
    t_max_range = float(quart_fi*MINS_Q) if quart_fi else float(df_orig["quart"].max()*MINS_Q)

    canvis = {round(t_min_range,2), round(t_max_range,2)}
    for j in jugs_eq:
        for ti, tf, _ in intervals_jug[j]:
            if tf > t_min_range and ti < t_max_range:
                canvis.add(round(max(ti, t_min_range),2))
                canvis.add(round(min(tf, t_max_range),2))
    canvis = sorted(canvis)

    lineup_intervals, resta_intervals = [], []
    for i in range(len(canvis)-1):
        t0, t1 = canvis[i], canvis[i+1]
        if t1 - t0 < 0.01: continue
        tm = (t0+t1)/2
        en_pista_ara = [j for j in jugs_eq
                        if any(ti <= tm < tf for ti,tf,_ in intervals_jug[j])]
        if len(en_pista_ara) != 5: continue
        compleix = all(j in en_pista_ara for j in jugadores_on) and \
                   not any(j in en_pista_ara for j in jugadores_off)
        (lineup_intervals if compleix else resta_intervals).append((t0, t1))

    def bucket_rtg(intervals):
        if not intervals:
            return {"minuts": 0.0, "off_rtg": None, "def_rtg": None, "net_rtg": None,
                     "pts_of": 0, "pts_def": 0, "poss_of": 0.0, "poss_def": 0.0}
        mask = df_t["t_abs"].apply(lambda t: any(ti <= t < tf for ti,tf in intervals))
        df_eq  = df_t[mask & (df_t["idEquip"]==equip_id)]
        df_riv = df_t[mask & (df_t["idEquip"]==rival_id)]
        mins_tot = round(sum(tf-ti for ti,tf in intervals), 1)
        pts_of  = int(df_eq["punts"].sum())
        pts_def = int(df_riv["punts"].sum())
        poss_of  = calc_possessions(df_eq)
        poss_def = calc_possessions(df_riv)
        off_rtg = round(pts_of/poss_of*100, 1) if poss_of >= MIN_POSS else None
        def_rtg = round(pts_def/poss_def*100, 1) if poss_def >= MIN_POSS else None
        net_rtg = round(off_rtg - def_rtg, 1) if (off_rtg is not None and def_rtg is not None) else None
        return {"minuts": mins_tot, "off_rtg": off_rtg, "def_rtg": def_rtg, "net_rtg": net_rtg,
                "pts_of": pts_of, "pts_def": pts_def, "poss_of": round(poss_of,1), "poss_def": round(poss_def,1)}

    return {"lineup": bucket_rtg(lineup_intervals), "resta": bucket_rtg(resta_intervals)}

def calc_metriques_partit(df_jug, match_id, nom_equip, nom_rival):
    """Calcula totes les mètriques avançades d'un equip en un partit."""
    pts_tot = int(df_jug["punts"].sum())
    pts_2   = int(df_jug["accio"].str.contains("Cistella de 2",case=False,na=False).sum()) * 2
    pts_3   = int(df_jug["accio"].str.contains("Cistella de 3",case=False,na=False).sum()) * 3
    pts_tl  = int(df_jug["accio"].str.contains("Cistella de 1",case=False,na=False).sum())
    tc_conv = int(df_jug["accio"].str.contains("Cistella de 2|Cistella de 3",case=False,na=False).sum())
    tc_fall = int(df_jug["accio"].str.contains("Intent fallat de 2|Intent fallat de 3|fallat de 2|fallat de 3",case=False,na=False).sum())
    tc_int  = tc_conv + tc_fall
    tl_conv = pts_tl
    tl_int  = tl_conv + int(df_jug["accio"].str.contains("Intent fallat de 1",case=False,na=False).sum())
    c3_conv = int(df_jug["accio"].str.contains("Cistella de 3",case=False,na=False).sum())
    c3_int  = c3_conv + int(df_jug["accio"].str.contains("Intent fallat de 3|fallat de 3",case=False,na=False).sum())
    c2_conv = int(df_jug["accio"].str.contains("Cistella de 2",case=False,na=False).sum())
    c2_int  = c2_conv + int(df_jug["accio"].str.contains("Intent fallat de 2|fallat de 2",case=False,na=False).sum())

    poss     = calc_possessions(df_jug)
    ts_denom = 2 * (tc_int + 0.44 * tl_int)
    return {
        "Equip":        nom_equip,
        "Rival":        nom_rival,
        "Pts":          pts_tot,
        "Pts 2pts":     pts_2,
        "Pts 3pts":     pts_3,
        "Pts TL":       pts_tl,
        "Possessions":  round(poss, 1),
        "Pts/Poss":     round(pts_tot / poss, 3) if poss > 0 else 0,
        "Off Rtg":      round(pts_tot / poss * 100, 1) if poss > 0 else 0,
        "TS%":          round(pts_tot / ts_denom * 100, 1) if ts_denom > 0 else 0,
        "TC%":          round(tc_conv / tc_int * 100, 1) if tc_int > 0 else 0,
        "eFG%":         round((tc_conv + 0.5 * c3_conv) / tc_int * 100, 1) if tc_int > 0 else 0,
        "FTAr":         round(tl_int / tc_int * 100, 1) if tc_int > 0 else 0,
        "2pts%":        round(c2_conv / c2_int * 100, 1) if c2_int > 0 else 0,
        "3pts%":        round(c3_conv / c3_int * 100, 1) if c3_int > 0 else 0,
        "TL%":          round(tl_conv / tl_int * 100, 1) if tl_int > 0 else 0,
        "%Pts 2pts":    round(pts_2 / pts_tot * 100, 1) if pts_tot > 0 else 0,
        "%Pts 3pts":    round(pts_3 / pts_tot * 100, 1) if pts_tot > 0 else 0,
        "%Pts TL":      round(pts_tl / pts_tot * 100, 1) if pts_tot > 0 else 0,
        "2pts conv/int": f"{c2_conv}/{c2_int}",
        "3pts conv/int": f"{c3_conv}/{c3_int}",
        "TL conv/int":   f"{tl_conv}/{tl_int}",
        # Detall complet per cistella
        "1pt conv":     tl_conv,
        "1pt int":      tl_int,
        "1pt%":         round(tl_conv / tl_int * 100, 1) if tl_int > 0 else 0,
        "2pts conv":    c2_conv,
        "2pts int":     c2_int,
        "2pts% ef":     round(c2_conv / c2_int * 100, 1) if c2_int > 0 else 0,
        "3pts conv":    c3_conv,
        "3pts int":     c3_int,
        "3pts% ef":     round(c3_conv / c3_int * 100, 1) if c3_int > 0 else 0,
    }


# ══════════════════════════════════════════════════
# ARQUETIPS, ZONES DE TIR, WIN SHARES
# ══════════════════════════════════════════════════
def classifica_arquetip_global(usage, p2, p3, ptl, min_p):
    """Classifica una jugadora en un arquetip simplificat (versió global, usada per UI i Excel)."""
    if usage >= 25:
        if p3 >= 35: return "🎯 Anotadora exterior (alt ús)"
        elif p2 >= 55: return "💪 Anotadora interior (alt ús)"
        else: return "⚡ Motor ofensiu"
    elif usage >= 15:
        if p3 >= 35: return "🏹 Especialista de triple"
        elif p2 >= 55: return "🏀 Anotadora interior (rol)"
        elif ptl >= 30: return "🎁 Generadora de contacte"
        else: return "⚖️ Anotadora equilibrada"
    else:
        if min_p >= 15: return "🛡️ Rol defensiu/suport"
        else: return "🔄 Rol secundari"

def classifica_zona_tir(x_raw, y_raw):
    """Classifica un tir en una de 7 zones segons les coordenades x,y.
    x: 0-100% (eix horitzontal, cistella a x≈48-50%)
    y: ~11-100% (eix vertical, y baix = a prop de la cistella)
    """
    if y_raw <= 28 and 30 <= x_raw <= 70:
        return "🎯 Zona pintada"
    es_triple = (y_raw >= 58) or (y_raw >= 35 and (x_raw <= 18 or x_raw >= 82))
    if es_triple:
        if x_raw < 38: return "🏹 Triple esquerra"
        elif x_raw > 62: return "🏹 Triple dreta"
        else: return "🏹 Triple centre"
    else:
        if x_raw < 38: return "📍 Mig esquerra"
        elif x_raw > 62: return "📍 Mig dreta"
        else: return "📍 Mig centre"

TC_INT_PAT = "Cistella de 2|Cistella de 3|Intent fallat de 2|Intent fallat de 3|fallat de 2|fallat de 3"
TL_INT_PAT = "Cistella de 1|Intent fallat de 1|Tir lliure convertit|Tir lliure fallat"

def calc_win_shares_temporada():
    """Win Shares ofensius aproximats per jugadora, acumulats de tots els partits
    de la BD (play-by-play complet, taula `jugades`). Versió simplificada: sense
    assists ni rebots ofensius (no disponibles), i amb DWS estimat com a 30% de l'OWS
    perquè no tenim Def Rating individual (calen possessions defensives per jugadora).
    Retorna DataFrame: jugador, idEquip, equip, partits, minuts, punts, OWS, DWS, WS,
    ws_per40, p2_pct, p3_pct, ptl_pct, min_p, Arquetip. Buit si no hi ha prou dades.
    """
    con = sqlite3.connect(DB_PATH)
    try:
        df_all = pd.read_sql("SELECT * FROM jugades", con).rename(
            columns={"id_equip": "idEquip", "team_action": "teamAction"})
        df_p = pd.read_sql("SELECT * FROM partits", con)
    finally:
        con.close()
    if df_all.empty or df_p.empty:
        return pd.DataFrame()

    col_j = "jugador" if "jugador" in df_all.columns else "jugadora"
    df_all[col_j] = df_all[col_j].fillna("")
    df_all["idEquip"] = df_all["idEquip"].astype(str)
    df_all["match_id"] = df_all["match_id"].astype(str)

    team_name_per_match = {}
    for _, p in df_p.iterrows():
        team_name_per_match[str(p["match_id"])] = {
            str(p["id_equip_a"]): p["nom_a"], str(p["id_equip_b"]): p["nom_b"]}

    # ── Referència de lliga: possessions i punts per equip i partit ──
    ep_rows = []
    minuts_per_jugmatch = {}
    for match_id, dfm in df_all.groupby("match_id"):
        intervals_m = get_intervals_jugadores_global(dfm)
        for jug, ivs in intervals_m.items():
            minuts_per_jugmatch[(jug, match_id)] = sum(tf - ti for ti, tf, _ in ivs)
        for eq_id, dfe in dfm.groupby("idEquip"):
            tc = int(dfe["accio"].str.contains(TC_INT_PAT, case=False, na=False).sum())
            tl = int(dfe["accio"].str.contains(TL_INT_PAT, case=False, na=False).sum())
            ep_rows.append({"match_id": match_id, "idEquip": eq_id,
                             "poss": tc + 0.44 * tl, "pts": int(dfe["punts"].sum())})

    df_ep = pd.DataFrame(ep_rows)
    if df_ep.empty or df_ep["poss"].sum() == 0:
        return pd.DataFrame()

    pts_per_poss_lliga = df_ep["pts"].sum() / df_ep["poss"].sum()
    pts_per_partit_equip = df_ep.groupby("idEquip")["pts"].mean().to_dict()

    rows = []
    for jug, dj in df_all.groupby(col_j):
        if not jug or str(jug) in ("", "nan"): continue
        eq_id = str(dj["idEquip"].iloc[0])
        match_ids_jug = dj["match_id"].unique().tolist()
        punts_jug = int(dj["punts"].sum())
        tc_jug = int(dj["accio"].str.contains(TC_INT_PAT, case=False, na=False).sum())
        tl_jug = int(dj["accio"].str.contains(TL_INT_PAT, case=False, na=False).sum())
        poss_jug = tc_jug + 0.44 * tl_jug

        marginal_off = punts_jug - 0.92 * pts_per_poss_lliga * poss_jug
        pts_partit_eq = pts_per_partit_equip.get(eq_id) or max(punts_jug, 1)
        pts_per_win = 0.32 * pts_partit_eq
        ows = max(0.0, marginal_off / pts_per_win) if pts_per_win > 0 else 0.0
        dws = ows * 0.3  # proxy simple: no tenim Def Rating individual
        ws = ows + dws

        minuts_jug = sum(minuts_per_jugmatch.get((jug, mid), 0.0) for mid in match_ids_jug)
        ws_per40 = (ws / minuts_jug * 40) if minuts_jug > 0 else 0.0

        equip_nom = team_name_per_match.get(match_ids_jug[0], {}).get(eq_id, "?")

        rows.append({
            "jugador": jug, "idEquip": eq_id, "equip": equip_nom,
            "partits": len(match_ids_jug), "minuts": round(minuts_jug, 1),
            "punts": punts_jug, "OWS": round(ows, 2), "DWS": round(dws, 2),
            "WS": round(ws, 2), "ws_per40": round(ws_per40, 2),
        })

    df_ws = pd.DataFrame(rows)
    if df_ws.empty:
        return df_ws

    # Distribució de punts i Usage% (per l'Arquetip), reutilitzant exactament el
    # mateix criteri i les mateixes dades que la resta de l'app (usage_rate ja es
    # calcula "on-court" partit a partit a save_stats_jugador/calc_usage_rate).
    df_sj = load_stats_jugador_db()
    if not df_sj.empty:
        col_j_sj = "jugador" if "jugador" in df_sj.columns else "jugadora"
        agg_sj = df_sj.groupby(col_j_sj).agg(
            c2=("cistelles_2", "sum"), c3=("cistelles_3", "sum"), tl=("tirs_lliures", "sum"),
            usage=("usage_rate", "mean") if "usage_rate" in df_sj.columns else ("punts", "mean"),
        ).reset_index().rename(columns={col_j_sj: "jugador"})
        agg_sj["pts_tot"] = (agg_sj["c2"] * 2 + agg_sj["c3"] * 3 + agg_sj["tl"]).replace(0, 1)
        agg_sj["p2_pct"] = (agg_sj["c2"] * 2 / agg_sj["pts_tot"] * 100).round(1)
        agg_sj["p3_pct"] = (agg_sj["c3"] * 3 / agg_sj["pts_tot"] * 100).round(1)
        agg_sj["ptl_pct"] = (agg_sj["tl"] / agg_sj["pts_tot"] * 100).round(1)
        # calc_usage_rate() ja retorna un percentatge (p.ex. 24.4 = 24.4%), no cal tornar a multiplicar per 100
        agg_sj["usage_pct"] = agg_sj["usage"].round(1) if "usage_rate" in df_sj.columns else 0
        df_ws = df_ws.merge(agg_sj[["jugador", "p2_pct", "p3_pct", "ptl_pct", "usage_pct"]], on="jugador", how="left").fillna(0)
    else:
        df_ws["p2_pct"] = 0; df_ws["p3_pct"] = 0; df_ws["ptl_pct"] = 0; df_ws["usage_pct"] = 0

    df_ws["min_p"] = (df_ws["minuts"] / df_ws["partits"].replace(0, 1)).round(1)
    df_ws["Arquetip"] = df_ws.apply(
        lambda r: classifica_arquetip_global(r["usage_pct"], r["p2_pct"], r["p3_pct"], r["ptl_pct"], r["min_p"]),
        axis=1)
    return df_ws
