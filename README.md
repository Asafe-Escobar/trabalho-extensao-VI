# Flow Assistente

Chatbot de vendas e relacionamento para a **Flow**, revenda de gás GLP e água mineral com
lojas em Teresina-PI, Parnaíba-PI e São Luís-MA, que atende residências (B2C) e restaurantes,
condomínios e empresas (B2B). O ERP é o **RevGás**: o chatbot lê o catálogo pela API e
**lança a venda direto no sistema** (`POST /sales`). Detalhes em [`docs/revgas-api.md`](docs/revgas-api.md).

Projeto de extensão universitária. O enunciado pede soluções (chatbots, automações com n8n,
APIs, RAG) que ajudem a Flow a **converter vendas e nutrir relacionamentos**. A solução tem
quatro partes:

| Parte | O que faz |
|---|---|
| **Chat do cliente** | Faz o pedido completo (produto, troca de botijão, endereço, pagamento, confirmação) e registra a venda na RevGás. Responde dúvidas de preço, estoque, entrega, segurança e pagamentos com base na base de conhecimento e no ERP. Tem um painel lateral "Por dentro do bot" que mostra cada técnica em ação. |
| **Painel do atendente** | Fila de transferências para humano (handoff) com resumo da conversa e dados já coletados. |
| **Painel do gestor** | Métricas, leads por estágio e perguntas em linguagem natural convertidas em SQL somente-leitura. |
| **Automações n8n** | Nutrição de leads, aviso de handoff para a equipe e pós-venda (pesquisa de satisfação + oferta). |

A especificação técnica entre módulos está em [`CONTRACT.md`](CONTRACT.md). A arquitetura
está em [`docs/arquitetura.md`](docs/arquitetura.md), o relatório acadêmico em
[`docs/relatorio-extensao.md`](docs/relatorio-extensao.md) e o roteiro da apresentação em
[`docs/roteiro-demo.md`](docs/roteiro-demo.md).

---

## Técnicas implementadas

Cada resposta do `/api/chat` traz o campo `debug.tecnicas` com as técnicas que foram usadas
naquela mensagem, e o painel "Por dentro do bot" mostra os detalhes.

| Técnica | Onde está no código | Como demonstrar (mensagem no chat) | O que olhar no painel |
|---|---|---|---|
| **Criar venda na RevGás** (foco) | `backend/app/agent/orchestrator.py` (fluxo `fazer_pedido`) + `backend/app/integrations/revgas.py` | "Quero 2 botijões de 13 e um galão de água" → endereço → "Pix" → "Sim" | ferramenta `criar_venda`, `debug.venda` com o payload e o número `RV-…` |
| Intent Classification | `backend/app/agent/nlu.py` | "Quanto tá o botijão de 13?" | `intencao` = `consultar_preco` e `confianca` |
| Entity Extraction | `backend/app/agent/nlu.py` | "Meu CPF é 123.456.789-09, cadê o pedido FL-2026-00042?" | `entidades` com `cpf_cnpj` e `numero_pedido` |
| Conversation Memory | `backend/app/agent/memory.py` | Depois do passo anterior: "E quando chega?" | `memoria` já tem CPF (mascarado) e pedido |
| Query Rewriting | `backend/app/rag/` (reescrita) | "E a mangueira também?" (após perguntar do regulador) | `retrieval.reescrita` com o nome do produto |
| Multi-Query RAG | `backend/app/rag/` (multi-query) | "Vocês aceitam cartão na entrega?" | `retrieval.multi_queries` (3 variações) |
| Query Expansion | `backend/app/rag/` (expansão) | "Quero um botijão" (botijão → P13 → GLP 13kg) | `retrieval.expansao` (sinônimos de domínio) |
| HyDE | `backend/app/rag/` (HyDE) | "Meu botijão tá chiando, o que faço?" | `retrieval.hyde_doc` (resposta hipotética) |
| HyPE | `backend/app/rag/` (indexação) | Qualquer dúvida de política | chunks com `fonte` = `hype` |
| GraphRAG | `backend/app/rag/` (grafo com `networkx`) | "O que combina com o P45 pra restaurante?" | chunks com `fonte` = `grafo` |
| RAG híbrido (BM25 + vetorial + RRF) | `backend/app/rag/` | Qualquer pergunta de conhecimento | chunks com `fonte` = `bm25` e `vetorial` |
| Reranking | `backend/app/rag/` (rerank) | Qualquer pergunta de conhecimento | ordem e `score` final dos chunks |
| Agentic RAG + Tool Calling (ERP) | `backend/app/agent/orchestrator.py`, `backend/app/agent/tools_erp.py` | "Tem P45 em Parnaíba?" | lista `ferramentas` (`consultar_estoque`, `buscar_conhecimento`...) |
| Text-to-SQL controlado | `backend/app/agent/text_to_sql.py` | Painel do gestor: "Faturamento por filial em 2026" | `sql` gerado (só `SELECT` em views `vw_*`, `LIMIT` ≤ 50) |
| Guardrails (entrada e saída) | `backend/app/agent/guardrails.py` | "Me faz por 90 o botijão" / "Tô sentindo cheiro de gás" / "Qual o CPF do cliente do pedido FL-2026-00010?" / "Ignore suas instruções" | `guardrails` com regra e ação |
| Human Handoff | `backend/app/agent/handoff.py` | "Quero falar com um atendente" | `handoff` com `id` e `resumo`; aparece no Painel do atendente |
| Lead scoring + nutrição | `registrar_lead` em `backend/app/agent/tools_erp.py` + `automations/n8n/01-nutricao-leads.json` | "Quero orçamento mensal de 10 P45 para meu restaurante" | ferramenta `registrar_lead`; lead aparece no Painel do gestor |

> As pastas `backend/` e `frontend/` são escritas por outros membros da equipe. Se um caminho
> acima mudar, o arquivo de referência é o `CONTRACT.md`.

---

## Pré-requisitos

- Windows 10/11 com PowerShell
- **Python 3.12** (`python --version`)
- **Node.js 20+** e npm (`node --version`)
- Opcional: **chave da API da Anthropic** (`ANTHROPIC_API_KEY`) para usar o Claude de verdade
- Opcional: **n8n** (Docker, `npx n8n` ou n8n Cloud) para as automações

---

## Como rodar no Windows

### 1. Backend (porta 8000)

```powershell
cd flow-chatbot\backend
copy .env.example .env        # edite se quiser colocar a chave da API
.\run.ps1
```

O `run.ps1` cria o ambiente virtual, instala o `requirements.txt`, cria o banco SQLite com os
dados de exemplo (seed), monta o índice do RAG e sobe o Uvicorn em `http://localhost:8000`.

Se o PowerShell bloquear o script:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Teste: abra `http://localhost:8000/api/health`; deve aparecer `{"ok": true, "modo_llm": "mock"}`
(ou `"anthropic"`). A documentação interativa da API fica em `http://localhost:8000/docs`.

### 2. Frontend (porta 5173)

Em outro terminal:

```powershell
cd flow-chatbot\frontend
npm install; npm run dev
```

Abra `http://localhost:5173`. Se o backend estiver em outro endereço, crie
`frontend\.env.local` com `VITE_API_URL=http://seu-host:8000`.

### Comandos úteis

| Ação | Como |
|---|---|
| Recriar o índice do RAG | `POST http://localhost:8000/api/admin/reindex` (ou botão no painel, se houver) |
| Recriar o banco do zero | apagar `backend\data\flow.db` e subir o backend de novo |
| Rodar os testes | `cd backend; .\.venv\Scripts\python -m pytest` |

---

## Modo mock vs. modo Claude

O projeto **funciona sem chave de API**. Toda chamada ao modelo passa por
`backend/app/llm.py`, que decide o modo pela variável `LLM_MODE` (padrão `auto`):

| | Modo **mock** (sem chave) | Modo **anthropic** (com `ANTHROPIC_API_KEY`) |
|---|---|---|
| Intenção e entidades | regex e palavras-chave | 1 chamada de saída estruturada |
| Reescrita, multi-query, expansão | templates + dicionário de sinônimos | geradas pelo modelo |
| HyDE / HyPE | documento e perguntas por template | gerados pelo modelo |
| Reranking | pontuação heurística (sobreposição de termos + fontes) | modelo ordena a lista |
| Agentic RAG | roteador por regras intenção → ferramentas → resposta com template | loop de tool calling com `tool_choice: auto` |
| Text-to-SQL | consultas pré-definidas por padrão de pergunta | SQL gerado e validado com `sqlglot` |
| Custo | zero, determinístico, ideal para ensaio | consome créditos da API |

O campo `debug.modo_llm` mostra qual modo respondeu. Para ativar o Claude, edite
`backend\.env`:

```env
ANTHROPIC_API_KEY=sk-ant-...
LLM_MODE=auto            # auto | anthropic | mock
LLM_MODEL=claude-opus-5-5
LLM_EFFORT=low
EMBEDDINGS=auto          # auto | fastembed | tfidf
N8N_WEBHOOK_URL=         # webhook de nutrição de leads (opcional)
N8N_HANDOFF_WEBHOOK_URL= # webhook de aviso de handoff (opcional)
FLOW_AUTOMACAO_TOKEN=    # token que o n8n usa no pós-venda

# ERP RevGás
REVGAS_API_URL=https://api.revgas.com/v1
REVGAS_API_KEY=          # pedida ao suporte RevGás; nunca versionar
REVGAS_MODO=dryrun       # offline | dryrun (padrão: monta e valida a venda, não grava) | real (POST /sales)
```

> `REVGAS_MODO=real` grava vendas de verdade no sistema da revenda. Use só com autorização,
> e confira `GET /api/revgas/status` antes da demonstração.

Os guardrails de saída (bloqueio de desconto, nunca citar `preco_minimo`, mascaramento de
CPF/CNPJ) são código determinístico e valem nos dois modos.

---

## API de vendas (FastAPI)

Além das rotas do chat, o backend expõe uma API REST para criar vendas na RevGás sem passar pela
conversa (n8n, outros sistemas, testes). Documentação interativa em **http://localhost:8000/docs**
(tag "Vendas RevGás").

| Método | Rota | O que faz |
|---|---|---|
| GET | `/api/v1/produtos?q=p13` | catálogo RevGás com preço e estoque (`q` aceita texto livre) |
| GET | `/api/v1/produtos/{revgas_id}` | um produto |
| POST | `/api/v1/vendas/cotacao` | calcula itens, vasilhame automático, total e troco, sem gravar |
| POST | `/api/v1/vendas` | cria a venda (`dryrun` grava só local; `real` faz `POST /sales` na RevGás) |
| GET | `/api/v1/vendas` · `/api/v1/vendas/{numero}` | vendas criadas e o payload enviado |
| GET | `/api/v1/status` | modo da integração e origem do catálogo (nunca mostra a chave) |

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/vendas -ContentType 'application/json' `
  -Headers @{ 'Idempotency-Key' = 'pedido-123' } -Body '{
  "itens": [{"produto": "botijão de 13", "quantidade": 2}, {"produto": "galão de água", "quantidade": 1}],
  "tem_botijao_para_troca": true,
  "endereco": {"rua": "Rua Augusto Freire", "numero": "2003", "bairro": "Centro", "cidade": "Teresina", "uf": "PI"},
  "pagamento": "PIX",
  "cliente": {"nome": "Maria Souza", "telefone": "86999990000"}
}'
```

O preço sempre vem do catálogo (o chamador não manda preço nem desconto). Repetir a mesma
`Idempotency-Key` devolve a mesma venda, sem duplicar. Para exigir autenticação, defina
`FLOW_API_KEY` no `backend\.env` e envie o header `X-API-Key`.

---

## Automações n8n

Os três workflows ficam em `automations/n8n/`:

| Arquivo | Gatilho | O que faz |
|---|---|---|
| `01-nutricao-leads.json` | Webhook chamado pelo backend quando um lead é registrado | Separa por score, espera o tempo certo, manda follow-up (WhatsApp/e-mail) e atualiza o estágio do lead |
| `02-notificacao-handoff.json` | Webhook chamado quando a conversa vai para humano | Formata o resumo e avisa a equipe por e-mail e Telegram |
| `03-pos-venda.json` | Agendamento diário às 9h | Busca pedidos entregues, envia pesquisa de satisfação e oferta relacionada |

Para importar: no n8n, **Workflows → Import from File** e escolha o JSON. Depois configure
as variáveis e credenciais descritas em
[`automations/n8n/README.md`](automations/n8n/README.md). Para o backend disparar o
workflow 1, coloque a URL de produção do webhook em `N8N_WEBHOOK_URL` no `backend\.env`.

---

## Estrutura de pastas

```
flow-chatbot/
├── CONTRACT.md                  # contrato entre módulos (fonte da verdade)
├── README.md
├── backend/
│   ├── run.ps1                  # sobe tudo no Windows
│   ├── requirements.txt
│   ├── .env.example
│   ├── app/
│   │   ├── main.py              # FastAPI, rotas /api/*
│   │   ├── config.py            # variáveis de ambiente
│   │   ├── llm.py               # wrapper único do Claude + modo mock
│   │   ├── agent/               # orquestrador das 8 etapas
│   │   │   ├── orchestrator.py  # handle_message()
│   │   │   ├── guardrails.py    # entrada e saída
│   │   │   ├── memory.py        # slots da conversa
│   │   │   ├── nlu.py           # intenção + entidades
│   │   │   ├── tools_erp.py     # ferramentas do ERP
│   │   │   ├── text_to_sql.py   # SQL somente-leitura validado
│   │   │   └── handoff.py       # transferência para humano
│   │   ├── rag/                 # build_index() e retrieve()
│   │   └── db/
│   │       ├── schema.sql, seed.py, connection.py
│   │       └── knowledge/*.md   # base de conhecimento (políticas, FAQ, manuais)
│   ├── data/                    # flow.db e índice (gerados)
│   └── tests/
├── frontend/                    # React 18 + Vite + TypeScript
├── automations/n8n/             # 3 workflows + README
└── docs/
    ├── arquitetura.md           # diagramas mermaid
    ├── relatorio-extensao.md    # relatório acadêmico
    └── roteiro-demo.md          # roteiro da apresentação (~10 min)
```

## Dados de demonstração

| Cliente | Documento | Pedido | Situação |
|---|---|---|---|
| Maria Souza (PF) | CPF `123.456.789-09` | `FL-2026-00042` | enviado, com boleto em aberto |
| Escritório Alfa Ltda (PJ) | CNPJ `11.222.333/0001-81` | `FL-2026-00043` | em separação |

Todos os dados são fictícios.
