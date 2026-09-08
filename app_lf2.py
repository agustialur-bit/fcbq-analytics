# -*- coding: utf-8 -*-
"""Analítica — Manresa CBF A (L.F.-2), font de dades feb.es.

App bessona de app.py (equip FCBQ) que comparteix tot el motor de càlcul via
analitica_core.py, però amb BD pròpia (historic_lf2.db) i la seva pròpia ingesta
(l'API LiveStats de feb.es en lloc de msstats/basquetcatala.cat).
"""
import re
import os
import sqlite3
import requests
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

st.set_page_config(page_title="Analítica LF2", page_icon="🏀", layout="wide", initial_sidebar_state="expanded")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historic_lf2.db")
COLOR_A, COLOR_B = "#185FA5", "#993C1D"

import analitica_core as core
import core_four_factors as cff
from analitica_core import (
    MICKI_CSS, card, sec, chart_style,
    init_db, migrate_db, save_partit, save_stats_jugador, save_shots_zones,
    save_timeouts, save_tirs_fcbq, load_jugades_db, load_partits_db,
    load_stats_jugador_db, load_shots_zones_db, load_tirs_fcbq, partit_exists,
    get_teams, get_teams_ordered, score_evo, final_score, estat_marc, analyze_timeouts,
    get_intervals_jugadores_global, calc_pm_combinacions, calc_possessions,
    calc_eficiencies, calc_onoff, calc_onoff_ts, calc_usage_rate,
    calc_win_shares_temporada, calc_metriques_partit, classifica_arquetip_global,
    classifica_zona_tir, calc_onoff_agregat, calc_context_onoff, calc_lineup_impact,
    genera_excel_analisi, genera_excel_temporada,
    TC_INT_PAT, TL_INT_PAT, C_TEXT, C_BG, C_BG_SOFT, C_BORDER, C_ACCENT_DARK,
    C_WHITE, C_LABEL, C_SUCCESS, C_ERROR, C_ACCENT, C_CARD_BORDER,
)

core.set_db_path(DB_PATH)
init_db()
migrate_db()

st.markdown(MICKI_CSS, unsafe_allow_html=True)


# ══════════════════════════════════════════════════
# INGESTA feb.es
# ══════════════════════════════════════════════════
def extract_feb_match_id(text):
    m = re.search(r"/partido/(\d+)", text)
    if m:
        return m.group(1)
    if re.match(r"^\d+$", text.strip()):
        return text.strip()
    return None


def feb_get_token(match_id):
    r = requests.get(f"https://www.feb.es/competiciones/partido/{match_id}", timeout=15)
    r.raise_for_status()
    m = re.search(r'id="_ctl0_token" value="([^"]+)"', r.text)
    if not m:
        raise Exception("No s'ha trobat el token a la pàgina del partit (comprova l'ID)")
    return m.group(1)


def feb_fetch_keyfacts(match_id):
    token = feb_get_token(match_id)
    r = requests.get(
        f"https://intrafeb.feb.es/LiveStats.API/api/v1/KeyFacts/{match_id}",
        headers={"Authorization": "Bearer " + token}, timeout=20)
    r.raise_for_status()
    return r.json()


def feb_normalize_to_jugades(data):
    """Converteix el JSON de KeyFacts de feb.es al mateix esquema de columnes que
    fetch_and_parse() fa servir per a l'API de msstats: num, quart, temps, min_num,
    idEquip, dorsal, jugador, accio, marcador, punts, teamAction — traduint els
    `action`/`text` de feb.es als literals catalans que la resta del motor
    (calc_minuts_reals, get_intervals_jugadores_global...) busca amb str.contains.
    També retorna les coordenades de tir (x,y,fet) ja separades per jugadora, a punt
    per desar-les a `tirs_fcbq` sense necessitat del pas manual de consola JS.
    """
    header = data["HEADER"]
    teams_info = header["TEAM"]
    id_a, id_b = str(teams_info[0]["id"]), str(teams_info[1]["id"])
    nom_a, nom_b = teams_info[0]["name"], teams_info[1]["name"]

    player_lookup = {}
    scoreboard = data.get("SCOREBOARD") or {}
    for team_block in (scoreboard.get("TEAM") or []):
        for p in (team_block.get("PLAYER") or []):
            pid = str(p.get("id", ""))
            if pid:
                player_lookup[pid] = {"nom": p.get("name", ""), "dorsal": p.get("no", "")}

    lines = list(reversed(data["PLAYBYPLAY"]["LINES"]))  # ordre cronològic (inici -> final)

    rows = []
    tirs = []  # {jugador, idEquip, x, y, fet}
    num = 0
    score_a = score_b = 0
    ultim_equip_tir_fallat = None  # per classificar Rebot ofensiu/defensiu (feb.es no ho marca directament)
    for ln in lines:
        action = ln.get("action")
        text = ln.get("text") or ""
        quart = int(ln.get("quarter")) if ln.get("quarter") not in (None, "") else 1
        time_str = ln.get("time") or "00:00"
        try:
            mn, sc = time_str.split(":")
            min_num = float(mn) + float(sc) / 60
        except Exception:
            min_num = 0.0
        id_team = str(ln.get("idTeam") or "")
        id_player = str(ln.get("idPlayer") or "")
        info = player_lookup.get(id_player, {})
        jugador = info.get("nom", "")
        dorsal = info.get("dorsal", "")

        accio = None
        punts = 0

        if action == "shoot":
            anotat = "ANOTADO" in text
            if "DE 3" in text:
                accio = "Cistella de 3" if anotat else "Intent fallat de 3"
                punts = 3 if anotat else 0
            elif "DE 2" in text:
                accio = "Cistella de 2" if anotat else "Intent fallat de 2"
                punts = 2 if anotat else 0
            ultim_equip_tir_fallat = None if anotat else id_team
            pos = ln.get("Position") or ""
            if pos and "|" in pos and jugador:
                try:
                    x_raw, y_raw = pos.split("|")
                    tirs.append({"jugador": jugador, "idEquip": id_team,
                                 "x": float(x_raw), "y": float(y_raw), "fet": anotat})
                except Exception:
                    pass
        elif action == "fthrow":
            anotat = "ANOTADO" in text
            accio = "Cistella de 1" if anotat else "Intent fallat de 1"
            punts = 1 if anotat else 0
            ultim_equip_tir_fallat = None if anotat else id_team
        elif action == "subst":
            if "Entra" in text:
                accio = "Entra al camp"
            elif "Sale" in text:
                accio = "Surt del camp"
        elif action == "period":
            if text.startswith("Fin del Cuarto"):
                accio = "Final de període"
            else:
                continue  # "Comienzo del Cuarto" — redundant
        elif action == "timeout":
            accio = "Temps mort"
        elif action == "lose":
            accio = "Pèrdua"
        elif action == "rebound":
            # feb.es no marca ofensiu/defensiu a l'esdeveniment; s'infereix comparant
            # l'equip del rebot amb l'equip que acaba de fallar el tir immediatament abans
            # (validat contra els totals RO/RD del box score).
            if ultim_equip_tir_fallat is not None:
                accio = "Rebot ofensiu" if id_team == ultim_equip_tir_fallat else "Rebot defensiu"
                ultim_equip_tir_fallat = None
            else:
                accio = "Rebot"
        elif action in ("foul", "assist", "recovery", "blockshot"):
            accio = text

        if accio is None:
            continue

        if punts and id_team == id_a:
            score_a += punts
        elif punts and id_team == id_b:
            score_b += punts

        num += 1
        rows.append({
            "num": num, "quart": quart, "temps": time_str, "min_num": min_num,
            "idEquip": id_team, "dorsal": dorsal, "jugador": jugador, "accio": accio,
            "marcador": f"{score_a}-{score_b}", "punts": punts, "teamAction": False,
        })

    df = pd.DataFrame(rows)
    teams_meta = {"id_a": id_a, "id_b": id_b, "nom_a": nom_a, "nom_b": nom_b}
    return df, teams_meta, tirs


def carrega_partit_feb(match_id):
    data = feb_fetch_keyfacts(match_id)
    df, meta, tirs = feb_normalize_to_jugades(data)
    if df.empty:
        raise Exception("El partit no té jugades (play-by-play buit)")

    id_a, id_b = meta["id_a"], meta["id_b"]
    nom_a, nom_b = meta["nom_a"], meta["nom_b"]
    noms = {id_a: nom_a, id_b: nom_b}
    teams_tmp = [id_a, id_b]

    sdf = score_evo(df)
    fa, fb = final_score(sdf)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    save_partit(match_id, df, nom_a, nom_b, id_a, id_b, fa, fb)
    save_stats_jugador(match_id, ts, df, teams_tmp, noms)
    save_shots_zones(match_id, ts, df, noms)
    save_timeouts(match_id, ts, df, noms)

    tirs_a = [t for t in tirs if t["idEquip"] == id_a]
    tirs_b = [t for t in tirs if t["idEquip"] == id_b]
    save_tirs_fcbq(match_id, ts, nom_a, nom_b, tirs_a, tirs_b)

    return df, noms, fa, fb


# ══════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""<div style="display:flex;align-items:center;gap:10px;padding-bottom:14px;border-bottom:0.5px solid #e2e4e8;margin-bottom:14px">
        <div style="width:34px;height:34px;background:#E6F1FB;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:18px">🏀</div>
        <div><div style="font-size:13px;font-weight:600;color:#1a1c22">Analítica</div>
        <div style="font-size:11px;color:#9ca3af">Manresa CBF A · L.F.-2</div></div></div>""", unsafe_allow_html=True)

    st.markdown('<div style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#9ca3af;margin-bottom:6px">Partit</div>', unsafe_allow_html=True)
    url_input = st.text_input("", placeholder="URL o ID del partit (feb.es)", label_visibility="collapsed")
    carregar = st.button("⬇ Carregar partit", use_container_width=True)
    st.caption("Ex: https://www.feb.es/competiciones/partido/2477341")
    st.markdown("---")
    st.markdown('<div style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#9ca3af;margin-bottom:6px">Filtres play-by-play</div>', unsafe_allow_html=True)
    quart_sel = st.multiselect("Quart", options=[1,2,3,4], default=[1,2,3,4])
    accio_cerca = st.text_input("Acció", placeholder="Cistella, falta...")
    jugador_cerca = st.text_input("Jugadora", placeholder="Nom...")
    st.markdown("---")
    st.caption("Analítica LF2")

for k,v in [("df",None),("match_id",None),("team_names",{}),("score_a",0),("score_b",0)]:
    if k not in st.session_state: st.session_state[k]=v

if carregar and url_input:
    mid = extract_feb_match_id(url_input)
    if not mid:
        st.error("ID no vàlid. Enganxa la URL sencera del partit a feb.es.")
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
            st.session_state.score_a = int(row.iloc[0]["score_a"])
            st.session_state.score_b = int(row.iloc[0]["score_b"])
        st.success("Carregat des de l'històric ⚡")
    else:
        with st.spinner("Descarregant de feb.es..."):
            try:
                df, noms, fa, fb = carrega_partit_feb(mid)
                st.session_state.df = df
                st.session_state.match_id = mid
                st.session_state.team_names = noms
                st.session_state.score_a = fa
                st.session_state.score_b = fb
                st.success("Carregat i desat ✅")
            except Exception as e:
                st.error(f"Error: {e}")

if st.session_state.df is None:
    st.markdown("""<div style="text-align:center;padding:80px 0">
        <div style="font-size:64px">🏀</div>
        <h1 style="font-size:38px;font-weight:600;color:#1a1c22;margin:16px 0 8px">Analítica</h1>
        <p style="color:#6b7280;font-size:15px">Manresa CBF A · L.F.-2. Enganxa la URL d'un partit de feb.es al panell esquerre i prem Carregar.</p>
        <p style="color:#d1d5db;font-size:12px;margin-top:32px">Exemple: https://www.feb.es/competiciones/partido/2477341</p>
    </div>""", unsafe_allow_html=True)
    st.stop()

df_orig = st.session_state.df.copy()
match_id = st.session_state.match_id
teams = get_teams_ordered(df_orig)
team_names = st.session_state.team_names
nom_a = team_names.get(teams[0],"Equip A") if teams else "Equip A"
nom_b = team_names.get(teams[1],"Equip B") if len(teams)>1 else "Equip B"
color_map_eq = {nom_a:COLOR_A, nom_b:COLOR_B}
df_orig["equip_nom"] = df_orig["idEquip"].map(team_names).fillna("?")
score_df = score_evo(df_orig)
if st.session_state.score_a or st.session_state.score_b:
    fa, fb = st.session_state.score_a, st.session_state.score_b
else:
    fa, fb = final_score(score_df)


# ══════════════════════════════════════════════════
# TABS — Fase 1
# ══════════════════════════════════════════════════
t1, t_kp, t2, t3, t4, t_onoff, t5, t6, t_arq, t7, t9 = st.tabs([
    "🏀 Partit", "🌟 Key Performers", "👤 Jugadores", "⏱ Ritme", "⚡ Eficiència", "⚖️ On/Off",
    "🔄 Rotacions", "📈 Hist. Jugadores", "🎭 Arquetips", "🎯 Mapa de Tir", "📚 Històric"
])

with t1:
    def parcial_quart(tid, q):
        if not tid: return 0
        return int(df_orig[(df_orig["idEquip"]==tid) & (df_orig["quart"]==q)]["punts"].sum())

    qs = sorted(df_orig["quart"].unique())
    fa = sum(parcial_quart(teams[0] if teams else None, q) for q in qs)
    fb = sum(parcial_quart(teams[1] if len(teams)>1 else None, q) for q in qs)
    guanya_a, guanya_b = fa > fb, fb > fa

    ca,cm,cb = st.columns([5,1,5])
    with ca:
        badge_a = '<div style="background:#E6F1FB;color:#0C447C;font-size:10px;font-weight:600;padding:3px 8px;border-radius:20px;display:inline-block;margin-bottom:8px">VICTÒRIA</div>' if guanya_a else ""
        border_a = f"2px solid {COLOR_A}" if guanya_a else "0.5px solid #e2e4e8"
        parc_a = " · ".join([f"Q{q}: {parcial_quart(teams[0] if teams else None, q)}" for q in qs])
        st.markdown(
            f'<div style="background:#fff;border:{border_a};border-radius:16px;padding:24px 20px;text-align:center">'
            f'{badge_a}'
            f'<div style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:{COLOR_A};margin-bottom:8px">{nom_a}</div>'
            f'<div style="font-size:88px;font-weight:600;color:{COLOR_A};line-height:1">{fa}</div>'
            f'<div style="font-size:11px;color:#9ca3af;margin:6px 0">Local</div>'
            f'<div style="border-top:0.5px solid #f3f4f6;padding-top:8px;font-size:12px;color:{COLOR_A};opacity:.7">{parc_a}</div>'
            f'</div>', unsafe_allow_html=True)
    with cm:
        st.markdown(
            f'<div style="text-align:center;padding-top:52px;font-size:20px;color:#d1d5db">vs</div>'
            f'<div style="text-align:center;margin-top:6px;font-size:10px;color:#d1d5db">{str(match_id)[:8]}...</div>',
            unsafe_allow_html=True)
    with cb:
        badge_b = '<div style="background:#FAECE7;color:#712B13;font-size:10px;font-weight:600;padding:3px 8px;border-radius:20px;display:inline-block;margin-bottom:8px">VICTÒRIA</div>' if guanya_b else ""
        border_b = f"2px solid {COLOR_B}" if guanya_b else "0.5px solid #e2e4e8"
        parc_b = " · ".join([f"Q{q}: {parcial_quart(teams[1] if len(teams)>1 else None, q)}" for q in qs])
        st.markdown(
            f'<div style="background:#fff;border:{border_b};border-radius:16px;padding:24px 20px;text-align:center">'
            f'{badge_b}'
            f'<div style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:{COLOR_B};margin-bottom:8px">{nom_b}</div>'
            f'<div style="font-size:88px;font-weight:600;color:{COLOR_B};line-height:1">{fb}</div>'
            f'<div style="font-size:11px;color:#9ca3af;margin:6px 0">Visitant</div>'
            f'<div style="border-top:0.5px solid #f3f4f6;padding-top:8px;font-size:12px;color:{COLOR_B};opacity:.7">{parc_b}</div>'
            f'</div>', unsafe_allow_html=True)

    st.markdown(sec("Resum del partit"), unsafe_allow_html=True)
    faltes_a=int(df_orig[(df_orig["idEquip"]==teams[0])&df_orig["accio"].str.contains("falta",case=False,na=False)].shape[0]) if teams else 0
    faltes_b=int(df_orig[(df_orig["idEquip"]==teams[1])&df_orig["accio"].str.contains("falta",case=False,na=False)].shape[0]) if len(teams)>1 else 0
    c1,c2,c3,c4,c5,c6=st.columns(6)
    for col,lab,val,sub,col_ in zip([c1,c2,c3,c4,c5,c6],
        ["Jugades","Punts","Punts","Faltes","Faltes","Quarts"],
        [len(df_orig),fa,fb,faltes_a,faltes_b,df_orig["quart"].nunique()],
        ["total",nom_a,nom_b,nom_a,nom_b,"períodes"],
        ["#374151",COLOR_A,COLOR_B,COLOR_A,COLOR_B,"#374151"]):
        with col: st.markdown(card(lab,val,sub,col_),unsafe_allow_html=True)

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
        fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02,
                        xanchor="right", x=1, bgcolor="rgba(0,0,0,0)", font=dict(size=12)))
        st.plotly_chart(chart_style(fig,300),use_container_width=True)

    st.markdown(sec("Punts per quart"), unsafe_allow_html=True)
    pq=df_orig.groupby(["quart","equip_nom"])["punts"].sum().reset_index()
    if not pq.empty and pq["punts"].sum()>0:
        cmap = {}
        if teams: cmap[team_names.get(teams[0], nom_a)] = COLOR_A
        if len(teams)>1: cmap[team_names.get(teams[1], nom_b)] = COLOR_B
        fig2=px.bar(pq,x="quart",y="punts",color="equip_nom",barmode="group",
            color_discrete_map=cmap,labels={"quart":"Quart","punts":"Punts","equip_nom":"Equip"})
        st.plotly_chart(chart_style(fig2,240),use_container_width=True)

    st.markdown(sec("Play-by-Play"), unsafe_allow_html=True)
    df_f=df_orig.copy()
    if quart_sel: df_f=df_f[df_f["quart"].isin(quart_sel)]
    if accio_cerca: df_f=df_f[df_f["accio"].str.contains(accio_cerca,case=False,na=False)]
    if jugador_cerca: df_f=df_f[df_f["jugador"].str.contains(jugador_cerca,case=False,na=False)]
    st.caption(f"{len(df_f)} jugades")
    st.dataframe(df_f[["num","quart","temps","equip_nom","dorsal","jugador","accio","marcador","punts"]]
        .rename(columns={"num":"#","quart":"Q","temps":"Temps","equip_nom":"Equip","dorsal":"D",
                          "jugador":"Jugadora","accio":"Acció","marcador":"Marc","punts":"Pts"}),
        use_container_width=True, hide_index=True, height=400)
    csv_data=df_f[["num","quart","temps","idEquip","equip_nom","dorsal","jugador","accio","marcador","punts"]].to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Descarregar CSV",csv_data,f"pbp_{match_id}.csv","text/csv")


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
        if str(jug_kp).upper() in noms_equip_kp: continue
        if len(str(jug_kp).split()) > 4: continue
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
        ef_kp = calc_eficiencies(df_orig, teams, team_names, poss_mode="full")
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
    df_orig_imp = df_orig.copy()
    df_orig_imp["t_abs"] = df_orig_imp.apply(
        lambda r: (int(r["quart"])-1)*10+(10-float(r["min_num"]))
        if float(r.get("min_num",0))<=10 else float(r.get("min_num",0)), axis=1)

    col_j_imp = "jugador" if "jugador" in df_orig.columns else "jugadora"
    noms_equip = [nom_a.upper(), nom_b.upper(), nom_a, nom_b]
    for jug in df_orig[col_j_imp].unique():
        if not jug or str(jug) in ("","nan"): continue
        if str(jug).upper() in [n.upper() for n in noms_equip]: continue
        if len(str(jug).split()) > 4: continue
        dj=df_orig[df_orig[col_j_imp]==jug]
        eq_id=dj["idEquip"].iloc[0]; eq_nom=dj["equip_nom"].iloc[0]
        rival=[t for t in teams if t!=eq_id]
        rival_id_imp = rival[0] if rival else None

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

    st.markdown(sec("Usage% vs Eficiència"), unsafe_allow_html=True)
    st.caption("Eix X = % de possessions usades · Eix Y = Pts/min · Quadrant ideal: dalt a la dreta")

    if imp_rows:
        df_scatter = pd.DataFrame(imp_rows).copy()
        df_scatter["_usage_num"] = df_scatter["Usage%"].str.replace("%","").astype(float)
        df_scatter["_pts"] = df_scatter["Jugadora"].apply(
            lambda j: int(df_orig[df_orig[col_j_imp]==j]["punts"].sum()))
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

        fig_sc = go.Figure()
        for eq, color in [(nom_a, COLOR_A), (nom_b, COLOR_B)]:
            df_eq = df_scatter[df_scatter["Equip"]==eq]
            if df_eq.empty: continue
            fig_sc.add_trace(go.Scatter(
                x=df_eq["_usage_num"], y=df_eq["Pts/min"], mode="markers+text", name=eq,
                marker=dict(size=14, color=color, line=dict(width=1.5, color="white")),
                text=df_eq["Jugadora"].apply(lambda n: n.split()[1] if len(n.split())>1 else n),
                textposition="top center", textfont=dict(size=9),
                hovertemplate="<b>%{text}</b><br>Usage: %{x:.1f}%<br>Pts/min: %{y:.2f}<extra></extra>"))

        mitjana_usage = df_scatter["_usage_num"].mean()
        mitjana_pts   = df_scatter["Pts/min"].mean()
        fig_sc.add_vline(x=mitjana_usage, line_dash="dot", line_color="#e2e4e8",
            annotation_text=f"Mitjana {mitjana_usage:.0f}%", annotation_font_size=9, annotation_font_color="#9ca3af")
        fig_sc.add_hline(y=mitjana_pts, line_dash="dot", line_color="#e2e4e8",
            annotation_text=f"Mitjana {mitjana_pts:.2f}", annotation_font_size=9, annotation_font_color="#9ca3af")

        x_max = df_scatter["_usage_num"].max() * 1.1
        y_max = df_scatter["Pts/min"].max() * 1.1
        for txt, x, y, color in [
            ("⭐ Estrella", x_max*0.95, y_max*0.95, "#16a34a"),
            ("⚠️ Massa ús", x_max*0.95, y_max*0.05, "#dc2626"),
            ("💡 Infravalorada", x_max*0.05, y_max*0.95, "#185FA5"),
            ("🔄 Rol secundari", x_max*0.05, y_max*0.05, "#9ca3af"),
        ]:
            fig_sc.add_annotation(x=x, y=y, text=txt, showarrow=False,
                font=dict(size=9, color=color), xanchor="center", yanchor="middle", opacity=0.5)

        fig_sc.update_layout(
            xaxis=dict(title="Usage% (% possessions usades)", showgrid=True, gridcolor="#f3f4f6", color="#9ca3af"),
            yaxis=dict(title="Pts/min", showgrid=True, gridcolor="#f3f4f6", color="#9ca3af"),
            paper_bgcolor="#ffffff", plot_bgcolor="#ffffff", font=dict(color="#374151", family="Inter"),
            legend=dict(bgcolor="#ffffff", bordercolor="#e2e4e8", borderwidth=1, orientation="h",
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

    st.markdown(sec("⏸ Temps morts — qui anota després?"), unsafe_allow_html=True)
    st.caption("Primera cistella de l'equip que demana el temps mort, i quant triga a anotar-la.")
    to_data = analyze_timeouts(df_orig, team_names)
    if not to_data:
        st.info("No s'han detectat temps morts en aquest partit.")
    else:
        df_to = pd.DataFrame(to_data)
        c1,c2,c3,c4 = st.columns(4)
        total_to = len(df_to)
        anotats = df_to["va_anotar"].sum()
        efectivitat = round(anotats/total_to*100) if total_to>0 else 0
        seg_mitjana = df_to[df_to["va_anotar"]==1]["segons_resposta"].mean()
        with c1: st.markdown(card("Temps morts",total_to,"total","#374151"),unsafe_allow_html=True)
        with c2: st.markdown(card("Anoten després",int(anotats),"cistella","#16a34a"),unsafe_allow_html=True)
        with c3: st.markdown(card("Efectivitat",f"{efectivitat}%","","#185FA5"),unsafe_allow_html=True)
        with c4: st.markdown(card("Seg. fins cistella",f"{seg_mitjana:.0f}s" if not pd.isna(seg_mitjana) else "—","mitjana","#d97706"),unsafe_allow_html=True)
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

    st.markdown(sec("📊 Rendiment per quart"), unsafe_allow_html=True)
    st.caption("Off Rtg = pts/100 poss · TS% = pts/(2×(TC_int+0.44×TL_int))×100 · Ritme = poss/min (quarts de 10 min)")
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
            quarts_data.append({"quart": int(q), "equip": nom_eq, "color": color_eq,
                "poss": round(poss_q, 1), "pts": pts_q, "ts": ts_q, "off_rtg": off_rtg_q, "ritme": ritme_q})
    if not quarts_data:
        st.info("No hi ha dades de quarts per aquest partit.")
    else:
        df_qd = pd.DataFrame(quarts_data)
        quarts_uniq = sorted(df_qd["quart"].unique())
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
            if ra["pts"] > rb["pts"]: bg_a, bg_b = "#D5F5E3", bg_row
            elif rb["pts"] > ra["pts"]: bg_a, bg_b = bg_row, "#D5F5E3"
            else: bg_a = bg_b = "#FFF3CD"
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

        fig_qp = go.Figure()
        for nom_eq, color_eq in [(nom_a, COLOR_A), (nom_b, COLOR_B)]:
            d_eq = df_qd[df_qd["equip"] == nom_eq]
            fig_qp.add_trace(go.Bar(x=[f"Q{q}" for q in d_eq["quart"]], y=d_eq["poss"],
                name=nom_eq, marker_color=color_eq, text=d_eq["poss"], textposition="outside"))
        fig_qp.update_layout(barmode="group")
        st.plotly_chart(chart_style(fig_qp, 260, "Possessions per quart"), use_container_width=True)

        fig_qo = go.Figure()
        for nom_eq, color_eq in [(nom_a, COLOR_A), (nom_b, COLOR_B)]:
            d_eq = df_qd[df_qd["equip"] == nom_eq]
            fig_qo.add_trace(go.Bar(x=[f"Q{q}" for q in d_eq["quart"]], y=d_eq["off_rtg"],
                name=nom_eq, marker_color=color_eq, text=d_eq["off_rtg"], textposition="outside"))
        fig_qo.add_hline(y=100, line_dash="dot", line_color=C_LABEL, annotation_text="Ref. 100", annotation_font_size=9)
        fig_qo.update_layout(barmode="group")
        st.plotly_chart(chart_style(fig_qo, 260, "Off Rating per quart"), use_container_width=True)

        fig_qt = go.Figure()
        for nom_eq, color_eq in [(nom_a, COLOR_A), (nom_b, COLOR_B)]:
            d_eq = df_qd[df_qd["equip"] == nom_eq]
            fig_qt.add_trace(go.Bar(x=[f"Q{q}" for q in d_eq["quart"]], y=d_eq["ts"],
                name=nom_eq, marker_color=color_eq, text=d_eq["ts"], textposition="outside"))
        fig_qt.add_hline(y=50, line_dash="dot", line_color=C_LABEL, annotation_text="Ref. 50%", annotation_font_size=9)
        fig_qt.update_layout(barmode="group")
        st.plotly_chart(chart_style(fig_qt, 260, "True Shooting % per quart"), use_container_width=True)

    st.markdown(sec("📈 Liderant vs. Remolcant"), unsafe_allow_html=True)
    st.caption("Eficiència ofensiva segons l'estat del marcador ABANS de cada acció. Mínim 4 possessions per bucket per ser fiable.")
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
            resultats_lvr[bkt] = {"poss": round(poss_b_lvr, 1), "pts": pts_b_lvr,
                "off_rtg": round(pts_b_lvr / poss_b_lvr * 100, 1), "ppp": round(pts_b_lvr / poss_b_lvr, 2),
                "ts": round(pts_b_lvr / ts_denom_b * 100, 1) if ts_denom_b > 0 else 0}
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
        st.dataframe(pd.DataFrame(shift_rows),use_container_width=True,hide_index=True)
    else:
        st.info(f"No s'han detectat runs de {THRESHOLD}+ punts.")
    st.markdown(sec("🔥 Clutch"), unsafe_allow_html=True)
    st.caption("Últims 5 minuts amb marge de 5 punts o menys.")

    clutch = cff.calc_clutch(df_orig, teams, team_names, poss_mode="full")
    if clutch:
        st.markdown(card("Finestra clutch", f"{clutch['finestra_min']:.1f} min",
                          f"{clutch['n_trams']} tram(s)", "#d97706"), unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        for col, tid_c, color_c in [(c1, teams[0], COLOR_A), (c2, teams[1] if len(teams) > 1 else None, COLOR_B)]:
            if tid_c is None:
                continue
            with col:
                met_c = clutch["equips"].get(tid_c, {})
                st.markdown(card(met_c.get("Equip", "?"), met_c.get("Pts", 0),
                                  f"TS% {met_c.get('TS%', 0)} · Off Rtg {met_c.get('Off Rtg', 0)}",
                                  color_c), unsafe_allow_html=True)

        st.markdown("**Jugadores en el tram clutch**")
        df_clutch_jug = pd.DataFrame(clutch["jugadores"])
        if not df_clutch_jug.empty:
            st.dataframe(
                df_clutch_jug[["jugadora", "equip_nom", "minuts", "punts", "TS%", "+/-"]]
                    .rename(columns={"jugadora": "Jugadora", "equip_nom": "Equip", "minuts": "Min"}),
                use_container_width=True, hide_index=True)
    else:
        st.info("Aquest partit no ha tingut cap tram amb marge ≤5 punts en els últims 5 minuts.")

with t4:
    st.markdown(sec("📊 Comparació d'equips"), unsafe_allow_html=True)
    st.caption("Off/Def/Net Rtg, TS%, eFG% i possessions totals dels dos equips d'aquest partit, costat a costat.")
    tid_a_cmp = teams[0] if teams else None
    tid_b_cmp = teams[1] if len(teams) > 1 else None
    if tid_a_cmp and tid_b_cmp:
        ef_cmp = calc_eficiencies(df_orig, teams, team_names, poss_mode="full")
        df_eq_a_cmp = df_orig[df_orig["idEquip"] == tid_a_cmp]
        df_eq_b_cmp = df_orig[df_orig["idEquip"] == tid_b_cmp]
        met_a_cmp = calc_metriques_partit(df_eq_a_cmp, match_id, nom_a, nom_b, poss_mode="full")
        met_b_cmp = calc_metriques_partit(df_eq_b_cmp, match_id, nom_b, nom_a, poss_mode="full")

        net_a_cmp, net_b_cmp = ef_cmp[tid_a_cmp]["net_rtg"], ef_cmp[tid_b_cmp]["net_rtg"]

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
        fig_cmp.add_trace(go.Bar(y=labels_cmp, x=vals_a_cmp, orientation="h", name=nom_a,
            marker_color=COLOR_A, text=[f"{v:g}" for v in vals_a_cmp], textposition="outside"))
        fig_cmp.add_trace(go.Bar(y=labels_cmp, x=[-v for v in vals_b_cmp], orientation="h", name=nom_b,
            marker_color=COLOR_B, text=[f"{v:g}" for v in vals_b_cmp], textposition="outside"))
        fig_cmp.update_layout(barmode="overlay",
            xaxis=dict(showticklabels=False, zeroline=True, zerolinecolor=C_BORDER, zerolinewidth=1.5),
            yaxis=dict(title=""),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(chart_style(fig_cmp, 340, "Comparació d'equips"), use_container_width=True)
        st.caption(f"Net Rtg (Off−Def, calculat oficialment amb el ritme propi de cada equip): "
                   f"{nom_a} {'+' if net_a_cmp>=0 else ''}{net_a_cmp} · {nom_b} {'+' if net_b_cmp>=0 else ''}{net_b_cmp}")
    else:
        st.info("Calen dos equips per a la comparació.")

    st.markdown(sec("ROT — Índex de gestió de rotacions"), unsafe_allow_html=True)
    st.caption("ROT = 5 · (ρ + 1)  on ρ = correlació de Pearson entre minuts jugats i +/- per minut de cada jugadora. Escala 0-10.")
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
            min_rot = round(sum(tf-ti for ti,tf in ivs_rot), 1)
            if min_rot < 0.5: continue
            pf_rot=pc_rot=0
            for ti_r,tf_r in ivs_rot:
                df_i_rot=df_t_rot[(df_t_rot["t_abs"]>=ti_r)&(df_t_rot["t_abs"]<=tf_r)]
                pf_rot+=int(df_i_rot[df_i_rot["idEquip"]==eq_rot]["punts"].sum())
                pc_rot+=int(df_i_rot[df_i_rot["idEquip"]==rival_id_rot]["punts"].sum())
            pm_rot = pf_rot - pc_rot
            pm_min_rot = pm_rot / min_rot if min_rot > 0 else 0
            rot_data.append({"equip": eq_rot, "jugadora": jug_rot, "minuts": min_rot, "pm_min": pm_min_rot})
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
            fig_rot = go.Figure()
            fig_rot.add_trace(go.Scatter(x=df_rot_eq["minuts"], y=df_rot_eq["pm_min"], mode="markers+text",
                marker=dict(size=10, color=color_rot, line=dict(width=1, color="white")),
                text=df_rot_eq["jugadora"].apply(lambda n: n.split()[1] if len(n.split())>1 else n),
                textposition="top center", textfont=dict(size=8),
                hovertemplate="<b>%{text}</b><br>Minuts: %{x:.1f}<br>+/- per min: %{y:+.3f}<extra></extra>"))
            import numpy as np
            m_rot, b_rot = np.polyfit(df_rot_eq["minuts"], df_rot_eq["pm_min"], 1)
            x_lr = [df_rot_eq["minuts"].min(), df_rot_eq["minuts"].max()]
            y_lr = [m_rot*x+b_rot for x in x_lr]
            fig_rot.add_trace(go.Scatter(x=x_lr, y=y_lr, mode="lines",
                line=dict(color="#d97706", width=2, dash="dot"),
                name=f"Tendència (ρ={rho_rot:+.3f})", showlegend=True))
            fig_rot.add_hline(y=0, line_dash="solid", line_color="#e2e4e8")
            fig_rot.update_xaxes(title="Minuts jugats")
            fig_rot.update_yaxes(title="+/- per minut")
            st.plotly_chart(chart_style(fig_rot, 260, f"{eq_nom_rot} — ROT {rot_val}/10 (ρ={rho_rot:+.3f})"), use_container_width=True)

    st.markdown(sec("Exporta a Excel"), unsafe_allow_html=True)
    st.caption("Excel amb totes les mètriques avançades de tots els partits de la base de dades.")
    if st.button("⬇ Descarregar Excel d'anàlisi complet", key="btn_excel_analisi_lf2"):
        excel_data = genera_excel_analisi()
        if excel_data:
            st.download_button(
                label="📥 Clic per descarregar", data=excel_data,
                file_name=f"analitica_lf2_analisi_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_excel_analisi_lf2")
        else:
            st.info("No hi ha partits a la base de dades.")
    st.markdown(sec("📐 Cuatro Factores (Dean Oliver)"), unsafe_allow_html=True)
    st.caption("eFG% = tir efectiu · TOV% = pèrdues per possessió · OR%/DR% = rebot ofensiu/defensiu · FT/TCI = tirs lliures per tir de camp")

    ff = cff.calc_four_factors(df_orig, teams, team_names, poss_mode="full")
    if ff and len(teams) > 1:
        tid_a_ff, tid_b_ff = teams[0], teams[1]
        fa_ff, fb_ff = ff[tid_a_ff], ff[tid_b_ff]

        factors = [
            ("eFG%", fa_ff["eFG%"], fb_ff["eFG%"]),
            ("TOV%", fa_ff["TOV%"], fb_ff["TOV%"]),
            ("OR%", fa_ff["OR%"], fb_ff["OR%"]),
            ("FT/TCI", fa_ff["FT_TCI"], fb_ff["FT_TCI"]),
        ]
        labels_ff = [f[0] for f in factors]
        vals_a_ff = [f[1] for f in factors]
        vals_b_ff = [f[2] for f in factors]

        fig_ff = go.Figure()
        fig_ff.add_trace(go.Bar(y=labels_ff, x=vals_a_ff, orientation="h", name=nom_a,
            marker_color=COLOR_A, text=[f"{v:g}" for v in vals_a_ff], textposition="outside"))
        fig_ff.add_trace(go.Bar(y=labels_ff, x=[-v for v in vals_b_ff], orientation="h", name=nom_b,
            marker_color=COLOR_B, text=[f"{v:g}" for v in vals_b_ff], textposition="outside"))
        fig_ff.update_layout(barmode="overlay",
            xaxis=dict(showticklabels=False, zeroline=True, zerolinecolor=C_BORDER, zerolinewidth=1.5),
            yaxis=dict(title=""),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        st.plotly_chart(chart_style(fig_ff, 260, "Quatre Factors"), use_container_width=True)

        st.markdown("**Lo que produjeron**")
        c1, c2, c3, c4 = st.columns(4)
        with c1: st.markdown(card("OER " + nom_a, fa_ff["OER"], "", COLOR_A), unsafe_allow_html=True)
        with c2: st.markdown(card("DER " + nom_a, fa_ff["DER"], "", "#dc2626"), unsafe_allow_html=True)
        with c3: st.markdown(card("OER " + nom_b, fb_ff["OER"], "", COLOR_B), unsafe_allow_html=True)
        with c4: st.markdown(card("DER " + nom_b, fb_ff["DER"], "", "#dc2626"), unsafe_allow_html=True)
    else:
        st.info("Calen dos equips per calcular els Quatre Factors.")



    st.markdown(sec("🧭 Cuándo la tuvieron, y cuánto valió"), unsafe_allow_html=True)
    st.caption(
        "Punts per possessió (PPP) segons com va començar: tras canasta, tras robo, "
        "tras rebote defensivo, o tras pérdida en balón parado."
    )

    pts_start = cff.calc_pts_by_start(df_orig, teams, team_names)
    etiquetes = {
        "after_make": "Tras canasta",
        "off_steal": "Tras robo",
        "off_dreb": "Tras rebote defensivo",
        "off_deadball_tov": "Tras pérdida en balón parado",
    }
    if pts_start and len(teams) > 1:
        tid_a_ps, tid_b_ps = teams[0], teams[1]
        for clau, etiqueta in etiquetes.items():
            d_a = pts_start.get(tid_a_ps, {}).get(clau, {})
            d_b = pts_start.get(tid_b_ps, {}).get(clau, {})
            c1, c2, c3 = st.columns([1, 2, 1])
            with c1:
                st.markdown(card(nom_a, d_a.get("ppp") if d_a.get("ppp") is not None else "—",
                                  f"{d_a.get('poss',0)} poss.", COLOR_A), unsafe_allow_html=True)
            with c2:
                st.markdown(f"<div style='text-align:center;padding-top:22px;color:#6b7280;"
                            f"font-size:13px'>{etiqueta}</div>", unsafe_allow_html=True)
            with c3:
                st.markdown(card(nom_b, d_b.get("ppp") if d_b.get("ppp") is not None else "—",
                                  f"{d_b.get('poss',0)} poss.", COLOR_B), unsafe_allow_html=True)
    else:
        st.info("Calen dos equips per calcular aquesta desagregació.")




with t_onoff:
    st.markdown(sec("⚡ Eficiència i On/Off Rating per jugadora"), unsafe_allow_html=True)
    st.caption("On/Off Net Rating = diferència de Net Rating (pts/100 poss) quan la jugadora és a pista vs quan no hi és. "
               "⚠️ = poques possessions Off, valor poc fiable.")
    st.markdown("**Eficiències d'equip**")
    ef2 = calc_eficiencies(df_orig, teams, team_names, poss_mode="full")
    col_ea2, col_eb2 = st.columns(2)
    for col_e2, tid2 in [(col_ea2, teams[0] if teams else None), (col_eb2, teams[1] if len(teams)>1 else None)]:
        with col_e2:
            if tid2 and tid2 in ef2:
                e2 = ef2[tid2]
                tcol2 = COLOR_A if tid2 == teams[0] else COLOR_B
                c1,c2,c3,c4 = st.columns(4)
                with c1: st.markdown(card("Possessions", e2["poss_of"], "", tcol2), unsafe_allow_html=True)
                with c2: st.markdown(card("Off Rating", e2["off_rtg"], "pts/100 poss", tcol2), unsafe_allow_html=True)
                with c3: st.markdown(card("Def Rating", e2["def_rtg"], "pts/100 poss", "#dc2626"), unsafe_allow_html=True)
                nc2 = "#16a34a" if e2["net_rtg"] >= 0 else "#dc2626"
                with c4: st.markdown(card("Net Rating", f"{'+' if e2['net_rtg']>=0 else ''}{e2['net_rtg']}", e2["nom"], nc2), unsafe_allow_html=True)

    st.markdown("**On/Off Rating per jugadora**")
    eq_oo2 = st.selectbox("Equip", [nom_a, nom_b], key="eq_oo_lf2")
    tid_oo2 = teams[0] if eq_oo2 == nom_a else (teams[1] if len(teams)>1 else None)
    if tid_oo2:
        jugs_oo2 = sorted([j for j in df_orig[df_orig["idEquip"]==tid_oo2]["jugador"].unique().tolist() if j])
        oo_rows2, ts_rows2 = [], []
        for jug2 in jugs_oo2:
            oo2 = calc_onoff(df_orig, jug2, tid_oo2, teams, poss_mode="full")
            if oo2 and oo2.get("diff") is not None:
                fiable = oo2.get("off_poss", 0) >= 4
                oo_rows2.append({"Jugadora": jug2, "_diff": oo2["diff"], "_fiable": fiable,
                    "On Poss": oo2["on_poss"], "On Net Rtg": oo2["on_net_rtg"],
                    "Off Poss": oo2["off_poss"], "Off Net Rtg": oo2["off_net_rtg"]})
            ts2 = calc_onoff_ts(df_orig, jug2, tid_oo2, teams)
            if ts2 and ts2["diff_ts"] is not None:
                ts_rows2.append({"Jugadora": jug2, "_diff": ts2["diff_ts"], "_fiable": ts2["tc_off"]>=4,
                    "TS% ON": ts2["ts_on"], "TS% OFF": ts2["ts_off"]})

        if oo_rows2:
            df_oo2 = pd.DataFrame(oo_rows2).sort_values("_diff", ascending=False)
            colors_bar2 = ["#d97706" if not r["_fiable"] else ("#16a34a" if r["_diff"]>=0 else "#dc2626") for _,r in df_oo2.iterrows()]
            fig_oo2 = go.Figure(go.Bar(x=df_oo2["Jugadora"], y=df_oo2["_diff"], marker_color=colors_bar2,
                text=[f"{'+'if d>=0 else ''}{d}" for d in df_oo2["_diff"]], textposition="outside"))
            fig_oo2.add_hline(y=0, line_color="#e2e4e8")
            fig_oo2.update_layout(yaxis_title="On - Off Net Rating", paper_bgcolor="#fff", plot_bgcolor="#fff",
                font=dict(color="#374151", family="Inter"), margin=dict(l=0,r=0,t=30,b=0), height=280)
            st.plotly_chart(fig_oo2, use_container_width=True)
            with st.expander("Veure detall"):
                st.dataframe(df_oo2.drop(columns=["_diff","_fiable"]), use_container_width=True, hide_index=True)
        else:
            st.info("No hi ha prou dades per calcular l'On/Off Rating d'aquest partit.")

        st.markdown(sec("🎯 TS% de l'equip — On/Off per jugadora"), unsafe_allow_html=True)
        if ts_rows2:
            df_ts2 = pd.DataFrame(ts_rows2).sort_values("_diff", ascending=False)
            colors_ts2 = ["#d97706" if not r["_fiable"] else ("#16a34a" if r["_diff"]>=0 else "#dc2626") for _,r in df_ts2.iterrows()]
            fig_ts2 = go.Figure(go.Bar(x=df_ts2["Jugadora"], y=df_ts2["_diff"], marker_color=colors_ts2,
                text=[f"{'+'if d>=0 else ''}{d}" for d in df_ts2["_diff"]], textposition="outside"))
            fig_ts2.add_hline(y=0, line_color="#e2e4e8")
            fig_ts2.update_layout(yaxis_title="TS% ON - TS% OFF", paper_bgcolor="#fff", plot_bgcolor="#fff",
                font=dict(color="#374151", family="Inter"), margin=dict(l=0,r=0,t=30,b=0), height=280)
            st.plotly_chart(fig_ts2, use_container_width=True)
        else:
            st.info("No hi ha prou dades per calcular el TS% On/Off.")

        st.markdown(sec("🧩 Lineup Impact Tool"), unsafe_allow_html=True)
        st.caption(
            "Compara el rendiment de l'equip amb un lineup concret a pista ('Amb aquest lineup') "
            "enfront de la resta del partit. 'A pista' = han de ser-hi TOTES; 'Fora de pista' = cap "
            "d'elles hi pot ser. Mínim 4 possessions per ser fiable."
        )
        col_li1, col_li2 = st.columns(2)
        with col_li1:
            jugs_on_li = st.multiselect("A pista (ON) — màx. 5", jugs_oo2, key="li_on", max_selections=5)
        with col_li2:
            jugs_off_li = st.multiselect("Fora de pista (OFF)",
                [j for j in jugs_oo2 if j not in jugs_on_li], key="li_off")

        n_quarts_li = int(df_orig["quart"].max()) if not df_orig.empty else 4
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
                res_li = calc_lineup_impact(
                    df_orig, jugs_on_li, jugs_off_li, tid_oo2, teams,
                    quart_ini_li, quart_fi_li, poss_mode="full")
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
            res_onoff_agr = calc_onoff_agregat(df_p_agr, min_poss_on_ui, min_poss_off_ui, poss_mode="full")
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

                st.markdown(sec("🧭 Context de l'On/Off — mèrit individual o companya habitual?"),
                    unsafe_allow_html=True)
                st.caption(
                    "Un On/Off alt pot ser mèrit real de la jugadora, o pot venir 'prestat' per jugar "
                    "gairebé sempre amb la mateixa companya forta. Aquí es divideixen els seus minuts ON "
                    "entre 'amb la seva companya més freqüent' i 'sense ella': si el Net Rating es manté "
                    "alt als dos costats, és mèrit individual; si només es manté a un, és efecte de context. "
                    "⚠️ No inclou la força del rival — és un indicador basat només en concentració de "
                    "companyes i consistència del Net Rating."
                )
                min_poss_seg_ui = st.number_input(
                    "Mínim possessions per segment (amb/sense bloc) per considerar-lo fiable",
                    min_value=0, value=40, step=5, key="min_poss_seg_ctx")

                res_context = calc_context_onoff(df_p_agr, min_poss_seg=min_poss_seg_ui, poss_mode="full")
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
    intervals_jug = get_intervals_jugadores_global(df_orig)
    score_df_rot = score_df.copy() if not score_df.empty else pd.DataFrame()

    # ── 1. Gràfic de quintets (Gantt de rotacions) ────────────────────────
    st.markdown(sec("Gràfic de rotacions — qui juga cada minut"), unsafe_allow_html=True)
    st.caption("Cada barra indica un tram de joc d'una jugadora. La línia vermella/blava és el ±parcial de l'equip.")

    eq_rot = st.selectbox("Equip", [nom_a, nom_b], key="rot_eq")
    tid_rot = teams[0] if eq_rot == nom_a else (teams[1] if len(teams)>1 else None)
    color_rot = COLOR_A if eq_rot == nom_a else COLOR_B
    rival_rot = teams[1] if eq_rot == nom_a else (teams[0] if teams else None)

    MINS_TOTAL = max(df_orig["quart"].max() * 10 if not df_orig.empty else 40, 40)

    if tid_rot and intervals_jug:
        jugs_rot = {j: ivs for j,ivs in intervals_jug.items()
                    if any(ei == tid_rot for _,_,ei in ivs)}

        if not jugs_rot:
            st.info("No s'han detectat events d'entrada/sortida per a aquest equip.")
        else:
            jugs_sorted = sorted(jugs_rot.items(), key=lambda x: min(i[0] for i in x[1]))
            n_jugs = len(jugs_sorted)

            fig_rot = go.Figure()
            for yi, (jug, ivs) in enumerate(jugs_sorted):
                for (t_ini, t_fi, ei) in ivs:
                    if ei != tid_rot: continue
                    fig_rot.add_trace(go.Bar(
                        x=[t_fi - t_ini], y=[jug], base=[t_ini], orientation='h',
                        marker_color=color_rot, marker_opacity=0.75,
                        marker_line=dict(width=0.5, color='white'),
                        name=jug, showlegend=False,
                        hovertemplate=f"{jug}<br>Minut {t_ini:.1f}–{t_fi:.1f}<br>Durada: {t_fi-t_ini:.1f} min<extra></extra>"
                    ))

            if not score_df_rot.empty:
                score_df_rot["t_min"] = score_df_rot.apply(
                    lambda r: (int(r["quart"])-1)*10 + (10 - float(r.get("min_num",0)))
                    if float(r.get("min_num",0)) <= 10 else float(r.get("min_num",0)), axis=1)
                parcial_eq  = score_df_rot["scoreA"] if tid_rot == teams[0] else score_df_rot["scoreB"]
                parcial_riv = score_df_rot["scoreB"] if tid_rot == teams[0] else score_df_rot["scoreA"]
                diff_parcial = parcial_eq - parcial_riv
                fig_rot.add_trace(go.Scatter(
                    x=score_df_rot["t_min"], y=diff_parcial, mode="lines", name="Parcial equip",
                    line=dict(color="#374151", width=1.5, dash="dot"), yaxis="y2",
                    hovertemplate="Minut %{x:.1f}<br>Parcial: %{y:+d}<extra></extra>"
                ))

            for q in range(1, 5):
                fig_rot.add_vline(x=q*10, line_dash="dot", line_color="#e2e4e8",
                    annotation_text=f"Fi Q{q}", annotation_font_size=9, annotation_font_color="#9ca3af")

            fig_rot.update_layout(
                barmode="overlay", height=max(280, n_jugs * 36 + 80),
                paper_bgcolor="#ffffff", plot_bgcolor="#f9fafb",
                font=dict(color="#374151", family="Inter"),
                xaxis=dict(title="Minut de joc", range=[0, MINS_TOTAL],
                           showgrid=True, gridcolor="#f3f4f6", color="#9ca3af"),
                yaxis=dict(showgrid=False, color="#374151"),
                yaxis2=dict(overlaying="y", side="right", title="Parcial ±",
                            showgrid=False, zeroline=True, zerolinecolor="#e2e4e8", color="#9ca3af"),
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
            rival_rot_id = teams[1] if tid_rot == teams[0] else (teams[0] if teams else None)
            parcial_favor = 0; parcial_contra = 0
            df_orig_t = df_orig.copy()
            df_orig_t["t_abs"] = df_orig_t.apply(
                lambda r: (int(r["quart"])-1)*10 + (10 - float(r["min_num"]))
                if float(r.get("min_num",0)) <= 10 else float(r.get("min_num",0)), axis=1)
            for t_ini, t_fi in ivs_eq:
                df_interval = df_orig_t[(df_orig_t["t_abs"] >= t_ini) & (df_orig_t["t_abs"] <= t_fi)]
                parcial_favor  += int(df_interval[df_interval["idEquip"]==tid_rot]["punts"].sum())
                if rival_rot_id:
                    parcial_contra += int(df_interval[df_interval["idEquip"]==rival_rot_id]["punts"].sum())
            pm = parcial_favor - parcial_contra
            pm_per_min = round(pm / total_min, 2) if total_min > 0 else 0
            pm_rows.append({"Jugadora": jug, "Minuts": round(total_min, 1), "+/-": pm, "+/- per min": pm_per_min})

        if pm_rows:
            df_pm = pd.DataFrame(pm_rows).sort_values("+/- per min", ascending=False)
            fig_pm = go.Figure()
            colors_pm = ["#16a34a" if v >= 0 else "#dc2626" for v in df_pm["+/- per min"]]
            fig_pm.add_trace(go.Scatter(
                x=df_pm["Minuts"], y=df_pm["+/- per min"], mode="markers+text",
                marker=dict(size=12, color=colors_pm, line=dict(width=1.5, color="white")),
                text=df_pm["Jugadora"].apply(lambda n: n.split()[1] if len(n.split())>1 else n),
                textposition="top center", textfont=dict(size=9),
                hovertemplate="%{text}<br>Minuts: %{x:.1f}<br>+/- per min: %{y:+.2f}<extra></extra>"
            ))
            fig_pm.add_hline(y=0, line_dash="solid", line_color="#e2e4e8")
            fig_pm.update_layout(
                xaxis=dict(title="Minuts jugats", showgrid=True, gridcolor="#f3f4f6", color="#9ca3af"),
                yaxis=dict(title="+/- per minut", showgrid=True, gridcolor="#f3f4f6", color="#9ca3af",
                           zeroline=True, zerolinecolor="#e2e4e8"),
                paper_bgcolor="#ffffff", plot_bgcolor="#ffffff", font=dict(color="#374151", family="Inter"),
                margin=dict(l=0,r=0,t=20,b=0), height=320)
            st.plotly_chart(fig_pm, use_container_width=True)
            st.dataframe(df_pm, use_container_width=True, hide_index=True)

    # ── 3. +/- per tram de minuts jugats ─────────────────────────────────
    st.markdown(sec("+/- per tram de joc"), unsafe_allow_html=True)
    st.caption("Per cada tram que una jugadora juga seguit, veus el parcial de l'equip minut a minut.")

    if tid_rot and not score_df_rot.empty and intervals_jug:
        jugs_tram = [j for j,ivs in intervals_jug.items() if any(ei==tid_rot for _,_,ei in ivs)]
        jug_tram = st.selectbox("Jugadora", sorted(jugs_tram), key="jug_tram")

        if jug_tram and jug_tram in intervals_jug:
            ivs_jug = [(ti,tf) for ti,tf,ei in intervals_jug[jug_tram] if ei==tid_rot]
            fig_tram = go.Figure()
            colors_tram = [color_rot, "#16a34a", "#d97706", "#6366f1", "#ec4899"]

            for bi, (t_ini, t_fi) in enumerate(ivs_jug):
                if "t_min" in score_df_rot.columns:
                    df_tr = score_df_rot[(score_df_rot["t_min"] >= t_ini) & (score_df_rot["t_min"] <= t_fi)].copy()
                    x_vals = df_tr["t_min"] - t_ini
                else:
                    n_ini = int(t_ini / MINS_TOTAL * len(score_df_rot))
                    n_fi  = int(t_fi  / MINS_TOTAL * len(score_df_rot))
                    df_tr = score_df_rot.iloc[n_ini:n_fi].copy()
                    x_vals = pd.Series(range(len(df_tr))) * (t_fi-t_ini) / max(len(df_tr),1)
                if df_tr.empty: continue

                if tid_rot == teams[0]:
                    parcial_tr = df_tr["scoreA"] - df_tr["scoreA"].iloc[0] - (df_tr["scoreB"] - df_tr["scoreB"].iloc[0])
                else:
                    parcial_tr = df_tr["scoreB"] - df_tr["scoreB"].iloc[0] - (df_tr["scoreA"] - df_tr["scoreA"].iloc[0])

                color_bi = colors_tram[bi % len(colors_tram)]
                fig_tram.add_trace(go.Scatter(
                    x=x_vals, y=parcial_tr, mode="lines+markers",
                    name=f"Tram {bi+1} (min {t_ini:.0f}–{t_fi:.0f})",
                    line=dict(color=color_bi, width=2), marker=dict(size=6, color=color_bi),
                    hovertemplate="Min %{x:.1f} del tram<br>Parcial: %{y:+d}<extra></extra>"
                ))

            fig_tram.add_hline(y=0, line_dash="solid", line_color="#e2e4e8")
            fig_tram.update_layout(
                xaxis=dict(title="Minuts dins del tram", showgrid=True, gridcolor="#f3f4f6", color="#9ca3af"),
                yaxis=dict(title="Parcial ±", showgrid=True, gridcolor="#f3f4f6", color="#9ca3af",
                           zeroline=True, zerolinecolor="#e2e4e8"),
                paper_bgcolor="#ffffff", plot_bgcolor="#ffffff", font=dict(color="#374151", family="Inter"),
                legend=dict(bgcolor="#ffffff", bordercolor="#e2e4e8", borderwidth=1, orientation="h",
                            yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=0,r=0,t=40,b=0), height=300)
            st.plotly_chart(fig_tram, use_container_width=True)

    # ── 4. Mapa de calor de parelles ─────────────────────────────────────
    st.markdown(sec("Mapa de calor +/- per parelles"), unsafe_allow_html=True)
    st.caption("Color de cada casella = +/- conjunt de la parella. Verd = l'equip guanya quan juguen juntes.")

    if tid_rot and intervals_jug:
        jugs_eq_all = sorted([j for j,ivs in intervals_jug.items() if any(ei==tid_rot for _,_,ei in ivs)])
        rival_rot_id2 = teams[1] if tid_rot == teams[0] else (teams[0] if teams else None)

        if len(jugs_eq_all) >= 2:
            df_orig_tab = df_orig.copy()
            df_orig_tab["t_abs"] = df_orig_tab.apply(
                lambda r: (int(r["quart"])-1)*10 + (10 - float(r["min_num"]))
                if float(r.get("min_num",0)) <= 10 else float(r.get("min_num",0)), axis=1)

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

            n = len(jugs_eq_all)
            matrix = [[None]*n for _ in range(n)]
            for i,j1 in enumerate(jugs_eq_all):
                for j,j2 in enumerate(jugs_eq_all):
                    if i == j: matrix[i][j] = 0
                    elif i < j:
                        val = pm_parella(j1, j2)
                        matrix[i][j] = val
                        matrix[j][i] = val

            noms_curts = [n.split()[1] if len(n.split())>1 else n for n in jugs_eq_all]
            z_vals = [[v if v is not None else 0 for v in row] for row in matrix]
            text_vals = [[f"+{v}" if v is not None and v > 0 else (str(v) if v is not None else "—")
                          for v in row] for row in matrix]

            fig_hm = go.Figure(go.Heatmap(
                z=z_vals, x=noms_curts, y=noms_curts, text=text_vals, texttemplate="%{text}",
                textfont=dict(size=11, color="white"),
                colorscale=[[0.0, "#dc2626"], [0.5, "#f9fafb"], [1.0, "#16a34a"]],
                zmid=0, showscale=True, colorbar=dict(title="+/-", thickness=12)
            ))
            fig_hm.update_layout(
                height=max(320, n*48+80), paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                font=dict(color="#374151", family="Inter", size=11),
                xaxis=dict(side="top", tickangle=-30), margin=dict(l=0,r=60,t=60,b=0)
            )
            st.plotly_chart(fig_hm, use_container_width=True)
            st.caption("Diagonal = la pròpia jugadora (0). Caselles buides = no han jugat juntes.")
        else:
            st.info("Cal tenir almenys 2 jugadores amb events d'entrada/sortida.")

    # ── 5. +/- per parella (detall) ───────────────────────────────────────
    st.markdown(sec("+/- per parella de jugadores (detall)"), unsafe_allow_html=True)
    st.caption("Parcial de l'equip durant els minuts que les dues jugadores seleccionades han jugat juntes.")

    if tid_rot and intervals_jug:
        jugs_par = [j for j,ivs in intervals_jug.items() if any(ei==tid_rot for _,_,ei in ivs)]
        col_p1, col_p2 = st.columns(2)
        with col_p1: jug_p1 = st.selectbox("Jugadora 1", sorted(jugs_par), key="par_j1")
        with col_p2: jug_p2 = st.selectbox("Jugadora 2",
            [j for j in sorted(jugs_par) if j != jug_p1], key="par_j2")

        if jug_p1 and jug_p2:
            ivs1 = [(ti,tf) for ti,tf,ei in intervals_jug.get(jug_p1,[]) if ei==tid_rot]
            ivs2 = [(ti,tf) for ti,tf,ei in intervals_jug.get(jug_p2,[]) if ei==tid_rot]
            juntes = []
            for a1,a2 in ivs1:
                for b1,b2 in ivs2:
                    ini = max(a1,b1); fi = min(a2,b2)
                    if fi > ini: juntes.append((ini,fi))

            if not juntes:
                st.info(f"{jug_p1} i {jug_p2} no han jugat juntes en aquest partit.")
            else:
                total_min_j = sum(f-i for i,f in juntes)
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

    # ── 6. +/- per quintet (bonus) ─────────────────────────────────────────
    st.markdown(sec("+/- per quintet"), unsafe_allow_html=True)
    quintets = calc_pm_combinacions(df_orig, mode="quintets")
    if quintets and tid_rot:
        dfq = pd.DataFrame([q for q in quintets if str(q["equip"])==str(tid_rot)])
        if not dfq.empty:
            dfq["Quintet"] = dfq["combinacio"].apply(lambda c: ", ".join(n.split()[0] for n in c))
            dfq = dfq.sort_values("pm", ascending=False)
            st.dataframe(dfq[["Quintet","minuts","pf","pc","pm","pm_min"]].rename(
                columns={"minuts":"Min","pf":"Pts favor","pc":"Pts contra","pm":"+/-","pm_min":"+/- per min"}),
                use_container_width=True, hide_index=True)
        else:
            st.info("Sense quintets complets (5 jugadores) prou estables per calcular.")


with t6:
    st.markdown(sec("Rànquing acumulat"), unsafe_allow_html=True)
    df_sj = load_stats_jugador_db()
    if df_sj.empty:
        st.info("Carrega partits per generar l'històric de jugadores.")
    else:
        df_pr = load_partits_db()
        def label_p(mid):
            r = df_pr[df_pr["match_id"]==mid]
            if r.empty: return mid[:10]+"..."
            return f"{r.iloc[0]['nom_a']} vs {r.iloc[0]['nom_b']} ({r.iloc[0]['data_consulta'][:10]})"
        df_sj["Partit"] = df_sj["match_id"].apply(label_p)
        df_sj["Data"] = df_sj["data_consulta"]

        ranking = df_sj.groupby(["jugador","equip_nom"]).agg(
            Partits=("match_id","nunique"), Punts=("punts","sum"),
            C2=("cistelles_2","sum"), C3=("cistelles_3","sum"),
            TL=("tirs_lliures","sum"), Faltes=("faltes","sum"), Impacte=("impacte","sum"),
        ).reset_index()
        ranking["Pts/p"] = (ranking["Punts"]/ranking["Partits"]).round(1)
        ranking["Imp/p"] = (ranking["Impacte"]/ranking["Partits"]).round(1)
        ranking = ranking.sort_values("Punts", ascending=False).rename(columns={"jugador":"Jugadora","equip_nom":"Equip"})

        equips_hist = ["Tots"] + sorted(df_sj["equip_nom"].unique().tolist())
        eq_rank = st.selectbox("Filtra per equip", equips_hist, key="eq_rank")
        df_rk = ranking if eq_rank=="Tots" else ranking[ranking["Equip"]==eq_rank]
        cols_rank = ["Jugadora","Equip","Partits","Punts","Pts/p","C2","C3","TL","Faltes","Impacte","Imp/p"]
        if "minuts" in ranking.columns:
            ranking["Min/p"] = (ranking.get("minuts",0) / ranking["Partits"]).round(1)
            cols_rank = ["Jugadora","Equip","Partits","Punts","Pts/p","C2","C3","TL","Faltes","Min/p","Impacte","Imp/p"]

        st.dataframe(df_rk[[c for c in cols_rank if c in df_rk.columns]], use_container_width=True, hide_index=True)

        # ── Eficiència de tir — ficats/tirats ────────────────────────────
        st.markdown(sec("Eficiència de tir — ficats/tirats"), unsafe_allow_html=True)
        st.caption(
            "Exemple: 12/17 vol dir 12 cistelles de 17 intents. · "
            "**eFG% (Effective FG%)** = (2pts ficats + 1.5 × 3pts ficats) / tirs de camp intentats. "
            "És el % de tirs de camp (2+3, sense tirs lliures) corregit perquè un triple val 1,5 cops més que un doble."
        )
        df_sz_rank = load_shots_zones_db()
        if not df_sz_rank.empty:
            df_sz_agg = df_sz_rank[df_sz_rank["jugador"]!="__equip__"].groupby(["jugador","equip_nom"]).agg(
                v1m=("val1_made","sum"), v1x=("val1_miss","sum"),
                v2m=("val2_made","sum"), v2x=("val2_miss","sum"),
                v3m=("val3_made","sum"), v3x=("val3_miss","sum"),
            ).reset_index()

            eq_tir_rank = st.selectbox("Equip", ["Tots"] + sorted(df_sz_agg["equip_nom"].unique().tolist()), key="eq_tir_rank")
            df_sz_show = df_sz_agg if eq_tir_rank == "Tots" else df_sz_agg[df_sz_agg["equip_nom"]==eq_tir_rank]
            df_sz_show = df_sz_show.copy()
            df_sz_show["TL (1pt)"] = df_sz_show.apply(lambda r: f"{r.v1m}/{r.v1m+r.v1x} ({round(r.v1m/(r.v1m+r.v1x)*100) if (r.v1m+r.v1x)>0 else 0}%)", axis=1)
            df_sz_show["2pts"]     = df_sz_show.apply(lambda r: f"{r.v2m}/{r.v2m+r.v2x} ({round(r.v2m/(r.v2m+r.v2x)*100) if (r.v2m+r.v2x)>0 else 0}%)", axis=1)
            df_sz_show["3pts"]     = df_sz_show.apply(lambda r: f"{r.v3m}/{r.v3m+r.v3x} ({round(r.v3m/(r.v3m+r.v3x)*100) if (r.v3m+r.v3x)>0 else 0}%)", axis=1)
            df_sz_show["eFG%"]     = df_sz_show.apply(lambda r: f"{round((r.v2m+r.v3m+0.5*r.v3m)/(r.v2m+r.v2x+r.v3m+r.v3x)*100,1) if (r.v2m+r.v2x+r.v3m+r.v3x)>0 else 0}%", axis=1)
            df_sz_show["Total"]    = df_sz_show.apply(lambda r: f"{r.v1m+r.v2m+r.v3m}/{r.v1m+r.v1x+r.v2m+r.v2x+r.v3m+r.v3x} ({round((r.v1m+r.v2m+r.v3m)/(r.v1m+r.v1x+r.v2m+r.v2x+r.v3m+r.v3x)*100) if (r.v1m+r.v1x+r.v2m+r.v2x+r.v3m+r.v3x)>0 else 0}%)", axis=1)
            df_sz_show = df_sz_show.sort_values("v2m", ascending=False)
            st.dataframe(df_sz_show[["jugador","equip_nom","TL (1pt)","2pts","3pts","eFG%","Total"]].rename(
                columns={"jugador":"Jugadora","equip_nom":"Equip"}), use_container_width=True, hide_index=True)
        else:
            st.info("Consulta més partits per veure les estadístiques de tir.")

        tots_jugs_hist = sorted(df_sj["jugador"].unique().tolist())

        # ── Rendiment per bloc de minuts — primers vs últims ─────────────
        st.markdown(sec("Rendiment per bloc de minuts — primers vs últims"), unsafe_allow_html=True)
        st.caption("Compara si la jugadora anota més al principi o al final de cada bloc de minuts que juga.")

        BLOC_MINS = 3
        jug_bloc = st.selectbox("Jugadora", tots_jugs_hist, key="jug_bloc")
        if jug_bloc:
            con_bloc = sqlite3.connect(DB_PATH)
            df_bloc = pd.read_sql("SELECT * FROM jugades WHERE jugador=? ORDER BY match_id, num", con_bloc, params=(jug_bloc,))
            con_bloc.close()

            if df_bloc.empty:
                st.info("Sense dades de play-by-play per a aquesta jugadora.")
            else:
                bloc_rows = []
                for mid, df_mid in df_bloc.groupby("match_id"):
                    df_mid = df_mid.sort_values("min_num")
                    df_mid["gap"] = df_mid["min_num"].diff().fillna(0)
                    df_mid["bloc_id"] = (df_mid["gap"] > 2).cumsum()

                    for bloc_id, df_b in df_mid.groupby("bloc_id"):
                        if len(df_b) < 2: continue
                        min_inici = df_b["min_num"].min()
                        min_fi    = df_b["min_num"].max()
                        durada    = min_fi - min_inici
                        if durada < BLOC_MINS * 2: continue

                        df_primers = df_b[df_b["min_num"] <= min_inici + BLOC_MINS]
                        pts_primers = int(df_primers["punts"].sum())
                        df_ultims = df_b[df_b["min_num"] >= min_fi - BLOC_MINS]
                        pts_ultims = int(df_ultims["punts"].sum())

                        row_p = df_pr[df_pr["match_id"]==mid]
                        lbl = f"{row_p.iloc[0]['nom_a']} vs {row_p.iloc[0]['nom_b']}" if not row_p.empty else mid[:8]

                        bloc_rows.append({
                            "Partit": lbl, "Bloc": f"Bloc {int(bloc_id)+1}", "Durada (min)": round(durada, 1),
                            f"Pts primers {BLOC_MINS} min": pts_primers, f"Pts últims {BLOC_MINS} min": pts_ultims,
                            "Tendència": "📈 Millora" if pts_ultims > pts_primers
                                         else ("📉 Baixa" if pts_ultims < pts_primers else "➡️ Estable")
                        })

                if bloc_rows:
                    df_blocs = pd.DataFrame(bloc_rows)
                    st.dataframe(df_blocs, use_container_width=True, hide_index=True)

                    col_b1, col_b2, col_b3 = st.columns(3)
                    mit_p = df_blocs[f"Pts primers {BLOC_MINS} min"].mean()
                    mit_u = df_blocs[f"Pts últims {BLOC_MINS} min"].mean()
                    tendencia = "📈 Millora al final" if mit_u > mit_p else ("📉 Baixa al final" if mit_u < mit_p else "➡️ Estable")
                    with col_b1: st.markdown(card(f"Pts/bloc inici",f"{mit_p:.1f}","mitjana","#185FA5"),unsafe_allow_html=True)
                    with col_b2: st.markdown(card(f"Pts/bloc final",f"{mit_u:.1f}","mitjana","#185FA5"),unsafe_allow_html=True)
                    with col_b3: st.markdown(card("Tendència global",tendencia,"","#374151"),unsafe_allow_html=True)

                    fig_bloc = go.Figure()
                    fig_bloc.add_trace(go.Bar(name=f"Primers {BLOC_MINS} min",
                        x=df_blocs["Partit"]+" "+df_blocs["Bloc"], y=df_blocs[f"Pts primers {BLOC_MINS} min"],
                        marker_color=COLOR_A, opacity=0.8))
                    fig_bloc.add_trace(go.Bar(name=f"Últims {BLOC_MINS} min",
                        x=df_blocs["Partit"]+" "+df_blocs["Bloc"], y=df_blocs[f"Pts últims {BLOC_MINS} min"],
                        marker_color="#16a34a", opacity=0.8))
                    fig_bloc.update_layout(barmode="group")
                    fig_bloc.update_xaxes(tickangle=-30)
                    st.plotly_chart(chart_style(fig_bloc,260,f"{jug_bloc} — primers vs últims minuts del bloc"),use_container_width=True)
                else:
                    st.info(f"No hi ha blocs de més de {BLOC_MINS*2} minuts per a aquesta jugadora.")

    # ── Usage% vs Pts/40min ──────────────────────────────────────────────
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
            if min_tot < 5: continue
            pts_tot = grp["punts"].sum()
            usage = grp["usage_rate"].mean() if "usage_rate" in grp.columns else 0
            rows_p40.append({
                "Jugadora": jug, "Partits": grp["match_id"].nunique(),
                "Min tot": round(min_tot, 1), "Pts tot": int(pts_tot),
                "Usage%": round(usage, 1), "Pts/40min": round(pts_tot / min_tot * 40, 1),
            })
        df_p40 = pd.DataFrame(rows_p40)

        if df_p40.empty:
            st.info("Cap jugadora amb almenys 5 minuts totals per a aquest equip.")
        else:
            fig_p40 = go.Figure()
            sizes_p40 = df_p40["Min tot"].clip(lower=1)
            sizes_norm = (sizes_p40 / sizes_p40.max() * 22 + 10).round(0)
            fig_p40.add_trace(go.Scatter(
                x=df_p40["Usage%"], y=df_p40["Pts/40min"], mode="markers+text", name=eq_p40_sel,
                marker=dict(size=sizes_norm, color=COLOR_A, line=dict(width=1.5, color=C_WHITE), opacity=0.88),
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
                st.dataframe(df_p40_show, use_container_width=True, hide_index=True)


with t7:
    st.markdown(sec("🎯 Mapa de tir"), unsafe_allow_html=True)
    st.caption("Coordenades extretes automàticament del play-by-play de feb.es.")
    df_tirs = load_tirs_fcbq(match_id=match_id)
    if df_tirs.empty:
        st.info("Sense dades de tir per aquest partit.")
    else:
        eq_tir = st.selectbox("Equip", [nom_a, nom_b], key="eq_tir_lf2")
        dt = df_tirs[df_tirs["equip_nom"]==eq_tir]
        if dt.empty:
            st.info("Sense tirs per aquest equip.")
        else:
            dt = dt.copy()
            dt["Resultat"] = dt["fet"].map({1:"Encertat", 0:"Fallat"})
            fig_shot = go.Figure()
            for fet, color, nom in [(1, "#16a34a", "Encertat"), (0, "#dc2626", "Fallat")]:
                d_f = dt[dt["fet"]==fet]
                fig_shot.add_trace(go.Scatter(x=d_f["x"], y=d_f["y"], mode="markers", name=nom,
                    marker=dict(size=9, color=color, opacity=0.75, line=dict(width=1, color="white"))))
            fig_shot.update_layout(xaxis=dict(range=[0,100], showgrid=False, zeroline=False, visible=False),
                yaxis=dict(range=[0,100], showgrid=False, zeroline=False, visible=False, scaleanchor="x"),
                paper_bgcolor="#fff", plot_bgcolor="#f9fafb", height=420,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=0,r=0,t=30,b=0))
            st.plotly_chart(fig_shot, use_container_width=True)

            tot = len(dt); fets = int(dt["fet"].sum())
            st.markdown(card("Tirs totals", tot, f"{fets} encertats ({round(fets/tot*100,1) if tot else 0}%)", COLOR_A if eq_tir==nom_a else COLOR_B), unsafe_allow_html=True)
            st.caption("⚠️ Classificació per zones (pintada/mig/triple) encara no disponible per feb.es: "
                       "les coordenades de feb.es semblen fer servir un sistema de pista sencera diferent del "
                       "de mig camp de la FCBQ (classifica_zona_tir no és compatible tal qual). Pendent de calibrar.")


with t_arq:
    st.markdown(sec("🎭 Arquetips de jugadora"), unsafe_allow_html=True)
    st.caption("Classificació simplificada de l'estil de cada jugadora a partir del seu Usage% i distribució de punts (2pts/3pts/TL), acumulat de tota la temporada.")
    df_sj_arq = load_stats_jugador_db()
    if df_sj_arq.empty or len(df_sj_arq) < 5:
        st.info("Carrega més partits per generar arquetips fiables (mínim recomanat: 3-5 partits).")
    else:
        col_j_arq = "jugador" if "jugador" in df_sj_arq.columns else "jugadora"
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
        agg_arq["usage_pct"] = agg_arq["usage"].round(1) if "usage_rate" in df_sj_arq.columns else 0
        agg_arq["min_p"] = (agg_arq["minuts"]/agg_arq["partits"].replace(0,1)).round(1)
        agg_arq["Arquetip"] = agg_arq.apply(
            lambda r: classifica_arquetip_global(r["usage_pct"], r["p2_pct"], r["p3_pct"], r["ptl_pct"], r["min_p"]),
            axis=1)
        df_show_arq = agg_arq.rename(columns={col_j_arq:"jugador"})[
            ["jugador","equip","partits","min_p","usage_pct","p2_pct","p3_pct","ptl_pct","Arquetip"]]
        df_show_arq.columns = ["Jugadora","Equip","Partits","Min/P","Usage%","%Pts2","%Pts3","%PtsTL","Arquetip"]
        df_show_arq = df_show_arq.sort_values("Usage%", ascending=False)
        st.dataframe(df_show_arq, use_container_width=True, hide_index=True)

        st.markdown(sec("🔍 Anàlisi d'ecosistema — amb quins arquetips rendeix millor?"), unsafe_allow_html=True)
        st.caption("Creua els quintets/parelles ja calculats amb els arquetips per veure quines combinacions d'estils funcionen millor juntes.")

        jug_eco = st.selectbox("Jugadora a analitzar", df_show_arq["Jugadora"].tolist(), key="jug_eco_arq")

        if jug_eco:
            arquetip_jug = df_show_arq[df_show_arq["Jugadora"]==jug_eco]["Arquetip"].values[0]

            st.markdown(f'<div style="font-size:13px;font-weight:600;color:#185FA5;margin-bottom:8px">'
                       f'{jug_eco} — <span style="color:#0C447C">{arquetip_jug}</span></div>', unsafe_allow_html=True)

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
                            "company": altra_jug, "minuts": r_par_eco["minuts"],
                            "pf": r_par_eco["pf"], "pc": r_par_eco["pc"]
                        })

            if ecosistema_rows:
                df_eco = pd.DataFrame(ecosistema_rows)
                eco_acum = df_eco.groupby("company").agg(
                    minuts=("minuts","sum"), pf=("pf","sum"), pc=("pc","sum")
                ).reset_index()
                eco_acum["pm"] = eco_acum["pf"]-eco_acum["pc"]
                eco_acum["pm_min"] = (eco_acum["pm"]/eco_acum["minuts"].replace(0,1)).round(3)

                arq_map = dict(zip(df_show_arq["Jugadora"], df_show_arq["Arquetip"]))
                eco_acum["Arquetip company"] = eco_acum["company"].map(arq_map).fillna("—")

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
                        y=eco_per_arq["Arquetip company"], x=eco_per_arq["pm_min"], orientation='h',
                        marker_color=colors_eco,
                        text=[f"{'+'if v>=0 else ''}{v:.3f}" for v in eco_per_arq["pm_min"]],
                        textposition="outside", customdata=eco_per_arq["minuts"],
                        hovertemplate="<b>%{y}</b><br>+/- per min: %{x:+.3f}<br>Minuts junts: %{customdata:.1f}<extra></extra>"
                    ))
                    fig_eco.add_vline(x=0, line_dash="solid", line_color="#e2e4e8")
                    fig_eco.update_xaxes(title="+/- per minut quan juguen junts")
                    st.plotly_chart(chart_style(fig_eco, max(250, len(eco_per_arq)*40),
                        f"{jug_eco} — rendiment segons l'arquetip del company"), use_container_width=True)

                    millor_arq = eco_per_arq.iloc[0]
                    pitjor_arq = eco_per_arq.iloc[-1]
                    st.info(f"📊 **{jug_eco}** rendeix millor amb perfils **{millor_arq['Arquetip company']}** "
                            f"({millor_arq['pm_min']:+.3f}/min, {millor_arq['minuts']:.0f} min junts) i pitjor amb "
                            f"**{pitjor_arq['Arquetip company']}** ({pitjor_arq['pm_min']:+.3f}/min, {pitjor_arq['minuts']:.0f} min junts).")

                    with st.expander("Veure detall per companya individual"):
                        eco_detall = eco_acum[["company","Arquetip company","minuts","pm","pm_min"]].sort_values("pm_min", ascending=False)
                        eco_detall.columns = ["Companya","Arquetip","Min junts","+/-","+/- per min"]
                        st.dataframe(eco_detall, use_container_width=True, hide_index=True)
                else:
                    st.info("No hi ha prou minuts compartits amb altres jugadores per fer l'anàlisi.")
            else:
                st.info("No hi ha dades suficients de parelles per a aquesta jugadora.")


with t9:
    st.markdown(sec("📚 Partits carregats"), unsafe_allow_html=True)
    df_hist = load_partits_db()
    if df_hist.empty:
        st.info("Encara no hi ha cap partit desat.")
    else:
        st.dataframe(df_hist[["match_id","nom_a","nom_b","score_a","score_b","data_consulta"]].rename(
            columns={"match_id":"ID","nom_a":"Local","nom_b":"Visitant","score_a":"Pts A","score_b":"Pts B",
                     "data_consulta":"Carregat"}), use_container_width=True, hide_index=True)

        st.markdown(sec("🏆 Win Shares de temporada"), unsafe_allow_html=True)
        if len(df_hist) < 2:
            st.caption("Calen almenys 2 partits carregats per a una referència de lliga mínimament fiable.")
        df_ws = calc_win_shares_temporada()
        if df_ws.empty:
            st.info("Encara no hi ha prou dades.")
        else:
            df_ws_show = df_ws.sort_values("WS", ascending=False)[
                ["jugador","equip","partits","minuts","punts","OWS","DWS","WS","ws_per40","Arquetip"]]
            st.dataframe(df_ws_show.rename(columns={"jugador":"Jugadora","equip":"Equip","partits":"PJ",
                "minuts":"Min","punts":"Pts","ws_per40":"WS/40"}), use_container_width=True, hide_index=True)

        st.markdown(sec("Exporta la temporada a Excel"), unsafe_allow_html=True)
        if st.button("⬇ Descarregar Excel de temporada", key="btn_excel_temp_lf2"):
            excel_temp_data = genera_excel_temporada()
            if excel_temp_data:
                st.download_button(
                    label="📥 Clic per descarregar", data=excel_temp_data,
                    file_name=f"analitica_lf2_temporada_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_excel_temp_lf2")
            else:
                st.info("No hi ha partits a la base de dades.")
