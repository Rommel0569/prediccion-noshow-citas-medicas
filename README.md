# Prototipo: predicción de inasistencia a citas médicas con recomendación por canal y reasignación de cupos

Proyecto del curso Gestión de Sistemas y Tecnologías de Información (UNSA). El sistema estima la probabilidad de
que un paciente falte a su cita, la clasifica en riesgo **bajo / medio / alto**, recomienda la acción de contacto
de menor costo según el canal disponible (WhatsApp, SMS/llamada o visita) y libera los cupos de riesgo alto que
no se confirman para reasignarlos a la lista de espera.

El modelo base se entrenó con el único dataset público latinoamericano con datos a nivel de cita
(Kaggle *Medical Appointment No Shows*, Brasil, 110 527 citas). Usa solo variables que existen en
cualquier sistema de citas de la región, así que puede llevarse a otro establecimiento (ver sección 4).

## 1. Instalación

Requiere Python 3.10 o superior.

```bash
pip install -r requirements.txt
```

## 2. Uso

```bash
python entrenar.py --config config/kaggle_brasil.yaml
```

Entrena y guarda `modelos/sistema.joblib` y `modelos/sistema.json` (las métricas). También genera
`datos/agenda_demo.csv`. Ya viene entrenado, así que solo hace falta repetirlo si se cambian los datos.

```bash
streamlit run app.py
```

```bash
python experimentos.py
```

Compara el modelo único con modelos por grupo (anticipación, edad, historial) y guarda el resultado que muestra la pestaña 4.

```bash
python evaluar.py
```

Compara 9 estrategias de contacto con las inasistencias reales del 20 % de prueba. También evalúa 1 000 grupos de 100 citas reales, calcula el efecto del SMS ajustado por todas las variables y el tamaño de muestra del piloto.

```bash
python probar_casos.py
```

Corre 100 casos de prueba variados de Arequipa (distritos, especialidades, horas, canales y esperas) con 11 verificaciones automáticas.

Abre la aplicación en el navegador (http://localhost:8501). La navegación lateral sigue el flujo de trabajo:

| Sección | Página | Qué hace |
|---|---|---|
| Operación | Panel de control | Resumen de la agenda: citas, inasistencias esperadas y evitables, contactos asignados, costos y citas prioritarias |
| Operación | Programación de citas | Al agendar: busca al paciente por N.° de historia, calcula el riesgo, el nivel, los factores determinantes (SHAP) y la acción, canal, momento y costo |
| Operación | Agenda y contactos | Cola de trabajo priorizada, con filtros y exportación a CSV; permite cargar una agenda propia |
| Operación | Confirmaciones y cupos | Libera los cupos no confirmados y los reasigna a la lista de espera por antigüedad |
| Análisis | Indicadores de gestión | Comparativo de estrategias de contacto, efecto del recordatorio y escenarios |
| Análisis | Calidad del modelo | AUC, curva ROC, importancia, desempeño por anticipación y pruebas automáticas |
| Administración | Configuración | Capacidad de llamadas y costos por canal (se aplican a toda la sesión) |
| Administración | Incorporar establecimiento | Plantillas, verificación de un archivo y recalibración con datos locales |
## 3. Estructura

```
config/                    parámetros por establecimiento (mapeo de columnas, costos, niveles)
  kaggle_brasil.yaml       dataset de entrenamiento base
  plantilla_otro_lugar.yaml  PLANTILLA para un hospital nuevo
  formato_estandar.yaml    para archivos que ya usan los nombres estándar
datos/
  plantilla_citas.csv      ejemplo del formato estándar (3 filas)
  ejemplo_historial_local.csv  ejemplo de historial para recalibrar (3 000 citas)
  agenda_demo.csv          agenda de demostración
noshow/                    paquete del sistema
  datos.py                 verificación de columnas, limpieza y estandarización
  variables.py             inasistencias previas (sin fuga de información) y tasa por zona
  modelo.py                entrenamiento, calibración, niveles, recalibración y explicación (SHAP)
  recomendacion.py         reglas riesgo × canal → acción, momento y costo
  cupos.py                 confirmación, liberación y reasignación a la lista de espera
  impacto.py               indicadores de costo-efectividad, efecto del SMS y escenarios
entrenar.py / recalibrar.py / experimentos.py / evaluar.py / probar_casos.py  comandos de consola
app.py                     aplicación web (Streamlit): navegación y tema
interfaz/                  estilos y componentes compartidos
paginas/                   una página por módulo (panel, programar, contactos, cupos, ...)
modelos/                   modelo entrenado y reporte de métricas
```

## 4. Cómo aplicarlo en otro establecimiento (por ejemplo, un hospital de Arequipa)

### 4.1 Datos que hay que conseguir

Se necesita una fila por cita, anonimizada, con estas columnas:

| Columna estándar | ¿Obligatoria? | Fuente típica en Perú |
|---|---|---|
| id_paciente | Sí | N.° de historia clínica o DNI, **anonimizado** (hash) |
| fecha_registro | Sí | Fecha en que se otorgó la cita (sistema de citas / EsSI / SIHCE) |
| fecha_cita | Sí | Fecha de la consulta |
| edad | Sí | Edad en años |
| sexo | Opcional | No entra al modelo: quitarlo no cambia la predicción (−0,0008 de AUC) |
| zona | Sí | Distrito de residencia |
| falto | Para entrenar o recalibrar | Estado de la cita (atendida / no atendida / deserción) |
| subsidio | Recomendada | Tipo de seguro (SIS = 1) |
| hipertension, diabetes | Opcional | Diagnósticos CIE-10 (I10–I15, E10–E14) |
| canal_disponible | Recomendada | Se obtiene al actualizar el contacto: whatsapp / sms_voz / ninguno |
| servicio | Recomendada | Especialidad. Entra al modelo al reentrenar y sirve para reasignar cupos dentro del mismo servicio |
| turno | Recomendada | MAÑANA / TARDE o la hora de la cita. Entra al modelo al reentrenar |

**Especialidad y turno:** el dataset de Brasil no los tiene, así que el modelo base usa 9 variables. Si el CSV local trae
`servicio` y/o `turno`, `entrenar.py` los agrega solos al modelo, que pasa a 11 variables: la tasa histórica de la
especialidad, calculada igual que la de la zona, y el turno tarde. Los estudios de Chile y Perú los asocian al riesgo.
También conviene reunir **más de un año de historial**.

### 4.2 Configuración

1. Copiar `config/plantilla_otro_lugar.yaml` como `config/mi_hospital.yaml`.
2. Completar los campos del archivo:
   - En `columnas`, poner el nombre de cada columna en el archivo del hospital.
   - En `valores.falto_si`, poner los textos que indican que el paciente no asistió (por ejemplo, "NO ATENDIDA").
   - En `niveles.alto_percentil`, poner el % de citas que el personal puede llamar (por defecto el 20 %).
   - En `costos`, poner el costo local de un SMS, una llamada y una visita, y el valor de una consulta.
   - En `efecto_canal`, mantener los valores de la literatura hasta medir el efecto local.

### 4.3 Elegir la opción según los datos disponibles

| Situación | Qué hacer | Comando |
|---|---|---|
| Sin datos locales | Usar el modelo base. Ordena bien el riesgo, pero los % son aproximados | (ninguno) |
| Pocos meses con resultado de asistencia (≥ 200 citas) | **Recalibrar** los % y umbrales | `python recalibrar.py --config config/mi_hospital.yaml --salida modelos/mi_hospital.joblib` |
| Historial suficiente (≥ 1 año) | **Reentrenar** con los datos locales | `python entrenar.py --config config/mi_hospital.yaml --salida modelos/mi_hospital.joblib` |

Ejemplo con los archivos incluidos:

```bash
python recalibrar.py --config config/formato_estandar.yaml --datos datos/ejemplo_historial_local.csv --salida modelos/ejemplo_recalibrado.joblib
```

Para que la aplicación use el modelo nuevo, cambie `MODELO` y `CFG_DATOS` al inicio de `app.py`.

## 5. Resultados del modelo base y limitaciones

- Datos: 110 516 citas válidas, con 20,19 % de inasistencia.
- **Regla 80/20 temporal:** el 80 % más antiguo se usa para entrenar. Su último cuarto sirve para elegir el modelo y calibrarlo, y luego se reentrena con todo el 80 %. El 20 % más reciente queda para la prueba final.
- El modelo elegido es Gradient Boosting:
  - AUC 0,731 (IC95 % 0,725–0,738) y PR-AUC 0,344 en la prueba.
  - **Mejora frente a no usar modelo:** si se marca el 20 % de las citas agendadas, el modelo encuentra el 28,2 % de las inasistencias. Al azar se encontraría el 20 % y con la regla de "solo anticipación", el 23,2 %. Son +41 % de inasistencias encontradas con el mismo esfuerzo.
- **¿Sirve avisar?** La comparación cruda engaña: con SMS faltó el 27,6 % y sin SMS el 16,7 %. Esto pasa porque el SMS solo se envió a citas con 3 días o más de anticipación. Dentro de cada tramo de anticipación, quien recibió SMS siempre faltó menos: −2,8 a −7,3 puntos (−11 % a −20 %). El sistema usa ese efecto por tramo y no avisa en las citas del mismo día.
- **Mejor estrategia (evaluar.py):** el sistema asigna las llamadas al 20 % de citas donde evitan más inasistencias por sol, y el resto recibe mensajes según el riesgo. Así evita 1 038 inasistencias reales de 4 882 (−21 %), frente a 634 (−13 %) del "SMS a todos", a S/ 14,24 por inasistencia evitada. Las visitas domiciliarias suman 26 evitadas, pero a S/ 166 cada una.
- **Variables:** se quitó el sexo porque no mejora la predicción. Se probaron 72 combinaciones de hiperparámetros y otras variables (hora de registro, citas previas): la mejora en validación no se mantiene en la prueba, así que el techo con estos datos es AUC ≈ 0,73.
- **Modelos por grupo:** se probó entrenar un modelo por anticipación, edad o historial (`experimentos.py`). Ninguno supera al modelo único, porque cada grupo tiene menos datos. Por eso la segmentación se aplica en la decisión y no en el modelo.
- **Limitación importante:** el factor dominante es la anticipación.
  - Sin las citas del mismo día, el AUC baja a 0,60.
  - Dentro de cada tramo de anticipación, el AUC está entre 0,57 y 0,59.
  - En hospitales con esperas largas, el desempeño esperado es moderado.
  - Por eso conviene recalibrar y agregar la especialidad, el turno y el historial local.
- El efecto del SMS en el dataset, ajustado por anticipación, es de −16 % de inasistencia.
- Los costos de WhatsApp y el valor de la consulta son **supuestos** y deben reemplazarse por los valores locales.
- La confirmación de citas y la lista de espera de la pestaña 3 son **simuladas**. En operación real vienen del registro de contactos.

## 6. Privacidad

Se trabaja solo con datos anonimizados. No se deben subir nombres, DNI ni teléfonos. El teléfono se usa únicamente
en el módulo de contacto del establecimiento y no entra al modelo.

## 7. Datos y licencia

El dataset original (Kaggle *Medical Appointment No Shows*, J. Hoppen, licencia CC BY-NC-SA 4.0, uso no comercial) **no se incluye**
en este repositorio: descárguelo de https://www.kaggle.com/datasets/joniarroba/noshowappointments y colóquelo en
`datos/KaggleV2-May-2016.csv` solo si desea reentrenar (`python entrenar.py --config config/kaggle_brasil.yaml`).
Los archivos derivados incluidos (`modelos/sistema_historial.csv.gz`, `datos/agenda_demo.csv`, etc.) provienen de ese dataset y
se comparten bajo la misma licencia, con atribución. Uso académico, sin pacientes reales.


## 8. Contacto real con los pacientes

El sistema envía los recordatorios y recibe las respuestas de verdad cuando hay un canal configurado:

| Canal | Qué hace | Costo |
|---|---|---|
| Telegram (bot) | Envía recordatorios con botones Confirmar / Cancelar / Reprogramar y registra la respuesta | Gratis |
| Twilio (opcional) | SMS y llamadas con mensaje hablado | De pago; la cuenta de prueba solo llega a números verificados |
| Personal | Llamadas y visitas: quedan como pendientes y el personal registra el resultado | - |

### Puesta en marcha con su propio bot (5 pasos)

1. En Telegram, abra **@BotFather**, envíe `/newbot` y elija un nombre y un usuario que termine en `bot`. BotFather entrega un **token**.
2. Copie `config/canales.ejemplo.yaml` como `config/canales.local.yaml` y pegue su token. También puede usar la variable de
   entorno `TELEGRAM_BOT_TOKEN`.
3. Inicie la aplicación (`streamlit run app.py`). En *Canales de contacto*, Telegram debe aparecer como *Configurado*;
   pulse *Verificar conexión*.
4. Genere un enlace de vinculación para un paciente de la agenda y ábralo en Telegram: el paciente queda autorizado.
5. En *Agenda y contactos* ejecute los contactos; en *Registro de contactos* verá las respuestas.

**Seguridad: nunca suba su token ni sus teléfonos al repositorio.** `config/canales.local.yaml`, `config/equipo.local.csv` y
`datos/operacion.db` están en `.gitignore`. Quien tenga el token controla el bot; si se expone, revóquelo con `/revoke` en BotFather.

Los teléfonos del equipo para pruebas se cargan desde `config/equipo.local.csv` (ver `config/equipo.ejemplo.csv`).
`python probar_contacto.py` verifica el ciclo completo contra un servidor Telegram de pruebas (21 verificaciones).
