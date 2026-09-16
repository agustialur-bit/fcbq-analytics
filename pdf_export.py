# -*- coding: utf-8 -*-
"""Generació de PDFs (informe de partit i de temporada) amb reportlab.

Reaprofita analitica_core.py i core_four_factors.py — aquest mòdul no calcula
res de nou (excepte un parell d'agregacions petites que no existien com a
funció reutilitzable — vegeu _impacte_en_pista_rows / _rot_per_equip / etc.
més avall), només maqueta el que ja existeix en un PDF descarregable.
"""
import io
import math
from datetime import datetime

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, KeepTogether
from reportlab.graphics.shapes import Drawing, Rect, String, Line, PolyLine, Circle

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
    noms_curts = [j.split()[1] if len(j.split()) > 1 else j for j in jugs]

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


def _rotacions_drawing(df_orig, teams, eq_id, eq_nom):
    """Gràfic de rotacions (Gantt): una barra per tram de joc de cada jugadora,
    amb el parcial ±de l'equip superposat com a línia discontínua — mateix
    gràfic que 'Gràfic de rotacions — qui juga cada minut' en pantalla,
    redibuixat amb reportlab.graphics (Plotly no es pot incrustar al PDF)."""
    intervals = core.get_intervals_jugadores_global(df_orig)
    jugs_eq = {j: ivs for j, ivs in intervals.items() if any(str(ei) == str(eq_id) for _, _, ei in ivs)}
    if not jugs_eq:
        return None
    jugs_sorted = sorted(jugs_eq.items(), key=lambda x: min(i[0] for i in x[1]))
    n = len(jugs_sorted)

    MINS_TOTAL = max(float(df_orig["quart"].max()) * 10 if not df_orig.empty else 40, 40)

    sdf = core.score_evo(df_orig)
    t_pts, diff = [], []
    if not sdf.empty:
        sdf = sdf.copy()
        sdf["t_min"] = sdf.apply(_t_abs, axis=1)
        parcial_eq = sdf["scoreA"] if str(eq_id) == str(teams[0]) else sdf["scoreB"]
        parcial_riv = sdf["scoreB"] if str(eq_id) == str(teams[0]) else sdf["scoreA"]
        diff = (parcial_eq - parcial_riv).tolist()
        t_pts = sdf["t_min"].tolist()

    LABEL_W, PLOT_W, RIGHT_M = 36 * mm, 105 * mm, 14 * mm
    ROW_H, TOP_M, BOT_M = 5.6 * mm, 5 * mm, 12 * mm
    W = LABEL_W + PLOT_W + RIGHT_M
    H = TOP_M + n * ROW_H + BOT_M

    d = Drawing(W, H)

    def x_of(t):
        return LABEL_W + (min(t, MINS_TOTAL) / MINS_TOTAL) * PLOT_W

    def row_top(i):
        return H - TOP_M - i * ROW_H

    GRIS = colors.HexColor("#9ca3af")
    GRIS_CLAR2 = colors.HexColor("#e2e4e8")
    FOSC = colors.HexColor("#374151")

    for q in range(1, 5):
        xq = x_of(q * 10)
        if q < 4:
            d.add(Line(xq, BOT_M, xq, H - TOP_M, strokeColor=GRIS_CLAR2, strokeDashArray=[2, 2], strokeWidth=0.6))
            d.add(String(xq, H - TOP_M + 1.5, f"Fi Q{q}", fontSize=6, fillColor=GRIS, textAnchor="middle"))
        else:
            d.add(String(xq, H - TOP_M + 1.5, f"Fi Q{q}", fontSize=6, fillColor=GRIS, textAnchor="end"))

    for i, (jug, ivs) in enumerate(jugs_sorted):
        ytop = row_top(i)
        d.add(String(LABEL_W - 3, ytop - ROW_H * 0.65, jug, fontSize=6.3, fillColor=FOSC, textAnchor="end"))
        for (t_ini, t_fi, ei) in ivs:
            if str(ei) != str(eq_id):
                continue
            x0, x1 = x_of(t_ini), x_of(t_fi)
            d.add(Rect(x0, ytop - ROW_H + 1, max(x1 - x0, 0.5), ROW_H - 2,
                        fillColor=BLAU, strokeColor=colors.white, strokeWidth=0.4))

    tick = 0
    while tick <= MINS_TOTAL + 0.01:
        xt = x_of(tick)
        d.add(Line(xt, BOT_M, xt, BOT_M - 1.5, strokeColor=GRIS, strokeWidth=0.5))
        d.add(String(xt, BOT_M - 8, str(int(tick)), fontSize=6, fillColor=GRIS, textAnchor="middle"))
        tick += 10
    d.add(String(LABEL_W + PLOT_W / 2, 2, "Minut de joc", fontSize=6.5, fillColor=FOSC, textAnchor="middle"))

    if diff:
        dmin, dmax = min(diff), max(diff)
        if dmin == dmax:
            dmin -= 1
            dmax += 1
        pad = (dmax - dmin) * 0.08
        dmin -= pad
        dmax += pad
        plot_bottom, plot_top = BOT_M, H - TOP_M

        def y_of_diff(v):
            return plot_bottom + (v - dmin) / (dmax - dmin) * (plot_top - plot_bottom)

        pts = []
        for t, v in zip(t_pts, diff):
            pts += [x_of(t), y_of_diff(v)]
        if len(pts) >= 4:
            d.add(PolyLine(pts, strokeColor=FOSC, strokeWidth=1, strokeDashArray=[2, 2]))

        y0 = y_of_diff(0)
        if plot_bottom <= y0 <= plot_top:
            d.add(Line(LABEL_W, y0, LABEL_W + PLOT_W, y0, strokeColor=GRIS_CLAR2, strokeWidth=0.5))

        for val in sorted({round(dmin + pad), 0, round(dmax - pad)}):
            if dmin <= val <= dmax:
                d.add(String(LABEL_W + PLOT_W + 3, y_of_diff(val) - 2, f"{val:+d}" if val else "0",
                              fontSize=6, fillColor=GRIS))
        d.add(String(LABEL_W + PLOT_W + 3, H - TOP_M - 7, "Parcial ±", fontSize=6, fillColor=FOSC))

    return d


def _rendiment_quart_rows(df_orig, teams):
    """Possessions, ritme, TS% i Off Rtg per quart i equip — mateix càlcul que
    '📊 Rendiment per quart' en pantalla."""
    rows = []
    if not teams or df_orig.empty:
        return rows
    for q in sorted(df_orig["quart"].unique()):
        df_q = df_orig[df_orig["quart"] == q]
        for tid in teams[:2]:
            df_eq_q = df_q[df_q["idEquip"].astype(str) == str(tid)]
            tc_q = int(df_eq_q["accio"].str.contains(core.TC_INT_PAT, case=False, na=False).sum())
            tl_q = int(df_eq_q["accio"].str.contains(core.TL_INT_PAT, case=False, na=False).sum())
            poss_q = tc_q + 0.44 * tl_q
            pts_q = int(df_eq_q["punts"].sum())
            ts_q = round(pts_q / (2 * poss_q) * 100, 1) if poss_q > 0 else 0.0
            off_rtg_q = round(pts_q / poss_q * 100, 1) if poss_q > 0 else 0.0
            ritme_q = round(poss_q / 10, 2)
            rows.append({"quart": int(q), "equip_id": str(tid), "poss": round(poss_q, 1),
                         "pts": pts_q, "ts": ts_q, "off_rtg": off_rtg_q, "ritme": ritme_q})
    return rows


def _usage_pts40_drawing(rows):
    """Bombolles Usage% vs Pts/40min (mida = minuts totals) per un equip —
    mateix gràfic que 'Usage% vs Pts/40min' en pantalla, redibuixat amb
    reportlab.graphics perquè es pugui incrustar al PDF."""
    if not rows:
        return None

    xs = [r["Usage%"] for r in rows]
    ys = [r["Pts/40min"] for r in rows]
    mins = [max(r["Min tot"], 1) for r in rows]
    mitj_x, mitj_y = sum(xs) / len(xs), sum(ys) / len(ys)

    x_lo, x_hi = min(xs), max(xs)
    y_lo, y_hi = min(ys), max(ys)
    x_pad = (x_hi - x_lo) * 0.15 or 5
    y_pad = (y_hi - y_lo) * 0.15 or 5
    x_lo -= x_pad; x_hi += x_pad
    y_lo -= y_pad; y_hi += y_pad

    PLOT_W, PLOT_H = 125 * mm, 80 * mm
    L_M, B_M, T_M, R_M = 12 * mm, 12 * mm, 4 * mm, 4 * mm
    W = L_M + PLOT_W + R_M
    H = B_M + PLOT_H + T_M

    d = Drawing(W, H)

    def x_of(v):
        return L_M + (v - x_lo) / (x_hi - x_lo) * PLOT_W

    def y_of(v):
        return B_M + (v - y_lo) / (y_hi - y_lo) * PLOT_H

    GRIS = colors.HexColor("#9ca3af")
    FOSC = colors.HexColor("#374151")
    GRIS_CLAR2 = colors.HexColor("#e2e4e8")

    d.add(Rect(L_M, B_M, PLOT_W, PLOT_H, fillColor=colors.HexColor("#f9fafb"),
                strokeColor=GRIS_CLAR2, strokeWidth=0.6))

    d.add(Line(x_of(mitj_x), B_M, x_of(mitj_x), B_M + PLOT_H, strokeColor=GRIS_CLAR2,
                strokeDashArray=[2, 2], strokeWidth=0.6))
    d.add(Line(L_M, y_of(mitj_y), L_M + PLOT_W, y_of(mitj_y), strokeColor=GRIS_CLAR2,
                strokeDashArray=[2, 2], strokeWidth=0.6))

    max_min = max(mins)
    for r, x, y, m in zip(rows, xs, ys, mins):
        radius = 1.3 * mm + (m / max_min) * 2.6 * mm
        cx, cy = x_of(x), y_of(y)
        d.add(Circle(cx, cy, radius, fillColor=BLAU, strokeColor=colors.white, strokeWidth=0.6,
                      fillOpacity=0.85))
        nom_curt = r["Jugadora"].split()[1] if len(r["Jugadora"].split()) > 1 else r["Jugadora"]
        d.add(String(cx, cy + radius + 2, nom_curt, fontSize=6, fillColor=FOSC, textAnchor="middle"))

    # eixos: ticks arrodonits
    for xt in _axis_ticks(x_lo + x_pad, x_hi - x_pad):
        xp = x_of(xt)
        if L_M <= xp <= L_M + PLOT_W:
            d.add(Line(xp, B_M, xp, B_M - 1.5, strokeColor=GRIS, strokeWidth=0.5))
            d.add(String(xp, B_M - 8, f"{xt:g}%", fontSize=6, fillColor=GRIS, textAnchor="middle"))
    for yt in _axis_ticks(y_lo + y_pad, y_hi - y_pad):
        yp = y_of(yt)
        if B_M <= yp <= B_M + PLOT_H:
            d.add(Line(L_M, yp, L_M - 1.5, yp, strokeColor=GRIS, strokeWidth=0.5))
            d.add(String(L_M - 3, yp - 2, f"{yt:g}", fontSize=6, fillColor=GRIS, textAnchor="end"))

    d.add(String(L_M + PLOT_W / 2, 2, "Usage%", fontSize=6.5, fillColor=FOSC, textAnchor="middle"))
    d.add(String(3, B_M + PLOT_H / 2, "Pts/40min", fontSize=6.5, fillColor=FOSC, textAnchor="middle",
                  transform=[0, 1, -1, 0, 3, B_M + PLOT_H / 2]))

    return d


def _axis_ticks(lo, hi, n=5):
    """Marques d'eix arrodonides i "boniques" entre lo i hi (aprox n marques)."""
    if hi <= lo:
        return [lo]
    span = hi - lo
    raw_step = span / max(n - 1, 1)
    mag = 10 ** (len(str(int(raw_step))) - 1) if raw_step >= 1 else 1
    for mult in (1, 2, 2.5, 5, 10):
        step = mult * mag
        if step >= raw_step:
            break
    start = round(lo / step) * step
    ticks = []
    v = start
    while v <= hi + step * 0.5:
        if v >= lo - step * 0.5:
            ticks.append(round(v, 2))
        v += step
    return ticks or [lo, hi]


def _arc_polyline_pts(cx, cy, r, a0, a1, n, scale):
    """Punts (llista plana x,y,x,y...) d'un arc de radi r centrat a (cx,cy),
    escalats per `scale` (punts per metre) — versió reportlab.graphics de
    _arc_path_m() (app_lf2.py, que fa servir Plotly)."""
    pts = []
    for i in range(n):
        t = a0 + (a1 - a0) * i / (n - 1)
        pts += [(cx + r * math.cos(t)) * scale, (cy + r * math.sin(t)) * scale]
    return pts


def _court_shapes(scale):
    """Formes (reportlab.graphics) d'un mig camp FIBA (28x15m real, aquí
    0-14m de llarg des del mig camp fins la línia de fons, 0-15m d'ample),
    escalades per `scale` (punts per metre) — versió reportlab.graphics de
    _mig_camp_shapes() (app_lf2.py, que fa servir Plotly)."""
    LINE = colors.HexColor("#cbd5e1")
    bx, by = 12.425, 7.5
    shapes = [
        Rect(0, 0, 14 * scale, 15 * scale, fillColor=None, strokeColor=LINE, strokeWidth=0.6),
        Rect(8.2 * scale, (by - 2.45) * scale, (14 - 8.2) * scale, 4.9 * scale,
             fillColor=None, strokeColor=LINE, strokeWidth=0.6),
        PolyLine(_arc_polyline_pts(8.2, by, 1.8, 0, 2 * math.pi, 32, scale), strokeColor=LINE, strokeWidth=0.6),
        Circle(bx * scale, by * scale, 0.225 * scale, fillColor=None,
               strokeColor=colors.HexColor("#f97316"), strokeWidth=1.2),
        Line(12.8 * scale, (by - 0.9) * scale, 12.8 * scale, (by + 0.9) * scale, strokeColor=LINE, strokeWidth=0.6),
        PolyLine(_arc_polyline_pts(bx, by, 1.25, -math.pi / 2, -3 * math.pi / 2, 20, scale),
                 strokeColor=LINE, strokeWidth=0.6),
        Line(14 * scale, (by - 1.25) * scale, bx * scale, (by - 1.25) * scale, strokeColor=LINE, strokeWidth=0.6),
        Line(14 * scale, (by + 1.25) * scale, bx * scale, (by + 1.25) * scale, strokeColor=LINE, strokeWidth=0.6),
    ]
    R3, corner_y = 6.75, 0.9
    dx_c = math.sqrt(max(R3 ** 2 - (by - corner_y) ** 2, 0))
    theta_low = math.atan2(-(by - corner_y), dx_c)
    theta_high = math.atan2(by - corner_y, dx_c) - 2 * math.pi
    shapes += [
        PolyLine(_arc_polyline_pts(bx, by, R3, theta_low, theta_high, 48, scale), strokeColor=LINE, strokeWidth=0.6),
        Line(14 * scale, corner_y * scale, (bx + dx_c) * scale, corner_y * scale, strokeColor=LINE, strokeWidth=0.6),
        Line(14 * scale, (15 - corner_y) * scale, (bx + dx_c) * scale, (15 - corner_y) * scale,
             strokeColor=LINE, strokeWidth=0.6),
    ]
    return shapes


def _shot_map_drawing(df_sub, scale_mm=5.5):
    """Mig camp amb un punt per tir (verd=encertat, vermell=fallat). df_sub ha
    de tenir columnes x_m,y_m (metres, ja normalitzades a una sola cistella) i
    fet (0/1) — vegeu _prep_tirs()."""
    scale = scale_mm * mm
    d = Drawing(14 * scale, 15 * scale)
    for shp in _court_shapes(scale):
        d.add(shp)
    r_punt = max(0.9, min(1.3, scale_mm * 0.22)) * mm
    for _, row in df_sub.iterrows():
        color = colors.HexColor("#16a34a") if row["fet"] else colors.HexColor("#dc2626")
        d.add(Circle(row["x_m"] * scale, row["y_m"] * scale, r_punt,
                      fillColor=color, strokeColor=colors.white, strokeWidth=0.35, fillOpacity=0.85))
    return d


def _prep_tirs(df_tirs):
    """Normalitza les coordenades de tirs_fcbq (feb.es, pista sencera 0-100)
    a metres sobre una sola cistella — mateixa transformació que el Mapa de
    Tir en pantalla (app_lf2.py)."""
    dfp = df_tirs.copy()
    dfp["jugador"] = dfp["jugador"].fillna("").replace("", "Sense identificar")
    mirall = dfp["x"] < 50
    dfp.loc[mirall, "x"] = 100 - dfp.loc[mirall, "x"]
    dfp["x_m"] = (dfp["x"] - 50) / 50 * 14.0
    dfp["y_m"] = dfp["y"] / 100 * 15.0
    return dfp


def genera_pdf_mapa_tir(df_tirs, match_id, nom_a, nom_b):
    """Informe PDF només del Mapa de Tir: un mig camp amb tots els tirs per
    equip, seguit d'una graella d'un mig camp petit per jugadora."""
    if df_tirs.empty:
        return None

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=15 * mm)
    elems = [
        Paragraph("Mapa de tir", TITOL),
        Paragraph(f"Partit {match_id} · Generat {datetime.now().strftime('%d/%m/%Y %H:%M')}", NORMAL),
        Spacer(1, 10),
    ]

    dfp = _prep_tirs(df_tirs)
    nom_jug_style = ParagraphStyle("NomJugMapa", parent=NORMAL, fontSize=8, textColor=BLAU_FOSC, alignment=1)
    tirs_jug_style = ParagraphStyle("TirsJugMapa", parent=NORMAL, fontSize=7.5, textColor=colors.HexColor("#6b7280"),
                                     alignment=1, spaceBefore=2)

    equips_amb_tirs = [n for n in [nom_a, nom_b] if not dfp[dfp["equip_nom"] == n].empty]
    for idx_eq, eq_nom in enumerate(equips_amb_tirs):
        d_eq = dfp[dfp["equip_nom"] == eq_nom]
        elems.append(Paragraph(eq_nom, SUBTITOL))
        tot = len(d_eq)
        fets = int(d_eq["fet"].sum())
        elems.append(Paragraph(f"{tot} tirs · {fets} encertats ({round(fets / tot * 100, 1) if tot else 0}%)",
                                NORMAL))
        elems.append(Spacer(1, 4))
        elems.append(_shot_map_drawing(d_eq, scale_mm=6.0))
        elems.append(Spacer(1, 8))

        jugadores = sorted(j for j in d_eq["jugador"].unique() if j != "Sense identificar")
        if jugadores:
            elems.append(Paragraph(f"Per jugadora — {eq_nom}", ParagraphStyle(
                f"PerJugMapa_{idx_eq}", parent=NORMAL, textColor=BLAU_FOSC, fontSize=10,
                spaceBefore=4, spaceAfter=4)))
            files = []
            fila = []
            for jug in jugadores:
                d_j = d_eq[d_eq["jugador"] == jug]
                tot_j = len(d_j)
                fets_j = int(d_j["fet"].sum())
                fila.append([
                    Paragraph(jug, nom_jug_style),
                    _shot_map_drawing(d_j, scale_mm=2.6),
                    Paragraph(f"{fets_j}/{tot_j} ({round(fets_j / tot_j * 100, 1) if tot_j else 0}%)",
                              tirs_jug_style),
                ])
                if len(fila) == 3:
                    files.append(fila)
                    fila = []
            if fila:
                fila += [""] * (3 - len(fila))
                files.append(fila)
            t_grid = Table(files, colWidths=[52 * mm] * 3)
            t_grid.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            elems.append(t_grid)

        if idx_eq < len(equips_amb_tirs) - 1:
            elems.append(PageBreak())

    doc.build(elems)
    buf.seek(0)
    return buf.getvalue()


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
            ast = int(df_eq["accio"].str.contains("Assistència", case=False, na=False).sum())
            oreb = int(df_eq["accio"].str.contains("Rebot ofensiu", case=False, na=False).sum())
            dreb = int(df_eq["accio"].str.contains("Rebot defensiu", case=False, na=False).sum())
            oreb_riv = int(df_riv["accio"].str.contains("Rebot ofensiu", case=False, na=False).sum())
            dreb_riv = int(df_riv["accio"].str.contains("Rebot defensiu", case=False, na=False).sum())
            pts = int(df_eq["punts"].sum())
            pts_riv = int(df_riv["punts"].sum())
            poss = core.calc_possessions(df_eq, poss_mode="full")
            poss_riv = core.calc_possessions(df_riv, poss_mode="full")

            a = acum.setdefault(nom_eq, dict(partits=0, fgm2=0, fga2=0, fgm3=0, fga3=0, ftm=0, fta=0,
                                              tov=0, ast=0, oreb=0, dreb=0, oreb_riv=0, dreb_riv=0,
                                              pts=0, pts_riv=0, poss=0.0, poss_riv=0.0))
            a["partits"] += 1
            a["fgm2"] += fgm2; a["fga2"] += fga2
            a["fgm3"] += fgm3; a["fga3"] += fga3
            a["ftm"] += ftm; a["fta"] += fta
            a["tov"] += tov; a["ast"] += ast
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
            "Assistències/partit": round(a["ast"] / a["partits"], 1) if a["partits"] else None,
            "Rebots/partit": round((a["oreb"] + a["dreb"]) / a["partits"], 1) if a["partits"] else None,
            "Pèrdues/partit": round(a["tov"] / a["partits"], 1) if a["partits"] else None,
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
            elems.append(Paragraph("Quan l'han tinguda, i quant ha valgut (PPP)", SUBTITOL))
            etiquetes = {
                "after_make": "Després de cistella", "off_steal": "Després de robatori",
                "off_dreb": "Després de rebot defensiu", "off_deadball_tov": "Després de pèrdua a pilota aturada",
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

        # ── Rendiment per quart ──────────────────────────────────────────
        rq = _rendiment_quart_rows(df_orig, teams)
        if rq:
            quart_elems = [
                Paragraph("Rendiment per quart", SUBTITOL),
                Paragraph(
                    "Off Rtg = pts/100 poss · TS% = pts/(2×poss)×100 · Ritme = poss/min (quarts de 10 min).", NORMAL),
                Spacer(1, 3),
            ]
            header1 = [_hp("Quart"), _hp(nom_a), "", "", "", "", _hp(nom_b), "", "", "", ""]
            header2 = ["", _hp("Poss"), _hp("Ritme"), _hp("TS%"), _hp("OffRtg"), _hp("Pts"),
                       _hp("Pts"), _hp("OffRtg"), _hp("TS%"), _hp("Ritme"), _hp("Poss")]
            data = [header1, header2]
            style_cmds = [
                ("SPAN", (0, 0), (0, 1)), ("SPAN", (1, 0), (5, 0)), ("SPAN", (6, 0), (10, 0)),
                ("BACKGROUND", (0, 0), (-1, 1), BLAU),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B5D4F4")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
            quarts_uniq = sorted({r["quart"] for r in rq})
            for q_val in quarts_uniq:
                ra = next((r for r in rq if r["quart"] == q_val and r["equip_id"] == str(tid_a)), None)
                rb = next((r for r in rq if r["quart"] == q_val and r["equip_id"] == str(tid_b)), None)
                if not ra or not rb:
                    continue
                row_i = len(data)
                data.append([f"Q{q_val}", ra["poss"], ra["ritme"], ra["ts"], ra["off_rtg"], ra["pts"],
                             rb["pts"], rb["off_rtg"], rb["ts"], rb["ritme"], rb["poss"]])
                if ra["pts"] > rb["pts"]:
                    style_cmds.append(("BACKGROUND", (5, row_i), (5, row_i), colors.HexColor("#D5F5E3")))
                elif rb["pts"] > ra["pts"]:
                    style_cmds.append(("BACKGROUND", (6, row_i), (6, row_i), colors.HexColor("#D5F5E3")))
                else:
                    style_cmds.append(("BACKGROUND", (5, row_i), (6, row_i), colors.HexColor("#FFF3CD")))
            t_q = Table(data, colWidths=[10 * mm] + [12 * mm] * 10)
            t_q.setStyle(TableStyle(style_cmds))
            quart_elems.append(t_q)
            elems.append(KeepTogether(quart_elems))

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

        # ── Gràfic de rotacions ──────────────────────────────────────────
        elems.append(PageBreak())
        elems.append(Paragraph("Gràfic de rotacions — qui juga cada minut", SUBTITOL))
        elems.append(Paragraph(
            "Cada barra és un tram de joc d'una jugadora. La línia discontínua és el parcial ± de l'equip.", NORMAL))
        elems.append(Spacer(1, 4))
        for eq_id, eq_nom in [(tid_a, nom_a), (tid_b, nom_b)]:
            d_rot = _rotacions_drawing(df_orig, teams, eq_id, eq_nom)
            if d_rot is None:
                continue
            elems.append(Paragraph(eq_nom, ParagraphStyle(f"EqLabelRot_{eq_id}", parent=NORMAL, textColor=BLAU_FOSC,
                                                             fontSize=10, spaceBefore=6, spaceAfter=3)))
            elems.append(d_rot)
            elems.append(Spacer(1, 6))

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

        elems.append(Paragraph("Assistències, rebots i pèrdues per partit", SUBTITOL))
        data2 = [["Equip", "PJ", "Assistències/partit", "Rebots/partit", "Pèrdues/partit"]]
        for _, r in df_teams_season.sort_values("NetRtg", ascending=False).iterrows():
            data2.append([_bp(r["Equip"]), r["Partits"], _na(r["Assistències/partit"]),
                          _na(r["Rebots/partit"]), _na(r["Pèrdues/partit"])])
        elems.append(_tbl(data2, [50*mm, 15*mm, 35*mm, 30*mm, 30*mm], font_size=8))
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
                "acumulat de tota la temporada. Mida de la bombolla = minuts totals jugats.", NORMAL))
            elems.append(Spacer(1, 4))
            for eq_nom_p40 in sorted({r["Equip"] for r in rows_p40}):
                rows_eq_p40 = [r for r in rows_p40 if r["Equip"] == eq_nom_p40]
                d_p40 = _usage_pts40_drawing(rows_eq_p40)
                if d_p40 is None:
                    continue
                elems.append(Paragraph(eq_nom_p40, ParagraphStyle(f"EqLabelP40_{eq_nom_p40}", parent=NORMAL,
                                                                     textColor=BLAU_FOSC, fontSize=10,
                                                                     spaceBefore=6, spaceAfter=3)))
                elems.append(d_p40)
                elems.append(Spacer(1, 4))
            data = [["Jugadora", "Equip", "Partits", "Min tot", "Pts tot", "Usage%", "Pts/40min"]]
            for r in sorted(rows_p40, key=lambda r: -r["Pts/40min"]):
                data.append([_bp(r["Jugadora"]), _bp(r["Equip"]), r["Partits"], r["Min tot"], r["Pts tot"],
                             f"{r['Usage%']}%", r["Pts/40min"]])
            elems.append(_tbl(data, [34*mm, 34*mm, 13*mm, 16*mm, 16*mm, 16*mm, 18*mm], font_size=8))

    doc.build(elems)
    buf.seek(0)
    return buf.getvalue()
