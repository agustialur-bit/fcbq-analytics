import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import urllib.request
import json, re, sqlite3, os
from datetime import datetime

st.set_page_config(page_title="FCBQ Analítica", page_icon="🏀", layout="wide", initial_sidebar_state="expanded")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historic.db")
API_BASE = "https://msstats.optimalwayconsulting.com/v1/fcbq/getJsonWithMatchMoves/{match_id}?currentSeason=true"
WEB_BASE = "https://www.basquetcatala.cat/estadistiques/2025/{match_id}"
COLOR_A, COLOR_B = "#185FA5", "#993C1D"

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif;}
.stApp{background:#f4f5f7;color:#1a1c22;}
div[data-testid="stSidebar"]{background:#ffffff;border-right:1px solid #e2e4e8;}
.stTabs [data-baseweb="tab-list"]{background:#ffffff;border-radius:8px;padding:4px;gap:2px;border:0.5px solid #e2e4e8;}
.stTabs [data-baseweb="tab"]{border-radius:6px;font-size:13px;font-weight:500;color:#6b7280;}
.stTabs [aria-selected="true"]{background:#185FA5!important;color:#fff!important;}
.stButton button{background:#185FA5!important;color:#fff!important;border:none!important;border-radius:8px!important;font-weight:500!important;font-size:13px!important;}
div[data-testid="stDataFrame"]{border-radius:8px;overflow:hidden;border:0.5px solid #e2e4e8;}
.stSelectbox>div>div{border-radius:8px!important;}
.stMultiSelect>div>div{border-radius:8px!important;}
.stTextInput>div>div{border-radius:8px!important;}
.stExpander{border:0.5px solid #e2e4e8!important;border-radius:8px!important;}
</style>
""", unsafe_allow_html=True)

def card(label, value, sub="", color="#185FA5"):
    return f"""<div style="background:#fff;border:0.5px solid #e2e4e8;border-radius:10px;padding:14px 16px;text-align:center;margin-bottom:8px">
    <div style="font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#9ca3af;margin-bottom:4px">{label}</div>
    <div style="font-size:28px;font-weight:600;color:{color};line-height:1.1">{value}</div>
    <div style="font-size:11px;color:#9ca3af;margin-top:3px">{sub}</div></div>"""

def sec(s):
    return f'<div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#6b7280;border-left:3px solid #185FA5;padding-left:8px;margin:24px 0 10px;border-radius:0">{s}</div>'

def badge(text, color, bg):
    return f'<span style="background:{bg};color:{color};font-size:10px;font-weight:600;padding:2px 7px;border-radius:20px;letter-spacing:.04em">{text}</span>'

def chart_style(fig, h=280, title=""):
    if title:
        fig.update_layout(title=dict(text=title, font=dict(color="#374151", size=13, family="Inter"), x=0))
    fig.update_layout(
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        font=dict(color="#374151", family="Inter", size=12),
        legend=dict(bgcolor="#ffffff", bordercolor="#e2e4e8", borderwidth=1, title="",
                    orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(showgrid=False, color="#9ca3af", linecolor="#e2e4e8"),
        yaxis=dict(showgrid=True, gridcolor="#f3f4f6", color="#9ca3af", linecolor="#e2e4e8"),
        margin=dict(l=0, r=0, t=40 if title else 10, b=0), height=h)
    return fig

def eff_color(p):
    if p >= 55: return "#16a34a"
    if p >= 35: return "#d97706"
    return "#dc2626"

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
# Migració automàtica: afegir columnes noves si no existeixen
def migrate_db():
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("ALTER TABLE stats_jugador ADD COLUMN minuts REAL DEFAULT 0")
        con.commit()
    except:
        pass  # La columna ja existeix
    con.close()

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
    CREATE TABLE IF NOT EXISTS equips (
        id_equip TEXT PRIMARY KEY, nom TEXT
    );
    """)
    con.commit(); con.close()

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
    for _, m in df.iterrows():
        nom = m.get("jugador","")
        if not nom or str(nom) in ("","nan"): continue
        idmove_str = str(m.get("accio",""))
        min_ = float(m.get("min_num", 0))
        # Reconstruïm minut absolut: min_num ja és minut dins del quart
        quart = int(m.get("quart", 1)) if m.get("quart","") != "" else 1
        t = (quart - 1) * MINS_PER_QUART + min_

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

    # Tanca intervals oberts
    for nom, p in players.items():
        if p["entrada"] is not None:
            p["intervals"].append((p["entrada"], p["entrada"] + MINS_PER_QUART))

    minuts = {}
    for nom, p in players.items():
        total = sum(fi - ini for ini, fi in p["intervals"])
        minuts[nom] = round(total, 1)
    return minuts

def save_stats_jugador(match_id, data_consulta, df, teams, team_names):
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM stats_jugador WHERE match_id=?", (match_id,))
    minuts_reals = calc_minuts_reals(df)
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
        n_min,n_max = dj["num"].min(),dj["num"].max()
        dr = df[(df["num"]>=n_min)&(df["num"]<=n_max)]
        rival = [t for t in teams if t!=eq_id]
        pf = int(dr[dr["idEquip"]==eq_id]["punts"].sum())
        pc = int(dr[dr["idEquip"]==rival[0]]["punts"].sum()) if rival else 0
        impacte = pf-pc
        min_jug = minuts_reals.get(jug, 0)
        pts_min = round(punts/min_jug, 2) if min_jug > 0 else 0.0
        rows.append((match_id,data_consulta,jug,eq_nom,punts,cist2,cist3,tl,faltes,accions,impacte,pts_min))
    # Afegir minuts a cada row
    rows_amb_min = [r + (minuts_reals.get(r[2], 0),) for r in rows]
    con.executemany("INSERT INTO stats_jugador (match_id,data_consulta,jugador,equip_nom,punts,cistelles_2,cistelles_3,tirs_lliures,faltes,accions,impacte,pts_per_min,minuts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows_amb_min)
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

def delete_partit_db(match_id):
    con = sqlite3.connect(DB_PATH)
    for tbl in ["partits","jugades","stats_jugador","shots_zones"]:
        con.execute(f"DELETE FROM {tbl} WHERE match_id=?", (match_id,))
    con.commit(); con.close()

init_db()

# Migració automàtica: afegir columnes noves si no existeixen a BD antigues
def migrate_db():
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("ALTER TABLE stats_jugador ADD COLUMN minuts REAL DEFAULT 0")
        con.commit()
    except Exception:
        pass
    con.close()

migrate_db()

# ══════════════════════════════════════════════════
# FETCH
# ══════════════════════════════════════════════════
def extract_match_id(text):
    m = re.search(r"/([a-f0-9]{24})(?:\?|$)", text)
    if m: return m.group(1)
    if re.match(r"^[a-f0-9]{24}$", text.strip()): return text.strip()
    return None

def fetch_and_parse(match_id):
    url = API_BASE.format(match_id=match_id)
    req = urllib.request.Request(url, headers={
        "User-Agent":"Mozilla/5.0","Accept":"application/json",
        "Referer":WEB_BASE.format(match_id=match_id)})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    if isinstance(data, list): data = {"moves": data}
    raw = data.get("moves") or data.get("matchMoves") or data.get("playByPlay") or []
    if not raw:
        for v in data.values():
            if isinstance(v,list) and len(v)>3: raw=v; break
    rows = []
    for i,play in enumerate(raw):
        if not isinstance(play,dict): continue
        mn=play.get("min",""); sc=play.get("sec","")
        temps=f"{int(mn):02d}:{int(sc):02d}" if mn!="" and sc!="" else str(mn)
        move=play.get("move","")
        punts=3 if "Cistella de 3" in move else (2 if "Cistella de 2" in move else (1 if ("Cistella de 1" in move or "Tir lliure convertit" in move) else 0))
        rows.append({"num":i+1,"quart":play.get("period",""),"temps":temps,
            "min_num":float(mn)+float(sc)/60 if mn!="" else 0,
            "idEquip":str(play.get("idTeam","")),"dorsal":play.get("actorShirtNumber",""),
            "jugador":play.get("actorName",""),"accio":move,
            "marcador":play.get("score",""),"punts":punts,
            "teamAction":play.get("teamAction",False)})
    return pd.DataFrame(rows)

# ══════════════════════════════════════════════════
# HELPERS
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
                rows.append({"num":r["num"],"quart":r["quart"],"temps":r["temps"],"scoreA":sa,"scoreB":sb,"diff":sa-sb})
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
# SIDEBAR
# ══════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""<div style="display:flex;align-items:center;gap:10px;padding-bottom:14px;border-bottom:0.5px solid #e2e4e8;margin-bottom:14px">
        <div style="width:34px;height:34px;background:#E6F1FB;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:18px">🏀</div>
        <div><div style="font-size:13px;font-weight:600;color:#1a1c22">FCBQ Analítica</div>
        <div style="font-size:11px;color:#9ca3af">Bàsquet Català</div></div></div>""", unsafe_allow_html=True)

    st.markdown('<div style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#9ca3af;margin-bottom:6px">Partit</div>', unsafe_allow_html=True)
    url_input = st.text_input("", placeholder="URL o ID del partit", label_visibility="collapsed")

    with st.expander("✏️ Noms dels equips", expanded=False):
        st.caption("Es guardaran per a futurs partits.")
        nom_equip_1 = st.text_input("Equip local", placeholder="Ex: CB Manresa")
        nom_equip_2 = st.text_input("Equip visitant", placeholder="Ex: Joventut")

    carregar = st.button("⬇ Carregar partit", use_container_width=True)
    st.markdown("---")
    st.markdown('<div style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#9ca3af;margin-bottom:6px">Filtres play-by-play</div>', unsafe_allow_html=True)
    quart_sel = st.multiselect("Quart", options=[1,2,3,4], default=[1,2,3,4])
    accio_cerca = st.text_input("Acció", placeholder="Cistella, falta...")
    jugador_cerca = st.text_input("Jugadora", placeholder="Nom...")
    st.markdown("---")
    st.caption("Federació Catalana de Basquetbol")

# ── Sessió ─────────────────────────────────────────────────────────────────────
for k,v in [("df",None),("match_id",None),("team_names",{}),("score_a",0),("score_b",0)]:
    if k not in st.session_state: st.session_state[k]=v

# ── Càrrega ────────────────────────────────────────────────────────────────────
if carregar and url_input:
    mid = extract_match_id(url_input)
    if not mid:
        st.error("ID no vàlid.")
    elif partit_exists(mid):
        st.session_state.df = load_jugades_db(mid)
        st.session_state.match_id = mid
        df_part = load_partits_db()
        row = df_part[df_part["match_id"]==mid]
        if not row.empty:
            t_list = get_teams(st.session_state.df)
            noms = {}
            if len(t_list)>=1: noms[t_list[0]] = row.iloc[0]["nom_a"]
            if len(t_list)>=2: noms[t_list[1]] = row.iloc[0]["nom_b"]
            st.session_state.team_names = noms
            # Guardem els scores de la BD per mostrar-los correctament
            st.session_state.score_a = int(row.iloc[0]["score_a"])
            st.session_state.score_b = int(row.iloc[0]["score_b"])
        st.success("Carregat des de l'històric ⚡")
    else:
        with st.spinner("Descarregant de l'API..."):
            try:
                df = fetch_and_parse(mid)
                teams_tmp = get_teams_ordered(df)
                noms_guardats = load_noms_equips()
                def get_nom(i, tid, input_nom):
                    if input_nom and input_nom.strip():
                        save_nom_equip(tid, input_nom.strip()); return input_nom.strip()
                    if tid in noms_guardats: return noms_guardats[tid]
                    return f"Equip {chr(65+i)}"
                noms = {}
                inputs = [nom_equip_1, nom_equip_2]
                for i,tid in enumerate(teams_tmp[:2]):
                    noms[tid] = get_nom(i, tid, inputs[i] if i<len(inputs) else "")
                id_a = teams_tmp[0] if teams_tmp else ""
                id_b = teams_tmp[1] if len(teams_tmp)>1 else ""
                sdf = score_evo(df); fa,fb = final_score(sdf)
                ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                save_partit(mid, df, noms.get(id_a,"A"), noms.get(id_b,"B"), id_a, id_b, fa, fb)
                save_stats_jugador(mid, ts, df, teams_tmp, noms)
                save_shots_zones(mid, ts, df, noms)
                st.session_state.df = df
                st.session_state.match_id = mid
                st.session_state.team_names = noms
                st.session_state.score_a = fa
                st.session_state.score_b = fb
                st.success("Carregat i desat ✅")
            except Exception as e:
                st.error(f"Error: {e}")

# ── Pantalla inicial ────────────────────────────────────────────────────────────
if st.session_state.df is None:
    st.markdown("""<div style="text-align:center;padding:80px 0">
        <div style="font-size:64px">🏀</div>
        <h1 style="font-size:38px;font-weight:600;color:#1a1c22;margin:16px 0 8px">FCBQ Analítica</h1>
        <p style="color:#6b7280;font-size:15px">Enganxa la URL o l'ID d'un partit al panell esquerre i prem Carregar.</p>
        <p style="color:#d1d5db;font-size:12px;margin-top:32px">Exemple: 69ec95d4339c3d0001f523a1</p>
    </div>""", unsafe_allow_html=True)
    st.stop()

# ── Variables globals del partit carregat ─────────────────────────────────────
df_orig = st.session_state.df.copy()
match_id = st.session_state.match_id
teams = get_teams_ordered(df_orig)
team_names = st.session_state.team_names
nom_a = team_names.get(teams[0],"Equip A") if teams else "Equip A"
nom_b = team_names.get(teams[1],"Equip B") if len(teams)>1 else "Equip B"
color_map_eq = {nom_a:COLOR_A, nom_b:COLOR_B}
df_orig["equip_nom"] = df_orig["idEquip"].map(team_names).fillna("?")
score_df = score_evo(df_orig)
# Usa els scores guardats si existeixen, sinó calcula del marcador
if st.session_state.score_a or st.session_state.score_b:
    fa, fb = st.session_state.score_a, st.session_state.score_b
else:
    fa, fb = final_score(score_df)

# ══════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════
t1,t2,t3,t4,t5,t6 = st.tabs([
    "🏀 Partit","👤 Jugadores","⏱ Ritme","📚 Històric","📈 Hist. Jugadores","🎯 Mapa de Tir"
])

# ══════════════════════════════════════════════════
# TAB 1: PARTIT
# ══════════════════════════════════════════════════
with t1:
    # Marcador
    # Parcials per quart: suma directa de punts del play-by-play per equip i quart
    def parcial_quart(tid, q):
        if not tid: return 0
        return int(df_orig[(df_orig["idEquip"]==tid) & (df_orig["quart"]==q)]["punts"].sum())

    # Resultat final: suma de tots els quarts
    def total_punts(tid):
        if not tid: return 0
        return int(df_orig[df_orig["idEquip"]==tid]["punts"].sum())

    # Recalculem fa/fb des del play-by-play (més fiable que el marcador de l'API)
    qs = sorted(df_orig["quart"].unique())
    # Resultat final = suma dels parcials de cada quart
    fa = sum(parcial_quart(teams[0] if teams else None, q) for q in qs)
    fb = sum(parcial_quart(teams[1] if len(teams)>1 else None, q) for q in qs)
    guanya_a = fa > fb
    guanya_b = fb > fa

    ca,cm,cb = st.columns([5,1,5])
    with ca:
        badge_a = '<div style="background:#E6F1FB;color:#0C447C;font-size:10px;font-weight:600;padding:3px 8px;border-radius:20px;display:inline-block;margin-bottom:8px">VICTÒRIA</div>' if guanya_a else ""
        border_a = f"2px solid {COLOR_A}" if guanya_a else "0.5px solid #e2e4e8"
        parc_a = " · ".join([f"Q{q}: {parcial_quart(teams[0] if teams else None, q)}" for q in qs])
        html_a = (
            f'<div style="background:#fff;border:{border_a};border-radius:16px;padding:24px 20px;text-align:center">'
            f'{badge_a}'
            f'<div style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:{COLOR_A};margin-bottom:8px">{nom_a}</div>'
            f'<div style="font-size:88px;font-weight:600;color:{COLOR_A};line-height:1">{fa}</div>'
            f'<div style="font-size:11px;color:#9ca3af;margin:6px 0">Local</div>'
            f'<div style="border-top:0.5px solid #f3f4f6;padding-top:8px;font-size:12px;color:{COLOR_A};opacity:.7">{parc_a}</div>'
            f'</div>'
        )
        st.markdown(html_a, unsafe_allow_html=True)
    with cm:
        st.markdown(
            f'<div style="text-align:center;padding-top:52px;font-size:20px;color:#d1d5db">vs</div>'
            f'<div style="text-align:center;margin-top:6px;font-size:10px;color:#d1d5db">{match_id[:8]}...</div>',
            unsafe_allow_html=True)
    with cb:
        badge_b = '<div style="background:#FAECE7;color:#712B13;font-size:10px;font-weight:600;padding:3px 8px;border-radius:20px;display:inline-block;margin-bottom:8px">VICTÒRIA</div>' if guanya_b else ""
        border_b = f"2px solid {COLOR_B}" if guanya_b else "0.5px solid #e2e4e8"
        parc_b = " · ".join([f"Q{q}: {parcial_quart(teams[1] if len(teams)>1 else None, q)}" for q in qs])
        html_b = (
            f'<div style="background:#fff;border:{border_b};border-radius:16px;padding:24px 20px;text-align:center">'
            f'{badge_b}'
            f'<div style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:{COLOR_B};margin-bottom:8px">{nom_b}</div>'
            f'<div style="font-size:88px;font-weight:600;color:{COLOR_B};line-height:1">{fb}</div>'
            f'<div style="font-size:11px;color:#9ca3af;margin:6px 0">Visitant</div>'
            f'<div style="border-top:0.5px solid #f3f4f6;padding-top:8px;font-size:12px;color:{COLOR_B};opacity:.7">{parc_b}</div>'
            f'</div>'
        )
        st.markdown(html_b, unsafe_allow_html=True)

    # Mètriques
    st.markdown(sec("Resum del partit"), unsafe_allow_html=True)
    # Resultat final directament del marcador de l'API
    try: pts_a = int(fa)
    except: pts_a = 0
    try: pts_b = int(fb)
    except: pts_b = 0
    faltes_a=int(df_orig[(df_orig["idEquip"]==teams[0])&df_orig["accio"].str.contains("falta",case=False,na=False)].shape[0]) if teams else 0
    faltes_b=int(df_orig[(df_orig["idEquip"]==teams[1])&df_orig["accio"].str.contains("falta",case=False,na=False)].shape[0]) if len(teams)>1 else 0
    c1,c2,c3,c4,c5,c6=st.columns(6)
    for col,lab,val,sub,col_ in zip([c1,c2,c3,c4,c5,c6],
        ["Jugades","Punts","Punts","Faltes","Faltes","Quarts"],
        [len(df_orig),pts_a,pts_b,faltes_a,faltes_b,df_orig["quart"].nunique()],
        ["total",nom_a,nom_b,nom_a,nom_b,"períodes"],
        ["#374151",COLOR_A,COLOR_B,COLOR_A,COLOR_B,"#374151"]):
        with col: st.markdown(card(lab,val,sub,col_),unsafe_allow_html=True)

    # Evolució marcador
    st.markdown(sec("Evolució del marcador"), unsafe_allow_html=True)
    if not score_df.empty:
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=score_df["num"],y=score_df["scoreA"],name=nom_a,
            line=dict(color=COLOR_A,width=2.5),fill="tozeroy",fillcolor="rgba(24,95,165,0.07)"))
        fig.add_trace(go.Scatter(x=score_df["num"],y=score_df["scoreB"],name=nom_b,
            line=dict(color=COLOR_B,width=2.5),fill="tozeroy",fillcolor="rgba(153,60,29,0.07)"))
        for q in score_df["quart"].unique():
            fq=score_df[score_df["quart"]==q]["num"].min()
            if fq>1: fig.add_vline(x=fq,line_dash="dot",line_color="#e2e4e8",
                annotation_text=f"Q{q}",annotation_font_color="#9ca3af",annotation_font_size=10)
        fig.update_xaxes(title="Jugada"); fig.update_yaxes(title="Punts")
        fig.update_layout(
            legend=dict(orientation="h", yanchor="bottom", y=1.02,
                        xanchor="right", x=1, bgcolor="rgba(0,0,0,0)",
                        font=dict(size=12)))
        st.plotly_chart(chart_style(fig,300),use_container_width=True)

    # Punts per quart
    st.markdown(sec("Punts per quart"), unsafe_allow_html=True)
    pq=df_orig.groupby(["quart","equip_nom"])["punts"].sum().reset_index()
    if not pq.empty and pq["punts"].sum()>0:
        # Reconstruïm el mapa de colors a partir dels idEquip reals
        cmap = {}
        if teams: cmap[team_names.get(teams[0], nom_a)] = COLOR_A
        if len(teams)>1: cmap[team_names.get(teams[1], nom_b)] = COLOR_B
        fig2=px.bar(pq,x="quart",y="punts",color="equip_nom",barmode="group",
            color_discrete_map=cmap,labels={"quart":"Quart","punts":"Punts","equip_nom":"Equip"})
        st.plotly_chart(chart_style(fig2,240),use_container_width=True)

    # Mapa de calor minuts
    st.markdown(sec("En quins minuts marca cada equip?"), unsafe_allow_html=True)
    df_cist=df_orig[df_orig["punts"]>0].copy()
    df_cist["min_quart"]=df_cist["min_num"].apply(lambda x: int(x%10) if x>0 else 0)
    tab_ha,tab_hb=st.tabs([nom_a,nom_b])
    for htab,tid,ch in [(tab_ha,teams[0] if teams else None,COLOR_A),
                        (tab_hb,teams[1] if len(teams)>1 else None,COLOR_B)]:
        with htab:
            if tid is None: continue
            de=df_cist[df_cist["idEquip"]==tid]
            if de.empty: st.info("Sense cistelles."); continue
            hd=de.groupby(["quart","min_quart"])["punts"].sum().reset_index()
            piv=hd.pivot(index="quart",columns="min_quart",values="punts").fillna(0)
            fh=go.Figure(go.Heatmap(z=piv.values,x=[f"min {c}" for c in piv.columns],
                y=[f"Q{q}" for q in piv.index],colorscale=[[0,"#f9fafb"],[1,ch]],
                text=piv.values.astype(int),texttemplate="%{text}",
                hovertemplate="Q%{y} min%{x}: %{z}pts<extra></extra>"))
            fh.update_layout(paper_bgcolor="#fff",plot_bgcolor="#fff",
                font=dict(color="#374151",family="Inter"),margin=dict(l=0,r=0,t=10,b=0),height=200)
            st.plotly_chart(fh,use_container_width=True)

    # Play-by-Play
    st.markdown(sec("Play-by-Play"), unsafe_allow_html=True)
    df_f=df_orig.copy()
    if quart_sel: df_f=df_f[df_f["quart"].isin(quart_sel)]
    if accio_cerca: df_f=df_f[df_f["accio"].str.contains(accio_cerca,case=False,na=False)]
    if jugador_cerca: df_f=df_f[df_f["jugador"].str.contains(jugador_cerca,case=False,na=False)]
    st.caption(f"{len(df_f)} jugades")
    # Afegir badge d'equip a la taula
    def fmt_equip(eq):
        if eq==nom_a: return f"● {nom_a}"
        if eq==nom_b: return f"● {nom_b}"
        return eq
    # Play-by-play com taula HTML (única manera de renderitzar badges de color)
    rows_html = []
    for _,r in df_f.iterrows():
        eq = r["equip_nom"]
        if eq == nom_a:
            bdg = f'<span style="background:#E6F1FB;color:#0C447C;font-size:10px;font-weight:600;padding:2px 7px;border-radius:20px;white-space:nowrap">{nom_a[:4].upper()}</span>'
        elif eq == nom_b:
            bdg = f'<span style="background:#FAECE7;color:#712B13;font-size:10px;font-weight:600;padding:2px 7px;border-radius:20px;white-space:nowrap">{nom_b[:4].upper()}</span>'
        else:
            bdg = ""
        rows_html.append(
            f'<tr style="border-bottom:0.5px solid #f3f4f6">'
            f'<td style="padding:5px 8px;color:#9ca3af;font-size:11px;text-align:right">{int(r["num"])}</td>'
            f'<td style="padding:5px 4px;color:#9ca3af;font-size:11px;text-align:center">{r["quart"]}</td>'
            f'<td style="padding:5px 8px;color:#6b7280;font-size:11px;font-variant-numeric:tabular-nums">{r["temps"]}</td>'
            f'<td style="padding:5px 8px">{bdg}</td>'
            f'<td style="padding:5px 4px;color:#9ca3af;font-size:11px;text-align:center">{r["dorsal"]}</td>'
            f'<td style="padding:5px 8px;color:#374151;font-size:12px;font-weight:500">{r["jugador"]}</td>'
            f'<td style="padding:5px 8px;color:#374151;font-size:12px">{r["accio"]}</td>'
            f'<td style="padding:5px 8px;color:#6b7280;font-size:11px;font-variant-numeric:tabular-nums;text-align:right">{r["marcador"]}</td>'
            f'</tr>'
        )
    table_html = (
        '<div style="background:#fff;border:0.5px solid #e2e4e8;border-radius:10px;overflow:auto;max-height:400px">'
        '<table style="width:100%;border-collapse:collapse">'
        '<thead><tr style="border-bottom:1px solid #e2e4e8;background:#f9fafb;position:sticky;top:0">'
        '<th style="padding:6px 8px;font-size:10px;color:#9ca3af;font-weight:600;text-align:right;white-space:nowrap">#</th>'
        '<th style="padding:6px 4px;font-size:10px;color:#9ca3af;font-weight:600;text-align:center">Q</th>'
        '<th style="padding:6px 8px;font-size:10px;color:#9ca3af;font-weight:600">Temps</th>'
        '<th style="padding:6px 8px;font-size:10px;color:#9ca3af;font-weight:600">Equip</th>'
        '<th style="padding:6px 4px;font-size:10px;color:#9ca3af;font-weight:600;text-align:center">D</th>'
        '<th style="padding:6px 8px;font-size:10px;color:#9ca3af;font-weight:600">Jugadora</th>'
        '<th style="padding:6px 8px;font-size:10px;color:#9ca3af;font-weight:600">Acció</th>'
        '<th style="padding:6px 8px;font-size:10px;color:#9ca3af;font-weight:600;text-align:right">Marc</th>'
        '</tr></thead>'
        '<tbody>' + "".join(rows_html) + '</tbody>'
        '</table></div>'
    )
    st.markdown(table_html, unsafe_allow_html=True)
    csv_data=df_f[["num","quart","temps","idEquip","equip_nom","dorsal","jugador","accio","marcador","punts"]].to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Descarregar CSV",csv_data,f"pbp_{match_id}.csv","text/csv")

# ══════════════════════════════════════════════════
# TAB 2: JUGADORES
# ══════════════════════════════════════════════════
with t2:
    st.markdown(sec("Punts per jugadora i quart"), unsafe_allow_html=True)
    stats_per=df_orig.groupby(["equip_nom","jugador","quart"]).agg(
        Punts=("punts","sum"),Accions=("accio","count"),
        Cistelles=("accio",lambda x: x.str.contains("Cistella",case=False,na=False).sum()),
        Faltes=("accio",lambda x: x.str.contains("falta",case=False,na=False).sum()),
    ).reset_index()
    tab_pa,tab_pb=st.tabs([nom_a,nom_b])
    for ptab,pnom,ph in [(tab_pa,nom_a,COLOR_A),(tab_pb,nom_b,COLOR_B)]:
        with ptab:
            dfe=stats_per[stats_per["equip_nom"]==pnom]
            if dfe.empty: st.info("Sense dades."); continue
            piv_p=dfe.pivot_table(index="jugador",columns="quart",values="Punts",aggfunc="sum",fill_value=0)
            piv_p["TOTAL"]=piv_p.sum(axis=1)
            piv_p=piv_p.sort_values("TOTAL",ascending=False)
            piv_p.columns=[f"Q{c}" if c!="TOTAL" else "TOTAL" for c in piv_p.columns]
            cols_q=[c for c in piv_p.columns if c!="TOTAL"]
            fig_hp=go.Figure(go.Heatmap(z=piv_p[cols_q].values,x=cols_q,y=piv_p.index.tolist(),
                colorscale=[[0,"#f9fafb"],[1,ph]],
                text=piv_p[cols_q].values.astype(int),texttemplate="%{text}",
                hovertemplate="%{y} — %{x}: %{z}pts<extra></extra>"))
            fig_hp.update_layout(paper_bgcolor="#fff",plot_bgcolor="#fff",
                font=dict(color="#374151",family="Inter"),
                margin=dict(l=0,r=0,t=10,b=0),height=max(180,36*len(piv_p)))
            st.plotly_chart(fig_hp,use_container_width=True)
            st.dataframe(piv_p,use_container_width=True)

    st.markdown(sec("Impacte en pista"), unsafe_allow_html=True)
    st.caption("Parcial de l'equip entre la primera i última acció de la jugadora.")
    imp_rows=[]
    for jug in df_orig["jugador"].unique():
        if not jug: continue
        dj=df_orig[df_orig["jugador"]==jug]
        eq_id=dj["idEquip"].iloc[0]; eq_nom=dj["equip_nom"].iloc[0]
        n_min,n_max=dj["num"].min(),dj["num"].max()
        dr=df_orig[(df_orig["num"]>=n_min)&(df_orig["num"]<=n_max)]
        rival=[t for t in teams if t!=eq_id]
        pf=int(dr[dr["idEquip"]==eq_id]["punts"].sum())
        pc=int(dr[dr["idEquip"]==rival[0]]["punts"].sum()) if rival else 0
        imp_rows.append({"Equip":eq_nom,"Jugadora":jug,"Pts favor":pf,"Pts contra":pc,
            "Parcial":f"+{pf-pc}" if pf>=pc else str(pf-pc),"_diff":pf-pc})
    df_imp=pd.DataFrame(imp_rows).sort_values("_diff",ascending=False).drop(columns="_diff")
    t_ia,t_ib=st.tabs([nom_a,nom_b])
    for it,in_nom in [(t_ia,nom_a),(t_ib,nom_b)]:
        with it:
            di=df_imp[df_imp["Equip"]==in_nom].drop(columns="Equip")
            st.dataframe(di,use_container_width=True,hide_index=True)

    st.markdown(sec("Combinació de jugadores"), unsafe_allow_html=True)
    eq_combo=st.selectbox("Equip",[nom_a,nom_b],key="combo_eq")
    eq_id_combo=teams[0] if eq_combo==nom_a else (teams[1] if len(teams)>1 else None)
    if eq_id_combo:
        jugs_eq=sorted(df_orig[df_orig["idEquip"]==eq_id_combo]["jugador"].unique().tolist())
        jugs_sel=st.multiselect("Selecciona 2–5 jugadores",jugs_eq,max_selections=5,key="combo_jugs")
        if len(jugs_sel)>=2:
            mask_c=df_orig["jugador"].isin(jugs_sel)&(df_orig["idEquip"]==eq_id_combo)
            df_c=df_orig[mask_c]; n1,n2=df_c["num"].min(),df_c["num"].max()
            dr=df_orig[(df_orig["num"]>=n1)&(df_orig["num"]<=n2)]
            rival_c=[t for t in teams if t!=eq_id_combo]
            pf_c=int(dr[dr["idEquip"]==eq_id_combo]["punts"].sum())
            pc_c=int(dr[dr["idEquip"]==rival_c[0]]["punts"].sum()) if rival_c else 0
            diff_c=pf_c-pc_c; cr="#16a34a" if diff_c>=0 else "#dc2626"
            rt="GUANYEN" if diff_c>0 else ("EMPATEN" if diff_c==0 else "PERDEN")
            c1,c2,c3,c4=st.columns(4)
            with c1: st.markdown(card("Parcial favor",pf_c,"","#16a34a"),unsafe_allow_html=True)
            with c2: st.markdown(card("Parcial contra",pc_c,"","#dc2626"),unsafe_allow_html=True)
            with c3: st.markdown(card("Diferència",f"{'+'if diff_c>=0 else ''}{diff_c}","",cr),unsafe_allow_html=True)
            with c4: st.markdown(card("Resultat",rt,"",cr),unsafe_allow_html=True)
        elif len(jugs_sel)==1: st.info("Selecciona almenys 2 jugadores.")

    st.markdown(sec("Jugadora: puntua quan guanya o perd?"), unsafe_allow_html=True)
    tots_jugs=sorted(df_orig["jugador"].unique().tolist())
    jug_sel=st.selectbox("Jugadora",tots_jugs,key="jug_analisi")
    if jug_sel:
        dj2=df_orig[df_orig["jugador"]==jug_sel].copy()
        dj2["estat"]=dj2.apply(lambda r: estat_marc(r,teams),axis=1)
        res2=dj2.groupby("estat").agg(Punts=("punts","sum"),Accions=("accio","count"),
            Cistelles=("accio",lambda x: x.str.contains("Cistella",case=False,na=False).sum())
        ).reindex(["Guanyant","Empatat","Perdent"]).fillna(0).astype(int)
        ec={"Guanyant":"#16a34a","Empatat":"#d97706","Perdent":"#dc2626"}
        ei={"Guanyant":"📈","Empatat":"➡️","Perdent":"📉"}
        cg,ce,cp=st.columns(3)
        for col,estat in zip([cg,ce,cp],["Guanyant","Empatat","Perdent"]):
            with col:
                pts=int(res2.loc[estat,"Punts"]) if estat in res2.index else 0
                acc=int(res2.loc[estat,"Accions"]) if estat in res2.index else 0
                cis=int(res2.loc[estat,"Cistelles"]) if estat in res2.index else 0
                st.markdown(card(f"{ei[estat]} {estat}",pts,f"{acc} acc · {cis} cist",ec[estat]),unsafe_allow_html=True)
        if res2["Punts"].sum()>0:
            fig_j=px.bar(res2.reset_index().rename(columns={"estat":"Estat"}),
                x="Estat",y="Punts",color="Estat",color_discrete_map=ec,text="Punts")
            fig_j.update_traces(textposition="outside")
            st.plotly_chart(chart_style(fig_j,240),use_container_width=True)
        with st.expander("Detall cistelles"):
            dj2_pts=dj2[dj2["punts"]>0][["quart","temps","accio","marcador","punts","estat"]]
            st.dataframe(dj2_pts.rename(columns={"quart":"Q","temps":"Temps","accio":"Acció",
                "marcador":"Marc","punts":"Pts","estat":"Estat"}),use_container_width=True,hide_index=True)

# ══════════════════════════════════════════════════
# TAB 3: RITME
# ══════════════════════════════════════════════════
with t3:
    st.markdown(sec("Temps entre cistelles"), unsafe_allow_html=True)
    df_cist2=df_orig[df_orig["punts"]>0].sort_values("num").copy()
    for tid,tnom,tc in [(teams[0] if teams else None,nom_a,COLOR_A),
                        (teams[1] if len(teams)>1 else None,nom_b,COLOR_B)]:
        if tid is None: continue
        dc=df_cist2[df_cist2["idEquip"]==tid].copy()
        if len(dc)<2: continue
        dc["seg_entre"]=((dc["min_num"].shift(-1)-dc["min_num"])*60).abs()
        dc=dc.dropna(subset=["seg_entre"]); dc=dc[dc["seg_entre"]<600]
        mit=dc["seg_entre"].mean(); med=dc["seg_entre"].median()
        c1,c2,c3=st.columns(3)
        with c1: st.markdown(card(f"{tnom} — Mitjana",f"{mit:.0f}s","",tc),unsafe_allow_html=True)
        with c2: st.markdown(card("Mediana",f"{med:.0f}s","",tc),unsafe_allow_html=True)
        with c3: st.markdown(card("Cistelles",len(dc),"",tc),unsafe_allow_html=True)
        fig_t=px.histogram(dc,x="seg_entre",nbins=20,color_discrete_sequence=[tc],
            labels={"seg_entre":"Segons"})
        st.plotly_chart(chart_style(fig_t,200,f"{tnom} — temps entre cistelles"),use_container_width=True)

    st.markdown(sec("Ritme de puntuació (pts/min)"), unsafe_allow_html=True)
    ritme_rows=[]
    for q in sorted(df_orig["quart"].unique()):
        for tid,tnom in [(teams[0] if teams else None,nom_a),(teams[1] if len(teams)>1 else None,nom_b)]:
            if tid is None: continue
            pts_q=df_orig[(df_orig["quart"]==q)&(df_orig["idEquip"]==tid)]["punts"].sum()
            ritme_rows.append({"Quart":f"Q{q}","Equip":tnom,"Pts/min":round(pts_q/10,2)})
    df_ritme=pd.DataFrame(ritme_rows)
    if not df_ritme.empty:
        fig_r=px.line(df_ritme,x="Quart",y="Pts/min",color="Equip",
            color_discrete_map={nom_a:COLOR_A,nom_b:COLOR_B},markers=True)
        st.plotly_chart(chart_style(fig_r,260,"Ritme per quart"),use_container_width=True)

    st.markdown(sec("Eficiència ofensiva per quart"), unsafe_allow_html=True)
    ef_rows=[]
    for q in sorted(df_orig["quart"].unique()):
        for tid,tnom in [(teams[0] if teams else None,nom_a),(teams[1] if len(teams)>1 else None,nom_b)]:
            if tid is None: continue
            dq=df_orig[(df_orig["quart"]==q)&(df_orig["idEquip"]==tid)]
            cist=dq["accio"].str.contains("Cistella",case=False,na=False).sum()
            fall=dq["accio"].str.contains("Tir|fallit|fallat",case=False,na=False).sum()
            tot=cist+fall
            ef=round(cist/tot*100,1) if tot>0 else 0
            ef_rows.append({"Quart":f"Q{q}","Equip":tnom,"Eficiència %":ef})
    df_ef=pd.DataFrame(ef_rows)
    if not df_ef.empty:
        fig_ef=px.bar(df_ef,x="Quart",y="Eficiència %",color="Equip",barmode="group",
            color_discrete_map={nom_a:COLOR_A,nom_b:COLOR_B},text="Eficiència %")
        fig_ef.update_traces(texttemplate="%{text}%",textposition="outside")
        st.plotly_chart(chart_style(fig_ef,260,"% Eficiència per quart"),use_container_width=True)

    st.markdown(sec("Momentum shifts"), unsafe_allow_html=True)
    st.caption("Runs de 5+ punts consecutius sense resposta del rival.")
    THRESHOLD=5; shift_rows=[]
    if not score_df.empty:
        prev_diff,run_team,run_pts,run_start=0,None,0,None
        for _,row in score_df.iterrows():
            diff=row["diff"]; delta=diff-prev_diff
            cur=(teams[0] if teams else None) if delta>0 else ((teams[1] if len(teams)>1 else None) if delta<0 else None)
            if cur and cur==run_team: run_pts+=abs(delta)
            else:
                if run_pts>=THRESHOLD and run_team:
                    shift_rows.append({"Equip":team_names.get(run_team,"?"),
                        "Jugada inici":run_start,"Jugada fi":row["num"],
                        "Parcial":f"+{run_pts}","Temps":row["temps"],"Quart":row["quart"]})
                run_team,run_pts,run_start=cur,abs(delta),row["num"]
            prev_diff=diff
    if shift_rows:
        df_sh=pd.DataFrame(shift_rows)
        st.dataframe(df_sh,use_container_width=True,hide_index=True)
    else:
        st.info(f"No s'han detectat runs de {THRESHOLD}+ punts.")

# ══════════════════════════════════════════════════
# TAB 4: HISTÒRIC PARTITS
# ══════════════════════════════════════════════════
with t4:
    st.markdown(sec("Partits consultats"), unsafe_allow_html=True)
    df_hist=load_partits_db()
    if df_hist.empty:
        st.info("Encara no hi ha partits. Carrega un partit per començar.")
    else:
        df_hs=df_hist.copy()
        df_hs["Resultat"]=df_hs.apply(lambda r: f"{r['score_a']}–{r['score_b']}",axis=1)
        st.dataframe(df_hs[["data_consulta","nom_a","Resultat","nom_b","total_jugades","match_id"]].rename(
            columns={"data_consulta":"Data","nom_a":"Local","nom_b":"Visitant",
                     "total_jugades":"Jugades","match_id":"ID"}),
            use_container_width=True,hide_index=True)

        st.markdown(sec("Carregar un partit de l'històric"), unsafe_allow_html=True)
        ids_hist=df_hist["match_id"].tolist()
        sel_hist=st.selectbox("Selecciona",ids_hist,
            format_func=lambda x: f"{df_hist[df_hist['match_id']==x]['nom_a'].values[0]} vs {df_hist[df_hist['match_id']==x]['nom_b'].values[0]}",
            key="sel_hist")
        if st.button("📂 Carregar",key="load_hist"):
            df_loaded=load_jugades_db(sel_hist)
            st.session_state.df=df_loaded
            st.session_state.match_id=sel_hist
            row=df_hist[df_hist["match_id"]==sel_hist].iloc[0]
            t_list=get_teams(df_loaded)
            noms={}
            if len(t_list)>=1: noms[t_list[0]]=row["nom_a"]
            if len(t_list)>=2: noms[t_list[1]]=row["nom_b"]
            st.session_state.team_names=noms
            st.session_state.score_a = int(row["score_a"])
            st.session_state.score_b = int(row["score_b"])
            st.success("Carregat! Ves a 🏀 Partit."); st.rerun()

        col_del1, col_del2 = st.columns([2,1])
        with col_del1:
            del_id=st.selectbox("Eliminar un partit",ids_hist,
                format_func=lambda x: f"{df_hist[df_hist['match_id']==x]['nom_a'].values[0]} vs {df_hist[df_hist['match_id']==x]['nom_b'].values[0]}",
                key="del_hist")
        with col_del2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("🗑 Eliminar",key="btn_del"):
                delete_partit_db(del_id); st.success("Eliminat."); st.rerun()

        if len(df_hist)>1:
            st.markdown(sec("Evolució de resultats"), unsafe_allow_html=True)
            rows_comp=[]
            for _,rh in df_hist.iterrows():
                lbl=f"{rh['nom_a']} vs {rh['nom_b']} ({rh['data_consulta'][:10]})"
                rows_comp.append({"Partit":lbl,"Equip":rh["nom_a"],"Punts":rh["score_a"]})
                rows_comp.append({"Partit":lbl,"Equip":rh["nom_b"],"Punts":rh["score_b"]})
            fig_comp=px.line(pd.DataFrame(rows_comp),x="Partit",y="Punts",color="Equip",markers=True)
            fig_comp.update_xaxes(tickangle=-30)
            st.plotly_chart(chart_style(fig_comp,280),use_container_width=True)

# ══════════════════════════════════════════════════
# TAB 5: HISTÒRIC JUGADORES
# ══════════════════════════════════════════════════
with t5:
    st.markdown(sec("Rànquing acumulat"), unsafe_allow_html=True)
    df_sj=load_stats_jugador_db()
    if df_sj.empty:
        st.info("Carrega partits per generar l'històric de jugadores.")
    else:
        df_pr=load_partits_db()
        def label_p(mid):
            r=df_pr[df_pr["match_id"]==mid]
            if r.empty: return mid[:10]+"..."
            return f"{r.iloc[0]['nom_a']} vs {r.iloc[0]['nom_b']} ({r.iloc[0]['data_consulta'][:10]})"
        df_sj["Partit"]=df_sj["match_id"].apply(label_p)
        df_sj["Data"]=df_sj["data_consulta"]

        ranking=df_sj.groupby(["jugador","equip_nom"]).agg(
            Partits=("match_id","nunique"),Punts=("punts","sum"),
            C2=("cistelles_2","sum"),C3=("cistelles_3","sum"),
            TL=("tirs_lliures","sum"),Faltes=("faltes","sum"),Impacte=("impacte","sum"),
        ).reset_index()
        ranking["Pts/p"]=(ranking["Punts"]/ranking["Partits"]).round(1)
        ranking["Imp/p"]=(ranking["Impacte"]/ranking["Partits"]).round(1)
        ranking=ranking.sort_values("Punts",ascending=False).rename(columns={"jugador":"Jugadora","equip_nom":"Equip"})

        equips_hist=["Tots"]+sorted(df_sj["equip_nom"].unique().tolist())
        eq_rank=st.selectbox("Filtra per equip",equips_hist,key="eq_rank")
        df_rk=ranking if eq_rank=="Tots" else ranking[ranking["Equip"]==eq_rank]
        # Afegir minuts totals si existeix la columna
        cols_rank = ["Jugadora","Equip","Partits","Punts","Pts/p","C2","C3","TL","Faltes","Impacte","Imp/p"]
        if "minuts" in ranking.columns:
            ranking["Min/p"] = (ranking.get("minuts",0) / ranking["Partits"]).round(1)
            cols_rank = ["Jugadora","Equip","Partits","Punts","Pts/p","C2","C3","TL","Faltes","Min/p","Impacte","Imp/p"]
        st.dataframe(df_rk[cols_rank],
            use_container_width=True,hide_index=True)

        top5=df_rk.head(5)
        if not top5.empty:
            fig_rank=px.bar(top5,x="Jugadora",y="Punts",color="Equip",
                color_discrete_map=dict(zip(df_sj["equip_nom"].unique(),[COLOR_A,COLOR_B])),
                text="Punts")
            fig_rank.update_traces(textposition="outside")
            st.plotly_chart(chart_style(fig_rank,240,"Top 5 anotadores acumulades"),use_container_width=True)

        st.markdown(sec("Evolució d'una jugadora per partit"), unsafe_allow_html=True)
        tots_jugs_hist=sorted(df_sj["jugador"].unique().tolist())
        jug_hist=st.selectbox("Selecciona jugadora",tots_jugs_hist,key="jug_hist")
        if jug_hist:
            df_jh=df_sj[df_sj["jugador"]==jug_hist].sort_values("Data")
            if df_jh.empty:
                st.info("Sense dades.")
            else:
                c1,c2,c3,c4=st.columns(4)
                with c1: st.markdown(card("Partits",len(df_jh),"","#374151"),unsafe_allow_html=True)
                with c2: st.markdown(card("Punts totals",int(df_jh["punts"].sum()),"",COLOR_A),unsafe_allow_html=True)
                with c3: st.markdown(card("Pts/partit",f"{df_jh['punts'].mean():.1f}","mitjana",COLOR_A),unsafe_allow_html=True)
                with c4:
                    imp=int(df_jh["impacte"].sum())
                    ci="#16a34a" if imp>=0 else "#dc2626"
                    st.markdown(card("Impacte total",f"{'+'if imp>=0 else ''}{imp}","acumulat",ci),unsafe_allow_html=True)

                tcol_jug=COLOR_A
                fig_evo=go.Figure()
                fig_evo.add_trace(go.Scatter(x=df_jh["Partit"],y=df_jh["punts"],
                    mode="lines+markers",name="Punts",
                    line=dict(color=tcol_jug,width=2.5),marker=dict(size=8),
                    fill="tozeroy",fillcolor="rgba(24,95,165,0.07)"))
                fig_evo.add_trace(go.Scatter(x=df_jh["Partit"],y=df_jh["punts"].expanding().mean(),
                    mode="lines",name="Mitjana",line=dict(color="#d97706",width=2,dash="dot")))
                fig_evo.update_xaxes(tickangle=-30)
                st.plotly_chart(chart_style(fig_evo,280,f"{jug_hist} — punts per partit"),use_container_width=True)

                ci_list=["#16a34a" if v>=0 else "#dc2626" for v in df_jh["impacte"]]
                fig_imp=go.Figure()
                fig_imp.add_trace(go.Scatter(x=df_jh["Partit"],y=df_jh["impacte"],
                    mode="lines+markers",name="Impacte",
                    line=dict(color="#6366f1",width=2.5),
                    marker=dict(size=9,color=ci_list,line=dict(width=1,color="#fff"))))
                fig_imp.add_hline(y=0,line_dash="solid",line_color="#e2e4e8")
                fig_imp.update_xaxes(tickangle=-30)
                st.plotly_chart(chart_style(fig_imp,240,f"{jug_hist} — impacte per partit"),use_container_width=True)

                fig_cist=go.Figure()
                fig_cist.add_trace(go.Scatter(x=df_jh["Partit"],y=df_jh["cistelles_2"],
                    mode="lines+markers",name="C2",line=dict(color=COLOR_A,width=2),marker=dict(size=7)))
                fig_cist.add_trace(go.Scatter(x=df_jh["Partit"],y=df_jh["cistelles_3"],
                    mode="lines+markers",name="C3",line=dict(color="#16a34a",width=2),marker=dict(size=7)))
                fig_cist.add_trace(go.Scatter(x=df_jh["Partit"],y=df_jh["tirs_lliures"],
                    mode="lines+markers",name="TL",line=dict(color="#d97706",width=2,dash="dot"),marker=dict(size=7)))
                fig_cist.update_xaxes(tickangle=-30)
                st.plotly_chart(chart_style(fig_cist,240,f"{jug_hist} — tipus cistelles per partit"),use_container_width=True)

                with st.expander("Taula completa"):
                    st.dataframe(df_jh[["Partit","punts","cistelles_2","cistelles_3","tirs_lliures","faltes","impacte","pts_per_min"]].rename(
                        columns={"punts":"Pts","cistelles_2":"C2","cistelles_3":"C3","tirs_lliures":"TL",
                                 "faltes":"Faltes","impacte":"Impacte","pts_per_min":"Pts/min"}),
                        use_container_width=True,hide_index=True)

        st.markdown(sec("Comparativa entre jugadores"), unsafe_allow_html=True)
        col_j,col_m=st.columns([2,1])
        with col_j:
            jugs_comp=st.multiselect("Jugadores (màx 4)",tots_jugs_hist,max_selections=4,key="jugs_comp")
        with col_m:
            metrica_comp=st.selectbox("Mètrica",
                ["punts","impacte","cistelles_2","cistelles_3","faltes","pts_per_min"],
                format_func=lambda x: {"punts":"Punts","impacte":"Impacte","cistelles_2":"C2",
                    "cistelles_3":"C3","faltes":"Faltes","pts_per_min":"Pts/min"}[x],
                key="metrica_comp")
        if len(jugs_comp)>=2:
            df_comp2=df_sj[df_sj["jugador"].isin(jugs_comp)].sort_values("Data")
            fig_comp2=px.line(df_comp2,x="Partit",y=metrica_comp,color="jugador",markers=True,
                labels={"jugador":"Jugadora"})
            fig_comp2.update_traces(line_width=2,marker_size=7)
            fig_comp2.update_xaxes(tickangle=-30)
            st.plotly_chart(chart_style(fig_comp2,280,f"Evolució per partit: {metrica_comp}"),use_container_width=True)

            mitt=df_comp2.groupby("jugador")[metrica_comp].mean().reset_index()
            mitt.columns=["Jugadora","Mitjana"]
            mitt=mitt.sort_values("Mitjana",ascending=False)
            mitt["Mitjana"]=mitt["Mitjana"].round(2)
            paleta=[COLOR_A,COLOR_B,"#16a34a","#d97706"]
            fig_mit=go.Figure()
            for i,row_m in mitt.iterrows():
                fig_mit.add_trace(go.Bar(x=[row_m["Jugadora"]],y=[row_m["Mitjana"]],
                    name=row_m["Jugadora"],
                    marker_color=paleta[list(mitt["Jugadora"]).index(row_m["Jugadora"])%len(paleta)],
                    text=[f"{row_m['Mitjana']:.2f}"],textposition="outside"))
            fig_mit.update_layout(showlegend=False,barmode="group")
            st.plotly_chart(chart_style(fig_mit,220,f"Mitjana per partit: {metrica_comp}"),use_container_width=True)
            st.dataframe(mitt,use_container_width=True,hide_index=True)

            metr=["punts","cistelles_2","cistelles_3","tirs_lliures","faltes","impacte"]
            labs=["Punts","C2","C3","TL","Faltes","Impacte"]
            fig_rad=go.Figure()
            for i,jug_r in enumerate(jugs_comp):
                dj_r=df_sj[df_sj["jugador"]==jug_r]
                vals=[dj_r[m].mean() for m in metr]
                maxv=[df_sj[m].max() for m in metr]
                norm=[round(v/mx*10,1) if mx>0 else 0 for v,mx in zip(vals,maxv)]
                fig_rad.add_trace(go.Scatterpolar(
                    r=norm+[norm[0]],theta=labs+[labs[0]],
                    fill="toself",name=jug_r,opacity=0.7,
                    line=dict(color=paleta[i%len(paleta)],width=2)))
            fig_rad.update_layout(
                polar=dict(bgcolor="#f9fafb",
                    radialaxis=dict(visible=True,range=[0,10],color="#9ca3af",gridcolor="#e2e4e8"),
                    angularaxis=dict(color="#374151",gridcolor="#e2e4e8")),
                paper_bgcolor="#ffffff",font=dict(color="#374151",family="Inter"),
                legend=dict(bgcolor="#fff",bordercolor="#e2e4e8",borderwidth=1),
                margin=dict(l=40,r=40,t=50,b=40),height=360,
                title=dict(text="Radar de rendiment (0–10 normalitzat)",font=dict(color="#374151",size=13)))
            st.plotly_chart(fig_rad,use_container_width=True)
        elif len(jugs_comp)==1:
            st.info("Selecciona almenys 2 jugadores.")

# ══════════════════════════════════════════════════
# TAB 6: MAPA DE TIR
# ══════════════════════════════════════════════════
with t6:
    st.markdown(sec("Mapa de tir — partit actual"), unsafe_allow_html=True)
    st.caption("Mida del cercle = volum · Color = eficiència: verd >55%, taronja 35–55%, vermell <35%")

    col_ma,col_mb=st.columns(2)
    for col_m,tid,tnom,tcol in [
        (col_ma,teams[0] if teams else None,nom_a,COLOR_A),
        (col_mb,teams[1] if len(teams)>1 else None,nom_b,COLOR_B)
    ]:
        with col_m:
            if tid is None: st.info("Sense dades."); continue
            de=df_orig[df_orig["idEquip"]==tid]
            v1m,v1x,v2m,v2x,v3m,v3x=get_shot_counts(de)
            tot=v1m+v1x+v2m+v2x+v3m+v3x; made=v1m+v2m+v3m
            ef=round(made/tot*100) if tot>0 else 0
            c1,c2,c3=st.columns(3)
            with c1: st.markdown(card("Tirs",tot,"","#374151"),unsafe_allow_html=True)
            with c2: st.markdown(card("Convertits",made,"","#16a34a"),unsafe_allow_html=True)
            with c3: st.markdown(card("Eficiència",f"{ef}%","",tcol),unsafe_allow_html=True)
            svg_html=shot_map_svg([(v1m,v1x),(v2m,v2x),(v3m,v3x)])
            st.markdown(f"""<div style="background:#fff;border:0.5px solid #e2e4e8;border-radius:12px;padding:14px">
                <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:{tcol};margin-bottom:8px">{tnom}</div>
                {svg_html}</div>""",unsafe_allow_html=True)

    st.markdown("""<div style="display:flex;gap:16px;margin-top:8px;flex-wrap:wrap">
        <div style="display:flex;align-items:center;gap:6px;font-size:11px;color:#6b7280"><div style="width:10px;height:10px;border-radius:50%;background:#16a34a"></div>Alta (&gt;55%)</div>
        <div style="display:flex;align-items:center;gap:6px;font-size:11px;color:#6b7280"><div style="width:10px;height:10px;border-radius:50%;background:#d97706"></div>Mitja (35–55%)</div>
        <div style="display:flex;align-items:center;gap:6px;font-size:11px;color:#6b7280"><div style="width:10px;height:10px;border-radius:50%;background:#dc2626"></div>Baixa (&lt;35%)</div>
    </div>""",unsafe_allow_html=True)

    st.markdown(sec("Mapa de tir per jugadora"), unsafe_allow_html=True)
    eq_shot=st.selectbox("Equip",[nom_a,nom_b],key="shot_eq")
    eq_id_shot=teams[0] if eq_shot==nom_a else (teams[1] if len(teams)>1 else None)
    if eq_id_shot:
        jugs_shot=sorted(df_orig[(df_orig["idEquip"]==eq_id_shot)&(df_orig["jugador"]!="")]["jugador"].unique().tolist())
        jug_shot=st.selectbox("Jugadora",jugs_shot,key="shot_jug")
        if jug_shot:
            dj=df_orig[df_orig["jugador"]==jug_shot]
            tcol_s=COLOR_A if eq_shot==nom_a else COLOR_B
            v1m,v1x,v2m,v2x,v3m,v3x=get_shot_counts(dj)
            tot=v1m+v1x+v2m+v2x+v3m+v3x; made=v1m+v2m+v3m
            ef=round(made/tot*100) if tot>0 else 0
            pts_tot=v1m+v2m*2+v3m*3
            c1,c2,c3,c4=st.columns(4)
            with c1: st.markdown(card("Tirs",tot,"",tcol_s),unsafe_allow_html=True)
            with c2: st.markdown(card("Convertits",made,"","#16a34a"),unsafe_allow_html=True)
            with c3: st.markdown(card("Eficiència",f"{ef}%","",tcol_s),unsafe_allow_html=True)
            with c4: st.markdown(card("Punts",pts_tot,"anotats",tcol_s),unsafe_allow_html=True)
            col_js,col_jd=st.columns([1,1])
            with col_js:
                svg_j=shot_map_svg([(v1m,v1x),(v2m,v2x),(v3m,v3x)])
                st.markdown(f"""<div style="background:#fff;border:0.5px solid #e2e4e8;border-radius:12px;padding:14px">
                    <div style="font-size:11px;font-weight:600;color:{tcol_s};margin-bottom:8px">{jug_shot}</div>
                    {svg_j}</div>""",unsafe_allow_html=True)
            with col_jd:
                rows_d=[
                    {"Zona":"Tirs lliures (1pt)","Conv":v1m,"Fall":v1x,"Total":v1m+v1x,
                     "Ef":f"{round(v1m/(v1m+v1x)*100) if (v1m+v1x)>0 else 0}%"},
                    {"Zona":"Tirs de 2pts","Conv":v2m,"Fall":v2x,"Total":v2m+v2x,
                     "Ef":f"{round(v2m/(v2m+v2x)*100) if (v2m+v2x)>0 else 0}%"},
                    {"Zona":"Tirs de 3pts","Conv":v3m,"Fall":v3x,"Total":v3m+v3x,
                     "Ef":f"{round(v3m/(v3m+v3x)*100) if (v3m+v3x)>0 else 0}%"},
                ]
                st.dataframe(pd.DataFrame(rows_d),use_container_width=True,hide_index=True)

    # ── Evolució temporal tirs ──────────────────────────────────────────────
    st.markdown(sec("Evolució de l'eficiència per zona — temporada"), unsafe_allow_html=True)
    st.caption("Línia temporal de l'eficiència de cada zona al llarg dels partits consultats.")
    df_sz=load_shots_zones_db()
    if df_sz.empty:
        st.info("Consulta més partits per veure l'evolució temporal.")
    else:
        df_pr2=load_partits_db()
        def lp(mid):
            r=df_pr2[df_pr2["match_id"]==mid]
            if r.empty: return mid[:8]+"..."
            return f"{r.iloc[0]['nom_a']} vs {r.iloc[0]['nom_b']} ({r.iloc[0]['data_consulta'][:10]})"
        df_sz["Partit"]=df_sz["match_id"].apply(lp)

        tab_eq_sz, tab_jug_sz = st.tabs(["Per equip","Per jugadora"])

        with tab_eq_sz:
            equips_sz=sorted(df_sz[df_sz["jugador"]=="__equip__"]["equip_nom"].unique().tolist())
            eq_sz=st.selectbox("Equip",equips_sz,key="sz_eq") if equips_sz else None
            if eq_sz:
                df_eq_sz=df_sz[(df_sz["equip_nom"]==eq_sz)&(df_sz["jugador"]=="__equip__")].sort_values("data_consulta").copy()
                if not df_eq_sz.empty:
                    df_eq_sz["ef1"]=[round(r.val1_made/(r.val1_made+r.val1_miss)*100) if (r.val1_made+r.val1_miss)>0 else None for _,r in df_eq_sz.iterrows()]
                    df_eq_sz["ef2"]=[round(r.val2_made/(r.val2_made+r.val2_miss)*100) if (r.val2_made+r.val2_miss)>0 else None for _,r in df_eq_sz.iterrows()]
                    df_eq_sz["ef3"]=[round(r.val3_made/(r.val3_made+r.val3_miss)*100) if (r.val3_made+r.val3_miss)>0 else None for _,r in df_eq_sz.iterrows()]
                    fig_sz=go.Figure()
                    for col_ef,label,color_ef in [("ef1","Tirs lliures (1pt)","#6366f1"),("ef2","Tirs de 2pts",COLOR_A),("ef3","Tirs de 3pts","#16a34a")]:
                        fig_sz.add_trace(go.Scatter(x=df_eq_sz["Partit"],y=df_eq_sz[col_ef].tolist(),
                            mode="lines+markers",name=label,line=dict(color=color_ef,width=2.5),
                            marker=dict(size=8,color=color_ef),connectgaps=True))
                    fig_sz.add_hline(y=50,line_dash="dot",line_color="#e2e4e8",
                        annotation_text="50%",annotation_font_color="#9ca3af",annotation_font_size=10)
                    fig_sz.update_layout(yaxis=dict(range=[0,100],ticksuffix="%"))
                    fig_sz.update_xaxes(tickangle=-30)
                    st.plotly_chart(chart_style(fig_sz,300,f"{eq_sz} — eficiència per zona"),use_container_width=True)

        with tab_jug_sz:
            jugs_sz=sorted(df_sz[df_sz["jugador"]!="__equip__"]["jugador"].unique().tolist())
            if jugs_sz:
                jug_sz=st.selectbox("Jugadora",jugs_sz,key="sz_jug")
                if jug_sz:
                    df_jug_sz=df_sz[df_sz["jugador"]==jug_sz].sort_values("data_consulta").copy()
                    if not df_jug_sz.empty:
                        df_jug_sz["ef1"]=[round(r.val1_made/(r.val1_made+r.val1_miss)*100) if (r.val1_made+r.val1_miss)>0 else None for _,r in df_jug_sz.iterrows()]
                        df_jug_sz["ef2"]=[round(r.val2_made/(r.val2_made+r.val2_miss)*100) if (r.val2_made+r.val2_miss)>0 else None for _,r in df_jug_sz.iterrows()]
                        df_jug_sz["ef3"]=[round(r.val3_made/(r.val3_made+r.val3_miss)*100) if (r.val3_made+r.val3_miss)>0 else None for _,r in df_jug_sz.iterrows()]
                        fig_jz=go.Figure()
                        for col_ef,label,color_ef in [("ef1","Tirs lliures (1pt)","#6366f1"),("ef2","Tirs de 2pts",COLOR_A),("ef3","Tirs de 3pts","#16a34a")]:
                            fig_jz.add_trace(go.Scatter(x=df_jug_sz["Partit"],y=df_jug_sz[col_ef].tolist(),
                                mode="lines+markers",name=label,line=dict(color=color_ef,width=2.5),
                                marker=dict(size=8,color=color_ef),connectgaps=True))
                        fig_jz.add_hline(y=50,line_dash="dot",line_color="#e2e4e8",
                            annotation_text="50%",annotation_font_color="#9ca3af",annotation_font_size=10)
                        fig_jz.update_layout(yaxis=dict(range=[0,100],ticksuffix="%"))
                        fig_jz.update_xaxes(tickangle=-30)
                        st.plotly_chart(chart_style(fig_jz,300,f"{jug_sz} — eficiència per zona"),use_container_width=True)
                        with st.expander("Detall per partit"):
                            df_det=df_jug_sz[["Partit","val1_made","val1_miss","ef1","val2_made","val2_miss","ef2","val3_made","val3_miss","ef3"]].copy()
                            df_det.columns=["Partit","1pt Conv","1pt Fall","Ef 1pt%","2pts Conv","2pts Fall","Ef 2pts%","3pts Conv","3pts Fall","Ef 3pts%"]
                            st.dataframe(df_det,use_container_width=True,hide_index=True)
            else:
                st.info("Consulta més partits per veure l'evolució per jugadora.")
