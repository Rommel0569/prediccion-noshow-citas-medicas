"""Liberación de cupos no confirmados y reasignación a la lista de espera."""
import numpy as np
import pandas as pd

ASISTENCIA_LISTA_ESPERA = 0.90   # supuesto: quien está en lista de espera y acepta un cupo cercano suele asistir


def simular_confirmacion(agenda, semilla=11):
    """Demostración: un paciente confirma con probabilidad (1 - riesgo).

    En operación real esta columna viene del registro de respuestas (auditoría de contacto).
    """
    rng = np.random.default_rng(semilla)
    out = agenda.copy()
    contactables = out["canal_accion"].isin(["llamada", "whatsapp", "sms", "visita"])
    out["confirmo"] = np.where(contactables, rng.random(len(out)) > out["probabilidad"], False)
    return out


def generar_lista_espera(n, servicios=None, semilla=3):
    rng = np.random.default_rng(semilla)
    lista = pd.DataFrame({"id_espera": [f"E{i:04d}" for i in range(1, n + 1)],
                          "dias_en_espera": rng.integers(5, 120, n)})
    if servicios is not None and len(servicios):
        lista["servicio"] = rng.choice(list(servicios), n)
    return lista.sort_values("dias_en_espera", ascending=False).reset_index(drop=True)


def liberar_y_reasignar(agenda, lista_espera):
    """Libera cupos de riesgo alto sin confirmación y los asigna por antigüedad en la lista."""
    mismo_dia = agenda["dias_anticipacion"].le(0) if "dias_anticipacion" in agenda else False
    prioridad = (agenda["canal_accion"] == "llamada") | (agenda["nivel"] == "alto")
    liberar = agenda[prioridad & (~agenda["confirmo"]) & ~mismo_dia].copy()
    lista = lista_espera.copy()
    lista["asignado"] = False
    asignaciones = []
    for _, cupo in liberar.iterrows():
        candidatos = lista[~lista["asignado"]]
        if "servicio" in agenda and "servicio" in lista:
            candidatos = candidatos[candidatos["servicio"] == cupo.get("servicio")]
        if candidatos.empty:
            asignaciones.append({"id_cita": cupo["id_cita"], "fecha_cita": cupo["fecha_cita"], "id_espera": None})
            continue
        elegido = candidatos.index[0]
        lista.loc[elegido, "asignado"] = True
        asignaciones.append({"id_cita": cupo["id_cita"], "fecha_cita": cupo["fecha_cita"],
                             "id_espera": lista.loc[elegido, "id_espera"],
                             "dias_en_espera": int(lista.loc[elegido, "dias_en_espera"])})
    tabla = pd.DataFrame(asignaciones)
    liberados = len(liberar)
    reasignados = int(tabla["id_espera"].notna().sum()) if len(tabla) else 0
    resumen = {
        "cupos_liberados": liberados,
        "cupos_reasignados": reasignados,
        "tasa_reutilizacion": round(reasignados / liberados, 4) if liberados else 0.0,
        "asistencias_recuperadas_esperadas": round(reasignados * ASISTENCIA_LISTA_ESPERA, 1),
    }
    return tabla, resumen
