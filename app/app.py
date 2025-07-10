import os
from datetime import datetime, timedelta, timezone
import pytz

from flask import Flask, render_template, request, jsonify, abort, redirect, url_for
import pandas as pd
from sqlalchemy import create_engine, text

# --------------------------------------------------------------------------
# Config & helpers
# --------------------------------------------------------------------------
UTC = timezone.utc
LOCAL_TZ = pytz.timezone(os.getenv("TZ", "America/Argentina/Buenos_Aires"))

def localize(ts):
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(LOCAL_TZ)

_engine = None
def get_engine():
    global _engine
    if _engine is None:
        host = os.getenv("MARIADB_HOST")
        user = os.getenv("DB_USER")
        password = os.getenv("DB_PASS")
        db = os.getenv("MYSQL_DB")
        _engine = create_engine(
            f"mysql+pymysql://{user}:{password}@{host}/{db}?charset=utf8mb4",
            pool_pre_ping=True,
        )
        with _engine.connect() as c:
            c.execute(text("SET collation_connection = 'utf8mb4_unicode_ci'"))
    return _engine

# --------------------------------------------------------------------------
# Flask app
# --------------------------------------------------------------------------
app = Flask(__name__)

@app.route("/")
def index():
    eng = get_engine()

    initial_date = request.args.get("date")
    initial_turno = request.args.get("turno")

    initial_start = request.args.get("start")
    initial_end = request.args.get("end")

    # Caso 1: Si se proporciona un rango personalizado (start y end), priorizamos este.
    if initial_start and initial_end:
        # Limpiamos initial_date y initial_turno para evitar conflictos con el rango.
        # Se establecen a None temporalmente para luego convertirlos a ""
        initial_date = None
        initial_turno = None
    # Caso 2: Si no se proporciona fecha/turno específicos NI un rango, volvemos al comportamiento por defecto.
    # Es decir, buscar la última fecha y turno con datos en la Vista.
    elif not initial_date and not initial_turno:
        with eng.connect() as c:
            last = c.execute(text("""
                SELECT fecha, Turno
                FROM Vista
                ORDER BY fecha DESC, FIELD(Turno,'TM','TT','TN')
                LIMIT 1
            """)).mappings().first()

        if last:
            initial_date = last["fecha"].strftime("%Y-%m-%d")
            initial_turno = last["Turno"]
        else:
            # Fallback si la Vista está vacía, usa la fecha actual y el turno 'TM'.
            initial_date = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
            initial_turno = 'TM'
        
        # Aseguramos que los parámetros de rango estén explícitamente en cadenas vacías
        # cuando se usa una fecha/turno único o se defaultea a una fecha/turno.
        initial_start = ""
        initial_end = ""
    # Caso 3: Si se proporciona una fecha/turno específico (pero no un rango).
    else:
        # Aseguramos que los parámetros de rango estén explícitamente en cadenas vacías.
        initial_start = ""
        initial_end = ""

    # Finalmente, aseguramos que cualquier variable que sea None se convierta a una cadena vacía
    # antes de pasarla a la plantilla, para facilitar el manejo en JavaScript.
    if initial_date is None:
        initial_date = ""
    if initial_turno is None:
        initial_turno = ""
    if initial_start is None:
        initial_start = ""
    if initial_end is None:
        initial_end = ""

    return render_template(
        "index.html",
        initial_date=initial_date,
        initial_turno=initial_turno,
        initial_start=initial_start, # Se pasan a la plantilla como "" si no están presentes
        initial_end=initial_end      # Se pasan a la plantilla como "" si no están presentes
    )

# --- Configuración de zona horaria ---
argentina_tz = pytz.timezone('America/Argentina/Buenos_Aires')
utc_tz = pytz.timezone('UTC')

# --------------------------------------------------------------------------
# grafico torta 
# --------------------------------------------------------------------------
@app.route("/api/vista")
def api_vista():
    eng = get_engine()
    args = request.args

    # Modo nuevo: consulta libre por rango de fechas y horas
    if "start" in args and "end" in args:
        try:
            start = datetime.fromisoformat(args["start"])
            end   = datetime.fromisoformat(args["end"])
        except ValueError:
            abort(400, "Formato de fecha/hora inválido")

        # Asegurar zona horaria local y convertir a UTC
        if start.tzinfo is None:
            start = argentina_tz.localize(start)
        if end.tzinfo is None:
            end = argentina_tz.localize(end)

        start_utc = start.astimezone(utc_tz)
        end_utc   = end.astimezone(utc_tz)

        label = f"{start.strftime('%Y-%m-%d %H:%M')} \u2192 {end.strftime('%Y-%m-%d %H:%M')}"
    
    else:
        # Modo tradicional: por fecha y turno
        selected_date = args.get("date")
        selected_turno = args.get("turno")
        shifts = {
            'TM': ("07:00:00", "15:00:00"),
            'TT': ("15:00:00", "23:00:00"),
            'TN': ("23:00:00", "07:00:00")
        }

        if not selected_date or not selected_turno or selected_turno not in shifts:
            abort(400, "Faltan fecha y turno válidos")

        d = datetime.strptime(selected_date, "%Y-%m-%d").date()
        start_naive = datetime.combine(d, datetime.strptime(shifts[selected_turno][0], "%H:%M:%S").time())
        end_day = d + timedelta(days=1) if selected_turno == 'TN' else d
        end_naive = datetime.combine(end_day, datetime.strptime(shifts[selected_turno][1], "%H:%M:%S").time())

        start_local = argentina_tz.localize(start_naive)
        end_local   = argentina_tz.localize(end_naive)
        start_utc = start_local.astimezone(utc_tz)
        end_utc   = end_local.astimezone(utc_tz)
        label = f"{selected_date} - Turno {selected_turno}"

    # Consulta SQL entre start_utc y end_utc
    raw_df = pd.read_sql(
        text("""
            SELECT m, mOn, mWo
            FROM registros
            WHERE time >= :s AND time < :e
        """),
        eng, params={"s": start_utc, "e": end_utc}
    )

    if raw_df.empty:
        return jsonify({"data": [], "label": label})

    results = []
    for machine_id, df_m in raw_df.groupby('m'):
        total = len(df_m)
        on_count = int(df_m['mOn'].sum())
        off_count = total - on_count
        wo_count = int(df_m[df_m['mOn'] == 1]['mWo'].sum())
        nwo_count = on_count - wo_count

        results.append({
            "m": machine_id,
            "N": total,
            "On": on_count,
            "Off": off_count,
            "Prod": wo_count,
            "NoProd": nwo_count
        })

    return jsonify({
        "data": results,
        "label": label
    })
    
    
# --------------------------------------------------------------------------
# serie temporal por máquina 
# --------------------------------------------------------------------------
@app.route("/api/maquina/<int:m>")
def api_maquina(m):
    date  = request.args.get("date")
    turno = request.args.get("turno")
    start_str = request.args.get("start")
    end_str   = request.args.get("end")

    # Si se proporcionan parámetros start y end → consulta personalizada
    if start_str and end_str:
        try:
            start_local = datetime.fromisoformat(start_str)
            end_local   = datetime.fromisoformat(end_str)
            
            # Localizar la fecha/hora sin información de zona horaria como Argentina
            if start_local.tzinfo is None:
                start_local = argentina_tz.localize(start_local)
            if end_local.tzinfo is None:
                end_local = argentina_tz.localize(end_local)

        except Exception as e:
            abort(400, f"Formato de fecha inválido: {e}")
    elif date and turno:
        shifts = {
            'TM': ("07:00:00", "15:00:00"),
            'TT': ("15:00:00", "23:00:00"),
            'TN': ("23:00:00", "07:00:00")
        }
        if turno not in shifts:
            abort(400, "Turno inválido")
        
        d = datetime.strptime(date, "%Y-%m-%d").date()
        start_naive = datetime.combine(d, datetime.strptime(shifts[turno][0], "%H:%M:%S").time())
        end_day = d + timedelta(days=1) if turno == 'TN' else d
        end_naive = datetime.combine(end_day, datetime.strptime(shifts[turno][1], "%H:%M:%S").time())
        start_local = argentina_tz.localize(start_naive)
        end_local   = argentina_tz.localize(end_naive)
    else:
        abort(400, "Faltan parámetros")

    start_utc = start_local.astimezone(utc_tz)
    end_utc   = end_local.astimezone(utc_tz)

    eng = get_engine()
    with eng.connect() as c:
        df = pd.read_sql(
            text("""
                SELECT time, mOn, mWo
                FROM registros
                WHERE m=:m AND time>=:s AND time<:e
                ORDER BY time
            """),
            c, params={"m": m, "s": start_utc, "e": end_utc}
        )

    if df.empty:
        return jsonify({"maquina": m, "data": []})

    # pd.to_datetime ya infiere TZ si es ambigua con 'infer', y se convierte a la TZ local.
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(utc_tz, ambiguous='infer', nonexistent='shift_forward') \
                                         .dt.tz_convert(argentina_tz) \
                                         .apply(lambda x: x.isoformat())
    
    return jsonify({"maquina": m, "data": df.to_dict("records")})

# --------------------------------------------------------------------------
# maquina en detalle con Chart.js 
# --------------------------------------------------------------------------
@app.route("/maquina/<int:m>")
def maquina(m):
    # Obtener todos los parámetros posibles de la URL
    date_param = request.args.get("date")
    turno_param = request.args.get("turno")
    start_param = request.args.get("start")
    end_param = request.args.get("end")

    # Validar que al menos un conjunto de parámetros esté presente
    if not ((date_param and turno_param) or (start_param and end_param)):
        # Si no hay parámetros válidos, redirigir al índice
        return redirect(url_for("index"))

    return render_template(
        "maquina.html",
        maquina=m,
        # Pasa los parámetros tal cual fueron recibidos a la plantilla
        # El JS en maquina.html se encargará de usarlos para la API y la UI
        date=date_param,
        turno=turno_param,
        start=start_param,
        end=end_param,
    )