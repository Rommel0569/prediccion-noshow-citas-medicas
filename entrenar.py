"""Entrena el sistema con un historial de citas.

Uso:
    python entrenar.py --config config/kaggle_brasil.yaml
    python entrenar.py --config config/mi_hospital.yaml --salida modelos/mi_hospital.joblib
"""
import argparse
import json
from pathlib import Path

import pandas as pd

from noshow.config import RAIZ, cargar_config
from noshow.datos import cargar
from noshow.impacto import efecto_sms_estratificado
from noshow.modelo import entrenar, guardar_reporte


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/kaggle_brasil.yaml")
    ap.add_argument("--salida", default="modelos/sistema.joblib")
    ap.add_argument("--datos", help="CSV (si no, se usa 'archivo_datos' del YAML)")
    args = ap.parse_args()

    cfg = cargar_config(args.config)
    if args.datos:
        cfg["archivo_datos_abs"] = str(RAIZ / args.datos)
    print(f"Datos: {cfg['nombre']}")
    df, limpieza = cargar(cfg)
    print("Limpieza:", json.dumps(limpieza, ensure_ascii=False))

    sistema, df_hist, prueba = entrenar(df, cfg)
    sistema.info["limpieza"] = limpieza
    if df["recordatorio"].nunique() == 2:
        # efecto por anticipación con todos los datos; por nivel de riesgo, solo en la prueba (riesgo fuera de muestra)
        sistema.info["efecto_recordatorio"] = efecto_sms_estratificado(df)
        sistema.info["efecto_recordatorio"]["por_riesgo"] = efecto_sms_estratificado(prueba, prueba["probabilidad"])["por_riesgo"]

    salida = RAIZ / args.salida
    sistema.guardar(salida)
    guardar_reporte(sistema.info, salida.with_suffix(".json"))
    cols_hist = [c for c in ["id_paciente", "fecha_cita", "falto", "edad", "sexo", "zona", "subsidio", "hipertension",
                             "diabetes", "servicio"] if c in df_hist]
    df_hist[cols_hist].to_csv(salida.with_name(salida.stem + "_historial.csv.gz"), index=False)

    if args.salida != "modelos/sistema.joblib":
        print(f"Guardado en {salida}")
        return
    # Agenda de demostración (solo para el modelo base): las citas de las 2 últimas fechas, en el formato estándar
    ultimas = sorted(prueba["fecha_cita"].unique())[-2:]
    demo = prueba[prueba["fecha_cita"].isin(ultimas)]
    columnas = ["id_cita", "id_paciente", "sexo", "fecha_registro", "fecha_cita", "edad", "zona",
                "subsidio", "hipertension", "diabetes"]
    demo[columnas].to_csv(RAIZ / "datos" / "agenda_demo.csv", index=False)

    i = sistema.info
    print(f"\nModelo elegido: {i['modelo_elegido']}")
    print(pd.DataFrame(i["prueba"]).T.to_string())
    print(f"AUC en prueba sin citas del mismo día: {i['auc_prueba_sin_citas_mismo_dia']}")
    print(f"Guardado en {salida}")


if __name__ == "__main__":
    main()
