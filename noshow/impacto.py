"""Indicadores de impacto y costo-eficiencia (sección 3.6 del informe)."""
import numpy as np
import pandas as pd


def resumen_agenda(agenda, res_cupos, cfg):
    c = cfg["costos"]
    sin = float(agenda["probabilidad"].sum())
    con = float(agenda["probabilidad_con_intervencion"].sum())
    evitadas = sin - con
    costo = float(agenda["costo"].sum())
    recuperadas = res_cupos.get("asistencias_recuperadas_esperadas", 0.0)
    return {
        "citas": int(len(agenda)),
        "inasistencias_esperadas_sin_intervencion": round(sin, 1),
        "inasistencias_esperadas_con_intervencion": round(con, 1),
        "inasistencias_evitadas": round(evitadas, 1),
        "reduccion_relativa": round(evitadas / sin, 4) if sin else 0.0,
        "asistencias_recuperadas_por_reasignacion": recuperadas,
        "costo_total_contacto": round(costo, 2),
        "costo_por_inasistencia_evitada": round(costo / evitadas, 2) if evitadas > 0 else None,
        "valor_consultas_recuperadas": round((evitadas + recuperadas) * c["valor_consulta"], 2),
        "por_canal": agenda["canal_accion"].value_counts().to_dict(),
        "por_nivel": agenda["nivel"].value_counts().to_dict(),
    }


TRAMOS_SMS = [2, 7, 14, 30, 10_000]
ETIQUETAS_SMS = ["3-7", "8-14", "15-30", ">30"]


def _rr_mh(d):
    num = den = 0.0
    for _, g in d.groupby("tramo", observed=True):
        a = ((g["recordatorio"] == 1) & (g["falto"] == 1)).sum(); n1 = (g["recordatorio"] == 1).sum()
        c = ((g["recordatorio"] == 0) & (g["falto"] == 1)).sum(); n0 = (g["recordatorio"] == 0).sum()
        if n1 and n0:
            n = n1 + n0; num += a * n0 / n; den += c * n1 / n
    return num / den if den else np.nan


def efecto_sms_estratificado(df, prob=None):
    """Efecto del SMS comparando citas con la MISMA anticipación (Mantel-Haenszel).

    La comparación cruda engaña: el SMS solo se envió a citas con ≥ 3 días de anticipación, que son las
    que más se pierden. Si se pasa `prob` (riesgo predicho fuera de muestra), se calcula también por nivel.
    """
    crudo = df.groupby("recordatorio")["falto"].mean()
    d = df[df["dias_anticipacion"] >= 3].copy()
    d["tramo"] = pd.cut(d["dias_anticipacion"], TRAMOS_SMS, labels=ETIQUETAS_SMS)
    num = den = 0.0
    filas = []
    for t, g in d.groupby("tramo", observed=True):
        a = ((g["recordatorio"] == 1) & (g["falto"] == 1)).sum()
        n1 = (g["recordatorio"] == 1).sum()
        c = ((g["recordatorio"] == 0) & (g["falto"] == 1)).sum()
        n0 = (g["recordatorio"] == 0).sum()
        if n1 == 0 or n0 == 0:
            continue
        n = n1 + n0
        num += a * n0 / n
        den += c * n1 / n
        filas.append({"tramo_dias": str(t), "citas": int(n), "sin_sms": round(c / n0, 4), "con_sms": round(a / n1, 4),
                      "puntos_menos": round((c / n0 - a / n1) * 100, 1), "reduccion_relativa": round(1 - (a / n1) / (c / n0), 3)})
    rr = num / den if den else np.nan
    out = {"rr_mantel_haenszel": round(float(rr), 3), "reduccion_relativa": round(float(1 - rr), 3), "tramos": filas,
           "crudo": {"sin_sms": round(float(crudo.get(0, np.nan)), 4), "con_sms": round(float(crudo.get(1, np.nan)), 4)}}
    if prob is not None:
        d["riesgo"] = pd.qcut(pd.Series(prob, index=df.index).loc[d.index], 3, labels=["bajo", "medio", "alto"])
        por_riesgo = []
        for r, g in d.groupby("riesgo", observed=True):
            rr_g = _rr_mh(g)
            sin, con = g.loc[g["recordatorio"] == 0, "falto"].mean(), g.loc[g["recordatorio"] == 1, "falto"].mean()
            por_riesgo.append({"riesgo_predicho": str(r), "citas": int(len(g)), "sin_sms": round(float(sin), 4),
                               "con_sms": round(float(con), 4), "reduccion_relativa": round(float(1 - rr_g), 3),
                               "evitadas_por_100_avisos": round(float((sin - con) * 100), 1)})
        out["por_riesgo"] = por_riesgo
    return out


def efecto_mensaje(dias, info=None, por_defecto=0.29):
    """Reducción relativa esperada de un mensaje según la anticipación de la cita.

    Usa el efecto medido en los datos de entrenamiento por tramo; fuera del rango observado usa la literatura.
    """
    if dias <= 0:
        return 0.0
    tramos = (info or {}).get("efecto_recordatorio", {}).get("tramos")
    if not tramos:
        return por_defecto
    if dias < 3:          # sin SMS en los datos para 1-2 días: se usa el menor efecto medido (conservador)
        return min(f["reduccion_relativa"] for f in tramos)
    for i, t in enumerate(ETIQUETAS_SMS):
        if dias <= TRAMOS_SMS[i + 1]:
            return next((f["reduccion_relativa"] for f in tramos if f["tramo_dias"] == t), por_defecto)
    return por_defecto


ESCENARIOS = [
    ("Conservador", 0.164, "CSV ajustado por anticipación"),
    ("Base (solo mensajes)", 0.29, "Recordatorios automatizados (Hasvold y Wootton)"),
    ("Alto", 0.39, "Llamada manual (Hasvold y Wootton)"),
    ("Optimista", 0.50, "Llamada dirigida + reasignación de cupos"),
]


def escenarios(tasa_base):
    return pd.DataFrame([{"escenario": n, "reduccion_relativa": r, "respaldo": f,
                          "inasistencia_resultante": round(tasa_base * (1 - r), 4)} for n, r, f in ESCENARIOS])
