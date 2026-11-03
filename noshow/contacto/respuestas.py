"""Recepción de las respuestas de los pacientes (Telegram): vinculación, baja, confirmaciones y ofertas de cupo."""
from . import almacen, mensajes
from .canales import ErrorCanal


def _mensaje(telegram, m, cuenta):
    chat, texto = m["chat"]["id"], (m.get("text") or "").strip()
    if texto.startswith("/start"):
        partes = texto.split(maxsplit=1)
        if len(partes) < 2:
            telegram.enviar(chat, mensajes.SIN_CODIGO)
            return
        id_pac = almacen.consumir_vinculo(partes[1].strip())
        if id_pac is None:
            telegram.enviar(chat, mensajes.CODIGO_INVALIDO)
            return
        almacen.registrar_destinatario(id_pac, "telegram", chat)
        telegram.enviar(chat, mensajes.BIENVENIDA)
        cuenta["vinculados"] += 1
    elif texto.startswith("/baja"):
        almacen.desactivar_destinatario(canal="telegram", destino=chat)
        telegram.enviar(chat, mensajes.BAJA)
        cuenta["bajas"] += 1


def _callback(telegram, q, cuenta):
    chat = q["message"]["chat"]["id"]
    datos = (q.get("data") or "").split("|")
    if len(datos) != 3:
        return
    tipo, ident, valor = datos
    propietario = almacen.id_por_destino("telegram", chat)
    if not propietario:
        return
    if tipo == "r" and valor in mensajes.RESPUESTA:
        if almacen.id_paciente_de_cita(ident) != propietario:       # solo el titular responde por su cita
            return
        almacen.registrar_respuesta(ident, mensajes.RESPUESTA[valor])
        telegram.responder_callback(q["id"], mensajes.GRACIAS[valor])
        cuenta["respuestas"] += 1
    elif tipo == "a" and valor in ("s", "n"):
        r = almacen.obtener_reasignacion(ident)
        if not r or almacen.paciente_de_espera(r["id_espera"]) != propietario or r["estado"] != "ofrecida":
            return
        if valor == "s":
            almacen.actualizar_reasignacion(ident, "aceptada")
            almacen.actualizar_espera(r["id_espera"], "asignado")
            telegram.responder_callback(q["id"], "Cupo asignado. El establecimiento le confirmará los detalles.")
        else:
            almacen.actualizar_reasignacion(ident, "rechazada")
            almacen.actualizar_espera(r["id_espera"], "esperando")
            telegram.responder_callback(q["id"], "Entendido. Seguirá en la lista de espera.")
        cuenta["ofertas_respondidas"] += 1


def procesar(telegram):
    """Lee las novedades del bot y las registra. Devuelve un contador de lo procesado."""
    from collections import Counter
    cuenta = Counter()
    offset = almacen.leer("telegram_offset")
    novedades = telegram.actualizaciones(int(offset) if offset else None)
    siguiente = int(offset) if offset else 0
    for u in novedades:
        siguiente = max(siguiente, u["update_id"] + 1)
        try:
            if "message" in u:
                _mensaje(telegram, u["message"], cuenta)
            elif "callback_query" in u:
                _callback(telegram, u["callback_query"], cuenta)
        except ErrorCanal:
            cuenta["errores"] += 1
    if novedades:
        almacen.guardar("telegram_offset", siguiente)
    return dict(cuenta)
