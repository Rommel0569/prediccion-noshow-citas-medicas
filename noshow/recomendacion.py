"""Motor de reglas: riesgo + canal disponible -> acción de menor costo suficiente."""
import numpy as np
import pandas as pd


def simular_canales(df, cfg, semilla=7):
    """Solo para demostración: asigna un canal según las proporciones del INEI.

    Si el archivo ya trae 'canal_disponible', se respeta ese dato.
    """
    rng = np.random.default_rng(semilla)
    out = df.copy()
    if "canal_disponible" not in out:
        out["canal_disponible"] = np.nan
    out["canal_disponible"] = out["canal_disponible"].astype(object)
    faltan = out["canal_disponible"].isna()
    if faltan.any():
        sim = cfg["canales_simulados"]
        nombres = ["whatsapp", "sms_voz", "ninguno"]
        mayor = out["edad"] >= 60
        for mascara, clave in ((faltan & mayor, "adulto_mayor"), (faltan & ~mayor, "general")):
            prob = [sim[clave][c] for c in nombres]
            out.loc[mascara, "canal_disponible"] = rng.choice(nombres, size=int(mascara.sum()), p=np.array(prob) / sum(prob))
        out["canal_simulado"] = faltan
    else:
        out["canal_simulado"] = False
    return out


def _regla(nivel, canal, cronico_o_reincidente, dias=None, llamar=False):
    """Devuelve (canal_usado, acción, momento, mensajes, llamadas, visitas)."""
    if dias is not None and dias <= 0:
        return "ninguno", "Cita del mismo día: no requiere recordatorio", "—", 0, 0, 0
    corta = dias is not None and dias <= 2
    if llamar:
        momento = "Al agendar o el día previo" if corta else "72 a 48 h antes; si no confirma a las 24 h, liberar cupo"
        return "llamada", "Llamada telefónica: confirmar, reprogramar o liberar el cupo", momento, 1, 1, 0
    if canal == "ninguno":
        if nivel == "alto" and cronico_o_reincidente:
            return "visita", "Visita domiciliaria o agente comunitario; confirmar o reprogramar", "5 a 3 días antes", 0, 0, 1
        if nivel == "alto":
            return "ninguno", "Sin contacto posible: marcar cupo para lista de espera si no confirma en ventanilla", "Al agendar", 0, 0, 0
        if nivel == "medio":
            return "ninguno", "Actualizar contacto; avisar por el centro de salud de referencia", "Al agendar", 0, 0, 0
        return "ninguno", "Entregar fecha y hora por escrito al agendar", "Al agendar", 0, 0, 0
    msg = "whatsapp" if canal == "whatsapp" else "sms"
    if corta:
        return msg, "Recordatorio automático", "24 h antes", 1, 0, 0
    if nivel == "bajo":
        return msg, "Recordatorio automático", "48 h y 24 h antes", 2, 0, 0
    return msg, "Recordatorio con pedido de confirmación; si no responde, llamada", "72 h (confirmar) y 24 h antes", 2, 0, 0


def elegir_llamadas(df, prob, cfg, info=None, capacidad=None, nivel=None):
    """Llama a las citas donde la llamada evita más inasistencias por sol, hasta llenar la capacidad.

    beneficio = riesgo × (efecto de la llamada − efecto del mensaje que recibiría igual) / costo de la llamada.
    La capacidad es la fracción de citas de la agenda que el personal puede llamar (niveles.alto_percentil).
    """
    from .impacto import efecto_mensaje
    capacidad = cfg["niveles"]["alto_percentil"] if capacidad is None else capacidad
    ef, c = cfg["efecto_canal"], cfg["costos"]
    dias = df["dias_anticipacion"].to_numpy() if "dias_anticipacion" in df else np.full(len(df), 3)
    e_msg = np.array([efecto_mensaje(x, info, ef["sms"]) for x in dias])
    beneficio = np.asarray(prob) * (np.maximum(ef["llamada"], e_msg) - e_msg) / c["llamada"]
    elegible = (dias > 0) & df["canal_disponible"].isin(["whatsapp", "sms_voz"]).to_numpy()
    k = int(round(capacidad * len(df)))
    if len(df) < 20 and nivel is not None:      # caso suelto o agenda muy pequeña: se llama al nivel alto
        return elegible & (np.asarray(nivel) == "alto"), beneficio
    llamar = np.zeros(len(df), bool)
    orden = [i for i in np.argsort(-beneficio) if elegible[i]][:k]
    llamar[orden] = True
    return llamar, beneficio


def recomendar(df, prob, nivel, cfg, info=None, capacidad=None):
    """`info` (del modelo entrenado) aporta el efecto del mensaje medido por anticipación."""
    from .impacto import efecto_mensaje
    out = df.copy()
    out["probabilidad"] = np.round(prob, 4)
    out["nivel"] = nivel
    llamar, beneficio = elegir_llamadas(out, prob, cfg, info, capacidad, nivel)
    out["prioridad_llamada"] = llamar
    out["beneficio_llamada"] = np.round(beneficio, 4)
    costos, efecto = cfg["costos"], cfg["efecto_canal"]
    filas = []
    for (_, r), ll in zip(out.iterrows(), llamar):
        cron = bool(r.get("hipertension", 0) or r.get("diabetes", 0) or r.get("faltas_previas", 0) > 0)
        dias = r.get("dias_anticipacion")
        canal, accion, momento, n_msg, n_llam, n_vis = _regla(r["nivel"], r["canal_disponible"], cron, dias, ll)
        costo_msg = costos["whatsapp"] if canal == "whatsapp" or (canal == "llamada" and r["canal_disponible"] == "whatsapp") else costos["sms"]
        costo = n_msg * costo_msg + n_llam * costos["llamada"] + n_vis * costos["visita"]
        if canal in ("whatsapp", "sms"):
            red = efecto_mensaje(dias if dias is not None else 3, info, efecto["sms"])
        elif canal in ("llamada", "visita"):          # sin datos propios: literatura, nunca menos que el mensaje
            red = max(efecto[canal], efecto_mensaje(dias if dias is not None else 3, info, efecto["sms"]))
        else:
            red = 0.0
        p_post = r["probabilidad"] * (1 - red)
        filas.append((canal, accion, momento, round(costo, 3), round(p_post, 4)))
    out[["canal_accion", "accion", "momento", "costo", "probabilidad_con_intervencion"]] = pd.DataFrame(filas, index=out.index)
    return out


def ordenar_por_prioridad(agenda):
    orden = {"alto": 0, "medio": 1, "bajo": 2}
    llamar = agenda["prioridad_llamada"] if "prioridad_llamada" in agenda else False
    return (agenda.assign(_l=~llamar, _o=agenda["nivel"].map(orden))
            .sort_values(["_l", "_o", "probabilidad"], ascending=[True, True, False]).drop(columns=["_l", "_o"]))
