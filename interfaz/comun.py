"""Utilidades compartidas: carga del modelo, parámetros de operación, agenda procesada y componentes visuales."""
import copy
import io
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from noshow import NOMBRES_LEGIBLES
from noshow.config import RAIZ, cargar_config
from noshow.datos import estandarizar
from noshow.modelo import Explicador, SistemaRiesgo
from noshow.recomendacion import ordenar_por_prioridad, recomendar, simular_canales
from noshow.variables import agregar_historial

MODELO = RAIZ / "modelos" / "sistema.joblib"
CFG_DATOS = "config/kaggle_brasil.yaml"
CFG_ESTANDAR = "config/formato_estandar.yaml"

NIVELES = {"alto": "Alto", "medio": "Medio", "bajo": "Bajo"}
COLOR_NIVEL = {"alto": "#B42318", "medio": "#B54708", "bajo": "#067647"}
FONDO_NIVEL = {"alto": "#FEE4E2", "medio": "#FEF0C7", "bajo": "#D1FADF"}
CANAL = {"llamada": "Llamada telefónica", "whatsapp": "WhatsApp", "sms": "SMS",
         "visita": "Visita domiciliaria", "ninguno": "Sin contacto"}
CANAL_DISPONIBLE = {"whatsapp": "WhatsApp", "sms_voz": "SMS / llamadas", "ninguno": "Sin celular"}
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
AZUL, AZUL_CLARO, GRIS = "#1F4E79", "#5B8DB8", "#9AA5B1"

CSS = """
<style>
.block-container{padding-top:2.2rem;padding-bottom:3rem;max-width:1280px;}
header[data-testid="stHeader"]{background:transparent;}
footer{visibility:hidden;}
h1,h2,h3,h4{letter-spacing:-.01em;}
h3{font-size:1.08rem !important;font-weight:650 !important;margin-top:1.6rem !important;padding-bottom:.35rem;
   border-bottom:1px solid #E4E8EE;}
.enc{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:1px solid #E4E8EE;
     padding-bottom:.9rem;margin-bottom:1.2rem;}
.enc h1{font-size:1.65rem;font-weight:650;margin:0;padding:0;line-height:1.2;}
.enc p{margin:.25rem 0 0 0;color:#667085;font-size:.95rem;}
.enc .der{color:#667085;font-size:.85rem;text-align:right;}
.panel{border:1px solid #D8DEE6;border-radius:8px;padding:16px 20px;background:#FFFFFF;}
.rotulo{font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:#667085;font-weight:600;margin-bottom:6px;}
.valor{font-size:2.5rem;font-weight:700;line-height:1.05;}
.badge{display:inline-block;padding:3px 12px;border-radius:4px;font-weight:700;font-size:.78rem;letter-spacing:.04em;}
.barra{background:#EEF1F5;border-radius:3px;height:8px;margin-top:12px;overflow:hidden;}
.barra>div{height:100%;}
.fila{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #EEF1F5;font-size:.92rem;}
.fila:last-child{border-bottom:none;}
.fila span:first-child{color:#667085;}
.accion{font-size:1.05rem;font-weight:600;margin:2px 0 10px 0;line-height:1.35;}
.factor{margin:10px 0 2px 0;font-size:.92rem;}
.factor .pista{background:#EEF1F5;border-radius:3px;height:6px;margin-top:5px;}
.factor .pista>div{height:100%;border-radius:3px;}
.paso{border-left:3px solid #1F4E79;padding:2px 0 2px 12px;margin-bottom:8px;}
.paso b{display:block;font-size:.92rem;}
.paso span{color:#667085;font-size:.88rem;}
.nota{color:#667085;font-size:.82rem;}
div[data-testid="stMetric"]{padding:2px 0;}
div[data-testid="stMetricLabel"] p{font-size:.78rem;color:#667085;font-weight:600;}
</style>
"""


def inyectar_estilos():
    st.markdown(CSS, unsafe_allow_html=True)


def estilo_grafico():
    plt.rcParams.update({
        "font.size": 9, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#C9D1DB",
        "axes.labelcolor": "#475467", "xtick.color": "#475467", "ytick.color": "#475467",
        "axes.titleweight": "bold", "axes.titlesize": 10, "axes.titlecolor": "#1B2733", "axes.titlelocation": "left",
        "axes.grid": True, "grid.color": "#EEF1F5", "axes.axisbelow": True, "figure.facecolor": "white",
        "legend.frameon": False,
    })


estilo_grafico()


# ------------------------------------------------------------------ formato y componentes
def num(x, dec=0):
    """Formato numérico en español: 12 345,6."""
    return f"{x:,.{dec}f}".replace(",", " ").replace(".", ",")


def pct(x, dec=1):
    return num(x * 100, dec) + " %"


def encabezado(titulo, descripcion, derecha=""):
    st.markdown(f'<div class="enc"><div><h1>{titulo}</h1><p>{descripcion}</p></div>'
                f'<div class="der">{derecha}</div></div>', unsafe_allow_html=True)


def seccion(titulo):
    st.markdown(f"### {titulo}")


def nota(texto):
    st.markdown(f'<div class="nota">{texto}</div>', unsafe_allow_html=True)


def badge_nivel(nivel):
    return (f'<span class="badge" style="background:{FONDO_NIVEL[nivel]};color:{COLOR_NIVEL[nivel]}">'
            f'{NIVELES[nivel].upper()}</span>')


def estado_html(texto, ok):
    fondo, color = ("#D1FADF", "#067647") if ok else ("#EEF1F5", "#667085")
    return f'<span class="badge" style="background:{fondo};color:{color}">{texto.upper()}</span>'


def estilo_nivel(df, columna="Nivel"):
    inverso = {v: k for k, v in NIVELES.items()}

    def f(v):
        k = inverso.get(v)
        return f"background-color:{FONDO_NIVEL[k]};color:{COLOR_NIVEL[k]};font-weight:600" if k else ""
    return df.style.map(f, subset=[columna])


def texto_factor(var, aporte, valor):
    signo = "aumenta" if aporte > 0 else "reduce"
    if var == "dias_anticipacion":
        v = f"{int(valor)} días"
    elif var in ("tasa_zona", "tasa_servicio"):
        v = pct(valor)
    elif var == "dia_semana":
        v = DIAS[int(valor)]
    elif var in ("sexo_f", "subsidio", "hipertension", "diabetes", "turno_tarde"):
        v = "sí" if valor >= 0.5 else "no"
    else:
        v = f"{valor:g}"
    return f"{NOMBRES_LEGIBLES[var]}: {v}", signo


def html_factores(factores):
    tope = max(abs(a) for _, a, _ in factores) or 1
    filas = []
    for var, aporte, valor in factores:
        etiqueta, signo = texto_factor(var, aporte, valor)
        color = COLOR_NIVEL["alto"] if aporte > 0 else COLOR_NIVEL["bajo"]
        filas.append(f'<div class="factor"><div class="fila" style="border:none;padding:0"><span style="color:#1B2733">'
                     f'{etiqueta}</span><span style="color:{color};font-weight:600">{signo} el riesgo</span></div>'
                     f'<div class="pista"><div style="width:{abs(aporte) / tope * 100:.0f}%;background:{color}"></div></div></div>')
    return "".join(filas)


# ------------------------------------------------------------------ modelo y datos (con caché)
@st.cache_resource
def cargar_sistema(ruta=MODELO):
    return SistemaRiesgo.cargar(ruta)


@st.cache_data
def cargar_historial(ruta=MODELO):
    h = pd.read_csv(Path(ruta).with_name(Path(ruta).stem + "_historial.csv.gz"), parse_dates=["fecha_cita"])
    h["id_paciente"] = h["id_paciente"].astype(str).str.replace(r"\.0$", "", regex=True)
    return h


@st.cache_resource
def cargar_explicador(ruta=MODELO):
    sistema = cargar_sistema(ruta)
    fondo = pd.read_csv(RAIZ / "datos" / "agenda_demo.csv")
    fondo, _ = estandarizar(fondo, cargar_config(CFG_ESTANDAR), con_objetivo=False)
    fondo = agregar_historial(fondo, cargar_historial(ruta))
    return Explicador(sistema, fondo)


@st.cache_data
def ejemplos_pacientes(ruta=MODELO):
    """Dos pacientes del historial para casos de ejemplo: con inasistencias reiteradas y sin ninguna."""
    g = cargar_historial(ruta).groupby("id_paciente")["falto"].agg(["size", "sum"])
    return g.sort_values("sum", ascending=False).index[0], g[(g["size"] >= 3) & (g["sum"] == 0)].index[0]


def datos_del_paciente(historial, id_paciente, fecha_cita):
    """Lo que admisión ya guarda del paciente: así no hay que digitarlo al programar la cita."""
    h = historial[historial["id_paciente"] == str(id_paciente).strip()]
    if h.empty:
        return None
    antes = h[h["fecha_cita"] < pd.Timestamp(fecha_cita)]
    ult = h.sort_values("fecha_cita").iloc[-1]
    return {
        "edad": int(ult["edad"]), "zona": str(ult.get("zona", "")), "subsidio": bool(ult.get("subsidio", 0)),
        "hipertension": bool(ult.get("hipertension", 0)), "diabetes": bool(ult.get("diabetes", 0)),
        "faltas_previas": int(antes["falto"].sum()), "citas_previas": int(len(antes)),
        "ultima_cita": antes["fecha_cita"].max().date() if len(antes) else None,
    }


# ------------------------------------------------------------------ parámetros de operación
@st.cache_resource
def _cfg_base():
    return cargar_config(CFG_DATOS)


def parametros_base():
    c = _cfg_base()
    return {"capacidad": c["niveles"]["alto_percentil"], "sms": c["costos"]["sms"],
            "whatsapp": c["costos"]["whatsapp"], "llamada": c["costos"]["llamada"],
            "visita": c["costos"]["visita"], "consulta": c["costos"]["valor_consulta"]}


def parametros():
    return {**parametros_base(), **st.session_state.get("parametros", {})}


def cfg_activa():
    """Configuración del establecimiento con los parámetros de operación vigentes en la sesión."""
    cfg, p = copy.deepcopy(_cfg_base()), parametros()
    cfg["niveles"]["alto_percentil"] = p["capacidad"]
    cfg["costos"].update({"sms": p["sms"], "whatsapp": p["whatsapp"], "llamada": p["llamada"],
                          "visita": p["visita"], "valor_consulta": p["consulta"]})
    return cfg


@st.cache_data(show_spinner="Procesando la agenda…")
def _procesar(contenido, cfg_json):
    cfg = json.loads(cfg_json)
    sistema, historial = cargar_sistema(), cargar_historial()
    origen = pd.read_csv(io.BytesIO(contenido)) if contenido else pd.read_csv(RAIZ / "datos" / "agenda_demo.csv")
    df, _ = estandarizar(origen, cargar_config(CFG_ESTANDAR), con_objetivo=False)
    df = simular_canales(agregar_historial(df, historial), cfg)
    p = sistema.probabilidad(df)
    return ordenar_por_prioridad(recomendar(df, p, sistema.nivel(p), cfg, sistema.info))


def obtener_agenda():
    """Agenda vigente (cargada por el usuario o de demostración) ya priorizada, y la configuración usada."""
    cfg = cfg_activa()
    cfg_json = json.dumps(cfg, sort_keys=True, default=str)
    try:
        return _procesar(st.session_state.get("agenda_bytes"), cfg_json), cfg
    except ValueError as e:
        st.session_state.pop("agenda_bytes", None)
        st.session_state.pop("agenda_nombre", None)
        st.session_state["agenda_error"] = str(e)
        return _procesar(None, cfg_json), cfg


def origen_agenda():
    return st.session_state.get("agenda_nombre") or "Agenda de demostración"


def vista_agenda(agenda):
    """Tabla de trabajo con nombres de columna comprensibles para el personal."""
    return pd.DataFrame({
        "N.° de cita": agenda["id_cita"].astype(str).str.replace(r"\.0$", "", regex=True),
        "Fecha de cita": agenda["fecha_cita"].dt.date,
        "Edad": agenda["edad"],
        "Anticipación (días)": agenda["dias_anticipacion"],
        "Inasistencias previas": agenda["faltas_previas"],
        "Riesgo": agenda["probabilidad"],
        "Nivel": agenda["nivel"].map(NIVELES),
        "Acción asignada": agenda["canal_accion"].map(CANAL),
        "Canal disponible": agenda["canal_disponible"].map(CANAL_DISPONIBLE),
        "Momento del contacto": agenda["momento"],
        "Costo (S/)": agenda["costo"],
    })


CONFIG_TABLA = {
    "Riesgo": st.column_config.ProgressColumn("Riesgo", min_value=0, max_value=1, format="percent"),
    "Costo (S/)": st.column_config.NumberColumn("Costo (S/)", format="%.2f"),
}
