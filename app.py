import json
import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = "troque-esta-chave-em-producao"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# No Vercel (serverless) o disco do projeto é só-leitura; gravamos em /tmp lá.
DATA_DIR = "/tmp" if os.environ.get("VERCEL") else BASE_DIR + "/data"
DATA_FILE = os.path.join(DATA_DIR, "materiais.json")
SEED_FILE = os.path.join(BASE_DIR, "data", "materiais.json")

CATEGORIAS_EMOJI = {
    "Courino": "🟫",
    "Metal": "⚙️",
    "Aviamento": "🧵",
    "Tecido": "🧶",
    "Embalagem": "📦",
    "Outros": "🔹",
}
CATEGORIAS = list(CATEGORIAS_EMOJI.keys())
UNIDADES = ["unidades", "metros", "rolos", "kg", "gramas", "pares", "pacotes"]
MOTIVOS_BAIXA = ["Produção de bolsa", "Produção de nécessaire", "Amostra / Teste", "Desperdício"]


def carregar_materiais():
    if not os.path.exists(DATA_FILE):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SEED_FILE, encoding="utf-8") as f:
            seed = json.load(f)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(seed, f, ensure_ascii=False, indent=2)
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def salvar_materiais(materiais):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(materiais, f, ensure_ascii=False, indent=2)


def encontrar(materiais, material_id):
    for m in materiais:
        if m["id"] == material_id:
            return m
    return None


@app.route("/")
def home():
    materiais = carregar_materiais()
    total_itens = len(materiais)
    baixo_estoque = [m for m in materiais if m["quantidade"] <= m["quantidade_minima"]]
    return render_template("home.html", total_itens=total_itens, baixo_estoque=baixo_estoque)


@app.route("/estoque")
def estoque():
    materiais = carregar_materiais()
    cat = request.args.get("cat", "Todos")
    q = request.args.get("q", "").strip().lower()

    resultado = materiais
    if cat != "Todos":
        resultado = [m for m in resultado if m["categoria"] == cat]
    if q:
        # busca por nome OU por código GTIN
        resultado = [
            m for m in resultado
            if q in m["nome"].lower() or q in (m.get("gtin") or "").lower()
        ]

    return render_template(
        "estoque.html",
        materiais=resultado,
        categorias=CATEGORIAS,
        cat_ativa=cat,
        q=request.args.get("q", ""),
        total=len(materiais),
    )


@app.route("/estoque/<material_id>/entrada", methods=["POST"])
def estoque_entrada(material_id):
    materiais = carregar_materiais()
    m = encontrar(materiais, material_id)
    if m:
        try:
            qtd = float(request.form.get("quantidade", 0))
        except ValueError:
            qtd = 0
        m["quantidade"] = round(m["quantidade"] + qtd, 3)
        salvar_materiais(materiais)
        flash(f"Entrada registrada em {m['nome']}.")
    return redirect(url_for("estoque"))


@app.route("/estoque/<material_id>/excluir", methods=["POST"])
def estoque_excluir(material_id):
    materiais = carregar_materiais()
    materiais = [m for m in materiais if m["id"] != material_id]
    salvar_materiais(materiais)
    flash("Material removido.")
    return redirect(url_for("estoque"))


@app.route("/adicionar", methods=["GET", "POST"])
def adicionar():
    materiais = carregar_materiais()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        categoria = request.form.get("categoria", "Outros")
        gtin = request.form.get("gtin", "").strip()

        try:
            quantidade = float(request.form.get("quantidade", 0))
        except ValueError:
            quantidade = 0
        try:
            quantidade_minima = float(request.form.get("quantidade_minima", 5))
        except ValueError:
            quantidade_minima = 5
        try:
            custo = float(request.form.get("custo", 0) or 0)
        except ValueError:
            custo = 0

        novo = {
            "id": str(uuid.uuid4()),
            "nome": nome,
            "categoria": categoria,
            "emoji": CATEGORIAS_EMOJI.get(categoria, "🔹"),
            "quantidade": quantidade,
            "unidade": request.form.get("unidade", "unidades"),
            "quantidade_minima": quantidade_minima,
            "custo": custo,
            "gtin": gtin,
        }
        materiais.append(novo)
        salvar_materiais(materiais)
        flash(f"{nome} adicionado ao estoque.")
        return redirect(url_for("estoque"))

    # dados usados pela busca (nome/gtin) que ajuda a evitar duplicados
    lista_busca = [
        {"id": m["id"], "nome": m["nome"], "gtin": m.get("gtin") or "", "quantidade": m["quantidade"], "unidade": m["unidade"]}
        for m in materiais
    ]
    return render_template(
        "adicionar.html",
        categorias=CATEGORIAS_EMOJI,
        unidades=UNIDADES,
        materiais_json=lista_busca,
    )


@app.route("/baixa", methods=["GET", "POST"])
def baixa():
    materiais = carregar_materiais()

    if request.method == "POST":
        material_id = request.form.get("material_id")
        m = encontrar(materiais, material_id)
        try:
            qtd = float(request.form.get("quantidade", 0))
        except ValueError:
            qtd = 0
        if m and qtd > 0:
            m["quantidade"] = round(max(0, m["quantidade"] - qtd), 3)
            salvar_materiais(materiais)
            flash(f"Baixa registrada em {m['nome']}.")
        return redirect(url_for("baixa"))

    mid_preselecionado = request.args.get("mid", "")
    return render_template(
        "baixa.html",
        materiais=materiais,
        motivos=MOTIVOS_BAIXA,
        mid_preselecionado=mid_preselecionado,
    )


# Páginas do menu ainda não reconstruídas — placeholder para não quebrar a navegação.
@app.route("/<pagina>")
def em_construcao(pagina):
    titulos = {
        "produtos": "Produtos & Receitas",
        "pedidos": "Pedidos dos Clientes",
        "sobras": "Sobras e Reaproveitamento",
        "financeiro": "Financeiro",
        "alertas": "Alertas e Relatórios",
    }
    if pagina not in titulos:
        return redirect(url_for("home"))
    return render_template("em_construcao.html", titulo=titulos[pagina])


if __name__ == "__main__":
    app.run(debug=True)
