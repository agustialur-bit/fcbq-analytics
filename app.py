import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import urllib.request
import json, re, sqlite3, os
from datetime import datetime

st.set_page_config(page_title="Analítica", page_icon="🏀", layout="wide", initial_sidebar_state="expanded")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historic.db")
API_BASE = "https://msstats.optimalwayconsulting.com/v1/fcbq/getJsonWithMatchMoves/{match_id}?currentSeason=true"
WEB_BASE = "https://www.basquetcatala.cat/estadistiques/2025/{match_id}"
COLOR_A, COLOR_B = "#185FA5", "#993C1D"

import analitica_core as core
from analitica_core import (
    MICKI_CSS, C_BG, C_BG_SOFT, C_BORDER, C_TEXT, C_TEXT_MUTED, C_LABEL,
    C_CARD_BORDER, C_WHITE, C_ACCENT, C_ACCENT_DARK, C_ACCENT_MID, C_CHART_TEXT,
    C_CHART_GRID, C_SUCCESS, C_WARNING, C_ERROR, MINS_PER_QUART, TC_INT_PAT, TL_INT_PAT,
    card, sec, badge, chart_style, eff_color, shot_map_svg,
    init_db, migrate_db, save_nom_equip, load_noms_equips, partit_exists, save_partit,
    calc_minuts_reals, calc_usage_rate, save_stats_jugador, save_shots_zones, save_timeouts,
    save_tirs_fcbq, load_jugades_db, load_partits_db, load_stats_jugador_db,
    load_shots_zones_db, load_timeouts_db, load_tirs_fcbq, delete_partit_db, analyze_timeouts,
    get_teams, get_teams_ordered, score_evo, final_score, estat_marc, get_shot_counts,
    get_intervals_jugadores_global, calc_pm_combinacions, calc_possessions, calc_eficiencies,
    calc_onoff_raw, calc_onoff, calc_onoff_agregat, calc_context_bloc, calc_onoff_bloc_split,
    calc_context_onoff, calc_onoff_ts, calc_lineup_impact, calc_metriques_partit,
    classifica_arquetip_global, classifica_zona_tir, calc_win_shares_temporada,
    genera_excel_analisi, genera_excel_temporada,
)

ZONA_A_CATEGORIA = {
    "🎯 Zona pintada": "Rim",
    "📍 Mig esquerra": "Midrange", "📍 Mig centre": "Midrange", "📍 Mig dreta": "Midrange",
    "🏹 Triple esquerra": "Corner 3", "🏹 Triple dreta": "Corner 3",
    "🏹 Triple centre": "Non-corner 3",
}
CATEGORIA_VALOR = {"Rim": 2, "Midrange": 2, "Corner 3": 3, "Non-corner 3": 3}

def calc_shot_portfolio(df_tirs):
    """Agrupa els tirs (x,y,fet,match_id) en 4 categories (Rim, Midrange, Corner 3,
    Non-corner 3 — aproximació a partir de les 7 zones existents) i calcula per
    categoria: volum (% de tirs), valor (punts per tir) i risc (desviació estàndard
    del PPS entre partits). No inclou continuació per rebot ofensiu (no disponible)."""
    MIN_GAMES = 5  # partits amb tirs a la categoria per considerar el risc fiable

    if df_tirs.empty: return None
    df = df_tirs.copy()
    df["zona"] = df.apply(lambda r: classifica_zona_tir(float(r["x"]), float(r["y"])), axis=1)
    df["categoria"] = df["zona"].map(ZONA_A_CATEGORIA)
    df = df[df["categoria"].notna()]
    if df.empty: return None

    total_tirs = len(df)
    rows = []
    for cat, valor in CATEGORIA_VALOR.items():
        df_cat = df[df["categoria"]==cat]
        n_tirs = len(df_cat)
        if n_tirs == 0:
            rows.append({"categoria":cat,"tirs":0,"volum_pct":0.0,"ef":None,"valor_tir":valor,
                         "pps":None,"risc":None,"n_partits":0,"fiable":False})
            continue
        fets = int(df_cat["fet"].sum())
        ef = round(fets/n_tirs*100, 1)
        pps = round(fets/n_tirs*valor, 2)
        volum_pct = round(n_tirs/total_tirs*100, 1)

        per_partit = df_cat.groupby("match_id").agg(t=("fet","count"), f=("fet","sum"))
        per_partit["pps_p"] = per_partit["f"]/per_partit["t"]*valor
        n_partits = len(per_partit)
        risc = round(per_partit["pps_p"].std(), 2) if n_partits >= 2 else None
        fiable = n_partits >= MIN_GAMES

        rows.append({"categoria":cat,"tirs":n_tirs,"volum_pct":volum_pct,"ef":ef,
                     "valor_tir":valor,"pps":pps,"risc":risc,"n_partits":n_partits,"fiable":fiable})
    return pd.DataFrame(rows)

st.markdown(MICKI_CSS, unsafe_allow_html=True)







core.set_db_path(DB_PATH)
init_db()
migrate_db()

# ── Funcions de temps morts ────────────────────────────────────────────────



# ══════════════════════════════════════════════════
# FETCH
# ══════════════════════════════════════════════════
def extract_match_id(text):
    m = re.search(r"/([a-f0-9]{24})(?:\?|$)", text)
    if m: return m.group(1)
    if re.match(r"^[a-f0-9]{24}$", text.strip()): return text.strip()
    return None

def fetch_and_parse(match_id):
    # Prova amb currentSeason=true i sense (per compatibilitat entre temporades)
    urls_a_provar = [
        API_BASE.format(match_id=match_id),
        API_BASE.format(match_id=match_id).replace("currentSeason=true","currentSeason=false"),
        f"https://msstats.optimalwayconsulting.com/v1/fcbq/getJsonWithMatchMoves/{match_id}",
    ]
    # Referers possibles — prova tots dos formats de URL
    referers = [
        f"https://www.basquetcatala.cat/competicions-anteriors/resultat/estadistiques/2025/{match_id}",
        f"https://www.basquetcatala.cat/estadistiques/2025/{match_id}",
        f"https://www.basquetcatala.cat/estadistiques/2024/{match_id}",
        f"https://www.basquetcatala.cat/",
    ]
    data = None
    for url in urls_a_provar:
        for referer in referers:
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent":"Mozilla/5.0","Accept":"application/json",
                    "Referer": referer})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
                if data: break
            except: continue
        if data: break
    if not data: raise Exception("No s'ha pogut obtenir dades de l'API")

    if isinstance(data, list): data = {"moves": data}
    raw = data.get("moves") or data.get("matchMoves") or data.get("playByPlay") or []
    if not raw:
        for v in data.values():
            if isinstance(v,list) and len(v)>3: raw=v; break

    # Detecta els noms de camps reals del primer element
    camp_equip = "idTeam"
    camp_jugador = "actorName"
    camp_accio = "move"
    camp_dorsal = "actorShirtNumber"
    camp_score = "score"
    camp_period = "period"
    if raw and isinstance(raw[0], dict):
        primer = raw[0]
        # Camp equip
        for c in ["idTeam","teamId","id_team","idEquip","equipId","team_id","idequip"]:
            if c in primer: camp_equip = c; break
        # Camp jugador
        for c in ["actorName","playerName","jugador","actor_name","name","player"]:
            if c in primer: camp_jugador = c; break
        # Camp acció
        for c in ["move","action","accio","moveText","actionText","description"]:
            if c in primer: camp_accio = c; break
        # Camp dorsal
        for c in ["actorShirtNumber","shirtNumber","dorsal","shirt_number","number"]:
            if c in primer: camp_dorsal = c; break
        # Camp marcador
        for c in ["score","marcador","scoreText","currentScore"]:
            if c in primer: camp_score = c; break
        # Camp periode
        for c in ["period","quart","quarter","cuarto"]:
            if c in primer: camp_period = c; break

    rows = []
    for i,play in enumerate(raw):
        if not isinstance(play,dict): continue
        mn=play.get("min",""); sc=play.get("sec","")
        temps=f"{int(mn):02d}:{int(sc):02d}" if mn!="" and sc!="" else str(mn)
        move=play.get(camp_accio,"")
        punts=3 if "Cistella de 3" in move else (2 if "Cistella de 2" in move else (1 if ("Cistella de 1" in move or "Tir lliure convertit" in move) else 0))
        rows.append({"num":i+1,"quart":play.get(camp_period,""),"temps":temps,
            "min_num":float(mn)+float(sc)/60 if mn!="" else 0,
            "idEquip":str(play.get(camp_equip,"")),"dorsal":play.get(camp_dorsal,""),
            "jugador":play.get(camp_jugador,""),"accio":move,
            "marcador":play.get(camp_score,""),"punts":punts,
            "teamAction":play.get("teamAction",False)})
    return pd.DataFrame(rows)

# ══════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════

# ══════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""<div style="display:flex;align-items:center;gap:10px;padding-bottom:14px;border-bottom:0.5px solid #e2e4e8;margin-bottom:14px">
        <div style="width:34px;height:34px;background:#E6F1FB;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:18px">🏀</div>
        <div><div style="font-size:13px;font-weight:600;color:#1a1c22">Analítica</div>
        <div style="font-size:11px;color:#9ca3af">Analítica de Bàsquet</div></div></div>""", unsafe_allow_html=True)

    st.markdown('<div style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#9ca3af;margin-bottom:6px">Partit</div>', unsafe_allow_html=True)
    url_input = st.text_input("", placeholder="URL o ID del partit", label_visibility="collapsed")
    nom_equip_1 = st.text_input("Equip local", placeholder="Ex: Manresa", key="nom_eq1")
    nom_equip_2 = st.text_input("Equip visitant", placeholder="Ex: Girona", key="nom_eq2")
    carregar = st.button("⬇ Carregar partit", use_container_width=True)

    # ── Càrrega múltiple ─────────────────────────────────────────────────
    with st.expander("📋 Carregar múltiples partits", expanded=False):
        st.caption("Enganxa una URL o ID per línia. S'intentaran carregar tots.")
        urls_multi = st.text_area("URLs / IDs (un per línia)", height=120,
                                   placeholder="69ec95d4339c3d0001f523a1\n6a1c25041cc34c000132763e\nhttps://www.basquetcatala.cat/...")
        carregar_multi = st.button("⬇ Carregar tots", use_container_width=True, key="btn_multi")
        if carregar_multi and urls_multi.strip():
            linies = [l.strip() for l in urls_multi.strip().split("\n") if l.strip()]
            ok = 0; errors = []
            progress = st.progress(0)
            for i, linia in enumerate(linies):
                # Extreu l'ID de la URL si cal
                mid_multi = linia.split("/")[-1].strip() if "/" in linia else linia.strip()
                mid_multi = mid_multi.split("?")[0].strip()
                try:
                    df_m, teams_m, team_names_m = fetch_and_parse(mid_multi)
                    if df_m is not None and not df_m.empty:
                        ts_m = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        save_jugades(mid_multi, ts_m, df_m)
                        save_stats_jugador(mid_multi, ts_m, df_m, teams_m, team_names_m)
                        save_shots_zones(mid_multi, ts_m, df_m, teams_m)
                        save_timeouts(mid_multi, ts_m, df_m, teams_m)
                        n_a = team_names_m.get(teams_m[0],"?") if teams_m else "?"
                        n_b = team_names_m.get(teams_m[1],"?") if len(teams_m)>1 else "?"
                        sa = int(df_m[df_m["idEquip"]==teams_m[0]]["punts"].sum()) if teams_m else 0
                        sb = int(df_m[df_m["idEquip"]==teams_m[1]]["punts"].sum()) if len(teams_m)>1 else 0
                        save_partit(mid_multi, ts_m, n_a, n_b, sa, sb)
                        ok += 1
                    else:
                        errors.append(f"No trobat: {mid_multi[:20]}")
                except Exception as ex:
                    errors.append(f"Error {mid_multi[:20]}: {str(ex)[:30]}")
                progress.progress((i+1)/len(linies))
            if ok > 0:
                st.success(f"✅ {ok}/{len(linies)} partits carregats!")
            if errors:
                st.warning("\n".join(errors))
    st.markdown("---")
    st.markdown('<div style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#9ca3af;margin-bottom:6px">Filtres play-by-play</div>', unsafe_allow_html=True)
    quart_sel = st.multiselect("Quart", options=[1,2,3,4], default=[1,2,3,4])
    accio_cerca = st.text_input("Acció", placeholder="Cistella, falta...")
    jugador_cerca = st.text_input("Jugadora", placeholder="Nom...")
    st.markdown("---")
    st.caption("Analítica")

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
            t_list = get_teams_ordered(st.session_state.df)
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
                save_timeouts(mid, ts, df, noms)
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
        <h1 style="font-size:38px;font-weight:600;color:#1a1c22;margin:16px 0 8px">Analítica</h1>
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
t1,t_kp,t2,t3,t4,t_onoff,t5,t6,t_arq,t7,t8,t9 = st.tabs([
    "🏀 Partit","🌟 Key Performers","👤 Jugadores","⏱ Ritme","⚡ Eficiència","⚖️ On/Off","🔄 Rotacions",
    "📈 Hist. Jugadores","🎭 Arquetips","🎯 Mapa de Tir","🎬 Vídeo","📚 Històric"
])

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
            color_discrete_map=cmap,category_orders={"equip_nom":[nom_a,nom_b]},
            labels={"quart":"Quart","punts":"Punts","equip_nom":"Equip"})
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
# TAB KEY PERFORMERS
# ══════════════════════════════════════════════════
with t_kp:
    st.markdown(sec("🌟 Destacats del partit"), unsafe_allow_html=True)
    st.caption("Resum dels destacats del partit carregat — reutilitza les mateixes mètriques que la resta de pestanyes, no en calcula de noves.")

    col_j_kp = "jugador" if "jugador" in df_orig.columns else "jugadora"
    intervals_kp = get_intervals_jugadores_global(df_orig)

    df_t_kp = df_orig.copy()
    df_t_kp["t_abs"] = df_t_kp.apply(
        lambda r: (int(r["quart"])-1)*10+(10-float(r["min_num"]))
        if float(r.get("min_num",0))<=10 else float(r.get("min_num",0)), axis=1)
    df_t_kp["idEquip"] = df_t_kp["idEquip"].astype(str)

    noms_equip_kp = [n.upper() for n in [nom_a, nom_b] if n]
    kp_rows = []
    for jug_kp in df_orig[col_j_kp].unique():
        if not jug_kp or str(jug_kp) in ("", "nan"): continue
        if str(jug_kp).upper() in noms_equip_kp: continue  # descarta files d'equip (no jugadores)
        if len(str(jug_kp).split()) > 4: continue  # noms d'equip solen ser llargs
        dj_kp = df_orig[df_orig[col_j_kp] == jug_kp]
        eq_id_kp = str(dj_kp["idEquip"].iloc[0])
        eq_nom_kp = team_names.get(eq_id_kp, dj_kp["equip_nom"].iloc[0] if "equip_nom" in dj_kp.columns else "?")
        rival_kp = [t for t in teams if str(t) != eq_id_kp]
        rival_id_kp = str(rival_kp[0]) if rival_kp else None

        punts_kp = int(dj_kp["punts"].sum())
        tc_conv_kp = int(dj_kp["accio"].str.contains("Cistella de 2|Cistella de 3", case=False, na=False).sum())
        tc_int_kp = tc_conv_kp + int(dj_kp["accio"].str.contains(
            "Intent fallat de 2|Intent fallat de 3|fallat de 2|fallat de 3", case=False, na=False).sum())
        tl_conv_kp = int(dj_kp["accio"].str.contains("Cistella de 1", case=False, na=False).sum())
        tl_int_kp = tl_conv_kp + int(dj_kp["accio"].str.contains("Intent fallat de 1", case=False, na=False).sum())
        ts_denom_kp = 2 * (tc_int_kp + 0.44 * tl_int_kp)
        ts_kp = round(punts_kp / ts_denom_kp * 100, 1) if ts_denom_kp > 0 else None

        ivs_kp = intervals_kp.get(jug_kp, [])
        min_jugats_kp = sum(tf - ti for ti, tf, _ in ivs_kp)
        pf_kp = pc_kp = 0
        usage_kp = None
        if ivs_kp:
            for ti_kp, tf_kp, _ in ivs_kp:
                df_i_kp = df_t_kp[(df_t_kp["t_abs"] >= ti_kp) & (df_t_kp["t_abs"] < tf_kp)]
                pf_kp += int(df_i_kp[df_i_kp["idEquip"] == eq_id_kp]["punts"].sum())
                if rival_id_kp:
                    pc_kp += int(df_i_kp[df_i_kp["idEquip"] == rival_id_kp]["punts"].sum())
            mask_on_kp = df_t_kp["t_abs"].apply(lambda t: any(ti <= t < tf for ti, tf, _ in ivs_kp))
            df_eq_on_kp = df_t_kp[mask_on_kp & (df_t_kp["idEquip"] == eq_id_kp)]
            usage_kp = calc_usage_rate(dj_kp, df_eq_on_kp)

        pts_min_kp = round(punts_kp / min_jugats_kp, 2) if min_jugats_kp > 0 else None

        kp_rows.append({
            "jugadora": jug_kp, "equip_id": eq_id_kp, "equip_nom": eq_nom_kp,
            "punts": punts_kp, "ts": ts_kp, "n_intents": tc_int_kp + tl_int_kp,
            "pm": (pf_kp - pc_kp) if ivs_kp else None, "usage": usage_kp,
            "minuts": round(min_jugats_kp, 1), "pts_min": pts_min_kp,
        })

    df_kp = pd.DataFrame(kp_rows)

    def _card_or_dash(label, cond, value_fn, sub_fn, color=C_ACCENT):
        if cond:
            st.markdown(card(label, value_fn(), sub_fn(), color), unsafe_allow_html=True)
        else:
            st.markdown(card(label, "—", "Dades insuficients", C_LABEL), unsafe_allow_html=True)

    r1c1, r1c2, r1c3 = st.columns(3)
    r2c1, r2c2, r2c3 = st.columns(3)

    with r1c1:
        cond = not df_kp.empty and df_kp["punts"].notna().any()
        if cond:
            top_pts = df_kp.loc[df_kp["punts"].idxmax()]
            col_pts = COLOR_A if top_pts["equip_id"] == (str(teams[0]) if teams else None) else COLOR_B
        _card_or_dash("Màxima anotadora", cond,
            lambda: top_pts["jugadora"], lambda: f"{int(top_pts['punts'])} punts · {top_pts['equip_nom']}",
            col_pts if cond else C_LABEL)

    with r1c2:
        df_ts_ok = df_kp[(df_kp["n_intents"] >= 3) & df_kp["ts"].notna()]
        cond = not df_ts_ok.empty
        if cond:
            top_ts = df_ts_ok.loc[df_ts_ok["ts"].idxmax()]
            col_ts = COLOR_A if top_ts["equip_id"] == (str(teams[0]) if teams else None) else COLOR_B
        _card_or_dash("Millor TS%", cond,
            lambda: top_ts["jugadora"], lambda: f"{top_ts['ts']}% TS · {top_ts['equip_nom']} (≥3 intents)",
            col_ts if cond else C_LABEL)

    with r1c3:
        df_pm_ok = df_kp[df_kp["pm"].notna()]
        cond = not df_pm_ok.empty
        if cond:
            top_pm = df_pm_ok.loc[df_pm_ok["pm"].idxmax()]
            col_pm = C_SUCCESS if top_pm["pm"] >= 0 else C_ERROR
        _card_or_dash("Millor +/-", cond,
            lambda: top_pm["jugadora"], lambda: f"{'+' if top_pm['pm']>=0 else ''}{int(top_pm['pm'])} · {top_pm['equip_nom']}",
            col_pm if cond else C_LABEL)

    with r2c1:
        df_us_ok = df_kp[df_kp["usage"].notna() & df_kp["pts_min"].notna()]
        cond = False
        if not df_us_ok.empty:
            mitj_usage_eq = df_us_ok.groupby("equip_id")["usage"].transform("mean")
            df_us_cand = df_us_ok[df_us_ok["usage"] >= mitj_usage_eq]
            cond = not df_us_cand.empty
        if cond:
            top_us = df_us_cand.loc[df_us_cand["pts_min"].idxmax()]
            col_us = COLOR_A if top_us["equip_id"] == (str(teams[0]) if teams else None) else COLOR_B
        _card_or_dash("Millor Usage% × Pts/min", cond,
            lambda: top_us["jugadora"], lambda: f"Usage {top_us['usage']:.1f}% · {top_us['pts_min']} pts/min",
            col_us if cond else C_LABEL)

    with r2c2:
        ef_kp = calc_eficiencies(df_orig, teams, team_names)
        tid_a_kp = teams[0] if teams else None
        tid_b_kp = teams[1] if len(teams) > 1 else None
        net_a_kp = ef_kp.get(tid_a_kp, {}).get("net_rtg") if tid_a_kp else None
        net_b_kp = ef_kp.get(tid_b_kp, {}).get("net_rtg") if tid_b_kp else None
        cond = net_a_kp is not None
        _card_or_dash("Net Rating", cond,
            lambda: f"{'+' if net_a_kp>=0 else ''}{net_a_kp}",
            lambda: f"{nom_a} · {nom_b}: {'+' if (net_b_kp or 0)>=0 else ''}{net_b_kp if net_b_kp is not None else '—'}",
            (COLOR_A if cond and net_a_kp >= 0 else C_ERROR) if cond else C_LABEL)

    with r2c3:
        from scipy import stats as _sp_stats_kp
        def _rot_equip(eq_id_r):
            d = df_kp[(df_kp["equip_id"] == str(eq_id_r)) & df_kp["pm"].notna() & (df_kp["minuts"] >= 0.5)].copy()
            if len(d) < 3: return None
            d["pm_min"] = d["pm"] / d["minuts"].replace(0, 1)
            if d["minuts"].std() == 0 or d["pm_min"].std() == 0: return None
            rho, _ = _sp_stats_kp.pearsonr(d["minuts"], d["pm_min"])
            return round(5 * (rho + 1), 1)
        rot_a_kp = _rot_equip(teams[0]) if teams else None
        rot_b_kp = _rot_equip(teams[1]) if len(teams) > 1 else None
        cond = rot_a_kp is not None
        def _rot_semafor(v):
            if v is None: return "—"
            if v >= 7.5: return f"🟢{v}"
            if v >= 5.5: return f"🟡{v}"
            if v >= 3.5: return f"🟠{v}"
            return f"🔴{v}"
        _card_or_dash("ROT", cond,
            lambda: _rot_semafor(rot_a_kp),
            lambda: f"{nom_a} · {nom_b}: {_rot_semafor(rot_b_kp)}",
            C_ACCENT if cond else C_LABEL)

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
    st.caption("Parcial de l'equip durant els minuts reals que la jugadora és a pista (intervals Entra/Surt).")
    imp_rows=[]
    MINS_Q_IMP = 10
    # Precalcula t_abs
    df_orig_imp = df_orig.copy()
    df_orig_imp["t_abs"] = df_orig_imp.apply(
        lambda r: (int(r["quart"])-1)*10+(10-float(r["min_num"]))
        if float(r.get("min_num",0))<=10 else float(r.get("min_num",0)), axis=1)

    col_j_imp = "jugador" if "jugador" in df_orig.columns else "jugadora"
    # Noms d'equip per filtrar
    noms_equip = [nom_a.upper(), nom_b.upper(), nom_a, nom_b]
    for jug in df_orig[col_j_imp].unique():
        if not jug or str(jug) in ("","nan"): continue
        # Filtra si el "jugador" és realment el nom de l'equip
        if str(jug).upper() in [n.upper() for n in noms_equip]: continue
        if len(str(jug).split()) > 4: continue  # noms d'equip solen ser llargs
        dj=df_orig[df_orig[col_j_imp]==jug]
        eq_id=dj["idEquip"].iloc[0]; eq_nom=dj["equip_nom"].iloc[0]
        rival=[t for t in teams if t!=eq_id]
        rival_id_imp = rival[0] if rival else None

        # Calcula intervals reals
        intervals_disp = []; en_pista_disp = {}
        primer_acc_disp = str(dj.sort_values("num").iloc[0].get("accio",""))
        primer_q_disp = int(dj.sort_values("num").iloc[0].get("quart",1))
        if "Surt" in primer_acc_disp and "camp" in primer_acc_disp:
            en_pista_disp[jug] = (primer_q_disp-1)*MINS_Q_IMP

        for _,row_d in df_orig.sort_values("num").iterrows():
            if str(row_d.get(col_j_imp,"")) != str(jug): continue
            acc_d = str(row_d.get("accio",""))
            q_d = int(row_d.get("quart",1))
            m_d = float(row_d.get("min_num",0))
            t_d = (q_d-1)*MINS_Q_IMP + (MINS_Q_IMP - m_d if m_d<=MINS_Q_IMP else m_d)
            t_d = max(0, min(t_d, q_d*MINS_Q_IMP))
            if "Entra" in acc_d and "camp" in acc_d:
                en_pista_disp[jug] = t_d
            elif "Surt" in acc_d and "camp" in acc_d:
                ti_d = en_pista_disp.pop(jug, (q_d-1)*MINS_Q_IMP)
                if t_d > ti_d: intervals_disp.append((ti_d, t_d))
            elif "Final de període" in acc_d:
                if jug in en_pista_disp:
                    ti_d = en_pista_disp.pop(jug)
                    fi_d = q_d*MINS_Q_IMP
                    if fi_d > ti_d: intervals_disp.append((ti_d, fi_d))
        for ti_o in en_pista_disp.values():
            fi_o = float(df_orig["quart"].max() * MINS_Q_IMP)
            if fi_o > ti_o: intervals_disp.append((ti_o, fi_o))
        intervals_disp = [(float(ti),float(tf)) for ti,tf in intervals_disp]

        if not intervals_disp:
            n_min,n_max=dj["num"].min(),dj["num"].max()
            dr=df_orig[(df_orig["num"]>=n_min)&(df_orig["num"]<=n_max)]
            pf=int(dr[dr["idEquip"]==eq_id]["punts"].sum())
            pc=int(dr[dr["idEquip"]==rival_id_imp]["punts"].sum()) if rival_id_imp else 0
        else:
            pf=pc=0
            for ti_d,tf_d in intervals_disp:
                df_i=df_orig_imp[(df_orig_imp["t_abs"]>=ti_d)&(df_orig_imp["t_abs"]<=tf_d)]
                pf+=int(df_i[df_i["idEquip"]==eq_id]["punts"].sum())
                if rival_id_imp:
                    pc+=int(df_i[df_i["idEquip"]==rival_id_imp]["punts"].sum())

        # Usage Rate per display
        if intervals_disp:
            df_orig_imp2 = df_orig.copy()
            df_orig_imp2["t_abs"] = df_orig_imp2.apply(
                lambda r: (int(r["quart"])-1)*10+(10-float(r["min_num"]))
                if float(r.get("min_num",0))<=10 else float(r.get("min_num",0)), axis=1)
            mask_us = df_orig_imp2["t_abs"].apply(
                lambda t: any(ti<=t<=tf for ti,tf in intervals_disp))
            df_eq_on_us = df_orig_imp2[mask_us & (df_orig_imp2["idEquip"]==eq_id)]
            usage_disp = calc_usage_rate(dj, df_eq_on_us)
        else:
            usage_disp = calc_usage_rate(dj, df_orig[df_orig["idEquip"]==eq_id])
        imp_rows.append({"Equip":eq_nom,"Jugadora":jug,"Pts favor":pf,"Pts contra":pc,
            "Parcial":f"+{pf-pc}" if pf>=pc else str(pf-pc),
            "Usage%": f"{usage_disp}%",
            "_diff":pf-pc})
    df_imp=pd.DataFrame(imp_rows).sort_values("_diff",ascending=False).drop(columns="_diff")
    t_ia,t_ib=st.tabs([nom_a,nom_b])
    for it,in_nom in [(t_ia,nom_a),(t_ib,nom_b)]:
        with it:
            di=df_imp[df_imp["Equip"]==in_nom].drop(columns="Equip")
            st.dataframe(di,use_container_width=True,hide_index=True)

    # ── Usage% vs Eficiència (scatter) ─────────────────────────────────────
    st.markdown(sec("Usage% vs Eficiència"), unsafe_allow_html=True)
    st.caption("Eix X = % de possessions usades · Eix Y = Pts/min · Quadrant ideal: dalt a la dreta")

    if imp_rows:
        df_scatter = pd.DataFrame(imp_rows).copy()
        df_scatter["_usage_num"] = df_scatter["Usage%"].str.replace("%","").astype(float)
        # Pts totals de la jugadora (de la taula d'estadístiques)
        df_scatter["_pts"] = df_scatter["Jugadora"].apply(
            lambda j: int(df_orig[df_orig[col_j_imp]==j]["punts"].sum()))
        # Minuts reals (dels intervals calculats)
        MINS_Q_SC = 10
        def get_minuts(jug):
            ivs = []; ep = {}
            dj_sc = df_orig[df_orig[col_j_imp]==jug]
            if dj_sc.empty: return 1
            pr = dj_sc.sort_values("num").iloc[0]
            if "Surt" in str(pr.get("accio","")) and "camp" in str(pr.get("accio","")):
                ep[jug] = (int(pr.get("quart",1))-1)*MINS_Q_SC
            for _,r in df_orig.sort_values("num").iterrows():
                if str(r.get(col_j_imp,"")) != str(jug): continue
                a = str(r.get("accio","")); q = int(r.get("quart",1))
                m = float(r.get("min_num",0))
                t = (q-1)*MINS_Q_SC + (MINS_Q_SC-m if m<=MINS_Q_SC else m)
                t = max(0, min(t, q*MINS_Q_SC))
                if "Entra" in a and "camp" in a: ep[jug] = t
                elif "Surt" in a and "camp" in a:
                    ti = ep.pop(jug, (q-1)*MINS_Q_SC)
                    if t > ti: ivs.append((ti, t))
                elif "Final de període" in a:
                    if jug in ep:
                        ti = ep.pop(jug); fi = float(q*MINS_Q_SC)
                        if fi > ti: ivs.append((ti, fi))
            for ti_o in ep.values():
                fi_o = float(df_orig["quart"].max()*MINS_Q_SC)
                if fi_o > ti_o: ivs.append((ti_o, fi_o))
            total = sum(tf-ti for ti,tf in ivs)
            return max(total, 1)
        df_scatter["_min"] = df_scatter["Jugadora"].apply(get_minuts)
        df_scatter["Pts/min"] = (df_scatter["_pts"] / df_scatter["_min"]).round(2)
        df_scatter["_color"] = df_scatter["Equip"].map({nom_a: COLOR_A, nom_b: COLOR_B})

        fig_sc = go.Figure()
        for eq, color in [(nom_a, COLOR_A), (nom_b, COLOR_B)]:
            df_eq = df_scatter[df_scatter["Equip"]==eq]
            if df_eq.empty: continue
            fig_sc.add_trace(go.Scatter(
                x=df_eq["_usage_num"],
                y=df_eq["Pts/min"],
                mode="markers+text",
                name=eq,
                marker=dict(size=14, color=color,
                            line=dict(width=1.5, color="white")),
                text=df_eq["Jugadora"].apply(
                    lambda n: n.split()[1] if len(n.split())>1 else n),
                textposition="top center",
                textfont=dict(size=9),
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    "Usage: %{x:.1f}%<br>"
                    "Pts/min: %{y:.2f}<br>"
                    "<extra></extra>"
                )
            ))

        # Línies de mitjana
        mitjana_usage = df_scatter["_usage_num"].mean()
        mitjana_pts   = df_scatter["Pts/min"].mean()
        fig_sc.add_vline(x=mitjana_usage, line_dash="dot",
            line_color="#e2e4e8",
            annotation_text=f"Mitjana {mitjana_usage:.0f}%",
            annotation_font_size=9, annotation_font_color="#9ca3af")
        fig_sc.add_hline(y=mitjana_pts, line_dash="dot",
            line_color="#e2e4e8",
            annotation_text=f"Mitjana {mitjana_pts:.2f}",
            annotation_font_size=9, annotation_font_color="#9ca3af")

        # Etiquetes dels quadrants
        x_max = df_scatter["_usage_num"].max() * 1.1
        y_max = df_scatter["Pts/min"].max() * 1.1
        for txt, x, y, color in [
            ("⭐ Estrella", x_max*0.95, y_max*0.95, "#16a34a"),
            ("⚠️ Massa ús", x_max*0.95, y_max*0.05, "#dc2626"),
            ("💡 Infravalorada", x_max*0.05, y_max*0.95, "#185FA5"),
            ("🔄 Rol secundari", x_max*0.05, y_max*0.05, "#9ca3af"),
        ]:
            fig_sc.add_annotation(x=x, y=y, text=txt,
                showarrow=False, font=dict(size=9, color=color),
                xanchor="center", yanchor="middle", opacity=0.5)

        fig_sc.update_layout(
            xaxis=dict(title="Usage% (% possessions usades)",
                       showgrid=True, gridcolor="#f3f4f6", color="#9ca3af"),
            yaxis=dict(title="Pts/min",
                       showgrid=True, gridcolor="#f3f4f6", color="#9ca3af"),
            paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
            font=dict(color="#374151", family="Inter"),
            legend=dict(bgcolor="#ffffff", bordercolor="#e2e4e8",
                        borderwidth=1, orientation="h",
                        yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=0,r=0,t=40,b=0), height=380)
        st.plotly_chart(fig_sc, use_container_width=True)

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

    # ── Anàlisi de temps morts ────────────────────────────────────────────
    st.markdown(sec("⏸ Temps morts — qui anota després?"), unsafe_allow_html=True)
    st.caption("Primera cistella de l'equip que demana el temps mort, i quant triga a anotar-la.")

    to_data = analyze_timeouts(df_orig, team_names)
    if not to_data:
        st.info("No s'han detectat temps morts en aquest partit.")
    else:
        df_to = pd.DataFrame(to_data)

        # Mètriques generals
        c1,c2,c3,c4 = st.columns(4)
        total_to = len(df_to)
        anotats = df_to["va_anotar"].sum()
        efectivitat = round(anotats/total_to*100) if total_to>0 else 0
        seg_mitjana = df_to[df_to["va_anotar"]==1]["segons_resposta"].mean()

        with c1: st.markdown(card("Temps morts",total_to,"total","#374151"),unsafe_allow_html=True)
        with c2: st.markdown(card("Anoten després",int(anotats),"cistella","#16a34a"),unsafe_allow_html=True)
        with c3: st.markdown(card("Efectivitat",f"{efectivitat}%","","#185FA5"),unsafe_allow_html=True)
        with c4: st.markdown(card("Seg. fins cistella",f"{seg_mitjana:.0f}s" if not pd.isna(seg_mitjana) else "—","mitjana","#d97706"),unsafe_allow_html=True)

        # Taula detallada
        df_to_show = df_to.copy()
        df_to_show["Q"] = df_to_show["quart"]
        df_to_show["Equip"] = df_to_show["equip_nom"]
        df_to_show["Anota?"] = df_to_show["va_anotar"].map({1:"✅ Sí", 0:"❌ No"})
        df_to_show["Jugadora"] = df_to_show["jugadora"]
        df_to_show["Acció"] = df_to_show["accio"]
        df_to_show["Seg."] = df_to_show["segons_resposta"].apply(lambda x: f"{x:.0f}s" if x and not pd.isna(x) else "—")
        df_to_show["≤24s?"] = df_to_show.get("dins_24s", pd.Series([0]*len(df_to_show))).map({1:"✅ Sí", 0:"❌ No"})
        st.dataframe(df_to_show[["Q","Equip","Anota?","≤24s?","Jugadora","Acció","Seg."]],
            use_container_width=True, hide_index=True)

        # Gràfic per equip
        if len(df_to) > 1:
            resum_eq = df_to.groupby("equip_nom").agg(
                Total=("va_anotar","count"),
                Anotats=("va_anotar","sum"),
                Seg_mitjana=("segons_resposta","mean")
            ).reset_index()
            resum_eq["Efectivitat %"] = (resum_eq["Anotats"]/resum_eq["Total"]*100).round(0)
            fig_to = px.bar(resum_eq, x="equip_nom", y="Efectivitat %",
                color="equip_nom", color_discrete_map=color_map_eq,
                category_orders={"equip_nom":[nom_a,nom_b]},
                text="Efectivitat %", labels={"equip_nom":"Equip"})
            fig_to.update_traces(texttemplate="%{text}%", textposition="outside")
            st.plotly_chart(chart_style(fig_to, 220, "Efectivitat dels temps morts per equip"), use_container_width=True)

    # ── Rendiment per quart ──────────────────────────────────────────────
    st.markdown(sec("📊 Rendiment per quart"), unsafe_allow_html=True)
    st.caption(
        "Off Rtg = pts/100 poss · TS% = pts/(2×(TC_int+0.44×TL_int))×100 · "
        "Ritme = poss/min (quarts de 10 min)"
    )
    quarts_data = []
    for q in sorted(df_orig["quart"].unique()):
        df_q = df_orig[df_orig["quart"] == q]
        for tid, nom_eq, color_eq in [(teams[0] if teams else None, nom_a, COLOR_A),
                                       (teams[1] if len(teams) > 1 else None, nom_b, COLOR_B)]:
            if tid is None: continue
            df_eq_q = df_q[df_q["idEquip"].astype(str) == str(tid)]
            tc_q = int(df_eq_q["accio"].str.contains(TC_INT_PAT, case=False, na=False).sum())
            tl_q = int(df_eq_q["accio"].str.contains(TL_INT_PAT, case=False, na=False).sum())
            poss_q = tc_q + 0.44 * tl_q
            pts_q = int(df_eq_q["punts"].sum())
            ts_denom = 2 * poss_q
            ts_q = round(pts_q / ts_denom * 100, 1) if ts_denom > 0 else 0.0
            off_rtg_q = round(pts_q / poss_q * 100, 1) if poss_q > 0 else 0.0
            ritme_q = round(poss_q / 10, 2)
            quarts_data.append({
                "quart": int(q), "equip": nom_eq, "color": color_eq,
                "poss": round(poss_q, 1), "pts": pts_q,
                "ts": ts_q, "off_rtg": off_rtg_q, "ritme": ritme_q,
            })

    if not quarts_data:
        st.info("No hi ha dades de quarts per aquest partit.")
    else:
        df_qd = pd.DataFrame(quarts_data)
        quarts_uniq = sorted(df_qd["quart"].unique())

        # Taula comparativa (HTML)
        caps_q = ["Quart", f"Poss {nom_a}", f"Ritme {nom_a}", f"TS% {nom_a}", f"Off Rtg {nom_a}",
                  f"Pts {nom_a}", f"Pts {nom_b}", f"Off Rtg {nom_b}", f"TS% {nom_b}",
                  f"Ritme {nom_b}", f"Poss {nom_b}"]
        html_q = ('<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;'
                  f'font-size:12px;color:{C_TEXT}">')
        html_q += '<tr>' + ''.join(
            f'<th style="background:{C_BG_SOFT};color:{C_ACCENT_DARK};padding:6px 10px;'
            f'text-align:center;border:1px solid {C_BORDER};font-weight:600">{c}</th>' for c in caps_q) + '</tr>'
        for i_q, q_val in enumerate(quarts_uniq):
            ra_df = df_qd[(df_qd["quart"] == q_val) & (df_qd["equip"] == nom_a)]
            rb_df = df_qd[(df_qd["quart"] == q_val) & (df_qd["equip"] == nom_b)]
            if ra_df.empty or rb_df.empty: continue
            ra, rb = ra_df.iloc[0], rb_df.iloc[0]
            bg_row = C_WHITE if i_q % 2 == 0 else C_BG
            if ra["pts"] > rb["pts"]:
                bg_a, bg_b = "#D5F5E3", bg_row
            elif rb["pts"] > ra["pts"]:
                bg_a, bg_b = bg_row, "#D5F5E3"
            else:
                bg_a = bg_b = "#FFF3CD"
            vals_q = [f"Q{q_val}", ra["poss"], ra["ritme"], ra["ts"], ra["off_rtg"],
                      ra["pts"], rb["pts"], rb["off_rtg"], rb["ts"], rb["ritme"], rb["poss"]]
            bgs_q = [bg_row, bg_row, bg_row, bg_row, bg_row, bg_a, bg_b, bg_row, bg_row, bg_row, bg_row]
            html_q += '<tr>'
            for ci_q, (val_q, bgc_q) in enumerate(zip(vals_q, bgs_q)):
                align_q = 'left' if ci_q == 0 else 'center'
                bold_q = 'font-weight:600;' if ci_q in (5, 6) else ''
                html_q += (f'<td style="padding:5px 10px;border:1px solid {C_BORDER};background:{bgc_q};'
                           f'color:{C_TEXT};text-align:{align_q};{bold_q}">{val_q}</td>')
            html_q += '</tr>'
        html_q += '</table></div>'
        st.markdown(html_q, unsafe_allow_html=True)

        # Gràfic 1 — Possessions per quart
        fig_qp = go.Figure()
        for nom_eq, color_eq in [(nom_a, COLOR_A), (nom_b, COLOR_B)]:
            d_eq = df_qd[df_qd["equip"] == nom_eq]
            fig_qp.add_trace(go.Bar(x=[f"Q{q}" for q in d_eq["quart"]], y=d_eq["poss"],
                name=nom_eq, marker_color=color_eq, text=d_eq["poss"], textposition="outside"))
        fig_qp.update_layout(barmode="group")
        st.plotly_chart(chart_style(fig_qp, 260, "Possessions per quart"), use_container_width=True)

        # Gràfic 2 — Off Rating per quart
        fig_qo = go.Figure()
        for nom_eq, color_eq in [(nom_a, COLOR_A), (nom_b, COLOR_B)]:
            d_eq = df_qd[df_qd["equip"] == nom_eq]
            fig_qo.add_trace(go.Bar(x=[f"Q{q}" for q in d_eq["quart"]], y=d_eq["off_rtg"],
                name=nom_eq, marker_color=color_eq, text=d_eq["off_rtg"], textposition="outside"))
        fig_qo.add_hline(y=100, line_dash="dot", line_color=C_LABEL,
            annotation_text="Ref. 100", annotation_font_size=9)
        fig_qo.update_layout(barmode="group")
        st.plotly_chart(chart_style(fig_qo, 260, "Off Rating per quart"), use_container_width=True)

        # Gràfic 3 — TS% per quart
        fig_qt = go.Figure()
        for nom_eq, color_eq in [(nom_a, COLOR_A), (nom_b, COLOR_B)]:
            d_eq = df_qd[df_qd["equip"] == nom_eq]
            fig_qt.add_trace(go.Bar(x=[f"Q{q}" for q in d_eq["quart"]], y=d_eq["ts"],
                name=nom_eq, marker_color=color_eq, text=d_eq["ts"], textposition="outside"))
        fig_qt.add_hline(y=50, line_dash="dot", line_color=C_LABEL,
            annotation_text="Ref. 50%", annotation_font_size=9)
        fig_qt.update_layout(barmode="group")
        st.plotly_chart(chart_style(fig_qt, 260, "True Shooting % per quart"), use_container_width=True)

        # ── Tipus de tirs per quart ─────────────────────────────────────────
        st.markdown(sec("🎯 Tipus de tirs per quart"), unsafe_allow_html=True)
        st.caption(
            "Intents de 2, 3 i tirs lliures per quart (encerts inclosos als intents). Útil per veure "
            "si un quart de TS% baix ve d'haver tirat més triples o més tirs lliures del normal."
        )
        tipus_rows = []
        for q in quarts_uniq:
            df_q_tip = df_orig[df_orig["quart"] == q]
            for tid, nom_eq in [(teams[0] if teams else None, nom_a), (teams[1] if len(teams) > 1 else None, nom_b)]:
                if tid is None: continue
                dq_eq = df_q_tip[df_q_tip["idEquip"].astype(str) == str(tid)]
                c2_int = int(dq_eq["accio"].str.contains("Cistella de 2|Intent fallat de 2|fallat de 2", case=False, na=False).sum())
                c3_int = int(dq_eq["accio"].str.contains("Cistella de 3|Intent fallat de 3|fallat de 3", case=False, na=False).sum())
                tl_int = int(dq_eq["accio"].str.contains("Cistella de 1|Intent fallat de 1", case=False, na=False).sum())
                tot_int = c2_int + c3_int + tl_int
                tipus_rows.append({
                    "quart": int(q), "equip": nom_eq,
                    "2PA": c2_int, "3PA": c3_int, "TLA": tl_int,
                    "%2PA": round(c2_int/tot_int*100, 0) if tot_int > 0 else 0,
                    "%3PA": round(c3_int/tot_int*100, 0) if tot_int > 0 else 0,
                    "%TLA": round(tl_int/tot_int*100, 0) if tot_int > 0 else 0,
                })
        df_tipus_q = pd.DataFrame(tipus_rows)

        caps_tip = ["Quart",
            f"2PA {nom_a}", f"3PA {nom_a}", f"TLA {nom_a}", f"%3PA {nom_a}",
            f"2PA {nom_b}", f"3PA {nom_b}", f"TLA {nom_b}", f"%3PA {nom_b}"]
        html_tip = ('<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;'
                    f'font-size:12px;color:{C_TEXT}">')
        html_tip += '<tr>' + ''.join(
            f'<th style="background:{C_BG_SOFT};color:{C_ACCENT_DARK};padding:6px 10px;'
            f'text-align:center;border:1px solid {C_BORDER};font-weight:600">{c}</th>' for c in caps_tip) + '</tr>'
        for i_tip, q_val in enumerate(quarts_uniq):
            ra_t = df_tipus_q[(df_tipus_q["quart"]==q_val)&(df_tipus_q["equip"]==nom_a)]
            rb_t = df_tipus_q[(df_tipus_q["quart"]==q_val)&(df_tipus_q["equip"]==nom_b)]
            if ra_t.empty or rb_t.empty: continue
            ra_t, rb_t = ra_t.iloc[0], rb_t.iloc[0]
            bg_tip = C_WHITE if i_tip % 2 == 0 else C_BG
            vals_tip = [f"Q{q_val}",
                ra_t["2PA"], ra_t["3PA"], ra_t["TLA"], f"{ra_t['%3PA']:.0f}%",
                rb_t["2PA"], rb_t["3PA"], rb_t["TLA"], f"{rb_t['%3PA']:.0f}%"]
            html_tip += '<tr>'
            for ci_tip, val_tip in enumerate(vals_tip):
                align_tip = 'left' if ci_tip == 0 else 'center'
                html_tip += (f'<td style="padding:5px 10px;border:1px solid {C_BORDER};background:{bg_tip};'
                             f'color:{C_TEXT};text-align:{align_tip}">{val_tip}</td>')
            html_tip += '</tr>'
        html_tip += '</table></div>'
        st.markdown(html_tip, unsafe_allow_html=True)
        st.caption("PA = intents (attempts) · TLA = tirs lliures intentats · %3PA = % dels intents totals que van ser de triple")

    # ── Liderant vs. Remolcant ────────────────────────────────────────────
    st.markdown(sec("📈 Liderant vs. Remolcant"), unsafe_allow_html=True)
    st.caption(
        "Eficiència ofensiva segons l'estat del marcador ABANS de cada acció (no després — "
        "si ja s'ha tirat, el marcador ja inclouria el resultat de la pròpia jugada). "
        "Reutilitza score_evo() ja existent; mínim 4 possessions per bucket per ser fiable."
    )
    score_prev_lvr = score_df.sort_values("num")[["num", "diff"]].copy()
    score_prev_lvr["marge_previ_a"] = score_prev_lvr["diff"].shift(1).fillna(0)
    df_lvr = df_orig.merge(score_prev_lvr[["num", "marge_previ_a"]], on="num", how="left")
    df_lvr["marge_previ_a"] = df_lvr["marge_previ_a"].fillna(0)

    MIN_POSS_LVR = 4
    bucket_order_lvr = ["📈 Liderant", "➡️ Empatat", "📉 Remolcant"]
    bucket_colors_lvr = {"📈 Liderant": C_SUCCESS, "➡️ Empatat": C_LABEL, "📉 Remolcant": C_ERROR}

    for tid_lvr, tnom_lvr in [(teams[0] if teams else None, nom_a), (teams[1] if len(teams)>1 else None, nom_b)]:
        if tid_lvr is None: continue
        st.markdown(f"**{tnom_lvr}**")
        signe_lvr = 1 if tid_lvr == (teams[0] if teams else None) else -1
        df_eq_lvr = df_lvr[df_lvr["idEquip"] == tid_lvr].copy()
        df_eq_lvr["marge_propi"] = df_eq_lvr["marge_previ_a"] * signe_lvr
        df_eq_lvr["bucket"] = df_eq_lvr["marge_propi"].apply(
            lambda m: "📈 Liderant" if m > 0 else ("➡️ Empatat" if m == 0 else "📉 Remolcant"))

        resultats_lvr = {}
        for bkt in bucket_order_lvr:
            df_b_lvr = df_eq_lvr[df_eq_lvr["bucket"] == bkt]
            poss_b_lvr = calc_possessions(df_b_lvr)
            if poss_b_lvr < MIN_POSS_LVR:
                resultats_lvr[bkt] = None
                continue
            pts_b_lvr = int(df_b_lvr["punts"].sum())
            tc_conv_b = int(df_b_lvr["accio"].str.contains("Cistella de 2|Cistella de 3", case=False, na=False).sum())
            tc_int_b = tc_conv_b + int(df_b_lvr["accio"].str.contains(
                "Intent fallat de 2|Intent fallat de 3|fallat de 2|fallat de 3", case=False, na=False).sum())
            tl_conv_b = int(df_b_lvr["accio"].str.contains("Cistella de 1", case=False, na=False).sum())
            tl_int_b = tl_conv_b + int(df_b_lvr["accio"].str.contains("Intent fallat de 1", case=False, na=False).sum())
            ts_denom_b = 2 * (tc_int_b + 0.44 * tl_int_b)
            resultats_lvr[bkt] = {
                "poss": round(poss_b_lvr, 1), "pts": pts_b_lvr,
                "off_rtg": round(pts_b_lvr / poss_b_lvr * 100, 1),
                "ppp": round(pts_b_lvr / poss_b_lvr, 2),
                "ts": round(pts_b_lvr / ts_denom_b * 100, 1) if ts_denom_b > 0 else 0,
            }

        cols_lvr = st.columns(3)
        for col_lvr, bkt in zip(cols_lvr, bucket_order_lvr):
            with col_lvr:
                r_lvr = resultats_lvr[bkt]
                if r_lvr is None:
                    st.markdown(card(bkt, "—", "Dades insuficients", C_LABEL), unsafe_allow_html=True)
                else:
                    st.markdown(card(bkt, r_lvr["off_rtg"],
                        f"TS% {r_lvr['ts']} · {r_lvr['poss']} poss · PPP {r_lvr['ppp']}",
                        bucket_colors_lvr[bkt]), unsafe_allow_html=True)

        vals_chart_lvr = [(bkt, resultats_lvr[bkt]["off_rtg"]) for bkt in bucket_order_lvr if resultats_lvr[bkt] is not None]
        if vals_chart_lvr:
            fig_lvr = go.Figure()
            fig_lvr.add_trace(go.Bar(
                x=[v[0] for v in vals_chart_lvr], y=[v[1] for v in vals_chart_lvr],
                marker_color=[bucket_colors_lvr[v[0]] for v in vals_chart_lvr],
                text=[f"{v[1]}" for v in vals_chart_lvr], textposition="outside"))
            fig_lvr.update_layout(yaxis_title="Off Rtg")
            st.plotly_chart(chart_style(fig_lvr, 240, f"{tnom_lvr} — Off Rtg segons l'estat del marcador"),
                use_container_width=True)
        else:
            st.info(f"No hi ha prou possessions en cap bucket per a {tnom_lvr}.")

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
with t9:
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

        # Win Shares de temporada
        equips_ws = sorted(set(df_hist["nom_a"]) | set(df_hist["nom_b"]))
        if len(df_hist) >= 3 and len(equips_ws) >= 2:
            st.markdown(sec("🏆 Win Shares de temporada"), unsafe_allow_html=True)
            if len(df_hist) < 5:
                st.warning("⚠️ Referència de lliga provisional: com més partits carreguis (de qualsevol equip), més fiable serà la mètrica.")
            equip_ws_sel = st.selectbox("Equip", equips_ws, key="equip_ws_sel")
            df_ws_all = calc_win_shares_temporada()
            if df_ws_all.empty:
                st.info("No hi ha prou dades de play-by-play per calcular Win Shares.")
            else:
                df_ws_eq = df_ws_all[df_ws_all["equip"] == equip_ws_sel].sort_values("WS", ascending=False)
                partits_eq = df_hist[(df_hist["nom_a"] == equip_ws_sel) | (df_hist["nom_b"] == equip_ws_sel)]
                victories_eq = int(sum(
                    1 for _, r in partits_eq.iterrows()
                    if (r["nom_a"] == equip_ws_sel and r["score_a"] > r["score_b"])
                    or (r["nom_b"] == equip_ws_sel and r["score_b"] > r["score_a"])))
                col_ws1, col_ws2 = st.columns(2)
                with col_ws1:
                    st.markdown(card("WS total equip", round(df_ws_eq["WS"].sum(), 1),
                                      "suma de totes les jugadores"), unsafe_allow_html=True)
                with col_ws2:
                    st.markdown(card("Victòries reals", victories_eq, f"de {len(partits_eq)} partits",
                                      color=C_SUCCESS), unsafe_allow_html=True)

                df_ws_show = df_ws_eq[["jugador", "partits", "minuts", "punts", "OWS", "WS", "ws_per40", "Arquetip"]].rename(
                    columns={"jugador": "Jugadora", "partits": "Partits", "minuts": "Min totals",
                             "punts": "Pts totals", "ws_per40": "WS/40min"})
                st.dataframe(df_ws_show, use_container_width=True, hide_index=True)
                st.caption("Win Shares ofensius aproximats. La component defensiva és una estimació "
                           "(no disposem de Def Rating individual). La referència de lliga s'actualitza "
                           "amb cada nou partit carregat.")

        # Botó per descarregar Excel de temporada
        st.markdown(sec("Exporta la temporada a Excel"), unsafe_allow_html=True)
        st.caption("Excel formatat amb 4 pestanyes: Temporada · Jugadores · Evolució per Partit · Eficiència de Tir")
        if st.button("⬇ Descarregar Excel de temporada", key="btn_excel"):
            excel_data = genera_excel_temporada()
            st.download_button(
                label="📥 Clic per descarregar",
                data=excel_data,
                file_name=f"miki_analitica_temporada_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_excel"
            )

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
with t4:
    # ── Comparació d'equips (tornado chart) ─────────────────────────────────
    st.markdown(sec("📊 Comparació d'equips"), unsafe_allow_html=True)
    st.caption("Off/Def/Net Rtg, TS%, eFG% i possessions totals dels dos equips d'aquest partit, costat a costat.")

    tid_a_cmp = teams[0] if teams else None
    tid_b_cmp = teams[1] if len(teams) > 1 else None
    if tid_a_cmp and tid_b_cmp:
        ef_cmp = calc_eficiencies(df_orig, teams, team_names)
        df_eq_a_cmp = df_orig[df_orig["idEquip"] == tid_a_cmp]
        df_eq_b_cmp = df_orig[df_orig["idEquip"] == tid_b_cmp]
        met_a_cmp = calc_metriques_partit(df_eq_a_cmp, match_id, nom_a, nom_b)
        met_b_cmp = calc_metriques_partit(df_eq_b_cmp, match_id, nom_b, nom_a)

        net_a_cmp, net_b_cmp = ef_cmp[tid_a_cmp]["net_rtg"], ef_cmp[tid_b_cmp]["net_rtg"]
        col_na = COLOR_A if net_a_cmp >= 0 else "#dc2626"
        col_nb = COLOR_B if net_b_cmp >= 0 else "#dc2626"
        col_net1, col_net2 = st.columns(2)
        with col_net1:
            st.markdown(card("Net Rtg", f"{'+' if net_a_cmp>=0 else ''}{net_a_cmp}", nom_a, col_na), unsafe_allow_html=True)
        with col_net2:
            st.markdown(card("Net Rtg", f"{'+' if net_b_cmp>=0 else ''}{net_b_cmp}", nom_b, col_nb), unsafe_allow_html=True)

        metrics_cmp = [
            ("Off Rtg", ef_cmp[tid_a_cmp]["off_rtg"], ef_cmp[tid_b_cmp]["off_rtg"]),
            ("Def Rtg", ef_cmp[tid_a_cmp]["def_rtg"], ef_cmp[tid_b_cmp]["def_rtg"]),
            ("TS%", met_a_cmp["TS%"], met_b_cmp["TS%"]),
            ("eFG%", met_a_cmp["eFG%"], met_b_cmp["eFG%"]),
            ("Possessions", met_a_cmp["Possessions"], met_b_cmp["Possessions"]),
        ]
        labels_cmp = [m[0] for m in metrics_cmp]
        vals_a_cmp = [m[1] for m in metrics_cmp]
        vals_b_cmp = [m[2] for m in metrics_cmp]

        fig_cmp = go.Figure()
        fig_cmp.add_trace(go.Bar(
            y=labels_cmp, x=[-v for v in vals_a_cmp], orientation="h", name=nom_a,
            marker_color=COLOR_A, text=[f"{v:g}" for v in vals_a_cmp], textposition="outside"))
        fig_cmp.add_trace(go.Bar(
            y=labels_cmp, x=vals_b_cmp, orientation="h", name=nom_b,
            marker_color=COLOR_B, text=[f"{v:g}" for v in vals_b_cmp], textposition="outside"))
        fig_cmp.update_layout(
            barmode="overlay",
            xaxis=dict(showticklabels=False, zeroline=True, zerolinecolor=C_CARD_BORDER, zerolinewidth=1.5),
            yaxis=dict(title=""),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(chart_style(fig_cmp, 340, "Comparació d'equips"), use_container_width=True)
    else:
        st.info("Calen dos equips per a la comparació.")

    # ── ROT — Índex de gestió de rotacions ─────────────────────────────────
    st.markdown(sec("ROT — Índex de gestió de rotacions"), unsafe_allow_html=True)
    st.caption("ROT = 5 · (ρ + 1)  on ρ = correlació de Pearson entre minuts jugats i +/- per minut de cada jugadora. Escala 0-10. ROT alt = les jugadores que juguen més aporten més.")

    col_j_rot = "jugador" if "jugador" in df_orig.columns else "jugadora"
    rot_data = []

    for eq_rot in teams:
        rival_rot = [t for t in teams if t != eq_rot]
        rival_id_rot = rival_rot[0] if rival_rot else None
        if rival_id_rot is None: continue

        df_t_rot = df_orig.copy()
        df_t_rot["t_abs"] = df_t_rot.apply(
            lambda r: (int(r["quart"])-1)*10+(10-float(r["min_num"]))
            if float(r.get("min_num",0))<=10 else float(r.get("min_num",0)), axis=1)

        jugs_rot = [j for j in df_orig[df_orig["idEquip"]==eq_rot][col_j_rot].unique()
                    if j and str(j) not in ("","nan")]

        for jug_rot in jugs_rot:
            # Calcula intervals reals (el mateix mètode que usem a tot arreu)
            MINS_Q_R = 10
            ivs_rot = []; ep_rot = {}
            dj_rot = df_orig[df_orig[col_j_rot]==jug_rot]
            if dj_rot.empty: continue
            pr_rot = dj_rot.sort_values("num").iloc[0]
            if "Surt" in str(pr_rot.get("accio","")) and "camp" in str(pr_rot.get("accio","")):
                ep_rot[jug_rot] = (int(pr_rot.get("quart",1))-1)*MINS_Q_R
            for _,row_r in df_orig.sort_values("num").iterrows():
                if str(row_r.get(col_j_rot,"")) != jug_rot: continue
                a_r=str(row_r.get("accio","")); q_r=int(row_r.get("quart",1))
                m_r=float(row_r.get("min_num",0))
                t_r=(q_r-1)*MINS_Q_R+(MINS_Q_R-m_r if m_r<=MINS_Q_R else m_r)
                t_r=max(0,min(t_r,q_r*MINS_Q_R))
                if "Entra" in a_r and "camp" in a_r: ep_rot[jug_rot]=t_r
                elif "Surt" in a_r and "camp" in a_r:
                    ti_r=ep_rot.pop(jug_rot,(q_r-1)*MINS_Q_R)
                    if t_r>ti_r: ivs_rot.append((float(ti_r),float(t_r)))
                elif "Final de període" in a_r:
                    if jug_rot in ep_rot:
                        ti_r=ep_rot.pop(jug_rot); fi_r=float(q_r*MINS_Q_R)
                        if fi_r>ti_r: ivs_rot.append((ti_r,fi_r))
            for ti_o in ep_rot.values():
                fi_o=float(df_orig["quart"].max()*MINS_Q_R)
                if fi_o>ti_o: ivs_rot.append((float(ti_o),fi_o))

            if not ivs_rot: continue

            # Minuts des dels intervals reals (igual que a Rotacions)
            min_rot = round(sum(tf-ti for ti,tf in ivs_rot), 1)
            if min_rot < 0.5: continue

            # +/- des dels mateixos intervals
            pf_rot=pc_rot=0
            for ti_r,tf_r in ivs_rot:
                df_i_rot=df_t_rot[(df_t_rot["t_abs"]>=ti_r)&(df_t_rot["t_abs"]<=tf_r)]
                pf_rot+=int(df_i_rot[df_i_rot["idEquip"]==eq_rot]["punts"].sum())
                pc_rot+=int(df_i_rot[df_i_rot["idEquip"]==rival_id_rot]["punts"].sum())
            pm_rot = pf_rot - pc_rot
            pm_min_rot = pm_rot / min_rot if min_rot > 0 else 0
            rot_data.append({"equip": eq_rot, "jugadora": jug_rot, "minuts": min_rot, "pm_min": pm_min_rot})

    # Calcula ROT per equip
    for eq_rot in teams:
        df_rot_eq = pd.DataFrame([r for r in rot_data if r["equip"]==eq_rot])
        if df_rot_eq.empty or len(df_rot_eq) < 3: continue

        from scipy import stats as sp_stats_rot
        rho_rot, pval_rot = sp_stats_rot.pearsonr(df_rot_eq["minuts"], df_rot_eq["pm_min"])
        rot_val = round(5 * (rho_rot + 1), 2)

        eq_nom_rot = nom_a if eq_rot==teams[0] else nom_b
        color_rot = COLOR_A if eq_rot==teams[0] else COLOR_B

        if rot_val >= 7.5: rot_interp = "🟢 Rotacions excel·lents"
        elif rot_val >= 5.5: rot_interp = "🟡 Rotacions bones"
        elif rot_val >= 3.5: rot_interp = "🟠 Rotacions millorables"
        else: rot_interp = "🔴 Rotacions per revisar"

        with st.container():
            st.markdown(f'<div style="font-size:13px;font-weight:700;color:{color_rot};margin-bottom:6px">🏀 {eq_nom_rot}</div>', unsafe_allow_html=True)
            c1,c2,c3,c4 = st.columns(4)
            with c1: st.markdown(card("ROT", f"{rot_val}/10", rot_interp, color_rot), unsafe_allow_html=True)
            with c2: st.markdown(card("Pearson (ρ)", f"{rho_rot:+.3f}", "minuts vs +/-/min", color_rot), unsafe_allow_html=True)
            with c3: st.markdown(card("p-value", f"{pval_rot:.3f}", "sig. si <0.05", "#374151"), unsafe_allow_html=True)
            with c4: st.markdown(card("Jugadores", len(df_rot_eq), "analitzades", "#374151"), unsafe_allow_html=True)

            # Scatter Minuts vs +/- per minut
            import numpy as np
            fig_rot = go.Figure()
            colors_rot = [COLOR_A if eq_rot==teams[0] else COLOR_B] * len(df_rot_eq)
            fig_rot.add_trace(go.Scatter(
                x=df_rot_eq["minuts"], y=df_rot_eq["pm_min"],
                mode="markers+text",
                marker=dict(size=10, color=color_rot, line=dict(width=1, color="white")),
                text=df_rot_eq["jugadora"].apply(lambda n: n.split()[1] if len(n.split())>1 else n),
                textposition="top center", textfont=dict(size=8),
                hovertemplate="<b>%{text}</b><br>Minuts: %{x:.1f}<br>+/- per min: %{y:+.3f}<extra></extra>"
            ))
            m_rot, b_rot = np.polyfit(df_rot_eq["minuts"], df_rot_eq["pm_min"], 1)
            x_lr = [df_rot_eq["minuts"].min(), df_rot_eq["minuts"].max()]
            y_lr = [m_rot*x+b_rot for x in x_lr]
            fig_rot.add_trace(go.Scatter(
                x=x_lr, y=y_lr, mode="lines",
                line=dict(color="#d97706", width=2, dash="dot"),
                name=f"Tendència (ρ={rho_rot:+.3f})", showlegend=True))
            fig_rot.add_hline(y=0, line_dash="solid", line_color="#e2e4e8")
            fig_rot.update_xaxes(title="Minuts jugats")
            fig_rot.update_yaxes(title="+/- per minut")
            st.plotly_chart(chart_style(fig_rot, 260, f"{eq_nom_rot} — ROT {rot_val}/10 (ρ={rho_rot:+.3f})"), use_container_width=True)

    # ── Exporta Excel ───────────────────────────────────────────────────────
    st.markdown(sec("Exporta a Excel"), unsafe_allow_html=True)
    st.caption("Excel amb totes les mètriques avançades de tots els partits de la base de dades.")
    if st.button("⬇ Descarregar Excel d'anàlisi complet", key="btn_excel_analisi"):
        excel_data = genera_excel_analisi()
        if excel_data:
            st.download_button(
                label="📥 Clic per descarregar",
                data=excel_data,
                file_name=f"miki_analisi_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_excel_analisi"
            )
        else:
            st.info("No hi ha partits a la base de dades.")

with t_onoff:
    st.markdown(sec("⚡ Eficiència i On/Off Rating per jugadora"), unsafe_allow_html=True)
    st.caption(
        "On/Off Net Rating = diferència de Net Rating (pts/100 poss) quan la jugadora és a pista vs quan no hi és. "
        "Exemple: +5.2 = l'equip guanya 5.2 pts més per 100 poss amb la jugadora. "
        "⚠️ = poques possessions Off, valor poc fiable."
    )
    df_pr_onoff = load_partits_db()
    if df_pr_onoff.empty:
        st.info("Carrega partits per veure l'On/Off Rating.")
    else:
        ids_onoff = df_pr_onoff["match_id"].tolist()
        sel_onoff = st.selectbox("Selecciona un partit", ids_onoff,
            format_func=lambda x: f"{df_pr_onoff[df_pr_onoff['match_id']==x]['nom_a'].values[0]} vs "
                                   f"{df_pr_onoff[df_pr_onoff['match_id']==x]['nom_b'].values[0]} "
                                   f"({df_pr_onoff[df_pr_onoff['match_id']==x]['data_consulta'].values[0][:10]})",
            key="sel_onoff2")
        df_onoff2 = load_jugades_db(sel_onoff)
        if not df_onoff2.empty:
            teams_oo2 = get_teams_ordered(df_onoff2)
            p_row2 = df_pr_onoff[df_pr_onoff["match_id"]==sel_onoff].iloc[0]
            tn_oo2 = {}
            if len(teams_oo2)>=1: tn_oo2[teams_oo2[0]] = p_row2["nom_a"]
            if len(teams_oo2)>=2: tn_oo2[teams_oo2[1]] = p_row2["nom_b"]
            df_onoff2["equip_nom"] = df_onoff2["idEquip"].map(tn_oo2).fillna("?")
            df_onoff2["jugador"] = df_onoff2.get("jugadora", df_onoff2.get("jugador",""))
            st.markdown("**Eficiències d'equip**")
            ef2 = calc_eficiencies(df_onoff2, teams_oo2, tn_oo2)
            col_ea2, col_eb2 = st.columns(2)
            for col_e2, tid2 in [(col_ea2, teams_oo2[0] if teams_oo2 else None),
                                  (col_eb2, teams_oo2[1] if len(teams_oo2)>1 else None)]:
                with col_e2:
                    if tid2 and tid2 in ef2:
                        e2 = ef2[tid2]
                        tcol2 = COLOR_A if tid2 == teams_oo2[0] else COLOR_B
                        c1,c2,c3,c4 = st.columns(4)
                        with c1: st.markdown(card("Possessions", e2["poss_of"], "", tcol2), unsafe_allow_html=True)
                        with c2: st.markdown(card("Off Rating", e2["off_rtg"], "pts/100 poss", tcol2), unsafe_allow_html=True)
                        with c3: st.markdown(card("Def Rating", e2["def_rtg"], "pts/100 poss", "#dc2626"), unsafe_allow_html=True)
                        nc2 = "#16a34a" if e2["net_rtg"] >= 0 else "#dc2626"
                        with c4: st.markdown(card("Net Rating",
                            f"{'+'if e2['net_rtg']>=0 else ''}{e2['net_rtg']}",
                            e2["nom"], nc2), unsafe_allow_html=True)
            st.markdown("**On/Off Rating per jugadora**")
            eq_oo2 = st.selectbox("Equip", [tn_oo2.get(t,"?") for t in teams_oo2], key="eq_oo2")
            tid_oo2 = teams_oo2[0] if eq_oo2 == tn_oo2.get(teams_oo2[0],"?") else (teams_oo2[1] if len(teams_oo2)>1 else None)
            if tid_oo2:
                col_jug2 = "jugadora" if "jugadora" in df_onoff2.columns else "jugador"
                jugs_oo2 = sorted(df_onoff2[
                    (df_onoff2["idEquip"]==tid_oo2) & (df_onoff2[col_jug2] != "")
                ][col_jug2].unique().tolist())
                oo_rows2 = []
                for jug2 in jugs_oo2:
                    df_jug_oo2 = df_onoff2.copy()
                    df_jug_oo2["jugador"] = df_jug_oo2[col_jug2]
                    oo2 = calc_onoff(df_jug_oo2, jug2, tid_oo2, teams_oo2)
                    if oo2:
                        if oo2 and oo2.get("diff") is not None:
                            off_poss = oo2.get("off_poss", 0)
                            fiable = off_poss >= 4
                            label_diff = f"{'+'if oo2['diff']>=0 else ''}{oo2['diff']}"
                            if not fiable:
                                label_diff += " ⚠️"
                            oo_rows2.append({
                                "Jugadora": jug2,
                                "On Poss": oo2.get("on_poss","—"),
                                "On Off Rtg": oo2["on_off_rtg"] if oo2["on_off_rtg"] is not None else "N/D",
                                "On Def Rtg": oo2["on_def_rtg"] if oo2["on_def_rtg"] is not None else "N/D",
                                "On Net Rtg": oo2["on_net_rtg"] if oo2["on_net_rtg"] is not None else "N/D",
                                "Off Poss": off_poss,
                                "Off Off Rtg": oo2["off_off_rtg"] if oo2["off_off_rtg"] is not None else "N/D",
                                "Off Def Rtg": oo2["off_def_rtg"] if oo2["off_def_rtg"] is not None else "N/D",
                                "Off Net Rtg": oo2["off_net_rtg"] if oo2["off_net_rtg"] is not None else "N/D",
                                "Diferència": label_diff,
                                "_diff": oo2["diff"],
                                "_fiable": fiable
                            })
                        elif oo2:
                            oo_rows2.append({
                                "Jugadora": jug2,
                                "On Poss": oo2.get("on_poss","—"),
                                "On Off Rtg": "N/D", "On Def Rtg": "N/D", "On Net Rtg": "N/D",
                                "Off Poss": oo2.get("off_poss","—"),
                                "Off Off Rtg": "N/D", "Off Def Rtg": "N/D", "Off Net Rtg": "N/D",
                                "Diferència": "N/D (poques poss.)", "_diff": 0, "_fiable": False
                            })
                if oo_rows2:
                    df_oo2 = pd.DataFrame(oo_rows2).sort_values("_diff", ascending=False)
                    colors_bar2 = []
                    for _, row_oo in df_oo2.iterrows():
                        if not row_oo.get("_fiable", True):
                            colors_bar2.append("#d97706")  # taronja = poc fiable
                        elif row_oo["_diff"] >= 0:
                            colors_bar2.append("#16a34a")
                        else:
                            colors_bar2.append("#dc2626")
                    fig_oo2 = go.Figure()
                    fig_oo2.add_trace(go.Bar(
                        x=df_oo2["Jugadora"], y=df_oo2["_diff"],
                        marker_color=colors_bar2,
                        text=[f"{'+'if d>=0 else ''}{d}" for d in df_oo2["_diff"]],
                        textposition="outside"))
                    fig_oo2.add_hline(y=0, line_dash="solid", line_color="#e2e4e8")
                    fig_oo2.update_layout(
                        yaxis_title="On - Off Net Rating",
                        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                        font=dict(color="#374151", family="Inter"),
                        margin=dict(l=0,r=0,t=30,b=0), height=280)
                    st.plotly_chart(fig_oo2, use_container_width=True)
                    with st.expander("Veure detall complet"):
                        st.caption("On = quan la jugadora és a pista · Off = quan no hi és · ⚠️ = poques possessions Off, valor poc fiable")
                        # Usa taula HTML en lloc de st.dataframe per evitar problemes de CSS
                        df_show_oo = df_oo2.drop(columns=["_diff","_fiable"], errors="ignore")
                        cols_oo = list(df_show_oo.columns)
                        html_oo = '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px;color:#1a2744">'
                        html_oo += '<tr>' + ''.join(f'<th style="background:#D6E8F7;color:#0C447C;padding:6px 10px;text-align:center;border:1px solid #B5D4F4;font-weight:600">{c}</th>' for c in cols_oo) + '</tr>'
                        for _, row_oo in df_show_oo.iterrows():
                            html_oo += '<tr>'
                            for ci_oo, col_oo in enumerate(cols_oo):
                                val_oo = row_oo[col_oo]
                                bg = '#ffffff' if ci_oo > 0 else '#EBF4FC'
                                align = 'left' if ci_oo == 0 else 'center'
                                html_oo += f'<td style="padding:5px 10px;border:1px solid #B5D4F4;background:{bg};color:#1a2744;text-align:{align}">{val_oo}</td>'
                            html_oo += '</tr>'
                        html_oo += '</table></div>'
                        st.markdown(html_oo, unsafe_allow_html=True)
                else:
                    st.info("No hi ha prou dades per calcular l'On/Off Rating.")

            # ── TS% On/Off ──────────────────────────────────────────────────
            st.markdown(sec("🎯 TS% de l'equip — On/Off per jugadora"), unsafe_allow_html=True)
            st.caption(
                "TS% (True Shooting%) de l'EQUIP quan la jugadora és a pista (ON) vs quan no hi és (OFF). "
                "Mostra si l'eficiència de tir de l'equip millora o empitjora amb ella en pista."
            )
            if tid_oo2:
                ts_rows2 = []
                for jug2 in jugs_oo2:
                    df_jug_ts2 = df_onoff2.copy()
                    df_jug_ts2["jugador"] = df_jug_ts2[col_jug2]
                    ts2 = calc_onoff_ts(df_jug_ts2, jug2, tid_oo2, teams_oo2)
                    if ts2 and ts2["diff_ts"] is not None:
                        fiable_ts = ts2["tc_off"] >= 4
                        label_ts = f"{'+'if ts2['diff_ts']>=0 else ''}{ts2['diff_ts']}"
                        if not fiable_ts:
                            label_ts += " ⚠️"
                        ts_rows2.append({
                            "Jugadora": jug2,
                            "TC ON": ts2["tc_on"],
                            "TS% ON": ts2["ts_on"],
                            "TC OFF": ts2["tc_off"],
                            "TS% OFF": ts2["ts_off"] if ts2["ts_off"] is not None else "N/D",
                            "Diferència": label_ts,
                            "_diff": ts2["diff_ts"],
                            "_fiable": fiable_ts
                        })

                if ts_rows2:
                    df_ts2 = pd.DataFrame(ts_rows2).sort_values("_diff", ascending=False)
                    colors_ts2 = []
                    for _, row_ts in df_ts2.iterrows():
                        if not row_ts.get("_fiable", True):
                            colors_ts2.append("#d97706")
                        elif row_ts["_diff"] >= 0:
                            colors_ts2.append("#16a34a")
                        else:
                            colors_ts2.append("#dc2626")
                    fig_ts2 = go.Figure()
                    fig_ts2.add_trace(go.Bar(
                        x=df_ts2["Jugadora"], y=df_ts2["_diff"],
                        marker_color=colors_ts2,
                        text=[f"{'+'if d>=0 else ''}{d}" for d in df_ts2["_diff"]],
                        textposition="outside"))
                    fig_ts2.add_hline(y=0, line_dash="solid", line_color="#e2e4e8")
                    fig_ts2.update_layout(
                        yaxis_title="TS% ON - TS% OFF (punts percentuals)",
                        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                        font=dict(color="#374151", family="Inter"),
                        margin=dict(l=0,r=0,t=30,b=0), height=280)
                    st.plotly_chart(fig_ts2, use_container_width=True)

                    millor_ts = df_ts2.iloc[0]
                    pitjor_ts = df_ts2.iloc[-1]
                    st.info(f"📊 Amb **{millor_ts['Jugadora']}** a pista el TS% de l'equip puja "
                            f"{millor_ts['_diff']:+.1f} punts. Amb **{pitjor_ts['Jugadora']}** "
                            f"baixa {pitjor_ts['_diff']:+.1f} punts.")

                    with st.expander("Veure detall complet TS%"):
                        st.caption("ON = quan la jugadora és a pista · OFF = quan no hi és · TC = tirs de camp intentats · ⚠️ = pocs tirs OFF, valor poc fiable")
                        df_show_ts = df_ts2.drop(columns=["_diff","_fiable"], errors="ignore")
                        cols_ts = list(df_show_ts.columns)
                        html_ts = '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px;color:#1a2744">'
                        html_ts += '<tr>' + ''.join(f'<th style="background:#D6E8F7;color:#0C447C;padding:6px 10px;text-align:center;border:1px solid #B5D4F4;font-weight:600">{c}</th>' for c in cols_ts) + '</tr>'
                        for _, row_ts in df_show_ts.iterrows():
                            html_ts += '<tr>'
                            for ci_ts, col_ts in enumerate(cols_ts):
                                val_ts = row_ts[col_ts]
                                bg_ts = '#ffffff' if ci_ts > 0 else '#EBF4FC'
                                align_ts = 'left' if ci_ts == 0 else 'center'
                                html_ts += f'<td style="padding:5px 10px;border:1px solid #B5D4F4;background:{bg_ts};color:#1a2744;text-align:{align_ts}">{val_ts}</td>'
                            html_ts += '</tr>'
                        html_ts += '</table></div>'
                        st.markdown(html_ts, unsafe_allow_html=True)
                else:
                    st.info("No hi ha prou dades per calcular el TS% On/Off.")

            # ── TS% vs Δ Net Rtg (Talent vs Optimization) ────────────────────
            st.markdown(sec("🧭 TS% vs Δ Net Rtg — Talent vs Optimization"), unsafe_allow_html=True)
            st.caption(
                "TS% (eix X) = eficiència de tir individual (\"Talent\") · "
                "Δ Net Rtg ON−OFF (eix Y) = com millora el Net Rating de l'equip quan ella és a pista "
                "(\"Optimization\") · Mida del punt = tirs de camp intentats."
            )
            rows_to = []
            for jug_to in jugs_oo2:
                df_jug_to = df_onoff2.copy()
                df_jug_to["jugador"] = df_jug_to[col_jug2]
                dj_to = df_jug_to[df_jug_to["jugador"] == jug_to]
                tc_conv_to = int(dj_to["accio"].str.contains(
                    "Cistella de 2|Cistella de 3", case=False, na=False).sum())
                tc_int_to = tc_conv_to + int(dj_to["accio"].str.contains(
                    "Intent fallat de 2|Intent fallat de 3|fallat de 2|fallat de 3", case=False, na=False).sum())
                tl_conv_to = int(dj_to["accio"].str.contains("Cistella de 1", case=False, na=False).sum())
                tl_int_to = tl_conv_to + int(dj_to["accio"].str.contains(
                    "Intent fallat de 1", case=False, na=False).sum())
                pts_to = int(dj_to["punts"].sum())
                ts_denom_to = 2 * (tc_int_to + 0.44 * tl_int_to)
                if ts_denom_to == 0:
                    continue
                oo_to = calc_onoff(df_jug_to, jug_to, tid_oo2, teams_oo2)
                if not oo_to or oo_to.get("diff") is None or oo_to.get("off_poss", 0) < 4:
                    continue
                rows_to.append({
                    "Jugadora": jug_to,
                    "TS%": round(pts_to / ts_denom_to * 100, 1),
                    "delta_net_rtg": oo_to["diff"],
                    "_n_tirs": max(tc_int_to, 1),
                })
            df_talent_opt = pd.DataFrame(rows_to)

            if df_talent_opt.empty:
                st.info(
                    "Cal que les jugadores hagin jugat amb i sense l'equip (mínim 4 possessions OFF) per "
                    "calcular el Δ Net Rtg. Carrega partits amb rotacions per activar aquest gràfic."
                )
            else:
                fig_to = go.Figure()
                color_to = COLOR_A if tid_oo2 == teams_oo2[0] else COLOR_B
                sizes_to = df_talent_opt["_n_tirs"].clip(lower=1)
                sizes_norm_to = (sizes_to / sizes_to.max() * 18 + 8).round(0)
                fig_to.add_trace(go.Scatter(
                    x=df_talent_opt["TS%"], y=df_talent_opt["delta_net_rtg"],
                    mode="markers+text", name=eq_oo2,
                    marker=dict(size=sizes_norm_to, color=color_to,
                                line=dict(width=1.5, color=C_WHITE), opacity=0.85),
                    text=df_talent_opt["Jugadora"].apply(lambda n: n.split()[1] if len(n.split())>1 else n),
                    textposition="top center", textfont=dict(size=9),
                    hovertemplate="<b>%{text}</b><br>TS%: %{x:.1f}%<br>Δ Net Rtg: %{y:+.1f}<extra></extra>",
                ))

                mitj_ts_to = df_talent_opt["TS%"].mean()
                mitj_net_to = df_talent_opt["delta_net_rtg"].mean()
                fig_to.add_vline(x=mitj_ts_to, line_dash="dot", line_color=C_CARD_BORDER,
                    annotation_text=f"Mitjana TS% {mitj_ts_to:.0f}%",
                    annotation_font_size=9, annotation_font_color=C_LABEL)
                fig_to.add_hline(y=mitj_net_to, line_dash="dot", line_color=C_CARD_BORDER,
                    annotation_text=f"Mitjana Δ Net Rtg {mitj_net_to:+.0f}",
                    annotation_font_size=9, annotation_font_color=C_LABEL)
                fig_to.add_vline(x=50, line_dash="dash", line_color=C_CARD_BORDER,
                    annotation_text="TS% 50%", annotation_font_size=8, annotation_font_color=C_CARD_BORDER)
                fig_to.add_hline(y=0, line_dash="solid", line_color=C_CARD_BORDER)

                x_max_to = df_talent_opt["TS%"].max()
                x_min_to = df_talent_opt["TS%"].min()
                y_max_to = df_talent_opt["delta_net_rtg"].max()
                y_min_to = df_talent_opt["delta_net_rtg"].min()
                for txt, xq, yq, cq in [
                    ("⭐ Gran talent i impacte", x_max_to * 0.97, y_max_to * 0.90, C_SUCCESS),
                    ("🛡️ Impacte sense anotació", x_min_to * 1.05, y_max_to * 0.90, C_ACCENT),
                    ("🎯 Anota però no eleva", x_max_to * 0.97, y_min_to * 0.90, C_WARNING),
                    ("🔄 Poc impacte global", x_min_to * 1.05, y_min_to * 0.90, C_LABEL),
                ]:
                    fig_to.add_annotation(x=xq, y=yq, text=txt, showarrow=False,
                        font=dict(size=9, color=cq), xanchor="center", yanchor="middle", opacity=0.5)

                fig_to.update_xaxes(title="TS% — Eficiència de tir (Talent)")
                fig_to.update_yaxes(title="Δ Net Rtg ON−OFF (Optimization)")

                st.plotly_chart(
                    chart_style(fig_to, 420, "TS% vs Δ Net Rtg — Talent vs Optimization ofensiu"),
                    use_container_width=True)

            # ── Lineup Impact Tool ────────────────────────────────────────────
            st.markdown(sec("🧩 Lineup Impact Tool"), unsafe_allow_html=True)
            st.caption(
                "Compara el rendiment de l'equip amb un lineup concret a pista ('Amb aquest lineup') "
                "enfront de la resta del partit. 'A pista' = han de ser-hi TOTES; 'Fora de pista' = cap "
                "d'elles hi pot ser. Mínim 4 possessions per ser fiable."
            )
            if tid_oo2:
                col_li1, col_li2 = st.columns(2)
                with col_li1:
                    jugs_on_li = st.multiselect(
                        "A pista (ON) — màx. 5", jugs_oo2, key="li_on", max_selections=5)
                with col_li2:
                    jugs_off_li = st.multiselect(
                        "Fora de pista (OFF)",
                        [j for j in jugs_oo2 if j not in jugs_on_li], key="li_off")

                n_quarts_li = int(df_onoff2["quart"].max()) if not df_onoff2.empty else 4
                usar_rang_li = st.checkbox("Limitar a un rang de quarts", key="li_rang")
                quart_ini_li, quart_fi_li = None, None
                if usar_rang_li:
                    quart_ini_li, quart_fi_li = st.select_slider(
                        "Rang de quarts", options=list(range(1, n_quarts_li+1)),
                        value=(1, n_quarts_li), key="li_quarts")

                if st.button("Calcular", key="li_calcula"):
                    if not jugs_on_li:
                        st.warning("Selecciona com a mínim una jugadora que hagi d'estar a pista.")
                    else:
                        df_li = df_onoff2.copy()
                        df_li["jugador"] = df_li[col_jug2]
                        res_li = calc_lineup_impact(
                            df_li, jugs_on_li, jugs_off_li, tid_oo2, teams_oo2,
                            quart_ini_li, quart_fi_li)
                        if not res_li:
                            st.info("No hi ha prou dades per calcular aquest lineup.")
                        else:
                            col_lu, col_re = st.columns(2)
                            for col_x, bucket_key, titol_x in [
                                (col_lu, "lineup", "Amb aquest lineup"),
                                (col_re, "resta", "Resta del partit"),
                            ]:
                                b = res_li[bucket_key]
                                with col_x:
                                    st.markdown(f"**{titol_x}**")
                                    if b["minuts"] <= 0:
                                        st.caption("— Sense minuts en aquesta situació —")
                                        continue
                                    c1li, c2li, c3li = st.columns(3)
                                    with c1li:
                                        st.markdown(card("Minuts", b["minuts"], "", COLOR_A), unsafe_allow_html=True)
                                    with c2li:
                                        off_txt = b["off_rtg"] if b["off_rtg"] is not None else "—"
                                        st.markdown(card("Off Rtg", off_txt, "pts/100 poss", COLOR_A), unsafe_allow_html=True)
                                    with c3li:
                                        def_txt = b["def_rtg"] if b["def_rtg"] is not None else "—"
                                        st.markdown(card("Def Rtg", def_txt, "pts/100 poss", "#dc2626"), unsafe_allow_html=True)
                                    if b["net_rtg"] is not None:
                                        nc_li = "#16a34a" if b["net_rtg"] >= 0 else "#dc2626"
                                        st.markdown(card("Net Rating",
                                            f"{'+' if b['net_rtg']>=0 else ''}{b['net_rtg']}",
                                            f"{b['pts_of']}-{b['pts_def']} pts", nc_li), unsafe_allow_html=True)
                                    else:
                                        st.caption("⚠️ Poques possessions per un rating fiable")

            # ── On/Off Rating agregat multi-partit ──────────────────────────────
            st.markdown(sec("📐 On/Off Rating agregat — tota la temporada"), unsafe_allow_html=True)
            st.caption(
                "Suma punts i possessions ON/OFF de TOTS els partits carregats abans de dividir "
                "(Net Rating = 100 × Σ(Pts fets − Pts rebuts) / Σ(Possessions)), en lloc de fer la "
                "mitjana dels Net Ratings de cada partit per separat — així un partit amb pocs minuts "
                "no pesa igual que un amb molts."
            )
            col_mp1, col_mp2 = st.columns(2)
            with col_mp1:
                min_poss_on_ui = st.number_input("Mínim possessions ON per ser fiable",
                    min_value=0, value=150, step=10, key="min_poss_on_agr")
            with col_mp2:
                min_poss_off_ui = st.number_input("Mínim possessions OFF per ser fiable",
                    min_value=0, value=150, step=10, key="min_poss_off_agr")

            df_p_agr = load_partits_db()
            if df_p_agr.empty:
                st.info("Carrega partits per veure l'On/Off Rating agregat.")
            else:
                res_onoff_agr = calc_onoff_agregat(df_p_agr, min_poss_on_ui, min_poss_off_ui)
                if not res_onoff_agr:
                    st.info("No hi ha dades suficients per calcular l'On/Off Rating agregat.")
                else:
                    df_onoff_agr = pd.DataFrame(res_onoff_agr)
                    df_onoff_agr = df_onoff_agr[df_onoff_agr["onoff_agregat"].notna()].sort_values(
                        "onoff_agregat", ascending=False)

                    st.caption(f"🟢 impacte positiu · 🔴 impacte negatiu · 🟠 mostra no fiable "
                        f"(per sota del llindar de {min_poss_on_ui} poss ON / {min_poss_off_ui} poss OFF)")

                    cols_agr_html = ["Jugadora","Equip","Partits","Poss ON","Poss OFF",
                        "Net Rtg ON","Net Rtg OFF","On/Off Agregat","Mostra fiable"]
                    html_agr = '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px;color:#1a2744">'
                    html_agr += '<tr>' + ''.join(f'<th style="background:#D6E8F7;color:#0C447C;padding:6px 10px;text-align:center;border:1px solid #B5D4F4;font-weight:600">{c}</th>' for c in cols_agr_html) + '</tr>'
                    for i_agr, (_, row_agr) in enumerate(df_onoff_agr.iterrows()):
                        bg_agr = '#ffffff' if i_agr % 2 == 0 else '#EBF4FC'
                        if not row_agr["fiable"]:
                            onoff_bg, onoff_fg = '#FFF3CD', '#854F0B'
                        elif row_agr["onoff_agregat"] >= 0:
                            onoff_bg, onoff_fg = '#D5F5E3', '#0F6E56'
                        else:
                            onoff_bg, onoff_fg = '#FADBD8', '#993C1D'
                        onoff_txt = f"{'+' if row_agr['onoff_agregat']>=0 else ''}{row_agr['onoff_agregat']}"
                        fiab_txt = "✅ Sí" if row_agr["fiable"] else "⚠️ No"
                        vals_agr = [row_agr["jugadora"], row_agr["equip_nom"], row_agr["partits"],
                            row_agr["poss_on"], row_agr["poss_off"], row_agr["net_on"], row_agr["net_off"]]
                        html_agr += '<tr>'
                        for ci_agr, v_agr in enumerate(vals_agr):
                            align_agr = 'left' if ci_agr in (0,1) else 'center'
                            html_agr += f'<td style="padding:5px 10px;border:1px solid #B5D4F4;background:{bg_agr};color:#1a2744;text-align:{align_agr}">{v_agr}</td>'
                        html_agr += f'<td style="padding:5px 10px;border:1px solid #B5D4F4;background:{onoff_bg};color:{onoff_fg};text-align:center;font-weight:700">{onoff_txt}</td>'
                        html_agr += f'<td style="padding:5px 10px;border:1px solid #B5D4F4;background:{bg_agr};color:#1a2744;text-align:center">{fiab_txt}</td>'
                        html_agr += '</tr>'
                    html_agr += '</table></div>'
                    st.markdown(html_agr, unsafe_allow_html=True)

                    # ── Descomposició de context ──────────────────────────────────
                    st.markdown(sec("🧭 Context de l'On/Off — mèrit individual o companya habitual?"),
                        unsafe_allow_html=True)
                    st.caption(
                        "Un On/Off alt pot ser mèrit real de la jugadora, o pot venir 'prestat' per jugar "
                        "gairebé sempre amb la mateixa companya forta. Aquí es divideixen els seus minuts ON "
                        "entre 'amb la seva companya més freqüent' i 'sense ella': si el Net Rating es manté "
                        "alt als dos costats, és mèrit individual; si només es manté a un, és efecte de context. "
                        "⚠️ No inclou la força del rival (no hi ha una font fiable d'això amb les dades actuals) "
                        "— és un indicador basat només en concentració de companyes i consistència del Net Rating."
                    )
                    min_poss_seg_ui = st.number_input(
                        "Mínim possessions per segment (amb/sense bloc) per considerar-lo fiable",
                        min_value=0, value=40, step=5, key="min_poss_seg_ctx")

                    res_context = calc_context_onoff(df_p_agr, min_poss_seg=min_poss_seg_ui)
                    if not res_context:
                        st.info("No hi ha dades suficients per calcular la descomposició de context.")
                    else:
                        onoff_map = {r["jugadora"]: r["onoff_agregat"] for r in res_onoff_agr}
                        df_ctx = pd.DataFrame(res_context)
                        df_ctx["onoff_agregat"] = df_ctx["jugadora"].map(onoff_map)
                        df_ctx = df_ctx[df_ctx["onoff_agregat"].notna()].sort_values(
                            "onoff_agregat", ascending=False)

                        df_show_ctx = df_ctx[[
                            "jugadora","equip_nom","onoff_agregat","bloc_habitual","pct_bloc_top",
                            "net_amb_bloc","net_sense_bloc","fiabilitat_context"
                        ]].copy()
                        for col_ctx in ["net_amb_bloc","net_sense_bloc"]:
                            df_show_ctx[col_ctx] = df_show_ctx[col_ctx].apply(lambda v: v if v is not None else "—")
                        df_show_ctx.columns = ["Jugadora","Equip","On/Off Agregat","Bloc habitual (companyes)",
                            "% min ON amb top companya","Net amb bloc","Net sense bloc","Fiabilitat de context"]
                        st.dataframe(df_show_ctx, use_container_width=True, hide_index=True)

with t5:
    # ══════════════════════════════════════════════════
    # PESTANYA ROTACIONS
    # ══════════════════════════════════════════════════

    # ── Càlcul de minuts reals per jugadora des de l'API ──────────────────
    def get_intervals_jugadores(df):
        """Retorna dict jugadora -> [(t_ini, t_fi, equip_id)] en minuts absoluts de partit."""
        MINS_Q = 10
        intervals = {}
        en_pista  = {}
        col_j = "jugador" if "jugador" in df.columns else "jugadora"

        # Detecta jugadores que comencen a pista (primer event és Surt sense Entra previ)
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
            # min_num és el minut DINS del quart (cronòmetre enrere: 10→0)
            # El convertim a minut absolut: inici_quart + (MINS_Q - min_dins_quart)
            min_dins = float(row.get("min_num", 0))
            # Si min_num ja és absolut (>10), ho detectem
            if min_dins > MINS_Q:
                t_min = min_dins  # ja és absolut
            else:
                t_min = (quart-1)*MINS_Q + (MINS_Q - min_dins)
            # Clipa al rang vàlid
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
        # Tanca intervals que han quedat oberts
        for j, (ti, ei) in en_pista.items():
            fi = df["quart"].max() * MINS_Q if not df.empty else 40
            if fi > ti:
                intervals.setdefault(j, []).append((ti, fi, ei))
        return intervals

    intervals_jug = get_intervals_jugadores(df_orig)
    score_df_rot = score_df.copy() if not score_df.empty else pd.DataFrame()

    # ── 1. Gràfic de quintets (Gantt de rotacions) ────────────────────────
    st.markdown(sec("Gràfic de rotacions — qui juga cada minut"), unsafe_allow_html=True)
    st.caption("Cada barra indica un tram de joc d'una jugadora. La línia vermella/blava és el ±parcial de l'equip.")

    eq_rot = st.selectbox("Equip", [nom_a, nom_b], key="rot_eq")
    tid_rot = teams[0] if eq_rot == nom_a else (teams[1] if len(teams)>1 else None)
    color_rot = COLOR_A if eq_rot == nom_a else COLOR_B
    rival_rot = teams[1] if eq_rot == nom_a else (teams[0] if teams else None)

    if tid_rot and intervals_jug:
        # Filtra jugadores de l'equip seleccionat
        jugs_rot = {j: ivs for j,ivs in intervals_jug.items()
                    if any(ei == tid_rot for _,_,ei in ivs)}

        if not jugs_rot:
            st.info("No s'han detectat events d'entrada/sortida per a aquest equip.")
        else:
            # Ordena per primer minut de joc
            jugs_sorted = sorted(jugs_rot.items(), key=lambda x: min(i[0] for i in x[1]))
            n_jugs = len(jugs_sorted)
            MINS_TOTAL = max(df_orig["quart"].max() * 10 if not df_orig.empty else 40, 40)

            fig_rot = go.Figure()

            # Barres de rotació per jugadora
            for yi, (jug, ivs) in enumerate(jugs_sorted):
                for (t_ini, t_fi, ei) in ivs:
                    if ei != tid_rot: continue
                    fig_rot.add_trace(go.Bar(
                        x=[t_fi - t_ini],
                        y=[jug],
                        base=[t_ini],
                        orientation='h',
                        marker_color=color_rot,
                        marker_opacity=0.75,
                        marker_line=dict(width=0.5, color='white'),
                        name=jug,
                        showlegend=False,
                        hovertemplate=f"{jug}<br>Minut {t_ini:.1f}–{t_fi:.1f}<br>Durada: {t_fi-t_ini:.1f} min<extra></extra>"
                    ))

            # Línies de parcial de l'equip (±)
            if not score_df_rot.empty:
                score_df_rot["t_min"] = score_df_rot.apply(
                    lambda r: (int(r["quart"])-1)*10 + (10 - float(r.get("min_num",0)))
                    if float(r.get("min_num",0)) <= 10 else float(r.get("min_num",0)), axis=1)

                parcial_eq  = score_df_rot["scoreA"] if tid_rot == teams[0] else score_df_rot["scoreB"]
                parcial_riv = score_df_rot["scoreB"] if tid_rot == teams[0] else score_df_rot["scoreA"]
                diff_parcial = parcial_eq - parcial_riv

                # Normalitza per mostrar com a línia sobre el gràfic
                d_max = max(abs(diff_parcial.max()), abs(diff_parcial.min()), 1)

                fig_rot.add_trace(go.Scatter(
                    x=score_df_rot["t_min"] if "t_min" in score_df_rot else score_df_rot.index,
                    y=diff_parcial,
                    mode="lines",
                    name="Parcial equip",
                    line=dict(color="#374151", width=1.5, dash="dot"),
                    yaxis="y2",
                    hovertemplate="Minut %{x:.1f}<br>Parcial: %{y:+d}<extra></extra>"
                ))

            # Línies de quart
            for q in range(1, 5):
                fig_rot.add_vline(x=q*10, line_dash="dot", line_color="#e2e4e8",
                    annotation_text=f"Fi Q{q}", annotation_font_size=9,
                    annotation_font_color="#9ca3af")

            fig_rot.update_layout(
                barmode="overlay",
                height=max(280, n_jugs * 36 + 80),
                paper_bgcolor="#ffffff", plot_bgcolor="#f9fafb",
                font=dict(color="#374151", family="Inter"),
                xaxis=dict(title="Minut de joc", range=[0, MINS_TOTAL],
                           showgrid=True, gridcolor="#f3f4f6", color="#9ca3af"),
                yaxis=dict(showgrid=False, color="#374151"),
                yaxis2=dict(overlaying="y", side="right", title="Parcial ±",
                            showgrid=False, zeroline=True, zerolinecolor="#e2e4e8",
                            color="#9ca3af"),
                margin=dict(l=0,r=60,t=20,b=40),
                legend=dict(bgcolor="#ffffff",bordercolor="#e2e4e8",borderwidth=1)
            )
            st.plotly_chart(fig_rot, use_container_width=True)

    # ── 2. +/- per minuts jugats ──────────────────────────────────────────
    st.markdown(sec("+/- per minut jugat"), unsafe_allow_html=True)
    st.caption("Parcial de l'equip per minut jugat per cada jugadora. Valors positius = l'equip guanya mentre juga.")

    if tid_rot and not score_df_rot.empty and intervals_jug:
        pm_rows = []
        for jug, ivs in intervals_jug.items():
            ivs_eq = [(ti,tf) for ti,tf,ei in ivs if ei==tid_rot]
            if not ivs_eq: continue
            total_min = sum(tf-ti for ti,tf in ivs_eq)
            if total_min < 0.5: continue

            # Usa el mateix mètode que la pestanya Jugadores:
            # compta punts del play-by-play durant els intervals
            rival_rot_id = teams[1] if tid_rot == teams[0] else (teams[0] if teams else None)
            parcial_favor = 0; parcial_contra = 0
            for t_ini, t_fi in ivs_eq:
                # Converteix minuts a nums de jugada
                df_interval = df_orig[
                    (df_orig["min_num"].apply(lambda m, q=0: m) >= 0)
                ]
                # Filtra per temps absolut
                df_orig_t = df_orig.copy()
                df_orig_t["t_abs"] = df_orig_t.apply(
                    lambda r: (int(r["quart"])-1)*10 + (10 - float(r["min_num"]))
                    if float(r.get("min_num",0)) <= 10
                    else float(r.get("min_num",0)), axis=1)
                df_interval = df_orig_t[
                    (df_orig_t["t_abs"] >= t_ini) &
                    (df_orig_t["t_abs"] <= t_fi)]
                parcial_favor  += int(df_interval[df_interval["idEquip"]==tid_rot]["punts"].sum())
                if rival_rot_id:
                    parcial_contra += int(df_interval[df_interval["idEquip"]==rival_rot_id]["punts"].sum())

            pm = parcial_favor - parcial_contra
            pm_per_min = round(pm / total_min, 2) if total_min > 0 else 0
            pm_rows.append({
                "Jugadora": jug,
                "Minuts": round(total_min, 1),
                "+/-": pm,
                "+/- per min": pm_per_min
            })

        if pm_rows:
            df_pm = pd.DataFrame(pm_rows).sort_values("+/- per min", ascending=False)

            # Gràfic scatter: X = minuts, Y = +/-
            fig_pm = go.Figure()
            colors_pm = ["#16a34a" if v >= 0 else "#dc2626" for v in df_pm["+/- per min"]]
            fig_pm.add_trace(go.Scatter(
                x=df_pm["Minuts"],
                y=df_pm["+/- per min"],
                mode="markers+text",
                marker=dict(size=12, color=colors_pm,
                            line=dict(width=1.5, color="white")),
                text=df_pm["Jugadora"].apply(lambda n: n.split()[1] if len(n.split())>1 else n),
                textposition="top center",
                textfont=dict(size=9),
                hovertemplate="%{text}<br>Minuts: %{x:.1f}<br>+/- per min: %{y:+.2f}<extra></extra>"
            ))
            fig_pm.add_hline(y=0, line_dash="solid", line_color="#e2e4e8")
            fig_pm.update_layout(
                xaxis=dict(title="Minuts jugats", showgrid=True, gridcolor="#f3f4f6", color="#9ca3af"),
                yaxis=dict(title="+/- per minut", showgrid=True, gridcolor="#f3f4f6", color="#9ca3af",
                           zeroline=True, zerolinecolor="#e2e4e8"),
                paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                font=dict(color="#374151", family="Inter"),
                margin=dict(l=0,r=0,t=20,b=0), height=320)
            st.plotly_chart(fig_pm, use_container_width=True)
            st.dataframe(df_pm, use_container_width=True, hide_index=True)

    # ── 3. +/- per tram de minuts jugats ─────────────────────────────────
    st.markdown(sec("+/- per tram de joc"), unsafe_allow_html=True)
    st.caption("Per cada tram que una jugadora juga seguit, veus el parcial de l'equip minut a minut.")

    if tid_rot and not score_df_rot.empty and intervals_jug:
        jugs_tram = [j for j,ivs in intervals_jug.items()
                     if any(ei==tid_rot for _,_,ei in ivs)]
        jug_tram = st.selectbox("Jugadora", sorted(jugs_tram), key="jug_tram")

        if jug_tram and jug_tram in intervals_jug:
            ivs_jug = [(ti,tf) for ti,tf,ei in intervals_jug[jug_tram] if ei==tid_rot]

            fig_tram = go.Figure()
            colors_tram = [color_rot, "#16a34a", "#d97706", "#6366f1", "#ec4899"]

            for bi, (t_ini, t_fi) in enumerate(ivs_jug):
                if "t_min" in score_df_rot.columns:
                    df_tr = score_df_rot[
                        (score_df_rot["t_min"] >= t_ini) &
                        (score_df_rot["t_min"] <= t_fi)].copy()
                    x_vals = df_tr["t_min"] - t_ini
                else:
                    n_ini = int(t_ini / MINS_TOTAL * len(score_df_rot))
                    n_fi  = int(t_fi  / MINS_TOTAL * len(score_df_rot))
                    df_tr = score_df_rot.iloc[n_ini:n_fi].copy()
                    x_vals = pd.Series(range(len(df_tr))) * (t_fi-t_ini) / max(len(df_tr),1)

                if df_tr.empty: continue

                if tid_rot == teams[0]:
                    parcial_tr = df_tr["scoreA"] - df_tr["scoreA"].iloc[0] -                                  (df_tr["scoreB"] - df_tr["scoreB"].iloc[0])
                else:
                    parcial_tr = df_tr["scoreB"] - df_tr["scoreB"].iloc[0] -                                  (df_tr["scoreA"] - df_tr["scoreA"].iloc[0])

                color_bi = colors_tram[bi % len(colors_tram)]
                fig_tram.add_trace(go.Scatter(
                    x=x_vals,
                    y=parcial_tr,
                    mode="lines+markers",
                    name=f"Tram {bi+1} (min {t_ini:.0f}–{t_fi:.0f})",
                    line=dict(color=color_bi, width=2),
                    marker=dict(size=6, color=color_bi),
                    hovertemplate="Min %{x:.1f} del tram<br>Parcial: %{y:+d}<extra></extra>"
                ))

            fig_tram.add_hline(y=0, line_dash="solid", line_color="#e2e4e8")
            fig_tram.update_layout(
                xaxis=dict(title="Minuts dins del tram", showgrid=True,
                           gridcolor="#f3f4f6", color="#9ca3af"),
                yaxis=dict(title="Parcial ±", showgrid=True,
                           gridcolor="#f3f4f6", color="#9ca3af",
                           zeroline=True, zerolinecolor="#e2e4e8"),
                paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                font=dict(color="#374151", family="Inter"),
                legend=dict(bgcolor="#ffffff", bordercolor="#e2e4e8", borderwidth=1,
                            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=0,r=0,t=40,b=0), height=300)
            st.plotly_chart(fig_tram, use_container_width=True)

    # ── 4. Mapa de calor de parelles ─────────────────────────────────────
    st.markdown(sec("Mapa de calor +/- per parelles"), unsafe_allow_html=True)
    st.caption("Color de cada casella = +/- conjunt de la parella. Verd = l'equip guanya quan juguen juntes.")

    if tid_rot and intervals_jug:
        jugs_eq_all = sorted([j for j,ivs in intervals_jug.items()
                              if any(ei==tid_rot for _,_,ei in ivs)])
        rival_rot_id2 = teams[1] if tid_rot == teams[0] else (teams[0] if teams else None)

        if len(jugs_eq_all) >= 2:
            # Precalcula t_abs per eficiència
            df_orig_tab = df_orig.copy()
            df_orig_tab["t_abs"] = df_orig_tab.apply(
                lambda r: (int(r["quart"])-1)*10 + (10 - float(r["min_num"]))
                if float(r.get("min_num",0)) <= 10
                else float(r.get("min_num",0)), axis=1)

            def pm_parella(j1, j2):
                ivs1 = [(ti,tf) for ti,tf,ei in intervals_jug.get(j1,[]) if ei==tid_rot]
                ivs2 = [(ti,tf) for ti,tf,ei in intervals_jug.get(j2,[]) if ei==tid_rot]
                juntes = []
                for a1,a2 in ivs1:
                    for b1,b2 in ivs2:
                        ini=max(a1,b1); fi=min(a2,b2)
                        if fi > ini: juntes.append((ini,fi))
                if not juntes: return None
                pf=pc=0
                for ti,tf in juntes:
                    df_j = df_orig_tab[(df_orig_tab["t_abs"]>=ti)&(df_orig_tab["t_abs"]<=tf)]
                    pf += int(df_j[df_j["idEquip"]==tid_rot]["punts"].sum())
                    if rival_rot_id2:
                        pc += int(df_j[df_j["idEquip"]==rival_rot_id2]["punts"].sum())
                return pf - pc

            # Construeix matriu
            n = len(jugs_eq_all)
            matrix = [[None]*n for _ in range(n)]
            for i,j1 in enumerate(jugs_eq_all):
                for j,j2 in enumerate(jugs_eq_all):
                    if i == j:
                        matrix[i][j] = 0
                    elif i < j:
                        val = pm_parella(j1, j2)
                        matrix[i][j] = val
                        matrix[j][i] = val

            # Noms curts per a l'eix
            noms_curts = [n.split()[1] if len(n.split())>1 else n for n in jugs_eq_all]

            # Substitueix None per 0 per al heatmap
            z_vals = [[v if v is not None else 0 for v in row] for row in matrix]
            text_vals = [[f"+{v}" if v is not None and v > 0
                          else (str(v) if v is not None else "—")
                          for v in row] for row in matrix]

            fig_hm = go.Figure(go.Heatmap(
                z=z_vals,
                x=noms_curts,
                y=noms_curts,
                text=text_vals,
                texttemplate="%{text}",
                textfont=dict(size=11, color="white"),
                colorscale=[
                    [0.0, "#dc2626"],
                    [0.5, "#f9fafb"],
                    [1.0, "#16a34a"]
                ],
                zmid=0,
                showscale=True,
                colorbar=dict(title="+/-", thickness=12)
            ))
            fig_hm.update_layout(
                height=max(320, n*48+80),
                paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                font=dict(color="#374151", family="Inter", size=11),
                xaxis=dict(side="top", tickangle=-30),
                margin=dict(l=0,r=60,t=60,b=0)
            )
            st.plotly_chart(fig_hm, use_container_width=True)
            st.caption("Diagonal = la pròpia jugadora (0). Caselles buides = no han jugat juntes.")
        else:
            st.info("Cal tenir almenys 2 jugadores amb events d'entrada/sortida.")

    # ── 5. +/- per parella (detall) ───────────────────────────────────────
    st.markdown(sec("+/- per parella de jugadores (detall)"), unsafe_allow_html=True)
    st.caption("Parcial de l'equip durant els minuts que les dues jugadores seleccionades han jugat juntes.")

    if tid_rot and intervals_jug:
        jugs_par = [j for j,ivs in intervals_jug.items()
                    if any(ei==tid_rot for _,_,ei in ivs)]
        col_p1, col_p2 = st.columns(2)
        with col_p1: jug_p1 = st.selectbox("Jugadora 1", sorted(jugs_par), key="par_j1")
        with col_p2: jug_p2 = st.selectbox("Jugadora 2",
            [j for j in sorted(jugs_par) if j != jug_p1], key="par_j2")

        if jug_p1 and jug_p2:
            ivs1 = [(ti,tf) for ti,tf,ei in intervals_jug.get(jug_p1,[]) if ei==tid_rot]
            ivs2 = [(ti,tf) for ti,tf,ei in intervals_jug.get(jug_p2,[]) if ei==tid_rot]

            # Troba intervals on les dues juguen juntes
            juntes = []
            for a1,a2 in ivs1:
                for b1,b2 in ivs2:
                    ini = max(a1,b1); fi = min(a2,b2)
                    if fi > ini: juntes.append((ini,fi))

            if not juntes:
                st.info(f"{jug_p1} i {jug_p2} no han jugat juntes en aquest partit.")
            else:
                total_min_j = sum(f-i for i,f in juntes)
                # Suma punts directament del play-by-play (mateix metode que el mapa de calor
                # de parelles, per garantir que els dos valors coincideixen sempre)
                df_orig_par = df_orig.copy()
                df_orig_par["t_abs"] = df_orig_par.apply(
                    lambda r: (int(r["quart"])-1)*10+(10-float(r["min_num"]))
                    if float(r.get("min_num",0))<=10 else float(r.get("min_num",0)), axis=1)
                rival_rot_par = teams[1] if tid_rot == teams[0] else (teams[0] if teams else None)
                pf_j = pc_j = 0
                for t_ini,t_fi in juntes:
                    df_j = df_orig_par[(df_orig_par["t_abs"]>=t_ini)&(df_orig_par["t_abs"]<=t_fi)]
                    pf_j += int(df_j[df_j["idEquip"]==tid_rot]["punts"].sum())
                    if rival_rot_par:
                        pc_j += int(df_j[df_j["idEquip"]==rival_rot_par]["punts"].sum())
                parcial_j = pf_j - pc_j

                c1,c2,c3 = st.columns(3)
                col_p = "#16a34a" if parcial_j >= 0 else "#dc2626"
                with c1: st.markdown(card("Minuts juntes", round(total_min_j,1), "min", color_rot), unsafe_allow_html=True)
                with c2: st.markdown(card("Parcial", f"{'+'if parcial_j>=0 else ''}{parcial_j}", "", col_p), unsafe_allow_html=True)
                with c3: st.markdown(card("+/- per min",
                    f"{'+'if parcial_j>=0 else ''}{round(parcial_j/total_min_j,2) if total_min_j>0 else 0}",
                    "", col_p), unsafe_allow_html=True)
                st.caption(f"Trams juntes: {', '.join([f'{i:.0f}–{f:.0f} min' for i,f in juntes])}")

with t6:
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
        # Afegir eficiència de tir al rànquing
        if "minuts" in ranking.columns:
            ranking["Ef2%"] = (ranking.get("C2",0) /
                (ranking.get("C2",0) + df_sj.groupby(["jugador","equip_nom"])["cistelles_2"].sum().reset_index()["cistelles_2"] * 0 + 1)
            ).round(0)

        st.dataframe(df_rk[cols_rank],
            use_container_width=True,hide_index=True)

        # Tirs ficats/tirats per tipus
        st.markdown(sec("Eficiència de tir — ficats/tirats"), unsafe_allow_html=True)
        st.caption(
            "Exemple: 12/17 vol dir 12 cistelles de 17 intents. · "
            "**eFG% (Effective FG%)** = (2pts ficats + 1.5 × 3pts ficats) / tirs de camp intentats. "
            "És el % de tirs de camp (2+3, sense tirs lliures) corregit perquè un triple val 1,5 cops més que un doble — "
            "a diferència del TC% normal, aquí encertar triples \"puja\" més la nota. Útil per veure qui tira bé de debò "
            "un cop tens en compte que no tots els tirs valen el mateix."
        )

        df_sz_rank = load_shots_zones_db()
        if not df_sz_rank.empty:
            # Agrega per jugadora tots els partits
            df_sz_agg = df_sz_rank[df_sz_rank["jugador"]!="__equip__"].groupby(["jugador","equip_nom"]).agg(
                v1m=("val1_made","sum"), v1x=("val1_miss","sum"),
                v2m=("val2_made","sum"), v2x=("val2_miss","sum"),
                v3m=("val3_made","sum"), v3x=("val3_miss","sum"),
            ).reset_index()

            def fmt_ratio(made, miss):
                total = made + miss
                ef = round(made/total*100) if total > 0 else 0
                color = "#16a34a" if ef >= 55 else ("#d97706" if ef >= 35 else "#dc2626")
                return f"{made}/{total} ({ef}%)", color

            # Filtra per equip
            eq_tir = st.selectbox("Equip", ["Tots"] + sorted(df_sz_agg["equip_nom"].unique().tolist()), key="eq_tir_rank")
            df_sz_show = df_sz_agg if eq_tir == "Tots" else df_sz_agg[df_sz_agg["equip_nom"]==eq_tir]
            df_sz_show = df_sz_show.copy()
            df_sz_show["TL (1pt)"]  = df_sz_show.apply(lambda r: f"{r.v1m}/{r.v1m+r.v1x} ({round(r.v1m/(r.v1m+r.v1x)*100) if (r.v1m+r.v1x)>0 else 0}%)", axis=1)
            df_sz_show["2pts"]      = df_sz_show.apply(lambda r: f"{r.v2m}/{r.v2m+r.v2x} ({round(r.v2m/(r.v2m+r.v2x)*100) if (r.v2m+r.v2x)>0 else 0}%)", axis=1)
            df_sz_show["3pts"]      = df_sz_show.apply(lambda r: f"{r.v3m}/{r.v3m+r.v3x} ({round(r.v3m/(r.v3m+r.v3x)*100) if (r.v3m+r.v3x)>0 else 0}%)", axis=1)
            df_sz_show["eFG%"]      = df_sz_show.apply(lambda r: f"{round((r.v2m+r.v3m+0.5*r.v3m)/(r.v2m+r.v2x+r.v3m+r.v3x)*100,1) if (r.v2m+r.v2x+r.v3m+r.v3x)>0 else 0}%", axis=1)
            df_sz_show["Total"]     = df_sz_show.apply(lambda r: f"{r.v1m+r.v2m+r.v3m}/{r.v1m+r.v1x+r.v2m+r.v2x+r.v3m+r.v3x} ({round((r.v1m+r.v2m+r.v3m)/(r.v1m+r.v1x+r.v2m+r.v2x+r.v3m+r.v3x)*100) if (r.v1m+r.v1x+r.v2m+r.v2x+r.v3m+r.v3x)>0 else 0}%)", axis=1)
            df_sz_show = df_sz_show.sort_values("v2m", ascending=False)
            st.dataframe(df_sz_show[["jugador","equip_nom","TL (1pt)","2pts","3pts","eFG%","Total"]].rename(
                columns={"jugador":"Jugadora","equip_nom":"Equip"}),
                use_container_width=True, hide_index=True)
        else:
            st.info("Consulta més partits per veure les estadístiques de tir.")

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
                    _df_tc = df_jh[["Partit","punts","cistelles_2","cistelles_3","tirs_lliures","faltes","impacte","pts_per_min"]].rename(
                        columns={"punts":"Pts","cistelles_2":"C2","cistelles_3":"C3","tirs_lliures":"TL",
                                 "faltes":"Faltes","impacte":"Impacte","pts_per_min":"Pts/min"})
                    _cols_tc = list(_df_tc.columns)
                    _html_tc = '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px;color:#1a2744">'
                    _html_tc += '<tr>' + ''.join(f'<th style="background:#D6E8F7;color:#0C447C;padding:6px 10px;text-align:center;border:1px solid #B5D4F4;font-weight:600">{c}</th>' for c in _cols_tc) + '</tr>'
                    for _, _row_tc in _df_tc.iterrows():
                        _html_tc += '<tr>'
                        for _ci_tc, _col_tc in enumerate(_cols_tc):
                            _bg_tc = '#EBF4FC' if _ci_tc == 0 else '#ffffff'
                            _align_tc = 'left' if _ci_tc == 0 else 'center'
                            _html_tc += f'<td style="padding:5px 10px;border:1px solid #B5D4F4;background:{_bg_tc};color:#1a2744;text-align:{_align_tc}">{_row_tc[_col_tc]}</td>'
                        _html_tc += '</tr>'
                    _html_tc += '</table></div>'
                    st.markdown(_html_tc, unsafe_allow_html=True)

        # ── Rendiment per bloc de minuts ────────────────────────────────────────
        st.markdown(sec("Rendiment per bloc de minuts — primers vs últims"), unsafe_allow_html=True)
        st.caption("Compara si la jugadora anota més al principi o al final de cada bloc de minuts que juga.")

        BLOC_MINS = 3  # minuts a considerar com 'principi' i 'final' del bloc

        jug_bloc = st.selectbox("Jugadora", tots_jugs_hist, key="jug_bloc")
        if jug_bloc:
            # Agafem totes les jugades d'aquesta jugadora de tots els partits
            con_bloc = sqlite3.connect(DB_PATH)
            df_bloc = pd.read_sql(
                "SELECT * FROM jugades WHERE jugador=? ORDER BY match_id, num",
                con_bloc, params=(jug_bloc,))
            con_bloc.close()

            if df_bloc.empty:
                st.info("Sense dades de play-by-play per a aquesta jugadora.")
            else:
                # Per cada partit, identifica blocs de joc continus
                bloc_rows = []
                for mid, df_mid in df_bloc.groupby("match_id"):
                    df_mid = df_mid.sort_values("min_num")
                    # Detecta ruptures de bloc (>2 min sense acció = fora de pista)
                    df_mid["gap"] = df_mid["min_num"].diff().fillna(0)
                    df_mid["bloc_id"] = (df_mid["gap"] > 2).cumsum()

                    for bloc_id, df_b in df_mid.groupby("bloc_id"):
                        if len(df_b) < 2: continue
                        min_inici = df_b["min_num"].min()
                        min_fi    = df_b["min_num"].max()
                        durada    = min_fi - min_inici
                        if durada < BLOC_MINS * 2: continue  # bloc massa curt

                        # Primers N minuts del bloc
                        df_primers = df_b[df_b["min_num"] <= min_inici + BLOC_MINS]
                        pts_primers = int(df_primers["punts"].sum())

                        # Últims N minuts del bloc
                        df_ultims = df_b[df_b["min_num"] >= min_fi - BLOC_MINS]
                        pts_ultims = int(df_ultims["punts"].sum())

                        # Etiqueta del partit
                        df_pr_b = load_partits_db()
                        row_p = df_pr_b[df_pr_b["match_id"]==mid]
                        lbl = f"{row_p.iloc[0]['nom_a']} vs {row_p.iloc[0]['nom_b']}" if not row_p.empty else mid[:8]

                        bloc_rows.append({
                            "Partit": lbl,
                            "Bloc": f"Bloc {int(bloc_id)+1}",
                            "Durada (min)": round(durada, 1),
                            f"Pts primers {BLOC_MINS} min": pts_primers,
                            f"Pts últims {BLOC_MINS} min": pts_ultims,
                            "Tendència": "📈 Millora" if pts_ultims > pts_primers
                                         else ("📉 Baixa" if pts_ultims < pts_primers
                                               else "➡️ Estable")
                        })

                if bloc_rows:
                    df_blocs = pd.DataFrame(bloc_rows)
                    st.dataframe(df_blocs, use_container_width=True, hide_index=True)

                    # Resum global
                    col_b1, col_b2, col_b3 = st.columns(3)
                    mit_p = df_blocs[f"Pts primers {BLOC_MINS} min"].mean()
                    mit_u = df_blocs[f"Pts últims {BLOC_MINS} min"].mean()
                    tendencia = "📈 Millora al final" if mit_u > mit_p else ("📉 Baixa al final" if mit_u < mit_p else "➡️ Estable")
                    with col_b1: st.markdown(card(f"Pts/bloc inici",f"{mit_p:.1f}","mitjana","#185FA5"),unsafe_allow_html=True)
                    with col_b2: st.markdown(card(f"Pts/bloc final",f"{mit_u:.1f}","mitjana","#185FA5"),unsafe_allow_html=True)
                    with col_b3: st.markdown(card("Tendència global",tendencia,"","#374151"),unsafe_allow_html=True)

                    fig_bloc = go.Figure()
                    fig_bloc.add_trace(go.Bar(name=f"Primers {BLOC_MINS} min",
                        x=df_blocs["Partit"]+" "+df_blocs["Bloc"],
                        y=df_blocs[f"Pts primers {BLOC_MINS} min"],
                        marker_color=COLOR_A, opacity=0.8))
                    fig_bloc.add_trace(go.Bar(name=f"Últims {BLOC_MINS} min",
                        x=df_blocs["Partit"]+" "+df_blocs["Bloc"],
                        y=df_blocs[f"Pts últims {BLOC_MINS} min"],
                        marker_color="#16a34a", opacity=0.8))
                    fig_bloc.update_layout(barmode="group")
                    fig_bloc.update_xaxes(tickangle=-30)
                    st.plotly_chart(chart_style(fig_bloc,260,f"{jug_bloc} — primers vs últims minuts del bloc"),use_container_width=True)
                else:
                    st.info(f"No hi ha blocs de més de {BLOC_MINS*2} minuts per a aquesta jugadora.")

    # ── 1. +/- per minut acumulat de temporada ──────────────────────────────
    st.markdown(sec("+/- per minut acumulat — temporada"), unsafe_allow_html=True)
    st.caption("Parcial de l'equip per minut jugat, acumulat de tots els partits.")

    jug_pm = st.selectbox("Jugadora", tots_jugs_hist, key="jug_pm_acum")

    if jug_pm:
        pm_acum_rows = []
        for mid_ac, df_ac in [(p, load_jugades_db(p)) for p in load_partits_db()["match_id"].tolist()]:
            if df_ac.empty: continue
            teams_ac = get_teams_ordered(df_ac)
            tn_ac = {}
            df_pr_ac = load_partits_db()
            p_ac = df_pr_ac[df_pr_ac["match_id"]==mid_ac]
            if not p_ac.empty:
                if len(teams_ac)>=1: tn_ac[teams_ac[0]] = p_ac.iloc[0]["nom_a"]
                if len(teams_ac)>=2: tn_ac[teams_ac[1]] = p_ac.iloc[0]["nom_b"]

            col_jac = "jugador" if "jugador" in df_ac.columns else "jugadora"
            df_ac["jugador"] = df_ac[col_jac].fillna("")
            if jug_pm not in df_ac["jugador"].values: continue

            # Calcula intervals reals
            MINS_Q_AC = 10
            intervals_ac = []; ep_ac = {}
            dj_ac = df_ac[df_ac["jugador"]==jug_pm]
            primer_ac = dj_ac.sort_values("num").iloc[0]
            if "Surt" in str(primer_ac.get("accio","")) and "camp" in str(primer_ac.get("accio","")):
                ep_ac[jug_pm] = (int(primer_ac.get("quart",1))-1)*MINS_Q_AC

            for _,row_ac in df_ac.sort_values("num").iterrows():
                if str(row_ac.get("jugador","")) != jug_pm: continue
                acc_ac = str(row_ac.get("accio",""))
                q_ac = int(row_ac.get("quart",1))
                m_ac = float(row_ac.get("min_num",0))
                t_ac = (q_ac-1)*MINS_Q_AC + (MINS_Q_AC-m_ac if m_ac<=MINS_Q_AC else m_ac)
                t_ac = max(0, min(t_ac, q_ac*MINS_Q_AC))
                if "Entra" in acc_ac and "camp" in acc_ac: ep_ac[jug_pm]=t_ac
                elif "Surt" in acc_ac and "camp" in acc_ac:
                    ti_ac=ep_ac.pop(jug_pm,(q_ac-1)*MINS_Q_AC)
                    if t_ac>ti_ac: intervals_ac.append((float(ti_ac),float(t_ac)))
                elif "Final de període" in acc_ac:
                    if jug_pm in ep_ac:
                        ti_ac=ep_ac.pop(jug_pm); fi_ac=float(q_ac*MINS_Q_AC)
                        if fi_ac>ti_ac: intervals_ac.append((ti_ac,fi_ac))
            for ti_o in ep_ac.values():
                fi_o=float(df_ac["quart"].max()*MINS_Q_AC)
                if fi_o>ti_o: intervals_ac.append((float(ti_o),fi_o))
            intervals_ac=[(float(ti),float(tf)) for ti,tf in intervals_ac]
            if not intervals_ac: continue

            total_min_ac = sum(tf-ti for ti,tf in intervals_ac)
            if total_min_ac < 1: continue

            # Calcula +/-
            eq_id_ac = dj_ac["idEquip"].iloc[0]
            rival_ac = [t for t in teams_ac if t!=eq_id_ac]
            rival_id_ac = rival_ac[0] if rival_ac else None
            df_t_ac = df_ac.copy()
            df_t_ac["t_abs"] = df_t_ac.apply(
                lambda r: (int(r["quart"])-1)*10+(10-float(r["min_num"]))
                if float(r.get("min_num",0))<=10 else float(r.get("min_num",0)), axis=1)
            pf_ac=pc_ac=0
            for ti_r,tf_r in intervals_ac:
                df_i_ac=df_t_ac[(df_t_ac["t_abs"]>=ti_r)&(df_t_ac["t_abs"]<=tf_r)]
                pf_ac+=int(df_i_ac[df_i_ac["idEquip"]==eq_id_ac]["punts"].sum())
                if rival_id_ac:
                    pc_ac+=int(df_i_ac[df_i_ac["idEquip"]==rival_id_ac]["punts"].sum())
            pm_val = pf_ac-pc_ac
            pm_per_min = round(pm_val/total_min_ac,3)

            lbl_ac = f"{tn_ac.get(eq_id_ac,'?')} vs {tn_ac.get(rival_id_ac,'?')}" if rival_id_ac else mid_ac[:8]
            pm_acum_rows.append({
                "Partit": lbl_ac,
                "match_id": mid_ac,
                "Minuts": round(total_min_ac,1),
                "+/-": pm_val,
                "+/- per min": pm_per_min,
            })

        if pm_acum_rows:
            df_pm_acum = pd.DataFrame(pm_acum_rows)
            mitj_pm = df_pm_acum["+/- per min"].mean()

            # Pearson entre Minuts i +/- per minut
            if len(df_pm_acum) >= 3:
                from scipy import stats as sp_stats
                rho, pval = sp_stats.pearsonr(df_pm_acum["Minuts"], df_pm_acum["+/- per min"])
                rho_txt = f"ρ = {rho:+.3f}"
                if abs(rho) >= 0.7: rho_interp = "correlació forta"
                elif abs(rho) >= 0.4: rho_interp = "correlació moderada"
                else: rho_interp = "correlació feble"
                rho_dir = "positiva" if rho > 0 else "negativa"
                pval_txt = f"p = {pval:.3f}" + (" (sig.)" if pval < 0.05 else " (no sig.)")
            else:
                rho, pval = None, None
                rho_txt = "Cal ≥3 partits"
                rho_interp = ""; rho_dir = ""; pval_txt = ""

            col_pa1,col_pa2,col_pa3,col_pa4 = st.columns(4)
            color_pm = "#16a34a" if mitj_pm>=0 else "#dc2626"
            color_rho = "#16a34a" if (rho or 0)>0.4 else ("#dc2626" if (rho or 0)<-0.4 else "#374151")
            with col_pa1: st.markdown(card("Partits analitzats",len(df_pm_acum),"",COLOR_A),unsafe_allow_html=True)
            with col_pa2: st.markdown(card("Minuts totals",round(df_pm_acum["Minuts"].sum(),1),"",COLOR_A),unsafe_allow_html=True)
            with col_pa3: st.markdown(card("+/- per min (mitj.)",f"{'+'if mitj_pm>=0 else ''}{mitj_pm:.3f}","",color_pm),unsafe_allow_html=True)
            with col_pa4: st.markdown(card("Pearson (Min vs +/-/min)",rho_txt,f"{rho_interp} {rho_dir}" if rho is not None else "",color_rho),unsafe_allow_html=True)

            if rho is not None:
                st.caption(f"ρ de Pearson (Minuts jugats vs +/- per minut): **{rho_txt}** — {rho_interp} {rho_dir} · {pval_txt}")

            # Gràfic barres +/- per minut per partit
            colors_pm_acum = ["#16a34a" if v>=0 else "#dc2626" for v in df_pm_acum["+/- per min"]]
            fig_pm_acum = go.Figure()
            fig_pm_acum.add_trace(go.Bar(
                x=df_pm_acum["Partit"],
                y=df_pm_acum["+/- per min"],
                marker_color=colors_pm_acum,
                text=[f"{'+'if v>=0 else ''}{v:.3f}" for v in df_pm_acum["+/- per min"]],
                textposition="outside"))
            fig_pm_acum.add_hline(y=0, line_dash="solid", line_color="#e2e4e8")
            fig_pm_acum.add_hline(y=mitj_pm, line_dash="dot", line_color="#d97706",
                annotation_text=f"Mitjana: {mitj_pm:+.3f}", annotation_font_size=10)
            fig_pm_acum.update_layout(xaxis_tickangle=-30)
            st.plotly_chart(chart_style(fig_pm_acum,280,f"{jug_pm} — +/- per minut (temporada)"),use_container_width=True)

            # Scatter Minuts vs +/- per minut amb línia de tendència
            if len(df_pm_acum) >= 3:
                import numpy as np
                fig_scatter_pm = go.Figure()
                fig_scatter_pm.add_trace(go.Scatter(
                    x=df_pm_acum["Minuts"], y=df_pm_acum["+/- per min"],
                    mode="markers+text",
                    marker=dict(size=10, color=colors_pm_acum, line=dict(width=1, color="white")),
                    text=df_pm_acum["Partit"].apply(lambda s: s[:12]),
                    textposition="top center", textfont=dict(size=8),
                    hovertemplate="<b>%{text}</b><br>Minuts: %{x}<br>+/- per min: %{y:+.3f}<extra></extra>"
                ))
                # Línia de tendència
                m, b = np.polyfit(df_pm_acum["Minuts"], df_pm_acum["+/- per min"], 1)
                x_line = [df_pm_acum["Minuts"].min(), df_pm_acum["Minuts"].max()]
                y_line = [m*x+b for x in x_line]
                fig_scatter_pm.add_trace(go.Scatter(
                    x=x_line, y=y_line, mode="lines",
                    line=dict(color="#d97706", width=2, dash="dot"),
                    name=f"Tendència (ρ={rho:+.3f})", showlegend=True
                ))
                fig_scatter_pm.add_hline(y=0, line_dash="solid", line_color="#e2e4e8")
                fig_scatter_pm.update_xaxes(title="Minuts jugats")
                fig_scatter_pm.update_yaxes(title="+/- per minut")
                st.plotly_chart(chart_style(fig_scatter_pm, 260,
                    f"{jug_pm} — Minuts vs +/- per minut (ρ = {rho:+.3f})"),
                    use_container_width=True)

            st.dataframe(df_pm_acum[["Partit","Minuts","+/-","+/- per min"]],
                use_container_width=True, hide_index=True)
        else:
            st.info("No hi ha prou dades per a aquesta jugadora.")

    # ── 2. Rendiment per posició dins del tram ──────────────────────────────
    st.markdown(sec("En quins minuts del tram aporta?"), unsafe_allow_html=True)
    st.caption("Parcial de l'equip al minut 1, 2, 3... de cada tram que juga la jugadora. Acumulat de tots els partits.")

    jug_tram_acum = st.selectbox("Jugadora", tots_jugs_hist, key="jug_tram_acum")

    if jug_tram_acum:
        tram_minuts = {}  # {minut_dins_tram: [parcials]}

        for mid_tr, df_tr in [(p, load_jugades_db(p)) for p in load_partits_db()["match_id"].tolist()]:
            if df_tr.empty: continue
            teams_tr = get_teams_ordered(df_tr)
            col_jtr = "jugador" if "jugador" in df_tr.columns else "jugadora"
            df_tr["jugador"] = df_tr[col_jtr].fillna("")
            if jug_tram_acum not in df_tr["jugador"].values: continue

            eq_id_tr = df_tr[df_tr["jugador"]==jug_tram_acum]["idEquip"].iloc[0]
            rival_tr = [t for t in teams_tr if t!=eq_id_tr]
            rival_id_tr = rival_tr[0] if rival_tr else None

            MINS_Q_TR = 10
            intervals_tr = []; ep_tr = {}
            dj_tr = df_tr[df_tr["jugador"]==jug_tram_acum]
            primer_tr = dj_tr.sort_values("num").iloc[0]
            if "Surt" in str(primer_tr.get("accio","")) and "camp" in str(primer_tr.get("accio","")):
                ep_tr[jug_tram_acum] = (int(primer_tr.get("quart",1))-1)*MINS_Q_TR

            for _,row_tr in df_tr.sort_values("num").iterrows():
                if str(row_tr.get("jugador","")) != jug_tram_acum: continue
                acc_tr = str(row_tr.get("accio",""))
                q_tr = int(row_tr.get("quart",1))
                m_tr = float(row_tr.get("min_num",0))
                t_tr = (q_tr-1)*MINS_Q_TR + (MINS_Q_TR-m_tr if m_tr<=MINS_Q_TR else m_tr)
                t_tr = max(0, min(t_tr, q_tr*MINS_Q_TR))
                if "Entra" in acc_tr and "camp" in acc_tr: ep_tr[jug_tram_acum]=t_tr
                elif "Surt" in acc_tr and "camp" in acc_tr:
                    ti_tr=ep_tr.pop(jug_tram_acum,(q_tr-1)*MINS_Q_TR)
                    if t_tr>ti_tr: intervals_tr.append((float(ti_tr),float(t_tr)))
                elif "Final de període" in acc_tr:
                    if jug_tram_acum in ep_tr:
                        ti_tr=ep_tr.pop(jug_tram_acum); fi_tr=float(q_tr*MINS_Q_TR)
                        if fi_tr>ti_tr: intervals_tr.append((ti_tr,fi_tr))
            for ti_o in ep_tr.values():
                fi_o=float(df_tr["quart"].max()*MINS_Q_TR)
                if fi_o>ti_o: intervals_tr.append((float(ti_o),fi_o))
            intervals_tr=[(float(ti),float(tf)) for ti,tf in intervals_tr]

            if not intervals_tr or rival_id_tr is None: continue

            df_t_tr = df_tr.copy()
            df_t_tr["t_abs"] = df_t_tr.apply(
                lambda r: (int(r["quart"])-1)*10+(10-float(r["min_num"]))
                if float(r.get("min_num",0))<=10 else float(r.get("min_num",0)), axis=1)

            # Per cada tram, calcula el parcial a cada minut
            for ti_tr, tf_tr in intervals_tr:
                durada_tr = tf_tr - ti_tr
                if durada_tr < 1: continue
                for min_dins in range(1, min(int(durada_tr)+1, 10)):
                    t_inici_min = ti_tr + min_dins - 1
                    t_fi_min = ti_tr + min_dins
                    df_min_tr = df_t_tr[(df_t_tr["t_abs"]>=t_inici_min)&(df_t_tr["t_abs"]<t_fi_min)]
                    pf_min = int(df_min_tr[df_min_tr["idEquip"]==eq_id_tr]["punts"].sum())
                    pc_min = int(df_min_tr[df_min_tr["idEquip"]==rival_id_tr]["punts"].sum())
                    tram_minuts.setdefault(min_dins, []).append(pf_min - pc_min)

        if tram_minuts:
            mins_sorted = sorted(tram_minuts.keys())
            mitjes_tram = [round(sum(tram_minuts[m])/len(tram_minuts[m]),2) for m in mins_sorted]
            mostres_tram = [len(tram_minuts[m]) for m in mins_sorted]

            fig_tram_acum = go.Figure()
            colors_tram_acum = ["#16a34a" if v>=0 else "#dc2626" for v in mitjes_tram]
            fig_tram_acum.add_trace(go.Bar(
                x=[f"Min {m}" for m in mins_sorted],
                y=mitjes_tram,
                marker_color=colors_tram_acum,
                text=[f"{'+'if v>=0 else ''}{v:.2f}" for v in mitjes_tram],
                textposition="outside",
                customdata=mostres_tram,
                hovertemplate="Min %{x}<br>Parcial mig: %{y:+.2f}<br>Mostres: %{customdata}<extra></extra>"
            ))
            fig_tram_acum.add_hline(y=0, line_dash="solid", line_color="#e2e4e8")
            fig_tram_acum.update_layout(
                xaxis_title="Minut dins del tram",
                yaxis_title="Parcial mig de l'equip")
            st.plotly_chart(chart_style(fig_tram_acum,280,
                f"{jug_tram_acum} — parcial per minut dins del tram"),use_container_width=True)
            st.caption("Cada barra = parcial mig de l'equip en aquell minut de cada tram que juga. "
                       "Verd = l'equip guanya en aquell minut. Vermell = l'equip perd.")

            # Interpretació
            best_min = mins_sorted[mitjes_tram.index(max(mitjes_tram))]
            worst_min = mins_sorted[mitjes_tram.index(min(mitjes_tram))]
            st.info(f"📊 Millor minut del tram: **Minut {best_min}** ({max(mitjes_tram):+.2f} parcial mig) · "
                    f"Pitjor: **Minut {worst_min}** ({min(mitjes_tram):+.2f})")
        else:
            st.info("No hi ha prou dades per a aquesta jugadora.")

    # ── 3. Evolució +/- per minut al llarg de la temporada ─────────────────
    st.markdown(sec("Evolució del +/- per minut — temporada"), unsafe_allow_html=True)
    st.caption("Com ha evolucionat l'aportació per minut jugat al llarg de la temporada.")

    jug_evo = st.selectbox("Jugadora", tots_jugs_hist, key="jug_evo_pm")
    if jug_evo and pm_acum_rows and jug_evo == jug_pm:
        # Reutilitza les dades calculades
        fig_evo = go.Figure()
        fig_evo.add_trace(go.Scatter(
            x=list(range(1, len(df_pm_acum)+1)),
            y=df_pm_acum["+/- per min"].tolist(),
            mode="lines+markers",
            name="+/- per min",
            line=dict(color=COLOR_A, width=2),
            marker=dict(size=8, color=["#16a34a" if v>=0 else "#dc2626"
                                        for v in df_pm_acum["+/- per min"]]),
            text=df_pm_acum["Partit"].tolist(),
            hovertemplate="%{text}<br>+/- per min: %{y:+.3f}<extra></extra>"
        ))
        # Línia de mitjana mòbil
        if len(df_pm_acum) >= 3:
            rolling = df_pm_acum["+/- per min"].rolling(2, min_periods=1).mean()
            fig_evo.add_trace(go.Scatter(
                x=list(range(1, len(df_pm_acum)+1)),
                y=rolling.tolist(),
                mode="lines",
                name="Tendència (2P)",
                line=dict(color="#d97706", width=2, dash="dot")
            ))
        fig_evo.add_hline(y=0, line_dash="solid", line_color="#e2e4e8")
        fig_evo.add_hline(y=mitj_pm, line_dash="dot", line_color="#185FA5",
            annotation_text=f"Mitjana: {mitj_pm:+.3f}")
        fig_evo.update_xaxes(title="Número de partit")
        fig_evo.update_yaxes(title="+/- per minut")
        st.plotly_chart(chart_style(fig_evo,280,f"{jug_evo} — evolució +/- per minut"),use_container_width=True)
    else:
        st.info("Selecciona la mateixa jugadora que als apartats anteriors per veure l'evolució.")

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

    # ══════════════════════════════════════════════════════════════════
    # USAGE% VS PTS/40MIN — VOLUM I PRODUCTIVITAT OFENSIVA
    # ══════════════════════════════════════════════════════════════════
    st.markdown(sec("📊 Usage% vs Pts/40min"), unsafe_allow_html=True)
    st.caption("Volum ofensiu (Usage%) vs productivitat anotadora normalitzada a 40 minuts, acumulat de tota la "
               "temporada. Usage% alt + Pts/40min alt identifica les jugadores d'elit ofensiu.")

    df_sj_p40 = load_stats_jugador_db()
    if df_sj_p40.empty:
        st.info("Carrega almenys un partit per activar aquest gràfic.")
    else:
        col_j_p40 = "jugador" if "jugador" in df_sj_p40.columns else "jugadora"
        equips_p40 = sorted(df_sj_p40["equip_nom"].unique().tolist())
        eq_p40_sel = st.selectbox("Equip", equips_p40, key="eq_p40_sel")

        rows_p40 = []
        for jug, grp in df_sj_p40[df_sj_p40["equip_nom"] == eq_p40_sel].groupby(col_j_p40):
            min_tot = grp["minuts"].sum() if "minuts" in grp.columns else 0
            if min_tot < 5:
                continue
            pts_tot = grp["punts"].sum()
            usage = grp["usage_rate"].mean() if "usage_rate" in grp.columns else 0
            rows_p40.append({
                "Jugadora": jug, "Partits": grp["match_id"].nunique(),
                "Min tot": round(min_tot, 1), "Pts tot": int(pts_tot),
                "Usage%": round(usage, 1),
                "Pts/40min": round(pts_tot / min_tot * 40, 1),
            })
        df_p40 = pd.DataFrame(rows_p40)

        if df_p40.empty:
            st.info("Cap jugadora amb almenys 5 minuts totals per a aquest equip.")
        else:
            fig_p40 = go.Figure()
            sizes_p40 = df_p40["Min tot"].clip(lower=1)
            sizes_norm = (sizes_p40 / sizes_p40.max() * 22 + 10).round(0)
            fig_p40.add_trace(go.Scatter(
                x=df_p40["Usage%"], y=df_p40["Pts/40min"],
                mode="markers+text", name=eq_p40_sel,
                marker=dict(size=sizes_norm, color=COLOR_A,
                            line=dict(width=1.5, color=C_WHITE), opacity=0.88),
                text=df_p40["Jugadora"].apply(lambda n: n.split()[1] if len(n.split())>1 else n),
                textposition="top center", textfont=dict(size=9, color=C_TEXT),
                hovertemplate=(
                    "<b>%{text}</b><br>Usage%: %{x:.1f}%<br>Pts/40min: %{y:.1f}<br>"
                    "Min totals: %{customdata[0]:.0f} | Partits: %{customdata[1]}<extra></extra>"),
                customdata=df_p40[["Min tot", "Partits"]].values,
            ))

            mitj_usage_p40 = df_p40["Usage%"].mean()
            mitj_pts40 = df_p40["Pts/40min"].mean()
            fig_p40.add_vline(x=mitj_usage_p40, line_dash="dot", line_color=C_CARD_BORDER,
                annotation_text=f"Mitjana Usage {mitj_usage_p40:.0f}%",
                annotation_font_size=9, annotation_font_color=C_LABEL, annotation_position="top right")
            fig_p40.add_hline(y=mitj_pts40, line_dash="dot", line_color=C_CARD_BORDER,
                annotation_text=f"Mitjana {mitj_pts40:.1f} pts/40",
                annotation_font_size=9, annotation_font_color=C_LABEL)

            x_max_p40 = df_p40["Usage%"].max() * 1.05
            x_min_p40 = df_p40["Usage%"].min() * 0.95
            y_max_p40 = df_p40["Pts/40min"].max() * 1.05
            y_min_p40 = df_p40["Pts/40min"].min() * 0.95
            for txt, xq, yq, cq in [
                ("⭐ Molt volum · molt productiva", x_max_p40*0.92, y_max_p40*0.94, C_SUCCESS),
                ("⚠️ Molt volum · poc productiva",  x_max_p40*0.92, y_min_p40*1.08, C_ERROR),
                ("💡 Poc volum · molt productiva",  x_min_p40*1.08, y_max_p40*0.94, C_ACCENT),
                ("🔄 Rol secundari",                x_min_p40*1.08, y_min_p40*1.08, C_LABEL),
            ]:
                fig_p40.add_annotation(x=xq, y=yq, text=txt, showarrow=False,
                    font=dict(size=9, color=cq), xanchor="center", yanchor="middle", opacity=0.45)

            fig_p40.update_xaxes(title="Usage% (% de possessions usades per la jugadora)")
            fig_p40.update_yaxes(title="Pts/40min (punts normalitzats a 40 minuts)")

            st.caption("Pts/40min = punts totals / minuts totals × 40 · Mida del punt = minuts totals jugats · "
                       "Quadrant ideal: dalt a la dreta (molt volum + màxima producció)")
            st.plotly_chart(
                chart_style(fig_p40, 430, "Usage% vs Pts/40min — Volum i productivitat ofensiva"),
                use_container_width=True)

            with st.expander("📋 Veure dades de temporada"):
                df_p40_show = df_p40[["Jugadora","Partits","Min tot","Pts tot","Usage%","Pts/40min"]].sort_values(
                    "Pts/40min", ascending=False)
                html_p40 = ('<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;'
                            f'font-size:12px;color:{C_TEXT}">')
                html_p40 += '<tr>' + ''.join(
                    f'<th style="background:{C_BG_SOFT};color:{C_ACCENT_DARK};padding:6px 10px;'
                    f'text-align:center;border:1px solid {C_BORDER};font-weight:600">{c}</th>'
                    for c in df_p40_show.columns) + '</tr>'
                for i_p40, (_, row_p40) in enumerate(df_p40_show.iterrows()):
                    bg_p40 = C_WHITE if i_p40 % 2 == 0 else C_BG
                    html_p40 += '<tr>'
                    for ci_p40, col_p40 in enumerate(df_p40_show.columns):
                        align_p40 = 'left' if ci_p40 == 0 else 'center'
                        html_p40 += (f'<td style="padding:5px 10px;border:1px solid {C_BORDER};background:{bg_p40};'
                                     f'color:{C_TEXT};text-align:{align_p40}">{row_p40[col_p40]}</td>')
                    html_p40 += '</tr>'
                html_p40 += '</table></div>'
                st.markdown(html_p40, unsafe_allow_html=True)

    # ── Històric temps morts ────────────────────────────────────────────────
    st.markdown(sec("⏸ Efectivitat dels temps morts — temporada"), unsafe_allow_html=True)
    df_to_hist = load_timeouts_db()
    if df_to_hist.empty:
        st.info("Consulta més partits per veure l'evolució dels temps morts.")
    else:
        df_pr_to = load_partits_db()
        def lp_to(mid):
            r = df_pr_to[df_pr_to["match_id"]==mid]
            if r.empty: return mid[:8]+"..."
            return f"{r.iloc[0]['nom_a']} vs {r.iloc[0]['nom_b']} ({r.iloc[0]['data_consulta'][:10]})"
        df_to_hist["Partit"] = df_to_hist["match_id"].apply(lp_to)

        equips_to = sorted(df_to_hist["equip_nom"].unique().tolist())
        eq_to = st.selectbox("Equip", equips_to, key="eq_to_hist")

        df_eq_to = df_to_hist[df_to_hist["equip_nom"]==eq_to]

        # Evolució efectivitat per partit
        evo = df_eq_to.groupby("Partit").agg(
            Total=("va_anotar","count"),
            Anotats=("va_anotar","sum"),
            Seg_mit=("segons_resposta","mean")
        ).reset_index()
        evo["Efectivitat %"] = (evo["Anotats"]/evo["Total"]*100).round(0)

        fig_to_evo = go.Figure()
        fig_to_evo.add_trace(go.Scatter(
            x=evo["Partit"], y=evo["Efectivitat %"],
            mode="lines+markers", name="Efectivitat %",
            line=dict(color=COLOR_A, width=2.5), marker=dict(size=8)))
        fig_to_evo.add_hline(y=50, line_dash="dot", line_color="#e2e4e8",
            annotation_text="50%", annotation_font_color="#9ca3af", annotation_font_size=10)
        fig_to_evo.update_layout(yaxis=dict(range=[0,100], ticksuffix="%"))
        fig_to_evo.update_xaxes(tickangle=-30)
        st.plotly_chart(chart_style(fig_to_evo, 260, f"{eq_to} — efectivitat temps morts per partit"), use_container_width=True)

        # Qui anota més després dels temps morts
        df_anotades = df_eq_to[df_eq_to["va_anotar"]==1]
        if not df_anotades.empty:
            top_jug = df_anotades.groupby("jugadora").size().reset_index(name="Cistelles post-TM")
            top_jug = top_jug.sort_values("Cistelles post-TM", ascending=False).head(8)
            fig_jug_to = px.bar(top_jug, x="jugadora", y="Cistelles post-TM",
                color_discrete_sequence=[COLOR_A], text="Cistelles post-TM",
                labels={"jugadora":"Jugadora"})
            fig_jug_to.update_traces(textposition="outside")
            st.plotly_chart(chart_style(fig_jug_to, 240,
                f"{eq_to} — qui anota després dels temps morts"), use_container_width=True)

        # Temps mitjà de resposta per partit
        fig_seg = go.Figure()
        fig_seg.add_trace(go.Scatter(
            x=evo["Partit"], y=evo["Seg_mit"],
            mode="lines+markers", name="Seg. fins cistella",
            line=dict(color="#d97706", width=2.5), marker=dict(size=8)))
        fig_seg.update_xaxes(tickangle=-30)
        fig_seg.update_yaxes(title="Segons")
        st.plotly_chart(chart_style(fig_seg, 220,
            f"{eq_to} — temps mitjà fins anotar després del temps mort"), use_container_width=True)

with t_arq:
    st.markdown(sec("🎭 Arquetips de jugadora"), unsafe_allow_html=True)
    st.caption("Classificació simplificada de l'estil de cada jugadora a partir del seu Usage% i distribució de punts (2pts/3pts/TL), acumulat de tota la temporada.")

    df_sj_arq = load_stats_jugador_db()
    if df_sj_arq.empty or len(df_sj_arq) < 5:
        st.info("Carrega més partits per generar arquetips fiables (mínim recomanat: 3-5 partits).")
    else:
        col_j_arq = "jugador" if "jugador" in df_sj_arq.columns else "jugadora"

        def classifica_arquetip(usage, p2, p3, ptl, min_p):
            """Classifica una jugadora en un arquetip simplificat."""
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

        # Agrega per jugadora (mitjanes de temporada)
        agg_arq = df_sj_arq.groupby(col_j_arq).agg(
            equip=("equip_nom","first"),
            punts=("punts","sum"),
            c2=("cistelles_2","sum"),
            c3=("cistelles_3","sum"),
            tl=("tirs_lliures","sum"),
            minuts=("minuts","sum") if "minuts" in df_sj_arq.columns else ("punts","count"),
            partits=("match_id","nunique"),
            usage=("usage_rate","mean") if "usage_rate" in df_sj_arq.columns else ("punts","mean"),
            impacte=("impacte","sum")
        ).reset_index()

        agg_arq["pts2"] = agg_arq["c2"]*2
        agg_arq["pts3"] = agg_arq["c3"]*3
        agg_arq["ptstl"] = agg_arq["tl"]
        agg_arq["pts_tot"] = agg_arq["pts2"]+agg_arq["pts3"]+agg_arq["ptstl"]
        agg_arq["p2_pct"] = (agg_arq["pts2"]/agg_arq["pts_tot"].replace(0,1)*100).round(1)
        agg_arq["p3_pct"] = (agg_arq["pts3"]/agg_arq["pts_tot"].replace(0,1)*100).round(1)
        agg_arq["ptl_pct"] = (agg_arq["ptstl"]/agg_arq["pts_tot"].replace(0,1)*100).round(1)
        # calc_usage_rate() ja retorna un percentatge (p.ex. 24.4 = 24.4%), no cal tornar a multiplicar per 100
        agg_arq["usage_pct"] = agg_arq["usage"].round(1) if "usage_rate" in df_sj_arq.columns else 0
        agg_arq["min_p"] = (agg_arq["minuts"]/agg_arq["partits"].replace(0,1)).round(1)

        agg_arq["Arquetip"] = agg_arq.apply(
            lambda r: classifica_arquetip(r["usage_pct"], r["p2_pct"], r["p3_pct"], r["ptl_pct"], r["min_p"]),
            axis=1)

        # Mostra taula d'arquetips
        df_show_arq = agg_arq[["jugador","equip","partits","min_p","usage_pct","p2_pct","p3_pct","ptl_pct","Arquetip"]].copy() if col_j_arq=="jugador" else agg_arq.rename(columns={col_j_arq:"jugador"})[["jugador","equip","partits","min_p","usage_pct","p2_pct","p3_pct","ptl_pct","Arquetip"]]
        df_show_arq.columns = ["Jugadora","Equip","Partits","Min/P","Usage%","%Pts2","%Pts3","%PtsTL","Arquetip"]
        df_show_arq = df_show_arq.sort_values("Usage%", ascending=False)

        # Taula HTML (per evitar problemes de visibilitat)
        html_arq = '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px;color:#1a2744">'
        html_arq += '<tr>' + ''.join(f'<th style="background:#D6E8F7;color:#0C447C;padding:6px 10px;text-align:center;border:1px solid #B5D4F4;font-weight:600">{c}</th>' for c in df_show_arq.columns) + '</tr>'
        for i_arq, row_arq in df_show_arq.iterrows():
            bg_arq = '#ffffff' if list(df_show_arq.index).index(i_arq)%2==0 else '#EBF4FC'
            html_arq += '<tr>'
            for ci_arq, col_arq in enumerate(df_show_arq.columns):
                val_arq = row_arq[col_arq]
                align_arq = 'left' if ci_arq in (0,1,8) else 'center'
                bold_arq = 'font-weight:600;' if ci_arq==0 else ''
                html_arq += f'<td style="padding:5px 10px;border:1px solid #B5D4F4;background:{bg_arq};color:#1a2744;text-align:{align_arq};{bold_arq}">{val_arq}</td>'
            html_arq += '</tr>'
        html_arq += '</table></div>'
        st.markdown(html_arq, unsafe_allow_html=True)

        # ── Descàrrega filtrada per equip ───────────────────────────────────
        st.markdown("**📥 Descarregar arquetips d'un equip concret**")
        equips_arq = sorted(df_show_arq["Equip"].unique().tolist())
        eq_filtre_arq = st.selectbox("Selecciona l'equip", equips_arq, key="eq_filtre_arq")

        if st.button(f"⬇ Generar Excel d'arquetips — {eq_filtre_arq}", key="btn_excel_arq"):
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            from openpyxl.utils import get_column_letter
            import io as io_arq

            df_eq_arq = df_show_arq[df_show_arq["Equip"]==eq_filtre_arq].copy()

            BLAU_F_A='0C447C'; BLAU_M_A='185FA5'; BLAU_C_A='EBF4FC'; BLANC_A='FFFFFF'

            def fons_a(c): return PatternFill('solid', fgColor=c)
            def vora_a():
                s=Side(style='thin',color='CCCCCC')
                return Border(top=s,bottom=s,left=s,right=s)
            def fc_a(ws,r,c,v,bold=False,bg=None,fg='000000',align='center',size=10):
                cell=ws.cell(row=r,column=c,value=v)
                cell.font=Font(name='Arial',bold=bold,color=fg,size=size)
                if bg: cell.fill=fons_a(bg)
                cell.alignment=Alignment(horizontal=align,vertical='center')
                cell.border=vora_a()
                return cell

            wb_a = Workbook(); wb_a.remove(wb_a.active)
            ws_a = wb_a.create_sheet("Arquetips")
            ws_a.sheet_view.showGridLines=False; ws_a.column_dimensions['A'].width=2
            ws_a.merge_cells('B1:J1')
            c=ws_a['B1']; c.value=f'MICKI ANALÍTICA — ARQUETIPS DE JUGADORA — {eq_filtre_arq}'
            c.font=Font(name='Arial',bold=True,color=BLANC_A,size=14)
            c.fill=fons_a(BLAU_F_A); c.alignment=Alignment(horizontal='center',vertical='center')
            ws_a.row_dimensions[1].height=36
            ws_a.merge_cells('B2:J2')
            c=ws_a['B2']; c.value=f"Generat: {datetime.now().strftime('%d/%m/%Y %H:%M')} · {len(df_eq_arq)} jugadores"
            c.font=Font(name='Arial',color=BLANC_A,size=10); c.fill=fons_a(BLAU_M_A)
            c.alignment=Alignment(horizontal='center',vertical='center')
            ws_a.row_dimensions[2].height=18; ws_a.row_dimensions[3].height=6

            for ci_a,w_a in zip(range(2,11),[24,16,9,9,10,10,10,10,28]):
                ws_a.column_dimensions[get_column_letter(ci_a)].width=w_a

            row_a=4
            for ci_a,cap_a in enumerate(df_eq_arq.columns,2):
                fc_a(ws_a,row_a,ci_a,cap_a,bold=True,bg=BLAU_M_A,fg=BLANC_A,size=9)
            ws_a.row_dimensions[row_a].height=20; row_a+=1

            for i_a,(_,r_a) in enumerate(df_eq_arq.iterrows()):
                bg_a = BLAU_C_A if i_a%2==0 else BLANC_A
                for ci_a,col_a in enumerate(df_eq_arq.columns,2):
                    align_a = 'left' if col_a in ('Jugadora','Equip','Arquetip') else 'center'
                    fc_a(ws_a,row_a,ci_a,r_a[col_a],bg=bg_a,align=align_a,size=9,
                         bold=(col_a=='Jugadora'),fg=BLAU_F_A if col_a=='Jugadora' else '000000')
                ws_a.row_dimensions[row_a].height=18; row_a+=1

            # ── PESTANYA 2: ECOSISTEMA — amb qui rendeix millor cada jugadora ──
            ws_b = wb_a.create_sheet("Ecosistema")
            ws_b.sheet_view.showGridLines=False; ws_b.column_dimensions['A'].width=2
            ws_b.merge_cells('B1:I1')
            c=ws_b['B1']; c.value=f'MICKI ANALÍTICA — ECOSISTEMA D\'EQUIP — {eq_filtre_arq}'
            c.font=Font(name='Arial',bold=True,color=BLANC_A,size=14)
            c.fill=fons_a(BLAU_F_A); c.alignment=Alignment(horizontal='center',vertical='center')
            ws_b.row_dimensions[1].height=36
            ws_b.merge_cells('B2:I2')
            c=ws_b['B2']; c.value='Amb quin tipus de companya rendeix millor cada jugadora (segons +/- per minut quan juguen juntes)'
            c.font=Font(name='Arial',color=BLANC_A,size=10); c.fill=fons_a(BLAU_M_A)
            c.alignment=Alignment(horizontal='center',vertical='center')
            ws_b.row_dimensions[2].height=18; ws_b.row_dimensions[3].height=6

            for ci_b,w_b in zip(range(2,10),[22,28,12,10,10,10,38]):
                ws_b.column_dimensions[get_column_letter(ci_b)].width=w_b

            row_b=4
            jugs_eq_arq = df_eq_arq["Jugadora"].tolist()
            df_pr_eco_a = load_partits_db()
            arq_map_a = dict(zip(df_show_arq["Jugadora"], df_show_arq["Arquetip"]))

            for jug_b in jugs_eq_arq:
                # Recull totes les parelles d'aquesta jugadora a tots els partits
                eco_rows_b = []
                for _,p_b in df_pr_eco_a.iterrows():
                    mid_b = p_b['match_id']
                    df_m_b = load_jugades_db(mid_b)
                    if df_m_b.empty: continue
                    col_j_b = "jugador" if "jugador" in df_m_b.columns else "jugadora"
                    df_m_b["jugador"] = df_m_b[col_j_b].fillna("")
                    if jug_b not in df_m_b["jugador"].values: continue
                    rows_par_b = calc_pm_combinacions(df_m_b, mode="parelles")
                    for r_par_b in rows_par_b:
                        if jug_b in r_par_b["combinacio"]:
                            altra_b = [j for j in r_par_b["combinacio"] if j != jug_b]
                            if not altra_b: continue
                            eco_rows_b.append({
                                "company": altra_b[0],
                                "minuts": r_par_b["minuts"],
                                "pf": r_par_b["pf"],
                                "pc": r_par_b["pc"]
                            })

                if not eco_rows_b: continue
                df_eco_b = pd.DataFrame(eco_rows_b)
                eco_acum_b = df_eco_b.groupby("company").agg(
                    minuts=("minuts","sum"), pf=("pf","sum"), pc=("pc","sum")
                ).reset_index()
                eco_acum_b["pm"] = eco_acum_b["pf"]-eco_acum_b["pc"]
                eco_acum_b["pm_min"] = (eco_acum_b["pm"]/eco_acum_b["minuts"].replace(0,1)).round(3)
                eco_acum_b["Arquetip"] = eco_acum_b["company"].map(arq_map_a).fillna("—")

                eco_per_arq_b = eco_acum_b.groupby("Arquetip").agg(
                    minuts=("minuts","sum"), pf=("pf","sum"), pc=("pc","sum")
                ).reset_index()
                eco_per_arq_b["pm"] = eco_per_arq_b["pf"]-eco_per_arq_b["pc"]
                eco_per_arq_b["pm_min"] = (eco_per_arq_b["pm"]/eco_per_arq_b["minuts"].replace(0,1)).round(3)
                eco_per_arq_b = eco_per_arq_b[eco_per_arq_b["minuts"]>=2].sort_values("pm_min", ascending=False)

                if eco_per_arq_b.empty: continue

                # Capçalera jugadora
                ws_b.merge_cells(f'B{row_b}:I{row_b}')
                arquetip_propi = arq_map_a.get(jug_b, "—")
                c=ws_b[f'B{row_b}']; c.value=f'{jug_b}  ({arquetip_propi})'
                c.font=Font(name='Arial',bold=True,color=BLANC_A,size=11)
                c.fill=fons_a(BLAU_M_A); c.alignment=Alignment(horizontal='left',vertical='center')
                ws_b.row_dimensions[row_b].height=20; row_b+=1

                for ci_b,cap_b in zip(range(2,9),['Arquetip company','Min junts','Pts favor','Pts contra','+/-','+/- per min','Conclusió']):
                    fc_a(ws_b,row_b,ci_b,cap_b,bold=True,bg=BLAU_C_A,fg=BLAU_F_A,size=9)
                ws_b.row_dimensions[row_b].height=18; row_b+=1

                millor_b = eco_per_arq_b.iloc[0]
                pitjor_b = eco_per_arq_b.iloc[-1]

                for i_b,(_,r_b) in enumerate(eco_per_arq_b.iterrows()):
                    bg_rb = BLANC_A if i_b%2==0 else BLAU_C_A
                    pm_v = r_b['pm_min']
                    pm_bg = 'D5F5E3' if pm_v>=0 else 'FADBD8'
                    pm_fg = '0F6E56' if pm_v>=0 else '993C1D'
                    concl = ''
                    if r_b['Arquetip']==millor_b['Arquetip']: concl='⭐ Millor combinació'
                    elif r_b['Arquetip']==pitjor_b['Arquetip']: concl='⚠️ Pitjor combinació'

                    fc_a(ws_b,row_b,2,r_b['Arquetip'],bg=bg_rb,align='left',size=9)
                    fc_a(ws_b,row_b,3,round(r_b['minuts'],1),bg=bg_rb,size=9)
                    fc_a(ws_b,row_b,4,int(r_b['pf']),bg=bg_rb,size=9)
                    fc_a(ws_b,row_b,5,int(r_b['pc']),bg=bg_rb,size=9)
                    fc_a(ws_b,row_b,6,f"{'+'if r_b['pm']>=0 else ''}{int(r_b['pm'])}",bold=True,bg=bg_rb,size=9)
                    fc_a(ws_b,row_b,7,f"{'+'if pm_v>=0 else ''}{pm_v}",bold=True,bg=pm_bg,fg=pm_fg,size=9)
                    fc_a(ws_b,row_b,8,concl,bg=bg_rb,align='left',size=9)
                    ws_b.row_dimensions[row_b].height=16; row_b+=1

                row_b += 1

            buf_a=io_arq.BytesIO(); wb_a.save(buf_a); buf_a.seek(0)
            st.download_button(
                label=f"📥 Clic per descarregar — {eq_filtre_arq}",
                data=buf_a.getvalue(),
                file_name=f"arquetips_{eq_filtre_arq.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_excel_arq"
            )

        # ── Anàlisi d'ecosistema: amb qui rendeix millor cada jugadora ──────
        st.markdown(sec("🔍 Anàlisi d'ecosistema — amb quins arquetips rendeix millor?"), unsafe_allow_html=True)
        st.caption("Creua els quintets/parelles ja calculats amb els arquetips per veure quines combinacions d'estils funcionen millor juntes.")

        jug_eco = st.selectbox("Jugadora a analitzar", df_show_arq["Jugadora"].tolist(), key="jug_eco_arq")

        if jug_eco:
            arquetip_jug = df_show_arq[df_show_arq["Jugadora"]==jug_eco]["Arquetip"].values[0]
            equip_jug = agg_arq[agg_arq[col_j_arq]==jug_eco]["equip"].values[0] if col_j_arq in agg_arq.columns else df_show_arq[df_show_arq["Jugadora"]==jug_eco]["Equip"].values[0]

            st.markdown(f'<div style="font-size:13px;font-weight:600;color:#185FA5;margin-bottom:8px">'
                       f'{jug_eco} — <span style="color:#0C447C">{arquetip_jug}</span></div>', unsafe_allow_html=True)

            # Calcula +/- de la jugadora quan juga amb cada altra jugadora (parelles)
            ecosistema_rows = []
            df_pr_eco = load_partits_db()

            for _,p_eco in df_pr_eco.iterrows():
                mid_eco = p_eco['match_id']
                df_m_eco = load_jugades_db(mid_eco)
                if df_m_eco.empty: continue
                col_j_m = "jugador" if "jugador" in df_m_eco.columns else "jugadora"
                df_m_eco["jugador"] = df_m_eco[col_j_m].fillna("")
                if jug_eco not in df_m_eco["jugador"].values: continue

                rows_par_eco = calc_pm_combinacions(df_m_eco, mode="parelles")
                for r_par_eco in rows_par_eco:
                    if jug_eco in r_par_eco["combinacio"]:
                        altra = [j for j in r_par_eco["combinacio"] if j != jug_eco]
                        if not altra: continue
                        altra_jug = altra[0]
                        ecosistema_rows.append({
                            "company": altra_jug,
                            "minuts": r_par_eco["minuts"],
                            "pf": r_par_eco["pf"],
                            "pc": r_par_eco["pc"]
                        })

            if ecosistema_rows:
                df_eco = pd.DataFrame(ecosistema_rows)
                eco_acum = df_eco.groupby("company").agg(
                    minuts=("minuts","sum"), pf=("pf","sum"), pc=("pc","sum")
                ).reset_index()
                eco_acum["pm"] = eco_acum["pf"]-eco_acum["pc"]
                eco_acum["pm_min"] = (eco_acum["pm"]/eco_acum["minuts"].replace(0,1)).round(3)

                # Afegeix l'arquetip de cada company
                arq_map = dict(zip(df_show_arq["Jugadora"], df_show_arq["Arquetip"]))
                eco_acum["Arquetip company"] = eco_acum["company"].map(arq_map).fillna("—")

                # Agrupa per arquetip del company
                eco_per_arq = eco_acum.groupby("Arquetip company").agg(
                    minuts=("minuts","sum"), pf=("pf","sum"), pc=("pc","sum")
                ).reset_index()
                eco_per_arq["pm"] = eco_per_arq["pf"]-eco_per_arq["pc"]
                eco_per_arq["pm_min"] = (eco_per_arq["pm"]/eco_per_arq["minuts"].replace(0,1)).round(3)
                eco_per_arq = eco_per_arq[eco_per_arq["minuts"]>=2].sort_values("pm_min", ascending=False)

                if not eco_per_arq.empty:
                    colors_eco = ["#16a34a" if v>=0 else "#dc2626" for v in eco_per_arq["pm_min"]]
                    fig_eco = go.Figure()
                    fig_eco.add_trace(go.Bar(
                        y=eco_per_arq["Arquetip company"],
                        x=eco_per_arq["pm_min"],
                        orientation='h',
                        marker_color=colors_eco,
                        text=[f"{'+'if v>=0 else ''}{v:.3f}" for v in eco_per_arq["pm_min"]],
                        textposition="outside",
                        customdata=eco_per_arq["minuts"],
                        hovertemplate="<b>%{y}</b><br>+/- per min: %{x:+.3f}<br>Minuts junts: %{customdata:.1f}<extra></extra>"
                    ))
                    fig_eco.add_vline(x=0, line_dash="solid", line_color="#e2e4e8")
                    fig_eco.update_xaxes(title="+/- per minut quan juguen junts")
                    fig_eco.update_layout(height=max(250, len(eco_per_arq)*40))
                    st.plotly_chart(chart_style(fig_eco, max(250, len(eco_per_arq)*40),
                        f"{jug_eco} — rendiment segons l'arquetip del company"), use_container_width=True)

                    millor_arq = eco_per_arq.iloc[0]
                    pitjor_arq = eco_per_arq.iloc[-1]
                    st.info(f"📊 **{jug_eco}** rendeix millor amb perfils **{millor_arq['Arquetip company']}** "
                            f"({millor_arq['pm_min']:+.3f}/min, {millor_arq['minuts']:.0f} min junts) i pitjor amb "
                            f"**{pitjor_arq['Arquetip company']}** ({pitjor_arq['pm_min']:+.3f}/min, {pitjor_arq['minuts']:.0f} min junts).")

                    # Detall per company individual
                    with st.expander("Veure detall per companya individual"):
                        eco_detall = eco_acum[["company","Arquetip company","minuts","pm","pm_min"]].sort_values("pm_min", ascending=False)
                        eco_detall.columns = ["Companya","Arquetip","Min junts","+/-","+/- per min"]
                        html_eco = '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px;color:#1a2744">'
                        html_eco += '<tr>' + ''.join(f'<th style="background:#D6E8F7;color:#0C447C;padding:6px 10px;text-align:center;border:1px solid #B5D4F4;font-weight:600">{c}</th>' for c in eco_detall.columns) + '</tr>'
                        for i_e,(_,row_e) in enumerate(eco_detall.iterrows()):
                            bg_e = '#ffffff' if i_e%2==0 else '#EBF4FC'
                            html_eco += '<tr>'
                            for ci_e,col_e in enumerate(eco_detall.columns):
                                align_e = 'left' if ci_e<2 else 'center'
                                html_eco += f'<td style="padding:5px 10px;border:1px solid #B5D4F4;background:{bg_e};color:#1a2744;text-align:{align_e}">{row_e[col_e]}</td>'
                            html_eco += '</tr>'
                        html_eco += '</table></div>'
                        st.markdown(html_eco, unsafe_allow_html=True)
                else:
                    st.info("No hi ha prou minuts compartits amb altres jugadores per fer l'anàlisi.")
            else:
                st.info("No hi ha dades suficients de parelles per a aquesta jugadora.")

# ══════════════════════════════════════════════════
# TAB 6: MAPA DE TIR
# ══════════════════════════════════════════════════
with t7:
    st.markdown(sec("Mapa de tir — partit actual"), unsafe_allow_html=True)
    st.caption("Mida del cercle = volum · Color = eficiència: verd >55%, taronja 35–55%, vermell <35%")

    # ── Migració BD tirs_fcbq ───────────────────────────────────────────────
    try:
        con_t = sqlite3.connect(DB_PATH)
        con_t.execute("""CREATE TABLE IF NOT EXISTS tirs_fcbq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT, data_consulta TEXT,
            equip_nom TEXT, x REAL, y REAL, fet INTEGER
        )""")
        con_t.commit(); con_t.close()
    except: pass

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

    def load_tirs_fcbq(match_id=None, equip_nom=None):
        con_t = sqlite3.connect(DB_PATH)
        q = "SELECT * FROM tirs_fcbq WHERE 1=1"
        params = []
        if match_id: q += " AND match_id=?"; params.append(match_id)
        if equip_nom: q += " AND equip_nom=?"; params.append(equip_nom)
        df_t = pd.read_sql(q, con_t, params=params)
        con_t.close()
        return df_t

    def classifica_zona_tir(x_raw, y_raw):
        """Classifica un tir en una de 7 zones segons les coordenades x,y del web FCBQ.
        x: 0-100% (eix horitzontal, cistella a x≈48-50%)
        y: ~11-100% (eix vertical, y baix = a prop de la cistella)
        """
        # Zona pintada: a prop de la cistella i centrada
        if y_raw <= 28 and 30 <= x_raw <= 70:
            return "🎯 Zona pintada"
        # Per sobre del llindar de triple aproximat (a partir d'on l'arc toca als laterals)
        # Triple si y és gran (lluny) i a més x és extrem (cantons) o y molt gran (centre)
        es_triple = (y_raw >= 58) or (y_raw >= 35 and (x_raw <= 18 or x_raw >= 82))
        if es_triple:
            if x_raw < 38: return "🏹 Triple esquerra"
            elif x_raw > 62: return "🏹 Triple dreta"
            else: return "🏹 Triple centre"
        else:
            if x_raw < 38: return "📍 Mig esquerra"
            elif x_raw > 62: return "📍 Mig dreta"
            else: return "📍 Mig centre"

    def dibuixa_mapa_tir_fcbq(tirs_list, titol="Mapa de tir", W=340, H=400):
        """Mig camp vertical. Cistella dalt al centre.
        Cada tir (x,y) és 0-100% relatiu al SEU PROPI mig camp individual.
        Cistella a x≈48-50%, y≈12-16% (dalt-centre).
        Mapeig directe: px=x%*W, py=y%*H (escalat per deixar marge dalt).
        """
        import math
        svg = []
        svg.append(f'<svg viewBox="0 0 {W} {H+38}" xmlns="http://www.w3.org/2000/svg" '
                   f'style="width:100%;max-width:420px;border-radius:10px">')
        svg.append(f'<rect width="{W}" height="{H}" fill="#e8e0d0" rx="6"/>')
        s  = 'stroke="#2d5a2d" stroke-width="1.5" fill="none"'
        sf = 'stroke="#2d5a2d" stroke-width="1.5" fill="rgba(255,255,255,0.18)"'

        cx_c = W // 2
        cy_c = 22

        svg.append(f'<rect x="4" y="4" width="{W-8}" height="{H-8}" {s} rx="3"/>')
        svg.append(f'<circle cx="{cx_c}" cy="{cy_c}" r="9" {sf}/>')
        svg.append(f'<circle cx="{cx_c}" cy="{cy_c}" r="3" fill="#2d5a2d"/>')

        z_w = int(W * 0.40); z_h = int(H * 0.34)
        z_x = (W - z_w) // 2
        svg.append(f'<rect x="{z_x}" y="4" width="{z_w}" height="{z_h}" {sf}/>')
        r_zona = z_w // 2
        svg.append(f'<path d="M {z_x} {4+z_h} A {r_zona} {r_zona} 0 0 0 {z_x+z_w} {4+z_h}" {s}/>')

        # Arc de triple: radi = 1.25 × distància lateral → sempre visible als dos costats
        dx_paret = cx_c - 4
        r_triple = int(dx_paret * 1.25)
        dy_paret = int(math.sqrt(max(r_triple**2 - dx_paret**2, 0)))
        y_paret = cy_c + dy_paret
        svg.append(f'<line x1="4" y1="4" x2="4" y2="{y_paret}" {s}/>')
        svg.append(f'<line x1="{W-4}" y1="4" x2="{W-4}" y2="{y_paret}" {s}/>')
        svg.append(f'<path d="M 4 {y_paret} A {r_triple} {r_triple} 0 0 0 {W-4} {y_paret}" {s}/>')

        svg.append(f'<line x1="4" y1="{H-4}" x2="{W-4}" y2="{H-4}" {s}/>')

        # ── Tirs ──────────────────────────────────────────────────────────
        # Mapeig directe: x → eix horitzontal, y → eix vertical
        # y mínim real ≈ 11 (línia de fons, a prop de la cistella, dalt)
        # y màxim ≈ 70-100 (línia de mig camp, baix)
        Y_MIN, Y_MAX = 8, 100
        fets_n = 0; fallats_n = 0
        for t in tirs_list:
            x_raw = float(t['x'])
            y_raw = float(t['y'])

            px = (x_raw / 100) * W
            py = ((y_raw - Y_MIN) / (Y_MAX - Y_MIN)) * H

            px = max(8, min(W-8, px))
            py = max(8, min(H-8, py))
            fet = bool(int(t.get('fet', 0)))

            if fet:
                fets_n += 1
                svg.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="7" fill="#16a34a" '
                           f'opacity="0.85" stroke="white" stroke-width="1.5">'
                           f'<title>✅ Cistella</title></circle>')
            else:
                fallats_n += 1
                svg.append(f'<line x1="{px-5:.1f}" y1="{py-5:.1f}" x2="{px+5:.1f}" y2="{py+5:.1f}" '
                           f'stroke="#dc2626" stroke-width="2.5" opacity="0.8"/>')
                svg.append(f'<line x1="{px+5:.1f}" y1="{py-5:.1f}" x2="{px-5:.1f}" y2="{py+5:.1f}" '
                           f'stroke="#dc2626" stroke-width="2.5" opacity="0.8"/>')

        ef = round(fets_n / max(fets_n + fallats_n, 1) * 100)
        svg.append(f'<text x="{W//2}" y="{H+16}" font-family="Arial" font-size="11" '
                   f'fill="#374151" text-anchor="middle" font-weight="bold">{titol}</text>')
        svg.append(f'<text x="{W//2}" y="{H+32}" font-family="Arial" font-size="10" '
                   f'fill="#374151" text-anchor="middle">'
                   f'✅ {fets_n} cistelles  ❌ {fallats_n} fallats  ·  {ef}% ef.</text>')
        svg.append('</svg>')
        return ''.join(svg)

    def dibuixa_heatmap_fcbq(tirs_list, titol="Mapa de calor", mode="tots", W=340, H=400):
        """Heatmap de densitat de tirs. mode: 'tots','cistelles','fallats'"""
        import math
        # Filtra segons mode
        if mode == "cistelles":
            tirs_f = [t for t in tirs_list if t.get('fet')]
        elif mode == "fallats":
            tirs_f = [t for t in tirs_list if not t.get('fet')]
        else:
            tirs_f = tirs_list

        if not tirs_f:
            return f'<svg viewBox="0 0 {W} {H+38}" xmlns="http://www.w3.org/2000/svg"><text x="{W//2}" y="{H//2}" text-anchor="middle" font-family="Arial" font-size="14" fill="#888">Sense dades</text></svg>'

        Y_MIN, Y_MAX = 8, 100
        svg = []
        svg.append(f'<svg viewBox="0 0 {W} {H+38}" xmlns="http://www.w3.org/2000/svg" '
                   f'style="width:100%;max-width:420px;border-radius:10px">')
        svg.append(f'<rect width="{W}" height="{H}" fill="#e8e0d0" rx="6"/>')

        # Grid de cel·les per calcular densitat
        COLS, ROWS = 12, 15
        cell_w = W / COLS
        cell_h = H / ROWS
        grid = [[0]*COLS for _ in range(ROWS)]
        for t in tirs_f:
            x_raw = float(t['x'])
            y_raw = float(t['y'])
            px = (x_raw / 100) * W
            py = ((y_raw - Y_MIN) / (Y_MAX - Y_MIN)) * H
            col_g = min(int(px / cell_w), COLS-1)
            row_g = min(int(py / cell_h), ROWS-1)
            if 0 <= col_g < COLS and 0 <= row_g < ROWS:
                grid[row_g][col_g] += 1

        max_v = max(max(r) for r in grid) or 1

        # Colors del heatmap (transparent → groc → taronja → vermell)
        def heat_color(v, max_v):
            if v == 0: return None
            ratio = v / max_v
            if mode == "cistelles":
                # Verd clar → verd fosc
                r = int(200 - ratio * 150)
                g = int(240 - ratio * 100)
                b = int(150 - ratio * 130)
            elif mode == "fallats":
                # Groc → vermell
                r = int(220 + ratio * 35)
                g = int(200 - ratio * 180)
                b = int(50 - ratio * 50)
            else:
                # Blau clar → blau fosc → vermell
                if ratio < 0.5:
                    r = int(100 + ratio * 100)
                    g = int(150 + ratio * 50)
                    b = int(240 - ratio * 80)
                else:
                    r = int(200 + (ratio-0.5)*110)
                    g = int(175 - (ratio-0.5)*350)
                    b = int(200 - (ratio-0.5)*400)
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))
            opacity = 0.3 + ratio * 0.65
            return f'rgba({r},{g},{b},{opacity:.2f})'

        for row_g in range(ROWS):
            for col_g in range(COLS):
                v = grid[row_g][col_g]
                color = heat_color(v, max_v)
                if color:
                    x0 = col_g * cell_w
                    y0 = row_g * cell_h
                    svg.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" '
                               f'width="{cell_w:.1f}" height="{cell_h:.1f}" '
                               f'fill="{color}" rx="3"/>')

        # Línies de la pista sobre el heatmap
        s = 'stroke="#2d5a2d" stroke-width="1.5" fill="none"'
        sf = 'stroke="#2d5a2d" stroke-width="1" fill="none" stroke-dasharray="3,3"'
        cx_c = W // 2; cy_c = 22
        svg.append(f'<rect x="4" y="4" width="{W-8}" height="{H-8}" {s} rx="3"/>')
        svg.append(f'<circle cx="{cx_c}" cy="{cy_c}" r="9" stroke="#2d5a2d" stroke-width="2" fill="rgba(255,255,255,0.7)"/>')
        svg.append(f'<circle cx="{cx_c}" cy="{cy_c}" r="3" fill="#2d5a2d"/>')
        z_w = int(W*0.40); z_h = int(H*0.34); z_x = (W-z_w)//2
        svg.append(f'<rect x="{z_x}" y="4" width="{z_w}" height="{z_h}" {sf}/>')
        r_zona = z_w//2
        svg.append(f'<path d="M {z_x} {4+z_h} A {r_zona} {r_zona} 0 0 0 {z_x+z_w} {4+z_h}" {s}/>')
        dx_p = cx_c-4
        r_t = int(dx_p * 1.25)
        dy_p = int(math.sqrt(max(r_t**2-dx_p**2,0)))
        y_p = cy_c+dy_p
        svg.append(f'<line x1="4" y1="4" x2="4" y2="{y_p}" {s}/>')
        svg.append(f'<line x1="{W-4}" y1="4" x2="{W-4}" y2="{y_p}" {s}/>')
        svg.append(f'<path d="M 4 {y_p} A {r_t} {r_t} 0 0 0 {W-4} {y_p}" {s}/>')
        svg.append(f'<line x1="4" y1="{H-4}" x2="{W-4}" y2="{H-4}" {s}/>')

        # Títol i stats
        n_show = len(tirs_f)
        fets_n = sum(1 for t in tirs_f if t.get('fet'))
        svg.append(f'<text x="{W//2}" y="{H+16}" font-family="Arial" font-size="11" '
                   f'fill="#374151" text-anchor="middle" font-weight="bold">{titol}</text>')
        svg.append(f'<text x="{W//2}" y="{H+32}" font-family="Arial" font-size="10" '
                   f'fill="#374151" text-anchor="middle">{n_show} tirs · '
                   f'{fets_n} cistelles · {round(fets_n/max(n_show,1)*100)}% ef.</text>')
        svg.append('</svg>')
        return ''.join(svg)

    def dibuixa_zones_camp(df_zones, value_col="pct_tirs", titol="Distribució de tirs per zona",
                            colorscale="sequential", fmt="{:.0f}%", W=340, H=400):
        """Pinta les 7 zones de classifica_zona_tir directament sobre el camp SVG, acolorides
        segons df_zones[value_col], amb etiqueta de valor i n de tirs al centroide de cada zona.

        df_zones: DataFrame amb columnes ["zona", value_col] (+ "tirs_sel" opcional per l'etiqueta n=).
        colorscale: "sequential" (un sol color, C_BG_SOFT -> C_ACCENT_DARK) o
                    "diverging" (C_ERROR <-> C_SUCCESS, centrat a 0, per a diferencials com diff_sq).
        """
        import math
        if df_zones.empty:
            return (f'<svg viewBox="0 0 {W} {H+38}" xmlns="http://www.w3.org/2000/svg">'
                    f'<text x="{W//2}" y="{H//2}" text-anchor="middle" font-family="Arial" '
                    f'font-size="14" fill="#888">Sense dades</text></svg>')

        def hex_rgb(h):
            h = h.lstrip('#')
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

        Y_MIN, Y_MAX = 8, 100
        COLS, ROWS = 60, 70  # graella fina -> vores de zona netes, sense calcular polígons a mà

        vals = df_zones.set_index("zona")[value_col].to_dict()
        tirs_n = df_zones.set_index("zona")["tirs_sel"].to_dict() if "tirs_sel" in df_zones.columns else {}

        vmin, vmax = min(vals.values()), max(vals.values())
        if colorscale == "diverging":
            amp = max(abs(vmin), abs(vmax), 0.01)
            vmin, vmax = -amp, amp

        def color_for(v):
            if colorscale == "diverging":
                t = (v - vmin) / (vmax - vmin)
                if t < 0.5:
                    (r0, g0, b0), (r1, g1, b1) = hex_rgb(C_ERROR), hex_rgb(C_CHART_GRID)
                    tt = t / 0.5
                else:
                    (r0, g0, b0), (r1, g1, b1) = hex_rgb(C_CHART_GRID), hex_rgb(C_SUCCESS)
                    tt = (t - 0.5) / 0.5
            else:
                tt = 0 if vmax == vmin else (v - vmin) / (vmax - vmin)
                (r0, g0, b0), (r1, g1, b1) = hex_rgb(C_BG_SOFT), hex_rgb(C_ACCENT_DARK)
            r = int(r0 + (r1 - r0) * tt); g = int(g0 + (g1 - g0) * tt); b = int(b0 + (b1 - b0) * tt)
            return f"rgb({r},{g},{b})"

        svg = [f'<svg viewBox="0 0 {W} {H+38}" xmlns="http://www.w3.org/2000/svg" '
               f'style="width:100%;max-width:420px;border-radius:10px">']
        svg.append(f'<rect width="{W}" height="{H}" fill="#e8e0d0" rx="6"/>')

        # Graella de cel·les acolorides per zona (sense stroke -> es fonen en un bloc continu)
        cell_w = W / COLS; cell_h = H / ROWS
        centroides = {}  # zona -> [suma_px, suma_py, n_cel·les]
        for row in range(ROWS):
            for col in range(COLS):
                px = col * cell_w; py = row * cell_h
                x_raw = ((px + cell_w / 2) / W) * 100
                y_raw = Y_MIN + ((py + cell_h / 2) / H) * (Y_MAX - Y_MIN)
                zona = classifica_zona_tir(x_raw, y_raw)
                if zona not in vals:
                    continue  # zona sense dades (mostra insuficient) -> es deixa sense pintar
                svg.append(f'<rect x="{px:.1f}" y="{py:.1f}" width="{cell_w+0.5:.1f}" height="{cell_h+0.5:.1f}" '
                           f'fill="{color_for(vals[zona])}" opacity="0.72"/>')
                c = centroides.setdefault(zona, [0, 0, 0])
                c[0] += px + cell_w / 2; c[1] += py + cell_h / 2; c[2] += 1

        # Línies del camp per sobre (mateix bloc que dibuixa_mapa_tir_fcbq, sense fill per no tapar les zones)
        s = 'stroke="#2d5a2d" stroke-width="1.5" fill="none"'
        cx_c = W // 2; cy_c = 22
        svg.append(f'<rect x="4" y="4" width="{W-8}" height="{H-8}" {s} rx="3"/>')
        svg.append(f'<circle cx="{cx_c}" cy="{cy_c}" r="9" {s}/>')
        svg.append(f'<circle cx="{cx_c}" cy="{cy_c}" r="3" fill="#2d5a2d"/>')
        z_w = int(W * 0.40); z_h = int(H * 0.34); z_x = (W - z_w) // 2
        svg.append(f'<rect x="{z_x}" y="4" width="{z_w}" height="{z_h}" {s}/>')
        r_zona = z_w // 2
        svg.append(f'<path d="M {z_x} {4+z_h} A {r_zona} {r_zona} 0 0 0 {z_x+z_w} {4+z_h}" {s}/>')
        dx_paret = cx_c - 4
        r_triple = int(dx_paret * 1.25)
        dy_paret = int(math.sqrt(max(r_triple**2 - dx_paret**2, 0)))
        y_paret = cy_c + dy_paret
        svg.append(f'<line x1="4" y1="4" x2="4" y2="{y_paret}" {s}/>')
        svg.append(f'<line x1="{W-4}" y1="4" x2="{W-4}" y2="{y_paret}" {s}/>')
        svg.append(f'<path d="M 4 {y_paret} A {r_triple} {r_triple} 0 0 0 {W-4} {y_paret}" {s}/>')
        svg.append(f'<line x1="4" y1="{H-4}" x2="{W-4}" y2="{H-4}" {s}/>')

        # Etiquetes per zona al seu centroide (valor + n de tirs)
        for zona, (sx, sy, n) in centroides.items():
            cx_z, cy_z = sx / n, sy / n
            txt_val = fmt.format(vals[zona])
            svg.append(f'<text x="{cx_z:.1f}" y="{cy_z-4:.1f}" font-family="Arial" font-size="13" '
                       f'font-weight="bold" fill="#1a2744" text-anchor="middle" '
                       f'style="paint-order:stroke" stroke="white" stroke-width="3">{txt_val}</text>')
            n_tirs = tirs_n.get(zona)
            if n_tirs is not None:
                svg.append(f'<text x="{cx_z:.1f}" y="{cy_z+9:.1f}" font-family="Arial" font-size="9" '
                           f'fill="#374151" text-anchor="middle" '
                           f'style="paint-order:stroke" stroke="white" stroke-width="2.5">n={int(n_tirs)}</text>')

        svg.append(f'<text x="{W//2}" y="{H+18}" font-family="Arial" font-size="11" '
                   f'fill="#374151" text-anchor="middle" font-weight="bold">{titol}</text>')
        svg.append('</svg>')
        return ''.join(svg)

    # ── Secció mapa FCBQ ────────────────────────────────────────────────────
    st.markdown(sec("Mapa de tir — dades de la FCBQ"), unsafe_allow_html=True)
    st.caption("Extreu les coordenades del web de la FCBQ i guarda-les aquí per veure el mapa i l'acumulat.")

    with st.expander("📋 Script per extreure les dades (copia i enganxa a la Console F12 del navegador)"):
        st.code("""// 1. Ves al web FCBQ → mapa de tir del partit
// 2. F12 → Console → escriu "allow pasting" → Enter
// 3. Enganxa aquest script → Enter
// 4. Es copiarà automàticament al portapapers

const punts = [];
document.querySelectorAll('*').forEach(el => {
  const style = el.getAttribute('style') || '';
  const left = style.match(/left:\\s*([\\d.]+)%/);
  const top = style.match(/top:\\s*([\\d.]+)%/);
  if (!left || !top) return;
  let color = '';
  const check = (e) => {
    const s = window.getComputedStyle(e);
    const bg = s.backgroundColor;
    const bc = s.borderColor;
    if (bg && bg !== 'rgba(0, 0, 0, 0)') return bg;
    if (bc && bc !== 'rgba(0, 0, 0, 0)' && bc !== 'rgb(0, 0, 0)') return bc;
    return '';
  };
  color = check(el);
  if (!color) el.querySelectorAll('*').forEach(c => { if (!color) color = check(c); });
  if (!color || (!color.includes('144') && !color.includes('220'))) return;
  const key = `${parseFloat(left[1]).toFixed(1)}_${parseFloat(top[1]).toFixed(1)}`;
  if (!punts.find(p => p.key === key)) {
    punts.push({ key, x: parseFloat(left[1]), y: parseFloat(top[1]), fet: color.includes('144') });
  }
});
copy(JSON.stringify(punts.map(p => ({x:p.x, y:p.y, fet:p.fet}))));
console.log(`✅ Copiat! Total: ${punts.length} | Cistelles: ${punts.filter(p=>p.fet).length} | Fallats: ${punts.filter(p=>!p.fet).length}`);""", language="javascript")

    df_pr_mapa = load_partits_db()
    if not df_pr_mapa.empty:
        mid_mapa = st.selectbox("Associa al partit",
            df_pr_mapa["match_id"].tolist(),
            format_func=lambda x: f"{df_pr_mapa[df_pr_mapa['match_id']==x]['nom_a'].values[0]} vs "
                                   f"{df_pr_mapa[df_pr_mapa['match_id']==x]['nom_b'].values[0]}",
            key="mid_mapa_fcbq")
        p_mapa = df_pr_mapa[df_pr_mapa["match_id"]==mid_mapa].iloc[0]
        nom_local_mapa = p_mapa["nom_a"]; nom_visit_mapa = p_mapa["nom_b"]
    else:
        mid_mapa = "manual"; nom_local_mapa = nom_a; nom_visit_mapa = nom_b

    json_tirs = st.text_area("Enganxa aquí el JSON dels tirs",
        height=80, placeholder='[{"x":46.05,"y":13.76,"fet":true},...]',
        key="json_tirs_fcbq")

    if json_tirs.strip():
        try:
            import json as json_mod
            tirs = json_mod.loads(json_tirs)
            n_total = len(tirs)

            split_idx = st.number_input(
                f"A partir de quina posició comencen els tirs de {nom_visit_mapa}? "
                f"(els primers tirs són de {nom_local_mapa})",
                min_value=0, max_value=n_total, value=n_total//2, step=1,
                key="split_idx_mapa",
                help=f"Total de tirs: {n_total}. Per exemple, si els primers 60 són del local i la resta del visitant, escriu 60."
            )

            tirs_local = tirs[:split_idx]
            tirs_visit = tirs[split_idx:]

            if st.button("💾 Guardar tirs a la BD", key="btn_save_tirs"):
                save_tirs_fcbq(mid_mapa, datetime.now().strftime("%Y-%m-%d"),
                               nom_local_mapa, nom_visit_mapa, tirs_local, tirs_visit)
                st.success(f"✅ {len(tirs)} tirs guardats! ({len(tirs_local)} {nom_local_mapa} + {len(tirs_visit)} {nom_visit_mapa})")

            eq_sel = st.radio("Mostra", ["Tots dos", nom_local_mapa, nom_visit_mapa],
                              horizontal=True, key="eq_sel_mapa")

            viz_sel = st.radio("Visualització", ["🎯 Punts individuals", "🔥 Mapa de calor", "🔥 Calor cistelles", "🔥 Calor fallats"],
                               horizontal=True, key="viz_sel_mapa")

            if eq_sel == nom_local_mapa:
                tirs_show = tirs_local
            elif eq_sel == nom_visit_mapa:
                tirs_show = tirs_visit
            else:
                tirs_show = tirs

            fets_n = sum(1 for t in tirs_show if t.get('fet'))
            tot_n = len(tirs_show)
            c1,c2,c3 = st.columns(3)
            with c1: st.markdown(card("Total tirs",tot_n,eq_sel,"#374151"),unsafe_allow_html=True)
            with c2: st.markdown(card("Cistelles",fets_n,"convertides","#16a34a"),unsafe_allow_html=True)
            with c3: st.markdown(card("Eficiència",f"{round(fets_n/max(tot_n,1)*100)}%","","#185FA5"),unsafe_allow_html=True)

            def mostra_mapa(tirs, titol, viz):
                if viz == "🎯 Punts individuals":
                    st.markdown(dibuixa_mapa_tir_fcbq(tirs, titol), unsafe_allow_html=True)
                elif viz == "🔥 Mapa de calor":
                    st.markdown(dibuixa_heatmap_fcbq(tirs, titol, "tots"), unsafe_allow_html=True)
                elif viz == "🔥 Calor cistelles":
                    st.markdown(dibuixa_heatmap_fcbq(tirs, f"{titol} — cistelles", "cistelles"), unsafe_allow_html=True)
                else:
                    st.markdown(dibuixa_heatmap_fcbq(tirs, f"{titol} — fallats", "fallats"), unsafe_allow_html=True)

            if eq_sel == "Tots dos":
                col_ma, col_mb = st.columns(2)
                with col_ma: mostra_mapa(tirs_local, nom_local_mapa, viz_sel)
                with col_mb: mostra_mapa(tirs_visit, nom_visit_mapa, viz_sel)
            else:
                mostra_mapa(tirs_show, eq_sel, viz_sel)

        except Exception as e:
            st.error(f"Error: {e}")

    # ── Punts a la pintura ───────────────────────────────────────────────────
    st.markdown(sec("🎯 Punts a la pintura"), unsafe_allow_html=True)
    st.caption(
        "Percentatge dels punts totals de cada equip anotats des de la 🎯 Zona pintada, "
        "segons el mapa de tir guardat per aquest partit."
    )
    df_tirs_pintura = load_tirs_fcbq(match_id=match_id)
    col_pin_a, col_pin_b = st.columns(2)
    for col_pin, tid_pin, nom_pin, color_pin in [
        (col_pin_a, teams[0] if teams else None, nom_a, COLOR_A),
        (col_pin_b, teams[1] if len(teams)>1 else None, nom_b, COLOR_B),
    ]:
        with col_pin:
            st.markdown(f"**{nom_pin}**")
            df_tirs_eq_pin = df_tirs_pintura[df_tirs_pintura["equip_nom"]==nom_pin] if not df_tirs_pintura.empty else df_tirs_pintura
            if tid_pin is None or df_tirs_eq_pin.empty:
                st.caption("— Sense mapa de tir per aquest partit —")
                continue
            zones_pin = df_tirs_eq_pin.apply(lambda r: classifica_zona_tir(float(r["x"]), float(r["y"])), axis=1)
            fets_pintura = int(df_tirs_eq_pin[zones_pin=="🎯 Zona pintada"]["fet"].sum())
            pts_pintura = fets_pintura * 2
            pts_tot_eq_pin = int(df_orig[df_orig["idEquip"]==tid_pin]["punts"].sum())
            pct_pin = round(pts_pintura / pts_tot_eq_pin * 100, 1) if pts_tot_eq_pin > 0 else 0
            st.markdown(card("% Punts a la pintura", f"{pct_pin}%",
                f"{pts_pintura} de {pts_tot_eq_pin} punts totals", color_pin), unsafe_allow_html=True)

    # ── Mapa acumulat ───────────────────────────────────────────────────────
    st.markdown(sec("Mapa de tir acumulat — temporada"), unsafe_allow_html=True)
    df_tirs_bd = load_tirs_fcbq()
    if df_tirs_bd.empty:
        st.info("Guarda tirs de partits per veure l'acumulat de temporada.")
    else:
        partits_tirs = sorted(df_tirs_bd["match_id"].unique().tolist())
        df_pr_acum = load_partits_db()
        sel_partits = st.multiselect("Partits", partits_tirs, default=partits_tirs,
            format_func=lambda x: f"{df_pr_acum[df_pr_acum['match_id']==x]['nom_a'].values[0]} vs "
                                   f"{df_pr_acum[df_pr_acum['match_id']==x]['nom_b'].values[0]}"
                                   if not df_pr_acum.empty and x in df_pr_acum["match_id"].values else x[:8],
            key="sel_partits_mapa")
        if sel_partits:
            df_acum = df_tirs_bd[df_tirs_bd["match_id"].isin(sel_partits)]

            equips_acum = sorted(df_acum["equip_nom"].dropna().unique().tolist())
            eq_acum_sel = st.radio("Filtra per equip", ["Tots els equips"] + equips_acum,
                horizontal=True, key="eq_acum_sel")
            if eq_acum_sel != "Tots els equips":
                df_acum = df_acum[df_acum["equip_nom"] == eq_acum_sel]

            tirs_acum = df_acum[["x","y","fet"]].to_dict("records")
            fets_a = int(df_acum["fet"].sum()); tot_a = len(df_acum)
            c1,c2,c3 = st.columns(3)
            with c1: st.markdown(card("Total tirs",tot_a,f"{len(sel_partits)} partits","#374151"),unsafe_allow_html=True)
            with c2: st.markdown(card("Cistelles",fets_a,"convertides","#16a34a"),unsafe_allow_html=True)
            with c3: st.markdown(card("Eficiència",f"{round(fets_a/max(tot_a,1)*100)}%","","#185FA5"),unsafe_allow_html=True)

            viz_acum = st.radio("Visualització",
                ["🎯 Punts individuals","🔥 Mapa de calor","🔥 Calor cistelles","🔥 Calor fallats"],
                horizontal=True, key="viz_acum_mapa")

            titol_acum = (f"{eq_acum_sel} — {len(sel_partits)} partits" if eq_acum_sel != "Tots els equips"
                          else f"{len(sel_partits)} partits seleccionats")
            if viz_acum == "🎯 Punts individuals":
                st.markdown(dibuixa_mapa_tir_fcbq(tirs_acum, titol_acum), unsafe_allow_html=True)
            elif viz_acum == "🔥 Mapa de calor":
                st.markdown(dibuixa_heatmap_fcbq(tirs_acum, titol_acum, "tots"), unsafe_allow_html=True)
            elif viz_acum == "🔥 Calor cistelles":
                st.markdown(dibuixa_heatmap_fcbq(tirs_acum, f"{titol_acum} — cistelles", "cistelles"), unsafe_allow_html=True)
            else:
                st.markdown(dibuixa_heatmap_fcbq(tirs_acum, f"{titol_acum} — fallats", "fallats"), unsafe_allow_html=True)

            # ── Shot Quality casolà: eficiència real vs mitjana de zona ──────
            st.markdown(sec("📐 Shot Quality — eficiència per zona"), unsafe_allow_html=True)
            st.caption(
                "Compara l'eficiència real de cada zona amb la mitjana pròpia de temporada "
                "(basada en tots els tirs acumulats a la BD). Inspirat en el concepte 'Shot Quality' "
                "de Synergy Sports, adaptat a les nostres dades."
            )

            # Calcula la mitjana de referència amb TOTS els tirs de la BD (no només els seleccionats)
            df_tots_tirs = load_tirs_fcbq()
            if len(df_tots_tirs) < 30:
                st.info(f"Tens {len(df_tots_tirs)} tirs acumulats. Calen almenys 30 tirs "
                        "per tenir una referència de zona mínimament fiable.")
            else:
                # Selector d'equip per filtrar
                equips_sq = sorted(df_tots_tirs["equip_nom"].dropna().unique().tolist())
                equips_sq_opts = ["Tots els equips"] + equips_sq
                eq_sq_sel = st.radio("Filtra per equip", equips_sq_opts, horizontal=True, key="eq_sq_sel")

                df_tots_tirs = df_tots_tirs.copy()
                if eq_sq_sel != "Tots els equips":
                    df_tots_tirs_ref = df_tots_tirs[df_tots_tirs["equip_nom"]==eq_sq_sel].copy()
                    df_acum_sq_fil = df_acum[df_acum["equip_nom"]==eq_sq_sel].copy() if "equip_nom" in df_acum.columns else df_acum.copy()
                else:
                    df_tots_tirs_ref = df_tots_tirs.copy()
                    df_acum_sq_fil = df_acum.copy()

                if len(df_tots_tirs_ref) < 30:
                    st.info(f"Tens {len(df_tots_tirs_ref)} tirs de '{eq_sq_sel}'. Calen almenys 30 per una referència fiable.")
                else:
                    df_tots_tirs_ref["zona"] = df_tots_tirs_ref.apply(
                        lambda r: classifica_zona_tir(float(r["x"]), float(r["y"])), axis=1)

                    ref_zones = df_tots_tirs_ref.groupby("zona").agg(
                        tirs_ref=("fet","count"), fets_ref=("fet","sum")
                    ).reset_index()
                    ref_zones["ef_ref"] = (ref_zones["fets_ref"]/ref_zones["tirs_ref"]*100).round(1)

                    # Zona dels tirs seleccionats (filtre actual + filtre equip)
                    df_acum_z = df_acum_sq_fil.copy()
                    df_acum_z["zona"] = df_acum_z.apply(
                        lambda r: classifica_zona_tir(float(r["x"]), float(r["y"])), axis=1)
                    sel_zones = df_acum_z.groupby("zona").agg(
                        tirs_sel=("fet","count"), fets_sel=("fet","sum")
                    ).reset_index()
                    sel_zones["ef_sel"] = (sel_zones["fets_sel"]/sel_zones["tirs_sel"]*100).round(1)

                    # Valor del tir: 3 punts si és zona de triple, 2 punts altrament
                    def valor_zona(z):
                        return 3 if "Triple" in z else 2
                    sel_zones["valor_tir"] = sel_zones["zona"].apply(valor_zona)
                    sel_zones["pps_sel"] = (sel_zones["ef_sel"]/100 * sel_zones["valor_tir"]).round(2)

                    ref_zones["valor_tir"] = ref_zones["zona"].apply(valor_zona)
                    ref_zones["pps_ref"] = (ref_zones["ef_ref"]/100 * ref_zones["valor_tir"]).round(2)

                    df_sq = sel_zones.merge(ref_zones[["zona","tirs_ref","ef_ref","pps_ref"]], on="zona", how="left")
                    df_sq["diff_sq"] = (df_sq["ef_sel"] - df_sq["ef_ref"]).round(1)
                    df_sq["diff_pps"] = (df_sq["pps_sel"] - df_sq["pps_ref"]).round(2)
                    ordre_zones = ["🎯 Zona pintada","📍 Mig esquerra","📍 Mig centre","📍 Mig dreta",
                                   "🏹 Triple esquerra","🏹 Triple centre","🏹 Triple dreta"]
                    df_sq["_ordre"] = df_sq["zona"].apply(lambda z: ordre_zones.index(z) if z in ordre_zones else 99)
                    df_sq = df_sq.sort_values("_ordre")

                    if not df_sq.empty:
                        colors_sq = ["#16a34a" if v>=0 else "#dc2626" for v in df_sq["diff_sq"]]
                        fig_sq = go.Figure()
                        fig_sq.add_trace(go.Bar(
                            x=df_sq["zona"], y=df_sq["diff_sq"],
                            marker_color=colors_sq,
                            text=[f"{'+'if v>=0 else ''}{v}pp" for v in df_sq["diff_sq"]],
                            textposition="outside",
                            customdata=df_sq[["tirs_sel","ef_sel","ef_ref"]].values,
                            hovertemplate="<b>%{x}</b><br>Tirs: %{customdata[0]}<br>"
                                          "Eficiència real: %{customdata[1]}%<br>"
                                          "Mitjana temporada: %{customdata[2]}%<extra></extra>"
                        ))
                        fig_sq.add_hline(y=0, line_dash="solid", line_color="#e2e4e8")
                        fig_sq.update_layout(yaxis_title="Diferència vs mitjana de zona (punts %)")
                        st.plotly_chart(chart_style(fig_sq, 280, "Eficiència real vs mitjana esperada per zona"),
                            use_container_width=True)

                        # ── Valor en punts per tir (PPS) — quina zona val més atacar ──
                        st.markdown("**💰 Valor real per tir — quina zona genera més punts**")
                        st.caption(
                            "PPS (Punts Per Tir) = % d'encert × valor del tir (2 o 3 punts). "
                            "Un alt % en una zona de 2 pot valer menys que un % moderat en una zona de 3. "
                            "Aquest és el càlcul que de veritat indica des d'on convé atacar."
                        )

                        df_pps = df_sq[["zona","valor_tir","tirs_sel","ef_sel","pps_sel","pps_ref"]].copy()
                        df_pps = df_pps.sort_values("pps_sel", ascending=False)

                        fig_pps = go.Figure()
                        colors_pps = ["#185FA5" if "Triple" in z else "#0F6E56" for z in df_pps["zona"]]
                        fig_pps.add_trace(go.Bar(
                            x=df_pps["zona"], y=df_pps["pps_sel"],
                            name="PPS actual",
                            marker_color=colors_pps,
                            text=[f"{v:.2f}" for v in df_pps["pps_sel"]],
                            textposition="outside",
                            customdata=df_pps[["tirs_sel","ef_sel","valor_tir"]].values,
                            hovertemplate="<b>%{x}</b><br>PPS: %{y:.2f}<br>Tirs: %{customdata[0]}<br>"
                                          "Eficiència: %{customdata[1]}%<br>Valor tir: %{customdata[2]} punts<extra></extra>"
                        ))
                        fig_pps.add_trace(go.Scatter(
                            x=df_pps["zona"], y=df_pps["pps_ref"],
                            mode="markers", name="PPS mitjana temporada",
                            marker=dict(symbol="diamond", size=11, color="#d97706",
                                       line=dict(width=1.5, color="white"))
                        ))
                        fig_pps.add_hline(y=1.0, line_dash="dot", line_color="#9ca3af",
                            annotation_text="PPS=1.0 (referència)", annotation_font_size=9)
                        fig_pps.update_layout(
                            yaxis_title="Punts per tir (PPS)",
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                        st.plotly_chart(chart_style(fig_pps, 300, "Punts per tir — quina zona val més"),
                            use_container_width=True)

                        # Recomanació tàctica automàtica
                        millor_pps = df_pps.iloc[0]
                        zones_amb_mostra = df_pps[df_pps["tirs_sel"] >= 5].sort_values("pps_sel", ascending=False)
                        if not zones_amb_mostra.empty:
                            rec_zona = zones_amb_mostra.iloc[0]
                            st.success(
                                f"💡 **Recomanació tàctica**: la zona amb millor valor real per tir "
                                f"(amb mostra suficient, ≥5 tirs) és **{rec_zona['zona']}** amb "
                                f"**{rec_zona['pps_sel']:.2f} punts/tir** ({rec_zona['ef_sel']}% d'encert, "
                                f"{int(rec_zona['tirs_sel'])} tirs). Buscar més tirs des d'aquesta zona "
                                f"maximitzaria els punts generats."
                            )
                        else:
                            st.info("Cap zona amb mostra suficient (≥5 tirs) per fer una recomanació fiable.")

                        # Taula detall
                        with st.expander("Veure detall per zona"):
                            df_show_sq = df_sq[["zona","tirs_sel","fets_sel","ef_sel","pps_sel","tirs_ref","ef_ref","pps_ref","diff_sq"]].copy()
                            df_show_sq.columns = ["Zona","Tirs (selecció)","Cistelles","Ef. real %","PPS real","Tirs (ref. temporada)","Ef. mitjana %","PPS mitjana","Diferència pp"]
                            html_sq = '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px;color:#1a2744">'
                            html_sq += '<tr>' + ''.join(f'<th style="background:#D6E8F7;color:#0C447C;padding:6px 10px;text-align:center;border:1px solid #B5D4F4;font-weight:600">{c}</th>' for c in df_show_sq.columns) + '</tr>'
                            for i_sq,(_,row_sq) in enumerate(df_show_sq.iterrows()):
                                bg_sq = '#ffffff' if i_sq%2==0 else '#EBF4FC'
                                html_sq += '<tr>'
                                for ci_sq,col_sq in enumerate(df_show_sq.columns):
                                    align_sq = 'left' if ci_sq==0 else 'center'
                                    html_sq += f'<td style="padding:5px 10px;border:1px solid #B5D4F4;background:{bg_sq};color:#1a2744;text-align:{align_sq}">{row_sq[col_sq]}</td>'
                                html_sq += '</tr>'
                            html_sq += '</table></div>'
                            st.markdown(html_sq, unsafe_allow_html=True)

                        millor_z = df_sq.loc[df_sq["diff_sq"].idxmax()]
                        pitjor_z = df_sq.loc[df_sq["diff_sq"].idxmin()]
                        st.info(f"📊 Zona amb millor rendiment relatiu: **{millor_z['zona']}** "
                                f"({millor_z['diff_sq']:+.1f}pp vs mitjana). "
                                f"Zona amb pitjor rendiment: **{pitjor_z['zona']}** "
                                f"({pitjor_z['diff_sq']:+.1f}pp vs mitjana).")

                        # ── Des d'on tira més l'equip — i on esperar el rebot ────
                        st.markdown("**🏀 Des d'on tira més — i on posicionar-se pel rebot**")
                        st.caption(
                            "Volum de tirs per zona (no eficiència): útil per a l'scouting — si un equip "
                            "concentra molts tirs en una zona, val la pena preparar-hi el rebot. "
                            "El play-by-play de la FCBQ no registra on cau cada rebot, així que això no és "
                            "una predicció calculada amb les teves dades, sinó una pauta general de bàsquet: "
                            "els tirs llargs (triples) generen rebots més llargs i dispersos — sovint cap al "
                            "costat contrari d'on s'ha tirat —, mentre que els tirs des de la zona pintada "
                            "generen rebots curts i molt disputats sota cistella."
                        )
                        df_vol = df_sq.copy()
                        df_vol["pct_tirs"] = (df_vol["tirs_sel"] / df_vol["tirs_sel"].sum() * 100).round(1)
                        df_vol = df_vol.sort_values("_ordre")
                        st.markdown(dibuixa_zones_camp(
                            df_vol[["zona", "pct_tirs", "tirs_sel"]], value_col="pct_tirs",
                            titol="% de tirs per zona", colorscale="sequential", fmt="{:.0f}%"
                        ), unsafe_allow_html=True)

                        zones_amb_vol = df_vol[df_vol["tirs_sel"] >= 5].sort_values("pct_tirs", ascending=False)
                        if not zones_amb_vol.empty:
                            top_vol = zones_amb_vol.iloc[0]
                            if "Triple" in top_vol["zona"]:
                                tip_rebot = "esperar rebots llargs i sovint cap al costat contrari d'aquesta zona"
                            elif "Zona pintada" in top_vol["zona"]:
                                tip_rebot = "esperar rebots curts i molt disputats sota cistella"
                            else:
                                tip_rebot = "esperar rebots de distància mitjana"
                            st.success(
                                f"🎯 **Pauta d'scouting**: el {top_vol['pct_tirs']}% dels tirs (amb mostra "
                                f"suficient) vénen de **{top_vol['zona']}** ({int(top_vol['tirs_sel'])} tirs). "
                                f"Convé {tip_rebot}."
                            )

                        # ── MOREYr — Rim rate + 3PA rate ─────────────────────────
                        st.markdown("**📊 MOREYr — Tirs en zones d'alt valor**")
                        tirs_totals_mr = df_sq["tirs_sel"].sum()
                        tirs_pintada_mr = df_sq[df_sq["zona"]=="🎯 Zona pintada"]["tirs_sel"].sum()
                        tirs_triple_mr = df_sq[df_sq["zona"].str.startswith("🏹")]["tirs_sel"].sum()
                        moreyr = round((tirs_pintada_mr+tirs_triple_mr)/tirs_totals_mr*100, 1) if tirs_totals_mr > 0 else None
                        if moreyr is None:
                            st.info("Cal mapa de tir per calcular MOREYr")
                        else:
                            st.markdown(card("MOREYr", f"{moreyr}%", "Rim + Triple / Total tirs", C_ACCENT),
                                unsafe_allow_html=True)
                            st.caption(
                                "MOREYr alt = l'equip concentra els seus tirs en zones d'alt valor esperat "
                                "(pintada i triple), evitant el mig camp llarg de baixa eficiència. No jutja "
                                "si l'equip encerta més o menys — només d'on tira."
                            )
                    else:
                        st.info("No hi ha prou tirs a la selecció actual per a aquesta anàlisi.")

            # ── Portfolio de tirs — valor, volum i risc per zona ──────────────
            st.markdown(sec("🧺 Portfolio de tirs — valor, volum i risc per zona"), unsafe_allow_html=True)
            st.caption(
                "Inspirat en tractar la selecció de tir com una cartera d'inversió: cada zona "
                "s'avalua per volum (% de tirs), valor (punts per tir) i risc (variabilitat del "
                "PPS entre partits). Categories aproximades: Rim = zona pintada, Midrange = mig camp "
                "(esquerra/centre/dreta), Corner 3 = triples de cantonada, Non-corner 3 = triple de "
                "centre. No inclou continuació per rebot ofensiu (no en tenim dades)."
            )
            equips_port = sorted(df_acum["equip_nom"].dropna().unique().tolist()) if "equip_nom" in df_acum.columns else []
            eq_port_sel = st.radio("Filtra per equip", ["Tots els equips"] + equips_port,
                horizontal=True, key="eq_port_sel")
            df_acum_port = df_acum if eq_port_sel=="Tots els equips" else df_acum[df_acum["equip_nom"]==eq_port_sel]
            df_port = calc_shot_portfolio(df_acum_port)
            if df_port is None or df_port["tirs"].sum() == 0:
                st.info("No hi ha prou tirs classificables en aquesta selecció per calcular el portfolio.")
            else:
                df_port_show = df_port[df_port["tirs"] > 0].copy()
                fig_port = go.Figure()
                for _, rp in df_port_show.iterrows():
                    color_p = "#16a34a" if rp["fiable"] else "#d97706"
                    fig_port.add_trace(go.Scatter(
                        x=[rp["risc"] if rp["risc"] is not None else 0],
                        y=[rp["pps"]],
                        mode="markers+text",
                        marker=dict(size=max(14, rp["volum_pct"]*1.8), color=color_p, opacity=0.75,
                                    line=dict(width=1.5,color="white")),
                        text=[rp["categoria"]], textposition="top center",
                        hovertemplate=f"<b>{rp['categoria']}</b><br>PPS: {rp['pps']}<br>"
                                      f"Volum: {rp['volum_pct']}%<br>Tirs: {int(rp['tirs'])}<br>"
                                      f"Risc (desv. PPS/partit): {rp['risc'] if rp['risc'] is not None else 'N/D'}<br>"
                                      f"Partits amb dades: {int(rp['n_partits'])}<extra></extra>",
                        showlegend=False
                    ))
                fig_port.update_layout(
                    xaxis_title="Risc (desviació del PPS entre partits)",
                    yaxis_title="Valor (punts per tir)",
                    margin=dict(l=0,r=0,t=30,b=0))
                st.plotly_chart(chart_style(fig_port, 340, "Valor vs risc per zona (mida = volum de tirs · verd = risc fiable, ⚠️ taronja = poca mostra)"),
                    use_container_width=True)

                with st.expander("Veure detall del portfolio de tirs"):
                    df_show_port = df_port_show[["categoria","tirs","volum_pct","ef","valor_tir","pps","risc","n_partits"]].copy()
                    df_show_port["risc"] = df_show_port["risc"].apply(lambda v: v if pd.notna(v) else "N/D")
                    df_show_port.columns = ["Categoria","Tirs","% Volum","Encert %","Valor tir","PPS","Risc (desv. PPS)","Partits"]
                    html_port = '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px;color:#1a2744">'
                    html_port += '<tr>' + ''.join(f'<th style="background:#D6E8F7;color:#0C447C;padding:6px 10px;text-align:center;border:1px solid #B5D4F4;font-weight:600">{c}</th>' for c in df_show_port.columns) + '</tr>'
                    for i_p,(_,row_p) in enumerate(df_show_port.iterrows()):
                        bg_p = '#ffffff' if i_p%2==0 else '#EBF4FC'
                        html_port += '<tr>'
                        for ci_p,col_p in enumerate(df_show_port.columns):
                            align_p = 'left' if ci_p==0 else 'center'
                            html_port += f'<td style="padding:5px 10px;border:1px solid #B5D4F4;background:{bg_p};color:#1a2744;text-align:{align_p}">{row_p[col_p]}</td>'
                        html_port += '</tr>'
                    html_port += '</table></div>'
                    st.markdown(html_port, unsafe_allow_html=True)

                best_val = df_port_show.sort_values("pps", ascending=False).iloc[0]
                worst_val = df_port_show.sort_values("pps", ascending=False).iloc[-1]
                st.info(f"📊 La zona amb més valor és **{best_val['categoria']}** ({best_val['pps']} PPS) i representa el "
                        f"{best_val['volum_pct']}% dels tirs. La de menys valor és **{worst_val['categoria']}** "
                        f"({worst_val['pps']} PPS) amb el {worst_val['volum_pct']}% del volum.")

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

# ══════════════════════════════════════════════════
# TAB 7: ANÀLISI DE VÍDEO
# ══════════════════════════════════════════════════
with t8:
    st.markdown(sec("🎬 Anàlisi de vídeo — carrega els CSV del notebook"), unsafe_allow_html=True)
    st.caption("Carrega els fitxers generats pel notebook de Google Colab per veure les dades del vídeo.")

    col_u1, col_u2, col_u3 = st.columns(3)
    with col_u1:
        f_accions  = st.file_uploader("CSV d'accions", type="csv", key="up_accions",
                                       help="dades_partit_accions.csv")
    with col_u2:
        f_tracking = st.file_uploader("CSV de tracking", type="csv", key="up_tracking",
                                       help="dades_partit_tracking.csv")
    with col_u3:
        f_resum    = st.file_uploader("CSV de resum", type="csv", key="up_resum",
                                       help="dades_partit_resum.csv")

    if f_accions is None:
        st.info("Carrega almenys el CSV d'accions per començar.")
    else:
        df_vid_acc = pd.read_csv(f_accions)
        df_vid_tra = pd.read_csv(f_tracking) if f_tracking else pd.DataFrame()
        df_vid_res = pd.read_csv(f_resum)    if f_resum    else pd.DataFrame()

        st.success(f"✅ {len(df_vid_acc)} accions carregades")

        # ── Mètriques generals ──────────────────────────────────────────
        st.markdown(sec("Resum del partit"), unsafe_allow_html=True)
        equips_vid = [e for e in df_vid_acc["equip"].unique() if e and e != "?"]

        cols_m = st.columns(len(equips_vid) * 3 + 1)
        idx = 0
        cols_m[idx].markdown(card("Accions totals", len(df_vid_acc), "", "#374151"), unsafe_allow_html=True)
        idx += 1
        for eq in equips_vid:
            df_e = df_vid_acc[df_vid_acc["equip"] == eq]
            color_e = COLOR_A if idx <= 3 else COLOR_B
            cist  = int((df_e["tipus"] == "cistella").sum())
            falts = int((df_e["tipus"] == "falta").sum())
            tfall = int((df_e["tipus"] == "tir_fallat").sum())
            cols_m[idx].markdown(card(f"Cistelles {eq}", cist, "", color_e), unsafe_allow_html=True); idx+=1
            cols_m[idx].markdown(card(f"Faltes {eq}", falts, "", color_e), unsafe_allow_html=True); idx+=1
            cols_m[idx].markdown(card(f"Tirs fallats {eq}", tfall, "", color_e), unsafe_allow_html=True); idx+=1

        # ── Gràfic accions per equip ────────────────────────────────────
        st.markdown(sec("Accions per equip i tipus"), unsafe_allow_html=True)
        df_grp = df_vid_acc[df_vid_acc["equip"].isin(equips_vid)].groupby(["equip","tipus"]).size().reset_index(name="n")
        if not df_grp.empty:
            pal = {equips_vid[0]: COLOR_A, equips_vid[1]: COLOR_B} if len(equips_vid) >= 2 else {equips_vid[0]: COLOR_A}
            fig_a = px.bar(df_grp, x="tipus", y="n", color="equip", barmode="group",
                color_discrete_map=pal,
                labels={"tipus":"Tipus","n":"Accions","equip":"Equip"})
            fig_a.update_layout(xaxis_title="", paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                font=dict(color="#374151",family="Inter"),
                legend=dict(bgcolor="#ffffff",bordercolor="#e2e4e8",borderwidth=1,title=""),
                margin=dict(l=0,r=0,t=30,b=0),height=280)
            st.plotly_chart(fig_a, use_container_width=True)

        # ── Accions per quart ───────────────────────────────────────────
        st.markdown(sec("Accions per quart"), unsafe_allow_html=True)
        if "quart" in df_vid_acc.columns:
            df_q = df_vid_acc[df_vid_acc["equip"].isin(equips_vid)].groupby(["quart","equip","tipus"]).size().reset_index(name="n")
            cistelles_q = df_q[df_q["tipus"]=="cistella"]
            if not cistelles_q.empty:
                pal = {equips_vid[0]: COLOR_A, equips_vid[1]: COLOR_B} if len(equips_vid) >= 2 else {equips_vid[0]: COLOR_A}
                fig_q = px.bar(cistelles_q, x="quart", y="n", color="equip", barmode="group",
                    color_discrete_map=pal,
                    labels={"quart":"Quart","n":"Cistelles","equip":"Equip"})
                fig_q.update_layout(paper_bgcolor="#ffffff",plot_bgcolor="#ffffff",
                    font=dict(color="#374151",family="Inter"),
                    legend=dict(bgcolor="#ffffff",bordercolor="#e2e4e8",borderwidth=1,title=""),
                    margin=dict(l=0,r=0,t=30,b=0),height=260)
                st.plotly_chart(fig_q, use_container_width=True)

        # ── Evolució del marcador (des de les accions del vídeo) ────────
        st.markdown(sec("Evolució del marcador"), unsafe_allow_html=True)
        if "marcador" in df_vid_acc.columns:
            df_marc = df_vid_acc[df_vid_acc["marcador"].str.contains("-", na=False)].copy()
            if not df_marc.empty:
                try:
                    df_marc["scoreA"] = df_marc["marcador"].str.split("-").str[0].astype(int)
                    df_marc["scoreB"] = df_marc["marcador"].str.split("-").str[1].astype(int)
                    df_marc = df_marc.sort_values("temps_joc")
                    fig_m = go.Figure()
                    fig_m.add_trace(go.Scatter(x=df_marc["temps_joc"]/60, y=df_marc["scoreA"],
                        name=equips_vid[0] if equips_vid else "Local",
                        line=dict(color=COLOR_A,width=2.5),mode="lines"))
                    fig_m.add_trace(go.Scatter(x=df_marc["temps_joc"]/60, y=df_marc["scoreB"],
                        name=equips_vid[1] if len(equips_vid)>1 else "Visitant",
                        line=dict(color=COLOR_B,width=2.5),mode="lines"))
                    fig_m.update_layout(paper_bgcolor="#ffffff",plot_bgcolor="#ffffff",
                        font=dict(color="#374151",family="Inter"),
                        xaxis=dict(title="Minut de joc",showgrid=False,color="#9ca3af"),
                        yaxis=dict(title="Punts",showgrid=True,gridcolor="#f3f4f6",color="#9ca3af"),
                        legend=dict(bgcolor="#ffffff",bordercolor="#e2e4e8",borderwidth=1,title="",
                                    orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1),
                        margin=dict(l=0,r=0,t=40,b=0),height=280)
                    st.plotly_chart(fig_m, use_container_width=True)
                except:
                    st.info("No s'ha pogut generar l'evolució del marcador.")

        # ── Taula d'accions ─────────────────────────────────────────────
        st.markdown(sec("Totes les accions"), unsafe_allow_html=True)
        col_eq_f, col_tip_f = st.columns(2)
        with col_eq_f:
            eq_filter = st.selectbox("Equip", ["Tots"] + equips_vid, key="vid_eq_f")
        with col_tip_f:
            tip_filter = st.selectbox("Tipus", ["Tots","cistella","tir_fallat","falta","rebot","altre"], key="vid_tip_f")

        df_show = df_vid_acc.copy()
        if eq_filter != "Tots":
            df_show = df_show[df_show["equip"] == eq_filter]
        if tip_filter != "Tots":
            df_show = df_show[df_show["tipus"] == tip_filter]

        st.caption(f"{len(df_show)} accions")
        st.dataframe(df_show[["quart","jugadora","equip","accio","tipus","marcador"]].rename(
            columns={"quart":"Q","jugadora":"Jugadora","equip":"Equip",
                     "accio":"Acció","tipus":"Tipus","marcador":"Marc"}),
            use_container_width=True, hide_index=True, height=350)

        # ── Resum de tracking (si disponible) ───────────────────────────
        if not df_vid_res.empty:
            st.markdown(sec("Presència en pantalla per jugadora"), unsafe_allow_html=True)
            st.caption("Basada en el tracking del vídeo — quant temps apareix cada ID a càmera.")
            st.dataframe(df_vid_res.sort_values("minuts_visibles", ascending=False).rename(
                columns={"track_id":"ID","equip":"Equip","aparicions":"Frames",
                         "minuts_visibles":"Minuts visibles"}),
                use_container_width=True, hide_index=True)

        # ── Descàrrega combinada ────────────────────────────────────────
        st.markdown("---")
        csv_exp = df_vid_acc.to_csv(index=False).encode("utf-8")
        st.download_button("⬇ Descarregar accions CSV", csv_exp,
            "accions_video.csv", "text/csv")
