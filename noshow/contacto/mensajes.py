"""Plantillas de mensajes. No incluyen nombres ni datos clínicos: solo fecha, servicio y el establecimiento."""


def _detalle(fecha, servicio):
    f = fecha.strftime("%d/%m/%Y") if hasattr(fecha, "strftime") else str(fecha)[:10]
    return f"el {f}" + (f" en {servicio}" if servicio else "")


def recordatorio(fecha, servicio, establecimiento):
    return (f"{establecimiento}: le recordamos su cita médica {_detalle(fecha, servicio)}. "
            "Si no podrá asistir, avísenos para ofrecer su cupo a otro paciente.")


def confirmacion(fecha, servicio, establecimiento):
    return (f"{establecimiento}: tiene una cita médica {_detalle(fecha, servicio)}. "
            "Por favor confirme su asistencia. Si no puede asistir, cancele o reprograme para liberar el cupo.")


def llamada(fecha, servicio, establecimiento):
    return (f"Hola, le llamamos de {establecimiento}. Le recordamos su cita médica {_detalle(fecha, servicio)}. "
            "Por favor comuníquese con el establecimiento si no podrá asistir. Gracias.")


def oferta_cupo(fecha, servicio, establecimiento):
    return (f"{establecimiento}: se liberó un cupo {_detalle(fecha, servicio)} y usted está en lista de espera. "
            "¿Desea tomarlo?")


def botones_cita(id_cita):
    return [[("Confirmar asistencia", f"r|{id_cita}|c")],
            [("Cancelar", f"r|{id_cita}|x"), ("Reprogramar", f"r|{id_cita}|p")]]


def botones_oferta(id_reasignacion):
    return [[("Tomar el cupo", f"a|{id_reasignacion}|s"), ("No, gracias", f"a|{id_reasignacion}|n")]]


BIENVENIDA = ("Quedó registrado para recibir recordatorios de sus citas médicas por este chat. "
              "No se enviarán datos clínicos. Para dejar de recibirlos, escriba /baja.")
VERIFICAR = ("Su chat quedó asociado a su registro en el establecimiento (teléfono terminado en {fin}). "
             "Para confirmar que es usted, pulse el botón de abajo y comparta su número de Telegram.")
BOTON_CONTACTO = "Compartir mi número"
VERIFICADO = ("Número verificado. Recibirá aquí los recordatorios de sus citas médicas; no se enviarán datos clínicos. "
              "Para dejar de recibirlos, escriba /baja.")
NO_COINCIDE = ("El número compartido no coincide con el registrado en el establecimiento, por lo que no se activaron los avisos. "
               "Acérquese a admisión para actualizar sus datos.")
CONTACTO_AJENO = "Por seguridad, comparta su propio número con el botón."
SIN_CODIGO = ("Para recibir recordatorios, use el enlace o el código QR que le entregó el establecimiento de salud al registrarse.")
CODIGO_INVALIDO = ("El enlace no es válido o ya venció. Solicite uno nuevo en el establecimiento de salud.")
AYUDA = ("Este chat envía recordatorios de sus citas médicas. Use los botones de cada recordatorio para confirmar, cancelar o "
         "reprogramar. Para otras consultas, comuníquese con el establecimiento. /baja para dejar de recibir avisos.")
DESCRIPCION = ("Recordatorios de citas médicas: confirme, cancele o reprograme su cita desde aquí. "
               "Para registrarse, use el enlace o el QR que le entrega el establecimiento de salud.")
BAJA = "Listo, no recibirá más recordatorios por este chat."
GRACIAS = {"c": "Asistencia confirmada. Gracias.", "x": "Cita cancelada. El cupo se ofrecerá a otro paciente.",
           "p": "Solicitud de reprogramación registrada. El establecimiento se comunicará con usted."}
RESPUESTA = {"c": "confirmo", "x": "cancelo", "p": "reprogramo"}
