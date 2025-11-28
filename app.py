import os
from flask import Flask, render_template, redirect, url_for, request, flash, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from fpdf import FPDF # Importacao nova

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chave_super_secreta_seguranca_total'

# Banco de dados Hibrido
uri = os.getenv("DATABASE_URL")
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri or 'sqlite:///escola.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- MODELOS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha = db.Column(db.String(200), nullable=False)
    is_professor = db.Column(db.Boolean, default=False)
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

# --- ROTAS ---
@app.route('/')
def index():
    return render_template('index.html')

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
        # Logica: Pegar todas as provas e marcar quais o aluno ja fez
        provas = Prova.query.all()
        meus_resultados = Resultado.query.filter_by(aluno_id=current_user.id).all()
        ids_feitas = [r.prova_id for r in meus_resultados] # Lista de IDs que ele ja fez
        return render_template('dash_aluno.html', provas=provas, resultados=meus_resultados, ids_feitas=ids_feitas)

@app.route('/criar_prova', methods=['GET', 'POST'])
@login_required
def criar_prova():
    if not current_user.is_professor: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        titulo = request.form.get('titulo')
        nova_prova = Prova(titulo=titulo, criado_por=current_user.id)
        db.session.add(nova_prova)
        db.session.commit()
        return redirect(url_for('adicionar_questoes', prova_id=nova_prova.id))
    return render_template('criar_prova.html')

@app.route('/adicionar_questoes/<int:prova_id>', methods=['GET', 'POST'])
@login_required
def adicionar_questoes(prova_id):
    if request.method == 'POST':
        q = Questao(
            texto=request.form.get('texto'),
            opcao_a=request.form.get('opcao_a'),
            opcao_b=request.form.get('opcao_b'),
            opcao_c=request.form.get('opcao_c'),
            opcao_d=request.form.get('opcao_d'),
            correta=request.form.get('correta'),
            prova_id=prova_id
        )
        db.session.add(q)
        db.session.commit()
    prova = Prova.query.get(prova_id)
    return render_template('add_questoes.html', prova=prova)

@app.route('/fazer_prova/<int:prova_id>', methods=['GET', 'POST'])
@login_required
def fazer_prova(prova_id):
    # REGRA DE NEGOCIO: Bloquear se ja fez
    ja_fez = Resultado.query.filter_by(aluno_id=current_user.id, prova_id=prova_id).first()
    if ja_fez:
        flash('Você já realizou esta prova!')
        return redirect(url_for('dashboard'))

    prova = Prova.query.get(prova_id)
    if request.method == 'POST':
        acertos = 0
        total = len(prova.questoes)
        for questao in prova.questoes:
            resposta_aluno = request.form.get(f'q_{questao.id}')
            if resposta_aluno == questao.correta:
                acertos += 1
        nota_final = (acertos / total) * 10 if total > 0 else 0
        resultado = Resultado(aluno_id=current_user.id, prova_id=prova.id, nota=nota_final)
        db.session.add(resultado)
        db.session.commit()
        return render_template('resultado.html', nota=nota_final, total=total, acertos=acertos)
    return render_template('fazer_prova.html', prova=prova)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# --- NOVIDADE: GERADOR DE CERTIFICADO ---
@app.route('/certificado/<int:resultado_id>')
@login_required
def gerar_certificado(resultado_id):
    res = Resultado.query.get(resultado_id)
    # Seguranca: so o dono pode baixar e apenas se nota >= 7
    if res.aluno_id != current_user.id or res.nota < 7.0:
        flash("Certificado indisponível (Nota insuficiente ou acesso negado).")
        return redirect(url_for('dashboard'))
    
    prova = Prova.query.get(res.prova_id)
    
    # Criando o PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=24)
    pdf.cell(200, 40, txt="CERTIFICADO DE CONCLUSÃO", ln=1, align="C")
    
    pdf.set_font("Arial", size=16)
    pdf.cell(200, 10, txt="Certificamos que o aluno(a):", ln=1, align="C")
    
    pdf.set_font("Arial", 'B', size=20)
    pdf.cell(200, 20, txt=current_user.nome, ln=1, align="C")
    
    pdf.set_font("Arial", size=16)
    texto = f"Concluiu a avaliação '{prova.titulo}' com nota {res.nota:.1f}"
    pdf.cell(200, 20, txt=texto, ln=1, align="C")
    
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 20, txt=f"Data: {res.data_envio.strftime('%d/%m/%Y')}", ln=1, align="C")
    
    response = make_response(pdf.output(dest='S').encode('latin-1'))
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=certificado_{res.id}.pdf'
    return response

# Rota magica mantida (mas use com cuidado!)
@app.route('/setup_banco_magico')
def setup_banco_magico():
    try:
        with app.app_context(): db.create_all()
        return "Tabelas verificadas/criadas."
    except Exception as e: return str(e)

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True)