# -*- coding: utf-8 -*-
"""Extracció de partit — API de msstats.optimalwayconsulting.com.

Setembre 2026: l'endpoint antic `getJsonWithMatchMoves` ha quedat mort —
respon 200 amb `{}` per a qualsevol ID, inclosos partits que abans anaven bé.
El substitueix `/v1/fcbq/matches/{uuid}/pbp`, que:

  * demana capçalera `Authorization: Bearer <JWT>` i `federation: fcbq`.
    El token és d'un compte de servei (`web@basquetcatala.cat`, ROLE_WEB) que
    basquetcatala.cat emet un cop passat el seu reCAPTCHA, i dura 2 hores;
    per això s'ha de passar des de fora (paràmetre `token` o $FCBQ_TOKEN).
  * torna els esdeveniments amb codis (`D2`, `F3`, `IN`, `TM`...) en lloc del
    text català de l'API antiga ("Cistella de 2", "Intent fallat de 3"...).
    Aquí es tradueixen al vocabulari antic perquè qualsevol motor de càlcul
    basat en `str.contains` sobre 'accio' segueixi funcionant sense canvis.

Novetat útil: `/matches/{uuid}/stats` sí que dona el nom real dels equips,
cosa que l'API antiga no feia (només l'ID intern).

Limitacions que es mantenen: no hi ha events de rebot, assistència, robatori
ni tap.
"""
import os
import re
import json
import base64
import urllib.request
import urllib.error
from datetime import datetime

import pandas as pd

API_MATCH = "https://msstats.optimalwayconsulting.com/v1/fcbq/matches/{match_id}/{recurs}?currentSeason=true"

# Codis d'esdeveniment del play-by-play → text de l'esquema antic.
EVENT_CODES = {
    "D1": "Cistella de 1", "D2": "Cistella de 2", "D3": "Cistella de 3",
    "F1": "Intent fallat de 1", "F2": "Intent fallat de 2", "F3": "Intent fallat de 3",
    "IN": "Entra al camp", "OUT": "Surt del camp",
    "TM": "Temps mort", "INIPER": "Inici de període", "FINPER": "Final de període",
}
# Les faltes porten a sobre el comptador personal de la jugadora (", 3a falta"),
# tal com feia l'API antiga: hi ha codi que compta faltes amb contains("falta").
CODIS_FALTA = {
    "P": "Personal", "P1": "Personal 1 tir lliure", "P2": "Personal 2 tirs lliures",
    "P3": "Personal 3 tirs lliures", "AT": "Falta en atac",
    "DI2": "Antiesportiva 2 tirs lliures", "TE1": "Falta tècnica 1 tir lliure",
}
PUNTS_CODI = {"D1": 1, "D2": 2, "D3": 3}
CODIS_EQUIP = {"TM", "INIPER", "FINPER"}


def extract_match_id(text: str):
    """Extreu l'ID de partit d'una URL o el retorna tal qual si ja n'és un.
    Suporta tots dos formats de basquetcatala.cat: l'UUID nou (des de la
    temporada 2026-27) i l'ObjectId hexadecimal de 24 car. (anteriors)."""
    text = text.strip()
    # Format nou: UUID — ex. /estadistica/partit/dc48fb62-07f4-4901-9bb2-8fdc70d4f011
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


def token_segons_restants(token: str):
    """Segons que queden abans que caduqui el token (None si no es pot llegir)."""
    try:
        payload = token.split(".")[1]
        dades = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return int(dades["exp"]) - int(datetime.now().timestamp())
    except Exception:
        return None


def _api_get(match_id: str, recurs: str, token: str = None):
    """Crida un recurs del partit ('pbp' o 'stats') i en retorna el JSON."""
    token = (token or os.environ.get("FCBQ_TOKEN", "")).strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        raise RuntimeError(
            "Falta el token de l'API. Passa'l com a paràmetre `token` o a $FCBQ_TOKEN. "
            "S'agafa del navegador: obre un partit a basquetcatala.cat → F12 → Network "
            "→ Fetch/XHR → capçalera Authorization. Dura 2 hores.")
    req = urllib.request.Request(
        API_MATCH.format(match_id=match_id, recurs=recurs),
        headers={
            "Accept": "application/json, text/plain, */*", "Accept-Language": "ca",
            "Authorization": f"Bearer {token}", "federation": "fcbq",
            "Origin": "https://www.basquetcatala.cat",
            "Referer": "https://www.basquetcatala.cat/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("Token caducat o no vàlid (duren 2 h).") from None
        if e.code in (404, 500):
            raise RuntimeError(f"L'API no troba el partit {match_id}.") from None
        raise RuntimeError(f"L'API ha respost amb un error {e.code}.") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"No s'ha pogut connectar amb l'API: {e.reason}") from None


def extract_match(match_id: str, token: str = None) -> pd.DataFrame:
    """Punt d'entrada: partit -> DataFrame amb columnes num, quart, temps,
    min_num, idEquip, dorsal, jugador, accio, marcador, punts, teamAction —
    el mateix esquema de sempre. `idEquip` ara és l'UUID de l'equip.

    Els noms reals dels equips queden a df.attrs["nom_local"] / ["nom_visitor"]
    i a df.attrs["noms_equips"] (uuid -> nom). Els codis d'esdeveniment que no
    siguin al diccionari es deixen tal qual i es llisten a
    df.attrs["codis_desconeguts"]."""
    raw = (_api_get(match_id, "pbp", token) or {}).get("playByPlay") or []
    if not raw:
        raise RuntimeError(f"El partit {match_id} no té play-by-play publicat.")

    noms_equips, nom_local, nom_visitor = {}, "", ""
    try:
        capc = (_api_get(match_id, "stats", token) or {}).get("header") or {}
        local, visitant = capc.get("localTeam") or {}, capc.get("visitorTeam") or {}
        nom_local, nom_visitor = local.get("name", ""), visitant.get("name", "")
        for eq in (local, visitant):
            if eq.get("uuid"):
                noms_equips[eq["uuid"]] = eq.get("name", "")
    except Exception:
        pass

    rows, desconeguts, faltes_jug = [], set(), {}
    for i, ev in enumerate(raw):
        if not isinstance(ev, dict):
            continue
        codi = str(ev.get("eventTypeCode") or "")
        if codi in CODIS_FALTA:
            clau = str(ev.get("uuid") or "") or f"{ev.get('teamUuid')}|{ev.get('actorName')}"
            faltes_jug[clau] = faltes_jug.get(clau, 0) + 1
            accio = f"{CODIS_FALTA[codi]}, {faltes_jug[clau]}a falta"
        else:
            accio = EVENT_CODES.get(codi)
            if accio is None:
                accio = codi or "?"
                desconeguts.add(codi)
        mn, sc = ev.get("minute"), ev.get("second")
        mn = 0 if mn in (None, "") else int(mn)
        sc = 0 if sc in (None, "") else int(sc)
        id_equip = str(ev.get("teamUuid") or "") or "0"
        jugador = ev.get("actorName") or ""
        if codi == "TM":
            jugador = noms_equips.get(id_equip, "")
        rows.append({
            "num": i + 1, "quart": ev.get("period", ""),
            "temps": f"{mn:02d}:{sc:02d}", "min_num": mn + sc / 60,
            "idEquip": id_equip, "dorsal": ev.get("dorsal") or "",
            "jugador": jugador, "accio": accio,
            "marcador": f"{ev.get('localScore', 0)}-{ev.get('visitorScore', 0)}",
            "punts": PUNTS_CODI.get(codi, 0), "teamAction": codi in CODIS_EQUIP,
        })

    df = pd.DataFrame(rows)
    df.attrs["nom_local"] = nom_local
    df.attrs["nom_visitor"] = nom_visitor
    df.attrs["noms_equips"] = noms_equips
    df.attrs["codis_desconeguts"] = sorted(c for c in desconeguts if c)
    return df


def extract_matches(match_ids: list, token: str = None) -> pd.DataFrame:
    """Descarrega i concatena diversos partits, afegint la columna match_id.

    pd.concat perd els .attrs, així que els noms dels equips de tots els
    partits es refonen a mà a df.attrs["noms_equips"] (uuid -> nom)."""
    frames, noms, desconeguts = [], {}, set()
    for mid in match_ids:
        df = extract_match(mid, token)
        df["match_id"] = mid
        noms.update(df.attrs.get("noms_equips") or {})
        desconeguts.update(df.attrs.get("codis_desconeguts") or [])
        frames.append(df)
    total = pd.concat(frames, ignore_index=True)
    total.attrs["noms_equips"] = noms
    total.attrs["codis_desconeguts"] = sorted(desconeguts)
    return total


# Compatibilitat: Micki Analítica crida fetch_and_parse(match_id) per a un sol partit.
def fetch_and_parse(match_id: str, token: str = None) -> pd.DataFrame:
    return extract_match(match_id, token)
