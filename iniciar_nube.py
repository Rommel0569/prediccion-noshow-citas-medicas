"""Arranque en la nube (Render): la web y el servicio del bot corren como procesos separados dentro del mismo servicio.

La web escucha en el puerto que indica la plataforma (PORT). El bot se reinicia solo si se cae. Los datos están en Postgres
(DATABASE_URL), por lo que sobreviven a los reinicios del servidor.
"""
import os
import subprocess
import sys
import time

from noshow.contacto.canales import cargar_canales

puerto = os.getenv("PORT", "8501")
web = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", puerto,
                        "--server.address", "0.0.0.0", "--server.headless", "true"])
bot = None
try:
    while web.poll() is None:
        if cargar_canales()["telegram"] and (bot is None or bot.poll() is not None):
            bot = subprocess.Popen([sys.executable, "bot.py"])
        time.sleep(30)
finally:
    for p in (bot, web):
        if p is not None and p.poll() is None:
            p.terminate()
