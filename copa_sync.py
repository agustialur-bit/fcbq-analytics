"""
copa_sync.py — Envia partits de Micki Analítica a la base comuna COPA (Google Sheets).

Flux:
    1. L'adaptador de Micki (copa_adapter.py, a fer per Claude Code) calcula les
       estadístiques de cada partit carregat i crida `construir_partit(...)`.
    2. `render_boto_copa(partits)` mostra el resum, valida i, en prémer el botó,
       crida `enviar_partits(...)`.
    3. `enviar_partits` substitueix per match_id: esborra les files existents
       d'aquells partits i escriu les noves. Reenviar un partit no el duplica.

Secrets de Streamlit necessaris (.streamlit/secrets.toml o panell de Streamlit Cloud):

    [gcp_service_account]
    type = "service_account"
    project_id = "..."
    private_key_id = "..."
    private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
    client_email = "...@....iam.gserviceaccount.com"
    client_id = "..."
    token_uri = "https://oauth2.googleapis.com/token"

    [copa]
    sheet_id = "ID_DEL_GOOGLE_SHEET"
    temporada = "2026-27"
    competicio = "COPA"

Dependències: gspread>=6.0, google-auth, pandas, streamlit>=1.26
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd

VERSIO_ESQUEMA = "2"   # v2: afegida la pestanya parella_partit

# ─────────────────────────────────────────────────────────────────────────────
# ESQUEMA — l'ordre de les columnes és el del Google Sheet. No el canviïs sense
# actualitzar també el hub i incrementar VERSIO_ESQUEMA.
# ─────────────────────────────────────────────────────────────────────────────
COLS_COMUNES = ["match_id", "temporada", "competicio", "jornada", "data"]

COLS_PARTITS = COLS_COMUNES + [
    "local", "local_id", "visitant", "visitant_id",
    "pts_local", "pts_visitant", "prorrogues",
    "enviat_at", "versio_esquema",
]

STATS_EQUIP = [
    "pts", "poss",
    "t2c", "t2i", "t3c", "t3i", "tlc", "tli", "faltes",
    "pts_q1", "pts_q2", "pts_q3", "pts_q4", "pts_pr",
]
COLS_EQUIP = COLS_COMUNES + [
    "equip", "equip_id", "rival", "rival_id", "condicio", "resultat",
    "pts", "pts_rival", "poss", "poss_rival",
    "t2c", "t2i", "t3c", "t3i", "tlc", "tli", "faltes",
    "pts_q1", "pts_q2", "pts_q3", "pts_q4", "pts_pr",
]

STATS_JUGADORA = [
    "min", "pts", "t2c", "t2i", "t3c", "t3i", "tlc", "tli", "faltes",
    # Dades de l'EQUIP mentre la jugadora és a pista (intervals reals Entra/Surt).
    # Els valors OFF es dedueixen: total equip − ON.
    "eq_pts_on", "eq_pts_contra_on", "eq_poss_on", "eq_poss_rival_on",
    "eq_tci_on", "eq_tli_on",
]
COLS_JUGADORA = COLS_COMUNES + [
    "jugadora", "jugadora_id", "dorsal", "equip", "equip_id", "rival", "titular",
] + STATS_JUGADORA

# Minuts i +/- de cada parella de jugadores que han coincidit a pista. No es pot
# deduir de jugadora_partit: alli tot esta agregat per jugadora i la coincidencia
# entre dues es perd. Nomes s'hi desen les parelles que arriben al minim de
# minuts que fixa l'adaptador, per no omplir la base de parelles testimonials.
COLS_PARELLA = COLS_COMUNES + [
    "equip", "equip_id", "rival",
    "jugadora_a", "jugadora_b", "min", "pf", "pc",
]

COLS_EQUIPS = ["nom_fcbq", "equip_id", "nom_curt"]
COLS_LOG = ["enviat_at", "match_id", "accio", "files_equip", "files_jugadora", "versio_esquema"]

ESQUEMA = {
    "partits": COLS_PARTITS,
    "equip_partit": COLS_EQUIP,
    "jugadora_partit": COLS_JUGADORA,
    "parella_partit": COLS_PARELLA,
    "equips": COLS_EQUIPS,
    "_log": COLS_LOG,
}

# Camps que poden quedar buits sense bloquejar l'enviament
OPCIONALS = {
    "jornada", "local_id", "visitant_id", "equip_id", "rival_id",
    "jugadora_id", "dorsal", "titular", "pts_pr",
}


# ─────────────────────────────────────────────────────────────────────────────
# CONSTRUCCIÓ DEL PARTIT
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class PartitCopa:
    partit: dict
    equips: pd.DataFrame
    jugadores: pd.DataFrame
    # Opcional: si l'adaptador no les calcula, el partit s'envia igualment i la
    # pestanya queda buida per a aquell match_id.
    parelles: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=COLS_PARELLA))

    @property
    def match_id(self) -> str:
        return str(self.partit["match_id"])

    def etiqueta(self) -> str:
        p = self.partit
        j = f"J{p['jornada']} · " if p.get("jornada") not in (None, "") else ""
        return f"{j}{p['local']} {p['pts_local']} – {p['pts_visitant']} {p['visitant']}"


def construir_partit(
    *,
    match_id: str,
    data: str,
    local: str,
    visitant: str,
    equips: dict[str, dict],
    jugadores: list[dict],
    temporada: str,
    competicio: str,
    jornada: int | None = None,
    local_id: str = "",
    visitant_id: str = "",
    prorrogues: int = 0,
    parelles: list[dict] | None = None,
) -> PartitCopa:
    """
    Munta un PartitCopa a partir de les estadístiques calculades per Micki.

    equips:    {nom_equip_fcbq: {pts, poss, t2c, t2i, ..., pts_q1..pts_q4, pts_pr}}
               (exactament 2 entrades: local i visitant)
    jugadores: [{jugadora, equip, jugadora_id?, dorsal?, titular?, min, pts, ...,
                 eq_pts_on, eq_pts_contra_on, eq_poss_on, eq_poss_rival_on,
                 eq_tci_on, eq_tli_on}]

    Els camps derivats (rival, condicio, resultat, pts_rival, poss_rival, ids,
    columnes comunes) s'omplen aquí automàticament.
    """
    comuns = {
        "match_id": str(match_id),
        "temporada": temporada,
        "competicio": competicio,
        "jornada": jornada if jornada is not None else "",
        "data": str(data)[:10],
    }
    ids = {local: local_id, visitant: visitant_id}
    rivals = {local: visitant, visitant: local}

    partit = {
        **comuns,
        "local": local, "local_id": local_id,
        "visitant": visitant, "visitant_id": visitant_id,
        "pts_local": equips[local]["pts"],
        "pts_visitant": equips[visitant]["pts"],
        "prorrogues": prorrogues,
        "enviat_at": "",
        "versio_esquema": VERSIO_ESQUEMA,
    }

    files_equip = []
    for nom in (local, visitant):
        s, r = equips[nom], equips[rivals[nom]]
        files_equip.append({
            **comuns,
            "equip": nom, "equip_id": ids[nom],
            "rival": rivals[nom], "rival_id": ids[rivals[nom]],
            "condicio": "L" if nom == local else "V",
            "resultat": "V" if s["pts"] > r["pts"] else ("D" if s["pts"] < r["pts"] else "E"),
            "pts_rival": r["pts"],
            "poss_rival": r.get("poss", ""),
            **{k: s.get(k, "") for k in STATS_EQUIP},
        })

    files_jug = []
    for j in jugadores:
        eq = j["equip"]
        files_jug.append({
            **comuns,
            "jugadora": j["jugadora"],
            "jugadora_id": j.get("jugadora_id", ""),
            "dorsal": j.get("dorsal", ""),
            "equip": eq, "equip_id": ids.get(eq, ""),
            "rival": rivals.get(eq, ""),
            "titular": j.get("titular", ""),
            **{k: j.get(k, "") for k in STATS_JUGADORA},
        })

    files_par = []
    for pa in (parelles or []):
        eq = pa["equip"]
        # Ordre alfabetic dins la parella: aixi (A,B) i (B,A) son la mateixa fila
        # i el hub pot agrupar sense duplicats.
        a, b = sorted([pa["jugadora_a"], pa["jugadora_b"]])
        files_par.append({
            **comuns,
            "equip": eq, "equip_id": ids.get(eq, ""), "rival": rivals.get(eq, ""),
            "jugadora_a": a, "jugadora_b": b,
            "min": pa.get("min", ""), "pf": pa.get("pf", ""), "pc": pa.get("pc", ""),
        })

    return PartitCopa(
        partit=partit,
        equips=pd.DataFrame(files_equip, columns=COLS_EQUIP),
        jugadores=pd.DataFrame(files_jug, columns=COLS_JUGADORA),
        parelles=pd.DataFrame(files_par, columns=COLS_PARELLA),
    )


# ─────────────────────────────────────────────────────────────────────────────
# VALIDACIÓ
# ─────────────────────────────────────────────────────────────────────────────
def _buit(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or v == ""


def validar(p: PartitCopa) -> tuple[list[str], list[str]]:
    """Retorna (errors, avisos). Els errors bloquegen l'enviament."""
    err, av = [], []
    et = p.etiqueta()

    if _buit(p.partit.get("match_id")):
        err.append(f"{et}: falta match_id")
    if _buit(p.partit.get("jornada")):
        av.append(f"{et}: sense jornada")

    # Camps obligatoris buits
    for nom, df, cols in (("equips", p.equips, COLS_EQUIP), ("jugadores", p.jugadores, COLS_JUGADORA)):
        for c in cols:
            if c in OPCIONALS:
                continue
            n = df[c].map(_buit).sum()
            if n:
                err.append(f"{et}: {n} valors buits a {nom}.{c}")

    if len(p.equips) != 2:
        err.append(f"{et}: hi ha {len(p.equips)} equips (n'esperava 2)")
        return err, av
    if p.jugadores.empty:
        err.append(f"{et}: no hi ha jugadores")
        return err, av

    num = lambda s: pd.to_numeric(s, errors="coerce").fillna(0)

    # Parelles: son opcionals, pero si n'hi ha han de referir-se a jugadores i
    # equips del partit, si no el hub creuaria dades que no existeixen.
    if not p.parelles.empty:
        noms = set(p.jugadores["jugadora"])
        equips_ok = set(p.equips["equip"])
        for _, r in p.parelles.iterrows():
            if r.equip not in equips_ok:
                err.append(f"{et}: parella amb equip desconegut '{r.equip}'")
            for c in ("jugadora_a", "jugadora_b"):
                if r[c] not in noms:
                    err.append(f"{et}: la parella {r.jugadora_a}/{r.jugadora_b} inclou '{r[c]}', que no surt a jugadores")
            if r.jugadora_a == r.jugadora_b:
                err.append(f"{et}: parella amb la mateixa jugadora dos cops ({r.jugadora_a})")

    for df, qui in ((p.equips, "equip"), (p.jugadores, "jugadora")):
        for c, i in (("t2c", "t2i"), ("t3c", "t3i"), ("tlc", "tli")):
            mal = df[num(df[c]) > num(df[i])]
            for _, f in mal.iterrows():
                err.append(f"{et}: {f[qui]} té {c} > {i}")

    # Coherència de punts
    for _, e in p.equips.iterrows():
        pts_tirs = 2 * num(pd.Series([e.t2c]))[0] + 3 * num(pd.Series([e.t3c]))[0] + num(pd.Series([e.tlc]))[0]
        if pts_tirs != e.pts:
            err.append(f"{et}: {e.equip} pts={e.pts} però els tirs sumen {pts_tirs}")
        jug = p.jugadores[p.jugadores.equip == e.equip]
        suma = num(jug.pts).sum()
        if suma != e.pts:
            av.append(f"{et}: {e.equip} pts={e.pts} però les jugadores sumen {suma:g}")
        quarts = sum(num(pd.Series([e[f"pts_q{q}"]]))[0] for q in range(1, 5)) + num(pd.Series([e.pts_pr]))[0]
        if quarts != e.pts:
            av.append(f"{et}: {e.equip} els quarts sumen {quarts:g} (pts={e.pts})")
        min_esperats = 200 + 25 * int(p.partit.get("prorrogues") or 0)
        mins = num(jug["min"]).sum()
        if abs(mins - min_esperats) > 2:
            av.append(f"{et}: {e.equip} suma {mins:.1f} min (n'esperava {min_esperats})")

    pts_calc = 2 * num(p.jugadores.t2c) + 3 * num(p.jugadores.t3c) + num(p.jugadores.tlc)
    for _, f in p.jugadores[pts_calc != num(p.jugadores.pts)].iterrows():
        err.append(f"{et}: {f.jugadora} pts no quadra amb els tirs")

    # Identitat de jugadores
    sense_id = p.jugadores.jugadora_id.map(_buit).sum()
    if sense_id:
        av.append(f"{et}: {sense_id} jugadores sense jugadora_id (s'usarà nom+equip)")
    clau = p.jugadores.apply(
        lambda f: f.jugadora_id if not _buit(f.jugadora_id) else f"{f.jugadora}|{f.equip}", axis=1
    )
    if clau.duplicated().any():
        err.append(f"{et}: jugadores duplicades: {', '.join(clau[clau.duplicated()])}")

    return err, av


# ─────────────────────────────────────────────────────────────────────────────
# ESCRIPTURA A GOOGLE SHEETS
# ─────────────────────────────────────────────────────────────────────────────
def obrir_full(credencials: dict, sheet_id: str):
    import gspread
    gc = gspread.service_account_from_dict(dict(credencials))
    return gc.open_by_key(sheet_id)


def _lletra_col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _natiu(v):
    """Converteix NaN i tipus numpy a valors que gspread pugui serialitzar."""
    if _buit(v):
        return ""
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float):
        v = round(v, 4)
        if v.is_integer():
            v = int(v)
    return v


def _a_files(df: pd.DataFrame, cols: list[str]) -> list[list]:
    return [[_natiu(v) for v in fila] for fila in df[cols].itertuples(index=False, name=None)]


def inicialitzar_full(sh) -> None:
    """Crea les pestanyes que falten amb la capçalera. Comprova les existents."""
    existents = {ws.title: ws for ws in sh.worksheets()}
    for nom, cols in ESQUEMA.items():
        if nom not in existents:
            ws = sh.add_worksheet(title=nom, rows=100, cols=len(cols))
            ws.update(range_name="A1", values=[cols])
            ws.freeze(rows=1)
        else:
            cap = existents[nom].row_values(1)
            if cap and cap != cols:
                raise RuntimeError(
                    f"La capçalera de '{nom}' no coincideix amb l'esquema v{VERSIO_ESQUEMA}. "
                    "No s'ha escrit res."
                )
            if not cap:
                existents[nom].update(range_name="A1", values=[cols])


def _substituir(ws, cols: list[str], match_ids: set[str], noves: list[list]) -> int:
    """
    Reescriu la pestanya conservant les files d'altres partits i posant les noves.
    Escriu primer i neteja després, perquè un error a mig camí no deixi la
    pestanya buida. Retorna quantes files s'han substituït.
    """
    valors = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    if not valors or valors[0] != cols:
        raise RuntimeError(f"Capçalera inesperada a '{ws.title}'. No s'ha escrit res.")
    idx = cols.index("match_id")
    ncol = len(cols)
    files = [(f + [""] * ncol)[:ncol] for f in valors[1:] if any(c != "" for c in f)]
    conservades = [f for f in files if str(f[idx]) not in match_ids]
    total = [cols] + conservades + noves

    if ws.row_count < len(total):
        ws.add_rows(len(total) - ws.row_count + 50)
    ws.update(range_name="A1", values=total, value_input_option="RAW")
    if len(valors) > len(total):
        ws.batch_clear([f"A{len(total) + 1}:{_lletra_col(ncol)}{len(valors)}"])
    return len(files) - len(conservades)


def ids_existents(sh) -> set[str]:
    try:
        return {str(v) for v in sh.worksheet("partits").col_values(1)[1:] if v}
    except Exception:
        return set()


def enviar_partits(sh, partits: list[PartitCopa]) -> dict:
    """Valida tots els partits i, si no hi ha errors, els escriu (substitució per match_id)."""
    errors = [e for p in partits for e in validar(p)[0]]
    if errors:
        raise ValueError("No s'ha enviat res:\n" + "\n".join(errors))

    inicialitzar_full(sh)
    ara = dt.datetime.now().isoformat(timespec="seconds")
    ids = {p.match_id for p in partits}
    existien = ids & ids_existents(sh)

    files_partits = []
    for p in partits:
        fila = {**p.partit, "enviat_at": ara, "versio_esquema": VERSIO_ESQUEMA}
        files_partits.append([_natiu(fila.get(c, "")) for c in COLS_PARTITS])
    df_eq = pd.concat([p.equips for p in partits], ignore_index=True)
    df_jug = pd.concat([p.jugadores for p in partits], ignore_index=True)
    df_par = pd.concat([p.parelles for p in partits], ignore_index=True)

    # Ordre: detall primer, 'partits' al final (és l'índex que llegeix el hub).
    _substituir(sh.worksheet("parella_partit"), COLS_PARELLA, ids, _a_files(df_par, COLS_PARELLA))
    _substituir(sh.worksheet("jugadora_partit"), COLS_JUGADORA, ids, _a_files(df_jug, COLS_JUGADORA))
    _substituir(sh.worksheet("equip_partit"), COLS_EQUIP, ids, _a_files(df_eq, COLS_EQUIP))
    _substituir(sh.worksheet("partits"), COLS_PARTITS, ids, files_partits)

    # Registra equips nous a 'equips' (nom_curt = nom FCBQ fins que l'editis)
    ws_eq = sh.worksheet("equips")
    coneguts = {str(v) for v in ws_eq.col_values(1)[1:]}
    nous = []
    for _, e in df_eq.drop_duplicates("equip").iterrows():
        if e.equip not in coneguts:
            nous.append([e.equip, _natiu(e.equip_id), e.equip])
    if nous:
        ws_eq.append_rows(nous, value_input_option="RAW")

    sh.worksheet("_log").append_rows([
        [ara, p.match_id, "substituit" if p.match_id in existien else "nou",
         len(p.equips), len(p.jugadores), VERSIO_ESQUEMA]
        for p in partits
    ], value_input_option="RAW")

    return {
        "partits": len(partits),
        "nous": len(ids - existien),
        "substituits": len(existien),
        "files_jugadora": len(df_jug),
        "files_parella": len(df_par),
        "equips_nous": [n[0] for n in nous],
    }


# ─────────────────────────────────────────────────────────────────────────────
# INTERFÍCIE STREAMLIT
# ─────────────────────────────────────────────────────────────────────────────
def render_boto_copa(partits: list[PartitCopa]) -> None:
    import streamlit as st

    st.subheader("📤 Enviar a la base COPA")
    if not partits:
        st.info("No hi ha partits carregats per enviar.")
        return

    cfg = st.secrets["copa"]

    sense_jornada = [p for p in partits if _buit(p.partit.get("jornada"))]
    if sense_jornada:
        jornada = st.number_input(
            f"Jornada per als {len(sense_jornada)} partits que no la porten",
            min_value=1, step=1, value=None,
        )
        if jornada:
            for p in sense_jornada:
                p.partit["jornada"] = int(jornada)
                p.equips["jornada"] = int(jornada)
                p.jugadores["jornada"] = int(jornada)

    try:
        sh = obrir_full(st.secrets["gcp_service_account"], cfg["sheet_id"])
        existents = ids_existents(sh)
    except Exception as ex:
        st.error(f"No puc connectar amb el Google Sheet: {ex}")
        return

    resum, tots_errors = [], []
    for p in partits:
        e, a = validar(p)
        tots_errors += e
        resum.append({
            "Partit": p.etiqueta(),
            "Data": p.partit["data"],
            "Jugadores": len(p.jugadores),
            "Estat": "🔁 Se substituirà" if p.match_id in existents else "🆕 Nou",
            "Avisos": len(a),
            "Errors": len(e),
        })
        for msg in a:
            st.warning(msg, icon="⚠️")
    st.dataframe(pd.DataFrame(resum), hide_index=True, use_container_width=True)
    for msg in tots_errors:
        st.error(msg)

    etiqueta = f"Envia {len(partits)} partit{'s' if len(partits) != 1 else ''} a {cfg['competicio']} {cfg['temporada']}"
    if st.button(etiqueta, type="primary", disabled=bool(tots_errors)):
        with st.spinner("Escrivint al Google Sheet…"):
            try:
                r = enviar_partits(sh, partits)
            except Exception as ex:
                st.error(f"Error en l'enviament: {ex}")
                return
        st.success(
            f"Fet: {r['nous']} partits nous, {r['substituits']} substituïts, "
            f"{r['files_jugadora']} files de jugadora."
        )
        if r["equips_nous"]:
            st.info("Equips nous afegits a la pestanya 'equips' (revisa'n el nom curt): "
                    + ", ".join(r["equips_nous"]))
