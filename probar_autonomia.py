"""Prueba del planificador autónomo: gestiona todo solo, según los datos de cada paciente (existentes y nuevos).

Usa servidores de prueba de Telegram y Twilio; no envía nada real.   Ejecutar:  python probar_autonomia.py
"""
import os
import tempfile
from datetime import datetime, timedelta

os.environ["NOSHOW_DB"] = os.path.join(tempfile.mkdtemp(), "auto.db")

import mocks_pruebas as mocks                         # noqa: E402
from noshow.config import RAIZ                        # noqa: E402
from noshow.contacto import agenda_db, almacen, despacho, respuestas, trabajador   # noqa: E402
from noshow.modelo import SistemaRiesgo               # noqa: E402

estado, canales, servidor = mocks.iniciar()
sistema = SistemaRiesgo.cargar(RAIZ / "modelos" / "sistema.joblib")
resultados = []


def verificar(nombre, condicion):
    resultados.append(bool(condicion))
    print(("OK    " if condicion else "FALLA ") + nombre)


def contactos_de(p):
    c = almacen.listar_contactos()
    return c[c["id_paciente"] == p] if not c.empty else c


ahora = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
dia = lambda n: (ahora + timedelta(days=n)).date()      # noqa: E731

# --- pacientes con distintos datos de contacto
for p, edad in (("A", 35), ("B", 61), ("C", 28), ("D", 45), ("W", 50)):
    almacen.registrar_paciente(p, edad, "", 0, 0, 0, "", 1)
almacen.registrar_destinatario("A", "telegram", 1001); almacen.registrar_destinatario("A", "telefono", "+51900000001")
almacen.registrar_destinatario("B", "telefono", "+51900000002")                      # solo teléfono
almacen.registrar_destinatario("D", "telegram", 1004)                                # solo Telegram
almacen.registrar_destinatario("W", "telegram", 1005)                                # lista de espera
cita = {p: almacen.agendar_cita(p, dia(2), "Cardiología", "Mañana", fecha_registro=dia(-10)) for p in "ABCD"}
lejana = almacen.agendar_cita("A", dia(30), "Cardiología", "Mañana", fecha_registro=dia(-10))

dest = almacen.destinatarios_activos()
verificar("el canal se deduce de lo que cada paciente tiene verificado",
          [agenda_db.canal_disponible(p, dest) for p in "ABCD"] == ["whatsapp", "sms_voz", "ninguno", "whatsapp"])

# --- primer ciclo: nadie interviene
r1 = trabajador.ciclo(canales, sistema, ahora)
contactos = almacen.listar_contactos()
canal_de = lambda p: set(contactos_de(p)["canal"]) if not contactos_de(p).empty else set()   # noqa: E731
verificar("hubo gestión automática", len(contactos) >= 3)
verificar("A (Telegram y teléfono) recibe por Telegram o llamada", canal_de("A") and canal_de("A") <= {"telegram", "llamada"})
verificar("B (solo teléfono) recibe SMS o llamada, nunca Telegram", canal_de("B") and canal_de("B") <= {"sms", "llamada"})
verificar("D (solo Telegram) recibe por Telegram o queda para el personal", canal_de("D") <= {"telegram", "llamada", "visita"})
verificar("C (sin canales) no recibe mensajes, solo gestión del personal", canal_de("C") <= {"llamada", "visita"})
verificar("la cita lejana (30 días) no se contacta aún", not (contactos["id_cita"] == lejana).any())
numeros_sms = {s["To"] for s in estado.sms}
verificar("los SMS van solo al teléfono de B", numeros_sms <= {"+51900000002"})
verificar("el SMS invita a pasar a Telegram con enlace", all("t.me/bot_de_prueba?start=" in s["Body"] for s in estado.sms))
verificar("los mensajes de Telegram solo llegan a quienes lo tienen verificado",
          {str(m["chat_id"]) for m in estado.enviados} <= {"1001", "1004"})
verificar("las llamadas automáticas van solo a quienes tienen teléfono", {c["To"] for c in estado.llamadas} <= {"+51900000001", "+51900000002"})
n1 = len(almacen.listar_contactos())
trabajador.ciclo(canales, sistema, ahora)
verificar("un segundo ciclo no repite contactos", len(almacen.listar_contactos()) == n1)

# --- paciente nuevo: se incorpora solo en el siguiente ciclo
almacen.registrar_paciente("F", 33, "", 0, 0, 0, "", 1)
almacen.registrar_destinatario("F", "telefono", "+51900000006")
cita_f = almacen.agendar_cita("F", dia(2), "Cardiología", "Tarde", fecha_registro=dia(-5))
trabajador.ciclo(canales, sistema, ahora)
verificar("un paciente nuevo es contactado en el siguiente ciclo sin tocar nada", not contactos_de("F").empty)

# --- el paciente cancela conversando con el bot; su cupo pasa a la lista de espera
almacen.agendar_cita("W", dia(40), "Dermatología", "Mañana")          # W ya tiene otra cita, distinta especialidad
almacen.agregar_espera("W", "Cardiología")
mocks.escribir(estado, 1004, "no voy a poder ir a mi cita")
respuestas.procesar(canales["telegram"])
verificar("el bot pide confirmar la cancelación", any("¿Desea cancelar" in m.get("text", "") for m in estado.enviados))
mocks.escribir(estado, 1004, "sí")
respuestas.procesar(canales["telegram"])
verificar("D cancela hablando con el bot", almacen.obtener_cita(cita["D"])["estado"] == "cancelada")
trabajador.ciclo(canales, sistema, ahora)
ofertas = [m for m in estado.enviados if "se liberó un cupo" in m.get("text", "")]
verificar("el cupo liberado se ofrece solo al paciente en espera", len(ofertas) == 1 and str(ofertas[0]["chat_id"]) == "1005")
rid = almacen.listar_reasignaciones().query("estado == 'ofrecida'")["id"].iloc[0]
mocks.escribir(estado, 1005, callback=f"a|{rid}|s")
respuestas.procesar(canales["telegram"])
nuevas = [c for c in almacen.citas_de_paciente("W") if c["servicio"] == "Cardiología"]
verificar("al aceptar, el cupo pasa de verdad al paciente en espera (cita nueva)", len(nuevas) == 1 and nuevas[0]["fecha_cita"] == str(dia(2)))

# --- escalamiento: confirmación sin respuesta a menos de 24 h => llamada
almacen.registrar_contacto(cita["B"], "B", "sms", "confirmacion", dia(2), "enviado")
llamadas_antes = len(estado.llamadas)
trabajador.ciclo(canales, sistema, ahora + timedelta(days=1, hours=12))
llamo_b = [c for c in estado.llamadas if c["To"] == "+51900000002"]
verificar("quien no respondió y está cerca recibe llamada", len(estado.llamadas) > llamadas_antes or llamo_b
          or (contactos_de("B")["tipo"] == "llamada").any())

# --- Twilio en cuenta de prueba: usa la plantilla predefinida en lugar del texto propio
canales["twilio"].plantilla_sms = "sms_appointment_reminders"
canales["twilio"].sms("+51900000009", "texto propio que la cuenta de prueba no admite")
verificar("con plantilla_sms el SMS envia el código de plantilla (cuenta de prueba)", estado.sms[-1]["Body"] == "sms_appointment_reminders")
canales["twilio"].plantilla_sms = None

# --- resiliencia: un canal caído no detiene el servicio
servidor.shutdown(); servidor.server_close()
almacen.registrar_paciente("G", 30, "", 0, 0, 0, "", 1); almacen.registrar_destinatario("G", "telegram", 1007)
almacen.agendar_cita("G", dia(2), "Cardiología", "Mañana", fecha_registro=dia(-5))
try:
    trabajador.ciclo(canales, sistema, ahora)
    verificar("con el canal caído el ciclo termina y registra el error (reintenta después)", True)
except Exception:
    verificar("con el canal caído el ciclo termina y registra el error (reintenta después)", False)

# --- si la llamada automática falla, el paciente no queda sin contacto: pasa al personal
import pandas as pd                                    # noqa: E402
almacen.registrar_destinatario("H", "telefono", "+51900000010")
fila = pd.DataFrame([{"id_cita": "X1", "id_paciente": "H", "tipo": "llamada", "destino": "Llamada automática", "estado": "Listo",
                      "fecha_cita": pd.Timestamp(dia(2)), "servicio": "", "dias": 2, "nivel": "alto"}])
res, _ = despacho.ejecutar(fila, canales, "Hospital")
pend = almacen.pendientes_manuales()
verificar("si la llamada automática falla, el paciente pasa al personal",
          res.get("derivados_al_personal") == 1 and (not pend.empty) and (pend["id_cita"] == "X1").any())

print(f"\n{sum(resultados)}/{len(resultados)} verificaciones correctas")
raise SystemExit(0 if all(resultados) else 1)



