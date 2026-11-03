"""Variables derivadas que existen en cualquier sistema de citas latinoamericano."""
import pandas as pd


def agregar_historial(df, historial=None):
    """Inasistencias previas del paciente, contando solo citas de fechas anteriores.

    `historial` (opcional) son citas pasadas ya atendidas o no, con columna 'falto';
    se usa al evaluar una agenda futura que aún no tiene resultado.
    """
    base = df[["id_paciente", "fecha_cita"]].copy()
    if historial is not None and len(historial):
        pasado = historial[["id_paciente", "fecha_cita", "falto"]].copy()
    elif "falto" in df:
        pasado = df[["id_paciente", "fecha_cita", "falto"]].copy()
    else:
        out = df.copy()
        out["faltas_previas"] = out["faltas_previas"].fillna(0).astype(int) if "faltas_previas" in out else 0
        return out

    por_dia = pasado.groupby(["id_paciente", "fecha_cita"], as_index=False)["falto"].sum()
    por_dia = por_dia.sort_values(["id_paciente", "fecha_cita"])
    por_dia["faltas_acum"] = por_dia.groupby("id_paciente")["falto"].cumsum()

    consulta = base.reset_index().sort_values("fecha_cita")
    por_dia = por_dia.sort_values("fecha_cita")
    unido = pd.merge_asof(
        consulta,
        por_dia[["id_paciente", "fecha_cita", "faltas_acum"]],
        on="fecha_cita",
        by="id_paciente",
        allow_exact_matches=False,
        direction="backward",
    ).set_index("index")
    out = df.copy()
    calculado = unido["faltas_acum"].reindex(out.index).fillna(0)
    if "faltas_previas" in out:     # el dato entregado por el establecimiento tiene prioridad
        calculado = out["faltas_previas"].fillna(calculado)
    out["faltas_previas"] = calculado.astype(int)
    return out


class CodificadorZona:
    """Tasa histórica de inasistencia por zona, suavizada hacia la tasa global.

    Se ajusta SOLO con datos de entrenamiento para no filtrar la respuesta.
    """

    def __init__(self, suavizado=50):
        self.suavizado = suavizado
        self.global_ = None
        self.tasas_ = {}

    def ajustar(self, zona, falto):
        self.global_ = float(falto.mean())
        g = pd.DataFrame({"zona": zona, "falto": falto}).groupby("zona")["falto"].agg(["sum", "count"])
        m = self.suavizado
        self.tasas_ = ((g["sum"] + m * self.global_) / (g["count"] + m)).to_dict()
        return self

    def transformar(self, zona):
        return zona.map(self.tasas_).fillna(self.global_).astype(float)


def matriz(df, codificador, variables, cod_servicio=None):
    out = df.copy()
    out["tasa_zona"] = codificador.transformar(out["zona"])
    if "tasa_servicio" in variables:
        serv = out["servicio"] if "servicio" in out else pd.Series("", index=out.index)
        out["tasa_servicio"] = cod_servicio.transformar(serv)
    if "turno_tarde" in variables and "turno_tarde" not in out:
        out["turno_tarde"] = 0
    return out[variables].astype(float)
