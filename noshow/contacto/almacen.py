"""Registro persistente (SQLite) de destinatarios, contactos, lista de espera y reasignaciones.

La base vive en datos/operacion.db (fuera del repositorio) y puede cambiarse con la variable NOSHOW_DB.
Solo guarda identificadores anonimizados y el dato de contacto autorizado por el paciente; nunca nombres.
"""
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from ..config import RAIZ

ESQUEMA = """
CREATE TABLE IF NOT EXISTS destinatarios(
  id_paciente TEXT NOT NULL, canal TEXT NOT NULL, destino TEXT NOT NULL, alta TEXT NOT NULL,
  activo INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(id_paciente, canal));
CREATE TABLE IF NOT EXISTS pacientes(
  id_paciente TEXT PRIMARY KEY, edad INTEGER, zona TEXT, subsidio INTEGER DEFAULT 0, hipertension INTEGER DEFAULT 0,
  diabetes INTEGER DEFAULT 0, telefono TEXT, consentimiento INTEGER DEFAULT 0, creado TEXT);
CREATE TABLE IF NOT EXISTS citas(
  id_cita TEXT PRIMARY KEY, id_paciente TEXT NOT NULL, fecha_registro TEXT, fecha_cita TEXT NOT NULL, servicio TEXT,
  turno TEXT, estado TEXT NOT NULL DEFAULT 'agendada', creado TEXT);
CREATE TABLE IF NOT EXISTS conversaciones(
  id_paciente TEXT PRIMARY KEY, estado TEXT, datos TEXT, actualizado TEXT);
CREATE TABLE IF NOT EXISTS vinculos(
  codigo TEXT PRIMARY KEY, id_paciente TEXT NOT NULL, creado TEXT NOT NULL, vence TEXT NOT NULL, usado INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS contactos(
  id INTEGER PRIMARY KEY AUTOINCREMENT, id_cita TEXT, id_paciente TEXT, canal TEXT, tipo TEXT, fecha_cita TEXT,
  creado TEXT, enviado_en TEXT, estado TEXT, respuesta TEXT, respondido_en TEXT, referencia TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS lista_espera(
  id_espera TEXT PRIMARY KEY, id_paciente TEXT NOT NULL, servicio TEXT, ingreso TEXT, estado TEXT DEFAULT 'esperando');
CREATE TABLE IF NOT EXISTS reasignaciones(
  id INTEGER PRIMARY KEY AUTOINCREMENT, id_cita TEXT, fecha_cita TEXT, servicio TEXT, motivo TEXT, id_espera TEXT,
  creado TEXT, estado TEXT);
CREATE TABLE IF NOT EXISTS sistema(clave TEXT PRIMARY KEY, valor TEXT);
"""


def ruta_db():
    return Path(os.getenv("NOSHOW_DB") or RAIZ / "datos" / "operacion.db")


def ahora():
    return datetime.now().isoformat(timespec="seconds")


def _con():
    ruta = ruta_db()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    columnas = {f["name"] for f in con.execute("PRAGMA table_info(destinatarios)").fetchall()}
    if "verificado" not in columnas:        # migración de bases creadas antes de la verificación de teléfono
        con.execute("ALTER TABLE destinatarios ADD COLUMN verificado INTEGER NOT NULL DEFAULT 1")
        con.commit()
    return con


def _ejecutar(sql, args=()):
    con = _con()
    try:
        with con:
            return con.execute(sql, args).lastrowid
    finally:
        con.close()


def _consultar(sql, args=()):
    con = _con()
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def _df(sql, args=()):
    return pd.DataFrame(_consultar(sql, args))


# ------------------------------------------------------------------ destinatarios y vínculos
def registrar_destinatario(id_paciente, canal, destino, verificado=1):
    _ejecutar("INSERT OR REPLACE INTO destinatarios(id_paciente,canal,destino,alta,activo,verificado) VALUES(?,?,?,?,1,?)",
              (str(id_paciente), canal, str(destino), ahora(), int(verificado)))


def verificar_destinatario(id_paciente, canal):
    _ejecutar("UPDATE destinatarios SET verificado=1 WHERE id_paciente=? AND canal=?", (str(id_paciente), canal))


def desactivar_destinatario(id_paciente=None, canal=None, destino=None):
    cond, args = [], []
    for col, v in (("id_paciente", id_paciente), ("canal", canal), ("destino", destino)):
        if v is not None:
            cond.append(f"{col}=?"); args.append(str(v))
    if cond:
        _ejecutar("UPDATE destinatarios SET activo=0 WHERE " + " AND ".join(cond), tuple(args))


def destinatarios_activos():
    """{(id_paciente, canal): destino} de quienes autorizaron el contacto y tienen el canal verificado."""
    return {(r["id_paciente"], r["canal"]): r["destino"]
            for r in _consultar("SELECT * FROM destinatarios WHERE activo=1 AND verificado=1")}


def listar_destinatarios():
    return _df("SELECT id_paciente, canal, destino, alta, activo, verificado FROM destinatarios ORDER BY alta DESC")


def id_por_destino(canal, destino, solo_verificados=True):
    sql = "SELECT id_paciente FROM destinatarios WHERE canal=? AND destino=? AND activo=1"
    r = _consultar(sql + (" AND verificado=1" if solo_verificados else "") + " ORDER BY alta DESC", (canal, str(destino)))
    return r[0]["id_paciente"] if r else None


# ------------------------------------------------------------------ pacientes (admisión)
def registrar_paciente(id_paciente, edad, zona, subsidio, hipertension, diabetes, telefono, consentimiento):
    _ejecutar("INSERT OR REPLACE INTO pacientes(id_paciente,edad,zona,subsidio,hipertension,diabetes,telefono,consentimiento,creado) "
              "VALUES(?,?,?,?,?,?,?,?,?)", (str(id_paciente), int(edad), zona or "", int(subsidio), int(hipertension),
                                            int(diabetes), telefono or "", int(consentimiento), ahora()))


def obtener_paciente(id_paciente):
    r = _consultar("SELECT * FROM pacientes WHERE id_paciente=?", (str(id_paciente),))
    return r[0] if r else None


def telefono_de_paciente(id_paciente):
    """Teléfono registrado en admisión, o el cargado como destinatario de pruebas."""
    p = obtener_paciente(id_paciente)
    if p and p["telefono"]:
        return p["telefono"]
    r = _consultar("SELECT destino FROM destinatarios WHERE id_paciente=? AND canal='telefono' AND activo=1", (str(id_paciente),))
    return r[0]["destino"] if r else None


def datos_pacientes():
    return _df("SELECT * FROM pacientes")


def listar_pacientes():
    """Pacientes registrados con el estado de su vinculación a Telegram."""
    return _df("""SELECT p.id_paciente, p.edad, p.zona, p.telefono, p.consentimiento, p.creado,
                  CASE WHEN d.id_paciente IS NULL THEN 'Sin vincular'
                       WHEN d.verificado=1 THEN 'Verificado' ELSE 'Pendiente de verificación' END AS vinculacion
                  FROM pacientes p LEFT JOIN destinatarios d
                    ON d.id_paciente=p.id_paciente AND d.canal='telegram' AND d.activo=1
                  ORDER BY p.creado DESC""")


def crear_vinculo(id_paciente, dias=7):
    """Código de un solo uso que el establecimiento entrega al paciente para vincular su Telegram."""
    codigo = secrets.token_urlsafe(6)
    _ejecutar("INSERT INTO vinculos(codigo,id_paciente,creado,vence) VALUES(?,?,?,?)",
              (codigo, str(id_paciente), ahora(), (datetime.now() + timedelta(days=dias)).isoformat(timespec="seconds")))
    return codigo


def consumir_vinculo(codigo):
    r = _consultar("SELECT * FROM vinculos WHERE codigo=? AND usado=0", (codigo,))
    if not r or r[0]["vence"] < ahora():
        return None
    _ejecutar("UPDATE vinculos SET usado=1 WHERE codigo=?", (codigo,))
    return r[0]["id_paciente"]


# ------------------------------------------------------------------ contactos
def registrar_contacto(id_cita, id_paciente, canal, tipo, fecha_cita, estado, referencia=None, error=None):
    enviado = ahora() if estado == "enviado" else None
    return _ejecutar(
        "INSERT INTO contactos(id_cita,id_paciente,canal,tipo,fecha_cita,creado,enviado_en,estado,referencia,error) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (str(id_cita), str(id_paciente), canal, tipo, str(fecha_cita)[:10], ahora(), enviado, estado, referencia, error))


def contactos_existentes():
    """Conjunto {(id_cita, tipo)} ya gestionado. Un envío con error se reintenta, hasta 3 veces."""
    hechos = {(r["id_cita"], r["tipo"]) for r in _consultar("SELECT id_cita,tipo FROM contactos WHERE estado!='error'")}
    agotados = _consultar("SELECT id_cita,tipo FROM contactos WHERE estado='error' GROUP BY id_cita,tipo HAVING COUNT(*)>=3")
    return hechos | {(r["id_cita"], r["tipo"]) for r in agotados}


def listar_contactos():
    return _df("SELECT * FROM contactos ORDER BY id DESC")


def pendientes_manuales():
    return _df("SELECT id,id_cita,id_paciente,canal,tipo,fecha_cita,creado,referencia FROM contactos "
               "WHERE estado='pendiente_manual' ORDER BY fecha_cita, id")


def registrar_respuesta(id_cita, respuesta):
    """Respuesta del paciente a su último contacto de la cita (confirmo, cancelo, reprogramo)."""
    _ejecutar("UPDATE contactos SET respuesta=?, respondido_en=? WHERE id=("
              "SELECT MAX(id) FROM contactos WHERE id_cita=? AND estado IN ('enviado','pendiente_manual','realizado'))",
              (respuesta, ahora(), str(id_cita)))
    nuevo = {"confirmo": "confirmada", "cancelo": "cancelada", "reprogramo": "reprogramacion_solicitada"}.get(respuesta)
    if nuevo:
        _ejecutar("UPDATE citas SET estado=? WHERE id_cita=? AND estado IN ('agendada','confirmada','reprogramacion_solicitada')",
                  (nuevo, str(id_cita)))


def registrar_resultado_manual(id_contacto, respuesta):
    """Resultado de una llamada o visita hecha por el personal."""
    _ejecutar("UPDATE contactos SET estado='realizado', enviado_en=COALESCE(enviado_en,?), respuesta=?, respondido_en=? WHERE id=?",
              (ahora(), respuesta, ahora(), int(id_contacto)))


def id_paciente_de_cita(id_cita):
    r = _consultar("SELECT id_paciente FROM contactos WHERE id_cita=? ORDER BY id DESC LIMIT 1", (str(id_cita),))
    return r[0]["id_paciente"] if r else None


# ------------------------------------------------------------------ lista de espera y reasignaciones
def agregar_espera(id_paciente, servicio=""):
    n = _consultar("SELECT COUNT(*) AS n FROM lista_espera")[0]["n"] + 1
    id_espera = f"E{n:04d}"
    _ejecutar("INSERT INTO lista_espera(id_espera,id_paciente,servicio,ingreso,estado) VALUES(?,?,?,?, 'esperando')",
              (id_espera, str(id_paciente), servicio or "", ahora()))
    return id_espera


def listar_espera():
    return _df("SELECT id_espera,id_paciente,servicio,ingreso,estado FROM lista_espera ORDER BY ingreso")


def actualizar_espera(id_espera, estado):
    _ejecutar("UPDATE lista_espera SET estado=? WHERE id_espera=?", (estado, id_espera))


def crear_reasignacion(id_cita, fecha_cita, servicio, motivo, id_espera, estado):
    return _ejecutar("INSERT INTO reasignaciones(id_cita,fecha_cita,servicio,motivo,id_espera,creado,estado) VALUES(?,?,?,?,?,?,?)",
                     (str(id_cita), str(fecha_cita)[:10], servicio or "", motivo, id_espera, ahora(), estado))


def reasignaciones_vigentes():
    """Cupos que ya tienen una oferta vigente o aceptada (no se vuelven a ofrecer)."""
    return {r["id_cita"] for r in _consultar("SELECT id_cita FROM reasignaciones WHERE estado IN ('ofrecida','aceptada','asignada_manual')")}


def listar_reasignaciones():
    return _df("SELECT id,id_cita,fecha_cita,servicio,motivo,id_espera,creado,estado FROM reasignaciones ORDER BY id DESC")


def obtener_reasignacion(id_reasignacion):
    r = _consultar("SELECT * FROM reasignaciones WHERE id=?", (int(id_reasignacion),))
    return r[0] if r else None


def actualizar_reasignacion(id_reasignacion, estado):
    _ejecutar("UPDATE reasignaciones SET estado=? WHERE id=?", (estado, int(id_reasignacion)))


def paciente_de_espera(id_espera):
    r = _consultar("SELECT id_paciente FROM lista_espera WHERE id_espera=?", (id_espera,))
    return r[0]["id_paciente"] if r else None


# ------------------------------------------------------------------ estado del sistema
def leer(clave, defecto=None):
    r = _consultar("SELECT valor FROM sistema WHERE clave=?", (clave,))
    return r[0]["valor"] if r else defecto


def guardar(clave, valor):
    _ejecutar("INSERT OR REPLACE INTO sistema(clave,valor) VALUES(?,?)", (clave, str(valor)))



# ------------------------------------------------------------------ citas
ESTADOS_VIGENTES = ("agendada", "confirmada", "reprogramacion_solicitada")


def agendar_cita(id_paciente, fecha_cita, servicio="", turno="", fecha_registro=None, id_cita=None):
    id_cita = id_cita or f"C{datetime.now():%y%m%d%H%M%S}{secrets.randbelow(900) + 100}"
    _ejecutar("INSERT INTO citas(id_cita,id_paciente,fecha_registro,fecha_cita,servicio,turno,estado,creado) "
              "VALUES(?,?,?,?,?,?, 'agendada', ?)",
              (id_cita, str(id_paciente), str(fecha_registro or datetime.now().date()), str(fecha_cita)[:10],
               servicio or "", turno or "", ahora()))
    return id_cita


def obtener_cita(id_cita):
    r = _consultar("SELECT * FROM citas WHERE id_cita=?", (str(id_cita),))
    return r[0] if r else None


def citas_de_paciente(id_paciente, desde=None, solo_vigentes=True):
    sql, args = "SELECT * FROM citas WHERE id_paciente=?", [str(id_paciente)]
    if desde:
        sql += " AND fecha_cita>=?"; args.append(str(desde)[:10])
    if solo_vigentes:
        sql += " AND estado IN ('agendada','confirmada','reprogramacion_solicitada')"
    return _consultar(sql + " ORDER BY fecha_cita", tuple(args))


def listar_citas():
    return _df("SELECT * FROM citas ORDER BY fecha_cita DESC, creado DESC")


def actualizar_estado_cita(id_cita, estado):
    _ejecutar("UPDATE citas SET estado=? WHERE id_cita=?", (estado, str(id_cita)))


def registrar_asistencia(id_cita, asistio):
    """Resultado real de la cita: alimenta el historial de inasistencias previas del paciente."""
    actualizar_estado_cita(id_cita, "atendida" if asistio else "no_asistio")


# ------------------------------------------------------------------ estado de la conversación
def estado_conversacion(id_paciente):
    r = _consultar("SELECT estado, datos FROM conversaciones WHERE id_paciente=?", (str(id_paciente),))
    return (r[0]["estado"], r[0]["datos"]) if r else (None, None)


def guardar_conversacion(id_paciente, estado, datos=""):
    _ejecutar("INSERT OR REPLACE INTO conversaciones(id_paciente,estado,datos,actualizado) VALUES(?,?,?,?)",
              (str(id_paciente), estado, datos, ahora()))


def limpiar_conversacion(id_paciente):
    _ejecutar("DELETE FROM conversaciones WHERE id_paciente=?", (str(id_paciente),))


def derivar_a_personal(id_paciente, motivo, id_cita=""):
    """El paciente pide hablar con una persona: queda como gestión pendiente del personal."""
    return _ejecutar(
        "INSERT INTO contactos(id_cita,id_paciente,canal,tipo,fecha_cita,creado,estado,referencia) VALUES(?,?,?,?,?,?,?,?)",
        (str(id_cita), str(id_paciente), "personal", "consulta", "", ahora(), "pendiente_manual", motivo[:200]))


