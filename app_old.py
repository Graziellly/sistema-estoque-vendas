from flask import Flask, render_template, request, redirect, url_for
from database import db
from models import Usuario, Produto
import os

app = Flask(__name__)

# GARANTE QUE A PASTA INSTANCE EXISTA
os.makedirs(app.instance_path, exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'estoque.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'segredo_supermercado'

db.init_app(app)

with app.app_context():
    db.create_all()

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario']
        senha = request.form['senha']

        user = Usuario.query.filter_by(usuario=usuario, senha=senha).first()
        if user:
            return redirect(url_for('dashboard'))

    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    produtos = Produto.query.all()
    return render_template('dashboard.html', produtos=produtos)

@app.route('/estoque', methods=['GET', 'POST'])
def estoque():
    if request.method == 'POST':
        nome = request.form['nome']
        quantidade = request.form['quantidade']

        produto = Produto(nome=nome, quantidade=quantidade)
        db.session.add(produto)
        db.session.commit()

    produtos = Produto.query.all()
    return render_template('estoque.html', produtos=produtos)

@app.route('/baixar/<int:id>')
def baixar(id):
    produto = Produto.query.get(id)
    if produto and produto.quantidade > 0:
        produto.quantidade -= 1
        db.session.commit()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
