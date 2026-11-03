"""Registro de contactos: seguimiento de envíos, respuestas y llamadas pendientes."""
import pandas as pd
import streamlit as st

from interfaz import comun as c
from noshow.contacto import almacen, respuestas
from noshow.contacto.canales import ErrorCanal, cargar_canales
from noshow.contacto.despacho import ETIQUETA_TIPO

canales = cargar_canales()
RESPUESTAS = {"": "Pendiente", "confirmo": "Confirmó", "cancelo": "Canceló", "reprogramo": "Reprogramó",
              "sin_respuesta": "Sin respuesta"}
INVERSO = {v: k for k, v in RESPUESTAS.items()}
CANAL = {"telegram": "Telegram", "sms": "SMS", "llamada": "Llamada", "visita": "Visita"}

c.encabezado("Registro de contactos", "Seguimiento de envíos, respuestas y gestiones pendientes del personal")


@st.fragment(run_every="10s")
def seguimiento():
    """Se actualiza solo: consulta las respuestas de Telegram y refresca los indicadores."""
    if canales["telegram"]:
        try:
            nuevas = respuestas.procesar(canales["telegram"])
            if nuevas:
                st.toast(f"Respuestas nuevas procesadas: {sum(nuevas.values())}")
        except ErrorCanal as e:
            st.warning(f"No se pudieron consultar las respuestas de Telegram: {e}")
    df = almacen.listar_contactos()
    env = df[df["estado"].isin(["enviado", "realizado"])] if not df.empty else df
    resp = env["respuesta"].fillna("") if not env.empty else pd.Series(dtype=str)
    k = st.columns(6)
    k[0].metric("Contactos realizados", c.num(len(env)), border=True)
    k[1].metric("Con respuesta", c.num((resp != "").sum()), border=True)
    k[2].metric("Confirmaron", c.num((resp == "confirmo").sum()), border=True)
    k[3].metric("Cancelaron", c.num((resp == "cancelo").sum()), border=True)
    k[4].metric("Reprogramaron", c.num((resp == "reprogramo").sum()), border=True)
    k[5].metric("Pendientes del personal", c.num((df["estado"] == "pendiente_manual").sum()) if not df.empty else 0, border=True)


seguimiento()
c.nota("Las respuestas de Telegram se consultan automáticamente cada 10 segundos mientras esta página está abierta.")

c.seccion("Llamadas y visitas pendientes")
pend = almacen.pendientes_manuales()
if pend.empty:
    st.write("No hay gestiones pendientes. Genere los contactos desde Agenda y contactos.")
else:
    dest = almacen.destinatarios_activos()
    tabla = pd.DataFrame({
        "id": pend["id"],
        "Tipo": pend["tipo"].map(ETIQUETA_TIPO),
        "N.° de cita": pend["id_cita"],
        "Fecha de cita": pend["fecha_cita"],
        "N.° de historia": pend["id_paciente"],
        "Teléfono": [dest.get((i, "telefono"), "No registrado") for i in pend["id_paciente"]],
        "Resultado": "Pendiente",
    })
    editada = st.data_editor(tabla, hide_index=True, use_container_width=True, key="pendientes",
                             disabled=["id", "Tipo", "N.° de cita", "Fecha de cita", "N.° de historia", "Teléfono"],
                             column_config={"id": None, "Resultado": st.column_config.SelectboxColumn(
                                 "Resultado", options=[v for k, v in RESPUESTAS.items() if k], default="Pendiente")})
    if st.button("Guardar resultados", type="primary"):
        guardados = 0
        for _, f in editada.iterrows():
            if f["Resultado"] in INVERSO and INVERSO[f["Resultado"]]:
                almacen.registrar_resultado_manual(f["id"], INVERSO[f["Resultado"]])
                guardados += 1
        st.success(f"{guardados} resultados guardados.")
        st.rerun()

c.seccion("Historial de contactos")
hist = almacen.listar_contactos()
if hist.empty:
    st.write("Todavía no se registraron contactos.")
else:
    vista = pd.DataFrame({
        "Fecha": hist["enviado_en"].fillna(hist["creado"]),
        "N.° de cita": hist["id_cita"],
        "Fecha de cita": hist["fecha_cita"],
        "Canal": hist["canal"].map(CANAL).fillna(hist["canal"]),
        "Tipo": hist["tipo"].map(ETIQUETA_TIPO),
        "Estado": hist["estado"].map({"enviado": "Enviado", "realizado": "Realizado", "pendiente_manual": "Pendiente",
                                      "error": "Error"}),
        "Respuesta": hist["respuesta"].map(RESPUESTAS).fillna("Sin respuesta aún"),
        "Detalle": hist["error"].fillna(""),
    })
    st.dataframe(vista, hide_index=True, use_container_width=True, height=380)
    st.download_button("Exportar a CSV", vista.to_csv(index=False).encode("utf-8-sig"), "registro_contactos.csv",
                       "text/csv", icon=":material/download:")
