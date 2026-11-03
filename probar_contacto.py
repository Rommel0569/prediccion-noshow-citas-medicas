"""Prueba de extremo a extremo del contacto real contra un servidor Telegram de pruebas (sin red ni credenciales).

Cubre: vinculación con código, envío con botones, respuesta del paciente, llamada pendiente, liberación de cupo,
reasignación a la lista de espera y respuesta a la oferta.   Ejecutar:  python probar_contacto.py
"""
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pandas as pd

os.environ["NOSHOW_DB"] = os.path.join(tempfile.mkdtemp(), "prueba.db")

from noshow.contacto import almacen, despacho, mensajes, reasignacion, respuestas   # noqa: E402
from noshow.contacto.canales import ErrorCanal, Telegram                              # noqa: E402

ENVIADOS, COLA = [], []          # lo que el bot "envía" y las novedades que "escriben" los pacientes


class FalsoTelegram(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        datos = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        metodo = self.path.rsplit("/", 1)[-1]
        if metodo == "getUpdates":
            out = [u for u in COLA if u["update_id"] >= datos.get("offset", 0)]
        elif metodo == "sendMessage":
            ENVIADOS.append(datos); out = {"message_id": len(ENVIADOS)}
        else:
            out = True
        cuerpo = json.dumps({"ok": True, "result": out}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(cuerpo)


servidor = HTTPServer(("127.0.0.1", 0), FalsoTelegram)
threading.Thread(target=servidor.serve_forever, daemon=True).start()
tg = Telegram("TOKEN", f"http://127.0.0.1:{servidor.server_port}")
canales = {"telegram": tg, "twilio": None}
resultados = []


def verificar(nombre, condicion):
    resultados.append(condicion)
    print(("OK    " if condicion else "FALLA ") + nombre)


def escribir(chat, texto=None, callback=None):
    n = len(COLA) + 1
    if texto is not None:
        COLA.append({"update_id": n, "message": {"chat": {"id": chat}, "text": texto}})
    else:
        COLA.append({"update_id": n, "callback_query": {"id": f"cb{n}", "data": callback, "message": {"chat": {"id": chat}}}})


hoy = pd.Timestamp("2026-11-10")
agenda = pd.DataFrame([
    {"id_cita": "100", "id_paciente": "P1", "fecha_cita": hoy + pd.Timedelta(days=1), "nivel": "alto", "canal_accion": "whatsapp", "prioridad_llamada": False, "servicio": "Cardiología"},
    {"id_cita": "101", "id_paciente": "P2", "fecha_cita": hoy + pd.Timedelta(days=1), "nivel": "bajo", "canal_accion": "sms", "prioridad_llamada": False, "servicio": "Cardiología"},
    {"id_cita": "102", "id_paciente": "P3", "fecha_cita": hoy + pd.Timedelta(days=2), "nivel": "alto", "canal_accion": "llamada", "prioridad_llamada": True, "servicio": "Cardiología"},
    {"id_cita": "103", "id_paciente": "P4", "fecha_cita": hoy + pd.Timedelta(days=30), "nivel": "medio", "canal_accion": "whatsapp", "prioridad_llamada": False, "servicio": "Cardiología"},
])

def contacto(chat, telefono, user_id=None):
    n = len(COLA) + 1
    COLA.append({"update_id": n, "message": {"chat": {"id": chat}, "from": {"id": chat},
                                              "contact": {"phone_number": telefono, "user_id": user_id or chat}}})


# 1. Admisión: el paciente se registra primero y luego vincula su Telegram con el código
almacen.registrar_paciente("P1", 40, "", 0, 0, 0, "+51930693548", 1)
almacen.registrar_paciente("P2", 30, "", 0, 0, 0, "+51 911 111 111", 1)
cod1, cod2 = almacen.crear_vinculo("P1"), almacen.crear_vinculo("P2")
escribir(555, f"/start {cod1}"); escribir(556, f"/start {cod2}"); escribir(777, "/start codigo-falso")
r = respuestas.procesar(tg)
verificar("el código vincula el chat al registro y pide verificar el teléfono", r.get("pendientes_verificacion") == 2)
verificar("el bot pide compartir el número (botón de contacto)", any("request_contact" in json.dumps(m) for m in ENVIADOS))
verificar("código inválido no registra a nadie", almacen.id_por_destino("telegram", 777, solo_verificados=False) is None)
verificar("el código es de un solo uso", almacen.consumir_vinculo(cod1) is None)
verificar("sin verificar no se envían avisos", despacho.plan(pd.DataFrame([{
    "id_cita": "100", "id_paciente": "P1", "fecha_cita": pd.Timestamp("2026-11-11"), "nivel": "alto", "canal_accion": "whatsapp"}]),
    canales, pd.Timestamp("2026-11-10"))["estado"].iloc[0] == "Sin destino")

contacto(555, "51930693548")                        # P1 comparte su número real: coincide (sin prefijo + ni espacios)
contacto(556, "51999999999", user_id=999)           # P2 intenta compartir el contacto de otra persona
contacto(556, "51999999999")                        # P2 comparte un número distinto al registrado
r = respuestas.procesar(tg)
verificar("el número que coincide queda verificado", almacen.id_por_destino("telegram", 555) == "P1")
verificar("no se acepta el contacto de otra persona", any("propio número" in m["text"] for m in ENVIADOS))
verificar("el número distinto desactiva la vinculación", r.get("no_coincide") == 1 and almacen.id_por_destino("telegram", 556, False) is None)
escribir(556, f"/start {almacen.crear_vinculo('P2')}"); contacto(556, "+51 911 111 111")
respuestas.procesar(tg)
verificar("el paciente corrige y se verifica con su número", almacen.id_por_destino("telegram", 556) == "P2")
almacen.registrar_paciente("P6", 22, "", 0, 0, 0, "+51 922 222 222", 1)      # el mismo chat se vincula a otro paciente
escribir(556, f"/start {almacen.crear_vinculo('P6')}"); respuestas.procesar(tg)
verificar("un chat corresponde a un solo paciente", almacen.id_por_destino("telegram", 556, False) == "P6"
          and almacen.id_por_destino("telegram", 556) is None)
escribir(556, f"/start {almacen.crear_vinculo('P2')}"); contacto(556, "+51 911 111 111"); respuestas.procesar(tg)
ENVIADOS.clear()

# 2. Plan y envío
p = despacho.plan(agenda, canales, hoy)
estados = dict(zip(p["id_cita"], p["estado"]))
verificar("cita dentro de la ventana queda lista", estados["100"] == "Listo" and estados["101"] == "Listo")
verificar("cita lejana queda fuera de la ventana", estados["103"] == "Fuera de la ventana")
verificar("llamada va al personal", p[p["id_cita"] == "102"]["destino"].iloc[0] == "Personal (manual)")
resumen, errores = despacho.ejecutar(p, canales, "Hospital de prueba")
verificar("se enviaron 2 mensajes y 1 llamada pendiente", resumen.get("enviados_telegram") == 2 and resumen.get("pendientes_manuales") == 1)
avisos = [m for m in ENVIADOS if "Hospital de prueba" in m["text"]]
verificar("el aviso lleva botones y solo datos de la cita", len(avisos) == 2 and all("reply_markup" in m for m in avisos))
verificar("no se reenvía lo ya gestionado", despacho.plan(agenda, canales, hoy)["estado"].eq("Ya gestionado").sum() == 3)

# 3. Respuestas del paciente
escribir(555, callback="r|100|x")            # P1 cancela
escribir(556, callback="r|100|c")            # P2 intenta responder por la cita de P1 (debe ignorarse)
escribir(556, callback="r|101|c")            # P2 confirma la suya
r = respuestas.procesar(tg)
c = almacen.listar_contactos().set_index("id_cita")["respuesta"].to_dict()
verificar("el titular cancela su cita", c.get("100") == "cancelo")
verificar("nadie responde por la cita de otro", r.get("respuestas") == 2)
verificar("el titular confirma su cita", c.get("101") == "confirmo")

# 4. Llamada manual sin resultado + liberación y reasignación
pend = almacen.pendientes_manuales()
verificar("hay una llamada pendiente", len(pend) == 1)
almacen.registrar_resultado_manual(int(pend["id"].iloc[0]), "sin_respuesta")
almacen.agregar_espera("P9", "Cardiología"); almacen.agregar_espera("P8", "Pediatría")
escribir(900, "/start " + almacen.crear_vinculo("P9")); respuestas.procesar(tg)
ref = (hoy + pd.Timedelta(days=1, hours=12)).to_pydatetime()     # faltan 20 h para la cita 102 (08:00 del día 2)
lib, res = reasignacion.reasignar(agenda, canales, 24, ref, "Hospital de prueba")
ids = set(lib["id_cita"])
verificar("se liberan la cancelada y la llamada sin respuesta", ids == {"100", "102"})
verificar("la confirmada no se libera", "101" not in ids)
verificar("se ofrece al paciente de la misma especialidad", set(res["id_espera"].dropna()) == {"E0001"} or "E0001" in set(res["id_espera"].dropna()))
verificar("la oferta llegó por Telegram con botones", any("Tomar el cupo" in json.dumps(m) for m in ENVIADOS))
verificar("el segundo cupo queda sin candidato", (res["resultado"] == "Sin candidato de la misma especialidad").sum() == 1
         or (res["resultado"] == "Sin candidato en lista de espera").sum() == 1)

# 5. El paciente acepta la oferta
rid = int(almacen.listar_reasignaciones().query("estado == 'ofrecida'")["id"].iloc[0])
escribir(900, callback=f"a|{rid}|s")
respuestas.procesar(tg)
verificar("la oferta aceptada queda registrada", almacen.obtener_reasignacion(rid)["estado"] == "aceptada")
verificar("no se vuelve a ofrecer un cupo ya asignado", "E0001" not in set(reasignacion.reasignar(agenda, canales, 24, ref, "H")[1].get("id_espera", [])))

# 6. El bot atiende solo, sin que nadie ejecute nada
import time                                                              # noqa: E402
from noshow.contacto import servicio                                     # noqa: E402
almacen.registrar_paciente("P7", 50, "", 0, 0, 0, "", 1)
verificar("sin proceso activo, el servicio no figura como activo", not servicio.activo())
hilo, detener = servicio.iniciar_en_segundo_plano(tg)
escribir(1234, f"/start {almacen.crear_vinculo('P7')}")                  # un paciente nuevo escribe al bot
for _ in range(30):
    if almacen.id_por_destino("telegram", 1234) == "P7":
        break
    time.sleep(0.2)
verificar("el bot de fondo registra al paciente sin intervención", almacen.id_por_destino("telegram", 1234) == "P7")
verificar("el servicio queda activo y evita un segundo proceso", servicio.activo() and servicio.iniciar_en_segundo_plano(tg) is None)
detener.set()

# 7. Errores del canal
try:
    Telegram("TOKEN", "http://127.0.0.1:9").info()
    verificar("un canal caído produce ErrorCanal", False)
except ErrorCanal:
    verificar("un canal caído produce ErrorCanal", True)

servidor.shutdown()
print(f"\n{sum(resultados)}/{len(resultados)} verificaciones correctas")
raise SystemExit(0 if all(resultados) else 1)
