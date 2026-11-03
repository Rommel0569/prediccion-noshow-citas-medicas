"""Servidores de prueba de Telegram y Twilio (sin red ni credenciales) para las pruebas automáticas."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs

from noshow.contacto.canales import Telegram, Twilio


def iniciar():
    """Devuelve (estado, canales, servidor). `estado` acumula lo enviado y la cola de novedades de los pacientes."""
    estado = SimpleNamespace(enviados=[], cola=[], sms=[], llamadas=[])

    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _responder(self, cuerpo, codigo=200):
            datos = json.dumps(cuerpo).encode()
            self.send_response(codigo); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(datos)

        def do_POST(self):
            crudo = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if "/bot" in self.path:
                datos = json.loads(crudo or b"{}")
                metodo = self.path.rsplit("/", 1)[-1]
                if metodo == "getUpdates":
                    salida = [u for u in estado.cola if u["update_id"] >= datos.get("offset", 0)]
                elif metodo == "sendMessage":
                    estado.enviados.append(datos); salida = {"message_id": len(estado.enviados)}
                elif metodo == "getMe":
                    salida = {"username": "bot_de_prueba", "first_name": "Prueba"}
                else:
                    salida = True
                self._responder({"ok": True, "result": salida})
            else:
                form = {k: v[0] for k, v in parse_qs(crudo.decode()).items()}
                if self.path.endswith("/Messages.json"):
                    estado.sms.append(form)
                else:
                    estado.llamadas.append(form)
                self._responder({"sid": f"SM{len(estado.sms) + len(estado.llamadas)}"}, 201)

    servidor = HTTPServer(("127.0.0.1", 0), Manejador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{servidor.server_port}"
    canales = {"telegram": Telegram("TOKEN", base), "twilio": Twilio("AC1", "tok", "+15005550006", base)}
    return estado, canales, servidor


def escribir(estado, chat, texto=None, callback=None, contacto=None):
    """Simula que un paciente escribe al bot (texto, botón o número compartido)."""
    n = len(estado.cola) + 1
    if contacto is not None:
        estado.cola.append({"update_id": n, "message": {"chat": {"id": chat}, "from": {"id": chat},
                                                          "contact": {"phone_number": contacto, "user_id": chat}}})
    elif texto is not None:
        estado.cola.append({"update_id": n, "message": {"chat": {"id": chat}, "from": {"id": chat}, "text": texto}})
    else:
        estado.cola.append({"update_id": n, "callback_query": {"id": f"cb{n}", "data": callback, "message": {"chat": {"id": chat}}}})
