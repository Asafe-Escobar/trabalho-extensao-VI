# NOTES — módulo DATABASE + RAG

Dono: agente "banco". Segue CONTRACT.md (incl. ATUALIZAÇÃO 22/11 — gás GLP/água + RevGás).

## DATABASE (`backend/app/db`)
- `connection.py`: `get_conn()`, `get_readonly_conn()` (URI `mode=ro`), `init_db(reset=False)`.
  Lê `config.DB_PATH` a cada chamada (testes trocam). Banco antigo (sem `produtos.revgas_id` ou sem
  `vendas_revgas`) é **recriado automaticamente** com o seed de gás.
- `schema.sql`: + `produtos.revgas_id UNIQUE`, `produtos.container_revgas_id`, `clientes.endereco/numero/bairro`,
  tabela `vendas_revgas` (status `DRYRUN|ENVIADA|ERRO`, `numero_local` UNIQUE), `financeiro.tipo` aceita também
  `'dinheiro'`. Views `vw_catalogo`, `vw_estoque`, `vw_vendas_resumo` iguais ao contrato + nova `vw_vendas_chatbot(dia, status, qtd_vendas, total)`.
- `seed.py`: produtos lidos de `integrations/revgas_catalogo_snapshot.json` + tabela `CATALOGO` (curadoria:
  sem TESTE/AAAA/2222/SADASD/BARA BARA/LLLL/CARLOS/TIGRINHO/FEIA/Furador). 71 produtos, 52 ativos; variações
  legadas do cadastro RevGás (ex.: GLP 13KG NORMAL 24230) entram com `ativo=0` (não aparecem em `vw_catalogo`).
  SKUs principais: `GLP-P13` (26717, R$125, vasilhame 26718 `VAS-P13` R$180), `GLP-P45` (23974, R$480, vasilhame
  23975), `GLP-P20` (28117, R$300), `AGUA-20L` (26255, R$12, galão `VAS-AGUA-20L` 24616), `ACE-KIT-REG` (26276, R$100).
  `vendas_revgas` começa vazia (numeração RV-DRY-xxxx fica com o adaptador do BACKEND).

### Decisões que o BACKEND deve conhecer
1. **Preço do P45**: o snapshot diz R$100 (a própria doc avisa "amostra pequena"); usei **R$480**. O regulador
   avulso 26318 tem R$12,31 no snapshot (valor de teste); usei **R$45**. Sugestão: o adaptador `revgas.py`
   usar `produtos.preco` do SQLite como preço de venda para manter base de conhecimento, catálogo e payload coerentes.
2. **Container da água 20L**: o snapshot não tem `container_id` para 26255; usei 24616 (galão vazio das outras 20L).
3. Escritório Alfa Ltda manteve o nome (frontend/README usam) e virou cliente B2B "Restaurante (central de gás P45)".
4. `previsao_entrega` agora é data+hora (`'2026-11-22 11:40'`); `codigo_rastreio` = entregador (`'MOTO-07'`).

## RAG (`backend/app/rag`)
- API do contrato em `app/rag/__init__.py` (+ extras: `reset_cache()`, `index_info()`, `TECNICAS`).
- `RetrievalTrace` tem campos extras opcionais: `grafo_entidades`, `hype_perguntas`, `embeddings` (bons para o painel).
- BM25 é a linha de base sempre ativa; `hybrid` acrescenta o vetorial (RRF k=60).
- `contexto` aceito: `produto_sku`/`produto`/`produto_nome`, `pedido_numero`, `carrinho[{revgas_id}]` (vira semente do grafo).
  CPF/CNPJ do contexto nunca entra na consulta.
- Domínio: botijão = P13 = gás de cozinha = GLP 13 kg; galão = água 20L; P45 = cilindro 45 kg; "gasolina/GNV" é
  tópico próprio (não vendemos) e não dispara GLP.
- Grafo: produto–vasilhame (`usa_vasilhame`, via container da RevGás), acessório–produto (`compativel_com`),
  produto–categoria/marca, chunk–produto/termo/categoria, doc–termo. Helper `graph.vizinhos_produto(g, sku)`.
- Índice em `config.INDEX_DIR`; assinatura = base + produtos + modo; mudou o código do RAG, suba `INDEX_VERSION`.
- Mock (sem chave): ~20–70 ms por consulta, build ~3 s. Com Claude: rewrite/multi-query/expansion/HyDE/rerank via
  `llm.py` (em paralelo) e HyPE via LLM no build (108 chunks, 6 threads), com fallback para template.

## Testes
`cd backend; .\.venv\Scripts\python -m pytest tests/test_db.py tests/test_rag.py` → 71 passam (suíte completa: 130).
Dependências instaladas no .venv: pydantic, rank_bm25, scikit-learn, networkx, numpy, pytest
(BACKEND: garantir no requirements.txt).
