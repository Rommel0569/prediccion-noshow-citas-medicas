"""Agenda y contactos: cola de trabajo priorizada para el personal de citas."""
from datetime import date

import streamlit as st

from interfaz import comun as c
from noshow import parametros
from noshow.contacto import despacho
from noshow.contacto.canales import cargar_canales

c.encabezado("Agenda y contactos", "Cola de contactos priorizada por riesgo y beneficio esperado")

with st.expander("Origen de los datos", expanded=False):
    fuente = st.radio("Fuente de la agenda", ["Citas registradas en el sistema", "Archivo CSV o demostración"],
                      index=0 if st.session_state.get("fuente_agenda") == "registradas" else 1, horizontal=True)
    st.session_state["fuente_agenda"] = "registradas" if fuente.startswith("Citas") else "archivo"
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

# ------------------------------------------------------------------ envío real
c.seccion("Envío de contactos")
canales = cargar_canales()
if not any(canales.values()):
    st.info("No hay canales configurados. Las llamadas y visitas se pueden gestionar con el personal; para enviar mensajes "
            "configure Telegram o Twilio en Canales de contacto.", icon=":material/info:")
with st.container(border=True):
    e1, e2, e3 = st.columns([1.3, 1, 1])
    referencia = e1.date_input("Fecha de referencia", date.today(), min_value=date(2015, 1, 1), max_value=date(2035, 12, 31),
                               help="Día desde el cual se calcula la ventana de contacto (72 h para confirmar, 48 h para recordar).")
    limite = e2.number_input("Máximo de contactos a ejecutar", 1, 5000, 25, help="Tope de seguridad por ejecución.")
    ignorar = e3.toggle("Ignorar la ventana de tiempo", value=False, help="Para pruebas: contacta aunque la cita no esté próxima.")
    auto = False
    if canales["twilio"]:
        auto = st.toggle("Usar llamada automática cuando el paciente tiene teléfono registrado", value=False)
    prog = despacho.plan(agenda, canales, referencia, ignorar, auto)
    if prog.empty:
        st.write("No hay contactos previstos en esta agenda.")
    else:
        resumen = prog.groupby(["tipo", "estado"]).size().unstack(fill_value=0)
        resumen.index = [despacho.ETIQUETA_TIPO[i] for i in resumen.index]
        st.dataframe(resumen, use_container_width=True)
        listos = int((prog["estado"] == "Listo").sum())
        st.markdown(f"**{c.num(listos)}** contactos listos; se ejecutarán como máximo **{c.num(min(listos, limite))}**.")
        por_destino = prog[prog["estado"] == "Listo"]["destino"].value_counts()
        if not por_destino.empty:
            c.nota("Destino de los contactos listos: " + ", ".join(f"{k}: {v}" for k, v in por_destino.items()) + ".")
        autoriza = st.checkbox("Confirmo el envío a pacientes con consentimiento registrado", key="autoriza_envio")
        if st.button("Ejecutar contactos", type="primary", disabled=not (autoriza and listos)):
            resultado, errores = despacho.ejecutar(prog, canales, parametros.establecimiento(), limite)
            st.success("Contactos ejecutados: " + ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in resultado.items()) + ".")
            for er in errores[:5]:
                st.error(er)
            c.nota("El seguimiento está en Registro de contactos.")
        with st.expander("Detalle del plan"):
            st.dataframe(prog.assign(tipo=prog["tipo"].map(despacho.ETIQUETA_TIPO), fecha_cita=prog["fecha_cita"].dt.date)
                         .drop(columns=["servicio", "dias"]).rename(columns={
                             "id_cita": "N.° de cita", "id_paciente": "N.° de historia", "tipo": "Tipo", "destino": "Destino",
                             "estado": "Estado", "fecha_cita": "Fecha de cita", "nivel": "Nivel"}),
                         hide_index=True, use_container_width=True, height=300)




