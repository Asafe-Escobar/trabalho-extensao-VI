# Flow Assistente — Contrato entre módulos

Projeto de extensão: chatbot de vendas e relacionamento para a **Flow**, **revenda de gás GLP e água
mineral** (botijões P13/P20/P45, galões 20L, reguladores, mangueiras), com filiais em Teresina-PI,
Parnaíba-PI e São Luís-MA; atende residências (B2C) e restaurantes/condomínios/empresas (B2B).
O ERP é a **API real da RevGás** (ver `docs/revgas-api.md`). Tudo em **português do Brasil**.

## ⚠️ ATUALIZAÇÃO 22/11 — VIRADA PARA GÁS + RevGás (prevalece sobre o resto deste arquivo)
**Foco do projeto: o chatbot CRIAR VENDA na RevGás.** Ler `docs/revgas-api.md` antes de tudo.
- Catálogo = produtos da RevGás. Fonte: `backend/app/integrations/revgas_catalogo_snapshot.json` (já existe)
  e, com chave, `GET /products`. O antigo catálogo de tecnologia (notebooks, impressoras...) está CANCELADO.
- `produtos` ganha coluna `revgas_id INT` (= id na RevGás) e `container_revgas_id INT NULL`. O seed usa
  só os produtos "de verdade" do snapshot (sem TESTE/AAAA/2222) e completa preço com valores realistas
  de Teresina quando o snapshot não tiver (`preco_referencia`). Categorias: Gás GLP, Vasilhames, Água, Acessórios, Outros.
  O mínimo de ≥40 produtos cai para "todos os reais do snapshot" (~30).
- Nova tabela `vendas_revgas(id, numero_local UNIQUE 'RV-DRY-0001'|'RV-30969866', revgas_id INT NULL,
  conversa_id, cliente_id NULL, payload_json, resposta_json, status 'DRYRUN'|'ENVIADA'|'ERRO', total REAL, criado_em)`.
- `clientes` ganha `endereco, numero, bairro` (a RevGás não nos dá /customers: CRM é local).
  `pedidos` continua existindo como histórico local da demo (Maria Souza / FL-2026-00042 = gás "saiu para entrega").
- **Adaptador** `backend/app/integrations/revgas.py` (dono: BACKEND): `listar_produtos()`, `buscar_produto(texto)`,
  `criar_venda(dados) -> {"numero","revgas_id","status","total","payload"}`, modos `REVGAS_MODO=dryrun|real|offline`
  (padrão `dryrun`; `real` é o ÚNICO que faz POST). Lê `REVGAS_API_URL`/`REVGAS_API_KEY` via config. Nunca logar a chave.
- **Fluxo de venda conversacional** (intenção nova `fazer_pedido`; manter as demais): slots na memória
  `carrinho[{revgas_id, nome, qtd, preco}]`, `tem_botijao_para_troca` (se não, adiciona o vasilhame do `container`),
  `endereco{rua,numero,bairro,cidade}`, `pagamento` (MONEY/PIX/CARTAO_DE_DEBITO/CARTAO_DE_CREDITO), `troco_para`.
  O bot pergunta só o que falta, mostra RESUMO com total e pede "Confirma o pedido?". Só após "sim" explícito
  chama a ferramenta `criar_venda`. Resposta final: número do pedido + previsão de entrega (30–60 min).
  Em mock (sem LLM) esse fluxo funciona 100% por regras/regex. `debug.ferramentas` mostra o payload enviado (sem chave).
- Ferramentas: `consultar_estoque`/`consultar_preco` usam o adaptador (fallback SQLite); nova `criar_venda`.
- API nova: `GET /api/vendas-revgas` -> lista `{numero_local, revgas_id, status, total, itens:[{nome,qtd,preco}], criado_em}`
  e `GET /api/revgas/status` -> `{"modo":"dryrun|real|offline","chave_configurada":bool,"produtos":int}`.
  No `/api/chat`, quando a venda é criada, `debug.venda` = `{numero, status, total, itens, endereco, pagamento, payload}`.
- Guardrail novo de **segurança**: "cheiro de gás"/"vazamento" → resposta imediata com instruções (não acender
  luz, abrir janelas, fechar registro, sair do local, ligar 193) + handoff urgente.
- Base de conhecimento passa a ser de gás: segurança com GLP, troca x compra de vasilhame, áreas e prazos de
  entrega por filial, formas de pagamento, validade de regulador (5 anos) e mangueira, água mineral 20L
  e higienização do galão, atendimento B2B (P45, contrato mensal para restaurantes/condomínios),
  política de descontos (bot nunca concede), LGPD, fidelidade (10º botijão), FAQ ≥25, manuais (instalar regulador,
  trocar botijão, central de gás P45). ≥12 arquivos.
- Exemplos de demo: "Quanto tá o botijão de 13?", "Quero 2 botijões de 13 e um galão de água" → fluxo de venda,
  "Tem P45 em Parnaíba?", "Tô sentindo cheiro de gás", "Meu CPF é 123.456.789-09, cadê o pedido FL-2026-00042?".

Este arquivo é a fonte da verdade. Cada agente só escreve na sua pasta, mas pode LER as demais.
Se precisar de algo de outro módulo que não está aqui, implemente um stub local e anote em
`NOTES-<modulo>.md` na raiz.

## Stack
- Backend: Python 3.12, FastAPI, Uvicorn, SQLite (stdlib `sqlite3`), Pydantic v2, SDK `anthropic`.
- RAG: `rank_bm25`, `numpy`, `scikit-learn` (TF-IDF fallback), `fastembed` (opcional), `networkx` (GraphRAG).
- Text-to-SQL: `sqlglot` para validar SQL somente-leitura.
- Frontend: React 18 + Vite + TypeScript, sem UI lib pesada (CSS próprio). Porta 5173.
- Automação: n8n (workflows JSON importáveis).
- LLM: SEMPRE via `backend/app/llm.py` (já existe — leia). `backend/app/config.py` já existe.
  Em modo mock (sem `ANTHROPIC_API_KEY`) tudo precisa funcionar com heurísticas — OBRIGATÓRIO.

## Estrutura e donos
```
backend/
  requirements.txt, .env.example, run.ps1         -> BACKEND
  app/config.py, app/llm.py                        -> já prontos (não reescrever; pode adicionar funções)
  app/db/schema.sql, seed.py, connection.py        -> DATABASE
  app/db/knowledge/*.md                            -> DATABASE (base de conhecimento)
  app/rag/                                         -> RAG
  app/agent/, app/main.py, app/api/                -> BACKEND
  tests/                                           -> cada agente pode criar test_<modulo>.py
frontend/                                          -> FRONTEND
automations/n8n/, docs/, README.md                 -> DOCS
```

## DATABASE — `app/db`
`connection.py`:
- `get_conn() -> sqlite3.Connection` (row_factory=sqlite3.Row, foreign_keys ON, cria o banco a partir de schema.sql + seed se não existir)
- `get_readonly_conn() -> sqlite3.Connection` (abre com `file:...?mode=ro`, uri=True)
- `init_db(reset: bool=False) -> None`

Tabelas (nomes exatos, snake_case):
- `filiais(id, nome, cidade, uf, endereco, telefone, horario)`
- `categorias(id, nome)`
- `produtos(id, sku UNIQUE, nome, descricao, categoria_id, marca, preco REAL, preco_minimo REAL, garantia_meses INT, ativo INT)`
  - `preco_minimo` = piso de desconto; é CONFIDENCIAL (nunca exposto ao cliente).
- `estoque(produto_id, filial_id, quantidade, PRIMARY KEY(produto_id, filial_id))`
- `clientes(id, nome, tipo 'PF'|'PJ', cpf_cnpj UNIQUE (só dígitos), email, telefone, cidade, uf, segmento, criado_em)`
- `pedidos(id, numero UNIQUE 'FL-2026-00001', cliente_id, filial_id, status 'aguardando_pagamento'|'pago'|'separacao'|'enviado'|'entregue'|'cancelado', valor_total, criado_em, previsao_entrega, codigo_rastreio)`
- `itens_pedido(id, pedido_id, produto_id, quantidade, preco_unitario)`
- `financeiro(id, cliente_id, pedido_id, tipo 'boleto'|'pix'|'cartao', valor, vencimento, status 'aberto'|'pago'|'vencido', linha_digitavel)`
- `trocas(id, pedido_id, motivo, status, criado_em)`
- `leads(id, nome, telefone, email, interesse, origem, estagio 'novo'|'qualificado'|'proposta'|'ganho'|'perdido', score INT, criado_em, atualizado_em)`
- `conversas(id TEXT PK uuid, cliente_id NULL, lead_id NULL, canal, iniciado_em, status 'bot'|'humano'|'encerrada')`
- `mensagens(id, conversa_id, papel 'user'|'assistant'|'system', conteudo, meta_json, criado_em)`
- `handoffs(id, conversa_id, motivo, resumo, dados_json, status 'pendente'|'em_atendimento'|'resolvido', criado_em)`
- `memoria(conversa_id PK, estado_json, atualizado_em)` — Conversation Memory (slots)

Views somente-leitura para Text-to-SQL (sem colunas sensíveis):
- `vw_catalogo(sku, nome, categoria, marca, preco, garantia_meses)`
- `vw_estoque(sku, produto, filial, cidade, quantidade)`
- `vw_vendas_resumo(mes, filial, qtd_pedidos, faturamento)`
Seed: ≥40 produtos, 3 filiais, ≥25 clientes (CPF/CNPJ fictícios válidos em formato), ≥60 pedidos
cobrindo todos os status, financeiro com boletos abertos/vencidos, ≥15 leads.
Clientes-demo fixos para a apresentação: CPF `12345678909` (Maria Souza, PF) com pedido `FL-2026-00042` em `enviado`
e um boleto `aberto`; CNPJ `11222333000181` (Escritório Alfa Ltda, PJ) com pedido `FL-2026-00043` em `separacao`.

Base de conhecimento (`knowledge/*.md`, front-matter YAML com `titulo`, `tipo`, `tags`):
catálogo comentado por categoria, política de trocas e devoluções, política de garantia, política de
frete e prazos, formas de pagamento/boleto/2ª via, política comercial de descontos (alçadas: bot NUNCA concede
desconto; até 5% vendedor; acima gerente), LGPD/privacidade, FAQ (≥25 perguntas), manuais de uso de
3-4 produtos, programa de fidelidade, atendimento B2B (faturamento, pedido mínimo). ≥12 arquivos.

## RAG — `app/rag`
Exporta em `app/rag/__init__.py`:
```python
class Chunk(BaseModel): id: str; doc_id: str; titulo: str; tipo: str; texto: str; score: float = 0; fonte: str = ""  # fonte: "bm25"|"vetorial"|"grafo"|"hype"
class RetrievalTrace(BaseModel):
    original: str; reescrita: str | None; multi_queries: list[str]; expansao: list[str]
    hyde_doc: str | None; candidatos: int; tecnicas: list[str]
def build_index(force: bool = False) -> None      # chunking + BM25 + embeddings + perguntas HyPE + grafo; persiste em config.INDEX_DIR
def retrieve(query: str, *, k: int = 5, contexto: dict | None = None,
             tecnicas: set[str] | None = None) -> tuple[list[Chunk], RetrievalTrace]
```
`tecnicas` ⊆ {"rewrite","multi_query","expansion","hyde","hype","graph","hybrid","rerank"}; None = todas.
- Query Rewriting (usa `contexto` da memória: cliente, pedido, produto), Multi-Query (3 variações),
  Query Expansion (sinônimos de domínio + LLM), HyDE, HyPE (perguntas hipotéticas por chunk geradas no build;
  em mock gere via template), GraphRAG (grafo produto–categoria–política–marca–termo; expansão por vizinhança),
  RAG híbrido (BM25 + vetorial com Reciprocal Rank Fusion), Reranking (LLM em lista ou cross-score heurístico no mock).
- Embeddings: `fastembed` (modelo multilíngue) se instalado e `config.EMBEDDINGS != "tfidf"`, senão TF-IDF.

## BACKEND — `app/agent` + `app/main.py`
Pipeline por mensagem (`agent/orchestrator.py: handle_message(conversa_id, texto) -> ChatResponse`):
1. Guardrails de entrada (`agent/guardrails.py`): prompt injection, pedido de dados de terceiros, PII.
2. Memória (`agent/memory.py`): carrega slots {cliente_id, cpf_cnpj, pedido_numero, produto_sku, filial, intencao_anterior, resumo}.
3. Intent Classification + Entity Extraction (`agent/nlu.py`, 1 chamada `llm.structured`; mock com regex).
   Intenções: `consultar_preco, consultar_estoque, consultar_pedido, segunda_via_boleto, troca_devolucao,
   garantia, duvida_politica, recomendacao_produto, pedir_desconto, falar_atendente, saudacao, relatorio_interno, outro`.
   Entidades: cpf_cnpj, numero_pedido, produto, sku, filial, periodo, status.
4. Agentic RAG: loop de tool calling (`llm.create_message`, tool_choice auto) com ferramentas:
   `buscar_conhecimento`(rag.retrieve), `consultar_cliente`, `consultar_pedido`, `consultar_estoque`,
   `consultar_preco`, `consultar_financeiro`, `registrar_lead`, `consulta_sql` (Text-to-SQL controlado),
   `transferir_atendente`. Ferramentas ERP em `agent/tools_erp.py` (usam get_readonly_conn, exceto lead/handoff).
   Toda consulta de pedido/financeiro exige cpf_cnpj verificado na memória e só retorna dados DO PRÓPRIO cliente.
   Em mock: roteador por regras intenção→ferramentas→resposta com template.
5. Text-to-SQL (`agent/text_to_sql.py`): LLM gera SELECT; `sqlglot` valida: só SELECT, só views `vw_*`, LIMIT ≤ 50,
   sem `;` múltiplo; executa em conexão read-only. Uso: intenção `relatorio_interno` (modo atendente/gestor).
6. Guardrails de saída: bloquear desconto não autorizado, nunca citar `preco_minimo`, mascarar CPF/CNPJ.
7. Human Handoff (`agent/handoff.py`): grava em `handoffs` com resumo (LLM/mock) + dados coletados; conversa vira status 'humano'.
8. Lead scoring simples para nutrição (`registrar_lead`), dispara webhook n8n se `N8N_WEBHOOK_URL` definido (httpx, falha silenciosa).

API (FastAPI, prefixo `/api`) — o FRONTEND consome exatamente isto:
- `POST /api/conversas` -> `{"conversa_id": str}`
- `POST /api/chat` body `{"conversa_id": str, "mensagem": str}` ->
```json
{"resposta": "texto markdown",
 "status_conversa": "bot|humano",
 "sugestoes": ["chips de resposta rápida"],
 "debug": {
   "intencao": "consultar_pedido", "confianca": 0.92,
   "entidades": {"numero_pedido": "FL-2026-00042"},
   "memoria": {"cpf_cnpj": "***.456.789-**", "pedido_numero": "..."},
   "retrieval": RetrievalTrace | null,
   "chunks": [{"titulo": "...", "score": 0.81, "fonte": "bm25", "trecho": "..."}],
   "ferramentas": [{"nome": "consultar_pedido", "entrada": {}, "saida_resumo": "..."}],
   "sql": "SELECT ..." | null,
   "guardrails": [{"regra": "desconto_nao_autorizado", "acao": "bloqueado"}],
   "handoff": {"id": 3, "resumo": "..."} | null,
   "tecnicas": ["intent_classification","entity_extraction","rag_hibrido", "..."],
   "latencia_ms": 812, "modo_llm": "anthropic|mock"}}
```
- `GET /api/conversas/{id}/mensagens` -> lista `{papel, conteudo, criado_em}`
- `GET /api/handoffs?status=pendente` -> lista `{id, conversa_id, motivo, resumo, dados, status, criado_em}`
- `POST /api/handoffs/{id}/assumir` · `POST /api/handoffs/{id}/resolver`
- `POST /api/atendente/mensagem` body `{"conversa_id","mensagem"}` (atendente humano responde)
- `GET /api/leads` · `GET /api/metricas` -> `{conversas, handoffs_pendentes, leads_por_estagio:{}, intencoes_top:[{intencao,qtd}]}`
- `POST /api/sql` body `{"pergunta": str}` -> `{"sql","linhas":[...],"colunas":[...]}` (painel do gestor)
- `POST /api/admin/reindex` · `GET /api/health` -> `{"ok":true,"modo_llm":...}`

Integração n8n (exigida pelos workflows em `automations/n8n/`):
- `config.N8N_WEBHOOK_URL` (lead) e `config.N8N_HANDOFF_WEBHOOK_URL` (handoff), lidos do `.env`; POST JSON, httpx, timeout 3s, falha silenciosa.
  - Lead: `{"id","nome","telefone","email","interesse","origem","score","estagio"}`.
  - Handoff: `{"id","conversa_id","motivo","resumo","dados":{...}}` (CPF/CNPJ mascarado em `dados`).
- `PATCH /api/leads/{id}` body `{"estagio": "qualificado"|...}` -> lead atualizado (404 se não existir).
- `GET /api/automacoes/pedidos-entregues?dias=1` (header `X-Flow-Token` = `config.FLOW_AUTOMACAO_TOKEN`; se a variável
  estiver vazia, não exige token) -> `{"pedidos":[{"numero","cliente_nome","email","telefone",
  "itens":[{"sku","nome","quantidade"}],"sugestao":{"sku","nome","preco"}|null}]}`. `sugestao` vem do GraphRAG/categoria
  (acessório relacionado ao primeiro item). Em demo, `dias` conta a partir da data mais recente de pedido entregue no seed.

## API REST de vendas — `app/api/vendas.py` (dono: MAESTRO; registrado em `main.py`)
Prefixo `/api/v1`, tag Swagger "Vendas RevGás", usa só `app.integrations.revgas`. Se `FLOW_API_KEY` existir no `.env`,
exige header `X-API-Key`.
- `GET /api/v1/produtos?q=&categoria=&todos=` · `GET /api/v1/produtos/{revgas_id}`
- `POST /api/v1/vendas/cotacao` (calcula, não grava) · `POST /api/v1/vendas` (cria; header `Idempotency-Key` opcional)
  body: `{itens:[{revgas_id|produto, quantidade}], tem_botijao_para_troca, endereco{rua,numero,bairro,cidade,uf,complemento},
  pagamento MONEY|PIX|CARTAO_DE_DEBITO|CARTAO_DE_CREDITO, troco_para?, cliente{nome,telefone}?, observacao?}`.
  Preço sempre do catálogo; vasilhame automático quando não há troca.
- `GET /api/v1/vendas?status=` · `GET /api/v1/vendas/{numero}` · `GET /api/v1/status`
- Testes: `tests/test_api_vendas.py` (modo offline).

## FRONTEND
3 telas: **Chat do cliente** (com painel lateral "Por dentro do bot" mostrando o `debug` — essencial
para a apresentação: técnica a técnica), **Painel do atendente** (fila de handoffs, assumir, ver resumo+dados,
responder), **Painel do gestor** (métricas, leads por estágio, Text-to-SQL). `VITE_API_URL` default `http://localhost:8000`.

## DOCS
README (como rodar no Windows), `docs/relatorio-extensao.md` (relatório acadêmico), `docs/arquitetura.md`
(diagrama mermaid), `docs/roteiro-demo.md` (roteiro de apresentação com as mensagens a digitar, uma por técnica),
`automations/n8n/*.json` (nutrição de leads, notificação de handoff, follow-up pós-venda).
