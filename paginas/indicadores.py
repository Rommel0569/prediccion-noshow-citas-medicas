"""Indicadores de gestión: impacto de la estrategia de contacto frente a la práctica actual."""
import json

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from interfaz import comun as c
from noshow.config import RAIZ
from noshow.impacto import escenarios

sistema = c.cargar_sistema()
info = sistema.info
ev_path = RAIZ / "modelos" / "evaluacion.json"

c.encabezado("Indicadores de gestión", "Impacto de la estrategia de contacto frente a la práctica actual",
             "Evaluación sobre citas reales no usadas en el entrenamiento")

if not ev_path.exists():
    st.warning("Falta el archivo de evaluación. Ejecute: python evaluar.py")
    st.stop()
ev = json.loads(ev_path.read_text(encoding="utf-8"))
est = pd.DataFrame(ev["estrategias_prueba"])
total = int(est["inasistencias_reales"].iloc[0])


def fila(nombre):
    return est[est["estrategia"].str.contains(nombre, regex=False)].iloc[0]


actual, sistema_prop = fila("práctica actual"), fila("Sistema propuesto sin visitas")
llamar_todos = fila("Llamar a todas")

c.seccion("Resultado principal")
k = st.columns(4)
k[0].metric("Inasistencias evitadas (sistema)", c.pct(sistema_prop["evitadas"] / total), border=True,
            help=f"{c.num(sistema_prop['evitadas'])} de {c.num(total)} inasistencias reales de la prueba.")
k[1].metric("Inasistencias evitadas (práctica actual)", c.pct(actual["evitadas"] / total), border=True,
            help="SMS a todas las citas.")
k[2].metric("Costo por inasistencia evitada", f"S/ {c.num(sistema_prop['costo_por_evitada'], 2)}", border=True,
            help=f"Práctica actual: S/ {c.num(actual['costo_por_evitada'], 2)}.")
k[3].metric("Efecto frente a llamar a todos", c.pct(sistema_prop["evitadas"] / llamar_todos["evitadas"], 0), border=True,
            help=f"Con {c.pct(sistema_prop['costo_total'] / llamar_todos['costo_total'], 0)} del costo.")

c.seccion("Comparativo de estrategias de contacto")
orden = est.sort_values("evitadas")
fig, ax = plt.subplots(figsize=(9.5, 3.6))
colores = [c.AZUL if "sin visitas" in n else c.GRIS for n in orden["estrategia"]]
barras = ax.barh(orden["estrategia"], orden["evitadas"], color=colores, height=.6)
ax.bar_label(barras, labels=[c.num(v) for v in orden["evitadas"]], padding=3, fontsize=8)
ax.set_title("Inasistencias evitadas por estrategia"); ax.grid(axis="y", visible=False)
ax.set_xlim(0, orden["evitadas"].max() * 1.12)
st.pyplot(fig, clear_figure=True)
tabla = est.drop(columns=["visitas"], errors="ignore").rename(columns={
    "estrategia": "Estrategia", "inasistencias_reales": "Inasistencias reales", "evitadas": "Evitadas",
    "tasa_resultante": "Tasa resultante", "reduccion_relativa": "Reducción", "costo_total": "Costo (S/)",
    "costo_por_evitada": "S/ por evitada", "llamadas": "Llamadas"})
st.dataframe(tabla, hide_index=True, use_container_width=True, column_config={
    "Tasa resultante": st.column_config.NumberColumn(format="percent"),
    "Reducción": st.column_config.NumberColumn(format="percent"),
    "Costo (S/)": st.column_config.NumberColumn(format="%.0f"),
    "S/ por evitada": st.column_config.NumberColumn(format="%.2f"),
    "Evitadas": st.column_config.NumberColumn(format="%.0f"),
})
c.nota("Una inasistencia alcanzada por un canal se evita con la probabilidad del efecto de ese canal: mensajes, medido en los datos "
       "por anticipación; llamada y visita, según la literatura. Mensajes y llamadas solo llegan a quien tiene celular.")

m = ev["muestras_100"]
c.seccion("Priorización con el modelo")
q = st.columns(4)
q[0].metric("Inasistencias en 100 citas", c.num(m["inasistencias_promedio"], 1), border=True)
q[1].metric("Halladas en 20 citas (modelo)", c.num(m["encontradas_modelo"], 1), border=True)
q[2].metric("Halladas en 20 citas (azar)", c.num(m["encontradas_azar"], 1), border=True)
q[3].metric("Muestras en que el modelo supera al azar", c.pct(m["modelo_supera_azar_pct"], 0), border=True)
c.nota(f"Promedio de {c.num(m['n_muestras'])} grupos de 100 citas reales. Referencia con la regla de solo anticipación: "
       f"{c.num(m['encontradas_regla_anticipacion'], 1)}.")

if "efecto_recordatorio" in info:
    e = info["efecto_recordatorio"]
    c.seccion("Efecto del recordatorio por SMS")
    t = pd.DataFrame(e["tramos"])
    g1, g2 = st.columns([3, 2], gap="large")
    with g1:
        fig, ax = plt.subplots(figsize=(5.6, 3.1))
        x = range(len(t))
        ax.bar([i - .2 for i in x], t["sin_sms"] * 100, .4, label="Sin SMS", color=c.GRIS)
        ax.bar([i + .2 for i in x], t["con_sms"] * 100, .4, label="Con SMS", color=c.AZUL)
        ax.set_xticks(list(x)); ax.set_xticklabels([f"{v} días" for v in t["tramo_dias"]])
        ax.set_ylabel("Inasistencia (%)"); ax.legend(); ax.set_title("Inasistencia según anticipación de la cita")
        ax.grid(axis="x", visible=False)
        st.pyplot(fig, clear_figure=True)
    with g2:
        st.dataframe(t.rename(columns={"tramo_dias": "Anticipación (días)", "citas": "Citas", "sin_sms": "Sin SMS",
                                       "con_sms": "Con SMS", "puntos_menos": "Puntos menos",
                                       "reduccion_relativa": "Reducción"}),
                     hide_index=True, use_container_width=True, column_config={
                         "Sin SMS": st.column_config.NumberColumn(format="percent"),
                         "Con SMS": st.column_config.NumberColumn(format="percent"),
                         "Reducción": st.column_config.NumberColumn(format="percent")})
        st.markdown(f"Reducción ajustada por anticipación (Mantel-Haenszel): **{c.pct(e['reduccion_relativa'])}**.")
    c.nota("La comparación sin ajustar sería engañosa: el SMS solo se envió a citas con tres o más días de anticipación, "
           "que son las que más se pierden. Es una asociación observacional; el efecto de cada canal debe confirmarse con un piloto.")

c.seccion("Escenarios de impacto")
esc = escenarios(info["tasa_global_entrenamiento"]).rename(columns={
    "escenario": "Escenario", "reduccion_relativa": "Reducción relativa", "respaldo": "Respaldo",
    "inasistencia_resultante": "Inasistencia resultante"})
st.dataframe(esc, hide_index=True, use_container_width=True, column_config={
    "Reducción relativa": st.column_config.NumberColumn(format="percent"),
    "Inasistencia resultante": st.column_config.NumberColumn(format="percent")})

c.seccion("Confirmación en campo")
pil = ev["piloto"]["citas_por_grupo_para_detectar"]
st.markdown("Los resultados de esta página son una simulación con inasistencias reales. Para confirmar el efecto de cada canal "
            "se recomienda un piloto aleatorizado. Citas necesarias por grupo según la reducción que se desea detectar:")
st.dataframe(pd.DataFrame({"Reducción relativa a detectar": list(pil.keys()),
                           "Citas por grupo": [c.num(v) for v in pil.values()]}),
             hide_index=True, use_container_width=False)
