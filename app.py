import os
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chave_super_secreta_seguranca_total'

# Lógica Híbrida de Banco de Dados
# Se existir a variavel DATABASE_URL (no Render), usa ela. Se não, usa o arquivo local.
uri = os.getenv("DATABASE_URL")
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri or 'sqlite:///escola.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- MODELOS (TABELAS) ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha = db.Column(db.String(200), nullable=False)
    is_professor = db.Column(db.Boolean, default=False)
    # Relacionamento: Um aluno tem muitos resultados
    resultados = db.relationship('Resultado', backref='aluno', lazy=True)

class Prova(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(150), nullable=False)
    criado_por = db.Column(db.Integer, db.ForeignKey('user.id'))
    questoes = db.relationship('Questao', backref='prova', lazy=True, cascade="all, delete-orphan")

class Questao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    texto = db.Column(db.String(300), nullable=False)
    opcao_a = db.Column(db.String(100))
    opcao_b = db.Column(db.String(100))
    opcao_c = db.Column(db.String(100))
    opcao_d = db.Column(db.String(100))
    correta = db.Column(db.String(1), nullable=False) 
    prova_id = db.Column(db.Integer, db.ForeignKey('prova.id'), nullable=False)

class Resultado(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    prova_id = db.Column(db.Integer, db.ForeignKey('prova.id'), nullable=False)
    nota = db.Column(db.Float, nullable=False)
    data_envio = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- ROTAS BÁSICAS ---
@app.route('/')
def index():
    return render_template('index.html') # Certifique-se de ter este arquivo ou mude para retornar texto simples

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nome = request.form.get('nome')
        email = request.form.get('email')
        senha_crua = request.form.get('senha')
        tipo = request.form.get('tipo') 
        
        user_existente = User.query.filter_by(email=email).first()
        if user_existente:
            flash('Email já cadastrado!')
            return redirect(url_for('registro'))
            
        nova_senha = generate_password_hash(senha_crua, method='pbkdf2:sha256')
        novo_user = User(nome=nome, email=email, senha=nova_senha, is_professor=(tipo=='professor'))
        db.session.add(novo_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('registro.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        senha = request.form.get('senha')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.senha, senha):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Login inválido.')
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_professor:
        provas = Prova.query.filter_by(criado_por=current_user.id).all()
        return render_template('dash_professor.html', provas=provas)
    else:
        provas = Prova.query.all()
        meus_resultados = Resultado.query.filter_by(aluno_id=current_user.id).all()
        return render_template('dash_aluno.html', provas=provas, resultados=meus_resultados)

# Inicializacao
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
