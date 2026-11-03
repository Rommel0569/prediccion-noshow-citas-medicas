"""Sistema predictivo de inasistencia con recomendación por canal y reasignación de cupos."""

# El sexo se quitó: no mejora la predicción (−0,0008 de AUC, IC95 % −0,0018 a 0) y la evidencia lo muestra débil.
VARIABLES_MODELO = [
    "dias_anticipacion",
    "dia_semana",
    "faltas_previas",
    "edad",
    "subsidio",
    "tasa_zona",
    "hipertension",
    "diabetes",
]

# Se agregan solas al reentrenar si los datos locales las traen (el dataset de Brasil no las tiene)
VARIABLES_OPCIONALES = ["tasa_servicio", "turno_tarde"]

NOMBRES_LEGIBLES = {
    "dias_anticipacion": "Días de anticipación",
    "dia_semana": "Día de la semana",
    "faltas_previas": "Inasistencias previas",
    "edad": "Edad",
    "sexo_f": "Sexo femenino",
    "subsidio": "Programa social / seguro subsidiado",
    "tasa_zona": "Tasa histórica de la zona",
    "hipertension": "Hipertensión",
    "diabetes": "Diabetes",
    "tasa_servicio": "Tasa histórica de la especialidad",
    "turno_tarde": "Turno tarde",
}
