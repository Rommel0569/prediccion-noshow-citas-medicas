"""Confirmaciones y cupos: liberación y reasignación a la lista de espera."""
import pandas as pd
import streamlit as st

from interfaz import comun as c
from noshow.cupos import generar_lista_espera, liberar_y_reasignar, simular_confirmacion
from noshow.impacto import resumen_agenda

agenda, cfg = c.obtener_agenda()
horas = cfg.get("reasignacion", {}).get("horas_limite_confirmacion", 24)

c.encabezado("Confirmaciones y cupos", "Liberación de cupos no confirmados y reasignación a la lista de espera",
             f"Fuente: {c.origen_agenda()}")

p1, p2, p3 = st.columns(3)
p1.markdown(f'<div class="paso"><b>1. Contacto</b><span>Cada cita priorizada recibe la acción asignada en la agenda.</span></div>',
            unsafe_allow_html=True)
p2.markdown(f'<div class="paso"><b>2. Confirmación</b><span>El paciente confirma, cancela o reprograma. '
            f'El plazo límite es de {horas} horas antes de la cita.</span></div>', unsafe_allow_html=True)
p3.markdown('<div class="paso"><b>3. Reasignación</b><span>El cupo no confirmado pasa al paciente que más tiempo '
            'espera en la misma especialidad.</span></div>', unsafe_allow_html=True)

with st.container(border=True):
    n_espera = st.slider("Pacientes en lista de espera", 0, 500, 150,
                         help="Tamaño de la lista de espera disponible para reasignar.")
st.info("En este entorno las respuestas de los pacientes se simulan (confirma con probabilidad igual a 1 menos el riesgo). "
        "En operación se registran en cada contacto.", icon=":material/info:")

conf = simular_confirmacion(agenda)
servicios = agenda["servicio"].dropna().unique() if "servicio" in agenda else None
tabla, res = liberar_y_reasignar(conf, generar_lista_espera(n_espera, servicios))

c.seccion("Resultado")
k = st.columns(4)
k[0].metric("Cupos liberados", c.num(res["cupos_liberados"]), border=True, help="Citas priorizadas que no confirmaron.")
k[1].metric("Cupos reasignados", c.num(res["cupos_reasignados"]), border=True)
k[2].metric("Tasa de reutilización", c.pct(res["tasa_reutilizacion"], 0), border=True)
k[3].metric("Asistencias recuperadas (estimadas)", c.num(res["asistencias_recuperadas_esperadas"]), border=True)
if res["cupos_liberados"] > res["cupos_reasignados"]:
    c.nota(f"{c.num(res['cupos_liberados'] - res['cupos_reasignados'])} cupos liberados quedan sin reasignar porque la lista "
           "de espera es menor que la demanda. La reutilización real depende del tamaño de la lista del establecimiento.")

c.seccion("Detalle de reasignaciones")
if tabla.empty:
    st.write("No hay cupos liberados con los parámetros actuales.")
else:
    det = pd.DataFrame({
        "N.° de cita": tabla["id_cita"].astype(str).str.replace(r"\.0$", "", regex=True),
        "Fecha de cita": pd.to_datetime(tabla["fecha_cita"]).dt.date,
        "Paciente en lista de espera": tabla["id_espera"].fillna("Sin candidato"),
        "Días en espera": tabla["dias_en_espera"] if "dias_en_espera" in tabla else None,
    })
    st.dataframe(det, hide_index=True, use_container_width=True, height=380)
    st.download_button("Exportar a CSV", det.to_csv(index=False).encode("utf-8-sig"), "reasignaciones.csv", "text/csv",
                       icon=":material/download:")

c.seccion("Impacto de la agenda")
total = resumen_agenda(agenda, res, cfg)
st.dataframe(pd.DataFrame([
    ("Inasistencias esperadas sin intervención", c.num(total["inasistencias_esperadas_sin_intervencion"], 1)),
    ("Inasistencias evitadas por el contacto", c.num(total["inasistencias_evitadas"], 1)),
    ("Asistencias recuperadas por reasignación", c.num(total["asistencias_recuperadas_por_reasignacion"], 1)),
    ("Costo de contacto (S/)", c.num(total["costo_total_contacto"], 2)),
    ("Valor de consultas recuperadas (S/)", c.num(total["valor_consultas_recuperadas"], 2)),
], columns=["Indicador", "Valor"]), hide_index=True, use_container_width=True)
