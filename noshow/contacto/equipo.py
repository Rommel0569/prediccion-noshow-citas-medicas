"""Carga de los números del equipo (pruebas reales) desde un archivo local que NO se sube al repositorio.

config/equipo.local.csv, una fila por persona del equipo que aceptó recibir los avisos:

    id_paciente,telefono,etiqueta
    8853121856158,+51999111222,Integrante 1

`id_paciente` debe ser un paciente de la agenda con el que se probará (así los avisos de esa cita llegan al equipo);
`telefono` va en formato internacional (+51...). Quien use Telegram se vincula con el enlace de la página Canales.
"""
import pandas as pd

from ..config import RAIZ
from . import almacen

RUTA = RAIZ / "config" / "equipo.local.csv"


def cargar_equipo(ruta=RUTA):
    """Registra los teléfonos del archivo como destinatarios autorizados. Devuelve cuántos registró."""
    if not ruta.exists():
        return 0
    df = pd.read_csv(ruta, dtype=str).fillna("")
    n = 0
    for r in df.to_dict("records"):
        tel = r.get("telefono", "").strip()
        if r.get("id_paciente") and tel.startswith("+") and tel[1:].isdigit():
            almacen.registrar_destinatario(r["id_paciente"].strip(), "telefono", tel)
            n += 1
    return n
