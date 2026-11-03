"""¿Mejora el modelo si se entrena un modelo por grupo? Compara un modelo único con modelos por segmento.

Uso:
    python experimentos.py --config config/kaggle_brasil.yaml

Misma regla 80/20 temporal que entrenar.py: se entrena con el 80 % más antiguo y se evalúa en el 20 % más reciente.
Se compara dentro de las citas agendadas (anticipación ≥ 1 día), que es donde el modelo tiene que decidir a quién avisar.
Guarda el resultado en modelos/experimento_segmentacion.json (la pestaña 4 de la aplicación lo muestra).
"""
import argparse
import json

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from noshow import VARIABLES_MODELO
from noshow.config import RAIZ, cargar_config
from noshow.datos import cargar
from noshow.modelo import _captura, candidatos, particion_temporal
from noshow.variables import CodificadorZona, agregar_historial, matriz

SEGMENTACIONES = {
    "Por anticipación (mismo día, 1-7, 8-30, >30 días)":
        lambda d: pd.cut(d["dias_anticipacion"], [-1, 0, 7, 30, 10_000], labels=["0", "1-7", "8-30", ">30"]).astype(str),
    "Mismo día aparte y agendadas aparte":
        lambda d: np.where(d["dias_anticipacion"] > 0, "agendada", "mismo día"),
    "Por grupo de edad (<18, 18-59, ≥60)":
        lambda d: pd.cut(d["edad"], [-1, 17, 59, 200], labels=["<18", "18-59", "60+"]).astype(str),
    "Pacientes con y sin inasistencias previas":
        lambda d: np.where(d["faltas_previas"] > 0, "con faltas", "sin faltas"),
}


def modelo(semilla):
    return candidatos(semilla)["Gradient Boosting"]      # el mismo modelo que usa el sistema


def ajustar_predecir(tr, te, cfg):
    cod = CodificadorZona(cfg["entrenamiento"]["suavizado_zona"]).ajustar(tr["zona"], tr["falto"])
    m = modelo(cfg["entrenamiento"]["semilla"]).fit(matriz(tr, cod, VARIABLES_MODELO), tr["falto"])
    return m.predict_proba(matriz(te, cod, VARIABLES_MODELO))[:, 1]


def evaluar(nombre, pru, p, frac):
    ag = (pru["dias_anticipacion"] > 0).to_numpy()
    y = pru["falto"].to_numpy()
    return {"enfoque": nombre, "auc_agendadas": round(float(roc_auc_score(y[ag], p[ag])), 4),
            "captura_top_agendadas": round(_captura(y[ag], p[ag], frac), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/kaggle_brasil.yaml")
    args = ap.parse_args()
    cfg = cargar_config(args.config)
    df, _ = cargar(cfg)
    df = agregar_historial(df)
    e = cfg["entrenamiento"]
    ent, val, pru = particion_temporal(df, e["proporcion_validacion"], e["proporcion_prueba"])
    e80 = pd.concat([ent, val])
    frac = cfg["niveles"]["alto_percentil"]

    filas = [evaluar("Modelo único (el del sistema)", pru, ajustar_predecir(e80, pru, cfg), frac)]
    for nombre, f in SEGMENTACIONES.items():
        g_tr, g_te = pd.Series(f(e80), index=e80.index), pd.Series(f(pru), index=pru.index)
        p = np.zeros(len(pru))
        for g in g_te.unique():
            te = (g_te == g).to_numpy()
            tr = e80[g_tr == g]
            p[te] = ajustar_predecir(tr, pru[te], cfg) if tr["falto"].nunique() == 2 else tr["falto"].mean()
        filas.append(evaluar(f"Un modelo por grupo: {nombre}", pru, p, frac))
        print(filas[-1])
    print(filas[0])
    salida = RAIZ / "modelos" / "experimento_segmentacion.json"
    salida.write_text(json.dumps({"datos": cfg["nombre"], "resultados": filas}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(pd.DataFrame(filas).to_string(index=False))


if __name__ == "__main__":
    main()
