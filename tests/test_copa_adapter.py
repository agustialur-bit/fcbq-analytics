"""
Comprova que el que s'envia a la base COPA quadra amb el que Micki ja calcula.

No toca la xarxa: carrega un partit real desat a tests/fixtures/ i compara les
files generades contra les mateixes funcions d'analitica_core que alimenten les
pestanyes de l'app. Si algú canvia un càlcul en un lloc i no a l'altre, aquí peta.

    python -m pytest tests/test_copa_adapter.py -q
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ARREL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ARREL))

import analitica_core as ac              # noqa: E402
from copa_adapter import partit_a_copa   # noqa: E402
from copa_sync import (                  # noqa: E402
    COLS_EQUIP, COLS_JUGADORA, COLS_PARELLA, VERSIO_ESQUEMA, validar,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def dades():
    meta = json.loads((FIXTURES / "partit_2477497.json").read_text(encoding="utf-8"))
    # dtype=str a idEquip: si no, pandas els llegeix com a float i surten "981415.0"
    df = pd.read_csv(FIXTURES / "partit_2477497.csv", encoding="utf-8",
                     dtype={"idEquip": str, "dorsal": str})
    df["idEquip"] = df["idEquip"].astype(str)
    df["jugador"] = df["jugador"].fillna("").astype(str)
    return df, meta


@pytest.fixture(scope="module")
def partit(dades):
    df, meta = dades
    return partit_a_copa(
        df,
        match_id=meta["match_id"],
        temporada="2026-27",
        competicio="COPA",
        data=meta["data"],
        jornada=meta["jornada"],
        noms_equips=meta["team_names"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Estructura
# ─────────────────────────────────────────────────────────────────────────────
def test_no_hi_ha_errors_de_validacio(partit):
    errors, _ = validar(partit)
    assert errors == [], "\n".join(errors)


def test_columnes_i_mides(partit):
    assert list(partit.equips.columns) == COLS_EQUIP
    assert list(partit.jugadores.columns) == COLS_JUGADORA
    assert list(partit.parelles.columns) == COLS_PARELLA
    assert len(partit.equips) == 2
    assert not partit.jugadores.empty
    assert partit.partit["versio_esquema"] == VERSIO_ESQUEMA


def test_la_data_es_la_del_partit_no_la_d_avui(partit, dades):
    _, meta = dades
    assert partit.partit["data"] == meta["data"]
    assert partit.partit["data"] != pd.Timestamp.today().strftime("%Y-%m-%d")


def test_els_equips_surten_amb_nom_no_amb_identificador(partit, dades):
    """El que va fallar la primera vegada: els noms han de ser els de la FCBQ."""
    _, meta = dades
    esperats = set(meta["team_names"].values())
    assert set(partit.equips["equip"]) == esperats
    assert set(partit.jugadores["equip"]) <= esperats
    assert partit.partit["local"] in esperats
    assert partit.partit["visitant"] in esperats


def test_match_id_obligatori(dades):
    df, meta = dades
    with pytest.raises(ValueError, match="match_id"):
        partit_a_copa(df, match_id="", temporada="2026-27", competicio="COPA",
                      data=meta["data"], noms_equips=meta["team_names"])


def test_sense_data_no_s_inventa_res(dades):
    """Guardar una data inventada corromp la base: val més que peti."""
    df, meta = dades
    with pytest.raises(ValueError, match="data"):
        partit_a_copa(df, match_id=meta["match_id"], temporada="2026-27",
                      competicio="COPA", noms_equips=meta["team_names"])


# ─────────────────────────────────────────────────────────────────────────────
# Equips: han de quadrar amb 📊 Partits
# ─────────────────────────────────────────────────────────────────────────────
def test_equips_punts_i_possessions(partit, dades):
    df, meta = dades
    for _, fila in partit.equips.iterrows():
        eq_id = str(fila["equip_id"])
        df_eq = df[df["idEquip"] == eq_id]
        assert fila["pts"] == int(df_eq["punts"].sum())
        assert fila["poss"] == pytest.approx(ac.calc_possessions(df_eq), abs=0.01)


def test_equips_els_tirs_reconstrueixen_els_punts(partit):
    for _, f in partit.equips.iterrows():
        assert 2 * f["t2c"] + 3 * f["t3c"] + f["tlc"] == f["pts"]


def test_equips_ts_coincideix_amb_el_calcul_de_micki(partit, dades):
    df, _ = dades
    for _, f in partit.equips.iterrows():
        df_eq = df[df["idEquip"] == str(f["equip_id"])]
        tci, tli = ac.compta_tirs(df_eq)
        esperat = f["pts"] / (2 * (tci + 0.44 * tli)) * 100
        # TS% recalculat des de les files enviades (el que farà el hub)
        obtingut = f["pts"] / (2 * ((f["t2i"] + f["t3i"]) + 0.44 * f["tli"])) * 100
        assert obtingut == pytest.approx(esperat, abs=0.01)


def test_quarts_sumen_el_total(partit):
    for _, f in partit.equips.iterrows():
        suma = f["pts_q1"] + f["pts_q2"] + f["pts_q3"] + f["pts_q4"] + f["pts_pr"]
        assert suma == f["pts"]


def test_el_marcador_del_partit_quadra_amb_els_equips(partit):
    p, eq = partit.partit, partit.equips
    assert p["pts_local"] == int(eq[eq.equip == p["local"]].iloc[0]["pts"])
    assert p["pts_visitant"] == int(eq[eq.equip == p["visitant"]].iloc[0]["pts"])


# ─────────────────────────────────────────────────────────────────────────────
# Jugadores: minuts i +/- han de quadrar amb Rotacions, tirs amb 🎯 Eficiència
# ─────────────────────────────────────────────────────────────────────────────
def test_minuts_iguals_als_de_calc_minuts_reals(partit, dades):
    df, _ = dades
    minuts = ac.calc_minuts_reals(df)
    for _, j in partit.jugadores.iterrows():
        assert j["min"] == pytest.approx(round(minuts.get(j["jugadora"], 0.0), 1), abs=0.05)


def test_tirs_per_jugadora_iguals_als_de_get_shot_counts(partit, dades):
    df, _ = dades
    for _, j in partit.jugadores.iterrows():
        df_j = df[(df["jugador"] == j["jugadora"]) & (df["idEquip"] == str(j["equip_id"]))]
        v1m, v1x, v2m, v2x, v3m, v3x = ac.get_shot_counts(df_j)
        assert (j["t2c"], j["t2i"]) == (v2m, v2m + v2x)
        assert (j["t3c"], j["t3i"]) == (v3m, v3m + v3x)
        assert (j["tlc"], j["tli"]) == (v1m, v1m + v1x)
        assert 2 * j["t2c"] + 3 * j["t3c"] + j["tlc"] == j["pts"]


def test_els_punts_de_les_jugadores_sumen_els_de_l_equip(partit):
    for _, e in partit.equips.iterrows():
        seves = partit.jugadores[partit.jugadores.equip == e["equip"]]
        assert seves["pts"].sum() == e["pts"]


def test_on_coincideix_amb_calc_onoff_raw(partit, dades):
    """El +/- i l'On/Off del hub surten d'aquests quatre camps."""
    df, _ = dades
    teams = ac.get_teams_ordered(df)
    for _, j in partit.jugadores.iterrows():
        raw = ac.calc_onoff_raw(df, j["jugadora"], str(j["equip_id"]), teams)
        if raw is None:
            continue
        assert j["eq_pts_on"] == raw["pts_on"]
        assert j["eq_pts_contra_on"] == raw["pts_on_riv"]
        assert j["eq_poss_on"] == pytest.approx(raw["poss_on"], abs=0.01)
        assert j["eq_poss_rival_on"] == pytest.approx(raw["poss_on_riv"], abs=0.01)
        assert j["eq_tci_on"] == raw["tci_on"]
        assert j["eq_tli_on"] == raw["tli_on"]


def test_el_hub_pot_deduir_l_off_restant_on_del_total(partit, dades):
    """
    La clau de tot l'esquema: els valors OFF no es desen, el hub els dedueix com
    a total de l'equip menys ON. Això només funciona si els dos surten del
    mateix recompte d'esdeveniments.
    """
    df, _ = dades
    teams = ac.get_teams_ordered(df)
    for _, e in partit.equips.iterrows():
        eq_id = str(e["equip_id"])
        df_eq = df[df["idEquip"] == eq_id]
        tci_eq, tli_eq = ac.compta_tirs(df_eq)
        for _, j in partit.jugadores[partit.jugadores.equip == e["equip"]].iterrows():
            raw = ac.calc_onoff_raw(df, j["jugadora"], eq_id, teams)
            if raw is None:
                continue
            assert j["eq_pts_on"] + raw["pts_off"] == e["pts"]
            assert j["eq_tci_on"] + raw["tci_off"] == tci_eq
            assert j["eq_tli_on"] + raw["tli_off"] == tli_eq
            assert j["eq_poss_on"] + raw["poss_off"] == pytest.approx(e["poss"], abs=0.02)


def test_usage_recalculat_des_de_les_files(partit, dades):
    """L'Usage del hub ha de donar el mateix que calc_usage_rate de Micki."""
    df, _ = dades
    for _, j in partit.jugadores.iterrows():
        if j["eq_tci_on"] == 0 and j["eq_tli_on"] == 0:
            continue
        obtingut = ((j["t2i"] + j["t3i"]) + 0.44 * j["tli"]) / \
                   (j["eq_tci_on"] + 0.44 * j["eq_tli_on"]) * 100
        assert 0 <= obtingut <= 100.001, (j["jugadora"], obtingut)


# ─────────────────────────────────────────────────────────────────────────────
# Parelles
# ─────────────────────────────────────────────────────────────────────────────
def test_parelles_coherents(partit):
    noms = set(partit.jugadores["jugadora"])
    equips = set(partit.equips["equip"])
    assert not partit.parelles.empty, "el partit hauria de tenir parelles amb minuts"
    for _, r in partit.parelles.iterrows():
        assert r["jugadora_a"] in noms and r["jugadora_b"] in noms
        assert r["jugadora_a"] < r["jugadora_b"], "han d'anar en ordre alfabètic"
        assert r["equip"] in equips
        assert r["min"] > 0


def test_min_ind_i_pm_ind_venen_del_motor_de_parelles(partit, dades):
    """
    El grafic de contribucio per companya compara la barra (+/- amb la
    companya) amb el diamant (mitjana propia d'aquella companya). Els dos han
    de sortir del MATEIX motor: si el diamant es calcules des d'eq_pts_on,
    difereix en algunes jugadores i el grafic es contradiria amb Micki.
    """
    df, _ = dades
    ind = {}
    for r in ac.calc_pm_combinacions(df, mode="individual"):
        if len(r["combinacio"]) == 1:
            ind[(str(r["equip"]), r["combinacio"][0])] = r

    comprovades = 0
    for _, j in partit.jugadores.iterrows():
        r = ind.get((str(j["equip_id"]), j["jugadora"]))
        if not r:
            continue
        comprovades += 1
        assert j["min_ind"] == pytest.approx(round(r["minuts"], 1), abs=0.05)
        assert j["pm_ind"] == r["pm"]
    assert comprovades > 0


def test_parelles_i_individual_son_coherents(partit):
    """Els minuts d'una parella mai poden passar dels de cap de les dues."""
    mins = {(r["equip"], r["jugadora"]): r["min_ind"]
            for _, r in partit.jugadores.iterrows()}
    for _, p in partit.parelles.iterrows():
        for qui in (p["jugadora_a"], p["jugadora_b"]):
            propi = mins.get((p["equip"], qui))
            if propi is None:
                continue
            assert p["min"] <= propi + 0.15, (p["jugadora_a"], p["jugadora_b"], qui)


def test_parelles_filtrades_pel_minim(dades):
    df, meta = dades
    comu = dict(match_id=meta["match_id"], temporada="2026-27", competicio="COPA",
                data=meta["data"], noms_equips=meta["team_names"])
    poques = partit_a_copa(df, min_minuts_parella=20.0, **comu)
    moltes = partit_a_copa(df, min_minuts_parella=0.0, **comu)
    assert len(poques.parelles) < len(moltes.parelles)
    assert poques.parelles["min"].min() >= 20.0
