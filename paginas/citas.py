"""Citas registradas: seguimiento de las citas agendadas y registro de la asistencia real."""
from datetime import date

import pandas as pd
import streamlit as st

from interfaz import comun as c
from noshow.contacto import almacen

ESTADOS = {"agendada": "Agendada", "confirmada": "Confirmada", "cancelada": "Cancelada",
           "reprogramacion_solicitada": "Reprogramación solicitada", "atendida": "Atendida", "no_asistio": "No asistió"}
c.encabezado("Citas registradas", "Citas agendadas en el sistema y registro de la asistencia real")

citas = almacen.listar_citas()
if citas.empty:
    st.info("Todavía no hay citas registradas. Agéndelas desde Programación de citas.", icon=":material/info:")
    st.stop()

k = st.columns(5)
conteo = citas["estado"].value_counts()
k[0].metric("Citas registradas", c.num(len(citas)), border=True)
k[1].metric("Agendadas", c.num(conteo.get("agendada", 0)), border=True)
k[2].metric("Confirmadas", c.num(conteo.get("confirmada", 0)), border=True)
k[3].metric("Canceladas o a reprogramar", c.num(conteo.get("cancelada", 0) + conteo.get("reprogramacion_solicitada", 0)), border=True)
k[4].metric("Inasistencias registradas", c.num(conteo.get("no_asistio", 0)), border=True,
            help="Alimentan el historial de inasistencias previas de cada paciente.")

c.seccion("Registrar asistencia")
st.markdown("Marque el resultado de las citas que ya ocurrieron. Cada inasistencia se suma al historial del paciente y "
            "el sistema la usa para evaluar sus próximas citas.")
vencidas = citas[citas["estado"].isin(["agendada", "confirmada"]) & (citas["fecha_cita"] <= str(date.today()))]
if vencidas.empty:
    st.write("No hay citas pendientes de registrar.")
else:
    tabla = pd.DataFrame({"id": vencidas["id_cita"], "N.° de historia": vencidas["id_paciente"],
                          "Fecha de cita": vencidas["fecha_cita"], "Especialidad": vencidas["servicio"],
                          "Resultado": "Pendiente"})
    editada = st.data_editor(tabla, hide_index=True, use_container_width=True, key="asistencia",
                             disabled=["id", "N.° de historia", "Fecha de cita", "Especialidad"],
                             column_config={"id": None, "Resultado": st.column_config.SelectboxColumn(
                                 "Resultado", options=["Pendiente", "Asistió", "No asistió"], default="Pendiente")})
    if st.button("Guardar asistencia", type="primary"):
        n = 0
        for _, f in editada.iterrows():
            if f["Resultado"] in ("Asistió", "No asistió"):
                almacen.registrar_asistencia(f["id"], f["Resultado"] == "Asistió")
                n += 1
        st.success(f"{n} resultados guardados.")
        st.rerun()

c.seccion("Todas las citas")
vista = pd.DataFrame({"N.° de cita": citas["id_cita"], "N.° de historia": citas["id_paciente"],
                      "Fecha de cita": citas["fecha_cita"], "Especialidad": citas["servicio"].replace("", "—"),
                      "Turno": citas["turno"].replace("", "—"), "Estado": citas["estado"].map(ESTADOS)})
st.dataframe(vista, hide_index=True, use_container_width=True, height=380)
