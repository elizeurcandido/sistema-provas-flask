import os
import io
import json
import random
import pandas as pd
from flask import Flask, render_template, redirect, url_for, request, flash, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from fpdf import FPDF
from pypdf import PdfReader
from groq import Groq
from sqlalchemy import text 

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chave_super_secreta_seguranca_total'

# --- CONFIGURAÇÃO DO BANCO DE DADOS ---
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

# --- ROTAS PRINCIPAIS ---
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
        provas = Prova.query.all()
        meus_resultados = Resultado.query.filter_by(aluno_id=current_user.id).all()
        ids_feitas = [r.prova_id for r in meus_resultados]
        return render_template('dash_aluno.html', provas=provas, resultados=meus_resultados, ids_feitas=ids_feitas)

@app.route('/criar_prova', methods=['GET', 'POST'])
@login_required
def criar_prova():
    if not current_user.is_professor: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        titulo = request.form.get('titulo')
        nova_prova = Prova(titulo=titulo, criado_por=current_user.id, ativa=True)
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
    prova = Prova.query.get(prova_id)
    
    if not prova: return redirect(url_for('dashboard'))
    if not prova.ativa:
        flash('Esta prova foi encerrada pelo professor.')
        return redirect(url_for('dashboard'))

    ja_fez = Resultado.query.filter_by(aluno_id=current_user.id, prova_id=prova_id).first()
    if ja_fez:
        flash('Você já realizou esta prova! Veja seu desempenho no histórico.')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        acertos = 0
        total = len(prova.questoes)
        detalhes_gabarito = []
        for questao in prova.questoes:
            resposta_aluno = request.form.get(f'q_{questao.id}')
            acertou = (resposta_aluno == questao.correta)
            if acertou: acertos += 1
            detalhes_gabarito.append({
                'enunciado': questao.texto,
                'opcao_a': questao.opcao_a, 'opcao_b': questao.opcao_b,
                'opcao_c': questao.opcao_c, 'opcao_d': questao.opcao_d,
                'marcada': resposta_aluno, 'correta': questao.correta, 'acertou': acertou
            })
        nota_final = (acertos / total) * 10 if total > 0 else 0
        resultado = Resultado(aluno_id=current_user.id, prova_id=prova.id, nota=nota_final)
        db.session.add(resultado)
        db.session.commit()
        return render_template('resultado.html', nota=nota_final, total=total, acertos=acertos, gabarito=detalhes_gabarito, resultado_id=resultado.id)
    
    questoes_embaralhadas = list(prova.questoes)
    random.shuffle(questoes_embaralhadas)
    return render_template('fazer_prova.html', prova=prova, questoes=questoes_embaralhadas)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/alternar_status/<int:prova_id>')
@login_required
def alternar_status(prova_id):
    prova = Prova.query.get(prova_id)
    if not prova or prova.criado_por != current_user.id:
        return redirect(url_for('dashboard'))
    prova.ativa = not prova.ativa
    db.session.commit()
    status_msg = "aberta" if prova.ativa else "fechada"
    flash(f'Prova {status_msg} com sucesso!')
    return redirect(url_for('dashboard'))

# --- NOVA FUNCIONALIDADE: DUPLICAR PROVA ---
@app.route('/duplicar_prova/<int:prova_id>')
@login_required
def duplicar_prova(prova_id):
    prova_original = Prova.query.get(prova_id)
    
    if not prova_original or prova_original.criado_por != current_user.id:
        flash('Erro de permissão.')
        return redirect(url_for('dashboard'))
    
    nova_prova = Prova(
        titulo=f"Cópia de {prova_original.titulo}",
        criado_por=current_user.id,
        ativa=False 
    )
    db.session.add(nova_prova)
    db.session.flush()

    for q in prova_original.questoes:
        nova_q = Questao(
            texto=q.texto,
            opcao_a=q.opcao_a, opcao_b=q.opcao_b, opcao_c=q.opcao_c, opcao_d=q.opcao_d,
            correta=q.correta,
            prova_id=nova_prova.id
        )
        db.session.add(nova_q)
    
    db.session.commit()
    flash(f'Prova duplicada com sucesso!')
    return redirect(url_for('dashboard'))

# --- EXPORTAÇÕES E RELATÓRIOS ---
@app.route('/certificado/<int:resultado_id>')
@login_required
def gerar_certificado(resultado_id):
    res = Resultado.query.get(resultado_id)
    if res.aluno_id != current_user.id or res.nota < 7.0:
        flash("Indisponível.")
        return redirect(url_for('dashboard'))
    prova = Prova.query.get(res.prova_id)
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

@app.route('/excluir_prova/<int:prova_id>')
@login_required
def excluir_prova(prova_id):
    prova = Prova.query.get(prova_id)
    if not prova or prova.criado_por != current_user.id: return redirect(url_for('dashboard'))
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
    if not questao: return redirect(url_for('dashboard'))
    prova = Prova.query.get(questao.prova_id)
    if prova.criado_por != current_user.id: return redirect(url_for('dashboard'))
    db.session.delete(questao)
    db.session.commit()
    flash('Questão removida.')
    return redirect(url_for('adicionar_questoes', prova_id=prova.id))

@app.route('/ver_notas/<int:prova_id>')
@login_required
def ver_notas(prova_id):
    prova = Prova.query.get(prova_id)
    if not prova or prova.criado_por != current_user.id: return redirect(url_for('dashboard'))
    resultados = Resultado.query.filter_by(prova_id=prova_id).all()
    return render_template('ver_notas.html', prova=prova, resultados=resultados)

@app.route('/exportar_excel/<int:prova_id>')
@login_required
def exportar_excel(prova_id):
    prova = Prova.query.get(prova_id)
    if not prova or prova.criado_por != current_user.id: return redirect(url_for('dashboard'))
    resultados = Resultado.query.filter_by(prova_id=prova_id).all()
    dados = []
    for res in resultados:
        dados.append({'Aluno': res.aluno.nome, 'Email': res.aluno.email, 'Data': res.data_envio.strftime('%d/%m/%Y'), 'Nota': res.nota, 'Status': 'Aprovado' if res.nota >= 7.0 else 'Reprovado'})
    df = pd.DataFrame(dados)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Notas')
    output.seek(0)
    return make_response(output.read(), 200, {'Content-Disposition': f'attachment; filename=notas_{prova.titulo}.xlsx', 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'})

# --- GERADOR COM IA (LLAMA 3.3) ---
@app.route('/gerar_com_ia/<int:prova_id>', methods=['POST'])
@login_required
def gerar_com_ia(prova_id):
    groq_key = os.getenv('GROQ_API_KEY')
    if not groq_key:
        flash("Erro: Chave API da Groq não configurada no Render.")
        return redirect(url_for('adicionar_questoes', prova_id=prova_id))

    file = request.files['arquivo']
    if not file:
        flash("Nenhum arquivo enviado.")
        return redirect(url_for('adicionar_questoes', prova_id=prova_id))

    try:
        reader = PdfReader(file)
        texto_completo = ""
        for page in reader.pages:
            texto_completo += page.extract_text()
        
        texto_completo = texto_completo[:30000]

        client = Groq(api_key=groq_key)
        
        prompt = f"""
        Crie 3 questões de múltipla escolha baseadas neste texto:
        {texto_completo}
        
        Responda APENAS com um JSON puro neste formato exato (sem texto extra, sem markdown):
        [
            {{
                "texto": "Pergunta",
                "a": "Opção A", "b": "Opção B", "c": "Opção C", "d": "Opção D",
                "correta": "a"
            }}
        ]
        """

        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile", 
            temperature=0.5,
        )

        resposta_texto = chat_completion.choices[0].message.content
        resposta_limpa = resposta_texto.replace("```json", "").replace("```", "").strip()
        questoes_json = json.loads(resposta_limpa)

        for item in questoes_json:
            nova_q = Questao(
                texto=item['texto'],
                opcao_a=item['a'], opcao_b=item['b'], opcao_c=item['c'], opcao_d=item['d'],
                correta=item['correta'].lower(),
                prova_id=prova_id
            )
            db.session.add(nova_q)
        
        db.session.commit()
        flash(f"Sucesso! {len(questoes_json)} questões geradas.")

    except Exception as e:
        flash(f"Erro ao gerar com IA: {str(e)}")
        print(f"Erro IA: {e}")

    return redirect(url_for('adicionar_questoes', prova_id=prova_id))

# --- SETUP E MIGRAÇÃO ---
@app.route('/debug_banco')
def debug_banco(): return f"Banco: {app.config['SQLALCHEMY_DATABASE_URI'].split('@')[0]}"

@app.route('/setup_banco_magico')
def setup_banco_magico():
    with app.app_context(): db.create_all()
    return "Tabelas criadas."

@app.route('/migrar_db')
def migrar_db():
    try:
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE tb_provas ADD COLUMN IF NOT EXISTS ativa BOOLEAN DEFAULT TRUE;"))
            conn.commit()
        return "Migração 'ativa' OK!"
    except Exception as e: return f"Erro migração: {e}"

@app.route('/corrigir_banco_ia')
def corrigir_banco_ia():
    try:
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE tb_questoes ALTER COLUMN texto TYPE TEXT;"))
            conn.execute(text("ALTER TABLE tb_questoes ALTER COLUMN opcao_a TYPE TEXT;"))
            conn.execute(text("ALTER TABLE tb_questoes ALTER COLUMN opcao_b TYPE TEXT;"))
            conn.execute(text("ALTER TABLE tb_questoes ALTER COLUMN opcao_c TYPE TEXT;"))
            conn.execute(text("ALTER TABLE tb_questoes ALTER COLUMN opcao_d TYPE TEXT;"))
            conn.commit()
        return "<h1>Sucesso! O banco agora aceita textos longos da IA.</h1>"
    except Exception as e:
        return f"<h1>Erro na correção: {str(e)}</h1>"

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True)