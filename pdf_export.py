# -*- coding: utf-8 -*-
"""Generació de PDFs (informe de partit i de temporada) amb reportlab.

Reaprofita analitica_core.py i core_four_factors.py — aquest mòdul no calcula
res de nou, només maqueta el que ja existeix en un PDF descarregable.
"""
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

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


def _taula_estil():
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLAU),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B5D4F4")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRIS_CLAR]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])


def genera_pdf_partit(df_orig, teams, team_names, match_id, nom_a, nom_b, fa, fb):
    """Informe PDF d'un sol partit: Quatre Factors, PPP per tipus d'inici, i Clutch."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=15 * mm)
    elems = [
        Paragraph(f"{nom_a} {fa} – {fb} {nom_b}", TITOL),
        Paragraph(f"Partit {match_id} · Generat {datetime.now().strftime('%d/%m/%Y %H:%M')}", NORMAL),
        Spacer(1, 10),
    ]

    if len(teams) > 1:
        ff = cff.calc_four_factors(df_orig, teams, team_names, poss_mode="full")
        if ff:
            elems.append(Paragraph("Quatre Factors", SUBTITOL))
            fa_ff, fb_ff = ff[teams[0]], ff[teams[1]]
            data = [["Factor", nom_a, nom_b]]
            for k, label in [("eFG%", "eFG%"), ("TOV%", "TOV%"), ("OR%", "OR%"),
                              ("DR%", "DR%"), ("FT_TCI", "FT/TCI")]:
                data.append([label, fa_ff[k], fb_ff[k]])
            data.append(["OER", fa_ff["OER"], fb_ff["OER"]])
            data.append(["DER", fa_ff["DER"], fb_ff["DER"]])
            t = Table(data, colWidths=[60 * mm, 50 * mm, 50 * mm])
            t.setStyle(_taula_estil())
            elems.append(t)

        pts_start = cff.calc_pts_by_start(df_orig, teams, team_names)
        if pts_start:
            elems.append(Paragraph("Cuándo la tuvieron, y cuánto valió (PPP)", SUBTITOL))
            etiquetes = {
                "after_make": "Tras canasta", "off_steal": "Tras robo",
                "off_dreb": "Tras rebote defensivo", "off_deadball_tov": "Tras pérdida balón parado",
            }
            data = [["Tipus", f"{nom_a} PPP", f"{nom_a} Poss.", f"{nom_b} PPP", f"{nom_b} Poss."]]
            for k, label in etiquetes.items():
                da = pts_start.get(teams[0], {}).get(k, {})
                db = pts_start.get(teams[1], {}).get(k, {})
                data.append([label,
                             da.get("ppp") if da.get("ppp") is not None else "—", da.get("poss", 0),
                             db.get("ppp") if db.get("ppp") is not None else "—", db.get("poss", 0)])
            t = Table(data, colWidths=[55 * mm, 25 * mm, 20 * mm, 25 * mm, 20 * mm])
            t.setStyle(_taula_estil())
            elems.append(t)

    clutch = cff.calc_clutch(df_orig, teams, team_names, poss_mode="full")
    elems.append(Paragraph("Clutch", SUBTITOL))
    if clutch:
        elems.append(Paragraph(
            f"{clutch['finestra_min']:.1f} min dins dels últims 5 min amb marge ≤5 punts "
            f"({clutch['n_trams']} tram(s))", NORMAL))
        data = [["Jugadora", "Equip", "Min", "Pts", "TS%", "+/-"]]
        for r in clutch["jugadores"]:
            data.append([r["jugadora"], r["equip_nom"], r["minuts"], r["punts"],
                         r["TS%"] if r["TS%"] is not None else "—", r["+/-"]])
        t = Table(data, colWidths=[45 * mm, 35 * mm, 18 * mm, 18 * mm, 18 * mm, 18 * mm])
        t.setStyle(_taula_estil())
        elems.append(t)
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

    df_sj = core.load_stats_jugador_db()
    if not df_sj.empty:
        elems.append(Paragraph("Rànquing de jugadores (top 20 per punts totals)", SUBTITOL))
        agg = df_sj.groupby(["jugador", "equip_nom"]).agg(
            Partits=("match_id", "nunique"), Punts=("punts", "sum"),
            C2=("cistelles_2", "sum"), C3=("cistelles_3", "sum"), TL=("tirs_lliures", "sum"),
        ).reset_index().sort_values("Punts", ascending=False).head(20)
        data = [["Jugadora", "Equip", "PJ", "Pts", "C2", "C3", "TL"]]
        for _, r in agg.iterrows():
            data.append([r["jugador"], r["equip_nom"], r["Partits"], r["Punts"], r["C2"], r["C3"], r["TL"]])
        t = Table(data, colWidths=[45 * mm, 35 * mm, 12 * mm, 15 * mm, 12 * mm, 12 * mm, 12 * mm])
        t.setStyle(_taula_estil())
        elems.append(t)

    doc.build(elems)
    buf.seek(0)
    return buf.getvalue()
