"""Conectores de los canales de contacto: Telegram (envío y recepción de respuestas) y Twilio (SMS y llamadas).

Las credenciales se leen de variables de entorno o de config/canales.local.yaml (fuera del repositorio).
"""
import os
from xml.sax.saxutils import escape

import requests
import yaml

from ..config import RAIZ

TIEMPO_ESPERA = 15


class ErrorCanal(Exception):
    """Fallo al usar un canal (red, credenciales o rechazo del proveedor)."""


class Telegram:
    nombre = "telegram"

    def __init__(self, token, base="https://api.telegram.org"):
        self.token, self.base = token, base.rstrip("/")

    def _llamar(self, metodo, **datos):
        try:
            r = requests.post(f"{self.base}/bot{self.token}/{metodo}", json=datos, timeout=TIEMPO_ESPERA)
            j = r.json()
        except (requests.RequestException, ValueError) as e:
            raise ErrorCanal(f"Telegram: {e}") from e
        if not j.get("ok"):
            raise ErrorCanal(f"Telegram: {j.get('description', r.status_code)}")
        return j["result"]

    def info(self):
        return self._llamar("getMe")

    def enviar(self, chat_id, texto, botones=None):
        """Envía un mensaje; `botones` es una lista de filas de (texto, callback_data). Devuelve el id del mensaje."""
        datos = {"chat_id": chat_id, "text": texto}
        if botones:
            datos["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in fila] for fila in botones]}
        return str(self._llamar("sendMessage", **datos)["message_id"])

    def actualizaciones(self, offset=None):
        datos = {"timeout": 0, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            datos["offset"] = offset
        return self._llamar("getUpdates", **datos)

    def responder_callback(self, id_callback, texto):
        self._llamar("answerCallbackQuery", callback_query_id=id_callback, text=texto)


class Twilio:
    nombre = "twilio"

    def __init__(self, sid, token, desde, base="https://api.twilio.com"):
        self.sid, self.token, self.desde, self.base = sid, token, desde, base.rstrip("/")

    def _crear(self, recurso, datos):
        try:
            r = requests.post(f"{self.base}/2010-04-01/Accounts/{self.sid}/{recurso}.json", data=datos,
                              auth=(self.sid, self.token), timeout=TIEMPO_ESPERA)
            j = r.json()
        except (requests.RequestException, ValueError) as e:
            raise ErrorCanal(f"Twilio: {e}") from e
        if r.status_code >= 300:
            raise ErrorCanal(f"Twilio: {j.get('message', r.status_code)}")
        return j["sid"]

    def sms(self, a, texto):
        return self._crear("Messages", {"To": a, "From": self.desde, "Body": texto})

    def llamar(self, a, texto):
        """Llamada con un mensaje hablado (sin captura de respuesta)."""
        twiml = f'<Response><Say language="es-MX" voice="alice">{escape(texto)}</Say></Response>'
        return self._crear("Calls", {"To": a, "From": self.desde, "Twiml": twiml})


def cargar_canales():
    """{'telegram': Telegram|None, 'twilio': Twilio|None} según las credenciales disponibles."""
    cfg = {}
    ruta = RAIZ / "config" / "canales.local.yaml"
    if ruta.exists():
        cfg = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    tg, tw = cfg.get("telegram") or {}, cfg.get("twilio") or {}
    token = os.getenv("TELEGRAM_BOT_TOKEN") or tg.get("token")
    base = os.getenv("TELEGRAM_API_BASE") or tg.get("base_url") or "https://api.telegram.org"
    sid = os.getenv("TWILIO_ACCOUNT_SID") or tw.get("account_sid")
    auth = os.getenv("TWILIO_AUTH_TOKEN") or tw.get("auth_token")
    desde = os.getenv("TWILIO_FROM") or tw.get("desde")
    base_tw = os.getenv("TWILIO_API_BASE") or tw.get("base_url") or "https://api.twilio.com"
    return {
        "telegram": Telegram(token, base) if token else None,
        "twilio": Twilio(sid, auth, desde, base_tw) if sid and auth and desde else None,
    }
