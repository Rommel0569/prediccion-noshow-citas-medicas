"""Plan y ejecución del contacto: convierte la agenda priorizada en envíos, llamadas pendientes y registro."""
import re
from collections import Counter

import pandas as pd

from . import almacen, mensajes
from .canales import ErrorCanal

# Días antes de la cita desde los que corresponde contactar (72 h para confirmar, 48 h para recordar)
VENTANA_DIAS = {"confirmacion": 3, "recordatorio": 2, "llamada": 3, "visita": 5}
ETIQUETA_TIPO = {"confirmacion": "Confirmación", "recordatorio": "Recordatorio", "llamada": "Llamada", "visita": "Visita"}


def limpiar_id(x):
    return re.sub(r"\.0$", "", str(x))


def _tipo(fila):
    canal = fila["canal_accion"]
    if canal in ("llamada", "visita"):
        return canal
    if canal in ("whatsapp", "sms"):
        return "confirmacion" if fila["nivel"] in ("medio", "alto") else "recordatorio"
    return None


def plan(agenda, canales, referencia, ignorar_ventana=False, llamada_automatica=False):
    """Una fila por contacto previsto, con su destino y si está listo para ejecutarse."""
    existentes = almacen.contactos_existentes()
    dest = almacen.destinatarios_activos()
    referencia = pd.Timestamp(referencia).normalize()
    filas = []
    for r in agenda.to_dict("records"):
        tipo = _tipo(r)
        if tipo is None:
            continue
        id_cita, id_pac = limpiar_id(r["id_cita"]), limpiar_id(r["id_paciente"])
        dias = (pd.Timestamp(r["fecha_cita"]).normalize() - referencia).days
        telefono, telegram = dest.get((id_pac, "telefono")), dest.get((id_pac, "telegram"))
        if tipo == "visita" or (tipo == "llamada" and not (llamada_automatica and telefono and canales.get("twilio"))):
            destino = "Personal (manual)"
        elif telegram and canales.get("telegram"):
            destino = "Telegram"
        elif telefono and canales.get("twilio"):
            destino = "Llamada automática" if tipo == "llamada" else "SMS"
        else:
            destino = "Sin destino registrado"
        if (id_cita, tipo) in existentes:
            estado = "Ya gestionado"
        elif dias < 0:
            estado = "Cita pasada"
        elif not ignorar_ventana and dias > VENTANA_DIAS[tipo]:
            estado = "Fuera de la ventana"
        elif destino == "Sin destino registrado":
            estado = "Sin destino"
        else:
            estado = "Listo"
        filas.append({"id_cita": id_cita, "id_paciente": id_pac, "tipo": tipo, "destino": destino, "estado": estado,
                      "fecha_cita": pd.Timestamp(r["fecha_cita"]), "servicio": r.get("servicio") or "",
                      "dias": dias, "nivel": r["nivel"]})
    return pd.DataFrame(filas, columns=["id_cita", "id_paciente", "tipo", "destino", "estado", "fecha_cita", "servicio",
                                        "dias", "nivel"])


def ejecutar(plan_df, canales, establecimiento, limite=None):
    """Ejecuta los contactos listos: envía por los canales conectados y deja pendientes las llamadas y visitas manuales."""
    resumen, errores = Counter(), []
    dest = almacen.destinatarios_activos()
    listos = plan_df[plan_df["estado"] == "Listo"]
    if limite:
        listos = listos.head(int(limite))
    for r in listos.to_dict("records"):
        tipo, f, s = r["tipo"], r["fecha_cita"], r["servicio"]
        base = (r["id_cita"], r["id_paciente"])
        try:
            if r["destino"] == "Personal (manual)":
                almacen.registrar_contacto(*base, tipo, tipo, f, "pendiente_manual")
                resumen["pendientes_manuales"] += 1
            elif r["destino"] == "Telegram":
                texto = (mensajes.confirmacion if tipo == "confirmacion" else mensajes.recordatorio)(f, s, establecimiento)
                ref = canales["telegram"].enviar(dest[(r["id_paciente"], "telegram")], texto, mensajes.botones_cita(r["id_cita"]))
                almacen.registrar_contacto(*base, "telegram", tipo, f, "enviado", referencia=ref)
                resumen["enviados_telegram"] += 1
            elif r["destino"] == "SMS":
                texto = (mensajes.confirmacion if tipo == "confirmacion" else mensajes.recordatorio)(f, s, establecimiento)
                ref = canales["twilio"].sms(dest[(r["id_paciente"], "telefono")], texto)
                almacen.registrar_contacto(*base, "sms", tipo, f, "enviado", referencia=ref)
                resumen["enviados_sms"] += 1
            elif r["destino"] == "Llamada automática":
                ref = canales["twilio"].llamar(dest[(r["id_paciente"], "telefono")], mensajes.llamada(f, s, establecimiento))
                almacen.registrar_contacto(*base, "llamada", tipo, f, "enviado", referencia=ref)
                resumen["llamadas_automaticas"] += 1
        except ErrorCanal as e:
            almacen.registrar_contacto(*base, r["destino"], tipo, f, "error", error=str(e))
            resumen["errores"] += 1
            errores.append(str(e))
    resumen["omitidos"] = int((plan_df["estado"] != "Listo").sum())
    return dict(resumen), errores
