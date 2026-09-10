# -*- coding: utf-8 -*-
"""Extracció de partit — API de msstats.optimalwayconsulting.com.

L'endpoint getJsonWithMatchMoves segueix funcionant (verificat en viu,
setembre 2026) amb el nou format d'ID de partit que fa servir
basquetcatala.cat des de la temporada 2026-27 (UUID, en lloc de l'antic
ObjectId hexadecimal de 24 caràcters) — només calia passar-li l'UUID tal
qual, sense cap canvi d'endpoint. Retorna una llista plana de jugades
("moves") amb els camps: idTeam, actorName, actorShirtNumber, move, min,
sec, period, score, teamAction.

Nota: aquesta font NO inclou el nom dels equips (només l'ID intern
idTeam) ni cap event de rebot/pèrdua/robatori/assistència/tap — les
mateixes limitacions que ja té Micki Analítica (agustialur-bit/fcbq-analytics)
amb aquesta mateixa API.
"""
import re
import urllib.request
import json

import pandas as pd

API_BASE = "https://msstats.optimalwayconsulting.com/v1/fcbq/getJsonWithMatchMoves/{match_id}?currentSeason=true"


def extract_match_id(text: str):
    """Extreu l'ID de partit d'una URL o el retorna tal qual si ja n'és un.
    Suporta tots dos formats de basquetcatala.cat: l'UUID nou (des de la
    temporada 2026-27) i l'ObjectId hexadecimal de 24 car. (temporades
    anteriors)."""
    text = text.strip()
    # Format nou: UUID amb guions — ex. /estadistica/partit/61b4b2db-9e91-456a-8f7a-b841b2dad323
    m = re.search(r"/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})(?:\?|$)", text)
    if m:
        return m.group(1)
    if re.match(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", text):
        return text
    # Format antic: ObjectId de 24 caràcters hexadecimals
    m = re.search(r"/([a-f0-9]{24})(?:\?|$)", text)
    if m:
        return m.group(1)
    if re.match(r"^[a-f0-9]{24}$", text):
        return text
    return None


def _fetch_json(match_id: str):
    """Descarrega el JSON de jugades d'un partit. Prova currentSeason=true i
    false (compatibilitat entre temporades) i uns quants Referers possibles,
    igual que fa Micki Analítica."""
    urls_a_provar = [
        API_BASE.format(match_id=match_id),
        API_BASE.format(match_id=match_id).replace("currentSeason=true", "currentSeason=false"),
        f"https://msstats.optimalwayconsulting.com/v1/fcbq/getJsonWithMatchMoves/{match_id}",
    ]
    referers = [
        f"https://www.basquetcatala.cat/estadistica/partit/{match_id}",
        f"https://www.basquetcatala.cat/competicions-anteriors/resultat/estadistiques/2025/{match_id}",
        f"https://www.basquetcatala.cat/estadistiques/2025/{match_id}",
        "https://www.basquetcatala.cat/",
    ]
    for url in urls_a_provar:
        for referer in referers:
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0", "Accept": "application/json",
                    "Referer": referer})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
                if data:
                    return data
            except Exception:
                continue
    raise Exception("No s'ha pogut obtenir dades de l'API")


def extract_match(match_id: str) -> pd.DataFrame:
    """Punt d'entrada: partit -> DataFrame amb columnes num, quart, temps,
    min_num, idEquip, dorsal, jugador, accio, marcador, punts, teamAction —
    el mateix esquema que fa servir Micki Analítica, perquè qualsevol motor
    de càlcul basat en str.contains sobre 'accio' funcioni sense canvis."""
    data = _fetch_json(match_id)

    if isinstance(data, list):
        data = {"moves": data}
    raw = data.get("moves") or data.get("matchMoves") or data.get("playByPlay") or []
    if not raw:
        for v in data.values():
            if isinstance(v, list) and len(v) > 3:
                raw = v
                break
    if not raw:
        raise Exception("Aquest partit no té jugades (resposta buida)")

    # Detecta els noms de camps reals del primer element (robust a petits
    # canvis de l'API sense haver de tocar aquest codi)
    camp_equip, camp_jugador, camp_accio = "idTeam", "actorName", "move"
    camp_dorsal, camp_score, camp_period = "actorShirtNumber", "score", "period"
    primer = raw[0] if isinstance(raw[0], dict) else {}
    for c in ["idTeam", "teamId", "id_team", "idEquip", "equipId", "team_id", "idequip"]:
        if c in primer: camp_equip = c; break
    for c in ["actorName", "playerName", "jugador", "actor_name", "name", "player"]:
        if c in primer: camp_jugador = c; break
    for c in ["move", "action", "accio", "moveText", "actionText", "description"]:
        if c in primer: camp_accio = c; break
    for c in ["actorShirtNumber", "shirtNumber", "dorsal", "shirt_number", "number"]:
        if c in primer: camp_dorsal = c; break
    for c in ["score", "marcador", "scoreText", "currentScore"]:
        if c in primer: camp_score = c; break
    for c in ["period", "quart", "quarter", "cuarto"]:
        if c in primer: camp_period = c; break

    rows = []
    for i, play in enumerate(raw):
        if not isinstance(play, dict):
            continue
        mn, sc = play.get("min", ""), play.get("sec", "")
        temps = f"{int(mn):02d}:{int(sc):02d}" if mn != "" and sc != "" else str(mn)
        move = play.get(camp_accio, "")
        punts = 3 if "Cistella de 3" in move else (
            2 if "Cistella de 2" in move else (
                1 if ("Cistella de 1" in move or "Tir lliure convertit" in move) else 0))
        rows.append({
            "num": i + 1, "quart": play.get(camp_period, ""), "temps": temps,
            "min_num": float(mn) + float(sc) / 60 if mn != "" else 0,
            "idEquip": str(play.get(camp_equip, "")), "dorsal": play.get(camp_dorsal, ""),
            "jugador": play.get(camp_jugador, ""), "accio": move,
            "marcador": play.get(camp_score, ""), "punts": punts,
            "teamAction": play.get("teamAction", False),
        })

    df = pd.DataFrame(rows)
    # Aquesta font no dona el nom dels equips (només l'idTeam intern);
    # es deixen buits perquè qui consumeixi el DataFrame faci servir el seu
    # propi fallback (nom desat prèviament, entrada manual, "Equip A/B"...).
    df.attrs["nom_local"] = ""
    df.attrs["nom_visitor"] = ""
    return df


def extract_matches(match_ids: list) -> pd.DataFrame:
    """Descarrega i concatena diversos partits, afegint la columna match_id."""
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
