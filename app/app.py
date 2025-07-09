from flask import Flask, render_template, request, redirect, url_for
from flask_mysqldb import MySQL
import os

 
app = Flask(__name__)
 
app.config["MYSQL_USER"] = os.environ["MYSQL_USER"]
app.config["MYSQL_PASSWORD"] = os.environ["MYSQL_PASSWORD"]
app.config["MYSQL_DB"] = os.environ["MYSQL_DB"]
app.config["MYSQL_HOST"] = os.environ["MYSQL_HOST"]


mysql = MySQL(app)


@app.route('/')
def index():
    cur = mysql.connection.cursor()
    cur.execute('SELECT DISTINCT m FROM registros')
    datos = cur.fetchall()
    cur.close()
    datos = [dato[0] for dato in datos]
    return render_template('index.html', maquinas = datos)

@app.route('/maquinas')
def maquinas():
    return render_template('maquinas.html')