"""Atiende al bot de Telegram de forma continua (registro de pacientes, verificación, respuestas y ofertas de cupo).

La aplicación web ya lo inicia sola; este comando sirve para dejarlo corriendo en un servidor sin la interfaz.
Ejecutar:  python bot.py
"""
import sys

from noshow.contacto import servicio
from noshow.contacto.canales import ErrorCanal, cargar_canales

telegram = cargar_canales()["telegram"]
if telegram is None:
    sys.exit("Falta el token de Telegram: configure config/canales.local.yaml o TELEGRAM_BOT_TOKEN.")
if servicio.activo():
    sys.exit("Otro proceso ya está atendiendo al bot (aplicación web u otra instancia).")
try:
    print(f"Bot conectado como @{telegram.info()['username']}. Atendiendo... (Ctrl+C para salir)")
    servicio.bucle(telegram)
except ErrorCanal as e:
    sys.exit(f"No se pudo conectar: {e}")
except KeyboardInterrupt:
    print("Detenido.")
