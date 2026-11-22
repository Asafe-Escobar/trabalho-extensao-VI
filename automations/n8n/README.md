# Automações n8n — Flow Gás

Três workflows importáveis (`Workflows → Import from File`). Todos começam **inativos**: configure as
variáveis e credenciais antes de ativar.

| Arquivo | Gatilho | Fluxo |
|---|---|---|
| `01-nutricao-leads.json` | Webhook `POST /webhook/flow-lead` (chamado pelo backend em `registrar_lead`) | Normaliza o lead → score ≥ 70? **Sim:** avisa vendedor no Telegram + WhatsApp imediato + estágio `qualificado`. **Não:** espera 1 dia → e-mail de conteúdo → espera 3 dias → WhatsApp com oferta → estágio `proposta` |
| `02-notificacao-handoff.json` | Webhook `POST /webhook/flow-handoff` (chamado em `transferir_atendente`) | Formata resumo → Telegram + e-mail da equipe → se urgente (vazamento, reclamação, Procon, cancelamento) espera 10 min e, se o handoff ainda estiver pendente, escala para a gerência |
| `03-pos-venda.json` | Todo dia às 9h | Busca pedidos entregues ontem → WhatsApp com pesquisa NPS → espera 3 dias → e-mail com produto relacionado (ex.: comprou P13, recebe oferta de regulador/mangueira) |

## Variáveis de ambiente do n8n

| Variável | Exemplo | Usada em |
|---|---|---|
| `FLOW_API_URL` | `http://host.docker.internal:8000` | 01, 02, 03 |
| `FLOW_FRONT_URL` | `http://localhost:5173` | 02 (link do painel) |
| `FLOW_AUTOMACAO_TOKEN` | mesmo valor do `backend/.env` | 03 |
| `WHATSAPP_API_URL`, `WHATSAPP_TOKEN` | provedor de WhatsApp (Z-API, Evolution, Twilio…) que aceite `{to, text}` | 01, 03 |
| `TELEGRAM_CHAT_VENDAS`, `TELEGRAM_CHAT_ATENDIMENTO`, `TELEGRAM_CHAT_GERENCIA` | id do grupo | 01, 02 |
| `FLOW_EMAIL_FROM`, `FLOW_EMAIL_ATENDIMENTO` | `atendimento@flowgas.example` | 01, 02, 03 |

Credenciais: **Telegram API** (nos nós Telegram) e **SMTP** (nos nós de e-mail). Os nós de envio estão com
"continuar em caso de erro", então o fluxo segue mesmo sem algum canal configurado.

## Ligando ao backend

No `backend/.env`:

```
N8N_WEBHOOK_URL=http://localhost:5678/webhook/flow-lead
N8N_HANDOFF_WEBHOOK_URL=http://localhost:5678/webhook/flow-handoff
FLOW_AUTOMACAO_TOKEN=troque-este-valor
```

Endpoints do backend usados pelos workflows: `PATCH /api/leads/{id}`, `GET /api/handoffs?status=pendente`
e `GET /api/automacoes/pedidos-entregues?dias=1` (contrato em `CONTRACT.md`).

## Teste rápido sem o chatbot

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:5678/webhook-test/flow-lead -ContentType 'application/json' `
  -Body '{"id":1,"nome":"Restaurante Sabor do Delta","telefone":"86999990000","email":"compras@sabor.example","interesse":"contrato mensal de P45","origem":"chatbot","score":85}'
```

(Use `webhook-test` com o workflow aberto no editor e "Listen for test event"; `webhook` depois de ativar.)
