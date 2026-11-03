"""Calidad del modelo: validación del desempeño predictivo."""
import json

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from interfaz import comun as c
from noshow import NOMBRES_LEGIBLES
from noshow.config import RAIZ

sistema = c.cargar_sistema()
info = sistema.info
elegido = info["modelo_elegido"]
pr = info["prueba"][elegido]
n = info["n"]

c.encabezado("Calidad del modelo", "Validación del desempeño predictivo sobre citas no usadas en el entrenamiento",
             f"Modelo: {elegido}")

comp = info.get("comparacion_prueba")
k = st.columns(4)
k[0].metric("AUC-ROC", f"{pr['auc']:.3f}", border=True, help="Capacidad de ordenar las citas por riesgo (0,5 = azar).")
k[1].metric("PR-AUC", f"{pr['pr_auc']:.3f}", border=True)
if comp:
    k[2].metric("Inasistencias en el 20 % marcado", c.pct(comp[-1]["captura_top"]), f"frente a {c.pct(comp[0]['captura_top'], 0)} al azar",
                border=True, help="Porcentaje de las inasistencias reales que quedan entre las citas marcadas para contacto.")
k[3].metric("Brier", f"{pr.get('brier', float('nan')):.3f}", border=True, help="Calidad de las probabilidades (menor es mejor).")

c.seccion("Diseño de la validación")
st.markdown(f"Partición temporal 80/20: entrenamiento {c.num(n['entrenamiento'])} y validación {c.num(n['validacion'])} citas "
            f"(80 %, las más antiguas); prueba {c.num(n['prueba'])} citas (20 %, las más recientes, sin intervenir en el "
            f"entrenamiento). Fechas de las citas: {info['fechas']['inicio']} a {info['fechas']['fin']}.")

if comp:
    c.seccion("Mejora frente a no usar modelo")
    t = pd.DataFrame(comp).rename(columns={"metodo": "Método", "auc_total": "AUC total", "auc_agendadas": "AUC citas agendadas",
                                           "captura_top": "Inasistencias en el 20 % marcado"})
    st.dataframe(t, hide_index=True, use_container_width=True, column_config={
        "Inasistencias en el 20 % marcado": st.column_config.NumberColumn(format="percent"),
        "AUC total": st.column_config.NumberColumn(format="%.3f"),
        "AUC citas agendadas": st.column_config.NumberColumn(format="%.3f")})
    mod, azar = comp[-1]["captura_top"], comp[0]["captura_top"]
    c.nota(f"Con la misma capacidad de contacto, el modelo encuentra {c.pct(mod / azar - 1, 0)} más inasistencias que elegir al azar.")

c.seccion("Comparación de algoritmos")
alg = pd.DataFrame(info["prueba"]).T.reset_index().rename(columns={
    "index": "Algoritmo", "auc": "AUC", "pr_auc": "PR-AUC", "recall": "Recall", "precision": "Precisión", "f1": "F1",
    "umbral": "Umbral", "brier": "Brier"})
st.dataframe(alg, hide_index=True, use_container_width=True)
c.nota("Recall, precisión y F1 consideran como positivo el nivel de riesgo alto.")

g1, g2 = st.columns(2, gap="large")
with g1:
    fig, ax = plt.subplots(figsize=(4.6, 4))
    ax.plot(info["roc"]["fpr"], info["roc"]["tpr"], color=c.AZUL, lw=2, label=f"{elegido} (AUC {pr['auc']:.3f})")
    ax.plot([0, 1], [0, 1], "--", color=c.GRIS, label="Azar")
    ax.set_xlabel("Tasa de falsos positivos"); ax.set_ylabel("Tasa de verdaderos positivos")
    ax.set_title("Curva ROC en el 20 % de prueba"); ax.legend(loc="lower right")
    st.pyplot(fig, clear_figure=True)
with g2:
    imp = pd.Series(info["importancia"]).rename(NOMBRES_LEGIBLES).sort_values()
    fig, ax = plt.subplots(figsize=(4.6, 4))
    ax.barh(imp.index, imp.values, color=c.AZUL, height=.6)
    ax.set_title("Importancia de las variables"); ax.set_xlabel("Caída del AUC al permutar la variable")
    ax.grid(axis="y", visible=False)
    st.pyplot(fig, clear_figure=True)

c.seccion("Desempeño por anticipación de la cita")
tr = pd.DataFrame(info["por_tramo_anticipacion"]).rename(columns={
    "tramo": "Anticipación (días)", "citas": "Citas", "inasistencia": "Inasistencia", "auc": "AUC"})
st.dataframe(tr, hide_index=True, use_container_width=True, column_config={
    "Inasistencia": st.column_config.NumberColumn(format="percent"), "AUC": st.column_config.NumberColumn(format="%.3f")})
c.nota(f"Dentro de cada tramo el desempeño es menor: la anticipación es el factor dominante. AUC excluyendo las citas del "
       f"mismo día: {info['auc_prueba_sin_citas_mismo_dia']:.3f}.")

exp = RAIZ / "modelos" / "experimento_segmentacion.json"
if exp.exists():
    c.seccion("Modelo único frente a modelos por grupo")
    r = pd.DataFrame(json.loads(exp.read_text(encoding="utf-8"))["resultados"]).rename(columns={
        "enfoque": "Enfoque", "auc_agendadas": "AUC citas agendadas",
        "captura_top_agendadas": "Inasistencias en el 20 % marcado"})
    st.dataframe(r, hide_index=True, use_container_width=True, column_config={
        "Inasistencias en el 20 % marcado": st.column_config.NumberColumn(format="percent"),
        "AUC citas agendadas": st.column_config.NumberColumn(format="%.3f")})
    c.nota("Separar el modelo por grupos no mejora el desempeño con estos datos. La segmentación se aplica en la decisión de "
           "contacto (anticipación y nivel de riesgo).")

pc_path = RAIZ / "modelos" / "pruebas_casos.json"
if pc_path.exists():
    pc = json.loads(pc_path.read_text(encoding="utf-8"))
    c.seccion("Pruebas del sistema")
    st.markdown("Verificaciones automáticas sobre 100 casos de prueba variados (distritos, especialidades, horas, canales y "
                "tiempos de espera) generados para Arequipa; no corresponden a pacientes reales.")
    st.dataframe(pd.DataFrame(pc["pruebas"]).rename(columns={"prueba": "Verificación", "resultado": "Resultado"}),
                 hide_index=True, use_container_width=True)
    grupos = pd.DataFrame(pc["por_grupo"]).rename(columns={
        "grupo": "Grupo de anticipación", "casos": "Casos", "riesgo_promedio": "Riesgo promedio", "llamadas": "Llamadas",
        "mensajes": "Mensajes", "visitas": "Visitas", "sin_accion": "Sin acción", "costo": "Costo (S/)"})
    st.dataframe(grupos, hide_index=True, use_container_width=True, column_config={
        "Riesgo promedio": st.column_config.NumberColumn(format="percent")})
