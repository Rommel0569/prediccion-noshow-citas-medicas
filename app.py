"""Gestión de inasistencias a citas médicas: aplicación web (Streamlit).

Ejecutar:  streamlit run app.py
"""
from pathlib import Path

import streamlit as st

from interfaz import comun as c

st.set_page_config(page_title="Gestión de Inasistencias", page_icon=":material/medical_services:", layout="wide")
c.inyectar_estilos()
st.logo(str(Path(__file__).parent / "interfaz" / "logo.svg"), size="large")

if not c.MODELO.exists():
    st.error("No se encontró el modelo. Ejecute primero: python entrenar.py --config config/kaggle_brasil.yaml")
    st.stop()

navegacion = st.navigation({
    "Operación": [
        st.Page("paginas/panel.py", title="Panel de control", icon=":material/space_dashboard:", default=True),
        st.Page("paginas/programar.py", title="Programación de citas", icon=":material/edit_calendar:"),
        st.Page("paginas/contactos.py", title="Agenda y contactos", icon=":material/contact_phone:"),
        st.Page("paginas/cupos.py", title="Confirmaciones y cupos", icon=":material/swap_horiz:"),
    ],
    "Análisis": [
        st.Page("paginas/indicadores.py", title="Indicadores de gestión", icon=":material/monitoring:"),
        st.Page("paginas/calidad_modelo.py", title="Calidad del modelo", icon=":material/fact_check:"),
    ],
    "Administración": [
        st.Page("paginas/configuracion.py", title="Configuración", icon=":material/tune:"),
        st.Page("paginas/establecimientos.py", title="Incorporar establecimiento", icon=":material/add_business:"),
    ],
})

info = c.cargar_sistema().info
with st.sidebar:
    st.divider()
    st.markdown(
        f'<div class="nota"><b>Modelo</b>: {info["modelo_elegido"]}<br>'
        f'<b>AUC en prueba</b>: {info["prueba"][info["modelo_elegido"]]["auc"]:.3f}<br>'
        f'<b>Entorno</b>: demostración<br>Canales y confirmaciones simulados.</div>',
        unsafe_allow_html=True)

navegacion.run()
