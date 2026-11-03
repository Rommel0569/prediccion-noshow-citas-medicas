"""Genera docs/llamada.xml: las instrucciones (TwiML) de la llamada, con el mensaje y la voz de config/establecimiento.yaml.

La cuenta de prueba de Twilio no deja enviar el mensaje desde el sistema: solo llama a una URL con instrucciones ya publicadas.
Este archivo se publica con GitHub Pages (carpeta docs/) y su dirección se configura como url_llamada.
Ejecutar:  python generar_llamada.py     (luego subir el cambio a GitHub)
"""
from xml.sax.saxutils import escape, quoteattr

import yaml

from noshow.config import RAIZ

cfg = yaml.safe_load((RAIZ / "config" / "establecimiento.yaml").read_text(encoding="utf-8"))
ll = cfg.get("llamada", {})
voz, idioma = ll.get("voz", "Polly.Mia"), ll.get("idioma", "es-MX")
nombre = cfg.get("nombre", "Consulta externa")
lineas = ['<?xml version="1.0" encoding="UTF-8"?>', "<Response>", '  <Pause length="1"/>']
for frase in ll.get("frases", []):
    lineas.append(f"  <Say voice={quoteattr(voz)} language={quoteattr(idioma)}>{escape(frase.format(establecimiento=nombre))}</Say>")
    lineas.append('  <Pause length="1"/>')
lineas.append("</Response>")
destino = RAIZ / "docs" / "llamada.xml"
destino.parent.mkdir(exist_ok=True)
destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
print(f"Escrito {destino}\n")
print(destino.read_text(encoding="utf-8"))
