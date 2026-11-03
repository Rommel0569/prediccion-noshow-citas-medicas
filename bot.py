"""Servicio del bot: servicio independiente de la web que atiende a los pacientes y gestiona los contactos solo.

Hace dos cosas, sin intervención de nadie:
  1. Atiende Telegram de forma continua (registro de pacientes, verificación, conversación y respuestas).
  2. Cada pocos minutos recorre las citas y contacta, escala y reasigna según los datos de cada paciente.

Comparte únicamente la base de datos con la aplicación web, por lo que puede correr en otro equipo o contenedor.
Ejecutar:  python bot.py
"""
import os
import sys
import threading

from noshow.config import RAIZ
from noshow.contacto import servicio, trabajador
from noshow.contacto.canales import ErrorCanal, cargar_canales
from noshow.modelo import SistemaRiesgo

canales = cargar_canales()
if canales["telegram"] is None:
    sys.exit("Falta el token de Telegram: configure config/canales.local.yaml o TELEGRAM_BOT_TOKEN.")
if servicio.activo():
    sys.exit("Otro proceso ya está atendiendo al bot.")
try:
    print(f"Bot conectado como @{canales['telegram'].info()['username']}.")
except ErrorCanal as e:
    sys.exit(f"No se pudo conectar: {e}")
print("Canales:", ", ".join(n for n, v in canales.items() if v))

sistema = SistemaRiesgo.cargar(RAIZ / "modelos" / "sistema.joblib")
cada = int(os.getenv("CICLO_SEGUNDOS", "300"))
detener = threading.Event()
threading.Thread(target=trabajador.bucle, args=(canales, sistema, detener, cada), daemon=True, name="planificador").start()
print(f"Atendiendo Telegram y planificando cada {cada} s. (Ctrl+C para salir)")
try:
    servicio.bucle(canales["telegram"], detener)
except KeyboardInterrupt:
    detener.set()
    print("Detenido.")
