"""Incorporar un establecimiento: preparación de datos, configuración y recalibración del modelo."""
import io

import joblib
import pandas as pd
import streamlit as st

from interfaz import comun as c
from noshow.config import RAIZ, cargar_config
from noshow.datos import estandarizar, verificar_columnas
from noshow.modelo import recalibrar

c.encabezado("Incorporar un establecimiento", "Aplicación del sistema en un hospital distinto al de entrenamiento")

c.seccion("Opciones según los datos disponibles")
st.dataframe(pd.DataFrame([
    ("Sin datos locales", "Usar el modelo base", "Ordena bien el riesgo; los porcentajes son aproximados."),
    ("Al menos 200 citas con resultado de asistencia", "Recalibrar", "Ajusta las probabilidades y los umbrales al establecimiento."),
    ("Un año o más de historial", "Reentrenar", "Aprende de los datos locales e incorpora especialidad y turno."),
], columns=["Situación", "Acción", "Efecto"]), hide_index=True, use_container_width=True)

c.seccion("Paso 1. Preparar los datos")
st.markdown("Exportar el historial de citas a CSV, una fila por cita, con el identificador del paciente anonimizado "
            "(nunca nombres, DNI ni teléfonos).")
st.dataframe(pd.DataFrame([
    ("id_paciente", "Sí", "Documento o N.° de historia anonimizado; permite calcular inasistencias previas"),
    ("fecha_registro", "Sí", "Día en que se otorgó la cita"),
    ("fecha_cita", "Sí", "Día de la consulta"),
    ("edad", "Sí", "Años"),
    ("zona", "Sí", "Distrito, comuna o localidad de residencia del paciente"),
    ("falto", "Para entrenar o recalibrar", "1 si no asistió, 0 si asistió"),
    ("subsidio", "Recomendada", "1 si tiene SIS, FONASA A-B u otro régimen subsidiado"),
    ("hipertension, diabetes", "Opcional", "Derivadas de diagnósticos CIE-10"),
    ("canal_disponible", "Recomendada", "whatsapp, sms_voz o ninguno; si falta se simula"),
    ("servicio", "Recomendada", "Especialidad: entra al modelo al reentrenar y limita la reasignación al mismo servicio"),
    ("turno", "Recomendada", "Mañana o tarde: entra al modelo al reentrenar"),
    ("sexo, faltas_previas", "Opcional", "El sexo no entra al modelo; las faltas previas se calculan del historial si no vienen"),
], columns=["Columna", "Obligatoria", "Descripción"]), hide_index=True, use_container_width=True)
d1, d2 = st.columns(2)
d1.download_button("Plantilla de datos (CSV)", (RAIZ / "datos" / "plantilla_citas.csv").read_bytes(),
                   "plantilla_citas.csv", "text/csv", icon=":material/download:", use_container_width=True)
d2.download_button("Plantilla de configuración (YAML)", (RAIZ / "config" / "plantilla_otro_lugar.yaml").read_bytes(),
                   "plantilla_otro_lugar.yaml", icon=":material/download:", use_container_width=True)

c.seccion("Paso 2. Configurar el establecimiento")
st.markdown("Copiar la plantilla de configuración como `config/mi_hospital.yaml` y completar los nombres de las columnas locales, "
            "los textos que indican inasistencia, los costos de cada canal y el porcentaje de citas que el personal puede llamar.")

c.seccion("Paso 3. Verificar y recalibrar")
local = st.file_uploader("Historial local en formato estándar, con la columna 'falto'", type="csv", key="local")
if local:
    df_local = pd.read_csv(local)
    cfg_std = cargar_config(c.CFG_ESTANDAR)
    problemas = verificar_columnas(df_local, cfg_std, con_objetivo=True)
    if problemas:
        st.error("\n".join(problemas))
    else:
        df_local, limp = estandarizar(df_local, cfg_std)
        st.success(f"Archivo válido: {c.num(limp['filas_finales'])} citas; inasistencia local {c.pct(limp['tasa_inasistencia'])}.")
        if len(df_local) < 200 or df_local["falto"].nunique() < 2:
            st.warning("Se necesitan al menos 200 citas con asistencias e inasistencias para recalibrar.")
        elif st.button("Recalibrar con estos datos", type="primary"):
            nuevo = recalibrar(c.cargar_sistema(), df_local, cfg_std)
            buf = io.BytesIO()
            joblib.dump(nuevo, buf)
            st.json(nuevo.info["recalibrado_con"])
            st.download_button("Descargar modelo recalibrado", buf.getvalue(), "sistema_recalibrado.joblib",
                               icon=":material/download:")
c.nota("También por consola: python recalibrar.py --config config/mi_hospital.yaml --salida modelos/mi_hospital.joblib "
       "(recalibrar) o python entrenar.py --config config/mi_hospital.yaml (reentrenar).")
