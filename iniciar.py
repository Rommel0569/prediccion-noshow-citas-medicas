"""Enciende todo el sistema con un solo comando: el bot de Telegram (siempre atento) y la aplicación web.

Ejecutar:  python iniciar.py        (Ctrl+C detiene ambos)
"""
import subprocess
import sys
import time
from pathlib import Path

raiz = Path(__file__).resolve().parent
bot = subprocess.Popen([sys.executable, "bot.py"], cwd=raiz)
time.sleep(2)
if bot.poll() is not None:
    print("El bot no se inició (revise config/canales.local.yaml). Se abre solo la aplicación web.")
try:
    subprocess.call([sys.executable, "-m", "streamlit", "run", "app.py"], cwd=raiz)
finally:
    if bot.poll() is None:
        bot.terminate()
