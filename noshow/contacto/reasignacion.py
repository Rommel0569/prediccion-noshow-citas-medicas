"""Liberación de cupos según las respuestas reales y reasignación a la lista de espera registrada."""
from datetime import datetime, time

import pandas as pd

from . import almacen, mensajes
from .canales import ErrorCanal
from .despacho import limpiar_id

HORA_CONSULTA = 8     # hora de inicio supuesta de la consulta para medir el plazo de confirmación


def cupos_liberables(agenda, horas_limite, referencia):
    """Citas priorizadas cuyo cupo debe liberarse: el paciente canceló o reprogramó, o no confirmó dentro del plazo."""
    contactos = almacen.listar_contactos()
    if contactos.empty:
        return pd.DataFrame(columns=["id_cita", "fecha_cita", "servicio", "motivo"])
    contactos["id_cita"] = contactos["id_cita"].astype(str)
    prior = agenda[(agenda["prioridad_llamada"]) | (agenda["nivel"] == "alto")]
    prior = prior[prior["canal_accion"] != "ninguno"]
    filas = []
    for r in prior.to_dict("records"):
        id_cita = limpiar_id(r["id_cita"])
        c = contactos[contactos["id_cita"] == id_cita]
        c = c[c["estado"].isin(["enviado", "pendiente_manual", "realizado"])]
        if c.empty:
            continue
        resp = set(c["respuesta"].dropna())
        if resp & {"cancelo", "reprogramo"}:
            motivo = "Cancelada o reprogramada por el paciente"
        elif "confirmo" in resp:
            continue
        else:
            inicio = datetime.combine(pd.Timestamp(r["fecha_cita"]).date(), time(HORA_CONSULTA))
            horas = (inicio - referencia).total_seconds() / 3600
            if not 0 <= horas <= horas_limite:
                continue
            motivo = f"Sin confirmación a {horas_limite} h de la cita"
        filas.append({"id_cita": id_cita, "fecha_cita": pd.Timestamp(r["fecha_cita"]).date(),
                      "servicio": r.get("servicio") or "", "motivo": motivo})
    return pd.DataFrame(filas, columns=["id_cita", "fecha_cita", "servicio", "motivo"])


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
        compatibles = espera[(espera["servicio"] == "") | (cupo["servicio"] == "") | (espera["servicio"] == cupo["servicio"])]
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
