"""Confirmaciones y cupos: liberación de cupos no confirmados y reasignación a la lista de espera."""
from datetime import date, datetime, time

import pandas as pd
import streamlit as st

from interfaz import comun as c
from noshow import parametros
from noshow.contacto import almacen, reasignacion
from noshow.contacto.canales import cargar_canales
from noshow.cupos import generar_lista_espera, liberar_y_reasignar, simular_confirmacion
from noshow.impacto import resumen_agenda

agenda, cfg = c.obtener_agenda()
horas = cfg.get("reasignacion", {}).get("horas_limite_confirmacion", 24)
canales = cargar_canales()

c.encabezado("Confirmaciones y cupos", "Liberación de cupos no confirmados y reasignación a la lista de espera",
             f"Fuente: {c.origen_agenda()}")

p1, p2, p3 = st.columns(3)
p1.markdown('<div class="paso"><b>1. Contacto</b><span>Cada cita priorizada recibe la acción asignada en la agenda.</span></div>',
            unsafe_allow_html=True)
p2.markdown(f'<div class="paso"><b>2. Confirmación</b><span>El paciente confirma, cancela o reprograma. '
            f'El plazo límite es de {horas} horas antes de la cita.</span></div>', unsafe_allow_html=True)
p3.markdown('<div class="paso"><b>3. Reasignación</b><span>El cupo liberado pasa al paciente que más tiempo '
            'espera en la misma especialidad.</span></div>', unsafe_allow_html=True)

hay_registro = not almacen.listar_contactos().empty
modo = st.radio("Origen de las respuestas", ["Registro de contactos", "Simulación"], horizontal=True,
                index=0 if hay_registro else 1,
                help="El registro usa las respuestas reales de los pacientes. La simulación sirve para probar sin contactos.")

# ====================================================================== registro real
if modo == "Registro de contactos":
    if not hay_registro:
        st.info("Todavía no hay contactos registrados. Ejecútelos desde Agenda y contactos.", icon=":material/info:")
    c.seccion("Lista de espera")
    esp = almacen.listar_espera()
    f1, f2, f3 = st.columns([2, 2, 1])
    id_esp = f1.text_input("N.° de historia del paciente (anonimizado)", key="esp_id")
    serv_ops = sorted(agenda["servicio"].dropna().unique()) if "servicio" in agenda else []
    serv = f2.text_input("Especialidad (opcional)", key="esp_serv", placeholder=", ".join(serv_ops[:2]) or "Cardiología")
    f3.markdown("<div style='height:1.9rem'></div>", unsafe_allow_html=True)
    if f3.button("Agregar", use_container_width=True, disabled=not id_esp.strip()):
        almacen.agregar_espera(id_esp.strip(), serv.strip())
        st.rerun()
    if esp.empty:
        st.write("La lista de espera está vacía.")
    else:
        st.dataframe(esp.rename(columns={"id_espera": "Código", "id_paciente": "N.° de historia", "servicio": "Especialidad",
                                         "ingreso": "Ingreso", "estado": "Estado"}), hide_index=True,
                     use_container_width=True, height=200)

    c.seccion("Liberar y reasignar")
    with st.container(border=True):
        r1, r2, r3 = st.columns([1, 1, 2])
        dia = r1.date_input("Fecha de evaluación", date.today(), min_value=date(2015, 1, 1), max_value=date(2035, 12, 31), key="ev_dia")
        hora = r2.time_input("Hora", datetime.now().time().replace(second=0, microsecond=0), key="ev_hora")
        referencia = datetime.combine(dia, hora)
        lib = reasignacion.cupos_liberables(agenda, horas, referencia)
        r3.markdown(f'<div style="padding-top:1.7rem"><b>{c.num(len(lib))}</b> cupos liberables a esa fecha y hora</div>',
                    unsafe_allow_html=True)
        if st.button("Liberar y reasignar cupos", type="primary", disabled=lib.empty):
            _, res = reasignacion.reasignar(agenda, canales, horas, referencia, parametros.establecimiento())
            st.session_state["ultimo_resultado"] = res
            st.rerun()
    if "ultimo_resultado" in st.session_state and not st.session_state["ultimo_resultado"].empty:
        st.dataframe(st.session_state["ultimo_resultado"].rename(columns={
            "id_cita": "N.° de cita", "fecha_cita": "Fecha de cita", "servicio": "Especialidad", "motivo": "Motivo",
            "id_espera": "Paciente en espera", "resultado": "Resultado"}), hide_index=True, use_container_width=True)

    c.seccion("Resultado acumulado")
    rea = almacen.listar_reasignaciones()
    liberados = len(rea)
    aceptados = int((rea["estado"] == "aceptada").sum()) if liberados else 0
    ofrecidos = int(rea["estado"].isin(["ofrecida", "asignada_manual", "aceptada"]).sum()) if liberados else 0
    k = st.columns(4)
    k[0].metric("Cupos liberados", c.num(liberados), border=True)
    k[1].metric("Cupos reasignados", c.num(ofrecidos), border=True, help="Con un paciente de la lista de espera asignado.")
    k[2].metric("Ofertas aceptadas", c.num(aceptados), border=True, help="El paciente confirmó que toma el cupo.")
    k[3].metric("Tasa de reutilización", c.pct(aceptados / liberados, 0) if liberados else "—", border=True,
                help="Ofertas aceptadas sobre cupos liberados.")
    if liberados:
        st.dataframe(rea.rename(columns={"id": "Código", "id_cita": "N.° de cita", "fecha_cita": "Fecha de cita",
                                         "servicio": "Especialidad", "motivo": "Motivo", "id_espera": "Paciente en espera",
                                         "creado": "Fecha", "estado": "Estado"}), hide_index=True,
                     use_container_width=True, height=300)

# ====================================================================== simulación
else:
    with st.container(border=True):
        n_espera = st.slider("Pacientes en lista de espera simulada", 0, 500, 150)
    st.info("Simulación: el paciente confirma con probabilidad igual a 1 menos el riesgo y la lista de espera es ficticia.",
            icon=":material/info:")
    conf = simular_confirmacion(agenda)
    servicios = agenda["servicio"].dropna().unique() if "servicio" in agenda else None
    tabla, res = liberar_y_reasignar(conf, generar_lista_espera(n_espera, servicios))
    c.seccion("Resultado")
    k = st.columns(4)
    k[0].metric("Cupos liberados", c.num(res["cupos_liberados"]), border=True)
    k[1].metric("Cupos reasignados", c.num(res["cupos_reasignados"]), border=True)
    k[2].metric("Tasa de reutilización", c.pct(res["tasa_reutilizacion"], 0), border=True)
    k[3].metric("Asistencias recuperadas (estimadas)", c.num(res["asistencias_recuperadas_esperadas"]), border=True)
    if not tabla.empty:
        det = pd.DataFrame({
            "N.° de cita": tabla["id_cita"].astype(str).str.replace(r"\.0$", "", regex=True),
            "Fecha de cita": pd.to_datetime(tabla["fecha_cita"]).dt.date,
            "Paciente en lista de espera": tabla["id_espera"].fillna("Sin candidato"),
            "Días en espera": tabla["dias_en_espera"] if "dias_en_espera" in tabla else None})
        st.dataframe(det, hide_index=True, use_container_width=True, height=340)
    total = resumen_agenda(agenda, res, cfg)
    c.seccion("Impacto de la agenda")
    st.dataframe(pd.DataFrame([
        ("Inasistencias esperadas sin intervención", c.num(total["inasistencias_esperadas_sin_intervencion"], 1)),
        ("Inasistencias evitadas por el contacto", c.num(total["inasistencias_evitadas"], 1)),
        ("Asistencias recuperadas por reasignación", c.num(total["asistencias_recuperadas_por_reasignacion"], 1)),
        ("Costo de contacto (S/)", c.num(total["costo_total_contacto"], 2)),
        ("Valor de consultas recuperadas (S/)", c.num(total["valor_consultas_recuperadas"], 2)),
    ], columns=["Indicador", "Valor"]), hide_index=True, use_container_width=True)



