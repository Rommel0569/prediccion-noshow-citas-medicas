"""Evaluación de la mejora real en el 20 % de prueba (citas que el modelo nunca vio).

Uso:
    python evaluar.py

1. Compara estrategias de contacto (sin aviso, SMS a todos, llamar a todos, al azar, por regla y el sistema)
   contando cuántas inasistencias REALES de la prueba alcanza cada una y cuánto cuesta.
2. Repite el ejercicio en 1 000 muestras de 100 citas reales para ver la mejora caso a caso.
3. Calcula intervalos de confianza (bootstrap) y el tamaño de muestra de un piloto para confirmar el efecto del SMS.

Supuesto de cálculo: una inasistencia real alcanzada por un canal se evita con la probabilidad de su efecto
(SMS: efecto medido por anticipación en los datos; llamada y visita: literatura, nunca menos que el SMS).
Guarda modelos/evaluacion.json y datos/muestra_100_citas_reales.csv.
"""
import json

import numpy as np
import pandas as pd
from scipy.stats import norm

from noshow.config import RAIZ, cargar_config
from noshow.datos import cargar
from noshow.impacto import efecto_mensaje
from noshow.modelo import SistemaRiesgo, particion_temporal
from noshow.recomendacion import recomendar, simular_canales
from noshow.variables import agregar_historial

FRAC_LLAMADAS = 0.20     # capacidad de llamadas: 20 % de las citas (nivel alto)


def efecto_sms(d, info):
    return np.array([efecto_mensaje(x, info, 0.29) for x in d["dias_anticipacion"]])


def resultado(nombre, y, efecto, costo, llamadas=0):
    evitadas = float((y * efecto).sum())
    return {"estrategia": nombre, "inasistencias_reales": int(y.sum()), "evitadas": round(evitadas, 1),
            "tasa_resultante": round(float((y.sum() - evitadas) / len(y)), 4),
            "reduccion_relativa": round(evitadas / y.sum(), 4), "costo_total": round(float(costo), 2),
            "costo_por_evitada": round(float(costo / evitadas), 2) if evitadas else None, "llamadas": int(llamadas)}


def estrategias(d, info, cfg, semilla=0):
    """Cada estrategia se evalúa con las inasistencias reales (y) de las mismas citas."""
    c, ef = cfg["costos"], cfg["efecto_canal"]
    y = d["falto"].to_numpy()
    n = len(d)
    agendada = (d["dias_anticipacion"] > 0).to_numpy()
    tel = d["canal_disponible"].isin(["whatsapp", "sms_voz"]).to_numpy()      # sin celular no llega SMS ni llamada
    n_tel = int(tel.sum())
    e_sms = efecto_sms(d, info) * tel
    e_llam = np.maximum(ef["llamada"], e_sms) * agendada * tel
    k = int(n * FRAC_LLAMADAS)
    rng = np.random.default_rng(semilla)

    def con_llamadas(orden):
        orden = [i for i in orden if tel[i] and agendada[i]][:k]
        sel = np.zeros(n, bool); sel[orden] = True
        return np.where(sel, e_llam, e_sms), sel.sum()

    out = [resultado("Sin recordatorios", y, np.zeros(n), 0)]
    out.append(resultado("SMS a todas las citas (práctica actual)", y, e_sms, n_tel * 2 * c["sms"]))
    out.append(resultado("Llamar a todas las citas", y, e_llam, n_tel * c["llamada"], n_tel))
    e, m = con_llamadas(rng.permutation(n))
    out.append(resultado("SMS a todos + llamada al 20 % elegido al azar", y, e, n_tel * 2 * c["sms"] + m * c["llamada"], m))
    e, m = con_llamadas(np.argsort(-d["dias_anticipacion"].to_numpy()))
    out.append(resultado("SMS a todos + llamada al 20 % con más días de espera", y, e, n_tel * 2 * c["sms"] + m * c["llamada"], m))
    e, m = con_llamadas(np.argsort(-d["probabilidad"].to_numpy()))
    out.append(resultado("SMS a todos + llamada al 20 % de mayor riesgo (modelo)", y, e, n_tel * 2 * c["sms"] + m * c["llamada"], m))
    beneficio = d["probabilidad"].to_numpy() * (e_llam - e_sms) / c["llamada"]
    e, m = con_llamadas(np.argsort(-beneficio))
    out.append(resultado("SMS a todos + llamada al 20 % de mayor beneficio por sol (modelo)", y, e, n_tel * 2 * c["sms"] + m * c["llamada"], m))
    # Sistema completo: reglas por anticipación, riesgo y canal disponible (no avisa el mismo día)
    rec = d
    efecto = np.where(rec["canal_accion"].isin(["whatsapp", "sms"]), e_sms,
                      np.where(rec["canal_accion"].isin(["llamada", "visita"]),
                               np.maximum(rec["canal_accion"].map(ef).fillna(0).to_numpy(), e_sms), 0.0))
    out.append(resultado("Sistema propuesto (reglas por anticipación, riesgo y canal)", y, efecto, rec["costo"].sum(),
                         (rec["canal_accion"] == "llamada").sum()))
    vis = (rec["canal_accion"] == "visita").to_numpy()
    out.append(resultado("Sistema propuesto sin visitas domiciliarias", y, np.where(vis, 0, efecto),
                         rec["costo"].sum() - vis.sum() * c["visita"], (rec["canal_accion"] == "llamada").sum()))
    out[-2]["visitas"] = int(vis.sum())
    return out


def efecto_sms_ipw(df, cod, B=200, semilla=3):
    """Efecto del SMS ajustado por TODAS las variables con puntaje de propensión (ponderación inversa, IPW).

    Solo citas con ≥ 3 días (las únicas que pudieron recibir SMS). Es la mejor estimación posible con datos
    observacionales; confirmar causalidad exige un piloto aleatorizado.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import SplineTransformer, StandardScaler
    from sklearn.pipeline import make_pipeline
    from sklearn.compose import ColumnTransformer
    d = df[df["dias_anticipacion"] >= 3].copy()
    d["tasa_zona"] = cod.transformar(d["zona"])
    cont = ["dias_anticipacion", "edad", "faltas_previas", "tasa_zona"]
    bina = ["dia_semana", "subsidio", "hipertension", "diabetes"] + (["sexo_f"] if "sexo_f" in d else [])
    pre = ColumnTransformer([("s", SplineTransformer(n_knots=5), cont), ("b", StandardScaler(), bina)])
    ps = make_pipeline(pre, LogisticRegression(max_iter=2000)).fit(d[cont + bina], d["recordatorio"])
    e = np.clip(ps.predict_proba(d[cont + bina])[:, 1], 0.02, 0.98)
    t, y = d["recordatorio"].to_numpy(), d["falto"].to_numpy()

    def rr(idx):
        w1, w0 = t[idx] / e[idx], (1 - t[idx]) / (1 - e[idx])
        return (w1 * y[idx]).sum() / w1.sum() / ((w0 * y[idx]).sum() / w0.sum())
    todo = np.arange(len(d))
    rng = np.random.default_rng(semilla)
    boot = [rr(rng.integers(0, len(d), len(d))) for _ in range(B)]
    est = rr(todo)
    return {"rr": round(float(est), 3), "reduccion_relativa": round(float(1 - est), 3),
            "ic95_reduccion": [round(float(1 - v), 3) for v in np.percentile(boot, [97.5, 2.5])],
            "citas": int(len(d)), "variables_ajuste": cont + bina}


def curva_costo(d, info, cfg, semilla=0):
    """Inasistencias evitadas y costo al variar la fracción de citas que se llaman (resto: SMS).

    Compara elegir a quién llamar por beneficio (modelo) frente a elegir al azar, con la misma capacidad.
    """
    c, ef = cfg["costos"], cfg["efecto_canal"]
    y = d["falto"].to_numpy(); n = len(d)
    tel = d["canal_disponible"].isin(["whatsapp", "sms_voz"]).to_numpy()
    ag = (d["dias_anticipacion"] > 0).to_numpy()
    e_sms = efecto_sms(d, info) * tel * ag
    e_llam = np.maximum(ef["llamada"], e_sms) * ag * tel
    benef = d["probabilidad"].to_numpy() * (e_llam - e_sms)
    elig = np.where(tel & ag)[0]
    orden_b = elig[np.argsort(-benef[elig])]
    orden_a = np.random.default_rng(semilla).permutation(elig)
    filas = []
    for frac in np.linspace(0, 1, 21):
        k = int(round(frac * len(elig)))
        for nombre, orden in (("modelo", orden_b), ("azar", orden_a)):
            sel = np.zeros(n, bool); sel[orden[:k]] = True
            ev = (y * np.where(sel, e_llam, e_sms)).sum()
            costo = (tel & ag & ~sel).sum() * 2 * c["sms"] + k * (c["llamada"] + c["sms"])
            filas.append({"frac_llamadas": round(float(frac), 2), "eleccion": nombre, "evitadas": round(float(ev), 1),
                          "costo": round(float(costo), 2)})
    return filas


def tamano_piloto(p0, reduccion, alfa=0.05, potencia=0.80):
    """Citas por grupo para detectar la reducción relativa en un ensayo aleatorizado (dos proporciones)."""
    p1 = p0 * (1 - reduccion)
    za, zb = norm.ppf(1 - alfa / 2), norm.ppf(potencia)
    pm = (p0 + p1) / 2
    return int(np.ceil((za * np.sqrt(2 * pm * (1 - pm)) + zb * np.sqrt(p0 * (1 - p0) + p1 * (1 - p1))) ** 2 / (p0 - p1) ** 2))


def main():
    cfg = cargar_config("config/kaggle_brasil.yaml")
    sistema = SistemaRiesgo.cargar(RAIZ / "modelos" / "sistema.joblib")
    info = sistema.info
    df, _ = cargar(cfg)
    df = agregar_historial(df)
    e = cfg["entrenamiento"]
    _, _, pru = particion_temporal(df, e["proporcion_validacion"], e["proporcion_prueba"])
    pru = simular_canales(pru, cfg)
    p = sistema.probabilidad(pru)
    pru = recomendar(pru, p, sistema.nivel(p), cfg, info)

    # 1) estrategias en toda la prueba
    total = estrategias(pru, info, cfg)
    print(pd.DataFrame(total).to_string(index=False))

    # IC95 % por bootstrap: evitadas del sistema frente a "SMS a todos"
    rng = np.random.default_rng(1)
    dif, red = [], []
    for _ in range(500):
        b = pru.iloc[rng.integers(0, len(pru), len(pru))]
        r = {x["estrategia"]: x for x in estrategias(b, info, cfg)}
        s, base = r["Sistema propuesto (reglas por anticipación, riesgo y canal)"], r["SMS a todas las citas (práctica actual)"]
        dif.append(s["costo_total"] - base["costo_total"])
        red.append(s["reduccion_relativa"])
    ic = {"reduccion_relativa_sistema_ic95": [round(float(v), 4) for v in np.percentile(red, [2.5, 97.5])],
          "ahorro_frente_a_sms_a_todos_ic95": [round(float(-v), 2) for v in np.percentile(dif, [97.5, 2.5])]}

    # 2) muestras de 100 citas agendadas reales
    ag = pru[pru["dias_anticipacion"] > 0].reset_index(drop=True)
    filas = []
    for _ in range(1000):
        m = ag.iloc[rng.choice(len(ag), 100, replace=False)]
        y = m["falto"].to_numpy()
        top = np.argsort(-m["probabilidad"].to_numpy())[:20]
        regla = np.argsort(-m["dias_anticipacion"].to_numpy(), kind="stable")[:20]
        azar = rng.choice(100, 20, replace=False)
        filas.append({"inasistencias": y.sum(), "modelo": y[top].sum(), "regla": y[regla].sum(), "azar": y[azar].sum()})
    f = pd.DataFrame(filas)
    muestras = {
        "n_muestras": 1000, "citas_por_muestra": 100, "marcadas_por_muestra": 20,
        "inasistencias_promedio": round(float(f["inasistencias"].mean()), 1),
        "encontradas_modelo": round(float(f["modelo"].mean()), 1),
        "encontradas_regla_anticipacion": round(float(f["regla"].mean()), 1),
        "encontradas_azar": round(float(f["azar"].mean()), 1),
        "modelo_supera_azar_pct": round(float((f["modelo"] > f["azar"]).mean()), 3),
        "modelo_empata_azar_pct": round(float((f["modelo"] == f["azar"]).mean()), 3),
        "modelo_rango_p5_p95": [int(v) for v in np.percentile(f["modelo"], [5, 95])],
        "azar_rango_p5_p95": [int(v) for v in np.percentile(f["azar"], [5, 95])],
    }
    print(muestras)
    # una muestra concreta de 100 citas reales para revisar caso por caso
    una = ag.iloc[np.random.default_rng(7).choice(len(ag), 100, replace=False)].copy()
    una["marcada_por_modelo"] = una["probabilidad"].rank(ascending=False, method="first") <= 20
    cols = ["id_cita", "fecha_cita", "dias_anticipacion", "dia_semana", "edad", "zona", "subsidio", "faltas_previas",
            "canal_disponible", "probabilidad", "nivel", "canal_accion", "accion", "costo", "marcada_por_modelo", "falto"]
    una[cols].sort_values("probabilidad", ascending=False).to_csv(RAIZ / "datos" / "muestra_100_citas_reales.csv", index=False)
    muestras["muestra_fija"] = {"inasistencias": int(una["falto"].sum()),
                                "encontradas_en_20_marcadas": int(una.loc[una["marcada_por_modelo"], "falto"].sum())}

    # 3) efecto del SMS ajustado por todas las variables (todo el dataset) y piloto para confirmarlo
    ipw = efecto_sms_ipw(df, sistema.codificador)
    print("SMS ajustado (IPW):", ipw)
    # 3) piloto para confirmar el efecto del SMS
    base_ag = float(ag["falto"].mean())
    piloto = {"tasa_base_agendadas": round(base_ag, 4),
              "citas_por_grupo_para_detectar": {f"{int(r * 100)} %": tamano_piloto(base_ag, r) for r in (0.10, 0.15, 0.20, 0.30)}}
    print(piloto)

    curva = curva_costo(pru, info, cfg)
    salida = {"curva_costo": curva, "estrategias_prueba": total, "efecto_sms_ipw": ipw, "intervalos": ic, "muestras_100": muestras, "piloto": piloto,
              "citas_prueba": int(len(pru)), "supuestos": {"efecto_llamada": cfg["efecto_canal"]["llamada"],
                                                           "costos": cfg["costos"], "frac_llamadas": FRAC_LLAMADAS}}
    (RAIZ / "modelos" / "evaluacion.json").write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(ic)


if __name__ == "__main__":
    main()
