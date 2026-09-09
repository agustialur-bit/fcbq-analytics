# -*- coding: utf-8 -*-
"""Extracció de partit — API NOVA de msstats.optimalwayconsulting.com (2026).

La federació va canviar l'API a mitjans de 2026: l'ID de partit ara és un UUID
(no un hexadecimal de 24 car.), i l'endpoint antic getJsonWithMatchMoves ja no
existeix. La nova API separa les dades en dos endpoints:

  - /v1/fcbq/matches/{uuid}/stats?currentSeason=true
      -> header, boxscore (per període + totals a period=0), scoreEvolution,
         shotChart (tirs de camp amb x/y/type/made/dorsal, SENSE hora exacta)
  - /v1/fcbq/matches/{uuid}/pbp?currentSeason=true
      -> playByPlay: llista d'esdeveniments amb hora exacta (minute/second),
         però NOMÉS cobreix: períodes, substitucions, temps morts, cistelles
         CONVERTIDES (D1=TL, D2=2pts, D3=3pts) i faltes (F1/P1/P2).

Mapa d'eventTypeCode confirmat empíricament (comparant deltes de localScore/
visitorScore i el text visible a la pàgina) a partir d'un partit real:
  INIPER/FINPER -> inici/final de període
  IN / OUT      -> entra / surt del camp
  TM            -> temps mort
  D1 / D2 / D3  -> tir lliure / de 2 / de 3 CONVERTIT (+1/+2/+3 punts)
  P  (sol)      -> intent de tir (aparellat amb un D del mateix jugador/moment
                   si l'encerta; sol si el falla — però NO diu si era de 2 o 3)
  P1            -> falta personal comuna (sense tir associat)
  P2            -> falta sobre tir de 2 (dona tirs lliures)
  F1            -> recompte de falta comesa (s'usa com a FC del jugador)

LIMITACIONS CONEGUDES (a verificar amb partits reals):
  - No hi ha esdeveniments de rebot, pèrdua, robatori, assistència ni tap
    enlloc del pbp. Fins que no es confirmi el contrari, RO/RD/REB/AS/BR/TAP/BP
    de core_four_factors.calc_box_score_jugadores sortiran a 0 amb aquesta font.
  - El shotChart sembla cobrir només tirs de camp (2/3, amb coordenades x/y).
    No s'hi ha vist cap entrada de tir lliure fallat, així que TLI (i per tant
    TL%) pot sortir incomplet — només es compten els TL CONVERTITS (via D1).
  - Com que "P" sol no diu si l'intent era de 2 o de 3, els intents fallats de
    tir de camp es reconstrueixen NOMÉS a partir del shotChart (que sí que ho
    distingeix), no del pbp.
"""
import requests
import pandas as pd

STATS_URL = "https://msstats.optimalwayconsulting.com/v1/fcbq/matches/{match_id}/stats?currentSeason=true"
PBP_URL = "https://msstats.optimalwayconsulting.com/v1/fcbq/matches/{match_id}/pbp?currentSeason=true"

PUNTS_PER_CODE = {"D1": 1, "D2": 2, "D3": 3}
ACCIO_MADE = {"D1": "Cistella de 1", "D2": "Cistella de 2", "D3": "Cistella de 3"}


def extract_match_id(text: str):
    """Extreu l'UUID del partit d'una URL de basquetcatala.cat/estadistica/partit/{uuid}."""
    import re
    m = re.search(r"/partit/([0-9a-fA-F-]{36})", text)
    if m:
        return m.group(1)
    if re.match(r"^[0-9a-fA-F-]{36}$", text.strip()):
        return text.strip()
    return None


def _fetch_json(url: str, match_id: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Referer": f"https://www.basquetcatala.cat/estadistica/partit/{match_id}",
    }
    resp = requests.get(url.format(match_id=match_id), headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_match_raw(match_id: str):
    """Retorna (data_stats, data_pbp), els dos JSON crus de l'API nova."""
    data_stats = _fetch_json(STATS_URL, match_id)
    data_pbp = _fetch_json(PBP_URL, match_id)
    return data_stats, data_pbp


def _detecta_equips(data_stats: dict, events: list):
    """Noms d'equip del boxscore (period=0, totals) + quin teamUuid és
    'local' segons quin fa pujar localScore als esdeveniments D1/D2/D3
    (mètode robust: no cal que el boxscore exposi l'uuid de l'equip)."""
    boxscore = data_stats.get("boxscore", [])
    totals = next((b for b in boxscore if b.get("period") == 0),
                  boxscore[0] if boxscore else {})
    nom_local = totals.get("local", {}).get("name", "Local")
    nom_visitor = totals.get("visitor", {}).get("name", "Visitant")

    id_local, id_visitor = None, None
    prev_local, prev_visitor = 0, 0
    for ev in events:
        if ev.get("eventTypeCode") not in ("D1", "D2", "D3"):
            continue
        cur_local = ev.get("localScore", prev_local)
        cur_visitor = ev.get("visitorScore", prev_visitor)
        if cur_local > prev_local and id_local is None:
            id_local = ev.get("teamUuid")
        if cur_visitor > prev_visitor and id_visitor is None:
            id_visitor = ev.get("teamUuid")
        prev_local, prev_visitor = cur_local, cur_visitor
        if id_local and id_visitor:
            break

    return nom_local, nom_visitor, id_local, id_visitor


def _rows_from_pbp(events: list, id_local: str, id_visitor: str) -> list:
    """Genera files (num, quart, temps, min_num, idEquip, dorsal, jugador,
    accio, marcador, punts) a partir del play-by-play — rotacions, +/-,
    temps morts i faltes. NO inclou tirs fallats de camp (vegeu shotChart)."""
    rows = []
    num = 0
    score_a = score_b = 0

    for ev in events:
        code = ev.get("eventTypeCode")
        if code in ("INIPER", "FINPER"):
            continue

        period = ev.get("period", 1)
        minute = ev.get("minute", 0) or 0
        second = ev.get("second", 0) or 0
        min_num = float(minute) + float(second) / 60
        team_uuid = ev.get("teamUuid") or ""
        dorsal = ev.get("dorsal", "")
        jugador = ev.get("actorName", "")

        accio = None
        punts = 0

        if code == "IN":
            accio = "Entra al camp"
        elif code == "OUT":
            accio = "Surt del camp"
        elif code == "TM":
            accio = "Temps mort"
        elif code in ("D1", "D2", "D3"):
            accio = ACCIO_MADE[code]
            punts = PUNTS_PER_CODE[code]
        elif code == "F1":
            accio = "Falta comesa"
        else:
            # "P" (intent, gestionat via shotChart), "P1"/"P2" (detall del
            # tipus de falta, ja comptada via F1) — no generem fila pròpia
            # per evitar duplicar faltes o intents sense tipus conegut.
            continue

        if team_uuid == id_local:
            score_a += punts
        elif team_uuid == id_visitor:
            score_b += punts

        num += 1
        rows.append({
            "num": num, "quart": period,
            "temps": f"{minute}:{second:02d}",
            "min_num": min_num, "idEquip": team_uuid,
            "dorsal": dorsal, "jugador": jugador, "accio": accio,
            "marcador": f"{score_a}-{score_b}", "punts": punts,
            "teamAction": False,
        })

    return rows


def _rows_from_shotchart_misses(data_stats: dict, id_local: str, id_visitor: str,
                                  num_inici: int) -> list:
    """Genera files d'intents FALLATS de tir de camp (2 o 3) a partir del
    shotChart — el pbp no distingeix el valor del tir quan falla. No tenim
    hora exacta (només 'period'), així que es col·loquen a min_num=0 dins
    del període corresponent; no afecten el càlcul de minuts/rotacions
    (que depèn només de IN/OUT), només els comptadors de %2/%3."""
    rows = []
    num = num_inici
    shot_chart = data_stats.get("shotChart", {})

    for costat, id_equip in [("local", id_local), ("visitor", id_visitor)]:
        for tir in shot_chart.get(costat, []):
            if tir.get("made"):
                continue  # les fetes ja venen del pbp (D2/D3), amb hora exacta
            tipus = tir.get("type", "")
            if tipus == "T2":
                accio = "Intent fallat de 2"
            elif tipus == "T3":
                accio = "Intent fallat de 3"
            else:
                continue
            num += 1
            rows.append({
                "num": num, "quart": tir.get("period", 1),
                "temps": "", "min_num": 0.0, "idEquip": id_equip,
                "dorsal": tir.get("dorsal", ""), "jugador": tir.get("actorName", ""),
                "accio": accio, "marcador": "", "punts": 0, "teamAction": False,
            })
    return rows


def extract_match(match_id: str) -> pd.DataFrame:
    """Punt d'entrada: partit -> DataFrame amb el mateix esquema que feia
    servir fetch_and_parse() de l'API antiga, perquè la resta del motor
    (calc_minuts_reals, get_intervals_jugadores_global, str.contains sobre
    accio...) segueixi funcionant sense canvis."""
    data_stats, data_pbp = fetch_match_raw(match_id)
    events = data_pbp.get("playByPlay", [])
    if not events:
        raise Exception("Aquest partit no té jugades (pbp buit)")

    nom_local, nom_visitor, id_local, id_visitor = _detecta_equips(data_stats, events)
    if not id_local or not id_visitor:
        raise Exception(
            "No s'ha pogut determinar quin equip és local/visitant a partir "
            "del pbp (cap esdeveniment D1/D2/D3 trobat)."
        )

    rows_pbp = _rows_from_pbp(events, id_local, id_visitor)
    rows_misses = _rows_from_shotchart_misses(
        data_stats, id_local, id_visitor, num_inici=len(rows_pbp))

    df = pd.DataFrame(rows_pbp + rows_misses)
    df.attrs["nom_local"] = nom_local
    df.attrs["nom_visitor"] = nom_visitor
    df.attrs["id_local"] = id_local
    df.attrs["id_visitor"] = id_visitor
    return df


def extract_matches(match_ids: list) -> pd.DataFrame:
    frames = []
    for mid in match_ids:
        df = extract_match(mid)
        df["match_id"] = mid
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


# Compatibilitat amb Micki Analítica (agustialur-bit/fcbq-analytics), que crida
# fetch_and_parse(match_id) directament per a un sol partit — mateixa funció
# que extract_match(), amb el nom antic perquè app.py no calgui tocar-lo.
def fetch_and_parse(match_id: str) -> pd.DataFrame:
    return extract_match(match_id)
