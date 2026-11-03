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

c.seccion("Vincular un paciente a Telegram")
st.markdown("El establecimiento genera un enlace de un solo uso y se lo entrega al paciente al registrar su cita. Al abrirlo y "
            "pulsar *Iniciar*, el paciente queda registrado y acepta recibir los recordatorios. Puede salir con `/baja`.")
with st.container(border=True):
    f1, f2 = st.columns([3, 1])
    id_pac = f1.text_input("N.° de historia del paciente (anonimizado)", key="vinc_id")
    f2.markdown("<div style='height:1.9rem'></div>", unsafe_allow_html=True)
    if f2.button("Generar enlace", use_container_width=True, disabled=not (canales["telegram"] and id_pac.strip())):
        try:
            usuario = canales["telegram"].info()["username"]
            st.session_state["enlace"] = f"https://t.me/{usuario}?start={almacen.crear_vinculo(id_pac.strip())}"
        except ErrorCanal as e:
            st.error(str(e))
    if st.session_state.get("enlace"):
        st.code(st.session_state["enlace"], language=None)
        c.nota("Válido por 7 días y de un solo uso.")
    if not canales["telegram"]:
        c.nota("Configure primero el token de Telegram.")

c.seccion("Teléfonos autorizados (SMS y llamadas)")
with st.container(border=True):
    t1, t2 = st.columns(2)
    id_tel = t1.text_input("N.° de historia del paciente (anonimizado)", key="tel_id")
    tel = t2.text_input("Teléfono en formato internacional", placeholder="+51999999999", key="tel_num")
    ok = st.checkbox("El paciente autorizó recibir avisos de sus citas por este teléfono", key="tel_ok")
    valido = tel.startswith("+") and tel[1:].isdigit() and len(tel) >= 10
    if st.button("Registrar teléfono", disabled=not (id_tel.strip() and valido and ok)):
        almacen.registrar_destinatario(id_tel.strip(), "telefono", tel)
        st.success("Teléfono registrado.")
    if RUTA_EQUIPO.exists():
        if st.button("Cargar los números del equipo (config/equipo.local.csv)"):
            st.success(f"{cargar_equipo()} números cargados.")
    else:
        c.nota("También puede cargar varios números a la vez con config/equipo.local.csv (archivo local, fuera del repositorio).")

c.seccion("Pacientes autorizados")
dest = almacen.listar_destinatarios()
if dest.empty:
    st.write("Todavía no hay pacientes autorizados.")
else:
    vista = dest.assign(canal=dest["canal"].map({"telegram": "Telegram", "telefono": "Teléfono"}),
                        activo=dest["activo"].map({1: "Activo", 0: "Dado de baja"}),
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
