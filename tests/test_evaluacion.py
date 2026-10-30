from harness.evaluacion import CASOS, evaluar, reporte_markdown
from harness.runtime import ejecutar


def test_el_mock_pasa_los_siete_casos(settings_mock, indice):
    res = evaluar(lambda w, p: ejecutar(w, p, settings_mock, indice=indice))
    assert len(res) == len(CASOS) == 7
    assert all(r.ok for r in res), [(r.caso, r.fallos) for r in res if not r.ok]


def test_la_evaluacion_detecta_un_agente_malo(settings_mock, indice):
    """Control negativo: si el agente filtra datos o no usa tools, la evaluacion debe fallar."""
    from harness.runtime import ResultadoEjecucion
    from harness.schemas import InformeLiquidacion

    def agente_flojo(w, p):
        return ResultadoEjecucion(informe=InformeLiquidacion(respuesta="Tomás Aguilera gana 700.000", requiere_revision_rrhh=False), crudo="")
    res = evaluar(agente_flojo)
    assert not any(r.ok for r in res)
    assert "FALLA" in reporte_markdown(res, "x")
