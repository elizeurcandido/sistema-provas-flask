from flask import Flask, render_template, request, send_file
from fpdf import FPDF
import os

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        escola = request.form.get('escola')
        professor = request.form.get('professor')
        prova = request.form.get('prova')
        data = request.form.get('data')
        conteudo = request.form.get('conteudo')

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        
        pdf.cell(200, 10, txt=f"Escola: {escola}", ln=1, align='C')
        pdf.cell(200, 10, txt=f"Professor: {professor}", ln=1, align='L')
        pdf.cell(200, 10, txt=f"Prova: {prova}", ln=1, align='L')
        pdf.cell(200, 10, txt=f"Data: {data}", ln=1, align='L')
        pdf.ln(10)
        pdf.multi_cell(0, 10, txt=f"Conteúdo da Prova:\n\n{conteudo}")

        filename = "prova_gerada.pdf"
        pdf.output(filename)

        return send_file(filename, as_attachment=True)

    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)
