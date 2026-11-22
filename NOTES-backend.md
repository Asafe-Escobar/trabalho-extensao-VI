# NOTES — módulo BACKEND (Flow Gás × RevGás)

## Arquivos do BACKEND
- `backend/requirements.txt`, `.env.example`, `run.ps1` (`-Reset`, `-SemReload`, `-Porta`)
- `app/main.py` (CORS 5173, lifespan: `init_db` + índice do RAG em thread). Registra também `app/api/vendas.py` (do maestro), **preservado**.
- `app/api/routes.py`: todas as rotas `/api/*` do contrato + `/api/vendas-revgas`, `/api/revgas/status`, `PATCH /api/leads/{id}`,
  `GET /api/automacoes/pedidos-entregues` (header `X-Flow-Token` se `FLOW_AUTOMACAO_TOKEN` existir) e `GET /api/conversas/{id}`.
- `app/integrations/revgas.py`: adaptador (modos `dryrun` (padrão) / `real` / `offline`, cache de 5 min, fallback pro snapshot, `truststore` para TLS no Windows).
  A chave só vai no header `Authorization` e nunca é logada nem devolvida. **Só `real` faz POST /sales.**
- `app/agent/`: `orchestrator.py` (pipeline de 8 passos + fluxo de venda), `nlu.py`, `guardrails.py`, `memory.py`, `tools_erp.py`,
  `text_to_sql.py`, `handoff.py`, `schemas.py`, `deps.py` (ponte com `app.db`/`app.rag`; stub se faltar).
- `app/config.py`: só adicionei `REVGAS_*`, `N8N_*`, `FLOW_AUTOMACAO_TOKEN` no fim.

## Fluxo de venda (`fazer_pedido`)
Máquina de estados **determinística** nos dois modos (mock e Claude): itens → troca de botijão (se não tiver, entra o vasilhame
`container_id` na mesma quantidade) → endereço (sugere o do CRM se o CPF foi verificado) → bairro → pagamento (cartão pergunta
débito/crédito) → troco (só dinheiro; valida que o troco é ≥ total) → RESUMO "Confirma o pedido?" → só depois de um "sim" explícito
chama `criar_venda`. "não" pergunta o que mudar; "cancelar" limpa o carrinho; "tira a água" e "quero também…" editam o carrinho.
No modo Claude o LLM **não** tem a ferramenta `criar_venda` no loop livre: só o fluxo, após o "sim", cria a venda.

## Alinhado com o NOTES-frontend.md
- `debug.venda` = `{numero, status, total, itens[{nome,qtd,preco,revgas_id}], endereco{...}, pagamento, payload, troco_para, previsao}`.
- `debug.memoria` expõe `carrinho[{nome,qtd,preco}]`, `endereco`, `pagamento`, `troco_para`, `tem_botijao_para_troca`, `etapa_venda` e **`aguardando`**.
- Vazamento: guardrail `seguranca_vazamento_gas`, `debug.intencao = "seguranca_vazamento"`, handoff com motivo `URGENTE: possível vazamento de gás`
  e `dados.prioridade = "URGENTE"`. Vale até com a conversa em atendimento humano.
- Conversa com humano: `/api/chat` devolve `resposta: ""`. Ao resolver o handoff, grava uma mensagem `papel: "system"`.
- `GET /api/conversas/{id}/mensagens`: campo opcional `autor` (`bot` | `atendente` | `sistema`) nas mensagens que não são do usuário.
- Rótulos de técnica novos: `fluxo_venda`, `slot_filling`, `criar_venda`, `guardrail_confirmacao_explicita`, `lead_scoring`, `text_to_sql`.

## Decisões / pendências
- Text-to-SQL no chat do **cliente** só acessa `vw_catalogo`/`vw_estoque`; faturamento (`vw_vendas_resumo`, `vw_vendas_chatbot`) só no
  `/api/sql` (painel do gestor) ou em conversa criada com `POST /api/conversas {"canal":"gestor"}`.
- Preço: seed (SQLite `produtos.revgas_id`) > mediana do snapshot (descartada se < 50% do valor de referência, ex. P45 a R$ 100) > tabela padrão.
- `pedidos-entregues.sugestao`: regra produto→acessório (P13→kit regulador, P20/P45→mangueira pig tail, água→bomba), não GraphRAG.
- O payload do `POST /sales` é **inferido** (docs/revgas-api.md); confirmar com o suporte RevGás antes de ligar `REVGAS_MODO=real`.
- Testes: `tests/test_agent.py` + `tests/test_api.py` (offline, banco temporário, httpx mockado para os webhooks).
