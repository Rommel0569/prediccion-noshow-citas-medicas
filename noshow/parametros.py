"""Parámetros de operación compartidos entre la aplicación web y el servicio del bot (se guardan en la base de datos).

No depende de Streamlit: el servicio del bot corre por separado de la web y solo comparte la base de datos.
"""
import copy
import json

import yaml

from .config import RAIZ, cargar_config
from .contacto import almacen

CFG_DATOS = "config/kaggle_brasil.yaml"


def cfg_base():
    return cargar_config(CFG_DATOS)


def base():
    c = cfg_base()
    return {"capacidad": c["niveles"]["alto_percentil"], "sms": c["costos"]["sms"], "whatsapp": c["costos"]["whatsapp"],
            "llamada": c["costos"]["llamada"], "visita": c["costos"]["visita"], "consulta": c["costos"]["valor_consulta"]}


def vigente():
    return {**base(), **json.loads(almacen.leer("parametros", "{}"))}


def guardar(valores):
    almacen.guardar("parametros", json.dumps(valores))


def restablecer():
    almacen.guardar("parametros", "{}")


def cfg_activa():
    """Configuración del establecimiento con los parámetros de operación vigentes."""
    cfg, p = copy.deepcopy(cfg_base()), vigente()
    cfg["niveles"]["alto_percentil"] = p["capacidad"]
    cfg["costos"].update({"sms": p["sms"], "whatsapp": p["whatsapp"], "llamada": p["llamada"], "visita": p["visita"],
                          "valor_consulta": p["consulta"]})
    return cfg


def _info():
    try:
        return yaml.safe_load((RAIZ / "config" / "establecimiento.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def establecimiento():
    """Nombre que aparece en los mensajes a los pacientes."""
    return almacen.leer("establecimiento") or _info().get("nombre") or "Consulta externa"


def guardar_establecimiento(nombre):
    almacen.guardar("establecimiento", nombre.strip() or "Consulta externa")


def servicios():
    return _info().get("servicios") or ["Medicina General"]
