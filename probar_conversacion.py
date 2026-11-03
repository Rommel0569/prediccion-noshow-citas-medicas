"""Pruebas de la conversación del bot: comprensión del español coloquial, contexto y acciones sobre las citas reales.

Ejecutar:  python probar_conversacion.py
"""
import os
import tempfile
from datetime import date, timedelta

os.environ["NOSHOW_DB"] = os.path.join(tempfile.mkdtemp(), "conv.db")

from noshow.contacto import almacen, conversacion   # noqa: E402

hoy = date.today()
resultados = []


def verificar(nombre, condicion):
    resultados.append(bool(condicion))
    print(("OK    " if condicion else "FALLA ") + nombre)


def di(paciente, texto):
    r = conversacion.responder(paciente, texto, hoy)
    return r["texto"], r


almacen.registrar_paciente("U1", 40, "", 0, 0, 0, "+51900000001", 1)
c1 = almacen.agendar_cita("U1", hoy + timedelta(days=5), "Cardiología", "Mañana")

# --- una sola cita
t, _ = di("U1", "Hola!!!"); verificar("saluda y ofrece ayuda", "asistente de citas" in t)
t, _ = di("U1", "holaaaa buenas tardes"); verificar("entiende saludos con letras repetidas", "asistente de citas" in t)
t, r = di("U1", "q hora es mi cita?"); verificar("responde la fecha y especialidad (abreviaturas)", "Cardiología" in t and r["botones"])
t, _ = di("U1", "cuando me toca ir"); verificar("entiende «cuándo me toca ir»", "Cardiología" in t)
t, _ = di("U1", "kiero cancelar mi sita"); verificar("cancelar con faltas de ortografía pide confirmación", "¿Desea cancelar" in t)
t, _ = di("U1", "mejor no"); verificar("«mejor no» mantiene la cita", "mantengo su cita" in t and almacen.obtener_cita(c1)["estado"] == "agendada")
di("U1", "no voy a poder ir"); t, _ = di("U1", "si")
verificar("«sí» tras la pregunta cancela la cita", "fue cancelada" in t and almacen.obtener_cita(c1)["estado"] == "cancelada")
t, _ = di("U1", "quiero ver mi cita"); verificar("sin citas vigentes lo dice", "No tengo citas próximas" in t)

# --- varias citas y contexto
almacen.registrar_paciente("U2", 30, "", 0, 0, 0, "+51900000002", 1)
a = almacen.agendar_cita("U2", hoy + timedelta(days=3), "Pediatría", "Tarde")
b = almacen.agendar_cita("U2", hoy + timedelta(days=9), "Neurología", "Mañana")
t, _ = di("U2", "mis citas"); verificar("lista varias citas", "1)" in t and "2)" in t)
t, _ = di("U2", "quiero cancelar"); verificar("con varias citas pregunta cuál", "¿Cuál desea cancelar?" in t)
t, _ = di("U2", "la 2"); verificar("entiende «la 2» y pide confirmar esa cita", "Neurología" in t and "¿Desea cancelar" in t)
t, _ = di("U2", "sí, cancelar"); verificar("confirma y cancela solo la elegida",
                                           almacen.obtener_cita(b)["estado"] == "cancelada" and almacen.obtener_cita(a)["estado"] == "agendada")
t, _ = di("U2", "confirmo mi cita"); verificar("confirma la única cita vigente", almacen.obtener_cita(a)["estado"] == "confirmada")
b2 = almacen.agendar_cita("U2", hoy + timedelta(days=20), "Neurología", "Mañana")
t, _ = di("U2", "reprogramar"); verificar("reprogramar pregunta cuál cuando hay varias", "¿Cuál desea reprogramar?" in t)
t, _ = di("U2", "la de neurologia"); verificar("entiende la especialidad como referencia y deriva al personal",
                                               "Anoté su solicitud" in t and almacen.obtener_cita(b2)["estado"] == "reprogramacion_solicitada"
                                               and len(almacen.pendientes_manuales()) >= 1)

# --- temas fuera del flujo
t, _ = di("U2", "tengo un dolor muy fuerte en el pecho"); verificar("urgencia: indica el 106 y avisa al personal", "106" in t)
t, _ = di("U2", "me pueden dar mi receta?"); verificar("tema clínico: no improvisa y deriva", "temas médicos" in t)
t, _ = di("U2", "donde queda el hospital"); verificar("dirección (sin dato configurado remite a admisión)", "admisión" in t or "Estamos en" in t)
t, _ = di("U2", "que debo llevar"); verificar("responde qué llevar", "DNI" in t)
t, _ = di("U2", "a que hora atienden"); verificar("responde horario", "Horario" in t)
t, _ = di("U2", "quiero hablar con una persona"); verificar("pasa al personal", "avisé al personal" in t)
t, _ = di("U2", "gracias"); verificar("agradece", "gusto" in t)
t, r = di("U2", "ya no quiero recibir mensajes"); verificar("baja: devuelve la acción de baja", r["accion"] == "baja")
t, _ = di("U2", "asdfgh"); verificar("no entiende: ofrece opciones", "No estoy seguro" in t)
t, _ = di("U2", "qwerty zzz"); verificar("tras dos fallos pasa al personal", "avisé al personal" in t or "Ya avisé" in t)
t, _ = di("U2", "ayuda"); verificar("explica qué puede hacer", "cita" in t)

print(f"\n{sum(resultados)}/{len(resultados)} verificaciones correctas")
raise SystemExit(0 if all(resultados) else 1)
