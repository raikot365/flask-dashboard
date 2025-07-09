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

    # si no hay argumento de fecha
    if not initial_date:
        # obtener la última fecha y turno con datos de la Vista
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
            # Fallback si la Vista está vacía, usa la fecha actual y TM
            initial_date = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
            initial_turno = 'TM'
    
    return render_template("index.html", initial_date=initial_date, initial_turno=initial_turno)

# --- Configuración de zona horaria ---
argentina_tz = pytz.timezone('America/Argentina/Buenos_Aires')
utc_tz = pytz.timezone('UTC')

# --------------------------------------------------------------------------
# grafico torta 
# --------------------------------------------------------------------------
@app.route("/api/vista")
def api_vista():
    selected_date = request.args.get("date")
    selected_turno = request.args.get("turno")
    eng = get_engine()

    shifts = {
        'TM': ("07:00:00", "15:00:00"),
        'TT': ("15:00:00", "23:00:00"),
        'TN': ("23:00:00", "07:00:00")
    }

    # Determinar fecha/turno por defecto si no vienen
    if not selected_date or not selected_turno:
        with eng.connect() as c:
            last = c.execute(text("""
                SELECT fecha, Turno
                FROM Vista
                ORDER BY fecha DESC, FIELD(Turno,'TM','TT','TN')
                LIMIT 1
            """)).mappings().first()
        if last:
            selected_date = last["fecha"].strftime("%Y-%m-%d")
            selected_turno = last["Turno"]
        else:
            selected_date = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
            selected_turno = 'TM'

    if selected_turno not in shifts:
        abort(400, "Turno inválido")

    # Calcular rangos UTC
    d = datetime.strptime(selected_date, "%Y-%m-%d").date()
    start_naive = datetime.combine(d, datetime.strptime(shifts[selected_turno][0], "%H:%M:%S").time())
    end_day = d + timedelta(days=1) if selected_turno == 'TN' else d
    end_naive = datetime.combine(end_day, datetime.strptime(shifts[selected_turno][1], "%H:%M:%S").time())

    start_local = argentina_tz.localize(start_naive)
    end_local   = argentina_tz.localize(end_naive)
    start_utc   = start_local.astimezone(utc_tz)
    end_utc     = end_local.astimezone(utc_tz)

    # Leer muestras del turno
    raw_df = pd.read_sql(
        text("""
            SELECT m, mOn, mWo
            FROM registros
            WHERE time >= :s AND time < :e
        """),
        eng, params={"s": start_utc, "e": end_utc}
    )

    if raw_df.empty:
        return jsonify({"date": selected_date, "turno": selected_turno, "data": []})

    # Recuento simple de muestras
    results = []
    for machine_id, df_m in raw_df.groupby('m'):
        total      = len(df_m)
        on_count   = int(df_m['mOn'].sum())                     # encendida
        off_count  = total - on_count                           # apagada
        wo_count   = int(df_m[df_m['mOn'] == 1]['mWo'].sum())    # produciendo
        nwo_count  = on_count - wo_count                        # encendida sin producir

        results.append({
            "m": machine_id,
            "N": total,
            "On": on_count,
            "Off": off_count,
            "Prod": wo_count,
            "NoProd": nwo_count
        })

    return jsonify({
        "date": selected_date,
        "turno": selected_turno,
        "data": results
    })
    
    
# --------------------------------------------------------------------------
# serie temporal por máquina 
# --------------------------------------------------------------------------
@app.route("/api/maquina/<int:m>")
def api_maquina(m):
    date  = request.args.get("date")
    turno = request.args.get("turno")
    if not date or not turno:
        abort(400, "Faltan fecha y turno")

    shifts = {'TM': ("07:00:00","15:00:00"),
              'TT': ("15:00:00","23:00:00"),
              'TN': ("23:00:00","07:00:00")}
    if turno not in shifts:
        abort(400, "Turno inválido")

    d = datetime.strptime(date, "%Y-%m-%d").date()

    start_time_str = shifts[turno][0]
    end_time_str = shifts[turno][1]

    start_naive_local = datetime.combine(d, datetime.strptime(start_time_str, "%H:%M:%S").time())
    if turno == 'TN':
        end_naive_local = datetime.combine(d + timedelta(days=1), datetime.strptime(end_time_str, "%H:%M:%S").time())
    else:
        end_naive_local = datetime.combine(d, datetime.strptime(end_time_str, "%H:%M:%S").time())

    start_aware_local = argentina_tz.localize(start_naive_local)
    end_aware_local = argentina_tz.localize(end_naive_local)

    start_utc = start_aware_local.astimezone(utc_tz)
    end_utc = end_aware_local.astimezone(utc_tz)

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
        return jsonify({"maquina": m, "date": date, "turno": turno, "data": []})

    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(utc_tz, ambiguous='infer', nonexistent='shift_forward') \
                                         .dt.tz_convert(argentina_tz) \
                                         .apply(lambda x: x.isoformat())
    
    return jsonify({"maquina": m, "date": date, "turno": turno, "data": df.to_dict("records")})

# --------------------------------------------------------------------------
# maquina en detalle con Chart.js 
# --------------------------------------------------------------------------
@app.route("/maquina/<int:m>")
def maquina(m):
    date  = request.args.get("date")
    turno = request.args.get("turno")
    if not date or not turno:
        return redirect(url_for("index"))

    datos_response = api_maquina(m)
    if datos_response.status_code != 200:
        return redirect(url_for("index"))

    datos = datos_response.json['data']

    ts   = [d["time"] for d in datos]
    enc  = [d["mOn"] for d in datos]
    prod = [d["mWo"] for d in datos]

    return render_template(
        "maquina.html",
        maquina      = m,
        date         = date,
        turno        = turno,
        timestamps   = ts,
        encendida    = enc,
        produciendo  = prod,
    )