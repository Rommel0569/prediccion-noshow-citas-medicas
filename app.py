"""Gestión de inasistencias a citas médicas: aplicación web (Streamlit).

Ejecutar:  streamlit run app.py
"""
import hmac
import os
from pathlib import Path

import streamlit as st

from interfaz import comun as c
from noshow.contacto import servicio
from noshow.contacto.canales import cargar_canales
from noshow.contacto.equipo import cargar_equipo

st.set_page_config(page_title="Gestión de Inasistencias", page_icon=":material/medical_services:", layout="wide")
c.inyectar_estilos()
st.logo(str(Path(__file__).parent / "interfaz" / "logo.svg"), size="large")

def _acceso():
    """Si APP_PASSWORD está definida (despliegue), exige la contraseña antes de mostrar cualquier dato."""
    clave = os.getenv("APP_PASSWORD")
    if not clave or st.session_state.get("autenticado"):
        return True
    c.encabezado("Gestión de Inasistencias", "Acceso restringido al personal del establecimiento")
    with st.form("acceso"):
        ingresada = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button("Ingresar", type="primary")
    if entrar and hmac.compare_digest(ingresada.encode(), clave.encode()):
        st.session_state["autenticado"] = True
        st.rerun()
    elif entrar:
        st.error("Contraseña incorrecta.")
    return False


if not _acceso():
    st.stop()

if not c.MODELO.exists():
    st.error("No se encontró el modelo. Ejecute primero: python entrenar.py --config config/kaggle_brasil.yaml")
    st.stop()


@st.cache_resource
def _cargar_equipo_una_vez():
    return cargar_equipo()      # teléfonos del equipo desde config/equipo.local.csv, si el archivo existe


_cargar_equipo_una_vez()

navegacion = st.navigation({
    "Operación": [
        st.Page("paginas/panel.py", title="Panel de control", icon=":material/space_dashboard:", default=True),
        st.Page("paginas/admision.py", title="Admisión de pacientes", icon=":material/how_to_reg:"),
        st.Page("paginas/programar.py", title="Programación de citas", icon=":material/edit_calendar:"),
        st.Page("paginas/citas.py", title="Citas registradas", icon=":material/event_note:"),
        st.Page("paginas/contactos.py", title="Agenda y contactos", icon=":material/contact_phone:"),
        st.Page("paginas/registro.py", title="Registro de contactos", icon=":material/forum:"),
        st.Page("paginas/cupos.py", title="Confirmaciones y cupos", icon=":material/swap_horiz:"),
    ],
    "Análisis": [
        st.Page("paginas/indicadores.py", title="Indicadores de gestión", icon=":material/monitoring:"),
        st.Page("paginas/calidad_modelo.py", title="Calidad del modelo", icon=":material/fact_check:"),
    ],
    "Administración": [
        st.Page("paginas/canales.py", title="Canales de contacto", icon=":material/cell_tower:"),
        st.Page("paginas/configuracion.py", title="Configuración", icon=":material/tune:"),
        st.Page("paginas/establecimientos.py", title="Incorporar establecimiento", icon=":material/add_business:"),
    ],
})

info = c.cargar_sistema().info
canales = cargar_canales()
activos = [n for n, v in (("Telegram", canales["telegram"]), ("Twilio", canales["twilio"])) if v]
with st.sidebar:
    st.divider()
    st.markdown(
        f'<div class="nota"><b>Modelo</b>: {info["modelo_elegido"]}<br>'
        f'<b>AUC en prueba</b>: {info["prueba"][info["modelo_elegido"]]["auc"]:.3f}<br>'
        f'<b>Canales</b>: {", ".join(activos) if activos else "sin configurar"}<br>'
        f'<b>Servicio del bot</b>: {"activo" if servicio.activo() else "detenido"}</div>',
        unsafe_allow_html=True)

navegacion.run()



