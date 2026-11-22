# Integração RevGás (ERP real)

Base: `https://api.revgas.com/v1` · header `Authorization: <REVGAS_API_KEY>` (sem "Bearer") +
`Content-Type: application/json`. A chave fica **só** em `backend/.env` (`REVGAS_API_KEY`), nunca no código,
em testes, logs ou no frontend.

Levantamento feito em 22/11/2026 com a chave do projeto (sem documentação pública):

| Endpoint | Status com nossa chave | Uso no chatbot |
|---|---|---|
| `GET /products?page=&page_size=` | 200 | catálogo + estoque (`consultar_estoque`, `consultar_preco`) |
| `GET /sales?page=&page_size=` | 200 | histórico, métricas, preço praticado |
| `POST /sales` | **não testado** (grava venda real) | `criar_venda` — FOCO do projeto |
| `GET /customers`, `GET /orders` | 403 (sem permissão) | clientes ficam no SQLite local |

Paginação: `{"data":[...], "pagination":{"count","has_next","page","page_size","total_count"}}`.

## Produto (`GET /products`)
```json
{"id": 26717, "description": "GLP 13KG", "stock_quantity": 939, "lent_quantity": 24, "transit_quantity": 281,
 "inactive": false, "revgas_product_id": 3, "container_id": 26718,
 "variation_options": [{"id": 24686, "description": "ENVASADO NO BOTIJÃO", "variation_type": "TIPO"}],
 "establishment_id": 2580, "commission_value": 0, "customized_product_id": 10442}
```
- Não há campo de preço: o preço de referência vem da mediana de `products[].value` nas vendas
  (snapshot em `backend/app/integrations/revgas_catalogo_snapshot.json`).
- `container_id` = vasilhame (botijão vazio) associado. Venda de gás com **troca** de botijão = só o GLP;
  cliente **sem botijão** = GLP + vasilhame (ex.: GLP 13KG 26717 + VASILHAME 13KG 26718).
- A conta é de homologação: ignore produtos com "TESTE", "AAAA", "2222" ou estoque 0 ao recomendar.

Preços de referência (mediana das vendas): GLP 13KG (26717) R$ 125 · GLP 13KG NORMAL (24230) R$ 150 ·
GLP 20KG (28117) R$ 300 · VASILHAME 20KG (28118) R$ 50 · GLP 45KG MA (23974) R$ 100 (amostra pequena) ·
KIT REGULADOR (26276) R$ 100 · REGULADOR 123 (26318) R$ 12,31 · água 1,5L/350ml R$ 5.

## Venda (`GET /sales`)
```json
{"id": 30969866, "date": "2026-11-22T15:43:50-03:00", "channel": "WHATSAPP",
 "location": "Rua ...", "number": "2003", "neighborhood": "...", "city": "...", "state_federation": "PI",
 "observation": "...", "lat": -5.0, "lon": -42.8, "total": 660.0, "paid": false, "status": "ACTIVE",
 "products": [{"product_id": 26717, "quantity": 6, "value": 110.0, "discount": 0, "product_description": "GLP 13KG"}],
 "payments": [{"date": "2026-11-22", "value": 660.0, "payment_type": "MONEY"}],
 "establishment_id": 2580, "display_customer": "...", "logs": [{"status": "OPEN"}]}
```
- `channel` observados: `WHATSAPP`, `DISK`, `SINO`. O chatbot usa `WHATSAPP`.
- `status`: `ACTIVE` (aberta), `CONFIRM` (confirmada/entregue), `CANCEL`, `WARNING`.
- `payment_type`: `MONEY` (Dinheiro), `PIX`, `CARTAO_DE_DEBITO`, `CARTAO_DE_CREDITO`, `FETLOCK` (Boleto),
  `WALLET` (Carteira), `CREDITO_CLIENTE`, `CREDISHOP`.

## `POST /sales` — payload proposto (INFERIDO do GET, confirmar com o suporte RevGás)
```json
{"channel": "WHATSAPP",
 "location": "Rua Augusto Freire", "number": "2003", "neighborhood": "Centro",
 "city": "Teresina", "state_federation": "PI", "observation": "Pedido via Flow Assistente. Troco para 200.",
 "products": [{"product_id": 26717, "quantity": 1, "value": 125.0, "discount": 0}],
 "payments": [{"payment_type": "PIX", "value": 125.0, "date": "2026-11-22"}]}
```

## Modos do adaptador (`REVGAS_MODO` no `.env`)
- `dryrun` (**padrão**): não chama o POST. Monta e valida o payload, grava a venda no SQLite local
  (tabela `vendas_revgas`) com `revgas_id = null`, `status = 'DRYRUN'` e devolve um número local `RV-DRY-0001`.
  Os GETs de produto continuam reais se houver chave (com cache de 5 min e fallback para o snapshot).
- `real`: faz o POST de verdade. Só ligar na demo, com autorização. Erros da API viram resposta educada +
  handoff para atendente.
- `offline`: nada de rede; tudo do snapshot (testes e apresentação sem internet).
