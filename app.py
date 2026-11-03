"""Prototipo: sistema predictivo de inasistencia con recomendación por canal y reasignación de cupos.

Ejecutar:  streamlit run app.py
"""
import io
import json
from datetime import date, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from noshow import NOMBRES_LEGIBLES
from noshow.config import RAIZ, cargar_config
from noshow.cupos import generar_lista_espera, liberar_y_reasignar, simular_confirmacion
from noshow.datos import estandarizar, verificar_columnas
from noshow.impacto import escenarios, resumen_agenda
from noshow.modelo import Explicador, SistemaRiesgo, recalibrar
from noshow.recomendacion import ordenar_por_prioridad, recomendar, simular_canales
from noshow.variables import agregar_historial

st.set_page_config(page_title="Inasistencia a citas médicas", page_icon="🩺", layout="wide")

MODELO = RAIZ / "modelos" / "sistema.joblib"
CFG_DATOS = "config/kaggle_brasil.yaml"
CFG_ESTANDAR = "config/formato_estandar.yaml"
CANALES = {"whatsapp": "WhatsApp", "sms_voz": "Solo SMS / llamadas", "ninguno": "Sin celular"}
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
COLOR = {"alto": "#D64545", "medio": "#E08E0B", "bajo": "#2E9E5B"}
ICONO = {"alto": "🔴", "medio": "🟠", "bajo": "🟢"}
ICONO_CANAL = {"llamada": "📞", "whatsapp": "💬", "sms": "✉️", "visita": "🏠", "ninguno": "➖"}

# Estilos que funcionan en tema claro y oscuro (fondos translúcidos)
st.markdown("""
<style>
.tarjeta{border:1px solid rgba(128,128,128,.30);border-radius:14px;padding:16px 20px;height:100%;}
.tarjeta h4{margin:0 0 6px 0;font-size:.95rem;opacity:.75;font-weight:600;}
.grande{font-size:2.8rem;font-weight:700;line-height:1.05;}
.chip{display:inline-block;padding:3px 12px;border-radius:999px;font-weight:700;font-size:.85rem;color:#fff;}
.barra{background:rgba(128,128,128,.25);border-radius:8px;height:12px;margin-top:10px;overflow:hidden;}
.barra>div{height:100%;border-radius:8px;}
.dato{display:inline-block;margin:6px 14px 0 0;font-size:.92rem;}
.dato b{opacity:.7;font-weight:600;}
.factor{margin:6px 0;font-size:.93rem;}
.factor .pista{background:rgba(128,128,128,.22);border-radius:6px;height:10px;margin-top:3px;}
.factor .pista>div{height:100%;border-radius:6px;}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def cargar_sistema(ruta):
    return SistemaRiesgo.cargar(ruta)


@st.cache_resource
def cargar_explicador(ruta):
    sistema = cargar_sistema(ruta)
    hist = cargar_historial(ruta)
    fondo = pd.read_csv(RAIZ / "datos" / "agenda_demo.csv")
    cfg = cargar_config(CFG_ESTANDAR)
    fondo, _ = estandarizar(fondo, cfg, con_objetivo=False)
    fondo = agregar_historial(fondo, hist)
    return Explicador(sistema, fondo)


@st.cache_data
def cargar_historial(ruta):
    h = pd.read_csv(Path(ruta).with_name(Path(ruta).stem + "_historial.csv.gz"), parse_dates=["fecha_cita"])
    h["id_paciente"] = h["id_paciente"].astype(str).str.replace(r"\.0$", "", regex=True)
    return h


@st.cache_data
def ejemplos_pacientes(ruta):
    """Pacientes de ejemplo para la demostración: uno de riesgo alto y uno de riesgo bajo."""
    h = cargar_historial(ruta)
    g = h.groupby("id_paciente")["falto"].agg(["size", "sum"])
    alto = g.sort_values("sum", ascending=False).index[0]
    bajo = g[(g["size"] >= 3) & (g["sum"] == 0)].index[0]
    return alto, bajo


def texto_factor(var, aporte, valor):
    signo = "sube" if aporte > 0 else "baja"
    if var == "dias_anticipacion":
        v = f"{int(valor)} días"
    elif var in ("tasa_zona", "tasa_servicio"):
        v = f"{valor:.1%}"
    elif var == "dia_semana":
        v = DIAS[int(valor)]
    elif var in ("sexo_f", "subsidio", "hipertension", "diabetes", "turno_tarde"):
        v = "sí" if valor >= 0.5 else "no"
    else:
        v = f"{valor:g}"
    return f"{NOMBRES_LEGIBLES[var]} ({v}) {signo} el riesgo"


def procesar_agenda(df_std, sistema, cfg, historial):
    df = agregar_historial(df_std, historial)
    df = simular_canales(df, cfg)
    p = sistema.probabilidad(df)
    return ordenar_por_prioridad(recomendar(df, p, sistema.nivel(p), cfg, sistema.info))


def datos_del_paciente(historial, id_paciente, fecha_cita):
    """Lo que el sistema de admisión ya guarda del paciente: así no hay que digitarlo al programar la cita."""
    h = historial[historial["id_paciente"] == str(id_paciente).strip()]
    if h.empty:
        return None
    antes = h[h["fecha_cita"] < pd.Timestamp(fecha_cita)]
    ult = h.sort_values("fecha_cita").iloc[-1]
    return {
        "edad": int(ult["edad"]) if "edad" in h else 35, "sexo": str(ult.get("sexo", "F")),
        "zona": str(ult.get("zona", "")), "subsidio": bool(ult.get("subsidio", 0)),
        "hipertension": bool(ult.get("hipertension", 0)), "diabetes": bool(ult.get("diabetes", 0)),
        "faltas_previas": int(antes["falto"].sum()), "citas_previas": int(len(antes)),
        "ultima_cita": antes["fecha_cita"].max().date() if len(antes) else None,
    }


def tarjeta_riesgo(p, p_con, nivel):
    c = COLOR[nivel]
    return (f'<div class="tarjeta"><h4>Probabilidad de inasistencia</h4>'
            f'<span class="grande" style="color:{c}">{p:.1%}</span> '
            f'<span class="chip" style="background:{c}">{ICONO[nivel]} RIESGO {nivel.upper()}</span>'
            f'<div class="barra"><div style="width:{min(p, 1) * 100:.0f}%;background:{c}"></div></div>'
            f'<div style="margin-top:10px;font-size:.92rem;opacity:.85">Con la intervención recomendada: '
            f'<b>{p_con:.1%}</b> ({(p_con - p) * 100:+.1f} pts)</div></div>')


def tarjeta_accion(rec):
    icono = ICONO_CANAL.get(rec["canal_accion"], "➖")
    return (f'<div class="tarjeta"><h4>Acción recomendada</h4>'
            f'<div style="font-size:1.15rem;font-weight:600">{icono} {rec["accion"]}</div>'
            f'<span class="dato"><b>Canal</b> {rec["canal_accion"]}</span>'
            f'<span class="dato"><b>Momento</b> {rec["momento"]}</span>'
            f'<span class="dato"><b>Costo</b> S/ {rec["costo"]:.2f}</span></div>')


def html_factores(factores):
    tope = max(abs(a) for _, a, _ in factores) or 1
    filas = []
    for var, aporte, valor in factores:
        c = "#D64545" if aporte > 0 else "#2E9E5B"
        filas.append(f'<div class="factor">{"▲" if aporte > 0 else "▼"} {texto_factor(var, aporte, valor)}'
                     f'<div class="pista"><div style="width:{abs(aporte) / tope * 100:.0f}%;background:{c}"></div></div></div>')
    return "".join(filas)


if not MODELO.exists():
    st.error("No se encontró el modelo. Ejecute primero:  python entrenar.py --config config/kaggle_brasil.yaml")
    st.stop()

sistema = cargar_sistema(MODELO)
cfg = cargar_config(CFG_DATOS)
historial = cargar_historial(MODELO)
info = sistema.info
auc = info["prueba"][info["modelo_elegido"]]["auc"]

# ------------------------------------------------------------------ barra lateral
with st.sidebar:
    st.header("🩺 Sistema no-show")
    st.caption("Predicción de inasistencia, recomendación por canal y reasignación de cupos.")
    st.markdown("**Modelo en uso**")
    st.write(f"{info['modelo_elegido']}")
    st.caption(f"Entrenado con: {info['datos']}")
    s1, s2 = st.columns(2)
    s1.metric("AUC (prueba)", auc)
    s2.metric("Variables", len(sistema.variables))
    st.caption(f"Niveles: alto ≥ {sistema.cortes['alto']:.1%} · medio ≥ {sistema.cortes['medio']:.1%}")
    st.markdown("**Costos configurados (S/)**")
    c = cfg["costos"]
    st.caption(f"SMS {c['sms']} · llamada {c['llamada']} · visita {c['visita']} · consulta perdida {c['valor_consulta']}")
    st.divider()
    st.warning("**Modo demostración.** El canal disponible y las confirmaciones de los pacientes se simulan; "
               "el sistema todavía no envía mensajes ni llamadas reales.", icon="⚠️")

st.title("Sistema predictivo de inasistencia a citas médicas")
st.caption("Universidad Nacional de San Agustín · Gestión de Sistemas y Tecnologías de Información")

tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs(["🏠 Inicio", "1. Evaluar una cita", "2. Agenda",
                                              "3. Reasignación de cupos", "4. Desempeño del modelo",
                                              "5. Aplicar en otro lugar"])

# --------------------------------------------------------------------------- 0
with tab0:
    st.subheader("¿Qué hace el sistema?")
    st.markdown("Para cada cita futura **estima la probabilidad de que el paciente falte**, decide **a quién y por qué "
                "canal contactar al menor costo** y **libera el cupo** de quien no confirma para reasignarlo a la "
                "lista de espera.")
    st.graphviz_chart("""
digraph G {
  rankdir=LR; bgcolor="transparent";
  node [shape=box, style="rounded,filled", fillcolor="#EAF1FB", fontname="Helvetica", fontsize=11, fontcolor="#1b1b1b", color="#7A98C6"];
  edge [color="#7A98C6"];
  a [label="Cita programada\\n(historial + datos)"];
  b [label="Variables\\nanticipación, historial,\\nedad, zona, seguro"];
  c [label="Modelo\\nprobabilidad y\\nnivel de riesgo"];
  d [label="Motor de reglas\\nriesgo × canal × costo"];
  e [label="Contacto\\nllamada · mensaje · visita"];
  f [label="¿Confirmó\\na 24 h?", shape=diamond, fillcolor="#FFF2D6"];
  g [label="Libera cupo →\\nlista de espera", fillcolor="#E3F4E8"];
  a -> b -> c -> d -> e -> f; f -> g [label=" no"];
}
""", use_container_width=True)
    i1, i2, i3 = st.columns(3)
    i1.markdown("**1 · Predice**  \nProbabilidad de inasistencia por cita, con los 3 factores que más influyen (SHAP).")
    i2.markdown("**2 · Decide**  \nLlamada para el 20 % donde más inasistencias evita por sol; mensajes para el resto; "
                "visita solo para riesgo alto sin celular; sin aviso en citas del mismo día.")
    i3.markdown("**3 · Reasigna**  \nLos cupos priorizados que no confirman a 24 h se liberan y pasan a la lista de espera.")
    r1, r2, r3, r4 = st.columns(4)
    comp = info.get("comparacion_prueba")
    r1.metric("AUC en prueba", auc)
    if comp:
        r2.metric("Inasistencias halladas (20 % marcado)", f"{comp[-1]['captura_top']:.1%}", "frente a 20 % al azar")
    r3.metric("Evita con el sistema", "21,3 %", "frente a 13,0 % con SMS a todos")
    r4.metric("Costo por inasistencia evitada", "S/ 14,24")
    st.caption("Resultados sobre 26 449 citas reales que el modelo no vio al entrenar (simulación del efecto de cada canal).")
    with st.expander("🎬 Guion sugerido para la demostración", expanded=True):
        st.markdown("""
1. **Evaluar una cita:** pulse *Paciente de riesgo alto* y observe la probabilidad, el nivel, la acción (llamada) y los factores.
   Luego pulse *Paciente de riesgo bajo* y compare.
2. **Agenda:** se procesa la agenda de demostración (citas reales que el modelo no vio). Vea cuántas llamadas, mensajes y visitas se asignan y el costo.
3. **Reasignación:** cambie el tamaño de la lista de espera y vea cuántos cupos se reutilizan.
4. **Desempeño:** muestre el AUC, la mejora frente al azar y la comparación de estrategias.
5. **Otro lugar:** descargue la plantilla y explique cómo se recalibra con datos de otro hospital.
""")

# --------------------------------------------------------------------------- 1
with tab1:
    st.subheader("Riesgo de una cita futura y acción recomendada")
    st.caption("En operación el riesgo se calcula solo, al programar la cita, con lo que admisión ya guarda "
               "(N.° de historia, fecha, distrito, edad, seguro e historial). Aquí puede buscar un paciente o llenar los datos.")
    ej_alto, ej_bajo = ejemplos_pacientes(MODELO)
    if "id_buscar" not in st.session_state:
        st.session_state["id_buscar"] = ""
    q1, q2, _q3 = st.columns([1, 1, 2])
    hoy = date.today()
    q1.button("🔴 Paciente de riesgo alto", use_container_width=True,
              on_click=lambda: st.session_state.update(id_buscar=ej_alto, f_reg=hoy, f_cita=hoy + timedelta(days=15)))
    q2.button("🟢 Paciente de riesgo bajo", use_container_width=True,
              on_click=lambda: st.session_state.update(id_buscar=ej_bajo, f_reg=hoy, f_cita=hoy + timedelta(days=1)))
    b1, b2, b3 = st.columns([2, 1, 1])
    id_buscar = b1.text_input("N.° de historia clínica (anonimizado)", key="id_buscar",
                              placeholder="Ej.: " + ej_alto)
    f_reg = b2.date_input("Fecha de registro de la cita", hoy, key="f_reg")
    f_cita = b3.date_input("Fecha de la cita", hoy + timedelta(days=15), key="f_cita")
    pac = datos_del_paciente(historial, id_buscar, f_cita) if id_buscar else None
    if id_buscar and pac is None:
        st.warning("No se encontró ese número en el historial: complete los datos a mano (paciente nuevo).")
    elif pac:
        st.success(f"Datos traídos del historial: {pac['citas_previas']} citas previas, {pac['faltas_previas']} "
                   f"inasistencias, última cita {pac['ultima_cita'] or '—'}.")
    d = pac or {"edad": 35, "sexo": "F", "zona": "", "subsidio": False, "hipertension": False, "diabetes": False,
                "faltas_previas": 0}
    k = f"_{id_buscar}" if pac else ""          # clave distinta por paciente: los campos se rellenan solos
    with st.expander("Datos del paciente", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            edad = st.number_input("Edad", 0, 110, d["edad"], key="edad" + k)
            faltas = st.number_input("Inasistencias previas del paciente", 0, 50, d["faltas_previas"], key="faltas" + k)
        with c2:
            zonas = sorted(sistema.codificador.tasas_)
            opciones = ["(otra / desconocida)"] + zonas
            zona = st.selectbox("Zona (en Perú: distrito de residencia)", opciones,
                                index=opciones.index(d["zona"]) if d["zona"] in zonas else 0, key="zona" + k)
            canal = st.selectbox("Canal de contacto disponible", list(CANALES), format_func=CANALES.get)
        with c3:
            subsidio = st.checkbox("Seguro subsidiado (SIS, FONASA A-B…)", d["subsidio"], key="sub" + k)
            hta = st.checkbox("Hipertensión", d["hipertension"], key="hta" + k)
            dm = st.checkbox("Diabetes", d["diabetes"], key="dm" + k)
        # Especialidad y turno: solo si el modelo en uso se entrenó con datos que los traen
        servicio, turno_tarde = "", 0
        if "tasa_servicio" in sistema.variables or "turno_tarde" in sistema.variables:
            e1, e2 = st.columns(2)
            if "tasa_servicio" in sistema.variables:
                servicio = e1.selectbox("Especialidad", sorted(sistema.cod_servicio.tasas_))
            if "turno_tarde" in sistema.variables:
                turno_tarde = int(e2.radio("Turno", ["Mañana", "Tarde"], horizontal=True) == "Tarde")
        else:
            st.caption("Especialidad y turno no se piden porque el modelo base (Brasil) no los tiene; "
                       "se agregan solos al reentrenar con datos locales que los incluyan (pestaña 5).")

    if f_cita < f_reg:
        st.warning("La fecha de la cita no puede ser anterior a la fecha de registro.")
    else:
        caso = pd.DataFrame([{
            "id_cita": "CASO", "id_paciente": "CASO",
            "fecha_registro": pd.Timestamp(f_reg), "fecha_cita": pd.Timestamp(f_cita),
            "dias_anticipacion": (f_cita - f_reg).days, "dia_semana": pd.Timestamp(f_cita).dayofweek,
            "edad": edad, "zona": zona.upper(), "subsidio": int(subsidio), "hipertension": int(hta),
            "diabetes": int(dm), "faltas_previas": faltas, "canal_disponible": canal,
            "servicio": servicio, "turno_tarde": turno_tarde,
        }])
        p = sistema.probabilidad(caso)
        rec = recomendar(caso, p, sistema.nivel(p), cfg, info).iloc[0]
        t1, t2 = st.columns(2)
        t1.markdown(tarjeta_riesgo(p[0], rec["probabilidad_con_intervencion"], rec["nivel"]), unsafe_allow_html=True)
        t2.markdown(tarjeta_accion(rec), unsafe_allow_html=True)
        st.markdown("##### Por qué: factores que más influyeron")
        try:
            factores = cargar_explicador(MODELO).explicar(caso)[0]
            st.markdown(html_factores(factores), unsafe_allow_html=True)
            st.caption("▲ rojo: sube el riesgo · ▼ verde: lo baja (valores SHAP).")
        except Exception as e:  # la explicación no debe impedir usar la predicción
            st.info(f"Explicación no disponible: {e}")

# --------------------------------------------------------------------------- 2
with tab2:
    st.subheader("Priorizar la agenda de próximas citas")
    st.caption("Suba un CSV en formato estándar (ver pestaña 5) o use la agenda de demostración "
               "(citas reales de las dos últimas fechas del dataset, que el modelo no vio al entrenar).")
    archivo = st.file_uploader("Agenda (CSV, formato estándar)", type="csv", key="archivo_agenda")
    origen = pd.read_csv(archivo) if archivo else pd.read_csv(RAIZ / "datos" / "agenda_demo.csv")
    try:
        df_std, limpieza = estandarizar(origen, cargar_config(CFG_ESTANDAR), con_objetivo=False)
        agenda = procesar_agenda(df_std, sistema, cfg, historial)
        st.session_state["agenda_proc"] = agenda
        r = resumen_agenda(agenda, {}, cfg)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Citas", f"{r['citas']:,}")
        k2.metric("Inasistencias esperadas", f"{r['inasistencias_esperadas_sin_intervencion']:,.0f}")
        k3.metric("Evitables con la intervención", f"{r['inasistencias_evitadas']:,.0f}", f"-{r['reduccion_relativa']:.0%}",
                  delta_color="inverse")
        k4.metric("Costo de contacto", f"S/ {r['costo_total_contacto']:,.2f}")
        if agenda["canal_simulado"].any():
            st.caption("El archivo no trae 'canal_disponible': se simuló con las proporciones del INEI 2025 "
                       "(solo para demostración).")
        g1, g2 = st.columns([1, 2])
        with g1:
            st.markdown("**Acciones asignadas**")
            cuenta = agenda["canal_accion"].value_counts()
            st.bar_chart(cuenta, horizontal=True, height=230)
        with g2:
            st.markdown("**Filtrar la agenda**")
            f1, f2 = st.columns(2)
            niveles = f1.multiselect("Nivel de riesgo", ["alto", "medio", "bajo"], default=["alto", "medio", "bajo"])
            solo_llamadas = f2.toggle("Solo citas para llamar", value=False)
        vista = agenda[["id_cita", "fecha_cita", "edad", "dias_anticipacion", "faltas_previas", "probabilidad",
                        "nivel", "prioridad_llamada", "canal_disponible", "canal_accion", "accion", "momento", "costo"]]
        vista = vista.assign(fecha_cita=vista["fecha_cita"].dt.date)
        vista = vista[vista["nivel"].isin(niveles)]
        if solo_llamadas:
            vista = vista[vista["prioridad_llamada"]]
        vista = vista.assign(nivel=vista["nivel"].map(lambda n: f"{ICONO[n]} {n}"))
        st.dataframe(vista, hide_index=True, use_container_width=True, height=420, column_config={
            "probabilidad": st.column_config.ProgressColumn("Probabilidad", min_value=0, max_value=1, format="%.2f"),
            "prioridad_llamada": st.column_config.CheckboxColumn("Llamar"),
            "costo": st.column_config.NumberColumn("Costo S/", format="%.2f"),
        })
        st.caption(f"{len(vista):,} de {len(agenda):,} citas mostradas.")
        st.download_button("⬇️ Descargar agenda priorizada (CSV)", vista.to_csv(index=False).encode("utf-8"),
                           "agenda_priorizada.csv", "text/csv")
    except ValueError as e:
        st.error(f"El archivo no tiene el formato esperado:\n\n{e}")

# --------------------------------------------------------------------------- 3
with tab3:
    st.subheader("Liberar cupos no confirmados y reasignarlos a la lista de espera")
    if "agenda_proc" not in st.session_state:
        st.info("Primero procese una agenda en la pestaña 2.")
    else:
        agenda = st.session_state["agenda_proc"]
        st.caption("Regla: si un paciente priorizado (llamada o riesgo alto) no confirma a 24 h de la cita, su cupo se "
                   "libera y pasa al paciente que más tiempo espera en la misma especialidad. Las confirmaciones se "
                   "simulan (confirma con probabilidad 1 − riesgo); en operación real vienen del registro de contactos.")
        n_espera = st.slider("Pacientes en lista de espera", 0, 500, 150)
        conf = simular_confirmacion(agenda)
        servicios = agenda["servicio"].dropna().unique() if "servicio" in agenda else None
        lista = generar_lista_espera(n_espera, servicios)
        tabla, res = liberar_y_reasignar(conf, lista)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Cupos liberados", f"{res['cupos_liberados']:,}", help="Priorizados que no confirmaron")
        c2.metric("Cupos reasignados", f"{res['cupos_reasignados']:,}")
        c3.metric("Tasa de reutilización", f"{res['tasa_reutilizacion']:.0%}")
        c4.metric("Asistencias recuperadas (esperadas)", f"{res['asistencias_recuperadas_esperadas']:,.0f}")
        if res["cupos_liberados"] > res["cupos_reasignados"]:
            st.caption(f"{res['cupos_liberados'] - res['cupos_reasignados']:,} cupos liberados quedan sin reasignar "
                       "porque la lista de espera simulada es más corta: la reutilización depende del tamaño real de la lista.")
        st.dataframe(tabla, hide_index=True, use_container_width=True, height=380)
        total = resumen_agenda(agenda, res, cfg)
        with st.expander("Resumen de impacto de la agenda (contacto + reasignación)"):
            st.json(total)

# --------------------------------------------------------------------------- 4
with tab4:
    st.subheader("Evaluación con la regla 80/20 (el 20 % más reciente no se usa para entrenar)")
    n = info["n"]
    st.caption(f"{info.get('particion', 'Partición temporal')}. Citas: entrenamiento {n['entrenamiento']:,} + "
               f"validación {n['validacion']:,} (= 80 %) · prueba {n['prueba']:,} (= 20 %). "
               f"Fechas del dataset: {info['fechas']['inicio']} a {info['fechas']['fin']}.")

    if "comparacion_prueba" in info:
        st.markdown("#### ¿Hay mejora? Modelo frente a no usar modelo")
        comp = pd.DataFrame(info["comparacion_prueba"]).rename(columns={
            "metodo": "Método", "auc_total": "AUC total", "auc_agendadas": "AUC citas agendadas",
            "captura_top": "Inasistencias atrapadas en el 20 % marcado"})
        st.dataframe(comp, hide_index=True, use_container_width=True)
        mod, azar = info["comparacion_prueba"][-1]["captura_top"], info["comparacion_prueba"][0]["captura_top"]
        st.success(f"Si el personal solo puede llamar al **20 %** de las citas agendadas, eligiéndolas con el modelo "
                   f"encuentra **{mod:.1%}** de las inasistencias, frente a **{azar:.0%}** al azar: "
                   f"**{mod / azar - 1:+.0%}** con el mismo esfuerzo.")

    st.markdown("#### Métricas del modelo en prueba")
    st.dataframe(pd.DataFrame(info["prueba"]).T, use_container_width=True)
    st.caption("Recall, precisión y F1 se calculan marcando como positivo al nivel alto.")
    c1, c2 = st.columns(2)
    with c1:
        fig, ax = plt.subplots(figsize=(4, 4))
        ax.plot(info["roc"]["fpr"], info["roc"]["tpr"], label=f"{info['modelo_elegido']} (AUC {auc})")
        ax.plot([0, 1], [0, 1], "--", color="grey", label="Azar (0,5)")
        ax.set_xlabel("Falsos positivos"); ax.set_ylabel("Verdaderos positivos"); ax.set_title("Curva ROC")
        ax.legend(loc="lower right")
        st.pyplot(fig)
    with c2:
        imp = pd.Series(info["importancia"]).rename(NOMBRES_LEGIBLES).sort_values()
        fig, ax = plt.subplots(figsize=(4.5, 4))
        imp.plot.barh(ax=ax, color="#2F6FB2"); ax.set_title("Importancia (caída de AUC al permutar)")
        st.pyplot(fig)
    with st.expander("Desempeño por tramo de anticipación"):
        st.caption("Dentro de cada tramo el desempeño es menor: la anticipación es el factor dominante.")
        st.dataframe(pd.DataFrame(info["por_tramo_anticipacion"]), hide_index=True)
        st.write(f"AUC en prueba excluyendo citas del mismo día: **{info['auc_prueba_sin_citas_mismo_dia']}**")

    if "efecto_recordatorio" in info:
        e = info["efecto_recordatorio"]
        st.markdown("#### ¿Sirve avisar? Efecto del SMS con la misma anticipación")
        if "crudo" in e:
            st.markdown(f"Comparación **cruda** (engañosa): con SMS faltó el **{e['crudo']['con_sms']:.1%}** y sin SMS "
                        f"el **{e['crudo']['sin_sms']:.1%}**. Pero el SMS solo se envió a citas con 3 o más días de "
                        f"anticipación, que son las que más se pierden. Comparando **dentro de cada tramo**, quien "
                        f"recibió SMS **siempre faltó menos**:")
        t = pd.DataFrame(e["tramos"])
        g1, g2 = st.columns([3, 2])
        with g1:
            fig, ax = plt.subplots(figsize=(5.5, 3.2))
            x = range(len(t))
            ax.bar([i - 0.2 for i in x], t["sin_sms"] * 100, 0.4, label="Sin SMS", color="#B0B7C3")
            ax.bar([i + 0.2 for i in x], t["con_sms"] * 100, 0.4, label="Con SMS", color="#2F6FB2")
            ax.set_xticks(list(x)); ax.set_xticklabels([f"{v} días" for v in t["tramo_dias"]])
            ax.set_ylabel("% de inasistencia"); ax.legend(); ax.set_title("Inasistencia por anticipación")
            st.pyplot(fig)
        with g2:
            st.dataframe(t.rename(columns={"tramo_dias": "días", "puntos_menos": "pts menos",
                                           "reduccion_relativa": "reducción"}), hide_index=True)
            st.markdown(f"Ajustado (Mantel-Haenszel): **{e['reduccion_relativa']:.1%} menos inasistencia**.")
        if "por_riesgo" in e:
            with st.expander("¿A quién conviene avisar primero? Efecto del SMS por nivel de riesgo"):
                st.dataframe(pd.DataFrame(e["por_riesgo"]), hide_index=True)
                st.caption("La reducción relativa es parecida en los tres grupos, pero en el riesgo alto se evitan más "
                           "inasistencias por cada 100 avisos: por eso la llamada (más cara) se reserva para ese grupo.")
        st.caption("Es una asociación en datos observacionales (el SMS no se asignó al azar); el efecto real de cada "
                   "canal debe confirmarse con un piloto.")

    exp = RAIZ / "modelos" / "experimento_segmentacion.json"
    if exp.exists():
        with st.expander("¿Mejora si se entrena un modelo por grupo?"):
            r = pd.DataFrame(json.loads(exp.read_text(encoding="utf-8"))["resultados"]).rename(columns={
                "enfoque": "Enfoque", "auc_agendadas": "AUC citas agendadas",
                "captura_top_agendadas": "Inasistencias atrapadas en el 20 % marcado"})
            st.dataframe(r, hide_index=True, use_container_width=True)
            st.caption("Con estos datos, separar en grupos no mejora: cada grupo tiene menos citas para aprender. "
                       "La segmentación se aplica en la decisión (anticipación y nivel de riesgo), no en el modelo.")

    ev_path = RAIZ / "modelos" / "evaluacion.json"
    if ev_path.exists():
        ev = json.loads(ev_path.read_text(encoding="utf-8"))
        st.markdown("#### Antes y después: estrategias de contacto (inasistencias reales del 20 % de prueba)")
        est = pd.DataFrame(ev["estrategias_prueba"]).drop(columns=["visitas"], errors="ignore")
        st.dataframe(est.rename(columns={"estrategia": "Estrategia", "inasistencias_reales": "Inasistencias reales",
                                         "evitadas": "Evitadas", "tasa_resultante": "Tasa resultante",
                                         "reduccion_relativa": "Reducción", "costo_total": "Costo S/",
                                         "costo_por_evitada": "S/ por evitada", "llamadas": "Llamadas"}),
                     hide_index=True, use_container_width=True)
        st.caption("Una inasistencia real alcanzada por un canal se evita con la probabilidad del efecto del canal "
                   "(SMS: medido en los datos por anticipación; llamada y visita: literatura). SMS y llamadas solo "
                   "llegan a quien tiene celular (canal simulado con proporciones del INEI).")
        m = ev["muestras_100"]
        st.info(f"**En grupos de 100 citas reales** ({m['n_muestras']} muestras): hay en promedio "
                f"{m['inasistencias_promedio']} inasistencias; entre las 20 que marca el modelo hay "
                f"**{m['encontradas_modelo']}**, frente a {m['encontradas_regla_anticipacion']} con la regla de "
                f"anticipación y {m['encontradas_azar']} al azar. El modelo gana al azar en "
                f"{m['modelo_supera_azar_pct']:.0%} de las muestras.")
        ipw = ev.get("efecto_sms_ipw")
        if ipw:
            st.markdown(f"**Efecto del SMS ajustado por todas las variables** (puntaje de propensión): "
                        f"{ipw['reduccion_relativa']:.1%} menos inasistencia (IC95 % {ipw['ic95_reduccion'][0]:.1%} a "
                        f"{ipw['ic95_reduccion'][1]:.1%}). Para confirmarlo como causa hace falta un piloto aleatorizado: "
                        f"{ev['piloto']['citas_por_grupo_para_detectar']['15 %']:,} citas por grupo detectan una "
                        "reducción de 15 %.")
    pc_path = RAIZ / "modelos" / "pruebas_casos.json"
    if pc_path.exists():
        with st.expander("Pruebas con 100 casos variados (python probar_casos.py)"):
            pc = json.loads(pc_path.read_text(encoding="utf-8"))
            st.dataframe(pd.DataFrame(pc["pruebas"]), hide_index=True, use_container_width=True)
            st.dataframe(pd.DataFrame(pc["por_grupo"]), hide_index=True, use_container_width=True)

    with st.expander("Escenarios de impacto (banda de la evidencia, Tabla E2 del informe)"):
        st.dataframe(escenarios(info["tasa_global_entrenamiento"]), hide_index=True)

# --------------------------------------------------------------------------- 5
with tab5:
    st.subheader("Cómo aplicar el sistema en otro establecimiento")
    st.markdown("""
1. **Exportar** el historial de citas del establecimiento a CSV (una fila por cita, anonimizada).
2. **Mapear columnas:** copiar `config/plantilla_otro_lugar.yaml` y escribir el nombre de cada columna local.
3. **Elegir la opción según los datos disponibles:**
   - *Sin datos locales:* usar el modelo base (ordena bien el riesgo; los % son aproximados).
   - *Pocos meses de datos:* **recalibrar** (abajo, o `python recalibrar.py ...`).
   - *Historial suficiente:* **reentrenar** con `python entrenar.py --config config/mi_hospital.yaml`.
4. **Ajustar parámetros locales** en el YAML: % de citas que el equipo puede llamar (niveles), costos por canal y valor de la consulta.
""")
    with st.expander("Columnas que necesita el sistema", expanded=True):
        st.dataframe(pd.DataFrame([
            ("id_paciente", "Sí", "Documento o N.° de historia anonimizado (para calcular inasistencias previas)"),
            ("fecha_registro", "Sí", "Día en que se otorgó la cita"),
            ("fecha_cita", "Sí", "Día de la consulta"),
            ("edad", "Sí", "Años"),
            ("sexo", "Opcional", "F / M (no entra al modelo: no mejora la predicción)"),
            ("faltas_previas", "Opcional", "Inasistencias previas, si el sistema ya las cuenta (si no, se calculan del historial)"),
            ("zona", "Sí", "Distrito, comuna o localidad del paciente"),
            ("falto", "Para entrenar o recalibrar", "1 si no asistió, 0 si asistió"),
            ("subsidio", "Recomendada", "1 si tiene SIS / FONASA A-B / régimen subsidiado / programa social"),
            ("hipertension, diabetes", "Opcional", "Derivadas de CIE-10"),
            ("canal_disponible", "Recomendada", "whatsapp / sms_voz / ninguno (si falta se simula)"),
            ("servicio", "Recomendada", "Especialidad: entra al modelo al reentrenar y permite reasignar cupos dentro del mismo servicio"),
            ("turno", "Recomendada", "MAÑANA / TARDE o la hora de la cita: entra al modelo al reentrenar"),
        ], columns=["Columna", "Obligatoria", "Descripción"]), hide_index=True, use_container_width=True)
    plantilla = (RAIZ / "datos" / "plantilla_citas.csv").read_bytes()
    yaml_tpl = (RAIZ / "config" / "plantilla_otro_lugar.yaml").read_bytes()
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Plantilla de datos (CSV)", plantilla, "plantilla_citas.csv", "text/csv")
    d2.download_button("⬇️ Plantilla de configuración (YAML)", yaml_tpl, "plantilla_otro_lugar.yaml")

    st.markdown("**Verificar y recalibrar con un archivo local (formato estándar)**")
    local = st.file_uploader("Historial local con columna 'falto'", type="csv", key="local")
    if local:
        df_local = pd.read_csv(local)
        cfg_std = cargar_config(CFG_ESTANDAR)
        problemas = verificar_columnas(df_local, cfg_std, con_objetivo=True)
        if problemas:
            st.error("\n".join(problemas))
        else:
            df_local, limp = estandarizar(df_local, cfg_std)
            st.success(f"Archivo válido: {limp['filas_finales']} citas, inasistencia local {limp['tasa_inasistencia']:.1%}.")
            if len(df_local) < 200 or df_local["falto"].nunique() < 2:
                st.warning("Se necesitan al menos 200 citas con asistencias e inasistencias para recalibrar.")
            elif st.button("Recalibrar con estos datos"):
                nuevo = recalibrar(cargar_sistema(MODELO), df_local, cfg_std)
                buf = io.BytesIO()
                import joblib
                joblib.dump(nuevo, buf)
                st.json(nuevo.info["recalibrado_con"])
                st.download_button("Descargar modelo recalibrado", buf.getvalue(), "sistema_recalibrado.joblib")
