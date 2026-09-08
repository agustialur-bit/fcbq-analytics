# -*- coding: utf-8 -*-
"""Mòdul complementari a analitica_core.py: Quatre Factors de Dean Oliver i
estadístiques Clutch, inspirats en els informes de Lens Stats.

Requereix que df_orig tingui els literals "Rebot ofensiu", "Rebot defensiu" i
"Pèrdua" a la columna accio — avui només els emet el normalitzador de feb.es
(app_lf2.py), no l'extracció de la FCBQ. Per això calc_four_factors només té
sentit amb poss_mode="full"; amb dades FCBQ (que no tenen aquests literals)
TOV% i OR%/DR% sortirien a 0 i no s'han de fer servir.

Importa's com: import analitica_core as core; import core_four_factors as cff
"""
import pandas as pd
import analitica_core as core


# ══════════════════════════════════════════════════
# QUATRE FACTORS (Dean Oliver)
# ══════════════════════════════════════════════════
def calc_four_factors(df_orig, teams, team_names, poss_mode="full"):
    """Retorna, per cada equip, els Quatre Factors + el que van produir
    (mateixa forma que la secció 'CUATRO FACTORES' del PDF Lens Stats):
    eFG%, TOV%, OR%, FT/TCI (ràtio, no %), i OER/DER/DR%/REB%.
    """
    if len(teams) < 2:
        return {}

    result = {}
    for i, tid in enumerate(teams[:2]):
        rival_id = teams[1 - i]
        df_eq = df_orig[df_orig["idEquip"] == tid]
        df_riv = df_orig[df_orig["idEquip"] == rival_id]

        fgm = int(df_eq["accio"].str.contains("Cistella de 2|Cistella de 3", case=False, na=False).sum())
        fg3m = int(df_eq["accio"].str.contains("Cistella de 3", case=False, na=False).sum())
        fga = int(df_eq["accio"].str.contains(core.TC_INT_PAT, case=False, na=False).sum())
        fta = int(df_eq["accio"].str.contains(core.TL_INT_PAT, case=False, na=False).sum())
        tov = int(df_eq["accio"].str.contains("Pèrdua", case=False, na=False).sum())
        oreb = int(df_eq["accio"].str.contains("Rebot ofensiu", case=False, na=False).sum())
        dreb = int(df_eq["accio"].str.contains("Rebot defensiu", case=False, na=False).sum())
        oreb_riv = int(df_riv["accio"].str.contains("Rebot ofensiu", case=False, na=False).sum())
        dreb_riv = int(df_riv["accio"].str.contains("Rebot defensiu", case=False, na=False).sum())

        efg = round((fgm + 0.5 * fg3m) / fga * 100, 1) if fga > 0 else 0.0
        plays = fga + 0.44 * fta + tov
        tov_pct = round(tov / plays * 100, 1) if plays > 0 else 0.0
        or_pct = round(oreb / (oreb + dreb_riv) * 100, 1) if (oreb + dreb_riv) > 0 else 0.0
        dr_pct = round(dreb / (dreb + oreb_riv) * 100, 1) if (dreb + oreb_riv) > 0 else 0.0
        ft_rate = round(fta / fga, 2) if fga > 0 else 0.0

        rebs_tot = oreb + dreb + oreb_riv + dreb_riv
        reb_pct = round((oreb + dreb) / rebs_tot * 100, 1) if rebs_tot > 0 else 0.0

        result[tid] = {
            "nom": team_names.get(tid, "?"),
            "eFG%": efg, "TOV%": tov_pct, "OR%": or_pct, "DR%": dr_pct,
            "FT_TCI": ft_rate, "REB%": reb_pct,
        }

    ef = core.calc_eficiencies(df_orig, teams, team_names, poss_mode=poss_mode)
    for tid in result:
        result[tid]["OER"] = ef.get(tid, {}).get("off_rtg", 0)
        result[tid]["DER"] = ef.get(tid, {}).get("def_rtg", 0)

    return result


# ══════════════════════════════════════════════════
# CLUTCH — últims N minuts amb marge ≤ M
# ══════════════════════════════════════════════════
def _t_abs_row(row):
    q = int(row["quart"]) if row.get("quart", "") != "" else 1
    m = float(row.get("min_num", 0))
    t = (q - 1) * 10 + (10 - m if m <= 10 else m)
    return max(0, min(t, q * 10))


def calc_clutch_windows(df_orig, marge_max=5, minuts_finals=5):
    """Retorna una llista d'intervals (t_ini, t_fi) en minuts absoluts de
    partit, dins dels últims `minuts_finals` minuts, on el marge absolut al
    marcador és <= marge_max. Poden ser diversos trams no contigus."""
    sdf = core.score_evo(df_orig)
    if sdf.empty or df_orig.empty:
        return []

    total_min = df_orig["quart"].max() * 10
    inici_finestra = max(total_min - minuts_finals, 0)

    sdf = sdf.copy()
    sdf["t_abs"] = sdf.apply(_t_abs_row, axis=1)
    sdf = sdf[sdf["t_abs"] >= inici_finestra].sort_values("t_abs")
    if sdf.empty:
        return []

    intervals = []
    obert = None
    prev_t = inici_finestra
    for _, row in sdf.iterrows():
        dins = abs(row["diff"]) <= marge_max
        t = row["t_abs"]
        if dins and obert is None:
            obert = prev_t
        elif not dins and obert is not None:
            intervals.append((obert, t))
            obert = None
        prev_t = t
    if obert is not None:
        intervals.append((obert, total_min))
    return intervals


def calc_clutch(df_orig, teams, team_names, poss_mode="full", marge_max=5, minuts_finals=5):
    """Estadístiques clutch (últims `minuts_finals` min, marge <= marge_max):
    box d'equip (via calc_metriques_partit) i box bàsic per jugadora (punts,
    TS%, +/-) restringit a les finestres de temps clutch."""
    intervals = calc_clutch_windows(df_orig, marge_max, minuts_finals)
    if not intervals or len(teams) < 2:
        return None

    df_t = df_orig.copy()
    df_t["t_abs"] = df_t.apply(_t_abs_row, axis=1)
    mask = df_t["t_abs"].apply(lambda t: any(ti <= t < tf for ti, tf in intervals))
    df_clutch = df_t[mask]

    equips = {}
    for i, tid in enumerate(teams[:2]):
        rival_nom = team_names.get(teams[1 - i], "?")
        df_eq = df_clutch[df_clutch["idEquip"] == tid]
        equips[tid] = core.calc_metriques_partit(
            df_eq, None, team_names.get(tid, "?"), rival_nom, poss_mode=poss_mode)

    col_j = "jugador" if "jugador" in df_orig.columns else "jugadora"
    intervals_jug = core.get_intervals_jugadores_global(df_orig)
    jugadores = []
    for jug, ivs in intervals_jug.items():
        if not ivs:
            continue
        eq_id = ivs[0][2]
        actiu = []
        for ti, tf, _ in ivs:
            for c0, c1 in intervals:
                lo, hi = max(ti, c0), min(tf, c1)
                if hi > lo:
                    actiu.append((lo, hi))
        if not actiu:
            continue
        mins_actiu = sum(hi - lo for lo, hi in actiu)
        mask_j = df_t["t_abs"].apply(lambda t: any(lo <= t < hi for lo, hi in actiu))
        df_j = df_t[mask_j]
        rival_id = next((t for t in teams if t != eq_id), None)
        pts = int(df_j[df_j["idEquip"] == eq_id]["punts"].sum())
        pc = int(df_j[df_j["idEquip"] == rival_id]["punts"].sum()) if rival_id else 0

        dj_own = df_j[df_j[col_j] == jug]
        tc_int = int(dj_own["accio"].str.contains(core.TC_INT_PAT, case=False, na=False).sum())
        tl_int = int(dj_own["accio"].str.contains(core.TL_INT_PAT, case=False, na=False).sum())
        ts_denom = 2 * (tc_int + 0.44 * tl_int)
        ts = round(pts / ts_denom * 100, 1) if ts_denom > 0 else None

        jugadores.append({
            "jugadora": jug, "idEquip": eq_id, "equip_nom": team_names.get(eq_id, "?"),
            "minuts": round(mins_actiu, 2), "punts": pts, "TS%": ts, "+/-": pts - pc,
        })

    return {
        "finestra_min": round(sum(tf - ti for ti, tf in intervals), 2),
        "n_trams": len(intervals),
        "equips": equips,
        "jugadores": sorted(jugadores, key=lambda r: -r["punts"]),
    }


# ══════════════════════════════════════════════════
# PPP PER TIPUS D'INICI DE POSSESSIÓ
# ══════════════════════════════════════════════════
TIPUS_INICI = ["after_make", "off_steal", "off_dreb", "off_deadball_tov"]

def calc_pts_by_start(df_orig, teams, team_names):
    """PPP segons com va començar cada possessió (mateixa idea que 'CUÁNDO LA
    TUVIERON, Y CUÁNTO VALIÓ' del PDF): tras canasta, tras robo, tras rebote
    defensivo, tras pérdida en balón parado.

    Requereix que accio distingeixi "Robatori" (robo) de "Pèrdua" genèrica —
    aplica el pegat a feb_normalize_to_jugades abans de fer servir això.
    Simplificacions conegudes:
    - Només els tirs de 2/3 encistellats tanquen possessió (els tirs lliures
      sumen punts però no es tracten com a frontera, per evitar el soroll
      d'intentar detectar "l'últim TL d'una tanda").
    - Si una "Pèrdua" va seguida immediatament d'un "Robatori" de l'altre
      equip, es compta com UNA sola frontera (el robatori), no dues.
    """
    if len(teams) < 2:
        return {}

    acum = {tid: {t: {"pts": 0, "poss": 0} for t in TIPUS_INICI} for tid in teams[:2]}
    df_s = df_orig.sort_values("num").reset_index(drop=True)

    equip_amb_pilota = None
    tipus_actual = None

    n = len(df_s)
    for i in range(n):
        row = df_s.iloc[i]
        accio = str(row.get("accio", ""))
        eq = str(row.get("idEquip", ""))
        punts = int(row.get("punts", 0) or 0)

        es_cistella_2_3 = ("Cistella de 2" in accio) or ("Cistella de 3" in accio)
        es_dreb = "Rebot defensiu" in accio
        es_robatori = "Robatori" in accio
        es_perdua = "Pèrdua" in accio and not es_robatori

        if es_cistella_2_3:
            if equip_amb_pilota == eq and tipus_actual in acum.get(eq, {}):
                acum[eq][tipus_actual]["pts"] += punts
            altre = next((t for t in teams if t != eq), None)
            if altre:
                equip_amb_pilota = altre
                tipus_actual = "after_make"
                acum[altre][tipus_actual]["poss"] += 1
            continue

        # Punts de tirs lliures: sumen al tipus/equip actuals sense canviar de frontera
        if "Cistella de 1" in accio:
            if equip_amb_pilota == eq and tipus_actual in acum.get(eq, {}):
                acum[eq][tipus_actual]["pts"] += punts
            continue

        if es_dreb:
            equip_amb_pilota = eq
            tipus_actual = "off_dreb"
            if eq in acum:
                acum[eq][tipus_actual]["poss"] += 1
            continue

        if es_robatori:
            equip_amb_pilota = eq
            tipus_actual = "off_steal"
            if eq in acum:
                acum[eq][tipus_actual]["poss"] += 1
            continue

        if es_perdua:
            # Si la pèrdua ve seguida d'un robatori de l'altre equip, és el
            # MATEIX esdeveniment de possessió — deixem que la fila del
            # robatori (que ve tot seguit) marqui la frontera, per no
            # comptar-la dues vegades (una com a "deadball_tov" i una altra
            # com a "steal").
            seguent_es_robatori_rival = False
            if i + 1 < n:
                seguent = df_s.iloc[i + 1]
                if "Robatori" in str(seguent.get("accio", "")) and str(seguent.get("idEquip", "")) != eq:
                    seguent_es_robatori_rival = True
            if seguent_es_robatori_rival:
                continue

            altre = next((t for t in teams if t != eq), None)
            if altre:
                equip_amb_pilota = altre
                tipus_actual = "off_deadball_tov"
                acum[altre][tipus_actual]["poss"] += 1
            continue
        # altres accions (faltes, assistències, entrades/sortides...) no canvien
        # la possessió i no es compten com a punts propis del tipus.

    resultat = {}
    for tid in teams[:2]:
        resultat[tid] = {"nom": team_names.get(tid, "?")}
        for t in TIPUS_INICI:
            pts = acum[tid][t]["pts"]
            poss = acum[tid][t]["poss"]
            resultat[tid][t] = {
                "pts": pts, "poss": poss,
                "ppp": round(pts / poss, 2) if poss > 0 else None,
            }
    return resultat
