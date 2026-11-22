# NOTES — módulo FRONTEND (Flow Gás)

Combinados com o BACKEND/back. O front consome exatamente o `CONTRACT.md` (incl. ATUALIZAÇÃO 22/11);
os itens abaixo são o que o front **espera** ou **tolera** além do texto do contrato.

## Como rodar
- `npm run dev` → usa a API em `VITE_API_URL` (padrão `http://localhost:8000`). CORS precisa liberar `http://localhost:5173`.
- `npm run dev:mock` → modo mock no navegador (`.env.mock`, `VITE_USE_MOCK=true`), sem backend e **sem rede**:
  toda venda é `DRYRUN` com número local `RV-DRY-0001`. Estado no `localStorage` (as 3 telas se enxergam entre abas).
- `npm test` → teste de fumaça (52 verificações: fluxo de venda, guardrails, card de pedido, markdown, zero chamadas de rede).
- `npm run build` → `tsc -b && vite build` (passando).

## Endpoints usados
| Tela | Chamada |
|---|---|
| Chat | `POST /api/conversas`, `POST /api/chat`, `GET /api/conversas/{id}/mensagens` (polling a cada 3,5 s enquanto `status_conversa == "humano"`) |
| Atendente | `GET /api/handoffs?status=pendente|em_atendimento|resolvido` (uma chamada por status, para os contadores), `POST /api/handoffs/{id}/assumir`, `POST /api/handoffs/{id}/resolver`, `POST /api/atendente/mensagem`, `GET /api/conversas/{id}/mensagens` |
| Gestor | `GET /api/metricas`, `GET /api/leads`, `POST /api/sql`, **`GET /api/vendas-revgas`**, **`GET /api/revgas/status`** |
| Topo | `GET /api/health`, `GET /api/revgas/status` (se falhar, a pílula some) |

## O que o front espera do back (por favor confirmar)
1. **`debug.venda`** quando `criar_venda` roda: `{numero, status: "DRYRUN"|"ENVIADA"|"ERRO", total, itens:[{nome,qtd,preco,revgas_id?}], endereco: {rua,numero,bairro,cidade} | string, pagamento, payload, troco_para?, previsao?}`.
   O `payload` é o JSON do `POST /sales` **sem a chave** (o painel mostra canal, endereço, products, payments, observation e o JSON bruto).
   Fallback: se `debug.venda` vier nulo, o front monta o card a partir de `ferramentas[nome="criar_venda"].entrada` (payload)
   e pega número/status de `saida_resumo` via regex `RV-[A-Z0-9-]+` e `DRYRUN|dry-run|erro`.
2. **Card de "resumo aguardando confirmação"**: aparece quando `debug.memoria.aguardando == "confirmacao"` **ou** a resposta contém
   "Confirma o pedido?" e `debug.memoria.carrinho` é lista `[{nome,qtd,preco}]`. Sugestão: expor `carrinho`, `endereco`, `pagamento`,
   `troco_para`, `aguardando` em `debug.memoria` (já são slots do contrato).
3. **Vazamento de gás**: a bolha fica vermelha se algum `debug.guardrails[].regra` casar `/vazamento|seguranca|emergencia/i`
   (o mock usa `seguranca_vazamento_gas`). No painel do atendente o handoff vira **URGENTE** (vai para o topo) se
   `motivo` casar `/emergencia|vazamento|urgente/i` ou `dados.prioridade == "URGENTE"`.
4. **Conversa com humano**: se o bot ficar em silêncio, `POST /api/chat` pode devolver `resposta: ""` (o front não desenha bolha vazia).
   Ao resolver, uma mensagem `papel: "system"` no fim da conversa faz o chat voltar ao modo bot.
5. **Campo opcional `autor: "bot" | "atendente"`** em `GET /api/conversas/{id}/mensagens` (fora do contrato). Sem ele o front deduz:
   mensagem `assistant` sem `debug` conhecido, depois de um handoff, é do atendente.
6. `GET /api/vendas-revgas` no formato do contrato (`{numero_local, revgas_id, status, total, itens:[{nome,qtd,preco}], criado_em}`).
   O bloco "Vendas pelo chatbot" calcula vendas, valor total, ticket médio e botijões (itens cujo `nome` começa com `GLP`).
7. `POST /api/sql`: `linhas` pode vir como lista de objetos **ou** de arrays (o front normaliza pela ordem de `colunas`).
8. Rótulos de intenção conhecidos pelo front: os do contrato + `fazer_pedido`, `seguranca_vazamento`. Rótulos de técnica:
   além das do contrato, `slot_filling` e `criar_venda`. Valores desconhecidos aparecem com `_` trocado por espaço.

## Segurança
- O front nunca recebe nem exibe `REVGAS_API_KEY`; o teste verifica que nada com `api_key`/`authorization` aparece no debug do mock.
- O mock não faz `fetch` (o teste substitui `fetch` por um que falha e confere zero chamadas).

## Teste ponta a ponta contra o backend REAL (22/11, ~16h30)
`node frontend/e2e/roteiro-demo.mjs` (Chrome headless via CDP, segue `docs/roteiro-demo.md`): **38/38 ok, zero erro de console/HTTP**.
Screenshots: `frontend/e2e/screenshots/01…14-*.png`. Cada execução cria 1 venda DRYRUN e 3 handoffs no banco do back (só local).

### Ajustes feitos no FRONT para casar com o back real
- Datas `"2026-11-22 19:21:54"` (UTC do SQLite, sem fuso) agora são lidas como UTC (`parseData` em `rotulos.ts`); antes apareciam 3 h adiantadas.
- `criar_venda.entrada` vem como `{confirmado, payload_revgas}` → card e painel desembrulham `payload_revgas` (o caminho principal continua `debug.venda.payload`).
- `debug.venda.pagamento` vem como rótulo ("Pix"), não código ("PIX") → `rotuloPagamento` aceita os dois.
- `handoff.dados.endereco = {}` não aparece mais como linha vazia.
- `/api/sql` → mostra `explicacao`; SQL de uma linha quebra no card; colunas de valor (`faturamento`, `total`…) em R$.
- Conversa reaberta: `GET /mensagens` não traz o status → o front deduz "com atendente" pelo histórico (transferência ou `autor: "atendente"` depois do último `system`) e liga o polling.

### Observações para o BACK (não editei; fora os 4 bugs de NLU já em correção)
1. `criado_em` sem fuso: sugiro ISO com `Z` (ou `-03:00`) em todas as respostas.
2. `GET /api/conversas/{id}/mensagens` não informa o status da conversa; um `GET /api/conversas/{id}` com `status` eliminaria a dedução no front.
3. "Tô sentindo cheiro de gás na cozinha": intenção `seguranca_vazamento` com **confiança 0.4** e entidade `produto: "gas na cozinha"` (o guardrail funciona; só o NLU fica estranho no painel).
4. "Não tenho o botijão vazio" gera entidade `produto: "botijao vazio", quantidade: 1` (o carrinho fica certo, mas o painel sugere item novo).
5. Pedido demo FL-2026-00042: "saiu para entrega" com previsão `22/11/2026 às 11h40`, já passada no horário da demo (seed).
