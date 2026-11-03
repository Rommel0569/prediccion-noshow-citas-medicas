"""Liberación de cupos según las respuestas reales y reasignación a la lista de espera registrada."""
from datetime import datetime, time

import pandas as pd

from . import almacen, mensajes
from .canales import ErrorCanal
from .despacho import limpiar_id

HORA_CONSULTA = 8     # hora de inicio supuesta de la consulta para medir el plazo de confirmación
COLUMNAS = ["id_cita", "fecha_cita", "servicio", "motivo"]


def cupos_liberables(agenda, horas_limite, referencia):
    """Cupos que deben liberarse: el paciente canceló o pidió reprogramar (cualquier riesgo), o una cita priorizada
    (llamada o riesgo alto) no se confirmó dentro del plazo."""
    contactos = almacen.listar_contactos()
    info = {}      # id_cita -> (fecha, servicio, priorizada)
    for r in agenda.to_dict("records"):
        info[limpiar_id(r["id_cita"])] = (pd.Timestamp(r["fecha_cita"]).date(), r.get("servicio") or "",
                                          bool(r.get("prioridad_llamada")) or r.get("nivel") == "alto")
    respuestas = {}
    if not contactos.empty:
        ok = contactos[contactos["estado"].isin(["enviado", "pendiente_manual", "realizado"]) & (contactos["id_cita"] != "")]
        respuestas = {k: set(s.dropna()) for k, s in ok.groupby("id_cita")["respuesta"]}
        for id_cita, c in ((i, almacen.obtener_cita(i)) for i in respuestas if i not in info):
            if c:
                info[id_cita] = (datetime.fromisoformat(c["fecha_cita"]).date(), c["servicio"] or "", False)
    for c in almacen.listar_citas().to_dict("records"):          # cancelaciones hechas por el bot sin contacto previo
        if c["estado"] in ("cancelada", "reprogramacion_solicitada"):
            info.setdefault(c["id_cita"], (datetime.fromisoformat(c["fecha_cita"]).date(), c["servicio"] or "", False))
            respuestas.setdefault(c["id_cita"], set()).add("cancelo" if c["estado"] == "cancelada" else "reprogramo")
    filas = []
    for id_cita, resp in respuestas.items():
        if id_cita not in info:
            continue
        fecha, servicio, priorizada = info[id_cita]
        registrada = almacen.obtener_cita(id_cita)
        servicio = (registrada or {}).get("servicio") or servicio          # la especialidad tal como se registró
        if resp & {"cancelo", "reprogramo"}:
            motivo = "Cancelada o reprogramada por el paciente"
        elif "confirmo" in resp or not priorizada:
            continue
        else:
            horas = (datetime.combine(fecha, time(HORA_CONSULTA)) - referencia).total_seconds() / 3600
            if not 0 <= horas <= horas_limite:
                continue
            motivo = f"Sin confirmación a {horas_limite} h de la cita"
        if fecha >= referencia.date():                                        # solo cupos de hoy en adelante
            filas.append({"id_cita": id_cita, "fecha_cita": fecha, "servicio": servicio, "motivo": motivo})
    return pd.DataFrame(filas, columns=COLUMNAS)


def reasignar(agenda, canales, horas_limite, referencia, establecimiento):
    """Asigna cada cupo liberable al paciente que más espera (misma especialidad) y le ofrece el cupo."""
    liberables = cupos_liberables(agenda, horas_limite, referencia)
    espera = almacen.listar_espera()
    espera = espera[espera["estado"] == "esperando"].sort_values("ingreso") if not espera.empty else espera
    vigentes = almacen.reasignaciones_vigentes()
    dest = almacen.destinatarios_activos()
    resultado = []
    for cupo in liberables.to_dict("records"):
        if cupo["id_cita"] in vigentes:
            continue
        if espera.empty:
            resultado.append({**cupo, "resultado": "Sin candidato en lista de espera"})
            continue
        servicio = str(cupo["servicio"]).upper()
        compatibles = espera[(espera["servicio"] == "") | (servicio == "") | (espera["servicio"].str.upper() == servicio)]
        if compatibles.empty:
            resultado.append({**cupo, "resultado": "Sin candidato de la misma especialidad"})
            continue
        elegido = compatibles.iloc[0]
        espera = espera.drop(compatibles.index[0])
        chat = dest.get((elegido["id_paciente"], "telegram"))
        if chat and canales.get("telegram"):
            rid = almacen.crear_reasignacion(cupo["id_cita"], cupo["fecha_cita"], cupo["servicio"], cupo["motivo"],
                                             elegido["id_espera"], "ofrecida")
            try:
                canales["telegram"].enviar(chat, mensajes.oferta_cupo(cupo["fecha_cita"], cupo["servicio"], establecimiento),
                                           mensajes.botones_oferta(rid))
                almacen.actualizar_espera(elegido["id_espera"], "ofrecido")
                res = "Oferta enviada por Telegram"
            except ErrorCanal as e:
                almacen.actualizar_reasignacion(rid, "asignada_manual")
                almacen.actualizar_espera(elegido["id_espera"], "ofrecido")
                res = f"Asignada; el aviso falló, informar manualmente ({e})"
        else:
            almacen.crear_reasignacion(cupo["id_cita"], cupo["fecha_cita"], cupo["servicio"], cupo["motivo"],
                                       elegido["id_espera"], "asignada_manual")
            almacen.actualizar_espera(elegido["id_espera"], "ofrecido")
            res = "Asignada; informar al paciente manualmente"
        resultado.append({**cupo, "id_espera": elegido["id_espera"], "resultado": res})
    return liberables, pd.DataFrame(resultado)


