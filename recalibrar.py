"""Aplica el modelo base a otro establecimiento con pocos datos locales (sin reentrenar).

Uso:
    python recalibrar.py --modelo modelos/sistema.joblib --config config/mi_hospital.yaml \
                         --salida modelos/mi_hospital_calibrado.joblib

Cuándo usar cada opción:
  * Sin datos locales     -> usar modelos/sistema.joblib tal cual (ordena bien el riesgo; % aproximados).
  * Pocos meses de datos  -> este script (ajusta % y umbrales a la tasa local).
  * Historial suficiente  -> python entrenar.py --config config/mi_hospital.yaml (reentrena).
"""
import argparse
import json

from noshow.config import RAIZ, cargar_config
from noshow.datos import cargar
from noshow.modelo import SistemaRiesgo, guardar_reporte, recalibrar


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", default="modelos/sistema.joblib")
    ap.add_argument("--config", required=True)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--datos", help="CSV local (si no, se usa 'archivo_datos' del YAML)")
    args = ap.parse_args()

    cfg = cargar_config(args.config)
    if args.datos:
        cfg["archivo_datos_abs"] = str(RAIZ / args.datos)
    sistema = SistemaRiesgo.cargar(RAIZ / args.modelo)
    df, limpieza = cargar(cfg)
    print("Datos locales:", json.dumps(limpieza, ensure_ascii=False))
    sistema = recalibrar(sistema, df, cfg)
    salida = RAIZ / args.salida
    sistema.guardar(salida)
    guardar_reporte(sistema.info, salida.with_suffix(".json"))
    print("Recalibrado:", sistema.info["recalibrado_con"])


if __name__ == "__main__":
    main()
