"""Entrenamiento, evaluación, recalibración y explicación del modelo."""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.base import clone
from sklearn.metrics import (average_precision_score, brier_score_loss, f1_score,
                             precision_score, recall_score, roc_auc_score, roc_curve)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import VARIABLES_MODELO
from .variables import CodificadorZona, agregar_historial, matriz


def particion_temporal(df, p_val, p_test):
    """Las citas más recientes quedan para prueba: simula predecir el futuro."""
    fechas = np.sort(df["fecha_cita"].unique())
    acum = df.groupby("fecha_cita").size().reindex(fechas).cumsum() / len(df)
    corte_val = acum.index[acum.searchsorted(1 - p_val - p_test)]
    corte_test = acum.index[acum.searchsorted(1 - p_test)]
    ent = df[df["fecha_cita"] < corte_val]
    val = df[(df["fecha_cita"] >= corte_val) & (df["fecha_cita"] < corte_test)]
    pru = df[df["fecha_cita"] >= corte_test]
    return ent, val, pru


def candidatos(semilla):
    return {
        "Regresión logística": make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced")),
        "Random Forest": RandomForestClassifier(n_estimators=300, min_samples_leaf=30, class_weight="balanced_subsample",
                                                n_jobs=-1, random_state=semilla),
        # Hiperparámetros elegidos por búsqueda en validación (72 combinaciones): árboles pequeños y regularizados
        "Gradient Boosting": HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                                            min_samples_leaf=100, l2_regularization=1.0,
                                                            class_weight="balanced", random_state=semilla),
    }


def metricas(y, p, umbral):
    pred = (p >= umbral).astype(int)
    return {
        "auc": round(float(roc_auc_score(y, p)), 4),
        "pr_auc": round(float(average_precision_score(y, p)), 4),
        "recall": round(float(recall_score(y, pred)), 4),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y, pred)), 4),
        "umbral": round(float(umbral), 4),
    }


class Calibrador:
    """Platt: ajusta los porcentajes del modelo a la tasa real de un establecimiento."""

    def __init__(self):
        self.lr = None

    @staticmethod
    def _logit(p):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p)).reshape(-1, 1)

    def ajustar(self, p, y):
        self.lr = LogisticRegression().fit(self._logit(p), y)
        return self

    def aplicar(self, p):
        return p if self.lr is None else self.lr.predict_proba(self._logit(p))[:, 1]


class SistemaRiesgo:
    """Modelo + codificador de zona + calibrador + umbrales de nivel. Es lo que se guarda."""

    def __init__(self, estimador, codificador, calibrador, cortes, nombre_modelo, info,
                 variables=None, cod_servicio=None):
        self.estimador = estimador
        self.codificador = codificador
        self.calibrador = calibrador
        self.cortes = cortes            # {"alto": p, "medio": p}
        self.nombre_modelo = nombre_modelo
        self.info = info
        self.variables = list(variables or VARIABLES_MODELO)
        self.cod_servicio = cod_servicio

    def matriz(self, df):
        return matriz(df, self.codificador, self.variables, getattr(self, "cod_servicio", None))

    def probabilidad(self, df):
        x = self.matriz(df)
        return self.calibrador.aplicar(self.estimador.predict_proba(x)[:, 1])

    def nivel(self, p):
        p = np.asarray(p)
        return np.where(p >= self.cortes["alto"], "alto", np.where(p >= self.cortes["medio"], "medio", "bajo"))

    def guardar(self, ruta):
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, ruta)

    @staticmethod
    def cargar(ruta):
        return joblib.load(ruta)


def cortes_por_percentil(p, alto, medio):
    return {"alto": float(np.quantile(p, 1 - alto)), "medio": float(np.quantile(p, 1 - alto - medio))}


def entrenar(df, cfg, log=print):
    e = cfg["entrenamiento"]
    df = agregar_historial(df)
    ent, val, pru = particion_temporal(df, e["proporcion_validacion"], e["proporcion_prueba"])
    log(f"Partición temporal: entrenamiento {len(ent)}, validación {len(val)}, prueba {len(pru)}")

    cod = CodificadorZona(e["suavizado_zona"]).ajustar(ent["zona"], ent["falto"])
    variables, cod_serv = list(VARIABLES_MODELO), None
    if "servicio" in df and ent["servicio"].nunique() > 1:      # especialidad: misma técnica que la zona
        cod_serv = CodificadorZona(e["suavizado_zona"]).ajustar(ent["servicio"], ent["falto"])
        variables.append("tasa_servicio")
    if "turno_tarde" in df and ent["turno_tarde"].nunique() > 1:
        variables.append("turno_tarde")
    log(f"Variables del modelo ({len(variables)}): {', '.join(variables)}")
    xe, xv, xp = (matriz(d, cod, variables, cod_serv) for d in (ent, val, pru))

    resultados, ajustados = {}, {}
    for nombre, est in candidatos(e["semilla"]).items():
        est.fit(xe, ent["falto"])
        pv = est.predict_proba(xv)[:, 1]
        resultados[nombre] = {"auc_validacion": round(float(roc_auc_score(val["falto"], pv)), 4)}
        ajustados[nombre] = est
        log(f"  {nombre}: AUC validación = {resultados[nombre]['auc_validacion']}")

    mejor = max(resultados, key=lambda k: resultados[k]["auc_validacion"])
    est = ajustados[mejor]
    cal = Calibrador().ajustar(est.predict_proba(xv)[:, 1], val["falto"].to_numpy())
    pv = cal.aplicar(est.predict_proba(xv)[:, 1])
    n = cfg["niveles"]
    cortes = cortes_por_percentil(pv, n["alto_percentil"], n["medio_percentil"])

    # Regla 80/20: elegido el modelo, se reentrena con todo el 80 % (entrenamiento + validación);
    # el 20 % más reciente (prueba) sigue sin usarse hasta la evaluación final.
    e80 = pd.concat([ent, val])
    cod = CodificadorZona(e["suavizado_zona"]).ajustar(e80["zona"], e80["falto"])
    if cod_serv is not None:
        cod_serv = CodificadorZona(e["suavizado_zona"]).ajustar(e80["servicio"], e80["falto"])
    x80, xp = matriz(e80, cod, variables, cod_serv), matriz(pru, cod, variables, cod_serv)
    ajustados = {k: clone(m).fit(x80, e80["falto"]) for k, m in candidatos(e["semilla"]).items()}
    est = ajustados[mejor]
    log(f"Modelo final ({mejor}) reentrenado con el 80 % ({len(e80)} citas)")

    # Evaluación final en prueba (datos nunca vistos)
    eval_prueba = {}
    for nombre, m in ajustados.items():
        pp_m = cal.aplicar(m.predict_proba(xp)[:, 1]) if nombre == mejor else m.predict_proba(xp)[:, 1]
        umbral = cortes["alto"] if nombre == mejor else float(np.quantile(pp_m, 1 - n["alto_percentil"]))
        eval_prueba[nombre] = metricas(pru["falto"], pp_m, umbral)
    pp = cal.aplicar(est.predict_proba(xp)[:, 1])
    eval_prueba[mejor]["brier"] = round(float(brier_score_loss(pru["falto"], pp)), 4)

    # Desempeño por tramo de anticipación (el mismo día se reporta aparte)
    tramos = pd.cut(pru["dias_anticipacion"], [-1, 0, 2, 7, 14, 30, 10_000],
                    labels=["mismo día", "1-2", "3-7", "8-14", "15-30", ">30"])
    por_tramo = []
    for t, idx in pru.groupby(tramos, observed=True).groups.items():
        y = pru.loc[idx, "falto"]
        p_t = pd.Series(pp, index=pru.index).loc[idx]
        fila = {"tramo": str(t), "citas": int(len(idx)), "inasistencia": round(float(y.mean()), 4)}
        fila["auc"] = round(float(roc_auc_score(y, p_t)), 4) if y.nunique() == 2 else None
        por_tramo.append(fila)
    sin_mismo_dia = pru["dias_anticipacion"] > 0
    comparacion = comparar_con_reglas(pru, pp, n["alto_percentil"], mejor)
    auc_sin_mismo_dia = round(float(roc_auc_score(pru.loc[sin_mismo_dia, "falto"], pd.Series(pp, index=pru.index)[sin_mismo_dia])), 4)

    fpr, tpr, _ = roc_curve(pru["falto"], pp)
    paso = max(1, len(fpr) // 200)
    info = {
        "datos": cfg["nombre"],
        "variables": variables,
        "modelo_elegido": mejor,
        "validacion": resultados,
        "prueba": eval_prueba,
        "auc_prueba_sin_citas_mismo_dia": auc_sin_mismo_dia,
        "por_tramo_anticipacion": por_tramo,
        "tasa_global_entrenamiento": round(cod.global_, 4),
        "cortes_nivel": {k: round(v, 4) for k, v in cortes.items()},
        "n": {"entrenamiento": len(ent), "validacion": len(val), "prueba": len(pru)},
        "particion": "80/20 temporal: el 80 % más antiguo para entrenar (su último cuarto sirve para elegir el modelo "
                     "y calibrar; luego se reentrena con todo el 80 %) y el 20 % más reciente para la prueba final",
        "comparacion_prueba": comparacion,
        "porcentaje_alto_en_prueba": round(float((pp >= cortes["alto"]).mean()), 4),
        "fechas": {"inicio": str(df["fecha_cita"].min().date()), "fin": str(df["fecha_cita"].max().date())},
        "roc": {"fpr": fpr[::paso].round(4).tolist(), "tpr": tpr[::paso].round(4).tolist()},
        "importancia": importancia_permutacion(est, xp, pru["falto"], e["semilla"]),
    }
    sistema = SistemaRiesgo(est, cod, cal, cortes, mejor, info, variables, cod_serv)
    return sistema, df, pru.assign(probabilidad=pp)


def _captura(y, p, frac):
    """% de las inasistencias reales que caen en el `frac` de citas con mayor puntaje."""
    y = np.asarray(y); k = max(1, int(len(y) * frac))
    return float(y[np.argsort(-np.asarray(p))[:k]].sum() / max(1, y.sum()))


def comparar_con_reglas(pru, pp, frac, nombre):
    """Mejora medida en el 20 % de prueba: modelo frente a no usar modelo (azar) y a una regla simple."""
    ag = (pru["dias_anticipacion"] > 0).to_numpy()
    y = pru["falto"].to_numpy()
    filas = []
    for metodo, s in [("Sin modelo (al azar)", None), ("Regla: solo días de anticipación", pru["dias_anticipacion"].to_numpy(float)),
                      (f"Modelo ({nombre})", np.asarray(pp))]:
        if s is None:
            filas.append({"metodo": metodo, "auc_total": 0.5, "auc_agendadas": 0.5, "captura_top": frac})
            continue
        filas.append({"metodo": metodo, "auc_total": round(float(roc_auc_score(y, s)), 4),
                      "auc_agendadas": round(float(roc_auc_score(y[ag], s[ag])), 4),
                      "captura_top": round(_captura(y[ag], s[ag], frac), 4)})
    return filas


def importancia_permutacion(est, x, y, semilla):
    from sklearn.inspection import permutation_importance
    muestra = x.sample(min(8000, len(x)), random_state=semilla)
    r = permutation_importance(est, muestra, y.loc[muestra.index], scoring="roc_auc", n_repeats=5,
                               random_state=semilla, n_jobs=-1)
    imp = pd.Series(r.importances_mean, index=x.columns).sort_values(ascending=False)
    return {k: round(float(v), 4) for k, v in imp.items()}


def recalibrar(sistema, df_local, cfg):
    """Paso 2 de la transferencia: ajusta % y umbrales con pocos datos locales, sin reentrenar."""
    df_local = agregar_historial(df_local)
    p_crudo = sistema.estimador.predict_proba(sistema.matriz(df_local))[:, 1]
    sistema.calibrador = Calibrador().ajustar(p_crudo, df_local["falto"].to_numpy())
    p = sistema.calibrador.aplicar(p_crudo)
    n = cfg["niveles"]
    sistema.cortes = cortes_por_percentil(p, n["alto_percentil"], n["medio_percentil"])
    sistema.info["recalibrado_con"] = {"datos": cfg["nombre"], "citas": int(len(df_local)),
                                       "auc_local": round(float(roc_auc_score(df_local["falto"], p)), 4)}
    return sistema


class Explicador:
    """Explicación por caso con SHAP: qué variables subieron o bajaron el riesgo."""

    def __init__(self, sistema, fondo):
        import os
        self.sistema = sistema
        x_fondo = sistema.matriz(fondo).sample(min(200, len(fondo)), random_state=0)
        self.tipico = x_fondo.median()          # valor "típico" de cada variable, para la explicación liviana
        self.exp, self.pre = None, None
        if os.getenv("NOSHOW_SIN_SHAP"):        # servidores con poca memoria: explicación liviana, sin SHAP
            return
        try:
            import shap
        except ImportError:
            return
        est = sistema.estimador
        if hasattr(est, "steps"):
            self.exp = shap.LinearExplainer(est.steps[-1][1], est.steps[0][1].transform(x_fondo))
            self.pre = est.steps[0][1]
        else:
            self.exp = shap.TreeExplainer(est, x_fondo)

    def _explicar_liviano(self, x, top):
        """Aporte de cada variable = cambio del riesgo al reemplazarla por su valor típico (sin SHAP, casi sin memoria)."""
        base = self.sistema.estimador.predict_proba(x)[:, 1]
        aportes = {}
        for col in x.columns:
            x_t = x.copy()
            x_t[col] = self.tipico[col]
            aportes[col] = base - self.sistema.estimador.predict_proba(x_t)[:, 1]
        filas = []
        for i in range(len(x)):
            s = pd.Series({c: aportes[c][i] for c in x.columns}).sort_values(key=np.abs, ascending=False).head(top)
            filas.append([(k, float(v), float(x.iloc[i][k])) for k, v in s.items()])
        return filas

    def explicar(self, df_caso, top=3):
        x = self.sistema.matriz(df_caso)
        if self.exp is None:
            return self._explicar_liviano(x, top)
        xv = self.pre.transform(x) if self.pre is not None else x
        valores = self.exp.shap_values(xv)
        if isinstance(valores, list):
            valores = valores[1]
        valores = np.asarray(valores)
        if valores.ndim == 3:
            valores = valores[..., 1]
        filas = []
        for i in range(len(x)):
            s = pd.Series(valores[i], index=x.columns).sort_values(key=np.abs, ascending=False).head(top)
            filas.append([(k, float(v), float(x.iloc[i][k])) for k, v in s.items()])
        return filas


def guardar_reporte(info, ruta):
    Path(ruta).write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
