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
def registrar_destinatario(id_paciente, canal, destino):
    _ejecutar("INSERT OR REPLACE INTO destinatarios(id_paciente,canal,destino,alta,activo) VALUES(?,?,?,?,1)",
              (str(id_paciente), canal, str(destino), ahora()))


def desactivar_destinatario(id_paciente=None, canal=None, destino=None):
    cond, args = [], []
    for col, v in (("id_paciente", id_paciente), ("canal", canal), ("destino", destino)):
        if v is not None:
            cond.append(f"{col}=?"); args.append(str(v))
    if cond:
        _ejecutar("UPDATE destinatarios SET activo=0 WHERE " + " AND ".join(cond), tuple(args))


def destinatarios_activos():
    """{(id_paciente, canal): destino} de quienes autorizaron el contacto."""
    return {(r["id_paciente"], r["canal"]): r["destino"]
            for r in _consultar("SELECT * FROM destinatarios WHERE activo=1")}


def listar_destinatarios():
    return _df("SELECT id_paciente, canal, destino, alta, activo FROM destinatarios ORDER BY alta DESC")


def id_por_destino(canal, destino):
    r = _consultar("SELECT id_paciente FROM destinatarios WHERE canal=? AND destino=? AND activo=1", (canal, str(destino)))
    return r[0]["id_paciente"] if r else None


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
    """Conjunto {(id_cita, tipo)} ya gestionado (no cuenta los envíos con error)."""
    return {(r["id_cita"], r["tipo"]) for r in _consultar("SELECT id_cita,tipo FROM contactos WHERE estado!='error'")}


def listar_contactos():
    return _df("SELECT * FROM contactos ORDER BY id DESC")


def pendientes_manuales():
    return _df("SELECT id,id_cita,id_paciente,canal,tipo,fecha_cita,creado FROM contactos "
               "WHERE estado='pendiente_manual' ORDER BY fecha_cita, id")


def registrar_respuesta(id_cita, respuesta):
    """Respuesta del paciente a su último contacto de la cita (confirmo, cancelo, reprogramo)."""
    _ejecutar("UPDATE contactos SET respuesta=?, respondido_en=? WHERE id=("
              "SELECT MAX(id) FROM contactos WHERE id_cita=? AND estado IN ('enviado','pendiente_manual','realizado'))",
              (respuesta, ahora(), str(id_cita)))


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
