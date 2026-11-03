from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent


def cargar_config(ruta):
    ruta = Path(ruta)
    if not ruta.is_absolute():
        ruta = RAIZ / ruta
    with open(ruta, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_ruta"] = str(ruta)
    datos = Path(cfg["archivo_datos"])
    cfg["archivo_datos_abs"] = str(datos if datos.is_absolute() else (ruta.parent / datos).resolve())
    return cfg
