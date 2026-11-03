"""Admisión de pacientes: registro de datos, consentimiento y vinculación a Telegram mediante QR o enlace."""
import pandas as pd
import streamlit as st

from interfaz import comun as c
from noshow.contacto import almacen, servicio
from noshow.contacto.canales import ErrorCanal, cargar_canales

canales = cargar_canales()
sistema = c.cargar_sistema()

c.encabezado("Admisión de pacientes", "Registro del paciente y vinculación de su Telegram para recibir avisos")

pasos = st.columns(3)
pasos[0].markdown('<div class="paso"><b>1. Registro</b><span>Admisión toma los datos del paciente y su teléfono, '
                  'con su consentimiento.</span></div>', unsafe_allow_html=True)
pasos[1].markdown('<div class="paso"><b>2. QR o enlace</b><span>El sistema genera un código de un solo uso, '
                  'asociado a ese registro.</span></div>', unsafe_allow_html=True)
pasos[2].markdown('<div class="paso"><b>3. Verificación automática</b><span>El paciente lo abre en Telegram y comparte su número; '
                  'el bot lo compara con el registrado.</span></div>', unsafe_allow_html=True)

if not canales["telegram"]:
    st.warning("Telegram no está configurado: se puede registrar al paciente, pero no generar el enlace de vinculación. "
               "Configure el token en Canales de contacto.", icon=":material/warning:")
elif not servicio.activo():
    st.info("El bot se está iniciando. En unos segundos atenderá a los pacientes automáticamente.", icon=":material/info:")


def generar_enlace(id_paciente):
    usuario = canales["telegram"].info()["username"]
    return f"https://t.me/{usuario}?start={almacen.crear_vinculo(id_paciente)}"


c.seccion("Registrar paciente")
zonas = sorted(sistema.codificador.tasas_)
with st.form("form_paciente", clear_on_submit=False):
    a, b, d = st.columns(3)
    id_pac = a.text_input("N.° de historia clínica (anonimizado)")
    edad = b.number_input("Edad", 0, 110, 35)
    zona = d.selectbox("Distrito de residencia", ["(otro)"] + zonas)
    e, f = st.columns([2, 1])
    tel = e.text_input("Teléfono celular", placeholder="+51 930 000 000", help="Se usa para SMS y llamadas, y para verificar la identidad del paciente en Telegram.")
    with f:
        st.markdown("<div style='height:1.7rem'></div>", unsafe_allow_html=True)
        subsidio = st.checkbox("Seguro subsidiado (SIS)")
    g1, g2, _ = st.columns([1, 1, 2])
    hta, dm = g1.checkbox("Hipertensión"), g2.checkbox("Diabetes")
    consiente = st.checkbox("El paciente autoriza recibir avisos de sus citas por Telegram, SMS y llamadas")
    enviar = st.form_submit_button("Registrar y generar QR", type="primary")

if enviar:
    digitos = "".join(ch for ch in tel if ch.isdigit())
    if not id_pac.strip():
        st.error("Ingrese el N.° de historia clínica.")
    elif len(digitos) < 9:
        st.error("Ingrese un teléfono válido (9 dígitos o con prefijo de país).")
    elif not consiente:
        st.error("Se requiere el consentimiento del paciente para continuar.")
    else:
        telefono = "+" + digitos if len(digitos) > 9 else "+51" + digitos
        almacen.registrar_paciente(id_pac.strip(), edad, "" if zona == "(otro)" else zona, subsidio, hta, dm, telefono, True)
        almacen.registrar_destinatario(id_pac.strip(), "telefono", telefono)      # con su consentimiento, el teléfono pasa a ser canal de SMS y llamadas
        st.session_state["enlace_paciente"] = (id_pac.strip(), None)
        if canales["telegram"]:
            try:
                st.session_state["enlace_paciente"] = (id_pac.strip(), generar_enlace(id_pac.strip()))
            except ErrorCanal as ex:
                st.error(str(ex))
        st.success("Paciente registrado.")

ult = st.session_state.get("enlace_paciente")
if ult and ult[1]:
    c.seccion("Vinculación del paciente")
    q1, q2 = st.columns([1, 2], gap="large")
    q1.image(c.qr_png(ult[1]), width=220)
    with q2:
        st.markdown(f"**Paciente {ult[0]}**")
        st.markdown("Muestre el QR en pantalla o entregue el enlace. Es de un solo uso y vence en 7 días. "
                    "Al abrirlo, el bot pedirá al paciente compartir su número para verificar que coincide con el registrado.")
        st.code(ult[1], language=None)

c.seccion("Pacientes registrados")


@st.fragment(run_every="4s")
def tabla_pacientes():
    """Se actualiza sola: el estado cambia en cuanto el paciente completa la verificación en Telegram."""
    pac = almacen.listar_pacientes()
    if pac.empty:
        st.write("Todavía no hay pacientes registrados.")
        return
    vista = pd.DataFrame({
        "N.° de historia": pac["id_paciente"], "Edad": pac["edad"], "Distrito": pac["zona"].replace("", "—"),
        "Teléfono": pac["telefono"].map(lambda t: "•" * max(len(t) - 3, 0) + t[-3:] if t else "—"),
        "Vinculación a Telegram": pac["vinculacion"], "Registrado": pac["creado"].str.replace("T", " ")})
    st.dataframe(vista, hide_index=True, use_container_width=True)
    n = (pac["vinculacion"] == "Verificado").sum()
    c.nota(f"{c.num(n)} de {c.num(len(pac))} pacientes con Telegram verificado. El estado se actualiza automáticamente.")


tabla_pacientes()

if canales["telegram"]:
    pac = almacen.listar_pacientes()
    if not pac.empty:
        c.seccion("Generar un nuevo enlace")
        sel = st.selectbox("Paciente", pac["id_paciente"].tolist(), key="reenlace")
        if st.button("Generar enlace y QR"):
            try:
                st.session_state["enlace_paciente"] = (sel, generar_enlace(sel))
                st.rerun()
            except ErrorCanal as ex:
                st.error(str(ex))

