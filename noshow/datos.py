"""Carga un CSV de cualquier establecimiento y lo lleva al esquema estándar."""
import numpy as np
import pandas as pd

OBLIGATORIAS = ["id_paciente", "fecha_registro", "fecha_cita", "edad", "zona"]
OPCIONALES = ["sexo", "faltas_previas", "id_cita", "subsidio", "hipertension", "diabetes", "recordatorio", "canal_disponible", "servicio", "turno", "falto"]
TURNO_TARDE = ["TARDE", "T", "PM", "NOCHE", "N"]
CANALES = {"whatsapp", "sms_voz", "ninguno"}


def verificar_columnas(df, cfg, con_objetivo=True):
    """Devuelve la lista de problemas encontrados (vacía si el archivo es utilizable)."""
    problemas = []
    mapeo = cfg["columnas"]
    requeridas = OBLIGATORIAS + (["falto"] if con_objetivo else [])
    for std in requeridas:
        origen = mapeo.get(std)
        if not origen:
            problemas.append(f"Falta definir la columna '{std}' en la configuración.")
        elif origen not in df.columns:
            problemas.append(f"La columna '{origen}' (para '{std}') no está en el archivo.")
    return problemas


def _a_binario(serie, verdaderos):
    vals = {str(v).strip().lower() for v in verdaderos}
    return serie.astype(str).str.strip().str.lower().isin(vals).astype(int)


def _turno_tarde(serie, tarde):
    """1 si la cita es de tarde. Acepta texto (MAÑANA/TARDE) u hora (14:30)."""
    s = serie.astype(str).str.strip()
    hora = pd.to_numeric(s.str.extract(r"^(\d{1,2})[:h]")[0], errors="coerce")
    texto = s.str.upper().isin([str(v).upper() for v in tarde]).astype(int)
    return np.where(hora.notna(), (hora >= 13).astype(int), texto)


def estandarizar(df_origen, cfg, con_objetivo=True):
    """Renombra, tipa y limpia. Devuelve (df_estandar, reporte_limpieza)."""
    problemas = verificar_columnas(df_origen, cfg, con_objetivo)
    if problemas:
        raise ValueError("\n".join(problemas))

    mapeo = {k: v for k, v in cfg["columnas"].items() if v and v in df_origen.columns}
    df = df_origen[list(mapeo.values())].rename(columns={v: k for k, v in mapeo.items()}).copy()
    val = cfg["valores"]
    reporte = {"filas_iniciales": len(df)}

    df["id_paciente"] = df["id_paciente"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    if "id_cita" not in df:
        df["id_cita"] = np.arange(len(df))
    df["fecha_registro"] = pd.to_datetime(df["fecha_registro"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    df["fecha_cita"] = pd.to_datetime(df["fecha_cita"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    df["edad"] = pd.to_numeric(df["edad"], errors="coerce")
    if "sexo" in df:
        df["sexo_f"] = df["sexo"].astype(str).str.strip().isin([str(v) for v in val["sexo_femenino"]]).astype(int)
    if "faltas_previas" in df:      # si el sistema de admisión ya entrega el conteo de inasistencias previas
        df["faltas_previas"] = pd.to_numeric(df["faltas_previas"], errors="coerce")
    df["zona"] = df["zona"].astype(str).str.strip().str.upper()

    for col in ["subsidio", "hipertension", "diabetes", "recordatorio"]:
        df[col] = _a_binario(df[col], val["verdadero"]) if col in df else 0
    if con_objetivo:
        df["falto"] = _a_binario(df["falto"], val["falto_si"])
    if "canal_disponible" in df:
        df["canal_disponible"] = df["canal_disponible"].astype(str).str.strip().str.lower().astype(object)
        df.loc[~df["canal_disponible"].isin(CANALES), "canal_disponible"] = np.nan

    if "servicio" in df:
        df["servicio"] = df["servicio"].astype(str).str.strip().str.upper()
    if "turno" in df:
        df["turno_tarde"] = _turno_tarde(df["turno"], val.get("turno_tarde", TURNO_TARDE))

    df["dias_anticipacion"] = (df["fecha_cita"] - df["fecha_registro"]).dt.days
    validas = (
        df["fecha_registro"].notna()
        & df["fecha_cita"].notna()
        & df["dias_anticipacion"].ge(0)
        & df["edad"].between(0, 110)
    )
    reporte["filas_descartadas"] = int((~validas).sum())
    reporte["fechas_invalidas_o_negativas"] = int((df["fecha_registro"].isna() | df["fecha_cita"].isna() | df["dias_anticipacion"].lt(0)).sum())
    reporte["edades_fuera_de_rango"] = int((~df["edad"].between(0, 110)).sum())
    df = df[validas].copy()
    reporte["duplicados"] = int(df["id_cita"].duplicated().sum())
    df = df.drop_duplicates(subset=["id_cita"])
    df["dia_semana"] = df["fecha_cita"].dt.dayofweek
    reporte["filas_finales"] = len(df)
    if con_objetivo:
        reporte["tasa_inasistencia"] = round(float(df["falto"].mean()), 4)
    return df.reset_index(drop=True), reporte


def cargar(cfg, con_objetivo=True):
    df = pd.read_csv(cfg["archivo_datos_abs"], encoding_errors="replace")
    return estandarizar(df, cfg, con_objetivo)
