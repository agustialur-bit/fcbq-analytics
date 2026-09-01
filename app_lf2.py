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
from analitica_core import (
    MICKI_CSS, card, sec, chart_style,
    init_db, migrate_db, save_partit, save_stats_jugador, save_shots_zones,
    save_timeouts, save_tirs_fcbq, load_jugades_db, load_partits_db,
    load_stats_jugador_db, load_tirs_fcbq, partit_exists,
    get_teams, get_teams_ordered, score_evo, final_score, estat_marc, analyze_timeouts,
    get_intervals_jugadores_global, calc_pm_combinacions, calc_possessions,
    calc_eficiencies, calc_onoff, calc_onoff_ts, calc_usage_rate,
    calc_win_shares_temporada, calc_metriques_partit, classifica_arquetip_global,
    TC_INT_PAT, TL_INT_PAT, C_TEXT, C_BG, C_BG_SOFT, C_BORDER, C_ACCENT_DARK,
    C_WHITE, C_LABEL, C_SUCCESS, C_ERROR,
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
        elif action in ("foul", "assist", "recovery", "lose", "blockshot"):
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
t1, t2, t3, t4, t_onoff, t5, t7, t_arq, t9 = st.tabs([
    "🏀 Partit", "👤 Jugadores", "⏱ Ritme", "⚡ Eficiència", "⚖️ On/Off", "🔄 Rotacions",
    "🎯 Mapa de Tir", "🎭 Arquetips", "📚 Històric"
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


with t2:
    st.markdown(sec("Estadístiques per jugadora"), unsafe_allow_html=True)
    df_sj_match = load_stats_jugador_db()
    df_sj_match = df_sj_match[df_sj_match["match_id"]==match_id] if not df_sj_match.empty else df_sj_match
    tab_pa, tab_pb = st.tabs([nom_a, nom_b])
    for ptab, pnom in [(tab_pa, nom_a), (tab_pb, nom_b)]:
        with ptab:
            de = df_sj_match[df_sj_match["equip_nom"]==pnom] if not df_sj_match.empty else pd.DataFrame()
            if de.empty:
                st.info("Sense dades.")
                continue
            show = de[["jugador","minuts","punts","cistelles_2","cistelles_3","tirs_lliures",
                       "faltes","impacte","usage_rate"]].sort_values("punts", ascending=False)
            st.dataframe(show.rename(columns={"jugador":"Jugadora","minuts":"Min","punts":"Pts",
                "cistelles_2":"C2","cistelles_3":"C3","tirs_lliures":"TL","faltes":"Faltes",
                "impacte":"+/-","usage_rate":"Usage%"}), use_container_width=True, hide_index=True)

    st.markdown(sec("Usage% vs Eficiència"), unsafe_allow_html=True)
    st.caption("Eix X = % de possessions usades · Eix Y = Pts/min · Quadrant ideal: dalt a la dreta")
    if not df_sj_match.empty:
        dfsc = df_sj_match.copy()
        dfsc["pts_min"] = dfsc.apply(lambda r: round(r["punts"]/r["minuts"],2) if r["minuts"]>0 else 0, axis=1)
        fig_sc = go.Figure()
        for eq, color in [(nom_a, COLOR_A), (nom_b, COLOR_B)]:
            deq = dfsc[dfsc["equip_nom"]==eq]
            if deq.empty: continue
            fig_sc.add_trace(go.Scatter(x=deq["usage_rate"], y=deq["pts_min"], mode="markers+text",
                name=eq, marker=dict(size=14, color=color, line=dict(width=1.5, color="white")),
                text=deq["jugador"].apply(lambda n: n.split()[0] if n else n),
                textposition="top center", textfont=dict(size=9)))
        fig_sc.update_layout(xaxis_title="Usage% (% possessions usades)", yaxis_title="Pts/min",
            paper_bgcolor="#fff", plot_bgcolor="#fff", font=dict(color="#374151", family="Inter"),
            legend=dict(bgcolor="#fff", bordercolor="#e2e4e8", borderwidth=1, orientation="h",
                        yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=0,r=0,t=40,b=0), height=380)
        st.plotly_chart(fig_sc, use_container_width=True)

    st.markdown(sec("Jugadora: puntua quan guanya o perd?"), unsafe_allow_html=True)
    tots_jugs=sorted([j for j in df_orig["jugador"].unique().tolist() if j])
    jug_sel=st.selectbox("Jugadora",tots_jugs,key="jug_analisi_lf2")
    if jug_sel:
        dj2=df_orig[df_orig["jugador"]==jug_sel].copy()
        dj2["estat"]=dj2.apply(lambda r: estat_marc(r,teams),axis=1)
        res2=dj2.groupby("estat").agg(Punts=("punts","sum"),Accions=("accio","count")
            ).reindex(["Guanyant","Empatat","Perdent"]).fillna(0).astype(int)
        ec={"Guanyant":"#16a34a","Empatat":"#d97706","Perdent":"#dc2626"}
        ei={"Guanyant":"📈","Empatat":"➡️","Perdent":"📉"}
        cg,ce,cp=st.columns(3)
        for col,estat in zip([cg,ce,cp],["Guanyant","Empatat","Perdent"]):
            with col:
                pts=int(res2.loc[estat,"Punts"]) if estat in res2.index else 0
                acc=int(res2.loc[estat,"Accions"]) if estat in res2.index else 0
                st.markdown(card(f"{ei[estat]} {estat}",pts,f"{acc} accions",ec[estat]),unsafe_allow_html=True)


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


with t4:
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
        metrics_cmp = [
            ("Off Rtg", ef_cmp[tid_a_cmp]["off_rtg"], ef_cmp[tid_b_cmp]["off_rtg"]),
            ("Def Rtg", ef_cmp[tid_a_cmp]["def_rtg"], ef_cmp[tid_b_cmp]["def_rtg"]),
            ("Net Rtg", ef_cmp[tid_a_cmp]["net_rtg"], ef_cmp[tid_b_cmp]["net_rtg"]),
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


with t_onoff:
    st.markdown(sec("⚡ Eficiència i On/Off Rating per jugadora"), unsafe_allow_html=True)
    st.caption("On/Off Net Rating = diferència de Net Rating (pts/100 poss) quan la jugadora és a pista vs quan no hi és. "
               "⚠️ = poques possessions Off, valor poc fiable.")
    st.markdown("**Eficiències d'equip**")
    ef2 = calc_eficiencies(df_orig, teams, team_names)
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
            oo2 = calc_onoff(df_orig, jug2, tid_oo2, teams)
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


with t5:
    st.markdown(sec("🔄 Rotacions"), unsafe_allow_html=True)
    intervals_rot = get_intervals_jugadores_global(df_orig)
    eq_rot = st.selectbox("Equip", [nom_a, nom_b], key="eq_rot_lf2")
    tid_rot = teams[0] if eq_rot == nom_a else (teams[1] if len(teams)>1 else None)
    if tid_rot:
        gantt_rows = []
        for jug, ivs in intervals_rot.items():
            for ti, tf, ei in ivs:
                if str(ei) != str(tid_rot): continue
                gantt_rows.append({"Jugadora": jug, "Inici": ti, "Final": tf})
        if gantt_rows:
            df_gantt = pd.DataFrame(gantt_rows)
            ordre = df_gantt.groupby("Jugadora")["Inici"].min().sort_values().index.tolist()
            fig_g = go.Figure()
            for _, r in df_gantt.iterrows():
                fig_g.add_trace(go.Bar(x=[r["Final"]-r["Inici"]], y=[r["Jugadora"]], base=r["Inici"],
                    orientation="h", marker_color=COLOR_A if eq_rot==nom_a else COLOR_B,
                    showlegend=False, hovertemplate=f"{r['Jugadora']}: {r['Inici']:.1f}–{r['Final']:.1f} min<extra></extra>"))
            max_t = df_orig["quart"].max()*10
            for q in range(1, int(df_orig["quart"].max())):
                fig_g.add_vline(x=q*10, line_dash="dot", line_color="#e2e4e8")
            fig_g.update_layout(yaxis=dict(categoryorder="array", categoryarray=ordre[::-1]),
                xaxis=dict(title="Minut de partit", range=[0, max_t]),
                paper_bgcolor="#fff", plot_bgcolor="#fff", font=dict(color="#374151", family="Inter"),
                margin=dict(l=0,r=0,t=10,b=0), height=max(220, 32*len(ordre)), barmode="stack")
            st.plotly_chart(fig_g, use_container_width=True)
        else:
            st.info("Sense intervals per aquest equip.")

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
