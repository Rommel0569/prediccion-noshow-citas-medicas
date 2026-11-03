"""Canales de contacto: conexión, vinculación de pacientes y mensaje de prueba."""
import pandas as pd
import streamlit as st

from interfaz import comun as c
from noshow.contacto import almacen
from noshow.contacto.canales import ErrorCanal, cargar_canales
from noshow.contacto.equipo import RUTA as RUTA_EQUIPO, cargar_equipo

canales = cargar_canales()
c.encabezado("Canales de contacto", "Conexión con los servicios de mensajería y registro de pacientes autorizados")

c.seccion("Estado de los canales")
a, b = st.columns(2)
with a.container(border=True):
    st.markdown("**Telegram**")
    if canales["telegram"]:
        st.markdown(c.estado_html("Configurado", True), unsafe_allow_html=True)
        if st.button("Verificar conexión", key="vt"):
            try:
                bot = canales["telegram"].info()
                st.success(f"Conectado como @{bot['username']}.")
            except ErrorCanal as e:
                st.error(str(e))
    else:
        st.markdown(c.estado_html("Sin configurar", False), unsafe_allow_html=True)
    c.nota("Envía recordatorios con botones de respuesta y recibe las confirmaciones. Sin costo.")
with b.container(border=True):
    st.markdown("**Twilio (SMS y llamadas)**")
    st.markdown(c.estado_html("Configurado" if canales["twilio"] else "Sin configurar", bool(canales["twilio"])),
                unsafe_allow_html=True)
    c.nota("Envía SMS y llamadas con mensaje hablado. Con cuenta de prueba solo llega a números verificados en Twilio.")

with st.expander("Cómo configurar los canales", expanded=not any(canales.values())):
    st.markdown("""
**Telegram (gratis, recomendado)**
1. En Telegram, abra el contacto **@BotFather** y envíe `/newbot`. Elija un nombre y un usuario que termine en `bot`.
2. BotFather entrega un **token**. Cópielo.
3. Cree el archivo `config/canales.local.yaml` (no se sube al repositorio) con el contenido de abajo, o defina la variable de entorno `TELEGRAM_BOT_TOKEN`.
4. Reinicie la aplicación.

**Twilio (opcional)**: cree una cuenta, verifique los números de prueba y copie *Account SID*, *Auth Token* y un número de origen.
""")
    st.code("telegram:\n  token: \"123456:ABC...\"\ntwilio:\n  account_sid: \"AC...\"\n  auth_token: \"...\"\n  desde: \"+1...\"", language="yaml")

c.seccion("Vinculación de pacientes")
st.markdown("El registro del paciente y su vinculación a Telegram (QR o enlace, con verificación automática del teléfono) "
            "se hacen en **Admisión de pacientes**.")
st.page_link("paginas/admision.py", label="Ir a Admisión de pacientes", icon=":material/arrow_forward:")

c.seccion("Pacientes autorizados")
dest = almacen.listar_destinatarios()
if dest.empty:
    st.write("Todavía no hay pacientes autorizados.")
else:
    vista = dest.assign(canal=dest["canal"].map({"telegram": "Telegram", "telefono": "Teléfono"}),
                        activo=dest.apply(lambda r: "Dado de baja" if r["activo"] == 0 else ("Verificado" if r["verificado"] == 1 else "Pendiente de verificación"), axis=1),
                        destino=dest.apply(lambda r: r["destino"][:3] + "•" * max(len(r["destino"]) - 5, 0) + r["destino"][-2:], axis=1))
    st.dataframe(vista.rename(columns={"id_paciente": "N.° de historia", "canal": "Canal", "destino": "Destino (oculto)",
                                       "alta": "Fecha de alta", "activo": "Estado"}),
                 hide_index=True, use_container_width=True)

con_tg = dest[(dest["canal"] == "telegram") & (dest["activo"] == 1)] if not dest.empty else dest
if canales["telegram"] and not con_tg.empty:
    c.seccion("Mensaje de prueba")
    elegido = st.selectbox("Paciente", con_tg["id_paciente"].tolist())
    if st.button("Enviar mensaje de prueba"):
        try:
            canales["telegram"].enviar(con_tg[con_tg["id_paciente"] == elegido]["destino"].iloc[0],
                                       "Mensaje de prueba del sistema de gestión de inasistencias.")
            st.success("Mensaje enviado.")
        except ErrorCanal as e:
            st.error(str(e))

