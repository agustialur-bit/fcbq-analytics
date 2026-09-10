# -*- coding: utf-8 -*-
"""Generació de PDFs (informe de partit i de temporada) amb reportlab.

Reaprofita analitica_core.py i core_four_factors.py — aquest mòdul no calcula
res de nou (excepte un parell d'agregacions petites que no existien com a
funció reutilitzable — vegeu _impacte_en_pista_rows / _rot_per_equip / etc.
més avall), només maqueta el que ja existeix en un PDF descarregable.
"""
import io
from datetime import datetime

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak

from scipy import stats as sp_stats

import analitica_core as core
import core_four_factors as cff

BLAU_FOSC = colors.HexColor("#0C447C")
BLAU = colors.HexColor("#185FA5")
GRIS_CLAR = colors.HexColor("#EBF4FC")

_styles = getSampleStyleSheet()
TITOL = ParagraphStyle("Titol", parent=_styles["Title"], textColor=BLAU_FOSC, fontSize=18)
SUBTITOL = ParagraphStyle("Subtitol", parent=_styles["Heading2"], textColor=BLAU,
                          fontSize=13, spaceBefore=14, spaceAfter=6)
NORMAL = _styles["Normal"]
CAP_TAULA = ParagraphStyle("CapTaula", parent=NORMAL, textColor=colors.white,
                            fontSize=8, leading=9, alignment=1)  # 1 = TA_CENTER


def _hp(text):
    """Capçalera de taula com a Paragraph perquè faci salt de línia dins
    l'amplada de columna (una cadena normal es talla/superposa si el nom
    de l'equip és llarg)."""
    return Paragraph(str(text), CAP_TAULA)


CEL_TAULA = ParagraphStyle("CelTaula", parent=NORMAL, fontSize=8, leading=9)


def _bp(text):
    """Cel·la de dades com a Paragraph (mateix motiu que _hp, per a cel·les
    amb noms d'equip llargs fora de la capçalera, p.ex. la taula de ROT)."""
    return Paragraph(str(text), CEL_TAULA)


def _taula_estil(font_size=9):
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLAU),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B5D4F4")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRIS_CLAR]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])


def _tbl(data, widths, font_size=9):
    t = Table(data, colWidths=widths)
    t.setStyle(_taula_estil(font_size))
    return t


def _na(v, fmt=None):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return format(v, fmt) if fmt else v


# ══════════════════════════════════════════════════
# Agregacions petites que encara no existeixen com a funció reutilitzable
# a analitica_core.py / core_four_factors.py (totes es basen en
# get_intervals_jugadores_global, la mateixa font que fa servir la resta
# del motor de càlcul — no es reinventa cap lògica de minuts/entra-surt).
# ══════════════════════════════════════════════════

def _t_abs(row):
    q = int(row["quart"]) if row.get("quart", "") != "" else 1
    m = float(row.get("min_num", 0))
    t = (q - 1) * 10 + (10 - m if m <= 10 else m)
    return max(0, min(t, q * 10))


def _impacte_en_pista_rows(df_orig, teams, team_names):
    """+/- (Pts favor/contra) i Usage% per jugadora, intervals reals Entra/Surt."""
    col_j = "jugador" if "jugador" in df_orig.columns else "jugadora"
    intervals = core.get_intervals_jugadores_global(df_orig)
    df_t = df_orig.copy()
    df_t["t_abs"] = df_t.apply(_t_abs, axis=1)

    rows = []
    for jug, ivs in intervals.items():
        for eq_id in teams:
            ivs_eq = [(ti, tf) for ti, tf, ei in ivs if str(ei) == str(eq_id)]
            if not ivs_eq:
                continue
            rival_id = next((t for t in teams if t != eq_id), None)
            mask = df_t["t_abs"].apply(lambda t: any(ti <= t <= tf for ti, tf in ivs_eq))
            win = df_t[mask]
            pf = int(win[win["idEquip"] == eq_id]["punts"].sum())
            pc = int(win[win["idEquip"] == rival_id]["punts"].sum()) if rival_id is not None else 0
            minuts = round(sum(tf - ti for ti, tf in ivs_eq), 1)
            dj = df_orig[df_orig[col_j] == jug]
            usage = core.calc_usage_rate(dj, win[win["idEquip"] == eq_id])
            rows.append({"equip_id": eq_id, "Equip": team_names.get(eq_id, "?"), "Jugadora": jug,
                         "MIN": minuts, "Pts favor": pf, "Pts contra": pc,
                         "+/-": pf - pc, "Usage%": usage})
    return rows


def _onoff_rows(df_orig, teams, team_names):
    """OER/DER/NetRtg on vs off per jugadora (calc_onoff, poss_mode='full')."""
    col_j = "jugador" if "jugador" in df_orig.columns else "jugadora"
    minuts_reals = core.calc_minuts_reals(df_orig)
    rows = []
    for eq_id in teams:
        jugs = sorted([j for j in df_orig[df_orig["idEquip"] == eq_id][col_j].unique() if j])
        for jug in jugs:
            oo = core.calc_onoff(df_orig, jug, eq_id, teams, poss_mode="full")
            if oo is None:
                continue
            rows.append({
                "equip_id": eq_id, "Equip": team_names.get(eq_id, "?"), "Jugadora": jug,
                "MIN": minuts_reals.get(jug, 0),
                "OER on": oo["on_off_rtg"], "OER off": oo["off_off_rtg"],
                "DER on": oo["on_def_rtg"], "DER off": oo["off_def_rtg"],
                "NetRtg on": oo["on_net_rtg"], "NetRtg off": oo["off_net_rtg"],
                "NET": oo["diff"],
            })
    return rows


def _rot_per_equip(df_orig, teams):
    """ROT (5·(ρ+1)) per equip a partir de minuts vs +/- per minut de cada jugadora.
    Retorna dict equip_id -> {rot, rho, pval, n}, o sense entrada si <3 jugadores."""
    intervals = core.get_intervals_jugadores_global(df_orig)
    df_t = df_orig.copy()
    df_t["t_abs"] = df_t.apply(_t_abs, axis=1)
    out = {}
    for eq_id in teams:
        rival_id = next((t for t in teams if t != eq_id), None)
        if rival_id is None:
            continue
        minuts_l, pm_min_l = [], []
        for jug, ivs in intervals.items():
            ivs_eq = [(ti, tf) for ti, tf, ei in ivs if str(ei) == str(eq_id)]
            if not ivs_eq:
                continue
            minuts = sum(tf - ti for ti, tf in ivs_eq)
            if minuts < 0.5:
                continue
            pf = pc = 0
            for ti, tf in ivs_eq:
                win = df_t[(df_t["t_abs"] >= ti) & (df_t["t_abs"] <= tf)]
                pf += int(win[win["idEquip"] == eq_id]["punts"].sum())
                pc += int(win[win["idEquip"] == rival_id]["punts"].sum())
            minuts_l.append(minuts)
            pm_min_l.append((pf - pc) / minuts)
        if len(minuts_l) < 3 or len(set(minuts_l)) < 2 or len(set(pm_min_l)) < 2:
            continue
        rho, pval = sp_stats.pearsonr(minuts_l, pm_min_l)
        out[eq_id] = {"rot": round(5 * (rho + 1), 2), "rho": rho, "pval": pval, "n": len(minuts_l)}
    return out


def _fmt_pm(v):
    if v is None:
        return "—"
    return f"{'+' if v >= 0 else ''}{v}"


def _color_pm(val, vmax):
    """Verd-blanc-vermell interpolat segons +/- (mateixa paleta que el Mapa
    de calor +/- per parelles en pantalla: #16a34a verd / #dc2626 vermell)."""
    if val is None or not vmax:
        return colors.HexColor("#f9fafb")
    t = max(-1.0, min(1.0, val / vmax))
    if t >= 0:
        r = 1 - t * (1 - 0.086); g = 1 - t * (1 - 0.639); b = 1 - t * (1 - 0.290)
    else:
        t = -t
        r = 1 - t * (1 - 0.863); g = 1 - t * (1 - 0.149); b = 1 - t * (1 - 0.149)
    return colors.Color(r, g, b)


def _heatmap_parelles_elems(parelles, intervals, eq_id, eq_nom):
    """Graella NxN acolorida (verd=l'equip guanya, vermell=perd) amb el +/-
    conjunt de cada parella de jugadores de l'equip quan han jugat juntes.
    Reaprofita calc_pm_combinacions(mode='parelles') — mateixa font de dades
    que la taula 'Parelles' i que el Mapa de calor +/- per parelles en pantalla."""
    jugs = sorted({j for j, ivs in intervals.items() if any(str(ei) == str(eq_id) for _, _, ei in ivs)})
    n = len(jugs)
    if n < 2:
        return []

    pm_map = {}
    for p in parelles:
        if str(p["equip"]) == str(eq_id):
            pm_map[tuple(sorted(p["combinacio"]))] = p["pm"]

    matrix = [[None] * n for _ in range(n)]
    for i in range(n):
        matrix[i][i] = 0
        for j in range(i + 1, n):
            v = pm_map.get(tuple(sorted((jugs[i], jugs[j]))))
            matrix[i][j] = v
            matrix[j][i] = v

    vmax = max([abs(v) for row in matrix for v in row if v is not None] or [1]) or 1
    noms_curts = [j.split()[-1] if len(j.split()) > 1 else j for j in jugs]

    data = [[""] + [_hp(nc) for nc in noms_curts]]
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), BLAU_FOSC),
        ("BACKGROUND", (0, 0), (0, -1), BLAU_FOSC),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
    ]
    for i in range(n):
        row = [_hp(noms_curts[i])]
        for j in range(n):
            v = matrix[i][j]
            row.append("" if v is None else _fmt_pm(v))
            if i == j:
                bg = colors.HexColor("#e5e7eb")
            else:
                bg = _color_pm(v, vmax)
            style_cmds.append(("BACKGROUND", (j + 1, i + 1), (j + 1, i + 1), bg))
            style_cmds.append(("TEXTCOLOR", (j + 1, i + 1), (j + 1, i + 1), colors.white))
        data.append(row)

    col_w = min(14 * mm, 140 * mm / (n + 1))
    t = Table(data, colWidths=[20 * mm] + [col_w] * n, rowHeights=5.5 * mm)
    t.setStyle(TableStyle(style_cmds))
    return [
        Paragraph(eq_nom, ParagraphStyle(f"EqLabelHM_{eq_id}", parent=NORMAL, textColor=BLAU_FOSC,
                                          fontSize=10, spaceBefore=6, spaceAfter=3)),
        t, Spacer(1, 6),
    ]


# ══════════════════════════════════════════════════
# Agregacions per al PDF de temporada
# ══════════════════════════════════════════════════

def _team_season_four_factors(df_partits):
    """Quatre Factors (Dean Oliver) + TS%/eFG%/OffRtg/DefRtg/NetRtg acumulats
    de temporada per equip — mateixes fórmules que calc_four_factors() (un sol
    partit), sumant encerts/intents/possessions de tots els partits abans de
    dividir (no mitjana de percentatges per partit). Clau d'agregació = NOM
    d'equip, no idEquip (intern i no estable entre partits)."""
    if df_partits.empty:
        return pd.DataFrame()

    acum = {}
    for _, p in df_partits.iterrows():
        df_m = core.load_jugades_db(p["match_id"])
        if df_m.empty:
            continue
        teams_m = core.get_teams_ordered(df_m)
        if len(teams_m) < 2:
            continue
        tn_m = {str(teams_m[0]): p["nom_a"], str(teams_m[1]): p["nom_b"]}

        for i, tid in enumerate(teams_m[:2]):
            rival_id = teams_m[1 - i]
            df_eq = df_m[df_m["idEquip"].astype(str) == str(tid)]
            df_riv = df_m[df_m["idEquip"].astype(str) == str(rival_id)]
            nom_eq = tn_m.get(str(tid), "?")

            fgm2 = int(df_eq["accio"].str.contains("Cistella de 2", case=False, na=False).sum())
            fga2 = fgm2 + int(df_eq["accio"].str.contains("Intent fallat de 2", case=False, na=False).sum())
            fgm3 = int(df_eq["accio"].str.contains("Cistella de 3", case=False, na=False).sum())
            fga3 = fgm3 + int(df_eq["accio"].str.contains("Intent fallat de 3", case=False, na=False).sum())
            ftm = int(df_eq["accio"].str.contains("Cistella de 1", case=False, na=False).sum())
            fta = ftm + int(df_eq["accio"].str.contains("Intent fallat de 1", case=False, na=False).sum())
            tov = int(df_eq["accio"].str.contains("Pèrdua", case=False, na=False).sum())
            oreb = int(df_eq["accio"].str.contains("Rebot ofensiu", case=False, na=False).sum())
            dreb = int(df_eq["accio"].str.contains("Rebot defensiu", case=False, na=False).sum())
            oreb_riv = int(df_riv["accio"].str.contains("Rebot ofensiu", case=False, na=False).sum())
            dreb_riv = int(df_riv["accio"].str.contains("Rebot defensiu", case=False, na=False).sum())
            pts = int(df_eq["punts"].sum())
            pts_riv = int(df_riv["punts"].sum())
            poss = core.calc_possessions(df_eq, poss_mode="full")
            poss_riv = core.calc_possessions(df_riv, poss_mode="full")

            a = acum.setdefault(nom_eq, dict(partits=0, fgm2=0, fga2=0, fgm3=0, fga3=0, ftm=0, fta=0,
                                              tov=0, oreb=0, dreb=0, oreb_riv=0, dreb_riv=0,
                                              pts=0, pts_riv=0, poss=0.0, poss_riv=0.0))
            a["partits"] += 1
            a["fgm2"] += fgm2; a["fga2"] += fga2
            a["fgm3"] += fgm3; a["fga3"] += fga3
            a["ftm"] += ftm; a["fta"] += fta
            a["tov"] += tov
            a["oreb"] += oreb; a["dreb"] += dreb
            a["oreb_riv"] += oreb_riv; a["dreb_riv"] += dreb_riv
            a["pts"] += pts; a["pts_riv"] += pts_riv
            a["poss"] += poss; a["poss_riv"] += poss_riv

    rows = []
    for nom_eq, a in acum.items():
        fga_tot = a["fga2"] + a["fga3"]
        fgm_tot = a["fgm2"] + a["fgm3"]
        efg = round((fgm_tot + 0.5 * a["fgm3"]) / fga_tot * 100, 1) if fga_tot > 0 else None
        ts = round(a["pts"] / (2 * (fga_tot + 0.44 * a["fta"])) * 100, 1) if (fga_tot or a["fta"]) else None
        plays = fga_tot + 0.44 * a["fta"] + a["tov"]
        tov_pct = round(a["tov"] / plays * 100, 1) if plays > 0 else None
        or_pct = round(a["oreb"] / (a["oreb"] + a["dreb_riv"]) * 100, 1) if (a["oreb"] + a["dreb_riv"]) > 0 else None
        dr_pct = round(a["dreb"] / (a["dreb"] + a["oreb_riv"]) * 100, 1) if (a["dreb"] + a["oreb_riv"]) > 0 else None
        ft_tci = round(a["fta"] / fga_tot, 2) if fga_tot > 0 else None
        off_rtg = round(a["pts"] / a["poss"] * 100, 1) if a["poss"] > 0 else None
        def_rtg = round(a["pts_riv"] / a["poss_riv"] * 100, 1) if a["poss_riv"] > 0 else None
        net_rtg = round(off_rtg - def_rtg, 1) if (off_rtg is not None and def_rtg is not None) else None
        rows.append({
            "Equip": nom_eq, "Partits": a["partits"], "TS%": ts, "eFG%": efg, "TOV%": tov_pct,
            "OR%": or_pct, "DR%": dr_pct, "FT/TCI": ft_tci,
            "OffRtg": off_rtg, "DefRtg": def_rtg, "NetRtg": net_rtg,
        })
    return pd.DataFrame(rows)


def _ranking_ts_efg(df_sz):
    """TS%/eFG% acumulats per jugadora a partir de shots_zones (té encerts I
    intents; stats_jugador només té encerts, no permet calcular-los)."""
    cols = ["jugador", "equip_nom", "TS%", "eFG%"]
    if df_sz.empty:
        return pd.DataFrame(columns=cols)
    agg = df_sz[df_sz["jugador"] != "__equip__"].groupby(["jugador", "equip_nom"]).agg(
        v1m=("val1_made", "sum"), v1x=("val1_miss", "sum"),
        v2m=("val2_made", "sum"), v2x=("val2_miss", "sum"),
        v3m=("val3_made", "sum"), v3x=("val3_miss", "sum"),
    ).reset_index()
    fga = agg["v2m"] + agg["v2x"] + agg["v3m"] + agg["v3x"]
    fta = agg["v1m"] + agg["v1x"]
    pts = agg["v1m"] + 2 * agg["v2m"] + 3 * agg["v3m"]
    denom_ts = 2 * (fga + 0.44 * fta)
    agg["TS%"] = (pts / denom_ts.replace(0, float("nan")) * 100).round(1)
    agg["eFG%"] = ((agg["v2m"] + 1.5 * agg["v3m"]) / fga.replace(0, float("nan")) * 100).round(1)
    return agg[cols]


def genera_pdf_partit(df_orig, teams, team_names, match_id, nom_a, nom_b, fa, fb):
    """Informe PDF d'un sol partit: Comparació d'equips, Quatre Factors, PPP per
    tipus d'inici, Box Score, Impacte en pista, On/Off, ROT, Parelles, Quintets i Clutch."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=15 * mm)
    elems = [
        Paragraph(f"{nom_a} {fa} – {fb} {nom_b}", TITOL),
        Paragraph(f"Partit {match_id} · Generat {datetime.now().strftime('%d/%m/%Y %H:%M')}", NORMAL),
        Spacer(1, 10),
    ]

    tid_a, tid_b = (teams[0], teams[1]) if len(teams) > 1 else (teams[0] if teams else None, None)

    if len(teams) > 1:
        # ── Comparació d'equips ──────────────────────────────────────────
        ef_cmp = core.calc_eficiencies(df_orig, teams, team_names, poss_mode="full")
        met_a_cmp = core.calc_metriques_partit(df_orig[df_orig["idEquip"] == tid_a], match_id, nom_a, nom_b, poss_mode="full")
        met_b_cmp = core.calc_metriques_partit(df_orig[df_orig["idEquip"] == tid_b], match_id, nom_b, nom_a, poss_mode="full")
        elems.append(Paragraph("Comparació d'equips", SUBTITOL))
        data = [["", nom_a, nom_b]]
        for label, ka, kb in [
            ("Off Rtg", ef_cmp[tid_a]["off_rtg"], ef_cmp[tid_b]["off_rtg"]),
            ("Def Rtg", ef_cmp[tid_a]["def_rtg"], ef_cmp[tid_b]["def_rtg"]),
            ("Net Rtg", ef_cmp[tid_a]["net_rtg"], ef_cmp[tid_b]["net_rtg"]),
            ("TS%", met_a_cmp["TS%"], met_b_cmp["TS%"]),
            ("eFG%", met_a_cmp["eFG%"], met_b_cmp["eFG%"]),
            ("Possessions", met_a_cmp["Possessions"], met_b_cmp["Possessions"]),
        ]:
            data.append([label, ka, kb])
        elems.append(_tbl(data, [40 * mm, 60 * mm, 60 * mm]))

        # ── Quatre Factors ────────────────────────────────────────────────
        ff = cff.calc_four_factors(df_orig, teams, team_names, poss_mode="full")
        if ff:
            elems.append(Paragraph("Quatre Factors", SUBTITOL))
            fa_ff, fb_ff = ff[tid_a], ff[tid_b]
            data = [["Factor", nom_a, nom_b]]
            for k, label in [("eFG%", "eFG%"), ("TOV%", "TOV%"), ("OR%", "OR%"),
                              ("DR%", "DR%"), ("FT_TCI", "FT/TCI")]:
                data.append([label, fa_ff[k], fb_ff[k]])
            data.append(["OER", fa_ff["OER"], fb_ff["OER"]])
            data.append(["DER", fa_ff["DER"], fb_ff["DER"]])
            elems.append(_tbl(data, [60 * mm, 50 * mm, 50 * mm]))

        pts_start = cff.calc_pts_by_start(df_orig, teams, team_names)
        if pts_start:
            elems.append(Paragraph("Cuándo la tuvieron, y cuánto valió (PPP)", SUBTITOL))
            etiquetes = {
                "after_make": "Tras canasta", "off_steal": "Tras robo",
                "off_dreb": "Tras rebote defensivo", "off_deadball_tov": "Tras pérdida balón parado",
            }
            data = [[_hp("Tipus"), _hp(f"{nom_a} PPP"), _hp(f"{nom_a} Poss."),
                     _hp(f"{nom_b} PPP"), _hp(f"{nom_b} Poss.")]]
            for k, label in etiquetes.items():
                da = pts_start.get(tid_a, {}).get(k, {})
                db = pts_start.get(tid_b, {}).get(k, {})
                data.append([label,
                             da.get("ppp") if da.get("ppp") is not None else "—", da.get("poss", 0),
                             db.get("ppp") if db.get("ppp") is not None else "—", db.get("poss", 0)])
            elems.append(_tbl(data, [55 * mm, 25 * mm, 20 * mm, 25 * mm, 20 * mm]))

        elems.append(PageBreak())

        # ── Box Score complet ────────────────────────────────────────────
        df_box = cff.calc_box_score_jugadores(df_orig, teams, team_names)
        if not df_box.empty:
            elems.append(Paragraph("Box Score complet", SUBTITOL))
            elems.append(Paragraph(
                "T2/T3/TL = c/i (convertits/intentats) · TS%/eFG% calculats a partir del box score · "
                "REB = RO+RD · AS = assistències · BR = robatories · TAP = taps · BP = pèrdues · FC = faltes comeses",
                NORMAL))
            elems.append(Spacer(1, 4))
            for eq_id, eq_nom in [(tid_a, nom_a), (tid_b, nom_b)]:
                df_box_eq = df_box[df_box["Equip"] == eq_nom].sort_values("PTS", ascending=False)
                if df_box_eq.empty:
                    continue
                elems.append(Paragraph(eq_nom, ParagraphStyle("EqLabel", parent=NORMAL, textColor=BLAU_FOSC,
                                                                fontSize=10, spaceBefore=6, spaceAfter=3)))
                data = [["Jugadora", "PTS", "T2", "T3", "TL", "TS%", "eFG%", "RO", "RD", "AS", "BR", "TAP", "BP", "FC"]]
                for _, r in df_box_eq.iterrows():
                    tca = r["T2I"] + r["T3I"]
                    tla = r["TLI"]
                    ts = round(r["PTS"] / (2 * (tca + 0.44 * tla)) * 100, 1) if (tca or tla) else None
                    efg = round((r["T2C"] + 1.5 * r["T3C"]) / (tca) * 100, 1) if tca else None
                    data.append([r["Jugadora"], r["PTS"],
                                 f"{r['T2C']}/{r['T2I']}", f"{r['T3C']}/{r['T3I']}", f"{r['TLC']}/{r['TLI']}",
                                 _na(ts), _na(efg), r["RO"], r["RD"], r["AS"], r["BR"], r["TAP"], r["BP"], r["FC"]])
                elems.append(_tbl(data,
                    [30*mm, 11*mm, 13*mm, 13*mm, 13*mm, 11*mm, 11*mm, 9*mm, 9*mm, 9*mm, 9*mm, 9*mm, 9*mm, 9*mm],
                    font_size=7))
                elems.append(Spacer(1, 4))

        # ── Impacte en pista (+/-) ───────────────────────────────────────
        imp_rows = _impacte_en_pista_rows(df_orig, teams, team_names)
        if imp_rows:
            elems.append(Paragraph("Impacte en pista (+/-)", SUBTITOL))
            elems.append(Paragraph("Parcial de l'equip durant els minuts reals que la jugadora és a pista.", NORMAL))
            elems.append(Spacer(1, 4))
            for eq_id, eq_nom in [(tid_a, nom_a), (tid_b, nom_b)]:
                rows_eq = sorted([r for r in imp_rows if r["equip_id"] == eq_id], key=lambda r: -r["+/-"])
                if not rows_eq:
                    continue
                elems.append(Paragraph(eq_nom, ParagraphStyle("EqLabel2", parent=NORMAL, textColor=BLAU_FOSC,
                                                                 fontSize=10, spaceBefore=6, spaceAfter=3)))
                data = [["Jugadora", "MIN", "Pts favor", "Pts contra", "+/-", "Usage%"]]
                for r in rows_eq:
                    data.append([r["Jugadora"], r["MIN"], r["Pts favor"], r["Pts contra"],
                                 _fmt_pm(r["+/-"]), f"{r['Usage%']}%"])
                elems.append(_tbl(data, [45*mm, 18*mm, 26*mm, 26*mm, 18*mm, 22*mm]))
                elems.append(Spacer(1, 4))

        # ── On/Off Rating ─────────────────────────────────────────────────
        oo_rows = _onoff_rows(df_orig, teams, team_names)
        if oo_rows:
            elems.append(Paragraph("On/Off Rating", SUBTITOL))
            elems.append(Paragraph(
                "OER/DER/NetRtg de l'equip quan la jugadora és a pista (on) vs quan no hi és (off). "
                "NET = NetRtg on − NetRtg off.", NORMAL))
            elems.append(Spacer(1, 4))
            for eq_id, eq_nom in [(tid_a, nom_a), (tid_b, nom_b)]:
                rows_eq = sorted([r for r in oo_rows if r["equip_id"] == eq_id], key=lambda r: -r["MIN"])
                if not rows_eq:
                    continue
                elems.append(Paragraph(eq_nom, ParagraphStyle("EqLabel3", parent=NORMAL, textColor=BLAU_FOSC,
                                                                 fontSize=10, spaceBefore=6, spaceAfter=3)))
                data = [["Jugadora", "MIN", "OER on", "OER off", "DER on", "DER off", "NetRtg on", "NetRtg off", "NET"]]
                for r in rows_eq:
                    data.append([r["Jugadora"], r["MIN"], _na(r["OER on"]), _na(r["OER off"]),
                                 _na(r["DER on"]), _na(r["DER off"]), _na(r["NetRtg on"]), _na(r["NetRtg off"]),
                                 _fmt_pm(r["NET"]) if r["NET"] is not None else "—"])
                elems.append(_tbl(data,
                    [32*mm, 13*mm, 16*mm, 16*mm, 16*mm, 16*mm, 18*mm, 18*mm, 14*mm], font_size=7))
                elems.append(Spacer(1, 4))

        elems.append(PageBreak())

        # ── ROT ───────────────────────────────────────────────────────────
        rot = _rot_per_equip(df_orig, teams)
        elems.append(Paragraph("ROT — Índex de gestió de rotacions", SUBTITOL))
        elems.append(Paragraph(
            "ROT = 5·(ρ+1), on ρ = correlació de Pearson entre minuts jugats i +/- per minut. Escala 0-10.", NORMAL))
        elems.append(Spacer(1, 4))
        if rot:
            data = [["Equip", "ROT", "Pearson (ρ)", "p-value", "Jugadores"]]
            for eq_id, eq_nom in [(tid_a, nom_a), (tid_b, nom_b)]:
                r = rot.get(eq_id)
                if not r:
                    continue
                data.append([_bp(eq_nom), f"{r['rot']}/10", f"{r['rho']:+.3f}", f"{r['pval']:.3f}", r["n"]])
            elems.append(_tbl(data, [50*mm, 20*mm, 28*mm, 22*mm, 22*mm]))
        else:
            elems.append(Paragraph("Calen almenys 3 jugadores amb minuts jugats a cada equip.", NORMAL))

        # ── Parelles (+/-) ────────────────────────────────────────────────
        parelles = core.calc_pm_combinacions(df_orig, mode="parelles")
        if parelles:
            intervals_hm = core.get_intervals_jugadores_global(df_orig)
            elems.append(Paragraph("Mapa de calor +/- per parelles", SUBTITOL))
            elems.append(Paragraph(
                "Color de cada casella = +/- conjunt de la parella quan han jugat juntes "
                "(verd = l'equip guanya, vermell = perd). Gris = no han coincidit en pista.", NORMAL))
            elems.append(Spacer(1, 2))
            for eq_id, eq_nom in [(tid_a, nom_a), (tid_b, nom_b)]:
                elems.extend(_heatmap_parelles_elems(parelles, intervals_hm, eq_id, eq_nom))

            elems.append(Paragraph("Parelles — +/- per minut junts", SUBTITOL))
            elems.append(Spacer(1, 2))
            for eq_id, eq_nom in [(tid_a, nom_a), (tid_b, nom_b)]:
                dfp = sorted([p for p in parelles if str(p["equip"]) == str(eq_id)],
                             key=lambda p: -p["pm_min"])[:12]
                if not dfp:
                    continue
                elems.append(Paragraph(eq_nom, ParagraphStyle("EqLabel4", parent=NORMAL, textColor=BLAU_FOSC,
                                                                 fontSize=10, spaceBefore=6, spaceAfter=3)))
                data = [["Parella", "Min junts", "Pts favor", "Pts contra", "+/-", "+/- per min"]]
                for p in dfp:
                    data.append([" + ".join(p["combinacio"]), round(p["minuts"], 1), p["pf"], p["pc"],
                                 _fmt_pm(p["pm"]), _fmt_pm(round(p["pm_min"], 3))])
                elems.append(_tbl(data, [65*mm, 20*mm, 22*mm, 22*mm, 16*mm, 22*mm], font_size=8))
                elems.append(Spacer(1, 4))

        # ── Quintets (+/-) ────────────────────────────────────────────────
        quintets = core.calc_pm_combinacions(df_orig, mode="quintets")
        if quintets:
            elems.append(Paragraph("Quintets — +/-", SUBTITOL))
            elems.append(Spacer(1, 2))
            for eq_id, eq_nom in [(tid_a, nom_a), (tid_b, nom_b)]:
                dfq = sorted([q for q in quintets if str(q["equip"]) == str(eq_id)], key=lambda q: -q["pm"])
                if not dfq:
                    continue
                elems.append(Paragraph(eq_nom, ParagraphStyle("EqLabel5", parent=NORMAL, textColor=BLAU_FOSC,
                                                                 fontSize=10, spaceBefore=6, spaceAfter=3)))
                data = [["Quintet", "Min", "Pts favor", "Pts contra", "+/-", "+/- per min"]]
                for q in dfq:
                    data.append([", ".join(n.split()[0] for n in q["combinacio"]), round(q["minuts"], 1),
                                 q["pf"], q["pc"], _fmt_pm(q["pm"]), _fmt_pm(round(q["pm_min"], 3))])
                elems.append(_tbl(data, [65*mm, 18*mm, 22*mm, 22*mm, 16*mm, 24*mm], font_size=8))
                elems.append(Spacer(1, 4))

        elems.append(PageBreak())

    # ── Clutch ────────────────────────────────────────────────────────────
    clutch = cff.calc_clutch(df_orig, teams, team_names, poss_mode="full")
    elems.append(Paragraph("Clutch", SUBTITOL))
    if clutch:
        elems.append(Paragraph(
            f"{clutch['finestra_min']:.1f} min dins dels últims 5 min amb marge ≤5 punts "
            f"({clutch['n_trams']} tram(s))", NORMAL))
        data = [["Jugadora", "Equip", "Min", "Pts", "TS%", "+/-"]]
        for r in clutch["jugadores"]:
            data.append([r["jugadora"], _bp(r["equip_nom"]), r["minuts"], r["punts"],
                         r["TS%"] if r["TS%"] is not None else "—", r["+/-"]])
        elems.append(_tbl(data, [40 * mm, 45 * mm, 15 * mm, 15 * mm, 18 * mm, 15 * mm]))
    else:
        elems.append(Paragraph("Sense tram clutch en aquest partit (marge >5 punts durant els últims 5 minuts).", NORMAL))

    doc.build(elems)
    buf.seek(0)
    return buf.getvalue()


def genera_pdf_temporada():
    """Informe PDF de tots els partits carregats: llistat de partits + rànquing de jugadores."""
    df_p = core.load_partits_db()
    if df_p.empty:
        return None

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=15 * mm)
    elems = [
        Paragraph("Informe de temporada", TITOL),
        Paragraph(f"{len(df_p)} partits · Generat {datetime.now().strftime('%d/%m/%Y %H:%M')}", NORMAL),
        Spacer(1, 10),
        Paragraph("Partits", SUBTITOL),
    ]

    data = [["Data", "Local", "Pts", "Pts", "Visitant"]]
    for _, p in df_p.sort_values("data_consulta").iterrows():
        data.append([str(p["data_consulta"])[:10], p["nom_a"], p["score_a"], p["score_b"], p["nom_b"]])
    t = Table(data, colWidths=[28 * mm, 45 * mm, 15 * mm, 15 * mm, 45 * mm])
    t.setStyle(_taula_estil())
    elems.append(t)

    # ── Equips — acumulat de temporada (Quatre Factors + TS/eFG/Rtg) ───────
    df_teams_season = _team_season_four_factors(df_p)
    if not df_teams_season.empty:
        elems.append(Paragraph("Equips — acumulat de temporada", SUBTITOL))
        elems.append(Paragraph(
            "Suma de tots els partits carregats abans de dividir (no mitjana de percentatges per "
            "partit). TOV% = pèrdues per possessió · OR%/DR% = rebot ofensiu/defensiu · "
            "FT/TCI = tirs lliures per tir de camp.", NORMAL))
        elems.append(Spacer(1, 4))
        data = [["Equip", "PJ", "TS%", "eFG%", "TOV%", "OR%", "DR%", "FT/TCI", "OffRtg", "DefRtg", "NetRtg"]]
        for _, r in df_teams_season.sort_values("NetRtg", ascending=False).iterrows():
            data.append([_bp(r["Equip"]), r["Partits"], _na(r["TS%"]), _na(r["eFG%"]), _na(r["TOV%"]),
                         _na(r["OR%"]), _na(r["DR%"]), _na(r["FT/TCI"]),
                         _na(r["OffRtg"]), _na(r["DefRtg"]), _fmt_pm(r["NetRtg"])])
        elems.append(_tbl(data, [38*mm, 9*mm, 11*mm, 11*mm, 12*mm, 11*mm, 11*mm, 12*mm, 12*mm, 12*mm, 12*mm],
                           font_size=7))
        elems.append(PageBreak())

    # ── Rànquing de jugadores (complet, amb TS%/eFG%) ───────────────────────
    df_sj = core.load_stats_jugador_db()
    df_sz = core.load_shots_zones_db()
    if not df_sj.empty:
        elems.append(Paragraph("Rànquing de jugadores (top 30 per punts totals)", SUBTITOL))
        agg = df_sj.groupby(["jugador", "equip_nom"]).agg(
            Partits=("match_id", "nunique"), Punts=("punts", "sum"),
            C2=("cistelles_2", "sum"), C3=("cistelles_3", "sum"), TL=("tirs_lliures", "sum"),
        ).reset_index().sort_values("Punts", ascending=False).head(30)
        df_ts_efg = _ranking_ts_efg(df_sz)
        agg = agg.merge(df_ts_efg, on=["jugador", "equip_nom"], how="left")
        data = [["Jugadora", "Equip", "PJ", "Pts", "C2", "C3", "TL", "TS%", "eFG%"]]
        for _, r in agg.iterrows():
            data.append([_bp(r["jugador"]), _bp(r["equip_nom"]), r["Partits"], r["Punts"], r["C2"], r["C3"], r["TL"],
                         _na(r.get("TS%")), _na(r.get("eFG%"))])
        elems.append(_tbl(data, [34*mm, 34*mm, 9*mm, 11*mm, 9*mm, 9*mm, 9*mm, 11*mm, 11*mm], font_size=8))
        elems.append(PageBreak())

    # ── Win Shares de temporada ──────────────────────────────────────────────
    df_ws = core.calc_win_shares_temporada()
    if not df_ws.empty:
        elems.append(Paragraph("Win Shares de temporada", SUBTITOL))
        data = [["Jugadora", "Equip", "PJ", "Min", "Pts", "OWS", "DWS", "WS", "WS/40", "Arquetip"]]
        for _, r in df_ws.sort_values("WS", ascending=False).iterrows():
            data.append([_bp(r["jugador"]), _bp(r["equip"]), r["partits"], r["minuts"], r["punts"],
                         r["OWS"], r["DWS"], r["WS"], r["ws_per40"], _bp(r["Arquetip"])])
        elems.append(_tbl(data, [26*mm, 30*mm, 8*mm, 10*mm, 10*mm, 10*mm, 10*mm, 10*mm, 11*mm, 25*mm],
                           font_size=7))
        elems.append(Spacer(1, 8))

    # ── On/Off Rating agregat ────────────────────────────────────────────────
    res_onoff_agr = core.calc_onoff_agregat(df_p, min_poss_on=150, min_poss_off=150, poss_mode="full")
    if res_onoff_agr:
        df_onoff_agr = pd.DataFrame(res_onoff_agr)
        df_onoff_agr = df_onoff_agr[df_onoff_agr["onoff_agregat"].notna()].sort_values(
            "onoff_agregat", ascending=False)
        if not df_onoff_agr.empty:
            elems.append(Paragraph("On/Off Rating agregat", SUBTITOL))
            elems.append(Paragraph(
                "Suma punts i possessions ON/OFF de tots els partits abans de dividir. "
                "Fiable = mínim 150 possessions ON i 150 OFF.", NORMAL))
            elems.append(Spacer(1, 4))
            data = [["Jugadora", "Equip", "Partits", "Poss ON", "Poss OFF", "NetRtg ON", "NetRtg OFF",
                     "On/Off", "Fiable"]]
            for _, r in df_onoff_agr.iterrows():
                data.append([_bp(r["jugadora"]), _bp(r["equip_nom"]), r["partits"], r["poss_on"], r["poss_off"],
                             _na(r["net_on"]), _na(r["net_off"]), _fmt_pm(r["onoff_agregat"]),
                             "Sí" if r["fiable"] else "No"])
            elems.append(_tbl(data, [30*mm, 30*mm, 12*mm, 14*mm, 14*mm, 15*mm, 15*mm, 12*mm, 12*mm],
                               font_size=7))
            elems.append(PageBreak())

    # ── Usage% vs Pts/40min ──────────────────────────────────────────────────
    if not df_sj.empty:
        col_j_p40 = "jugador" if "jugador" in df_sj.columns else "jugadora"
        rows_p40 = []
        for (jug, eq_nom), grp in df_sj.groupby([col_j_p40, "equip_nom"]):
            min_tot = grp["minuts"].sum() if "minuts" in grp.columns else 0
            if min_tot < 5:
                continue
            pts_tot = grp["punts"].sum()
            usage = grp["usage_rate"].mean() if "usage_rate" in grp.columns else 0
            rows_p40.append({
                "Jugadora": jug, "Equip": eq_nom, "Partits": grp["match_id"].nunique(),
                "Min tot": round(min_tot, 1), "Pts tot": int(pts_tot),
                "Usage%": round(usage, 1), "Pts/40min": round(pts_tot / min_tot * 40, 1),
            })
        if rows_p40:
            elems.append(Paragraph("Usage% vs Pts/40min", SUBTITOL))
            elems.append(Paragraph(
                "Volum ofensiu (Usage%) vs productivitat anotadora normalitzada a 40 minuts, "
                "acumulat de tota la temporada.", NORMAL))
            elems.append(Spacer(1, 4))
            data = [["Jugadora", "Equip", "Partits", "Min tot", "Pts tot", "Usage%", "Pts/40min"]]
            for r in sorted(rows_p40, key=lambda r: -r["Pts/40min"]):
                data.append([_bp(r["Jugadora"]), _bp(r["Equip"]), r["Partits"], r["Min tot"], r["Pts tot"],
                             f"{r['Usage%']}%", r["Pts/40min"]])
            elems.append(_tbl(data, [34*mm, 34*mm, 13*mm, 16*mm, 16*mm, 16*mm, 18*mm], font_size=8))

    doc.build(elems)
    buf.seek(0)
    return buf.getvalue()
