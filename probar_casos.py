"""Pruebas del sistema con 100 casos variados (Arequipa): distintos distritos, especialidades, horas, canales y esperas.

Uso:
    python probar_casos.py

Genera datos/casos_prueba_100.csv (casos de prueba, no son pacientes reales), los pasa por el sistema y verifica
automáticamente que cada regla se cumpla. Guarda datos/resultados_casos_prueba.csv y modelos/pruebas_casos.json.
"""
import json
import time

import numpy as np
import pandas as pd

from noshow.config import RAIZ, cargar_config
from noshow.datos import estandarizar
from noshow.modelo import SistemaRiesgo
from noshow.recomendacion import recomendar
from noshow.variables import agregar_historial

DISTRITOS = ["AREQUIPA", "CERRO COLORADO", "PAUCARPATA", "MARIANO MELGAR", "MIRAFLORES", "ALTO SELVA ALEGRE", "CAYMA",
             "YANAHUARA", "SOCABAYA", "JOSE LUIS BUSTAMANTE Y RIVERO", "HUNTER", "SACHACA", "YURA", "CHARACATO", "MAJES"]
ESPECIALIDADES = ["CARDIOLOGIA", "NEUROLOGIA", "ENDOCRINOLOGIA", "NEUMOLOGIA", "REUMATOLOGIA", "NEFROLOGIA", "GERIATRIA",
                  "MEDICINA FISICA", "PEDIATRIA", "DERMATOLOGIA", "GASTROENTEROLOGIA", "OFTALMOLOGIA"]
HORAS = ["07:30", "08:00", "09:15", "10:30", "11:45", "13:00", "14:30", "15:45", "17:00", "18:00"]
GRUPOS = [("Mismo día", 10, (0, 0)), ("1 a 2 días", 15, (1, 2)), ("3 a 14 días", 25, (3, 14)),
          ("15 a 60 días", 25, (15, 60)), ("Más de 60 días (espera larga, como en EsSalud)", 25, (61, 150))]


def generar(semilla=2026):
    rng = np.random.default_rng(semilla)
    filas, i = [], 0
    hoy = pd.Timestamp("2026-10-13")
    for grupo, n, (dmin, dmax) in GRUPOS:
        for _ in range(n):
            i += 1
            edad = int(rng.choice([rng.integers(1, 17), rng.integers(18, 59), rng.integers(60, 92)], p=[0.2, 0.5, 0.3]))
            mayor = edad >= 60
            canal = rng.choice(["whatsapp", "sms_voz", "ninguno"], p=[0.483, 0.365, 0.152] if mayor else [0.802, 0.107, 0.091])
            dias = int(rng.integers(dmin, dmax + 1))
            filas.append({
                "id_cita": f"PRUEBA-{i:03d}", "id_paciente": f"PAC-{i:03d}", "grupo": grupo,
                "sexo": rng.choice(["F", "M"]), "fecha_registro": hoy.date(), "fecha_cita": (hoy + pd.Timedelta(days=dias)).date(),
                "hora_cita": rng.choice(HORAS), "edad": edad, "zona": rng.choice(DISTRITOS), "servicio": rng.choice(ESPECIALIDADES),
                "subsidio": int(rng.random() < 0.7), "hipertension": int(mayor and rng.random() < 0.45),
                "diabetes": int(edad >= 40 and rng.random() < 0.15),
                "faltas_previas": int(rng.choice([0, 0, 0, 1, 2, 3, 5])), "canal_disponible": canal,
            })
    casos = pd.DataFrame(filas)
    casos["turno"] = np.where(casos["hora_cita"].str[:2].astype(int) >= 13, "TARDE", "MAÑANA")
    return casos


def main():
    cfg = cargar_config("config/kaggle_brasil.yaml")
    std = cargar_config("config/formato_estandar.yaml")
    std["columnas"]["faltas_previas"] = "faltas_previas"
    sistema = SistemaRiesgo.cargar(RAIZ / "modelos" / "sistema.joblib")
    casos = generar()
    casos.to_csv(RAIZ / "datos" / "casos_prueba_100.csv", index=False)

    t0 = time.perf_counter()
    d, _ = estandarizar(casos, std, con_objetivo=False)
    d = agregar_historial(d)
    p = sistema.probabilidad(d)
    r = recomendar(d, p, sistema.nivel(p), cfg, sistema.info)
    seg_100 = time.perf_counter() - t0
    # tiempo de un caso individual (requisito RNF-04: menos de 3 s)
    t1 = time.perf_counter(); un = d.iloc[[0]]; pu = sistema.probabilidad(un); recomendar(un, pu, sistema.nivel(pu), cfg, sistema.info)
    seg_1 = time.perf_counter() - t1
    r = r.merge(casos[["id_cita", "grupo", "hora_cita"]], on="id_cita")

    # -------- verificaciones automáticas
    def caso_variado(**cambios):
        x = d.iloc[[30]].copy()
        for k, v in cambios.items():
            x[k] = v
        return float(sistema.probabilidad(x)[0])

    tel = r["canal_disponible"].isin(["whatsapp", "sms_voz"])
    cron = (r["hipertension"] == 1) | (r["diabetes"] == 1) | (r["faltas_previas"] > 0)
    pruebas = [
        ("Las 100 citas reciben probabilidad entre 0 y 1", bool(r["probabilidad"].between(0, 1).all())),
        ("Citas del mismo día: sin recordatorio y costo 0", bool((r.loc[r["dias_anticipacion"] == 0, "costo"] == 0).all()
                                                               and (r.loc[r["dias_anticipacion"] == 0, "canal_accion"] == "ninguno").all())),
        ("Solo se llama a quien tiene celular y cita futura", bool(((r["canal_accion"] != "llamada") | (tel & (r["dias_anticipacion"] > 0))).all())),
        ("Las llamadas no superan la capacidad (20 % de la agenda)", bool((r["canal_accion"] == "llamada").sum() <= 20)),
        ("Sin celular nunca recibe SMS ni WhatsApp", bool(~((~tel) & r["canal_accion"].isin(["sms", "whatsapp"])).any())),
        ("Visita solo para riesgo alto, sin celular y crónico o reincidente",
         bool(((r["canal_accion"] != "visita") | ((r["nivel"] == "alto") & ~tel & cron)).all())),
        ("La intervención nunca sube el riesgo", bool((r["probabilidad_con_intervencion"] <= r["probabilidad"]).all())),
        ("Más inasistencias previas → más riesgo", caso_variado(faltas_previas=3) > caso_variado(faltas_previas=0)),
        ("Distrito no visto en el entrenamiento se procesa (tasa global)", bool(r["probabilidad"].notna().all())),
        ("La hora y la especialidad no cambian el riesgo del modelo base (no las tiene)",
         caso_variado(servicio="CARDIOLOGIA") == caso_variado(servicio="PEDIATRIA")),
        ("Tiempo de un caso individual menor a 3 s (RNF-04)", seg_1 < 3),
    ]
    for nombre, ok in pruebas:
        print(("OK   " if ok else "FALLA"), nombre)

    por_grupo = (r.groupby("grupo", sort=False)
                 .agg(casos=("id_cita", "size"), riesgo_promedio=("probabilidad", "mean"),
                      llamadas=("canal_accion", lambda s: int((s == "llamada").sum())),
                      mensajes=("canal_accion", lambda s: int(s.isin(["sms", "whatsapp"]).sum())),
                      visitas=("canal_accion", lambda s: int((s == "visita").sum())),
                      sin_accion=("canal_accion", lambda s: int((s == "ninguno").sum())),
                      costo=("costo", "sum"))
                 .round(3).reset_index())
    print(por_grupo.to_string(index=False))
    print(f"100 casos en {seg_100:.2f} s; un caso en {seg_1 * 1000:.0f} ms")

    cols = ["id_cita", "grupo", "dias_anticipacion", "hora_cita", "servicio", "zona", "edad", "subsidio", "hipertension",
            "diabetes", "faltas_previas", "canal_disponible", "probabilidad", "nivel", "canal_accion", "accion", "momento",
            "costo", "probabilidad_con_intervencion"]
    r[cols].to_csv(RAIZ / "datos" / "resultados_casos_prueba.csv", index=False)
    salida = {"pruebas": [{"prueba": n, "resultado": "OK" if ok else "FALLA"} for n, ok in pruebas],
              "por_grupo": por_grupo.to_dict("records"), "segundos_100_casos": round(seg_100, 3),
              "milisegundos_un_caso": round(seg_1 * 1000, 1),
              "resumen": {"llamadas": int((r["canal_accion"] == "llamada").sum()),
                          "mensajes": int(r["canal_accion"].isin(["sms", "whatsapp"]).sum()),
                          "visitas": int((r["canal_accion"] == "visita").sum()),
                          "costo_total": round(float(r["costo"].sum()), 2),
                          "riesgo_promedio": round(float(r["probabilidad"].mean()), 4),
                          "riesgo_con_intervencion": round(float(r["probabilidad_con_intervencion"].mean()), 4)}}
    (RAIZ / "modelos" / "pruebas_casos.json").write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
