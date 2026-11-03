"""Servicio del bot: atiende a los pacientes de forma continua, sin intervención de nadie.

Se inicia solo junto con la aplicación (app.py) o por separado con `python bot.py`. Un latido en la base evita que dos
procesos atiendan el mismo bot a la vez.
"""
import threading
import time

from . import almacen, mensajes, respuestas
from .canales import ErrorCanal

LATIDO = "bot_latido"
COMANDOS = [("start", "Registrarse con el enlace del establecimiento"), ("baja", "Dejar de recibir avisos")]


def activo(maximo_segundos=45):
    """¿Hay un proceso atendiendo al bot ahora mismo?"""
    ult = almacen.leer(LATIDO)
    if not ult:
        return False
    from datetime import datetime
    return (datetime.now() - datetime.fromisoformat(ult)).total_seconds() < maximo_segundos


def bucle(telegram, detener=None, espera=20):
    """Atiende novedades hasta que se pida detener. Se recupera solo de caídas de red."""
    detener = detener or threading.Event()
    try:
        telegram.configurar_bot(mensajes.DESCRIPCION, COMANDOS)
    except ErrorCanal:
        pass
    while not detener.is_set():
        try:
            almacen.guardar(LATIDO, almacen.ahora())
            respuestas.procesar(telegram, espera=espera)
            detener.wait(0.3)
        except Exception:               # red caída, token inválido, etc.: se reintenta
            detener.wait(5)


def iniciar_en_segundo_plano(telegram):
    """Lanza el bucle en un hilo. Devuelve (hilo, evento_de_parada) o None si otro proceso ya atiende al bot."""
    if activo():
        return None
    detener = threading.Event()
    hilo = threading.Thread(target=bucle, args=(telegram, detener), daemon=True, name="bot-telegram")
    hilo.start()
    time.sleep(0.2)
    return hilo, detener
