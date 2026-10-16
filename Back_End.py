import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# La base se busca junto a este archivo, sin importar desde qué carpeta
# se ejecute el programa (así nunca crea una cooperadora.db vacía por error).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUTA_DB = os.path.join(BASE_DIR, 'cooperadora.db')

MONTO_FIJO = 4000.0   # Monto actual de la cooperadora

# Valores permitidos (tienen que coincidir con los <option> del formulario)
TIPOS_VALIDOS = {'Alumno', 'Docente', 'No docente'}
CARRERAS_VALIDAS = {
    'Analista de Sistemas', 'Desarrollo de Software',
    'Ciencia de Datos e IA', 'IoT', 'Seguridad e Higiene',
}
ANIOS_VALIDOS = {'1°', '2°', '3°'}


def conectar_db():
    print(f"--> Conectando a la base de datos en: {RUTA_DB}")
    return sqlite3.connect(RUTA_DB)


def error(mensaje, codigo=400):
    return jsonify(ok=False, error=mensaje), codigo


def preparar_db():
    """Deja la base lista para las estadísticas. Se puede ejecutar siempre:
    si ya está todo en orden, no cambia nada.

    - contribuyente: guarda los datos ACTUALES de cada persona.
    - cuota: guarda además una "foto" del tipo, carrera y año que tenía la
      persona EN EL MOMENTO de pagar. Así el historial no cambia aunque
      después pase de año o de carrera."""
    if not os.path.exists(RUTA_DB):
        print(f"AVISO: no se encontró {RUTA_DB}; se crea una base nueva.")

    with closing(conectar_db()) as con:
        con.execute('''
            CREATE TABLE IF NOT EXISTS contribuyente (
                dni TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                apellido TEXT NOT NULL,
                mail TEXT NOT NULL,
                tipo TEXT NOT NULL,
                carrera TEXT,
                anio TEXT
            )''')
        con.execute('''
            CREATE TABLE IF NOT EXISTS cuota (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                monto REAL NOT NULL,
                contribuyente_id TEXT NOT NULL,
                tipo TEXT,
                carrera TEXT,
                anio TEXT,
                FOREIGN KEY (contribuyente_id) REFERENCES contribuyente(dni)
            )''')

        # Bases creadas antes de este cambio: agregar las columnas que falten
        existentes = {fila[1] for fila in con.execute('PRAGMA table_info(cuota)')}
        for columna in ('tipo', 'carrera', 'anio'):
            if columna not in existentes:
                con.execute(f'ALTER TABLE cuota ADD COLUMN {columna} TEXT')

        # Pagos viejos sin "foto": se completan con los datos actuales de la persona
        con.execute('''
            UPDATE cuota SET
                tipo    = (SELECT tipo    FROM contribuyente WHERE dni = cuota.contribuyente_id),
                carrera = (SELECT carrera FROM contribuyente WHERE dni = cuota.contribuyente_id),
                anio    = (SELECT anio    FROM contribuyente WHERE dni = cuota.contribuyente_id)
            WHERE tipo IS NULL
        ''')
        con.commit()


preparar_db()


# Ruta 1: muestra el formulario
@app.route('/')
def index():
    return render_template('formularioFinal.html')


# Ruta 2: recibe los datos y los guarda
@app.route('/registrar', methods=['POST'])
def registrar():
    nombre = (request.form.get('nombre') or '').strip()
    apellido = (request.form.get('apellido') or '').strip()
    dni = (request.form.get('dni') or '').strip()
    email = (request.form.get('email') or '').strip()
    tipo = (request.form.get('tipo') or '').strip()
    carrera = (request.form.get('carrera') or '').strip() or None   # None si no viene
    anio = (request.form.get('anio') or '').strip() or None

    # ---- Validación en el servidor (el navegador se puede saltear) ----
    if not (nombre and apellido and email):
        return error('Completá nombre, apellido y email.')
    if not re.fullmatch(r'\d{7,8}', dni):
        return error('El DNI debe tener 7 u 8 números.')
    if tipo not in TIPOS_VALIDOS:
        return error('Elegí un tipo de contribuyente válido.')

    if tipo == 'Alumno':
        if carrera not in CARRERAS_VALIDAS or anio not in ANIOS_VALIDOS:
            return error('Elegí la carrera y el año.')
    else:
        # Docentes y no docentes: nunca se guardan carrera ni año
        carrera = None
        anio = None

    fecha_actual = datetime.now().strftime('%Y-%m-%d')

    try:
        with closing(conectar_db()) as conexion:
            cursor = conexion.cursor()

            # 1. Alta: si el DNI no existe, se crea con todos sus datos
            cursor.execute('''
                INSERT OR IGNORE INTO contribuyente
                    (dni, nombre, apellido, mail, tipo, carrera, anio)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (dni, nombre, apellido, email, tipo, carrera, anio))

            # 2. Si ya existía, se actualiza SOLO tipo, carrera y año (lo que cambia
            #    con el tiempo). Nombre, apellido y mail no se pisan: así un DNI
            #    mal tipeado no puede pisar los datos de otra persona.
            cursor.execute('''
                UPDATE contribuyente SET tipo = ?, carrera = ?, anio = ?
                WHERE dni = ?
            ''', (tipo, carrera, anio, dni))

            # 3. Pago, con la "foto" del tipo/carrera/año de este momento
            cursor.execute('''
                INSERT INTO cuota
                    (fecha, monto, contribuyente_id, tipo, carrera, anio)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (fecha_actual, MONTO_FIJO, dni, tipo, carrera, anio))

            conexion.commit()

        print(f"¡Éxito! Pago guardado para: {nombre} {apellido} (DNI: {dni}, {tipo})")
        return jsonify(ok=True, mensaje='¡Registrado con éxito!')

    except Exception as e:
        print(f"Error al guardar en la base de datos: {e}")
        return error('Hubo un error al registrar. Intentá de nuevo.', 500)


if __name__ == '__main__':
    app.run(debug=True)
