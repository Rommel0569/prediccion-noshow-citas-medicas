"""Panel de control: resumen operativo de la agenda en gestión."""
import matplotlib.pyplot as plt
import streamlit as st

from interfaz import comun as c
from noshow.impacto import resumen_agenda

agenda, cfg = c.obtener_agenda()
if agenda.empty:
    c.encabezado("Panel de control", "Resumen operativo de la agenda en gestión")
    c.aviso_sin_citas()
    st.stop()
r = resumen_agenda(agenda, {}, cfg)
canal = agenda["canal_accion"]
llamadas, visitas = int((canal == "llamada").sum()), int((canal == "visita").sum())
mensajes = int(canal.isin(["whatsapp", "sms"]).sum())

c.encabezado("Panel de control", "Resumen operativo de la agenda en gestión", f"Fuente: {c.origen_agenda()}")

k = st.columns(5)
k[0].metric("Citas en agenda", c.num(r["citas"]), border=True)
k[1].metric("Inasistencias esperadas", c.num(r["inasistencias_esperadas_sin_intervencion"]), border=True,
            help="Suma de las probabilidades de inasistencia, sin intervención.")
k[2].metric("Inasistencias evitables", c.num(r["inasistencias_evitadas"]), f"-{r['reduccion_relativa'] * 100:.0f} %",
            delta_color="inverse", border=True, help="Con la estrategia de contacto recomendada.")
k[3].metric("Contactos asignados", c.num(llamadas + mensajes + visitas), border=True,
            help=f"{c.num(llamadas)} llamadas, {c.num(mensajes)} mensajes, {c.num(visitas)} visitas.")
k[4].metric("Costo de contacto", f"S/ {c.num(r['costo_total_contacto'], 2)}", border=True)

c.seccion("Distribución de la agenda")
g1, g2 = st.columns(2)
with g1:
    niveles = [n for n in ("alto", "medio", "bajo")]
    valores = [int((agenda["nivel"] == n).sum()) for n in niveles]
    fig, ax = plt.subplots(figsize=(5.2, 2.9))
    barras = ax.bar([c.NIVELES[n] for n in niveles], valores, color=[c.COLOR_NIVEL[n] for n in niveles], width=.55)
    ax.bar_label(barras, labels=[c.num(v) for v in valores], padding=3, fontsize=9)
    ax.set_title("Citas por nivel de riesgo"); ax.grid(axis="x", visible=False)
    ax.set_ylim(0, max(valores) * 1.15)
    st.pyplot(fig, clear_figure=True)
with g2:
    cuenta = canal.value_counts().reindex(["llamada", "whatsapp", "sms", "visita", "ninguno"]).dropna()
    fig, ax = plt.subplots(figsize=(5.2, 2.9))
    barras = ax.barh([c.CANAL[i] for i in cuenta.index][::-1], cuenta.values[::-1], color=c.AZUL, height=.55)
    ax.bar_label(barras, labels=[c.num(v) for v in cuenta.values[::-1]], padding=3, fontsize=9)
    ax.set_title("Citas por acción asignada"); ax.grid(axis="y", visible=False)
    ax.set_xlim(0, cuenta.max() * 1.15)
    st.pyplot(fig, clear_figure=True)

c.seccion("Resumen económico")
e = st.columns(4)
evit = r["inasistencias_evitadas"]
e[0].metric("Costo por inasistencia evitada",
            f"S/ {c.num(r['costo_por_inasistencia_evitada'], 2)}" if r["costo_por_inasistencia_evitada"] else "—", border=True)
e[1].metric("Valor de consultas recuperadas", f"S/ {c.num(r['valor_consultas_recuperadas'])}", border=True,
            help=f"Inasistencias evitadas × S/ {c.num(cfg['costos']['valor_consulta'], 2)} por consulta (parámetro configurable).")
e[2].metric("Beneficio neto estimado", f"S/ {c.num(r['valor_consultas_recuperadas'] - r['costo_total_contacto'])}", border=True)
e[3].metric("Capacidad de llamadas", c.pct(cfg["niveles"]["alto_percentil"], 0), border=True,
            help="Porcentaje de la agenda que el personal puede llamar. Se modifica en Configuración.")
c.nota("Las estimaciones usan la efectividad de cada canal medida en los datos (mensajes) y la reportada en la literatura "
       "(llamada y visita). El valor por consulta es un supuesto del establecimiento.")

c.seccion("Citas con atención prioritaria")
prior = agenda[agenda["prioridad_llamada"]].head(10)
vista = c.vista_agenda(prior)[["N.° de cita", "Fecha de cita", "Anticipación (días)", "Inasistencias previas",
                               "Riesgo", "Nivel", "Acción asignada", "Momento del contacto"]]
st.dataframe(c.estilo_nivel(vista), hide_index=True, use_container_width=True, column_config=c.CONFIG_TABLA)
st.page_link("paginas/contactos.py", label="Abrir la agenda de contactos completa", icon=":material/arrow_forward:")

