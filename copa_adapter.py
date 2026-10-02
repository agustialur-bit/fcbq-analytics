"""
Adaptador Micki → base COPA.

Converteix un partit ja carregat per Micki (el DataFrame de play-by-play que
retorna extraction.extract_match) en un PartitCopa llest per enviar.

Regla que governa tot aquest fitxer: **cap fórmula nova**. Cada valor surt de la
mateixa funció d'analitica_core que alimenta les pestanyes de l'app i l'Excel.
Si un dia canvia un càlcul allà, aquí canvia sol. Concretament:

  · possessions ............ calc_possessions()      (columna "Poss." de 📊 Partits)
  · minuts ................. calc_minuts_reals()     (intervals reals Entra/Surt)
  · punts/possessions ON ... calc_onoff_raw()        (pestanya On-Off Rating)
  · tirs ON ................ calc_onoff_raw()        (mateixa màscara que els punts ON)
  · tirs .................... get_shot_counts()      (🎯 Eficiència de tir)
  · parelles ............... calc_pm_combinacions()  (Rotacions)

L'única cosa que es calcula aquí són els punts per quart i les faltes, amb el
mateix criteri literal que ja fa servir app.py.
"""
from __future__ import annotations

import pandas as pd

from extraction import metadades_de_capcalera
from analitica_core import (
    calc_minuts_reals,
    calc_onoff_raw,
    calc_pm_combinacions,
    calc_possessions,
    get_shot_counts,
    get_teams_ordered,
)
from copa_sync import PartitCopa, construir_partit

# Parelles per sota d'aquests minuts compartits no es desen. Es va comencar amb
# 3 minuts, pero per al grafic de contribucio per companya el que compta es el
# total de la temporada, i amb 3 es perdia un 2% dels minuts compartits i un 11%
# de les parelles. Amb 1 minut es conserva el 99,9% del temps i la base nomes
# creix un 10%. Micki fa servir el mateix llindar per defecte.
MIN_MINUTS_PARELLA = 1.0

MINS_PER_QUART = 10


# ─────────────────────────────────────────────────────────────────────────────
# METADADES
# ─────────────────────────────────────────────────────────────────────────────
def metadades_del_partit(df: pd.DataFrame) -> dict:
    """Treu data i jornada de la capçalera de l'API, si hi són.

    Retorna {"data": "YYYY-MM-DD"|None, "jornada": int|None}. Qualsevol dels dos
    pot ser None: aleshores els ha de demanar la UI. Mai s'inventa la data
    d'avui, que és justament el que feia que l'Excel mostrés 29/09 per a partits
    del cap de setmana.
    """
    return metadades_de_capcalera(df.attrs.get("header"))


# ─────────────────────────────────────────────────────────────────────────────
# RECOMPTES AUXILIARS (mateix criteri que app.py)
# ─────────────────────────────────────────────────────────────────────────────
def _faltes(df_sub: pd.DataFrame) -> int:
    # app.py compta faltes amb contains("falta"): funciona tant amb el format
    # actual ("Personal, 1a falta") com amb l'antic de l'API.
    return int(df_sub["accio"].str.contains("falta", case=False, na=False).sum())


def _tirs(df_sub: pd.DataFrame) -> dict:
    v1m, v1x, v2m, v2x, v3m, v3x = get_shot_counts(df_sub)
    return {
        "t2c": v2m, "t2i": v2m + v2x,
        "t3c": v3m, "t3i": v3m + v3x,
        "tlc": v1m, "tli": v1m + v1x,
    }


def _punts_per_quart(df: pd.DataFrame, equip_id) -> dict:
    """Punts de l'equip a cada quart i a la pròrroga (Q5 endavant)."""
    df_eq = df[df["idEquip"] == equip_id]
    out = {}
    for q in (1, 2, 3, 4):
        out[f"pts_q{q}"] = int(df_eq[df_eq["quart"] == q]["punts"].sum())
    out["pts_pr"] = int(df_eq[pd.to_numeric(df_eq["quart"], errors="coerce") > 4]["punts"].sum())
    return out


def _es_titular(df: pd.DataFrame, jugadora: str) -> int:
    """1 si comença el partit a pista.

    Mateixa deducció que fa calc_onoff_raw: si el primer moviment que registra
    d'una jugadora és un 'Surt del camp', és que ja hi era abans.
    """
    files = df[df["jugador"].astype(str) == str(jugadora)].sort_values("num")
    if files.empty:
        return 0
    primera = files.iloc[0]
    acc = str(primera.get("accio", ""))
    if int(primera.get("quart", 1) or 1) != 1:
        return 0
    return 1 if ("Surt" in acc and "camp" in acc) else 0


def _dorsal(df_jug: pd.DataFrame) -> str:
    vals = [str(d).strip() for d in df_jug["dorsal"] if str(d).strip() not in ("", "nan")]
    return vals[0] if vals else ""


def _jugadores_de(df: pd.DataFrame, equip_id, nom_equip: str) -> list[str]:
    """Noms de les jugadores d'un equip, descartant les files d'equip.

    Les accions d'equip (temps morts) porten el nom de l'equip a la columna
    'jugador'; no són jugadores.
    """
    noms = df[df["idEquip"] == equip_id]["jugador"].astype(str)
    return sorted({
        n for n in noms
        if n and n not in ("nan", "None") and n.strip() and n != nom_equip
    })


# ─────────────────────────────────────────────────────────────────────────────
# ADAPTADOR
# ─────────────────────────────────────────────────────────────────────────────
def partit_a_copa(
    df: pd.DataFrame,
    *,
    match_id: str,
    temporada: str,
    competicio: str,
    data: str | None = None,
    jornada: int | None = None,
    noms_equips: dict | None = None,
    poss_mode: str = "approx",
    min_minuts_parella: float = MIN_MINUTS_PARELLA,
) -> PartitCopa:
    """
    Converteix un partit carregat per Micki en un PartitCopa.

    df          play-by-play tal com el retorna extraction.extract_match()
    match_id    ID FCBQ del partit. Obligatori: és la clau de tota la base.
    data        YYYY-MM-DD real del partit. Si no es passa, es mira a la
                capçalera de l'API (df.attrs["header"]); si tampoc hi és, peta,
                perquè guardar una data inventada corromp la base.
    noms_equips {equip_id: nom}. Si no es passa, s'agafa de df.attrs.
    """
    if not str(match_id).strip():
        raise ValueError("Falta el match_id: sense ell no es pot enviar el partit.")

    teams = get_teams_ordered(df)
    if len(teams) < 2:
        raise ValueError(f"El partit {match_id} no té dos equips identificables.")
    id_local, id_visitant = teams[0], teams[1]

    # Els identificadors poden arribar com a "981415" o com a "981415.0" segons
    # si han passat per un CSV o per SQLite. S'indexen de les dues maneres
    # perque la cerca del nom no depengui d'aixo.
    def _claus(k):
        k = str(k)
        return {k, k[:-2]} if k.endswith(".0") else {k, k + ".0"}

    noms = {}
    for origen in (df.attrs.get("noms_equips") or {}, noms_equips or {}):
        for k, v in origen.items():
            for kk in _claus(k):
                noms[kk] = v
    nom_local = noms.get(id_local) or df.attrs.get("nom_local") or str(id_local)
    nom_visitant = noms.get(id_visitant) or df.attrs.get("nom_visitor") or str(id_visitant)
    if nom_local == nom_visitant:
        raise ValueError(f"Els dos equips del partit {match_id} tenen el mateix nom ({nom_local}).")

    meta = metadades_del_partit(df)
    data = data or meta["data"]
    if not data:
        raise ValueError(
            f"No sé la data real del partit {match_id} i no me la puc inventar. "
            "Passa-la a la UI abans d'enviar-lo."
        )
    if jornada is None:
        jornada = meta["jornada"]

    quart_max = int(pd.to_numeric(df["quart"], errors="coerce").max() or 4)
    prorrogues = max(quart_max - 4, 0)

    # ── equips ───────────────────────────────────────────────────────────────
    equips = {}
    for eq_id, nom in ((id_local, nom_local), (id_visitant, nom_visitant)):
        df_eq = df[df["idEquip"] == eq_id]
        equips[nom] = {
            "pts": int(df_eq["punts"].sum()),
            "poss": round(calc_possessions(df_eq, poss_mode), 2),
            "faltes": _faltes(df_eq),
            **_tirs(df_eq),
            **_punts_per_quart(df, eq_id),
        }

    # ── jugadores ────────────────────────────────────────────────────────────
    minuts = calc_minuts_reals(df)
    # Minuts i +/- a pista del mateix motor que calcula les parelles. Es desen a
    # part perque el grafic de contribucio per companya compari la barra (amb la
    # companya) i el diamant (mitjana propia) amb el mateix criteri.
    ind = {}
    for r in calc_pm_combinacions(df, mode="individual"):
        if len(r["combinacio"]) != 1:
            continue
        ind[(str(r["equip"]), r["combinacio"][0])] = r
    jugadores = []
    for eq_id, nom_eq in ((id_local, nom_local), (id_visitant, nom_visitant)):
        for jug in _jugadores_de(df, eq_id, nom_eq):
            df_j = df[(df["jugador"].astype(str) == jug) & (df["idEquip"] == eq_id)]
            on = calc_onoff_raw(df, jug, eq_id, teams, poss_mode) or {}
            jugadores.append({
                "jugadora": jug,
                # El play-by-play no porta identificador de jugadora, només el
                # nom; per això va buit. Si algun dia l'API el dona, és aquí.
                "jugadora_id": "",
                "dorsal": _dorsal(df_j),
                "equip": nom_eq,
                "titular": _es_titular(df, jug),
                "min": round(minuts.get(jug, 0.0), 1),
                "pts": int(df_j["punts"].sum()),
                "faltes": _faltes(df_j),
                **_tirs(df_j),
                "eq_pts_on": on.get("pts_on", 0),
                "eq_pts_contra_on": on.get("pts_on_riv", 0),
                "eq_poss_on": round(on.get("poss_on", 0.0), 2),
                "eq_poss_rival_on": round(on.get("poss_on_riv", 0.0), 2),
                "eq_tci_on": on.get("tci_on", 0),
                "eq_tli_on": on.get("tli_on", 0),
                "min_ind": round(ind.get((str(eq_id), jug), {}).get("minuts", 0.0), 1),
                "pm_ind": ind.get((str(eq_id), jug), {}).get("pm", 0),
            })

    # ── parelles ─────────────────────────────────────────────────────────────
    nom_per_id = {}
    for _id, _nom in ((id_local, nom_local), (id_visitant, nom_visitant)):
        for kk in _claus(_id):
            nom_per_id[kk] = _nom
    noms_jugadores = {j["jugadora"] for j in jugadores}
    parelles = []
    for c in calc_pm_combinacions(df, mode="parelles"):
        if c["minuts"] < min_minuts_parella:
            continue
        combo = c["combinacio"]
        if len(combo) != 2:
            continue
        a, b = str(combo[0]), str(combo[1])
        # Descarta qualsevol parella amb un nom que no hagi arribat a jugadores:
        # el validador ho rebutjaria i no val la pena enviar-ho.
        if a not in noms_jugadores or b not in noms_jugadores or a == b:
            continue
        nom_eq = nom_per_id.get(str(c["equip"])) or nom_per_id.get(c["equip"])
        if not nom_eq:
            continue
        parelles.append({
            "equip": nom_eq, "jugadora_a": a, "jugadora_b": b,
            "min": c["minuts"], "pf": c["pf"], "pc": c["pc"],
        })

    return construir_partit(
        match_id=str(match_id),
        data=data,
        local=nom_local,
        visitant=nom_visitant,
        local_id=str(id_local),
        visitant_id=str(id_visitant),
        equips=equips,
        jugadores=jugadores,
        parelles=parelles,
        temporada=temporada,
        competicio=competicio,
        jornada=jornada,
        prorrogues=prorrogues,
    )
