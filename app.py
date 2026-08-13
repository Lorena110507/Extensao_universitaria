import json
import os
import uuid
import secrets
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, make_response, session, g, send_from_directory
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
# Use environment variable for the secret key in production
app.secret_key = os.environ.get("APP_SECRET", "troque-esta-chave-em-producao")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# No Vercel (serverless) o disco do projeto é só-leitura; gravamos em /tmp lá.
DATA_DIR = "/tmp" if os.environ.get("VERCEL") else BASE_DIR + "/data"
DB_PATH = os.path.join(DATA_DIR, "data.db")
USE_SQLITE = os.environ.get("USE_SQLITE", "1") in ("1", "true", "yes")
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

EMOJIS_PRODUTO = ["👜", "🎒", "👝", "💼", "🧳", "👛"]
STATUS_PEDIDO = ["Pendente", "Em produção", "Concluído", "Entregue", "Cancelado"]
STATUS_PEDIDO_BADGE = {
    "Pendente": "badge-warn",
    "Em produção": "badge-warn",
    "Concluído": "badge-ok",
    "Entregue": "badge-ok",
    "Cancelado": "badge-low",
}
STATUS_SOBRA_BADGE = {
    "Disponível": "badge-warn",
    "Reaproveitado": "badge-ok",
    "Descartado": "badge-low",
}
CATEGORIAS_DESPESA = ["Matéria-prima", "Aluguel", "Transporte", "Ferramentas", "Marketing", "Outros"]


# ── Persistência genérica (usada pelos módulos novos) ────────────────────────

# --- role decorator helper

def requires_roles(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not g.get('user'):
                return redirect(url_for('login', next=request.path))
            role = (g.user.get('role') or '') if g.user else ''
            if role == 'Admin' or (role in allowed_roles):
                return f(*args, **kwargs)
            flash('Acesso negado: você não tem permissão para acessar esta área.')
            return redirect(url_for('home'))
        return wrapped
    return decorator


def init_db():
    """Initialize SQLite database and tables used by the app when USE_SQLITE is enabled.
    Creates both a generic collections table (legacy) and proper normalized tables for
    materiais, produtos, pedidos, movimentacoes, sobras, despesas and usuarios.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # legacy generic collection storage (used for produtos, pedidos, etc.)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS collections (
            name TEXT NOT NULL,
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_collections_name ON collections(name)")

    # proper materiais table with explicit columns and uniqueness on (lower(nome), gtin)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS materiais (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            categoria TEXT,
            emoji TEXT,
            quantidade REAL DEFAULT 0,
            unidade TEXT,
            quantidade_minima REAL DEFAULT 0,
            custo REAL DEFAULT 0,
            gtin TEXT,
            foto TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    # case-insensitive uniqueness on name+gtin to avoid duplicates
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_materiais_nome_gtin ON materiais (lower(nome), gtin)"
    )

    # produtos table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS produtos (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            emoji TEXT,
            preco_venda REAL DEFAULT 0,
            receita TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    # pedidos table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pedidos (
            id TEXT PRIMARY KEY,
            cliente TEXT,
            produto_id TEXT,
            produto_nome TEXT,
            produto_emoji TEXT,
            quantidade INTEGER,
            preco_unitario REAL,
            valor_total REAL,
            status TEXT,
            materiais_baixados INTEGER DEFAULT 0,
            data_pedido TEXT,
            data_pedido_iso TEXT,
            observacoes TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    # movimentacoes (audit/history)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS movimentacoes (
            id TEXT PRIMARY KEY,
            tipo TEXT,
            material_nome TEXT,
            quantidade REAL,
            unidade TEXT,
            motivo TEXT,
            data TEXT,
            usuario TEXT,
            created_at TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_movimentacoes_created ON movimentacoes(created_at)")

    # sobras
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sobras (
            id TEXT PRIMARY KEY,
            material_id TEXT,
            descricao TEXT,
            quantidade REAL,
            unidade TEXT,
            data TEXT,
            status TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    # despesas
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS despesas (
            id TEXT PRIMARY KEY,
            descricao TEXT,
            valor REAL,
            categoria TEXT,
            data TEXT,
            created_at TEXT
        )
        """
    )

    # usuarios
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE,
            password_hash TEXT,
            role TEXT,
            created_at TEXT
        )
        """
    )
    # For older DBs, ensure role column exists
    try:
        cur.execute("PRAGMA table_info(usuarios)")
        cols = [r[1] for r in cur.fetchall()]
        if 'role' not in cols:
            cur.execute("ALTER TABLE usuarios ADD COLUMN role TEXT")
    except Exception:
        pass

    conn.commit()
    conn.close()


def carregar_json(nome_arquivo, seed=None):
    """Load a list of items from JSON file or from SQLite collections table when enabled."""
    if USE_SQLITE:
        name = os.path.splitext(nome_arquivo)[0]
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT data FROM collections WHERE name=? ORDER BY rowid DESC", (name,))
        rows = cur.fetchall()
        conn.close()
        if not rows and seed is not None:
            # seed DB from provided seed value
            salvar_json(nome_arquivo, seed)
            return seed
        return [json.loads(r[0]) for r in rows]

    caminho = os.path.join(DATA_DIR, nome_arquivo)
    if not os.path.exists(caminho):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(seed if seed is not None else [], f, ensure_ascii=False, indent=2)
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def salvar_json(nome_arquivo, dados):
    """Save a list of items into JSON file or into SQLite collections table when enabled.
    Each item must be a dict and will have an id field.
    """
    if USE_SQLITE:
        name = os.path.splitext(nome_arquivo)[0]
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # remove previous collection rows
        cur.execute("DELETE FROM collections WHERE name=?", (name,))
        for item in dados:
            _id = item.get("id") or str(uuid.uuid4())
            item["id"] = _id
            cur.execute("INSERT INTO collections(name, id, data) VALUES (?, ?, ?)", (name, _id, json.dumps(item, ensure_ascii=False)))
        conn.commit()
        conn.close()
        return

    os.makedirs(DATA_DIR, exist_ok=True)
    caminho = os.path.join(DATA_DIR, nome_arquivo)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def registrar_movimentacao(tipo, quantidade, unidade, motivo, material_nome=""):
    """Grava um evento no histórico (usado em Alertas e Relatórios). Mantém só os 200 mais recentes.
    Persiste em tabela movimentacoes quando USE_SQLITE está ativo, e mantém ainda o arquivo JSON legada
    para compatibilidade com código antigo.
    """
    usuario = session.get("user_id") if session else None
    data_text = datetime.now().strftime("%d/%m/%Y %H:%M")

    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO movimentacoes (id,tipo,material_nome,quantidade,unidade,motivo,data,usuario,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), tipo, material_nome, float(quantidade or 0), unidade, motivo or "Não informado", data_text, usuario, datetime.now().isoformat()),
            )
            # Keep only 200 latest rows
            cur.execute("DELETE FROM movimentacoes WHERE id NOT IN (SELECT id FROM movimentacoes ORDER BY created_at DESC LIMIT 200)")
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            conn.close()

    # legacy JSON fallback/update (kept for templates that read movimentacoes.json)
    movs = carregar_json("movimentacoes.json")
    movs.insert(0, {
        "id": str(uuid.uuid4()),
        "tipo": tipo,
        "material_nome": material_nome,
        "quantidade": float(quantidade or 0),
        "unidade": unidade,
        "motivo": motivo or "Não informado",
        "data": data_text,
        "usuario": usuario,
    })
    salvar_json("movimentacoes.json", movs[:200])


# ── Autenticação simples (usuários em collections 'usuarios') ─────────────────

def carregar_usuarios():
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios ORDER BY username")
        rows = cur.fetchall()
        conn.close()
        return [{
            "id": r["id"],
            "username": r["username"],
            "password_hash": r["password_hash"],
            "role": r["role"] if r["role"] is not None else "",
            "created_at": r["created_at"],
        } for r in rows]
    # legacy JSON fallback: each user dict may include role
    return carregar_json("usuarios.json", seed=[])


def salvar_usuarios(usuarios):
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("DELETE FROM usuarios")
            now = datetime.now().isoformat()
            for u in usuarios:
                _id = u.get("id") or str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO usuarios (id,username,password_hash,role,created_at) VALUES (?,?,?,?,?)",
                    (_id, u.get("username"), u.get("password_hash"), u.get("role") or "", u.get("created_at") or now),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return
    return salvar_json("usuarios.json", usuarios)


def encontrar_usuario_por_username(username):
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios WHERE username=?", (username,))
        r = cur.fetchone()
        conn.close()
        return {
            "id": r["id"],
            "username": r["username"],
            "password_hash": r["password_hash"],
            "role": r["role"] if r and r["role"] is not None else "",
            "created_at": r["created_at"],
        } if r else None

    usuarios = carregar_usuarios()
    for u in usuarios:
        if u.get("username") == username:
            return u
    return None


def criar_usuario_padrao_se_necessario():
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(1) FROM usuarios")
        cnt = cur.fetchone()[0]
        if cnt == 0:
            senha = os.environ.get("ADMIN_PASSWORD", "admin")
            uid = str(uuid.uuid4())
            cur.execute("INSERT INTO usuarios (id,username,password_hash,role,created_at) VALUES (?,?,?,?,?)", (uid, 'admin', generate_password_hash(senha), 'Admin', datetime.now().isoformat()))
            conn.commit()
        conn.close()
        return

    usuarios = carregar_usuarios()
    if not usuarios:
        senha = os.environ.get("ADMIN_PASSWORD", "admin")
        usuario = {
            "id": str(uuid.uuid4()),
            "username": "admin",
            "password_hash": generate_password_hash(senha),
            "role": 'Admin',
            "created_at": datetime.now().isoformat(),
        }
        usuarios.append(usuario)
        salvar_usuarios(usuarios)


criar_usuario_padrao_se_necessario()


def recreate_db_with_admin_forced():
    """If RECREATE_DB env var is set (1/true/yes), delete and recreate the SQLite DB and
    inject an 'admin' user with a generated password. Writes credentials to data/admin_credentials.txt
    so the operator can retrieve the password after starting the app.
    """
    if not USE_SQLITE:
        return
    if os.environ.get('RECREATE_DB', '').lower() not in ('1', 'true', 'yes'):
        return
    try:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
    except Exception:
        pass
    # Recreate schema
    init_db()
    pwd = secrets.token_urlsafe(10)
    uid = str(uuid.uuid4())
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("INSERT OR REPLACE INTO usuarios (id,username,password_hash,created_at) VALUES (?,?,?,?)", (uid, 'admin', generate_password_hash(pwd), now))
        conn.commit()
    finally:
        conn.close()
    os.makedirs(DATA_DIR, exist_ok=True)
    cred_path = os.path.join(DATA_DIR, 'admin_credentials.txt')
    try:
        with open(cred_path, 'w', encoding='utf-8') as f:
            f.write(f"username: admin\npassword: {pwd}\ncreated_at: {now}\n")
    except Exception:
        pass
    # Also print so logs/console show it when app starts
    print(f"RECREATE_DB: created {DB_PATH} and wrote admin credentials to {cred_path}")

# If the deploy/start command explicitly asks for recreation, do it now
if os.environ.get('RECREATE_DB', '').lower() in ('1','true','yes'):
    recreate_db_with_admin_forced()


ROLE_PERMISSIONS = {
    # endpoint_name: allowed_roles (Admin always allowed)
    'financeiro': ['Financeiro'],
    'financeiro_despesa': ['Financeiro'],
    'financeiro_despesa_excluir': ['Financeiro'],
    'estoque': ['Estoque'],
    'adicionar': ['Estoque'],
    'estoque_entrada': ['Estoque'],
    'estoque_excluir': ['Estoque'],
    'baixa': ['Estoque'],
    'sobras': ['Estoque'],
    'sobra_novo': ['Estoque'],
    'sobra_reaproveitar': ['Estoque'],
    'sobra_descartar': ['Estoque'],
    'sobra_excluir': ['Estoque'],
    'pedidos': ['Vendas','Producao'],
    'pedido_excluir': ['Vendas','Producao'],
    'pedido_status': ['Vendas','Producao'],
    'alertas': ['Relatorios','Financeiro','Estoque'],
    'exportar_financeiro_pdf': ['Financeiro','Relatorios'],
    'exportar_tudo_xlsx': ['Relatorios','Financeiro'],
    'exportar_tudo': ['Relatorios','Financeiro'],
    'usuarios': ['Admin'],
    'usuarios_novo': ['Admin'],
    'usuarios_excluir': ['Admin'],
}

@app.before_request
def require_login():
    # Allow these endpoints unauthenticated
    allowed = {"login", "static", "home", "em_construcao"}
    if request.endpoint is None:
        return
    if request.endpoint in allowed:
        return
    # load user into g for template access and role checks
    if session.get("user_id"):
        user_id = session.get("user_id")
        # try to find user by id
        user = None
        if USE_SQLITE:
            init_db()
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM usuarios WHERE id=?", (user_id,))
            r = cur.fetchone()
            conn.close()
            if r:
                user = {"id": r["id"], "username": r["username"], "role": r["role"] if r["role"] is not None else ""}
        else:
            usuarios = carregar_usuarios()
            user = next((u for u in usuarios if u.get("id") == user_id), None)
        g.user = user
        # Role based access control: if endpoint has permissions defined, enforce
        allowed_roles = ROLE_PERMISSIONS.get(request.endpoint)
        if allowed_roles:
            user_role = (g.user.get('role') or '') if g.user else ''
            if 'Admin' not in (user_role, ) and user_role not in allowed_roles:
                flash('Acesso negado: você não tem permissão para acessar esta área.')
                return redirect(url_for('home'))
        return
    return redirect(url_for("login", next=request.path))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        senha = request.form.get("password", "")
        user = encontrar_usuario_por_username(username)
        if user:
            stored = user.get("password_hash", "")
            # Backward/compatibility: allow a stored plaintext marker 'PLAIN:' for quick local setup
            if stored.startswith('PLAIN:'):
                if stored[len('PLAIN:'):] == senha:
                    session["user_id"] = user["id"]
                    flash("Autenticado com sucesso.")
                    nxt = request.args.get("next") or url_for("home")
                    return redirect(nxt)
            else:
                if check_password_hash(stored, senha):
                    session["user_id"] = user["id"]
                    flash("Autenticado com sucesso.")
                    nxt = request.args.get("next") or url_for("home")
                    return redirect(nxt)
        flash("Usuário ou senha inválidos.")
        return redirect(url_for("login"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("Desconectado.")
    return redirect(url_for("login"))


# Minha conta (trocar senha)
@app.route('/minha-conta', methods=['GET','POST'])
def minha_conta():
    if not g.get('user'):
        return redirect(url_for('login'))
    if request.method == 'POST':
        current = request.form.get('current_password','')
        new = request.form.get('new_password','')
        new2 = request.form.get('new_password2','')
        if new != new2:
            flash('Novas senhas não conferem.')
            return redirect(url_for('minha_conta'))
        user = encontrar_usuario_por_username(g.user.get('username'))
        if not user:
            flash('Usuário não encontrado.')
            return redirect(url_for('login'))
        stored = user.get('password_hash','')
        ok = False
        if stored.startswith('PLAIN:'):
            ok = (stored[len('PLAIN:'):] == current)
        else:
            ok = check_password_hash(stored, current)
        if not ok:
            flash('Senha atual inválida.')
            return redirect(url_for('minha_conta'))
        # update password
        new_hash = generate_password_hash(new)
        if USE_SQLITE:
            init_db()
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute('UPDATE usuarios SET password_hash=? WHERE id=?', (new_hash, g.user.get('id')))
            conn.commit()
            conn.close()
        else:
            usuarios = carregar_usuarios()
            for u in usuarios:
                if u.get('id') == g.user.get('id'):
                    u['password_hash'] = new_hash
            salvar_usuarios(usuarios)
        flash('Senha alterada com sucesso.')
        return redirect(url_for('home'))
    return render_template('minha_conta.html')


# ── Usuários (admin) ──────────────────────────────────────────────────────────
@app.route("/usuarios")
@requires_roles('Admin')
def usuarios():
    # only admin may list users
    if not (g.get('user') and g.user.get('role') == 'Admin'):
        flash('Acesso negado.')
        return redirect(url_for('home'))
    usuarios = carregar_usuarios()
    return render_template("usuarios.html", usuarios=usuarios)


@app.route("/usuarios/novo", methods=["GET", "POST"])\n@requires_roles('Admin') 
def usuarios_novo():
    # only admin may create users
    if not (g.get('user') and g.user.get('role') == 'Admin'):
        flash('Acesso negado.')
        return redirect(url_for('home'))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        role = request.form.get("role", "")

        if not username or not password:
            flash("Nome de usuário e senha são obrigatórios.")
            return redirect(url_for('usuarios_novo'))
        if password != password2:
            flash("As senhas não conferem.")
            return redirect(url_for('usuarios_novo'))
        exists = encontrar_usuario_por_username(username)
        if exists:
            flash("Já existe um usuário com este nome.")
            return redirect(url_for('usuarios_novo'))

        now = datetime.now().isoformat()
        uid = str(uuid.uuid4())
        password_hash = generate_password_hash(password)

        if USE_SQLITE:
            init_db()
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            try:
                cur.execute("INSERT INTO usuarios (id,username,password_hash,role,created_at) VALUES (?,?,?,?,?)", (uid, username, password_hash, role, now))
                conn.commit()
            except Exception as e:
                conn.rollback()
                flash('Erro ao criar usuário: ' + str(e))
                return redirect(url_for('usuarios_novo'))
            finally:
                conn.close()
        else:
            usuarios = carregar_usuarios()
            usuarios.append({
                'id': uid,
                'username': username,
                'password_hash': password_hash,
                'role': role,
                'created_at': now,
            })
            salvar_usuarios(usuarios)

        flash('Usuário criado com sucesso.')
        return redirect(url_for('usuarios'))

    return render_template('usuario_form.html')


@app.route('/usuarios/<user_id>/excluir', methods=['POST'])
@requires_roles('Admin')
def usuarios_excluir(user_id):
    # only admin can remove users
    if not (g.get('user') and g.user.get('role') == 'Admin'):
        flash('Acesso negado.')
        return redirect(url_for('home'))

    # Prevent removing the last user accidentally
    usuarios = carregar_usuarios()
    if len(usuarios) <= 1:
        flash('Não é possível remover o último usuário.')
        return redirect(url_for('usuarios'))

    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        try:
            cur.execute('DELETE FROM usuarios WHERE id=?', (user_id,))
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            conn.close()
    else:
        usuarios = [u for u in usuarios if u.get('id') != user_id]
        salvar_usuarios(usuarios)

    flash('Usuário removido.')
    return redirect(url_for('usuarios'))


# Edit user (role, optional password)
@app.route('/usuarios/<user_id>/editar', methods=['GET','POST'])
@requires_roles('Admin')
def usuarios_editar(user_id):
    if not (g.get('user') and g.user.get('role') == 'Admin'):
        flash('Acesso negado.')
        return redirect(url_for('home'))

    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute('SELECT * FROM usuarios WHERE id=?', (user_id,))
        r = cur.fetchone()
        conn.close()
        if not r:
            flash('Usuário não encontrado.')
            return redirect(url_for('usuarios'))
        usuario = {"id": r['id'], 'username': r['username'], 'role': r['role']}
    else:
        usuarios = carregar_usuarios()
        usuario = next((u for u in usuarios if u.get('id') == user_id), None)
        if not usuario:
            flash('Usuário não encontrado.')
            return redirect(url_for('usuarios'))

    if request.method == 'POST':
        role = request.form.get('role','')
        new_pwd = request.form.get('password','')
        if USE_SQLITE:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            try:
                if new_pwd:
                    cur.execute('UPDATE usuarios SET role=?, password_hash=?, updated_at=? WHERE id=?', (role, generate_password_hash(new_pwd), datetime.now().isoformat(), user_id))
                else:
                    cur.execute('UPDATE usuarios SET role=?, updated_at=? WHERE id=?', (role, datetime.now().isoformat(), user_id))
                conn.commit()
            except Exception:
                conn.rollback()
            finally:
                conn.close()
        else:
            usuarios = carregar_usuarios()
            for u in usuarios:
                if u.get('id') == user_id:
                    u['role'] = role
                    if new_pwd:
                        u['password_hash'] = generate_password_hash(new_pwd)
            salvar_usuarios(usuarios)
        flash('Usuário atualizado.')
        return redirect(url_for('usuarios'))

    return render_template('usuario_edit.html', usuario=usuario)


# ── Materiais (estoque) ───────────────────────────────────────────────────────
def carregar_materiais():
    # When using SQLite, read from the proper 'materiais' table with a transaction.
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(1) as cnt FROM materiais")
        cnt = cur.fetchone()[0]
        if cnt == 0 and os.path.exists(SEED_FILE):
            # seed the table from the JSON seed file
            try:
                with open(SEED_FILE, encoding="utf-8") as f:
                    seed = json.load(f)
            except Exception:
                seed = []
            if seed:
                now = datetime.now().isoformat()
                to_insert = []
                for m in seed:
                    _id = m.get("id") or str(uuid.uuid4())
                    to_insert.append((
                        _id,
                        m.get("nome"),
                        m.get("categoria"),
                        m.get("emoji"),
                        float(m.get("quantidade") or 0),
                        m.get("unidade"),
                        float(m.get("quantidade_minima") or 0),
                        float(m.get("custo") or 0),
                        m.get("gtin"),
                        m.get("foto"),
                        now,
                        now,
                    ))
                cur.executemany(
                    "INSERT OR IGNORE INTO materiais (id,nome,categoria,emoji,quantidade,unidade,quantidade_minima,custo,gtin,foto,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    to_insert,
                )
                conn.commit()
        cur.execute("SELECT * FROM materiais ORDER BY nome COLLATE NOCASE")
        rows = cur.fetchall()
        conn.close()
        # convert rows to dicts matching previous JSON structure
        result = []
        for r in rows:
            result.append({
                "id": r["id"],
                "nome": r["nome"],
                "categoria": r["categoria"],
                "emoji": r["emoji"],
                "quantidade": r["quantidade"],
                "unidade": r["unidade"],
                "quantidade_minima": r["quantidade_minima"],
                "custo": r["custo"],
                "gtin": r["gtin"],
                "foto": r["foto"],
            })
        return result

    if not os.path.exists(DATA_FILE):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SEED_FILE, encoding="utf-8") as f:
            seed = json.load(f)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(seed, f, ensure_ascii=False, indent=2)
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def salvar_materiais(materiais):
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        try:
            # Use a transaction to atomically replace the materials set.
            cur.execute("BEGIN IMMEDIATE")
            # We'll upsert per id to preserve uniqueness constraints
            # Clear names that are no longer present
            incoming_ids = [m.get("id") for m in materiais if m.get("id")]
            if incoming_ids:
                # delete any rows not in incoming_ids
                placeholders = ",".join(["?" for _ in incoming_ids])
                cur.execute(f"DELETE FROM materiais WHERE id NOT IN ({placeholders})", incoming_ids)
            else:
                cur.execute("DELETE FROM materiais")

            now = datetime.now().isoformat()
            for m in materiais:
                _id = m.get("id") or str(uuid.uuid4())
                cur.execute(
                    "INSERT OR REPLACE INTO materiais (id,nome,categoria,emoji,quantidade,unidade,quantidade_minima,custo,gtin,foto,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,COALESCE((SELECT created_at FROM materiais WHERE id=?),?),?)",
                    (
                        _id,
                        m.get("nome"),
                        m.get("categoria"),
                        m.get("emoji"),
                        float(m.get("quantidade") or 0),
                        m.get("unidade"),
                        float(m.get("quantidade_minima") or 0),
                        float(m.get("custo") or 0),
                        m.get("gtin"),
                        m.get("foto"),
                        _id,
                        now,
                        now,
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return

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
@requires_roles('Estoque')
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


@app.route("/estoque/<material_id>/entrada", methods=["POST"])\n@requires_roles('Estoque')
def estoque_entrada(material_id):
    materiais = carregar_materiais()
    m = encontrar(materiais, material_id)
    if m:
        try:
            qtd = float(request.form.get("quantidade", 0))
        except ValueError:
            qtd = 0
        motivo = request.form.get("motivo", "").strip()
        if qtd > 0:
            m["quantidade"] = round(m["quantidade"] + qtd, 3)
            salvar_materiais(materiais)
            registrar_movimentacao("entrada", qtd, m["unidade"], motivo or "Entrada manual de estoque", m["nome"])
            flash(f"Entrada registrada em {m['nome']}.")
    return redirect(url_for("estoque"))


@app.route("/estoque/<material_id>/excluir", methods=["POST"])\n@requires_roles('Estoque')
def estoque_excluir(material_id):
    # Remove material and its photo (if present). Works with JSON or SQLite backend.
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT foto FROM materiais WHERE id=?", (material_id,))
        r = cur.fetchone()
        if r and r["foto"]:
            caminho = os.path.join(DATA_DIR, 'uploads', r["foto"])
            try:
                if os.path.exists(caminho):
                    os.remove(caminho)
            except Exception:
                pass
        cur.execute("DELETE FROM materiais WHERE id=?", (material_id,))
        conn.commit()
        conn.close()
        flash("Material removido.")
        return redirect(url_for("estoque"))

    materiais = carregar_materiais()
    to_remove = next((m for m in materiais if m["id"] == material_id), None)
    if to_remove and to_remove.get("foto"):
        caminho = os.path.join(DATA_DIR, 'uploads', to_remove.get('foto'))
        try:
            if os.path.exists(caminho):
                os.remove(caminho)
        except Exception:
            pass
    materiais = [m for m in materiais if m["id"] != material_id]
    salvar_materiais(materiais)
    flash("Material removido.")
    return redirect(url_for("estoque"))


@app.route("/adicionar", methods=["GET", "POST"])\n@requires_roles('Estoque')
def adicionar():
    materiais = carregar_materiais()

    if request.method == "POST":
        # Basic form token to avoid duplicate submissions
        token = request.form.get('form_token')
        expected = session.pop('form_token', None)
        if not token or token != expected:
            flash('Formulário já foi enviado ou token inválido. Por favor, tente novamente.')
            return redirect(url_for('adicionar'))

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

        # Basic duplicate prevention: same name + gtin
        existe = next((m for m in materiais if m["nome"].strip().lower() == nome.lower() and (m.get("gtin") or "") == gtin), None)
        if existe:
            flash("Material com mesmo nome/GTIN já existe no estoque.")
            return redirect(url_for("adicionar"))

        novo_id = str(uuid.uuid4())
        novo = {
            "id": novo_id,
            "nome": nome,
            "categoria": categoria,
            "emoji": CATEGORIAS_EMOJI.get(categoria, "🔹"),
            "quantidade": quantidade,
            "unidade": request.form.get("unidade", "unidades"),
            "quantidade_minima": quantidade_minima,
            "custo": custo,
            "gtin": gtin,
        }

        # Handle optional photo upload
        foto = None
        if 'foto' in request.files:
            f = request.files.get('foto')
            if f and f.filename:
                os.makedirs(os.path.join(DATA_DIR, 'uploads'), exist_ok=True)
                filename = secure_filename(f"{novo_id}_{f.filename}")
                caminho = os.path.join(DATA_DIR, 'uploads', filename)
                f.save(caminho)
                novo['foto'] = filename

        materiais.append(novo)
        salvar_materiais(materiais)
        flash(f"{nome} adicionado ao estoque.")
        return redirect(url_for("estoque"))

    # dados usados pela busca (nome/gtin) que ajuda a evitar duplicados
    lista_busca = [
        {"id": m["id"], "nome": m["nome"], "gtin": m.get("gtin") or "", "quantidade": m["quantidade"], "unidade": m["unidade"]}
        for m in materiais
    ]
    # generate a one-time token to prevent duplicate form submits
    session['form_token'] = str(uuid.uuid4())
    return render_template(
        "adicionar.html",
        categorias=CATEGORIAS_EMOJI,
        unidades=UNIDADES,
        materiais_json=lista_busca,
        form_token=session['form_token'],
    )


@app.route("/baixa", methods=["GET", "POST"])\n@requires_roles('Estoque')
def baixa():
    materiais = carregar_materiais()

    if request.method == "POST":
        material_id = request.form.get("material_id")
        m = encontrar(materiais, material_id)
        try:
            qtd = float(request.form.get("quantidade", 0))
        except ValueError:
            qtd = 0
        motivo = request.form.get("motivo", "").strip()
        if m and qtd > 0:
            m["quantidade"] = round(max(0, m["quantidade"] - qtd), 3)
            salvar_materiais(materiais)
            registrar_movimentacao("baixa", qtd, m["unidade"], motivo, m["nome"])
            flash(f"Baixa registrada em {m['nome']}.")
        return redirect(url_for("baixa"))

    mid_preselecionado = request.args.get("mid", "")
    return render_template(
        "baixa.html",
        materiais=materiais,
        motivos=MOTIVOS_BAIXA,
        mid_preselecionado=mid_preselecionado,
    )


# ── Produtos & Receitas ───────────────────────────────────────────────────────
def carregar_produtos():
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM produtos ORDER BY nome COLLATE NOCASE")
        rows = cur.fetchall()
        conn.close()
        res = []
        for r in rows:
            receita = []
            try:
                receita = json.loads(r["receita"]) if r["receita"] else []
            except Exception:
                receita = []
            res.append({
                "id": r["id"],
                "nome": r["nome"],
                "emoji": r["emoji"],
                "preco_venda": r["preco_venda"],
                "receita": receita,
            })
        return res
    return carregar_json("produtos.json")


def salvar_produtos(produtos):
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("DELETE FROM produtos")
            now = datetime.now().isoformat()
            for p in produtos:
                _id = p.get("id") or str(uuid.uuid4())
                cur.execute(
                    "INSERT INTO produtos (id,nome,emoji,preco_venda,receita,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                    (_id, p.get("nome"), p.get("emoji"), float(p.get("preco_venda") or 0), json.dumps(p.get("receita") or [] , ensure_ascii=False), now, now),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return
    return salvar_json("produtos.json", produtos)


def calcular_produto(produto, mat_map):
    """Anexa custo estimado, margem e a receita já resolvida com nome/emoji/unidade dos materiais."""
    custo = 0.0
    receita_detalhada = []
    for item in produto.get("receita", []):
        m = mat_map.get(item["material_id"])
        if m:
            custo += m["custo"] * item["quantidade"]
            receita_detalhada.append({
                "nome": m["nome"], "emoji": m["emoji"],
                "quantidade": item["quantidade"], "unidade": m["unidade"],
                "disponivel": m["quantidade"],
            })
        else:
            receita_detalhada.append({
                "nome": "Material removido", "emoji": "❓",
                "quantidade": item["quantidade"], "unidade": "", "disponivel": None,
            })
    p = dict(produto)
    p["custo_estimado"] = round(custo, 2)
    p["margem"] = round(produto.get("preco_venda", 0) - custo, 2)
    p["receita_detalhada"] = receita_detalhada
    return p


@app.route("/produtos")
@requires_roles('Producao','Vendas')
def produtos():
    lista = carregar_produtos()
    mat_map = {m["id"]: m for m in carregar_materiais()}
    produtos_calc = [calcular_produto(p, mat_map) for p in lista]
    return render_template("produtos.html", produtos=produtos_calc)


@app.route("/produtos/novo", methods=["GET", "POST"])\n@requires_roles('Producao','Vendas')
def produto_novo():
    materiais = carregar_materiais()

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        emoji = request.form.get("emoji", "👜").strip() or "👜"
        try:
            preco_venda = float(request.form.get("preco_venda", 0) or 0)
        except ValueError:
            preco_venda = 0

        mat_ids = request.form.getlist("material_id[]")
        qtds = request.form.getlist("material_qtd[]")
        receita = []
        for mid, q in zip(mat_ids, qtds):
            if not mid:
                continue
            try:
                qf = float(q)
            except ValueError:
                continue
            if qf <= 0:
                continue
            receita.append({"material_id": mid, "quantidade": qf})

        if not nome:
            flash("Informe o nome do produto.")
            return redirect(url_for("produto_novo"))

        produtos_lista = carregar_produtos()
        produtos_lista.append({
            "id": str(uuid.uuid4()),
            "nome": nome,
            "emoji": emoji,
            "preco_venda": preco_venda,
            "receita": receita,
        })
        salvar_produtos(produtos_lista)
        flash(f"{nome} cadastrado em Produtos & Receitas.")
        return redirect(url_for("produtos"))

    return render_template("produto_form.html", materiais=materiais, emojis=EMOJIS_PRODUTO)


@app.route("/produtos/<produto_id>/excluir", methods=["POST"])\n@requires_roles('Producao','Vendas')
def produto_excluir(produto_id):
    produtos_lista = carregar_produtos()
    produtos_lista = [p for p in produtos_lista if p["id"] != produto_id]
    salvar_produtos(produtos_lista)
    flash("Produto removido.")
    return redirect(url_for("produtos"))


# ── Pedidos dos Clientes ──────────────────────────────────────────────────────
@app.route("/pedidos")
@requires_roles('Vendas','Producao')
def pedidos():
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM pedidos ORDER BY data_pedido_iso DESC")
        rows = cur.fetchall()
        conn.close()
        res = []
        for r in rows:
            res.append({
                "id": r["id"],
                "cliente": r["cliente"],
                "produto_id": r["produto_id"],
                "produto_nome": r["produto_nome"],
                "produto_emoji": r["produto_emoji"],
                "quantidade": r["quantidade"],
                "preco_unitario": r["preco_unitario"],
                "valor_total": r["valor_total"],
                "status": r["status"],
                "materiais_baixados": bool(r["materiais_baixados"]),
                "data_pedido": r["data_pedido"],
                "data_pedido_iso": r["data_pedido_iso"],
                "observacoes": r["observacoes"],
            })
        return render_template("pedidos.html", pedidos=res, status_lista=STATUS_PEDIDO, status_badge=STATUS_PEDIDO_BADGE)

    lista = carregar_json("pedidos.json")
    lista_ordenada = sorted(lista, key=lambda p: p.get("data_pedido_iso", ""), reverse=True)
    return render_template("pedidos.html", pedidos=lista_ordenada, status_lista=STATUS_PEDIDO,
                            status_badge=STATUS_PEDIDO_BADGE)


@app.route("/pedidos/novo", methods=["GET", "POST"])\n@requires_roles('Vendas')
def pedido_novo():
    produtos_lista = carregar_produtos() if USE_SQLITE else carregar_json("produtos.json")

    if request.method == "POST":
        cliente = request.form.get("cliente", "").strip()
        produto_id = request.form.get("produto_id", "")
        try:
            quantidade = int(request.form.get("quantidade", 1) or 1)
        except ValueError:
            quantidade = 1
        observacoes = request.form.get("observacoes", "").strip()

        produto = next((p for p in produtos_lista if p["id"] == produto_id), None)
        if not cliente or not produto or quantidade <= 0:
            flash("Preencha cliente, produto e uma quantidade válida.")
            return redirect(url_for("pedido_novo"))

        preco_unit = produto.get("preco_venda", 0)
        agora = datetime.now()
        novo = {
            "id": str(uuid.uuid4()),
            "cliente": cliente,
            "produto_id": produto_id,
            "produto_nome": produto["nome"],
            "produto_emoji": produto.get("emoji", "👜"),
            "quantidade": quantidade,
            "preco_unitario": preco_unit,
            "valor_total": round(preco_unit * quantidade, 2),
            "status": "Pendente",
            "materiais_baixados": False,
            "data_pedido": agora.strftime("%d/%m/%Y"),
            "data_pedido_iso": agora.strftime("%Y-%m-%d %H:%M:%S"),
            "observacoes": observacoes,
        }
        if USE_SQLITE:
            init_db()
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO pedidos (id,cliente,produto_id,produto_nome,produto_emoji,quantidade,preco_unitario,valor_total,status,materiais_baixados,data_pedido,data_pedido_iso,observacoes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    novo["id"], novo["cliente"], novo["produto_id"], novo["produto_nome"], novo["produto_emoji"], novo["quantidade"], novo["preco_unitario"], novo["valor_total"], novo["status"], 0, novo["data_pedido"], novo["data_pedido_iso"], novo["observacoes"], agora.isoformat(), agora.isoformat()
                )
            )
            conn.commit()
            conn.close()
        else:
            pedidos_lista = carregar_json("pedidos.json")
            pedidos_lista.append(novo)
            salvar_json("pedidos.json", pedidos_lista)
        flash(f"Pedido de {cliente} registrado.")
        return redirect(url_for("pedidos"))

    return render_template("pedido_form.html", produtos=produtos_lista)


@app.route("/pedidos/<pedido_id>/status", methods=["POST"])\n@requires_roles('Vendas','Producao')
def pedido_status(pedido_id):
    novo_status = request.form.get("status", "")
    if novo_status not in STATUS_PEDIDO:
        flash("Status inválido.")
        return redirect(url_for("pedidos"))

    if USE_SQLITE:
        # perform transactional status update and material deduction if necessary
        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("SELECT * FROM pedidos WHERE id=?", (pedido_id,))
            p = cur.fetchone()
            if not p:
                conn.rollback()
                flash("Pedido não encontrado.")
                return redirect(url_for("pedidos"))
            # update status
            cur.execute("UPDATE pedidos SET status=?, updated_at=? WHERE id=?", (novo_status, datetime.now().isoformat(), pedido_id))

            # if concluding production, deduct materials only once
            if novo_status == "Concluído" and not p["materiais_baixados"]:
                # load product recipe
                cur.execute("SELECT * FROM produtos WHERE id=?", (p["produto_id"],))
                pr = cur.fetchone()
                if pr and pr["receita"]:
                    receita = []
                    try:
                        receita = json.loads(pr["receita"])
                    except Exception:
                        receita = []
                    for item in receita:
                        mat_id = item.get("material_id")
                        qtd_por_unidade = float(item.get("quantidade") or 0)
                        total = round(qtd_por_unidade * p["quantidade"], 3)
                        # decrement material quantity
                        cur.execute("SELECT quantidade, unidade, nome FROM materiais WHERE id=?", (mat_id,))
                        mat = cur.fetchone()
                        if mat:
                            nova = max(0, float(mat["quantidade"]) - total)
                            cur.execute("UPDATE materiais SET quantidade=?, updated_at=? WHERE id=?", (nova, datetime.now().isoformat(), mat_id))
                            # registrar movimentacao into collections table as legacy JSON storage
                            movs = carregar_json("movimentacoes.json")
                            movs.insert(0, {
                                "id": str(uuid.uuid4()),
                                "tipo": "producao",
                                "material_nome": mat["nome"],
                                "quantidade": total,
                                "unidade": mat["unidade"],
                                "motivo": f"Produção — pedido de {p['cliente']}",
                                "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
                                "usuario": session.get("user_id") if session else None,
                            })
                            salvar_json("movimentacoes.json", movs[:200])
                    cur.execute("UPDATE pedidos SET materiais_baixados=1, updated_at=? WHERE id=?", (datetime.now().isoformat(), pedido_id))
            conn.commit()
            flash(f"Pedido atualizado para \"{novo_status}\".")
        except Exception as e:
            conn.rollback()
            flash("Erro ao atualizar pedido: " + str(e))
        finally:
            conn.close()
        return redirect(url_for("pedidos"))

    # legacy JSON path
    pedidos_lista = carregar_json("pedidos.json")
    pedido = next((p for p in pedidos_lista if p["id"] == pedido_id), None)
    if pedido:
        pedido["status"] = novo_status

        # Ao concluir a produção, dá baixa automática dos materiais da receita (só na 1ª vez).
        if novo_status == "Concluído" and not pedido.get("materiais_baixados"):
            produto = next((pr for pr in carregar_json("produtos.json") if pr["id"] == pedido["produto_id"]), None)
            if produto and produto.get("receita"):
                materiais = carregar_materiais()
                for item in produto["receita"]:
                    m = encontrar(materiais, item["material_id"])
                    if m:
                        total = round(item["quantidade"] * pedido["quantidade"], 3)
                        m["quantidade"] = round(max(0, m["quantidade"] - total), 3)
                        registrar_movimentacao("producao", total, m["unidade"],
                                                f"Produção — pedido de {pedido['cliente']}", m["nome"])
                salvar_materiais(materiais)
            pedido["materiais_baixados"] = True

    salvar_json("pedidos.json", pedidos_lista)
    flash(f"Pedido de {pedido['cliente']} atualizado para \"{novo_status}\".")
    return redirect(url_for("pedidos"))


@app.route("/pedidos/<pedido_id>/excluir", methods=["POST"])\n@requires_roles('Vendas','Producao')
def pedido_excluir(pedido_id):
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM pedidos WHERE id=?", (pedido_id,))
        conn.commit()
        conn.close()
        flash("Pedido removido.")
        return redirect(url_for("pedidos"))

    pedidos_lista = carregar_json("pedidos.json")
    pedidos_lista = [p for p in pedidos_lista if p["id"] != pedido_id]
    salvar_json("pedidos.json", pedidos_lista)
    flash("Pedido removido.")
    return redirect(url_for("pedidos"))


# ── Sobras e Reaproveitamento ──────────────────────────────────────────────────
@app.route("/sobras")
@requires_roles('Estoque')
def sobras():
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM sobras ORDER BY created_at DESC")
        rows = cur.fetchall()
        conn.close()
        sobs = []
        for r in rows:
            sobs.append({
                "id": r["id"],
                "material_id": r["material_id"],
                "descricao": r["descricao"],
                "quantidade": r["quantidade"],
                "unidade": r["unidade"],
                "data": r["data"],
                "status": r["status"],
            })
        return render_template("sobras.html", sobras=sobs, status_badge=STATUS_SOBRA_BADGE)

    lista = carregar_json("sobras.json")
    return render_template("sobras.html", sobras=list(reversed(lista)), status_badge=STATUS_SOBRA_BADGE)


@app.route("/sobras/novo", methods=["GET", "POST"])\n@requires_roles('Estoque')
def sobra_novo():
    materiais = carregar_materiais()

    if request.method == "POST":
        material_id = request.form.get("material_id", "")
        descricao = request.form.get("descricao", "").strip()
        try:
            quantidade = float(request.form.get("quantidade", 0) or 0)
        except ValueError:
            quantidade = 0

        m = encontrar(materiais, material_id) if material_id else None
        unidade = m["unidade"] if m else request.form.get("unidade", "unidades")
        nome_final = descricao or (m["nome"] if m else "Sobra sem descrição")

        if quantidade <= 0:
            flash("Informe uma quantidade válida.")
            return redirect(url_for("sobra_novo"))

        if USE_SQLITE:
            init_db()
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            now = datetime.now().isoformat()
            cur.execute("INSERT INTO sobras (id,material_id,descricao,quantidade,unidade,data,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (str(uuid.uuid4()), material_id, nome_final, quantidade, unidade, datetime.now().strftime("%d/%m/%Y"), "Disponível", now, now))
            conn.commit()
            conn.close()
        else:
            sobras_lista = carregar_json("sobras.json")
            sobras_lista.append({
                "id": str(uuid.uuid4()),
                "material_id": material_id,
                "descricao": nome_final,
                "quantidade": quantidade,
                "unidade": unidade,
                "data": datetime.now().strftime("%d/%m/%Y"),
                "status": "Disponível",
            })
            salvar_json("sobras.json", sobras_lista)
        flash(f"Sobra de {nome_final} registrada.")
        return redirect(url_for("sobras"))

    return render_template("sobra_form.html", materiais=materiais)


@app.route("/sobras/<sobra_id>/reaproveitar", methods=["POST"])\n@requires_roles('Estoque')
def sobra_reaproveitar(sobra_id):
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM sobras WHERE id=?", (sobra_id,))
        s = cur.fetchone()
        if s and s["status"] == "Disponível":
            if s["material_id"]:
                # increment material quantity
                cur.execute("SELECT quantidade, unidade, nome FROM materiais WHERE id=?", (s["material_id"],))
                mat = cur.fetchone()
                if mat:
                    nova = round(float(mat["quantidade"]) + float(s["quantidade"]), 3)
                    cur.execute("UPDATE materiais SET quantidade=?, updated_at=? WHERE id=?", (nova, datetime.now().isoformat(), s["material_id"]))
                    # register movimentacao
                    registrar_movimentacao("reaproveitamento", s["quantidade"], s["unidade"], "Sobra reaproveitada de volta ao estoque", mat["nome"]) 
            cur.execute("UPDATE sobras SET status=?, updated_at=? WHERE id=?", ("Reaproveitado", datetime.now().isoformat(), sobra_id))
            conn.commit()
            conn.close()
            flash("Sobra reaproveitada com sucesso.")
        return redirect(url_for("sobras"))

    sobras_lista = carregar_json("sobras.json")
    sobra = next((s for s in sobras_lista if s["id"] == sobra_id), None)
    if sobra and sobra["status"] == "Disponível":
        if sobra.get("material_id"):
            materiais = carregar_materiais()
            m = encontrar(materiais, sobra["material_id"])
            if m:
                m["quantidade"] = round(m["quantidade"] + sobra["quantidade"], 3)
                salvar_materiais(materiais)
                registrar_movimentacao("reaproveitamento", sobra["quantidade"], sobra["unidade"],
                                        "Sobra reaproveitada de volta ao estoque", m["nome"])
        sobra["status"] = "Reaproveitado"
        salvar_json("sobras.json", sobras_lista)
        flash(f"{sobra['descricao']} reaproveitada com sucesso.")
    return redirect(url_for("sobras"))


@app.route("/sobras/<sobra_id>/descartar", methods=["POST"])\n@requires_roles('Estoque')
def sobra_descartar(sobra_id):
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT status FROM sobras WHERE id=?", (sobra_id,))
        r = cur.fetchone()
        if r and r[0] == "Disponível":
            cur.execute("UPDATE sobras SET status=?, updated_at=? WHERE id=?", ("Descartado", datetime.now().isoformat(), sobra_id))
            conn.commit()
        conn.close()
        flash("Sobra marcada como descartada.")
        return redirect(url_for("sobras"))

    sobras_lista = carregar_json("sobras.json")
    sobra = next((s for s in sobras_lista if s["id"] == sobra_id), None)
    if sobra and sobra["status"] == "Disponível":
        sobra["status"] = "Descartado"
        salvar_json("sobras.json", sobras_lista)
        flash(f"{sobra['descricao']} marcada como descartada.")
    return redirect(url_for("sobras"))


@app.route("/sobras/<sobra_id>/excluir", methods=["POST"])\n@requires_roles('Estoque')
def sobra_excluir(sobra_id):
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM sobras WHERE id=?", (sobra_id,))
        conn.commit()
        conn.close()
        flash("Registro removido.")
        return redirect(url_for("sobras"))

    sobras_lista = carregar_json("sobras.json")
    sobras_lista = [s for s in sobras_lista if s["id"] != sobra_id]
    salvar_json("sobras.json", sobras_lista)
    flash("Registro removido.")
    return redirect(url_for("sobras"))


# ── Financeiro ─────────────────────────────────────────────────────────────────
@app.route("/financeiro")
@requires_roles('Financeiro','Relatorios')
def financeiro():
    materiais = carregar_materiais()
    valor_estoque = round(sum(m["quantidade"] * m["custo"] for m in materiais), 2)

    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM pedidos")
        pedidos_rows = cur.fetchall()
        pedidos_lista = [{
            "id": r["id"],
            "status": r["status"],
            "valor_total": r["valor_total"],
        } for r in pedidos_rows]
        receita_entregue = round(sum(p["valor_total"] for p in pedidos_lista if p["status"] == "Entregue"), 2)
        receita_prevista = round(sum(p["valor_total"] for p in pedidos_lista if p["status"] in ("Pendente", "Em produção", "Concluído")), 2)

        cur.execute("SELECT * FROM despesas ORDER BY created_at DESC")
        despesas_rows = cur.fetchall()
        despesas = [{"id": r["id"], "descricao": r["descricao"], "valor": r["valor"], "categoria": r["categoria"], "data": r["data"]} for r in despesas_rows]
        conn.close()
        total_despesas = round(sum(d["valor"] for d in despesas), 2)
        lucro = round(receita_entregue - total_despesas, 2)

        return render_template(
            "financeiro.html",
            valor_estoque=valor_estoque,
            receita_entregue=receita_entregue,
            receita_prevista=receita_prevista,
            despesas=list(reversed(despesas)),
            total_despesas=total_despesas,
            lucro=lucro,
            categorias_despesa=CATEGORIAS_DESPESA,
        )

    # legacy JSON path
    pedidos_lista = carregar_json("pedidos.json")
    receita_entregue = round(sum(p["valor_total"] for p in pedidos_lista if p["status"] == "Entregue"), 2)
    receita_prevista = round(
        sum(p["valor_total"] for p in pedidos_lista if p["status"] in ("Pendente", "Em produção", "Concluído")), 2
    )

    despesas = carregar_json("despesas.json")
    total_despesas = round(sum(d["valor"] for d in despesas), 2)
    lucro = round(receita_entregue - total_despesas, 2)

    return render_template(
        "financeiro.html",
        valor_estoque=valor_estoque,
        receita_entregue=receita_entregue,
        receita_prevista=receita_prevista,
        despesas=list(reversed(despesas)),
        total_despesas=total_despesas,
        lucro=lucro,
        categorias_despesa=CATEGORIAS_DESPESA,
    )


@app.route("/financeiro/despesa", methods=["POST"])\n@requires_roles('Financeiro')
def financeiro_despesa():
    descricao = request.form.get("descricao", "").strip()
    try:
        valor = float(request.form.get("valor", 0) or 0)
    except ValueError:
        valor = 0
    categoria = request.form.get("categoria", "Outros")

    if not descricao or valor <= 0:
        flash("Informe descrição e valor válidos para a despesa.")
        return redirect(url_for("financeiro"))

    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        now = datetime.now().isoformat()
        cur.execute("INSERT INTO despesas (id,descricao,valor,categoria,data,created_at) VALUES (?,?,?,?,?,?)",
                    (str(uuid.uuid4()), descricao, float(valor), categoria, datetime.now().strftime("%d/%m/%Y"), now))
        conn.commit()
        conn.close()
        flash(f'Despesa "{descricao}" registrada.')
        return redirect(url_for("financeiro"))

    despesas = carregar_json("despesas.json")
    despesas.append({
        "id": str(uuid.uuid4()),
        "descricao": descricao,
        "valor": valor,
        "categoria": categoria,
        "data": datetime.now().strftime("%d/%m/%Y"),
    })
    salvar_json("despesas.json", despesas)
    flash(f'Despesa "{descricao}" registrada.')
    return redirect(url_for("financeiro"))


@app.route("/financeiro/despesa/<despesa_id>/excluir", methods=["POST"])\n@requires_roles('Financeiro')
def financeiro_despesa_excluir(despesa_id):
    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM despesas WHERE id=?", (despesa_id,))
        conn.commit()
        conn.close()
        flash("Despesa removida.")
        return redirect(url_for("financeiro"))

    despesas = carregar_json("despesas.json")
    despesas = [d for d in despesas if d["id"] != despesa_id]
    salvar_json("despesas.json", despesas)
    flash("Despesa removida.")
    return redirect(url_for("financeiro"))


# ── Alertas e Relatórios ───────────────────────────────────────────────────────
@app.route("/alertas")
@requires_roles('Relatorios','Financeiro','Estoque')
def alertas():
    materiais = carregar_materiais()
    baixo_estoque = sorted(
        [m for m in materiais if m["quantidade"] <= m["quantidade_minima"]],
        key=lambda m: m["quantidade"],
    )
    zerados = [m for m in baixo_estoque if m["quantidade"] == 0]
    valor_em_risco = round(sum(m["quantidade_minima"] * m["custo"] for m in baixo_estoque), 2)

    por_categoria = {}
    for m in materiais:
        c = por_categoria.setdefault(m["categoria"], {"qtd_itens": 0, "valor": 0.0, "emoji": m["emoji"]})
        c["qtd_itens"] += 1
        c["valor"] += m["quantidade"] * m["custo"]
    for c in por_categoria.values():
        c["valor"] = round(c["valor"], 2)

    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM movimentacoes ORDER BY created_at DESC LIMIT 30")
        rows = cur.fetchall()
        movimentacoes = []
        for r in rows:
            movimentacoes.append({
                "id": r["id"],
                "tipo": r["tipo"],
                "material_nome": r["material_nome"],
                "quantidade": r["quantidade"],
                "unidade": r["unidade"],
                "motivo": r["motivo"],
                "data": r["data"],
                "usuario": r["usuario"],
            })
        conn.close()
    else:
        movimentacoes = carregar_json("movimentacoes.json")[:30]

    return render_template(
        "alertas.html",
        baixo_estoque=baixo_estoque,
        zerados=zerados,
        valor_em_risco=valor_em_risco,
        por_categoria=por_categoria,
        movimentacoes=movimentacoes,
        total_materiais=len(materiais),
    )


# Serve uploaded files
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    uploads_dir = os.path.join(DATA_DIR, 'uploads')
    return send_from_directory(uploads_dir, filename)


# Exportar todos os dados (backup)
@app.route("/exportar")
@requires_roles('Relatorios','Financeiro')
def exportar_tudo():
    colecoes = [
        "materiais.json",
        "produtos.json",
        "pedidos.json",
        "movimentacoes.json",
        "sobras.json",
        "despesas.json",
    ]
    tudo = {}
    for c in colecoes:
        tudo[os.path.splitext(c)[0]] = carregar_json(c)
    resp = make_response(json.dumps(tudo, ensure_ascii=False, indent=2))
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=export_all.json"
    return resp


# Exportar relatório financeiro em PDF
@app.route('/exportar/pdf')
@requires_roles('Relatorios','Financeiro')
def exportar_financeiro_pdf():
    try:
        from io import BytesIO
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
    except Exception:
        return ("Biblioteca ReportLab não instalada. Instale com: pip install reportlab"), 400

    materiais = carregar_materiais()
    valor_estoque = round(sum(m.get("quantidade", 0) * m.get("custo", 0) for m in materiais), 2)

    if USE_SQLITE:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM pedidos")
        pedidos_rows = cur.fetchall()
        pedidos_lista = [{
            "id": r["id"],
            "status": r["status"],
            "valor_total": r["valor_total"],
        } for r in pedidos_rows]
        receita_entregue = round(sum(p["valor_total"] for p in pedidos_lista if p["status"] == "Entregue"), 2)
        receita_prevista = round(sum(p["valor_total"] for p in pedidos_lista if p["status"] in ("Pendente", "Em produção", "Concluído")), 2)

        cur.execute("SELECT * FROM despesas ORDER BY created_at DESC LIMIT 20")
        despesas_rows = cur.fetchall()
        despesas = [{"descricao": r["descricao"], "valor": r["valor"], "categoria": r["categoria"], "data": r["data"]} for r in despesas_rows]
        conn.close()
    else:
        pedidos_lista = carregar_json("pedidos.json")
        receita_entregue = round(sum(p.get("valor_total", 0) for p in pedidos_lista if p.get("status") == "Entregue"), 2)
        receita_prevista = round(sum(p.get("valor_total", 0) for p in pedidos_lista if p.get("status") in ("Pendente", "Em produção", "Concluído")), 2)
        despesas = carregar_json("despesas.json")[:20]

    total_despesas = round(sum(d.get("valor", 0) for d in despesas), 2)
    lucro = round(receita_entregue - total_despesas, 2)

    # Build PDF
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 20 * mm
    y = height - margin

    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, "Relatório Financeiro")
    y -= 10 * mm

    c.setFont("Helvetica", 11)
    lines = [
        f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        f"Valor em estoque: R$ {valor_estoque:.2f}",
        f"Receita (entregue): R$ {receita_entregue:.2f}",
        f"Receita (prevista): R$ {receita_prevista:.2f}",
        f"Total despesas (últimas 20): R$ {total_despesas:.2f}",
        f"Lucro estimado: R$ {lucro:.2f}",
    ]
    for ln in lines:
        c.drawString(margin, y, ln)
        y -= 7 * mm

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Despesas (últimas 20)")
    y -= 8 * mm
    c.setFont("Helvetica", 10)
    for d in despesas:
        texto = f"{d.get('data','')}: {d.get('descricao','')} — R$ {float(d.get('valor',0)):.2f} ({d.get('categoria','')})"
        c.drawString(margin, y, texto[:120])
        y -= 6 * mm
        if y < margin + 40*mm:
            c.showPage()
            y = height - margin
            c.setFont("Helvetica", 10)

    c.showPage()
    c.save()
    buf.seek(0)

    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name='relatorio_financeiro.pdf')


# Exportar todos em Excel (XLSX)
@app.route('/exportar/xlsx')
@requires_roles('Relatorios','Financeiro')
def exportar_tudo_xlsx():
    try:
        from io import BytesIO
        from openpyxl import Workbook
    except Exception:
        return ("Biblioteca openpyxl não instalada. Instale com: pip install openpyxl"), 400

    colecoes = [
        "materiais.json",
        "produtos.json",
        "pedidos.json",
        "movimentacoes.json",
        "sobras.json",
        "despesas.json",
    ]

    wb = Workbook()
    # remove default sheet handling by reusing it for first collection
    first = True
    for cfile in colecoes:
        sheet_name = os.path.splitext(cfile)[0][:31]
        data_list = carregar_json(cfile)
        if first:
            ws = wb.active
            ws.title = sheet_name
            first = False
        else:
            ws = wb.create_sheet(title=sheet_name)

        if not data_list:
            ws.append(["(vazio)"])
            continue
        # determine headers union of all keys
        headers = set()
        for item in data_list:
            if isinstance(item, dict):
                headers.update(item.keys())
        headers = list(sorted(headers))
        ws.append(headers)
        for item in data_list:
            if isinstance(item, dict):
                row = [item.get(h, "") for h in headers]
            else:
                row = [str(item)]
            ws.append(row)

    # add a summary sheet
    summary = wb.create_sheet(title="resumo")
    materiais = carregar_materiais()
    valor_estoque = round(sum(m.get("quantidade", 0) * m.get("custo", 0) for m in materiais), 2)
    summary.append(["Relatório gerado em", datetime.now().isoformat()])
    summary.append(["Valor em estoque", valor_estoque])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name='export_all.xlsx')


# Fallback — mantém a navegação de pé para qualquer rota que ainda não exista.
@app.route("/<pagina>")
def em_construcao(pagina):
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)


# Fallback — mantém a navegação de pé para qualquer rota que ainda não exista.
@app.route("/<pagina>")
def em_construcao(pagina):
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)
