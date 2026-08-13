PRAGMA foreign_keys = OFF;
BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS collections (
    name TEXT NOT NULL,
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_collections_name ON collections(name);

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
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_materiais_nome_gtin ON materiais (lower(nome), gtin);

CREATE TABLE IF NOT EXISTS produtos (
    id TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    emoji TEXT,
    preco_venda REAL DEFAULT 0,
    receita TEXT,
    created_at TEXT,
    updated_at TEXT
);

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
);

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
);
CREATE INDEX IF NOT EXISTS idx_movimentacoes_created ON movimentacoes(created_at);

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
);

CREATE TABLE IF NOT EXISTS despesas (
    id TEXT PRIMARY KEY,
    descricao TEXT,
    valor REAL,
    categoria TEXT,
    data TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS usuarios (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE,
    password_hash TEXT,
    created_at TEXT
);

COMMIT;
