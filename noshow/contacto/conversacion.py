"""Conversación del bot con el paciente (Telegram): comprende español coloquial y actúa sobre sus citas reales.

Es un motor propio, gratuito y sin servicios externos: normaliza el texto, reconoce la intención, recuerda el contexto
(por ejemplo, cuál de varias citas quiere cancelar) y solo ejecuta acciones sobre los datos del propio paciente.
Opcionalmente puede apoyarse en un modelo de lenguaje gratuito (OpenAI-compatible, p. ej. Ollama local) SOLO para
conversación fuera de tema; nunca para ejecutar acciones.
"""
import json
import re
import unicodedata
from datetime import date, datetime

import requests
import yaml

from ..config import RAIZ
from . import almacen, mensajes

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
EMERGENCIA = "Si es una emergencia, llame al 106 (SAMU) o acuda de inmediato al servicio de emergencia más cercano."
SIN_DATO = "Para ese dato, comuníquese con admisión del establecimiento."
ABREVIATURAS = {"q": "que", "k": "que", "xq": "porque", "pq": "porque", "x": "por", "ola": "hola", "kiero": "quiero",
                "tmb": "tambien", "tb": "tambien", "pls": "por favor", "plis": "por favor", "dnd": "donde",
                "cm": "como", "grax": "gracias", "gracs": "gracias", "ps": "pues", "xfa": "por favor", "xfavor": "por favor"}


# ------------------------------------------------------------------ utilidades de texto
def normalizar(texto):
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"(.)\1{2,}", r"\1", t)                      # "holaaa" -> "hola"
    t = re.sub(r"[^a-z0-9/ ]", " ", t)
    palabras = [ABREVIATURAS.get(p, p) for p in t.split()]
    return " ".join(palabras)


def fecha_larga(f):
    f = datetime.fromisoformat(str(f)[:10]).date() if not isinstance(f, date) else f
    return f"{DIAS[f.weekday()]} {f.day} de {MESES[f.month - 1]}"


def info():
    """Datos del establecimiento que el paciente puede consultar (config/establecimiento.yaml)."""
    ruta = RAIZ / "config" / "establecimiento.yaml"
    try:
        return yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _descripcion(c):
    turno = f" ({c['turno'].lower()})" if c.get("turno") else ""
    serv = f" · {c['servicio']}" if c.get("servicio") else ""
    estado = {"confirmada": " — confirmada", "reprogramacion_solicitada": " — reprogramación solicitada"}.get(c["estado"], "")
    return f"{fecha_larga(c['fecha_cita'])}{serv}{turno}{estado}"


def _respuesta(texto, botones=None, accion=None):
    return {"texto": texto, "botones": botones, "accion": accion}


# ------------------------------------------------------------------ intenciones (sobre texto normalizado)
PATRONES = [
    ("urgencia", r"\b(emergencia|urgencia|urgente|me siento muy mal|dolor (muy )?fuerte|no puedo respirar|me falta el aire|"
                 r"sangr\w+|desmay\w+|convuls\w+|infarto|accidente|me duele mucho|estoy grave|me muero)\b"),
    ("baja", r"\b(dejar de recibir|no quiero (recibir )?(mas )?(mensajes|avisos|recordatorios)|ya no quiero recibir|darme de baja|desuscrib\w+|no me escriban|"
             r"no me envien mas|baja)\b"),
    ("cancelar", r"\b(cancel\w*|anul\w*|no voy( a ir)?|no podre|no puedo (ir|asistir|llegar|acudir)|no asistire|ya no (voy|quiero)|"
                 r"no ire|no podria (ir|asistir))\b"),
    ("reprogramar", r"\b(reprogram\w*|reagend\w*|re agend\w*|cambiar|cambio de|mover|otra (fecha|hora|dia)|otro (dia|horario|fecha)|"
                    r"posponer|adelantar|pasar mi cita)\b"),
    ("confirmar", r"\b(confirm\w*|voy a ir|ire|asistire|si voy|alli estare|ahi estare|estare ahi|cuente conmigo|ahi nos vemos)\b"),
    ("horario", r"\b(horario|a que hora (atienden|abren|cierran)|hasta que hora|dias de atencion|atienden los)\b"),
    ("mis_citas", r"\b(mi cita|mis citas|cuando (es|tengo|me toca)|que dia|que fecha|a que hora|proxima cita|tengo cita|"
                  r"fecha de mi|hora de mi|que citas|ver mi cita|recordar\w* mi cita|con que doctor|que especialidad)\b"),
    ("direccion", r"\b(donde (queda|esta|es|estan)|direccion|ubicacion|como llego|como llegar|como se llega)\b"),
    ("documentos", r"\b(que (debo |tengo que |necesito )?(llevar|traer|presentar)|documentos?|dni|carnet|requisitos|que llevo)\b"),
    ("costo", r"\b(cuanto (cuesta|cobran|pago|es)|costo|precio|tarifa|pagar|es gratis)\b"),
    ("personal", r"\b(hablar con (alguien|una persona|un asesor|el personal|admision|un humano)|persona real|operador|asesor|"
                 r"humano|llamenme|llamar(me)?|comunicarme con|telefono|numero de contacto|admision)\b"),
    ("clinico", r"\b(resultados?|receta|medicamentos?|medicina|diagnostico|analisis|examen(es)?|dosis|tratamiento|sintomas?|"
                r"me duele|dolor|fiebre|enfermo)\b"),
    ("ayuda", r"\b(ayuda|que (puedes|haces|puedo hacer)|opciones|menu|como funciona|para que sirves)\b"),
    ("gracias", r"\b(gracias|te agradezco|chau|adios|hasta luego|nos vemos|listo|perfecto|ok)\b"),
    ("saludo", r"\b(hola|holi|buen(os|as)? (dias|tardes|noches)|buenas|hey|que tal|saludos|alo)\b"),
]
SI = re.compile(r"^(si|sii|claro|ok|dale|correcto|afirmativo|por supuesto|esta bien|de acuerdo|seguro|confirmo|si por favor)\b")
NO = re.compile(r"^(no|nop|negativo|mejor no|todavia no|no gracias|dejalo|no cancelar)\b")
ORDINALES = {"primera": 1, "primero": 1, "uno": 1, "segunda": 2, "segundo": 2, "dos": 2, "tercera": 3, "tercero": 3, "tres": 3,
             "ultima": -1, "ultimo": -1, "proxima": 1, "proximo": 1}


def _intencion(t):
    for nombre, patron in PATRONES:
        if re.search(patron, t):
            return nombre
    return None


def _elegir_cita(t, citas):
    """Cita a la que se refiere el texto: número, ordinal o fecha (dd/mm). None si no se puede decidir."""
    m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", t)
    if m:
        d, mes = int(m.group(1)), int(m.group(2))
        for c in citas:
            f = datetime.fromisoformat(c["fecha_cita"]).date()
            if f.day == d and f.month == mes:
                return c
    m = re.fullmatch(r"(?:la |el |numero |n )?(\d{1,2})", t.strip())
    if m and 1 <= int(m.group(1)) <= len(citas):
        return citas[int(m.group(1)) - 1]
    for palabra, n in ORDINALES.items():
        if re.search(rf"\b{palabra}\b", t):
            return citas[n - 1] if n > 0 else citas[-1]
    for c in citas:                                     # "la de cardiologia"
        if c.get("servicio") and normalizar(c["servicio"]) in t:
            return c
    return None


# ------------------------------------------------------------------ acciones sobre las citas del paciente
def _hacer_confirmar(id_paciente, c):
    almacen.registrar_respuesta(c["id_cita"], "confirmo")
    almacen.limpiar_conversacion(id_paciente)
    extra = info().get("documentos")
    return _respuesta(f"Listo, dejé confirmada su cita del {_descripcion({**c, 'estado': 'agendada'})}. ¡Lo esperamos!"
                      + (f" Recuerde llevar: {extra}" if extra else ""))


def _pedir_cancelacion(id_paciente, c):
    almacen.guardar_conversacion(id_paciente, "confirmar_cancelacion", json.dumps({"id_cita": c["id_cita"]}))
    return _respuesta(f"¿Desea cancelar su cita del {_descripcion({**c, 'estado': 'agendada'})}? Su cupo se ofrecerá a otro "
                      "paciente en espera. Responda sí o no.",
                      [[("Sí, cancelar", f"q|{c['id_cita']}|s"), ("No, mantener", f"q|{c['id_cita']}|n")]])


def resolver_cancelacion(id_paciente, id_cita, si):
    """Respuesta (texto) a la confirmación de cancelación: por texto o por los botones."""
    c = almacen.obtener_cita(id_cita)
    almacen.limpiar_conversacion(id_paciente)
    if not c or c["id_paciente"] != str(id_paciente):
        return _respuesta("No encontré esa cita.")
    if not si:
        return _respuesta("Perfecto, mantengo su cita. ¡Lo esperamos!")
    almacen.registrar_respuesta(id_cita, "cancelo")
    return _respuesta("Su cita fue cancelada. Gracias por avisar: así otro paciente podrá usar ese cupo. "
                      "Si desea una nueva fecha, escriba «reprogramar» y aviso al personal.")


def _hacer_reprogramar(id_paciente, c):
    almacen.registrar_respuesta(c["id_cita"], "reprogramo")
    almacen.derivar_a_personal(id_paciente, f"Solicita reprogramar la cita del {c['fecha_cita']} ({c.get('servicio') or 'sin especialidad'})",
                               c["id_cita"])
    almacen.limpiar_conversacion(id_paciente)
    return _respuesta(f"Anoté su solicitud para reprogramar la cita del {fecha_larga(c['fecha_cita'])}. El personal de admisión "
                      "se comunicará con usted para acordar la nueva fecha.")


ACCIONES = {"confirmar": _hacer_confirmar, "cancelar": _pedir_cancelacion, "reprogramar": _hacer_reprogramar}
VERBO = {"confirmar": "confirmar", "cancelar": "cancelar", "reprogramar": "reprogramar"}


def _con_cita(id_paciente, accion, t, hoy):
    citas = almacen.citas_de_paciente(id_paciente, desde=hoy)
    if not citas:
        return _respuesta("No tengo citas próximas registradas a su nombre. Si cree que es un error, escriba «personal» y aviso a admisión.")
    elegida = citas[0] if len(citas) == 1 else _elegir_cita(t, citas)
    if elegida:
        return ACCIONES[accion](id_paciente, elegida)
    almacen.guardar_conversacion(id_paciente, f"elegir:{accion}", json.dumps({"ids": [c["id_cita"] for c in citas]}))
    lista = "\n".join(f"{i}) {_descripcion(c)}" for i, c in enumerate(citas, 1))
    return _respuesta(f"Tiene {len(citas)} citas próximas. ¿Cuál desea {VERBO[accion]}?\n{lista}\nResponda con el número.")


# ------------------------------------------------------------------ modelo de lenguaje gratuito (opcional, solo conversación)
def _llm_libre(texto):
    """Respuesta de un LLM OpenAI-compatible configurado (p. ej. Ollama local), o None. Nunca ejecuta acciones."""
    try:
        cfg = yaml.safe_load((RAIZ / "config" / "canales.local.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    llm = cfg.get("llm_libre")
    if not llm or not llm.get("base_url") or not llm.get("modelo"):
        return None
    sistema = ("Eres el asistente virtual de citas médicas de un establecimiento de salud en Perú. Responde en español, breve y "
               "amable, solo sobre citas, horarios y orientación administrativa. No des consejos médicos ni diagnósticos. "
               "Si piden algo fuera de eso, di con cortesía que solo puedes ayudar con sus citas. No inventes datos.")
    try:
        r = requests.post(llm["base_url"].rstrip("/") + "/chat/completions", timeout=20,
                          headers={"Authorization": f"Bearer {llm.get('api_key', '')}"},
                          json={"model": llm["modelo"], "max_tokens": 200,
                                "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": texto[:500]}]})
        return r.json()["choices"][0]["message"]["content"].strip()
    except (requests.RequestException, KeyError, ValueError, IndexError):
        return None


# ------------------------------------------------------------------ punto de entrada
def responder(id_paciente, texto, hoy=None):
    """Respuesta del bot a un mensaje libre del paciente: {'texto', 'botones', 'accion'}."""
    hoy = hoy or date.today()
    t = normalizar(texto)
    estado, datos = almacen.estado_conversacion(id_paciente)
    datos = json.loads(datos) if datos else {}

    if _intencion(t) == "urgencia":
        almacen.derivar_a_personal(id_paciente, "Posible urgencia: " + (texto or "")[:120])
        return _respuesta(f"{EMERGENCIA} Este chat no atiende urgencias. Ya avisé al personal.")

    # contexto pendiente: confirmación de cancelación o elección entre varias citas
    if estado == "confirmar_cancelacion":
        if SI.match(t):
            return resolver_cancelacion(id_paciente, datos["id_cita"], True)
        if NO.match(t):
            return resolver_cancelacion(id_paciente, datos["id_cita"], False)
    elif estado and estado.startswith("elegir:"):
        citas = [c for c in (almacen.obtener_cita(i) for i in datos.get("ids", [])) if c]
        elegida = _elegir_cita(t, citas) if citas else None
        if elegida:
            return ACCIONES[estado.split(":", 1)[1]](id_paciente, elegida)

    intencion = _intencion(t)
    e = info()
    if intencion in ("confirmar", "cancelar", "reprogramar"):
        return _con_cita(id_paciente, intencion, t, hoy)
    if intencion == "baja":
        return _respuesta("Entendido, dejará de recibir avisos por este chat. Si cambia de opinión, solicite un nuevo enlace en admisión.",
                          accion="baja")
    almacen.limpiar_conversacion(id_paciente)
    if intencion == "mis_citas":
        citas = almacen.citas_de_paciente(id_paciente, desde=hoy)
        if not citas:
            return _respuesta("No tengo citas próximas registradas a su nombre. Si cree que es un error, escriba «personal» y aviso a admisión.")
        if len(citas) == 1:
            c = citas[0]
            return _respuesta(f"Su próxima cita es el {_descripcion(c)}.", mensajes.botones_cita(c["id_cita"]))
        return _respuesta("Sus próximas citas:\n" + "\n".join(f"{i}) {_descripcion(c)}" for i, c in enumerate(citas, 1)))
    if intencion == "horario":
        return _respuesta(f"Horario de atención: {e['horario']}" if e.get("horario") else SIN_DATO)
    if intencion == "direccion":
        return _respuesta(f"Estamos en: {e['direccion']}" if e.get("direccion") else SIN_DATO)
    if intencion == "documentos":
        return _respuesta(f"Para su cita lleve: {e['documentos']}" if e.get("documentos") else SIN_DATO)
    if intencion == "costo":
        return _respuesta(e["costo"] if e.get("costo") else "Sobre costos y pagos, consulte en admisión del establecimiento.")
    if intencion == "personal":
        almacen.derivar_a_personal(id_paciente, "Pide hablar con una persona: " + (texto or "")[:120])
        extra = f" También puede llamar al {e['telefono']}." if e.get("telefono") else ""
        return _respuesta("Listo, avisé al personal de admisión para que se comuniquen con usted." + extra)
    if intencion == "clinico":
        almacen.derivar_a_personal(id_paciente, "Consulta clínica/administrativa: " + (texto or "")[:120])
        return _respuesta("Con temas médicos (resultados, recetas, síntomas) no puedo ayudarle por aquí: eso lo ve su médico. "
                          f"Ya avisé al personal para que se comuniquen con usted. {EMERGENCIA}")
    if intencion == "ayuda":
        return _respuesta("Puedo ayudarle con su cita: ver cuándo es, confirmarla, cancelarla o pedir reprogramarla. También le "
                          "informo horario, dirección y qué llevar, o aviso al personal si necesita hablar con alguien. "
                          "Escríbame con confianza, como en un chat normal.")
    if intencion == "gracias":
        return _respuesta("¡Con gusto! Que tenga un buen día.")
    if intencion == "saludo":
        hora = datetime.now().hour
        momento = "Buenos días" if hora < 12 else "Buenas tardes" if hora < 19 else "Buenas noches"
        return _respuesta(f"{momento}. Soy el asistente de citas del establecimiento. ¿En qué puedo ayudarle? "
                          "Puedo ver su cita, confirmarla, cancelarla o reprogramarla.")

    # no entendió: ofrece opciones, usa el LLM libre si existe y, tras dos intentos, pasa al personal
    fallos = int(datos.get("fallos", 0)) + 1 if estado == "no_entendi" else 1
    libre = _llm_libre(texto)
    if libre:
        almacen.guardar_conversacion(id_paciente, "no_entendi", json.dumps({"fallos": fallos}))
        return _respuesta(libre)
    if fallos >= 2:
        almacen.derivar_a_personal(id_paciente, "El bot no logró entender: " + (texto or "")[:120])
        almacen.limpiar_conversacion(id_paciente)
        return _respuesta("Parece que no estoy logrando ayudarle bien. Ya avisé al personal para que se comuniquen con usted.")
    almacen.guardar_conversacion(id_paciente, "no_entendi", json.dumps({"fallos": fallos}))
    return _respuesta("No estoy seguro de haber entendido. Puedo ayudarle a ver su cita, confirmarla, cancelarla o reprogramarla; "
                      "también dar horario, dirección y qué llevar, o avisar al personal. ¿Qué necesita?")

