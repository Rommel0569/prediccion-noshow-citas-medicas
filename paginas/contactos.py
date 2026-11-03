"""Agenda y contactos: cola de trabajo priorizada para el personal de citas."""
import streamlit as st

from interfaz import comun as c

c.encabezado("Agenda y contactos", "Cola de contactos priorizada por riesgo y beneficio esperado")

with st.expander("Origen de los datos", expanded=False):
    st.write("Cargue la agenda de próximas citas en formato estándar (CSV). La plantilla está en "
             "Administración, Incorporar establecimiento. Si no carga ninguna, se usa la agenda de demostración.")
    archivo = st.file_uploader("Agenda de próximas citas (CSV)", type="csv", key="subida_agenda")
    if archivo is not None and st.session_state.get("agenda_nombre") != archivo.name:
        st.session_state["agenda_bytes"] = archivo.getvalue()
        st.session_state["agenda_nombre"] = archivo.name
        st.rerun()
    if st.session_state.get("agenda_bytes") and st.button("Volver a la agenda de demostración"):
        st.session_state.pop("agenda_bytes"); st.session_state.pop("agenda_nombre", None)
        st.rerun()

agenda, cfg = c.obtener_agenda()
if st.session_state.pop("agenda_error", None):
    st.error("El archivo no tiene el formato esperado; se muestra la agenda de demostración. "
             "Revise las columnas obligatorias en Incorporar establecimiento.")
if agenda["canal_simulado"].any():
    c.nota("El archivo no incluye el canal de contacto disponible: en este entorno se asigna con las proporciones de "
           "conectividad del INEI (II trimestre 2025).")

canal = agenda["canal_accion"]
k = st.columns(5)
k[0].metric("Citas en agenda", c.num(len(agenda)), border=True)
k[1].metric("Llamadas", c.num((canal == "llamada").sum()), border=True,
            help=f"Capacidad vigente: {c.pct(cfg['niveles']['alto_percentil'], 0)} de la agenda.")
k[2].metric("Mensajes", c.num(canal.isin(["whatsapp", "sms"]).sum()), border=True)
k[3].metric("Visitas domiciliarias", c.num((canal == "visita").sum()), border=True)
k[4].metric("Sin acción", c.num((canal == "ninguno").sum()), border=True)

c.seccion("Cola de trabajo")
f1, f2, f3 = st.columns([2, 2, 1.4])
niveles = f1.multiselect("Nivel de riesgo", list(c.NIVELES.values()), default=list(c.NIVELES.values()))
acciones = f2.multiselect("Acción asignada", list(c.CANAL.values()), default=list(c.CANAL.values()))
buscar = f3.text_input("Buscar N.° de cita")

vista = c.vista_agenda(agenda)
vista = vista[vista["Nivel"].isin(niveles) & vista["Acción asignada"].isin(acciones)]
if buscar:
    vista = vista[vista["N.° de cita"].str.contains(buscar.strip())]
st.dataframe(c.estilo_nivel(vista), hide_index=True, use_container_width=True, height=470, column_config=c.CONFIG_TABLA)
a, b = st.columns([4, 1])
a.markdown(f'<div class="nota">{c.num(len(vista))} de {c.num(len(agenda))} citas. Las citas con llamada se ordenan primero.</div>',
           unsafe_allow_html=True)
b.download_button("Exportar a CSV", vista.to_csv(index=False).encode("utf-8-sig"), "agenda_priorizada.csv", "text/csv",
                  icon=":material/download:", use_container_width=True)
