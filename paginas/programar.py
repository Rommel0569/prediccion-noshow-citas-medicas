"""Programación de citas: evaluación del riesgo y acción recomendada al momento de agendar."""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from interfaz import comun as c
from noshow import parametros
from noshow.contacto import almacen
from noshow.recomendacion import recomendar

sistema, historial, cfg = c.cargar_sistema(), c.cargar_historial(), c.cfg_activa()
info = sistema.info
ej_alto, ej_bajo = c.ejemplos_pacientes()
hoy = date.today()


def cargar_ejemplo():
    opcion = st.session_state["caso_ejemplo"]
    if opcion == "Paciente con inasistencias reiteradas":
        st.session_state.update(id_buscar=ej_alto, f_reg=hoy, f_cita=hoy + timedelta(days=15))
    elif opcion == "Paciente sin inasistencias":
        st.session_state.update(id_buscar=ej_bajo, f_reg=hoy, f_cita=hoy + timedelta(days=1))
    else:
        st.session_state.update(id_buscar="")


st.session_state.setdefault("f_reg", hoy)
st.session_state.setdefault("f_cita", hoy + timedelta(days=15))
c.encabezado("Programación de citas", "Evaluación del riesgo de inasistencia al momento de agendar")

izq, der = st.columns([6, 5], gap="large")

with izq:
    with st.container(border=True):
        st.markdown("**Paciente**")
        st.radio("Caso de ejemplo", ["Ninguno", "Paciente con inasistencias reiteradas", "Paciente sin inasistencias"],
                 key="caso_ejemplo", horizontal=True, on_change=cargar_ejemplo,
                 help="Carga un paciente del historial para probar el sistema.")
        id_buscar = st.text_input("N.° de historia clínica (anonimizado)", key="id_buscar", placeholder=f"Ej.: {ej_alto}")
        f1, f2 = st.columns(2)
        f_reg = f1.date_input("Fecha de registro de la cita", key="f_reg")
        f_cita = f2.date_input("Fecha de la cita", key="f_cita")
        pac = c.datos_del_paciente(historial, id_buscar, f_cita) if id_buscar else None
        if id_buscar and pac is None:
            st.warning("El número no figura en el historial. Complete los datos manualmente (paciente nuevo).")
        elif pac:
            st.success(f"Historial encontrado: {pac['citas_previas']} citas previas, {pac['faltas_previas']} "
                       f"inasistencias. Última cita: {pac['ultima_cita'] or 'sin registro'}.")
    d = pac or {"edad": 35, "zona": "", "subsidio": False, "hipertension": False, "diabetes": False, "faltas_previas": 0}
    k = f"_{id_buscar}" if pac else ""      # clave distinta por paciente: los campos se rellenan solos
    with st.container(border=True):
        st.markdown("**Datos del paciente**")
        a1, a2 = st.columns(2)
        edad = a1.number_input("Edad", 0, 110, d["edad"], key="edad" + k)
        faltas = a2.number_input("Inasistencias previas", 0, 50, d["faltas_previas"], key="faltas" + k)
        zonas = sorted(sistema.codificador.tasas_)
        opciones = ["(otra / desconocida)"] + zonas
        zona = st.selectbox("Zona de residencia (distrito)", opciones,
                            index=opciones.index(d["zona"]) if d["zona"] in zonas else 0, key="zona" + k)
        canal = st.selectbox("Canal de contacto disponible", list(c.CANAL_DISPONIBLE), format_func=c.CANAL_DISPONIBLE.get)
        b1, b2, b3 = st.columns(3)
        subsidio = b1.checkbox("Seguro subsidiado", d["subsidio"], key="sub" + k, help="SIS, FONASA A-B u otro régimen subsidiado.")
        hta = b2.checkbox("Hipertensión", d["hipertension"], key="hta" + k)
        dm = b3.checkbox("Diabetes", d["diabetes"], key="dm" + k)
        servicio, turno_tarde = "", 0          # solo si el modelo en uso se entrenó con datos que los traen
        if "tasa_servicio" in sistema.variables or "turno_tarde" in sistema.variables:
            e1, e2 = st.columns(2)
            if "tasa_servicio" in sistema.variables:
                servicio = e1.selectbox("Especialidad", sorted(sistema.cod_servicio.tasas_))
            if "turno_tarde" in sistema.variables:
                turno_tarde = int(e2.radio("Turno", ["Mañana", "Tarde"], horizontal=True) == "Tarde")

with der:
    if f_cita < f_reg:
        st.warning("La fecha de la cita no puede ser anterior a la fecha de registro.")
    else:
        caso = pd.DataFrame([{
            "id_cita": "CASO", "id_paciente": "CASO", "fecha_registro": pd.Timestamp(f_reg),
            "fecha_cita": pd.Timestamp(f_cita), "dias_anticipacion": (f_cita - f_reg).days,
            "dia_semana": pd.Timestamp(f_cita).dayofweek, "edad": edad, "zona": zona.upper(),
            "subsidio": int(subsidio), "hipertension": int(hta), "diabetes": int(dm), "faltas_previas": faltas,
            "canal_disponible": canal, "servicio": servicio, "turno_tarde": turno_tarde,
        }])
        p = sistema.probabilidad(caso)
        rec = recomendar(caso, p, sistema.nivel(p), cfg, info).iloc[0]
        nivel, color = rec["nivel"], c.COLOR_NIVEL[rec["nivel"]]
        st.markdown(
            f'<div class="panel"><div class="rotulo">Riesgo de inasistencia</div>'
            f'<span class="valor" style="color:{color}">{c.pct(p[0])}</span>&nbsp;&nbsp;{c.badge_nivel(nivel)}'
            f'<div class="barra"><div style="width:{min(p[0], 1) * 100:.0f}%;background:{color}"></div></div>'
            f'<div class="fila" style="margin-top:12px"><span>Con la intervención recomendada</span>'
            f'<span><b>{c.pct(rec["probabilidad_con_intervencion"])}</b></span></div>'
            f'<div class="fila"><span>Anticipación de la cita</span><span>{(f_cita - f_reg).days} días</span></div></div>',
            unsafe_allow_html=True)
        st.markdown(
            f'<div class="panel" style="margin-top:14px"><div class="rotulo">Acción recomendada</div>'
            f'<div class="accion">{rec["accion"]}</div>'
            f'<div class="fila"><span>Canal</span><span>{c.CANAL[rec["canal_accion"]]}</span></div>'
            f'<div class="fila"><span>Momento</span><span>{rec["momento"]}</span></div>'
            f'<div class="fila"><span>Costo estimado</span><span>S/ {c.num(rec["costo"], 2)}</span></div></div>',
            unsafe_allow_html=True)
        try:
            factores = c.cargar_explicador().explicar(caso)[0]
            st.markdown('<div class="panel" style="margin-top:14px"><div class="rotulo">Factores determinantes</div>'
                        + c.html_factores(factores) + "</div>", unsafe_allow_html=True)
        except Exception as e:   # la explicación no debe impedir usar la predicción
            st.info(f"Explicación no disponible: {e}")

        # ---------------------------------------------------------------- agendar de verdad
        st.markdown('<div class="panel" style="margin-top:14px"><div class="rotulo">Agendar esta cita</div></div>', unsafe_allow_html=True)
        registrado = almacen.obtener_paciente(id_buscar.strip()) if id_buscar.strip() else None
        if not registrado:
            c.nota("Para agendar, el paciente debe estar registrado en Admisión de pacientes.")
        else:
            a1, a2 = st.columns(2)
            servicio_cita = a1.selectbox("Especialidad", parametros.servicios(), key="agendar_servicio")
            turno_cita = a2.radio("Turno", ["Mañana", "Tarde"], horizontal=True, key="agendar_turno")
            if st.button("Agendar cita", type="primary"):
                nueva = almacen.agendar_cita(id_buscar.strip(), f_cita, servicio_cita, turno_cita, f_reg)
                st.success(f"Cita {nueva} agendada. Desde ahora el sistema la gestiona solo: contacta al paciente por su canal "
                           "verificado, escala si no responde y libera el cupo si hace falta.")

