"""Atención del bot: vinculación con el registro del paciente, verificación de su teléfono, bajas, confirmaciones
y respuestas a ofertas de cupo."""
import re
import threading
from collections import Counter

from . import almacen, conversacion, mensajes
from .canales import ErrorCanal

_CERROJO = threading.Lock()      # una sola atención a la vez: evita procesar dos veces la misma novedad
TECLADO_CONTACTO = {"keyboard": [[{"text": mensajes.BOTON_CONTACTO, "request_contact": True}]],
                    "resize_keyboard": True, "one_time_keyboard": True}
SIN_TECLADO = {"remove_keyboard": True}


def _digitos(x):
    return re.sub(r"\D", "", str(x or ""))


def mismo_telefono(a, b):
    """Compara teléfonos por sus últimos 9 dígitos (ignora prefijo de país y formato)."""
    a, b = _digitos(a), _digitos(b)
    return len(a) >= 9 and len(b) >= 9 and a[-9:] == b[-9:]


def _vincular(telegram, chat, codigo, cuenta):
    id_pac = almacen.consumir_vinculo(codigo)
    if id_pac is None:
        telegram.enviar(chat, mensajes.CODIGO_INVALIDO)
        return
    almacen.desactivar_destinatario(canal="telegram", destino=chat)      # un chat corresponde a un solo paciente
    tel = almacen.telefono_de_paciente(id_pac)
    if tel:     # el establecimiento ya tiene su teléfono: se verifica antes de activar los avisos
        almacen.registrar_destinatario(id_pac, "telegram", chat, verificado=0)
        telegram.enviar(chat, mensajes.VERIFICAR.format(fin=_digitos(tel)[-3:]), teclado=TECLADO_CONTACTO)
        cuenta["pendientes_verificacion"] += 1
    else:
        almacen.registrar_destinatario(id_pac, "telegram", chat, verificado=1)
        telegram.enviar(chat, mensajes.BIENVENIDA)
        cuenta["vinculados"] += 1


def _contacto(telegram, m, cuenta):
    chat, c = m["chat"]["id"], m["contact"]
    if c.get("user_id") != (m.get("from") or {}).get("id"):
        telegram.enviar(chat, mensajes.CONTACTO_AJENO, teclado=TECLADO_CONTACTO)
        return
    id_pac = almacen.id_por_destino("telegram", chat, solo_verificados=False)
    if not id_pac:
        telegram.enviar(chat, mensajes.SIN_CODIGO, teclado=SIN_TECLADO)
        return
    if mismo_telefono(c.get("phone_number"), almacen.telefono_de_paciente(id_pac)):
        almacen.verificar_destinatario(id_pac, "telegram")
        telegram.enviar(chat, mensajes.VERIFICADO, teclado=SIN_TECLADO)
        cuenta["vinculados"] += 1
    else:
        almacen.desactivar_destinatario(id_paciente=id_pac, canal="telegram")
        telegram.enviar(chat, mensajes.NO_COINCIDE, teclado=SIN_TECLADO)
        cuenta["no_coincide"] += 1


def _mensaje(telegram, m, cuenta):
    chat, texto = m["chat"]["id"], (m.get("text") or "").strip()
    if m.get("contact"):
        _contacto(telegram, m, cuenta)
    elif texto.startswith("/start"):
        partes = texto.split(maxsplit=1)
        if len(partes) < 2:
            telegram.enviar(chat, mensajes.SIN_CODIGO)
        else:
            _vincular(telegram, chat, partes[1].strip(), cuenta)
    elif texto.startswith("/baja"):
        almacen.desactivar_destinatario(canal="telegram", destino=chat)
        telegram.enviar(chat, mensajes.BAJA, teclado=SIN_TECLADO)
        cuenta["bajas"] += 1
    elif texto:
        id_pac = almacen.id_por_destino("telegram", chat)
        if id_pac:      # paciente verificado: conversación libre sobre sus citas
            r = conversacion.responder(id_pac, texto)
            telegram.enviar(chat, r["texto"], r["botones"])
            cuenta["conversaciones"] += 1
            if r["accion"] == "baja":
                almacen.desactivar_destinatario(canal="telegram", destino=chat)
                cuenta["bajas"] += 1
        elif almacen.id_por_destino("telegram", chat, solo_verificados=False):
            telegram.enviar(chat, mensajes.FALTA_VERIFICAR, teclado=TECLADO_CONTACTO)
        else:
            telegram.enviar(chat, mensajes.SIN_CODIGO)


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
    elif tipo == "q" and valor in ("s", "n"):
        r = conversacion.resolver_cancelacion(propietario, ident, valor == "s")
        telegram.responder_callback(q["id"], "Listo")
        telegram.enviar(chat, r["texto"])
        cuenta["respuestas"] += 1
    elif tipo == "a" and valor in ("s", "n"):
        r = almacen.obtener_reasignacion(ident)
        if not r or almacen.paciente_de_espera(r["id_espera"]) != propietario or r["estado"] != "ofrecida":
            return
        if valor == "s":
            almacen.actualizar_reasignacion(ident, "aceptada")
            almacen.actualizar_espera(r["id_espera"], "asignado")
            original = almacen.obtener_cita(r["id_cita"]) or {}
            almacen.agendar_cita(propietario, r["fecha_cita"], r["servicio"], original.get("turno", ""))
            telegram.responder_callback(q["id"], "Cupo asignado. El establecimiento le confirmará los detalles.")
        else:
            almacen.actualizar_reasignacion(ident, "rechazada")
            almacen.actualizar_espera(r["id_espera"], "esperando")
            telegram.responder_callback(q["id"], "Entendido. Seguirá en la lista de espera.")
        cuenta["ofertas_respondidas"] += 1


def procesar(telegram, espera=0):
    """Lee las novedades del bot y las atiende. Con `espera` > 0 aguarda hasta ese número de segundos a que llegue algo."""
    with _CERROJO:
        cuenta = Counter()
        offset = almacen.leer("telegram_offset")
        novedades = telegram.actualizaciones(int(offset) if offset else None, espera)
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



