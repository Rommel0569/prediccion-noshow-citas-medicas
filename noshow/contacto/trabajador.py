"""Planificador autónomo: cada cierto tiempo recorre las citas registradas y gestiona todo según los datos de cada paciente.

Cada ciclo: (1) evalúa el riesgo de las citas futuras, (2) contacta por el canal verificado de cada paciente dentro de su
ventana de tiempo (Telegram, SMS con enlace, llamada o personal), (3) escala a llamada a quien no confirmó, y (4) libera los
cupos cancelados o sin confirmar y los ofrece a la lista de espera. Pacientes y citas nuevos se incorporan solos.
"""
import json
import threading
from collections import Counter
from datetime import datetime

from .. import parametros
from . import agenda_db, almacen, despacho, reasignacion

LIMITE_POR_CICLO = 200


def ciclo(canales, sistema, ahora=None, limite=LIMITE_POR_CICLO):
    ahora = ahora or datetime.now()
    cfg, nombre = parametros.cfg_activa(), parametros.establecimiento()
    horas = cfg.get("reasignacion", {}).get("horas_limite_confirmacion", 24)
    resumen = Counter()

    pendiente = agenda_db.construir(sistema, cfg, ahora.date(), estados=("agendada",))
    if not pendiente.empty:
        prog = despacho.plan(pendiente, canales, ahora, llamada_automatica=True)
        res, _ = despacho.ejecutar(prog, canales, nombre, limite)
        resumen.update(res)
    esc = despacho.plan_escalamiento(canales, ahora)
    if not esc.empty:
        res, _ = despacho.ejecutar(esc, canales, nombre, limite)
        resumen["escalamientos"] += sum(v for k, v in res.items() if k != "omitidos")

    todas = agenda_db.construir(sistema, cfg, ahora.date(), estados=agenda_db.FUTURAS)
    _, asignadas = reasignacion.reasignar(todas, canales, horas, ahora, nombre)
    resumen["cupos_reasignados"] += len(asignadas)

    almacen.guardar("trabajador_ultimo_ciclo", ahora.isoformat(timespec="seconds"))
    almacen.guardar("trabajador_resumen", json.dumps(dict(resumen)))
    return dict(resumen)


def bucle(canales, sistema, detener=None, cada=300):
    """Ejecuta un ciclo cada `cada` segundos hasta que se pida detener; un fallo no detiene el servicio."""
    detener = detener or threading.Event()
    while not detener.is_set():
        try:
            ciclo(canales, sistema)
        except Exception as e:                          # se registra y se reintenta en el siguiente ciclo
            almacen.guardar("trabajador_error", f"{datetime.now():%Y-%m-%d %H:%M:%S} {type(e).__name__}: {e}")
        detener.wait(cada)
