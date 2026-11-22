# Arquitetura do Flow Assistente

Este documento descreve os componentes, o caminho de uma mensagem pelo pipeline de 8 etapas,
o pipeline de recuperação (RAG) e o modelo de dados. A especificação de interfaces está em
[`../CONTRACT.md`](../CONTRACT.md).

## 1. Visão de componentes

```mermaid
flowchart LR
    subgraph Usuarios["Usuários"]
        C["Cliente (B2C/B2B)"]
        A["Atendente"]
        G["Gestor"]
    end

    subgraph FE["Frontend - React + Vite :5173"]
        CHAT["Chat do cliente<br/>+ painel 'Por dentro do bot'"]
        PAT["Painel do atendente"]
        PGE["Painel do gestor"]
    end

    subgraph BE["Backend - FastAPI :8000"]
        API["app/main.py<br/>rotas /api/*"]
        ORQ["agent/orchestrator.py<br/>handle_message()"]
        GR["agent/guardrails.py"]
        MEM["agent/memory.py"]
        NLU["agent/nlu.py"]
        TOOLS["agent/tools_erp.py"]
        T2S["agent/text_to_sql.py"]
        HO["agent/handoff.py"]
        RAG["rag/<br/>build_index() / retrieve()"]
        LLM["llm.py<br/>Claude ou mock"]
        REVA["integrations/revgas.py<br/>offline | dryrun | real"]
    end

    subgraph DADOS["Dados"]
        DB[("SQLite flow.db<br/>CRM local, histórico, memória")]
        KB["db/knowledge/*.md<br/>políticas, FAQ, manuais"]
        IDX[("data/index<br/>BM25, vetores, HyPE, grafo")]
    end

    CLAUDE["API Anthropic<br/>(opcional)"]
    REVGAS["ERP RevGás<br/>GET /products · POST /sales"]
    N8N["n8n<br/>nutrição, handoff, pós-venda"]
    MSG["WhatsApp / e-mail / Telegram<br/>(provedores)"]

    C --> CHAT
    A --> PAT
    G --> PGE
    CHAT & PAT & PGE -->|HTTP JSON| API
    API --> ORQ
    ORQ --> GR & MEM & NLU & TOOLS & HO
    TOOLS --> RAG
    TOOLS --> T2S
    API --> T2S
    NLU & RAG & ORQ & T2S & HO --> LLM
    LLM -.->|se houver ANTHROPIC_API_KEY| CLAUDE
    TOOLS & MEM & HO --> DB
    T2S -->|conexão read-only| DB
    KB --> RAG
    TOOLS -->|catálogo, estoque, criar_venda| REVA
    REVA -.->|Authorization: chave| REVGAS
    RAG <--> IDX
    TOOLS -->|webhook lead| N8N
    HO -.->|webhook handoff| N8N
    N8N -->|HTTP /api| API
    N8N --> MSG
```

Princípios de projeto:

- **Um ponto de acesso ao LLM** (`llm.py`). Isso permite o modo mock, que roda a apresentação
  sem chave de API e sem custo.
- **Ferramentas do ERP só leem** (`get_readonly_conn`), exceto `registrar_lead`,
  `transferir_atendente` e `criar_venda` (que só roda depois da confirmação explícita do cliente
  e só grava na RevGás com `REVGAS_MODO=real`).
- **Guardrails são código determinístico**, não instrução no prompt. Valem mesmo se o modelo
  errar.

## 2. Sequência de uma mensagem (8 etapas)

Exemplo: cliente já identificado pergunta *"meu pedido já saiu? e me dá um desconto na próxima
compra"*.

```mermaid
sequenceDiagram
    autonumber
    participant U as Cliente (Chat)
    participant API as FastAPI /api/chat
    participant GE as 1. Guardrails entrada
    participant M as 2. Memória
    participant N as 3. NLU (intenção + entidades)
    participant AG as 4. Agente (tool calling)
    participant R as RAG
    participant ERP as Ferramentas ERP (SQLite)
    participant SQL as 5. Text-to-SQL
    participant GS as 6. Guardrails saída
    participant H as 7. Handoff
    participant L as 8. Lead / n8n

    U->>API: POST {conversa_id, mensagem}
    API->>GE: verificar texto
    GE-->>API: ok (sem injeção, sem dado de terceiro, PII mascarada no log)
    API->>M: carregar slots
    M-->>API: {cliente_id, cpf_cnpj verificado, pedido_numero: FL-2026-00042}
    API->>N: classificar + extrair
    N-->>API: intenção consultar_pedido (0.9), pedir_desconto secundário
    API->>AG: mensagem + memória + NLU
    loop até resposta final (máx. N passos)
        AG->>ERP: consultar_pedido(FL-2026-00042)
        ERP-->>AG: status enviado, rastreio, previsão
        AG->>R: buscar_conhecimento("política de descontos")
        R-->>AG: chunks + RetrievalTrace
    end
    opt intenção relatorio_interno (atendente/gestor)
        AG->>SQL: pergunta em linguagem natural
        SQL-->>AG: SELECT validado em vw_* + linhas
    end
    AG-->>API: rascunho da resposta
    API->>GS: verificar rascunho
    GS-->>API: remove oferta de desconto, mascara CPF, nunca cita preco_minimo
    alt cliente pede humano, ou bot não resolve, ou pedido de desconto
        API->>H: criar handoff (resumo + dados)
        H-->>API: {id, resumo}; conversa = humano
    end
    opt interesse de compra
        API->>L: registrar_lead (score)
        L-->>L: POST N8N_WEBHOOK_URL (falha silenciosa)
    end
    API->>M: salvar slots atualizados
    API-->>U: {resposta, status_conversa, sugestoes, debug}
```

O objeto `debug` devolvido ao frontend registra o que aconteceu em cada etapa (intenção,
entidades, memória mascarada, trace de recuperação, chunks, ferramentas, SQL, guardrails,
handoff, técnicas, latência e modo do LLM).

## 3. Pipeline de recuperação (RAG)

```mermaid
flowchart TD
    Q["Pergunta do cliente"] --> RW["Query Rewriting<br/>resolve 'esse', 'ele' com a memória<br/>(cliente, pedido, produto)"]
    RW --> MQ["Multi-Query<br/>3 variações da pergunta"]
    RW --> EX["Query Expansion<br/>sinônimos de domínio + LLM<br/>ex.: boleto ↔ 2ª via ↔ linha digitável"]
    RW --> HY["HyDE<br/>gera resposta hipotética<br/>e busca por ela"]

    MQ & EX & HY --> BUS

    subgraph BUS["Busca em paralelo"]
        BM["BM25<br/>(rank_bm25)"]
        VE["Vetorial<br/>fastembed ou TF-IDF"]
        HP["HyPE<br/>perguntas hipotéticas<br/>geradas por chunk na indexação"]
        GF["GraphRAG<br/>vizinhança no grafo<br/>produto–categoria–marca–política–termo"]
    end

    BUS --> RRF["Fusão por Reciprocal Rank Fusion<br/>score = Σ 1/(60 + rank)"]
    RRF --> RR["Reranking<br/>LLM ordena a lista<br/>(mock: score heurístico)"]
    RR --> TOP["Top-k chunks (k=5)<br/>com fonte e score"]
    TOP --> AG["Agente usa como contexto<br/>e cita a fonte"]

    subgraph IDX["build_index() - offline"]
        KB["knowledge/*.md<br/>front-matter: titulo, tipo, tags"] --> CK["Chunking"]
        CK --> I1["Índice BM25"]
        CK --> I2["Embeddings"]
        CK --> I3["Perguntas HyPE"]
        CK --> I4["Grafo networkx"]
    end

    I1 -.-> BM
    I2 -.-> VE
    I3 -.-> HP
    I4 -.-> GF
```

Cada etapa pode ser ligada ou desligada pelo parâmetro `tecnicas` de `retrieve()`
(`rewrite, multi_query, expansion, hyde, hype, graph, hybrid, rerank`), o que permite
comparar resultados com e sem cada técnica.

## 4. Modelo de dados

```mermaid
erDiagram
    filiais ||--o{ estoque : "tem"
    produtos ||--o{ estoque : "tem"
    categorias ||--o{ produtos : "classifica"
    clientes ||--o{ pedidos : "faz"
    filiais ||--o{ pedidos : "atende"
    pedidos ||--|{ itens_pedido : "contém"
    produtos ||--o{ itens_pedido : "aparece em"
    clientes ||--o{ financeiro : "deve"
    pedidos ||--o{ financeiro : "gera"
    pedidos ||--o{ trocas : "tem"
    clientes |o--o{ conversas : "participa"
    leads |o--o{ conversas : "origina"
    conversas ||--o{ mensagens : "contém"
    conversas ||--o{ handoffs : "gera"
    conversas ||--o| memoria : "guarda"

    filiais {
        int id PK
        text nome
        text cidade
        text uf
        text endereco
        text telefone
        text horario
    }
    categorias {
        int id PK
        text nome
    }
    produtos {
        int id PK
        text sku UK
        text nome
        text descricao
        int categoria_id FK
        text marca
        real preco
        real preco_minimo "CONFIDENCIAL"
        int garantia_meses
        int ativo
    }
    estoque {
        int produto_id PK,FK
        int filial_id PK,FK
        int quantidade
    }
    clientes {
        int id PK
        text nome
        text tipo "PF|PJ"
        text cpf_cnpj UK
        text email
        text telefone
        text cidade
        text uf
        text segmento
        text criado_em
    }
    pedidos {
        int id PK
        text numero UK "FL-2026-00001"
        int cliente_id FK
        int filial_id FK
        text status
        real valor_total
        text criado_em
        text previsao_entrega
        text codigo_rastreio
    }
    itens_pedido {
        int id PK
        int pedido_id FK
        int produto_id FK
        int quantidade
        real preco_unitario
    }
    financeiro {
        int id PK
        int cliente_id FK
        int pedido_id FK
        text tipo "boleto|pix|cartao"
        real valor
        text vencimento
        text status "aberto|pago|vencido"
        text linha_digitavel
    }
    trocas {
        int id PK
        int pedido_id FK
        text motivo
        text status
        text criado_em
    }
    leads {
        int id PK
        text nome
        text telefone
        text email
        text interesse
        text origem
        text estagio "novo|qualificado|proposta|ganho|perdido"
        int score
        text criado_em
        text atualizado_em
    }
    conversas {
        text id PK "uuid"
        int cliente_id FK
        int lead_id FK
        text canal
        text iniciado_em
        text status "bot|humano|encerrada"
    }
    mensagens {
        int id PK
        text conversa_id FK
        text papel "user|assistant|system"
        text conteudo
        text meta_json
        text criado_em
    }
    handoffs {
        int id PK
        text conversa_id FK
        text motivo
        text resumo
        text dados_json
        text status "pendente|em_atendimento|resolvido"
        text criado_em
    }
    memoria {
        text conversa_id PK,FK
        text estado_json
        text atualizado_em
    }
```

### Views para Text-to-SQL

O Text-to-SQL só enxerga três views, sem colunas sensíveis (`preco_minimo`, CPF/CNPJ, e-mail,
telefone ficam de fora):

| View | Colunas |
|---|---|
| `vw_catalogo` | sku, nome, categoria, marca, preco, garantia_meses |
| `vw_estoque` | sku, produto, filial, cidade, quantidade |
| `vw_vendas_resumo` | mes, filial, qtd_pedidos, faturamento |

Validação com `sqlglot`: um único comando, só `SELECT`, só tabelas `vw_*`, `LIMIT` ≤ 50.
A execução usa conexão SQLite aberta em `mode=ro`, então mesmo um SQL que escape da
validação não consegue escrever.

## 5. Integração com n8n

```mermaid
flowchart LR
    BE["Backend"] -->|"POST lead (registrar_lead)"| W1["01 Nutrição de leads"]
    BE -.->|"POST handoff"| W2["02 Notificação de handoff"]
    CRON["Agendamento 9h"] --> W3["03 Pós-venda"]
    W1 -->|WhatsApp/e-mail| CLI["Lead"]
    W1 -->|atualiza estágio| BE
    W2 -->|e-mail/Telegram| EQ["Equipe de vendas"]
    W3 -->|GET pedidos entregues| BE
    W3 -->|pesquisa + oferta| CLI2["Cliente"]
```

Endpoints usados pelo n8n que ainda não constam do contrato estão listados em
[`../NOTES-docs.md`](../NOTES-docs.md).
