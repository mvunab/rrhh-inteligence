import json

import pytest

from harness.calculos import (
    calcular_descuentos,
    comparar_con_liquidacion,
    gratificacion_art50,
    impuesto_unico,
    tasa_afp,
    tasa_seguro_cesantia,
    tope_gratificacion_mensual,
    tope_imponible_pesos,
)
from harness.config import DATA_DIR
from harness.datos import cargar_liquidaciones, cargar_trabajadores


def test_topes_en_pesos(params):
    assert tope_imponible_pesos(params, "afp_salud") == 3_695_148      # 90 UF x 41.057,20
    assert tope_imponible_pesos(params, "seguro_cesantia") == 5_550_933  # 135,2 UF
    assert tope_gratificacion_mensual(params) == 219_115               # 4,75 IMM / 12


def test_gratificacion_con_y_sin_tope(params):
    assert gratificacion_art50(params, 1_000_000) == 219_115  # 25% = 250.000 -> tope
    assert gratificacion_art50(params, 780_000) == 195_000    # 25% bajo el tope


def test_tasas(params):
    assert float(tasa_afp(params, "Habitat")) == pytest.approx(0.1127)
    assert float(tasa_seguro_cesantia(params, "indefinido")) == pytest.approx(0.006)
    assert float(tasa_seguro_cesantia(params, "plazo_fijo")) == 0
    with pytest.raises(ValueError):
        tasa_afp(params, "AFPInexistente")


@pytest.mark.parametrize("base, esperado", [
    (0, 0), (974_038, 0), (989_067, 601), (5_000_000, 351_042),
])
def test_impuesto_unico(params, base, esperado):
    assert impuesto_unico(params, base) == esperado


def test_tope_se_aplica_a_afp_y_salud(params):
    t = cargar_trabajadores()["W003"]
    calc = calcular_descuentos(params, t, 4_719_115)
    afp = next(l for l in calc["lineas"] if l["codigo"] == "afp")
    sc = next(l for l in calc["lineas"] if l["codigo"] == "seguro_cesantia")
    assert afp["base"] == 3_695_148          # topado
    assert sc["base"] == 4_719_115           # su tope es mayor: no se topa


def test_plazo_fijo_no_paga_seguro_de_cesantia(params):
    t = cargar_trabajadores()["W004"]
    calc = calcular_descuentos(params, t, 775_000)
    assert next(l for l in calc["lineas"] if l["codigo"] == "seguro_cesantia")["monto"] == 0


def test_errores_sembrados_coinciden_con_el_fixture(params, errores_sembrados):
    trabajadores = cargar_trabajadores()
    for liq in cargar_liquidaciones():
        if liq["periodo"] != errores_sembrados["periodo"]:
            continue
        cmp = comparar_con_liquidacion(params, trabajadores[liq["worker_id"]], liq)
        con_dif = sorted(f["codigo"] for f in cmp["lineas"] if f["estado"] == "diferencia")
        derivadas = sorted(f["codigo"] for f in cmp["lineas"] if f["estado"] == "derivada")
        esperado = errores_sembrados[liq["worker_id"]]
        assert con_dif == sorted(esperado["lineas_con_diferencia"]), liq["worker_id"]
        assert derivadas == sorted(esperado["derivadas"]), liq["worker_id"]


def test_agosto_esta_limpio(params):
    trabajadores = cargar_trabajadores()
    for liq in cargar_liquidaciones():
        if liq["periodo"] == "2026-08":
            assert not comparar_con_liquidacion(params, trabajadores[liq["worker_id"]], liq)["hay_diferencias"]


def test_causas_probables(params):
    trabajadores, liqs = cargar_trabajadores(), cargar_liquidaciones()
    def fila(wid, codigo):
        liq = next(l for l in liqs if l["worker_id"] == wid and l["periodo"] == "2026-09")
        return next(f for f in comparar_con_liquidacion(params, trabajadores[wid], liq)["lineas"] if f["codigo"] == codigo)
    assert "ProVida" in fila("W001", "afp")["causa_probable"] and "Habitat" in fila("W001", "afp")["causa_probable"]
    assert "tope" in fila("W003", "afp")["causa_probable"]
    assert "plazo fijo" in fila("W004", "seguro_cesantia")["causa_probable"]


def test_liquidaciones_son_consistentes():
    for liq in cargar_liquidaciones():
        assert liq["total_haberes"] == sum(h["monto"] for h in liq["haberes_imponibles"] + liq["haberes_no_imponibles"])
        assert liq["total_descuentos"] == sum(d["monto"] for d in liq["descuentos_legales"])
        assert liq["liquido_a_pagar"] == liq["total_haberes"] - liq["total_descuentos"]


def test_parametros_tienen_fuente_y_fecha(params):
    for clave in ("uf", "utm", "ingreso_minimo", "topes_uf", "comisiones_afp", "impuesto_unico", "gratificacion"):
        assert "fuente" in params[clave], clave
    assert params["fecha_verificacion"]
