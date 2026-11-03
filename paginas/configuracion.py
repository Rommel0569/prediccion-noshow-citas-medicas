"""Configuración: parámetros de operación del establecimiento."""
import pandas as pd
import streamlit as st

from interfaz import comun as c
from noshow import parametros as parametros_mod

sistema = c.cargar_sistema()
base, vigente = c.parametros_base(), c.parametros()
cfg = c.cfg_activa()

c.encabezado("Configuración", "Parámetros de operación del establecimiento",
             "Los cambios los usan la web y el servicio del bot")

c.seccion("Capacidad y costos")
with st.form("form_parametros"):
    cap = st.slider("Capacidad de llamadas (% de la agenda)", 5, 50, int(round(vigente["capacidad"] * 100)),
                    help="Porcentaje de las citas de la agenda que el personal puede llamar.") / 100
    a, b, d, e = st.columns(4)
    sms = a.number_input("SMS (S/)", 0.0, 10.0, float(vigente["sms"]), 0.01, format="%.3f")
    wsp = b.number_input("WhatsApp (S/)", 0.0, 10.0, float(vigente["whatsapp"]), 0.01, format="%.3f")
    lla = d.number_input("Llamada (S/)", 0.0, 100.0, float(vigente["llamada"]), 0.1, format="%.2f")
    vis = e.number_input("Visita domiciliaria (S/)", 0.0, 500.0, float(vigente["visita"]), 1.0, format="%.2f")
    consulta = st.number_input("Valor de una consulta perdida (S/)", 0.0, 1000.0, float(vigente["consulta"]), 1.0, format="%.2f")
    nombre = st.text_input("Nombre del establecimiento (aparece en los mensajes a los pacientes)",
                           parametros_mod.establecimiento())
    g1, g2 = st.columns([1, 5])
    guardar = g1.form_submit_button("Aplicar cambios", type="primary")
    restablecer = g2.form_submit_button("Restablecer valores del archivo")
if guardar:
    parametros_mod.guardar({"capacidad": cap, "sms": sms, "whatsapp": wsp, "llamada": lla, "visita": vis, "consulta": consulta})
    parametros_mod.guardar_establecimiento(nombre)
    st.success("Parámetros guardados. Los usan la web y el servicio del bot.")
elif restablecer:
    parametros_mod.restablecer()
    st.rerun()
c.nota("Los valores iniciales provienen de config/kaggle_brasil.yaml. El costo de SMS corresponde a una tarifa comercial "
       "peruana; la llamada, la visita y el valor de la consulta son supuestos que deben reemplazarse por costos reales del establecimiento.")

c.seccion("Reglas vigentes")
r1, r2 = st.columns(2, gap="large")
with r1:
    st.markdown("**Niveles de riesgo**")
    st.markdown(f"- Alto: probabilidad igual o mayor a {c.pct(sistema.cortes['alto'])}\n"
                f"- Medio: igual o mayor a {c.pct(sistema.cortes['medio'])}\n- Bajo: menor a ese valor")
    st.markdown("**Plazo de confirmación**")
    st.markdown(f"- {cfg.get('reasignacion', {}).get('horas_limite_confirmacion', 24)} horas antes de la cita")
with r2:
    st.markdown("**Reducción esperada por canal**")
    ef = cfg["efecto_canal"]
    st.markdown(f"- Mensaje: medido en los datos según la anticipación (literatura: {c.pct(ef['sms'], 0)})\n"
                f"- Llamada: {c.pct(ef['llamada'], 0)}\n- Visita domiciliaria: {c.pct(ef['visita'], 0)}")
    st.markdown("**Política de contacto**")
    st.markdown("- Citas del mismo día: sin recordatorio\n- Llamada: citas con mayor beneficio por sol, hasta la capacidad\n"
                "- Resto: mensajes según el riesgo\n- Visita: riesgo alto, sin celular y crónico o reincidente")

c.seccion("Modelo en uso")
st.dataframe(pd.DataFrame([
    ("Algoritmo", sistema.info["modelo_elegido"]),
    ("Datos de entrenamiento", sistema.info["datos"]),
    ("Variables", ", ".join(sistema.variables)),
    ("AUC en prueba", f"{sistema.info['prueba'][sistema.info['modelo_elegido']]['auc']:.3f}"),
], columns=["Característica", "Valor"]), hide_index=True, use_container_width=True)

