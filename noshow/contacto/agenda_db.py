"""Agenda construida desde las citas registradas en el sistema, con el canal verificado de cada paciente."""
import pandas as pd

from ..config import cargar_config
from ..datos import estandarizar
from ..recomendacion import ordenar_por_prioridad, recomendar
from ..variables import agregar_historial
from . import almacen

CFG_ESTANDAR = "config/formato_estandar.yaml"
FUTURAS = ("agendada", "confirmada", "reprogramacion_solicitada", "cancelada")


def canal_disponible(id_paciente, dest):
    """Lo que el sistema sabe del paciente: Telegram verificado -> mensajería; solo teléfono -> SMS/llamada; nada -> ninguno."""
    if (id_paciente, "telegram") in dest:
        return "whatsapp"
    return "sms_voz" if (id_paciente, "telefono") in dest else "ninguno"


def construir(sistema, cfg, hoy=None, estados=("agendada",)):
    """Citas futuras en los estados indicados, evaluadas por el modelo y con su acción recomendada (agenda vacía si no hay)."""
    hoy = pd.Timestamp(hoy or pd.Timestamp.today()).normalize()
    citas, pac = almacen.listar_citas(), almacen.datos_pacientes()
    if citas.empty or pac.empty:
        return pd.DataFrame()
    futuras = citas[citas["estado"].isin(estados) & (pd.to_datetime(citas["fecha_cita"]) >= hoy)]
    futuras = futuras.merge(pac[["id_paciente", "edad", "zona", "subsidio", "hipertension", "diabetes"]],
                            on="id_paciente", how="inner")        # sin ficha del paciente no se puede evaluar
    if futuras.empty:
        return pd.DataFrame()
    dest = almacen.destinatarios_activos()
    df = pd.DataFrame({
        "id_paciente": futuras["id_paciente"], "id_cita": futuras["id_cita"],
        "fecha_registro": futuras["fecha_registro"].fillna(futuras["fecha_cita"]), "fecha_cita": futuras["fecha_cita"],
        "edad": futuras["edad"], "zona": futuras["zona"].replace("", "SIN ZONA"),
        "subsidio": futuras["subsidio"], "hipertension": futuras["hipertension"], "diabetes": futuras["diabetes"],
        "canal_disponible": [canal_disponible(i, dest) for i in futuras["id_paciente"]],
        "servicio": futuras["servicio"], "turno": futuras["turno"]})
    df, _ = estandarizar(df, cargar_config(CFG_ESTANDAR), con_objetivo=False)
    pasadas = citas[citas["estado"].isin(["atendida", "no_asistio"])]
    historial = pd.DataFrame({"id_paciente": pasadas["id_paciente"],
                              "fecha_cita": pd.to_datetime(pasadas["fecha_cita"]),
                              "falto": (pasadas["estado"] == "no_asistio").astype(int)})
    df = agregar_historial(df, historial if len(historial) else None)
    p = sistema.probabilidad(df)
    agenda = ordenar_por_prioridad(recomendar(df, p, sistema.nivel(p), cfg, sistema.info))
    agenda["estado_cita"] = agenda["id_cita"].map(dict(zip(citas["id_cita"], citas["estado"])))
    return agenda
