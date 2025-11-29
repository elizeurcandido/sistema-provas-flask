import os
import io
import json
import random
import pandas as pd
from flask import Flask, render_template, redirect, url_for, request, flash, make_response, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from fpdf import FPDF
from pypdf import PdfReader
from groq import Groq
import google.generativeai as genai # Reimportando Gemini para o Tutor
from sqlalchemy import text 

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chave_super_secreta_seguranca_total'

# --- CONFIGURAÇÃO DAS IAs ---
# Groq para criar provas (Rápido)
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

# Gemini para explicar erros (Didático)
GOOGLE_API_KEY = os.getenv('GEMINI_API_KEY')
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

# --- BANCO DE DADOS ---
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
    __tablename__ = 'tb_usuarios' 
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha = db.Column(db.String(200), nullable=False)
    is_professor = db.Column(db.Boolean, default=False)
    resultados = db.relationship('Resultado', backref='aluno', lazy=True)

class Prova(db.Model):
    __tablename__ = 'tb_provas'
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(150), nullable=False)
    criado_por = db.Column(db.Integer, db.ForeignKey('tb_usuarios.id'))
    ativa = db.Column(db.Boolean, default=True)
    questoes = db.relationship('Questao', backref='prova', lazy=True, cascade="all, delete-orphan")

class Questao(db.Model):
    __tablename__ = 'tb_questoes'
    id = db.Column(db.Integer, primary_key=True)
    texto = db.Column(db.Text, nullable=False)
    opcao_a = db.Column(db.Text)
    opcao_b = db.Column(db.Text)
    opcao_c = db.Column(db.Text)
    opcao_d = db.Column(db.Text)
    correta = db.Column(db.String(1), nullable=False) 
    prova_id = db.Column(db.Integer, db.ForeignKey('tb_provas.id'), nullable=False)

class Resultado(db.Model):
    __tablename__ = 'tb_resultados'
    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey('tb_usuarios.id'), nullable=False)
    prova_id = db.Column(db.Integer, db.ForeignKey('tb_provas.id'), nullable=False)
    nota = db.Column(db.Float, nullable=False)
    data_envio = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- ROTAS GERAIS ---
@app.route('/')
def index(): return render_template('index.html')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        user_existente = User.query.filter_by(email=request.form.get('email')).first()
        if user_existente:
            flash('Email já cadastrado!')
            return redirect(url_for('registro'))
        novo_user = User(
            nome=request.form.get('nome'),
            email=request.form.get('email'),
            senha=generate_password_hash(request.form.get('senha'), method='pbkdf2:sha256'),
            is_professor=(request.form.get('tipo') == 'professor')
        )
        db.session.add(novo_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('registro.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form.get('email')).first()
        if user and check_password_hash(user.senha, request.form.get('senha')):
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
        ids_feitas = [r.prova_id for r in meus_resultados]
        return render_template('dash_aluno.html', provas=provas, resultados=meus_resultados, ids_feitas=ids_feitas)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# --- ROTAS DE PROVA (PROFESSOR) ---
@app.route('/criar_prova', methods=['GET', 'POST'])
@login_required
def criar_prova():
    if not current_user.is_professor: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        nova_prova = Prova(titulo=request.form.get('titulo'), criado_por=current_user.id, ativa=True)
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
            opcao_a=request.form.get('opcao_a'), opcao_b=request.form.get('opcao_b'),
            opcao_c=request.form.get('opcao_c'), opcao_d=request.form.get('opcao_d'),
            correta=request.form.get('correta'), prova_id=prova_id
        )
        db.session.add(q)
        db.session.commit()
    prova = Prova.query.get(prova_id)
    return render_template('add_questoes.html', prova=prova)

@app.route('/excluir_prova/<int:prova_id>')
@login_required
def excluir_prova(prova_id):
    prova = Prova.query.get(prova_id)
    if prova and prova.criado_por == current_user.id:
        Resultado.query.filter_by(prova_id=prova_id).delete()
        Questao.query.filter_by(prova_id=prova_id).delete()
        db.session.delete(prova)
        db.session.commit()
        flash('Prova excluída.')
    return redirect(url_for('dashboard'))

@app.route('/excluir_questao/<int:questao_id>')
@login_required
def excluir_questao(questao_id):
    questao = Questao.query.get(questao_id)
    if questao:
        prova = Prova.query.get(questao.prova_id)
        if prova.criado_por == current_user.id:
            db.session.delete(questao)
            db.session.commit()
            flash('Questão removida.')
            return redirect(url_for('adicionar_questoes', prova_id=prova.id))
    return redirect(url_for('dashboard'))

@app.route('/duplicar_prova/<int:prova_id>')
@login_required
def duplicar_prova(prova_id):
    original = Prova.query.get(prova_id)
    if original and original.criado_por == current_user.id:
        nova = Prova(titulo=f"Cópia de {original.titulo}", criado_por=current_user.id, ativa=False)
        db.session.add(nova)
        db.session.flush()
        for q in original.questoes:
            db.session.add(Questao(
                texto=q.texto, opcao_a=q.opcao_a, opcao_b=q.opcao_b,
                opcao_c=q.opcao_c, opcao_d=q.opcao_d, correta=q.correta, prova_id=nova.id
            ))
        db.session.commit()
        flash('Prova duplicada!')
    return redirect(url_for('dashboard'))

@app.route('/alternar_status/<int:prova_id>')
@login_required
def alternar_status(prova_id):
    prova = Prova.query.get(prova_id)
    if prova and prova.criado_por == current_user.id:
        prova.ativa = not prova.ativa
        db.session.commit()
        flash(f"Prova {'aberta' if prova.ativa else 'fechada'}.")
    return redirect(url_for('dashboard'))

# --- ROTAS DE PROVA (ALUNO) ---
@app.route('/fazer_prova/<int:prova_id>', methods=['GET', 'POST'])
@login_required
def fazer_prova(prova_id):
    prova = Prova.query.get(prova_id)
    if not prova or not prova.ativa:
        flash('Prova não disponível.')
        return redirect(url_for('dashboard'))
    
    ja_fez = Resultado.query.filter_by(aluno_id=current_user.id, prova_id=prova_id).first()
    if ja_fez:
        flash('Você já fez esta prova.')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        acertos = 0
        detalhes = []
        for q in prova.questoes:
            resp = request.form.get(f'q_{q.id}')
            acertou = (resp == q.correta)
            if acertou: acertos += 1
            detalhes.append({
                'enunciado': q.texto,
                'opcao_a': q.opcao_a, 'opcao_b': q.opcao_b,
                'opcao_c': q.opcao_c, 'opcao_d': q.opcao_d,
                'marcada': resp, 'correta': q.correta, 'acertou': acertou
            })
        
        nota = (acertos / len(prova.questoes)) * 10 if prova.questoes else 0
        resultado = Resultado(aluno_id=current_user.id, prova_id=prova.id, nota=nota)
        db.session.add(resultado)
        db.session.commit()
        return render_template('resultado.html', nota=nota, total=len(prova.questoes), acertos=acertos, gabarito=detalhes, resultado_id=resultado.id)

    questoes = list(prova.questoes)
    random.shuffle(questoes)
    return render_template('fazer_prova.html', prova=prova, questoes=questoes)

# --- INTEGRAÇÕES AI (GEMINI E GROQ) ---

# 1. API: Explicar Erro (GEMINI) - ✨ NOVO ✨
@app.route('/api/explicar_erro', methods=['POST'])
@login_required
def api_explicar_erro():
    if not GOOGLE_API_KEY:
        return jsonify({'error': 'Chave Gemini não configurada'}), 500
    
    data = request.json
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        Você é um professor particular gentil. O aluno errou esta questão:
        PERGUNTA: {data['pergunta']}
        ALUNO MARCOU: {data['marcada']}
        CORRETA ERA: {data['correta']}
        
        Explique em no máximo 2 parágrafos curtos:
        1. Por que a alternativa do aluno está incorreta (se fizer sentido explicar).
        2. Por que a alternativa correta é a certa.
        Use linguagem simples e direta.
        """
        response = model.generate_content(prompt)
        return jsonify({'explicacao': response.text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 2. Gerar Prova (GROQ/LLAMA)
@app.route('/gerar_com_ia/<int:prova_id>', methods=['POST'])
@login_required
def gerar_com_ia(prova_id):
    if not GROQ_API_KEY:
        flash("Erro: Chave Groq não configurada.")
        return redirect(url_for('adicionar_questoes', prova_id=prova_id))
    
    file = request.files['arquivo']
    if not file: return redirect(url_for('adicionar_questoes', prova_id=prova_id))

    try:
        reader = PdfReader(file)
        text_content = "".join([p.extract_text() for p in reader.pages])[:30000]
        
        client = Groq(api_key=GROQ_API_KEY)
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Gere um JSON puro com 3 questões de prova baseadas no texto."},
                {"role": "user", "content": f"Texto: {text_content}\nFormato JSON: [{{'texto': '...', 'a': '...', 'b': '...', 'c': '...', 'd': '...', 'correta': 'a'}}]. Apenas JSON."}
            ],
            model="llama-3.3-70b-versatile", temperature=0.5
        )
        
        content = completion.choices[0].message.content.replace("```json", "").replace("```", "").strip()
        data = json.loads(content)
        
        for item in data:
            db.session.add(Questao(
                texto=item['texto'], opcao_a=item['a'], opcao_b=item['b'],
                opcao_c=item['c'], opcao_d=item['d'], correta=item['correta'].lower(), prova_id=prova_id
            ))
        db.session.commit()
        flash(f"{len(data)} questões geradas!")
    except Exception as e:
        flash(f"Erro IA: {str(e)}")
        
    return redirect(url_for('adicionar_questoes', prova_id=prova_id))

# --- RELATÓRIOS E UTILITÁRIOS ---
@app.route('/ver_notas/<int:prova_id>')
@login_required
def ver_notas(prova_id):
    prova = Prova.query.get(prova_id)
    if not prova or prova.criado_por != current_user.id: return redirect(url_for('dashboard'))
    resultados = Resultado.query.filter_by(prova_id=prova_id).all()
    
    aprovados = sum(1 for r in resultados if r.nota >= 7)
    reprovados = len(resultados) - aprovados
    media = sum(r.nota for r in resultados) / len(resultados) if resultados else 0
    
    stats = {'total': len(resultados), 'aprovados': aprovados, 'reprovados': reprovados, 'media': round(media, 1)}
    return render_template('ver_notas.html', prova=prova, resultados=resultados, stats=stats)

@app.route('/exportar_excel/<int:prova_id>')
@login_required
def exportar_excel(prova_id):
    prova = Prova.query.get(prova_id)
    if not prova or prova.criado_por != current_user.id: return redirect(url_for('dashboard'))
    res = Resultado.query.filter_by(prova_id=prova_id).all()
    data = [{'Aluno': r.aluno.nome, 'Nota': r.nota, 'Data': r.data_envio} for r in res]
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame(data).to_excel(writer, index=False)
    output.seek(0)
    
    return make_response(output.read(), 200, {'Content-Disposition': f'attachment; filename=notas_{prova.id}.xlsx', 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'})

@app.route('/certificado/<int:resultado_id>')
@login_required
def gerar_certificado(resultado_id):
    res = Resultado.query.get(resultado_id)
    if res.aluno_id != current_user.id or res.nota < 7: return redirect(url_for('dashboard'))
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=24)
    pdf.cell(200, 40, txt="CERTIFICADO", ln=1, align="C")
    pdf.set_font("Arial", size=16)
    pdf.cell(200, 20, txt=f"Certificamos que {current_user.nome} completou a prova com nota {res.nota}", ln=1, align="C")
    
    response = make_response(pdf.output(dest='S').encode('latin-1'))
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=cert_{res.id}.pdf'
    return response

# --- ROTAS DE MANUTENÇÃO ---
@app.route('/setup_banco_magico')
def setup():
    with app.app_context(): db.create_all()
    return "Tabelas Criadas"

@app.route('/corrigir_banco_ia')
def fix_db():
    try:
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE tb_questoes ALTER COLUMN texto TYPE TEXT;"))
            conn.execute(text("ALTER TABLE tb_questoes ALTER COLUMN opcao_a TYPE TEXT;"))
            conn.execute(text("ALTER TABLE tb_questoes ALTER COLUMN opcao_b TYPE TEXT;"))
            conn.execute(text("ALTER TABLE tb_questoes ALTER COLUMN opcao_c TYPE TEXT;"))
            conn.execute(text("ALTER TABLE tb_questoes ALTER COLUMN opcao_d TYPE TEXT;"))
            conn.commit()
        return "Banco Corrigido"
    except Exception as e: return str(e)

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True)