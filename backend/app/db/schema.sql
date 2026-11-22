-- Flow Assistente — schema SQLite
-- Fonte da verdade: CONTRACT.md (seção DATABASE)

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS filiais (
    id        INTEGER PRIMARY KEY,
    nome      TEXT NOT NULL,
    cidade    TEXT NOT NULL,
    uf        TEXT NOT NULL,
    endereco  TEXT NOT NULL,
    telefone  TEXT NOT NULL,
    horario   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categorias (
    id    INTEGER PRIMARY KEY,
    nome  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS produtos (
    id              INTEGER PRIMARY KEY,
    sku             TEXT NOT NULL UNIQUE,
    nome            TEXT NOT NULL,
    descricao       TEXT,
    categoria_id    INTEGER NOT NULL REFERENCES categorias(id),
    marca           TEXT,
    preco           REAL NOT NULL CHECK (preco >= 0),
    preco_minimo    REAL NOT NULL CHECK (preco_minimo >= 0), -- CONFIDENCIAL: piso de desconto
    garantia_meses  INTEGER NOT NULL DEFAULT 12,
    ativo           INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    revgas_id           INTEGER UNIQUE,   -- id do produto na API RevGás
    container_revgas_id INTEGER           -- vasilhame associado (revgas_id do vasilhame) ou NULL
);
CREATE INDEX IF NOT EXISTS idx_produtos_revgas ON produtos(revgas_id);
CREATE INDEX IF NOT EXISTS idx_produtos_categoria ON produtos(categoria_id);
CREATE INDEX IF NOT EXISTS idx_produtos_nome ON produtos(nome);
CREATE INDEX IF NOT EXISTS idx_produtos_marca ON produtos(marca);

CREATE TABLE IF NOT EXISTS estoque (
    produto_id  INTEGER NOT NULL REFERENCES produtos(id),
    filial_id   INTEGER NOT NULL REFERENCES filiais(id),
    quantidade  INTEGER NOT NULL DEFAULT 0 CHECK (quantidade >= 0),
    PRIMARY KEY (produto_id, filial_id)
);
CREATE INDEX IF NOT EXISTS idx_estoque_filial ON estoque(filial_id);

CREATE TABLE IF NOT EXISTS clientes (
    id         INTEGER PRIMARY KEY,
    nome       TEXT NOT NULL,
    tipo       TEXT NOT NULL CHECK (tipo IN ('PF', 'PJ')),
    cpf_cnpj   TEXT NOT NULL UNIQUE, -- só dígitos
    email      TEXT,
    telefone   TEXT,
    endereco   TEXT,   -- rua/avenida (a RevGás não expõe /customers: o CRM é local)
    numero     TEXT,
    bairro     TEXT,
    cidade     TEXT,
    uf         TEXT,
    segmento   TEXT,
    criado_em  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pedidos (
    id                INTEGER PRIMARY KEY,
    numero            TEXT NOT NULL UNIQUE, -- 'FL-2026-00001'
    cliente_id        INTEGER NOT NULL REFERENCES clientes(id),
    filial_id         INTEGER NOT NULL REFERENCES filiais(id),
    status            TEXT NOT NULL CHECK (status IN
                        ('aguardando_pagamento', 'pago', 'separacao', 'enviado', 'entregue', 'cancelado')),
    valor_total       REAL NOT NULL DEFAULT 0,
    criado_em         TEXT NOT NULL DEFAULT (datetime('now')),
    previsao_entrega  TEXT,
    codigo_rastreio   TEXT
);
CREATE INDEX IF NOT EXISTS idx_pedidos_cliente ON pedidos(cliente_id);
CREATE INDEX IF NOT EXISTS idx_pedidos_filial ON pedidos(filial_id);
CREATE INDEX IF NOT EXISTS idx_pedidos_status ON pedidos(status);
CREATE INDEX IF NOT EXISTS idx_pedidos_criado ON pedidos(criado_em);

CREATE TABLE IF NOT EXISTS itens_pedido (
    id              INTEGER PRIMARY KEY,
    pedido_id       INTEGER NOT NULL REFERENCES pedidos(id) ON DELETE CASCADE,
    produto_id      INTEGER NOT NULL REFERENCES produtos(id),
    quantidade      INTEGER NOT NULL CHECK (quantidade > 0),
    preco_unitario  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_itens_pedido ON itens_pedido(pedido_id);
CREATE INDEX IF NOT EXISTS idx_itens_produto ON itens_pedido(produto_id);

CREATE TABLE IF NOT EXISTS financeiro (
    id               INTEGER PRIMARY KEY,
    cliente_id       INTEGER NOT NULL REFERENCES clientes(id),
    pedido_id        INTEGER REFERENCES pedidos(id),
    tipo             TEXT NOT NULL CHECK (tipo IN ('boleto', 'pix', 'cartao', 'dinheiro')),
    valor            REAL NOT NULL,
    vencimento       TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('aberto', 'pago', 'vencido')),
    linha_digitavel  TEXT
);
CREATE INDEX IF NOT EXISTS idx_financeiro_cliente ON financeiro(cliente_id);
CREATE INDEX IF NOT EXISTS idx_financeiro_pedido ON financeiro(pedido_id);
CREATE INDEX IF NOT EXISTS idx_financeiro_status ON financeiro(status);

CREATE TABLE IF NOT EXISTS trocas (
    id         INTEGER PRIMARY KEY,
    pedido_id  INTEGER NOT NULL REFERENCES pedidos(id),
    motivo     TEXT NOT NULL,
    status     TEXT NOT NULL,
    criado_em  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_trocas_pedido ON trocas(pedido_id);

CREATE TABLE IF NOT EXISTS leads (
    id             INTEGER PRIMARY KEY,
    nome           TEXT,
    telefone       TEXT,
    email          TEXT,
    interesse      TEXT,
    origem         TEXT,
    estagio        TEXT NOT NULL DEFAULT 'novo' CHECK (estagio IN
                     ('novo', 'qualificado', 'proposta', 'ganho', 'perdido')),
    score          INTEGER NOT NULL DEFAULT 0,
    criado_em      TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_leads_estagio ON leads(estagio);

CREATE TABLE IF NOT EXISTS conversas (
    id           TEXT PRIMARY KEY, -- uuid
    cliente_id   INTEGER REFERENCES clientes(id),
    lead_id      INTEGER REFERENCES leads(id),
    canal        TEXT NOT NULL DEFAULT 'web',
    iniciado_em  TEXT NOT NULL DEFAULT (datetime('now')),
    status       TEXT NOT NULL DEFAULT 'bot' CHECK (status IN ('bot', 'humano', 'encerrada'))
);
CREATE INDEX IF NOT EXISTS idx_conversas_status ON conversas(status);

CREATE TABLE IF NOT EXISTS mensagens (
    id           INTEGER PRIMARY KEY,
    conversa_id  TEXT NOT NULL REFERENCES conversas(id) ON DELETE CASCADE,
    papel        TEXT NOT NULL CHECK (papel IN ('user', 'assistant', 'system')),
    conteudo     TEXT NOT NULL,
    meta_json    TEXT,
    criado_em    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mensagens_conversa ON mensagens(conversa_id, id);

CREATE TABLE IF NOT EXISTS handoffs (
    id           INTEGER PRIMARY KEY,
    conversa_id  TEXT NOT NULL REFERENCES conversas(id),
    motivo       TEXT NOT NULL,
    resumo       TEXT,
    dados_json   TEXT,
    status       TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'em_atendimento', 'resolvido')),
    criado_em    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_handoffs_status ON handoffs(status);
CREATE INDEX IF NOT EXISTS idx_handoffs_conversa ON handoffs(conversa_id);

-- Vendas criadas pelo chatbot na RevGás (dryrun grava só aqui; real = aqui + POST /sales)
CREATE TABLE IF NOT EXISTS vendas_revgas (
    id             INTEGER PRIMARY KEY,
    numero_local   TEXT NOT NULL UNIQUE,   -- 'RV-DRY-0001' (dryrun) | 'RV-30969866' (real)
    revgas_id      INTEGER,                -- id da venda na RevGás (NULL em dryrun/erro)
    conversa_id    TEXT REFERENCES conversas(id),
    cliente_id     INTEGER REFERENCES clientes(id),
    payload_json   TEXT NOT NULL,          -- payload enviado/validado (NUNCA contém a chave da API)
    resposta_json  TEXT,
    status         TEXT NOT NULL CHECK (status IN ('DRYRUN', 'ENVIADA', 'ERRO')),
    total          REAL NOT NULL DEFAULT 0,
    criado_em      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_vendas_revgas_conversa ON vendas_revgas(conversa_id);
CREATE INDEX IF NOT EXISTS idx_vendas_revgas_status ON vendas_revgas(status);

-- Conversation Memory (slots)
CREATE TABLE IF NOT EXISTS memoria (
    conversa_id    TEXT PRIMARY KEY REFERENCES conversas(id) ON DELETE CASCADE,
    estado_json    TEXT NOT NULL DEFAULT '{}',
    atualizado_em  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Views somente-leitura para Text-to-SQL (SEM colunas sensíveis: nada de
-- preco_minimo, CPF/CNPJ, e-mail, telefone ou linha digitável).
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS vw_catalogo;
CREATE VIEW vw_catalogo AS
SELECT p.sku            AS sku,
       p.nome           AS nome,
       c.nome           AS categoria,
       p.marca          AS marca,
       p.preco          AS preco,
       p.garantia_meses AS garantia_meses
FROM produtos p
JOIN categorias c ON c.id = p.categoria_id
WHERE p.ativo = 1;

DROP VIEW IF EXISTS vw_estoque;
CREATE VIEW vw_estoque AS
SELECT p.sku        AS sku,
       p.nome       AS produto,
       f.nome       AS filial,
       f.cidade     AS cidade,
       e.quantidade AS quantidade
FROM estoque e
JOIN produtos p ON p.id = e.produto_id
JOIN filiais f  ON f.id = e.filial_id
WHERE p.ativo = 1;

DROP VIEW IF EXISTS vw_vendas_resumo;
CREATE VIEW vw_vendas_resumo AS
SELECT strftime('%Y-%m', pe.criado_em) AS mes,
       f.nome                          AS filial,
       COUNT(*)                        AS qtd_pedidos,
       ROUND(SUM(pe.valor_total), 2)   AS faturamento
FROM pedidos pe
JOIN filiais f ON f.id = pe.filial_id
WHERE pe.status <> 'cancelado'
GROUP BY mes, f.nome;

-- Vendas do chatbot (sem payload/endereço/cliente)
DROP VIEW IF EXISTS vw_vendas_chatbot;
CREATE VIEW vw_vendas_chatbot AS
SELECT strftime('%Y-%m-%d', criado_em) AS dia,
       status                          AS status,
       COUNT(*)                        AS qtd_vendas,
       ROUND(SUM(total), 2)            AS total
FROM vendas_revgas
GROUP BY dia, status;
