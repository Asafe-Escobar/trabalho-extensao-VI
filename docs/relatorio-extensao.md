# Relatório de Projeto de Extensão

**Título:** Flow Assistente — chatbot de vendas e relacionamento integrado ao ERP RevGás para revenda de gás e água
**Instituição / curso:** _[preencher]_
**Equipe:** _[preencher]_ · **Orientador(a):** _[preencher]_
**Período:** novembro de 2026
**Parceiro:** Flow (revenda de GLP e água mineral, lojas em Teresina-PI, Parnaíba-PI e São Luís-MA), usuária do sistema RevGás

---

## 1. Introdução

Revendas de gás de cozinha trabalham com pedidos curtos, urgentes e repetitivos: o cliente quer saber o
preço do botijão, se há entrega no bairro e em quanto tempo chega. Na Flow, esses pedidos chegam por telefone
(canal "DISK") e WhatsApp e são digitados à mão no sistema RevGás. No levantamento feito na API da empresa
(105 vendas entre 3 e 22 de novembro de 2026), 69% dos pedidos vieram por telefone, 30% por WhatsApp e 26%
terminaram cancelados. Cada pedido exige atenção de um atendente, inclusive fora do horário comercial, e
dúvidas recorrentes (validade do regulador, troca de vasilhame, formas de pagamento) ocupam a mesma fila
das vendas.

O projeto propõe um assistente conversacional que atende o cliente, responde dúvidas com base nas políticas
da empresa, consulta o catálogo e o estoque no ERP e **lança a venda diretamente na RevGás**, transferindo
para um humano quando necessário.

## 2. Justificativa

- **Conversão:** pedido de gás é decisão imediata. Se ninguém responde em minutos, o cliente liga para outra
  revenda. Atendimento automático 24h reduz a perda.
- **Retrabalho:** a venda nasce estruturada no chat e vai para o ERP via API, sem redigitação.
- **Segurança:** relatos de cheiro de gás precisam de orientação imediata e correta. O chatbot aplica uma regra
  determinística de emergência antes de qualquer outra etapa.
- **Relacionamento:** clientes B2B (restaurantes, condomínios) têm consumo recorrente de P45; leads
  qualificados são nutridos automaticamente via n8n.
- **Extensão universitária:** o projeto aplica conteúdos de IA, bancos de dados e engenharia de software
  a um problema real de um pequeno negócio local do Piauí e Maranhão.

## 3. Objetivos

**Geral:** desenvolver um chatbot que converta pedidos e nutra o relacionamento com clientes da Flow,
integrado ao ERP RevGás.

**Específicos:**
1. Conduzir o pedido completo no chat (produto, quantidade, troca de vasilhame, endereço, pagamento,
   confirmação) e registrá-lo na RevGás via `POST /sales`.
2. Responder dúvidas com recuperação aumentada por geração (RAG) sobre uma base de conhecimento da empresa.
3. Consultar catálogo, estoque, pedidos e financeiro com controle de acesso por titularidade (CPF/CNPJ).
4. Aplicar guardrails de segurança (vazamento de gás), privacidade (LGPD) e política comercial (descontos).
5. Transferir para atendente humano com resumo da conversa.
6. Oferecer ao gestor métricas e consultas em linguagem natural (Text-to-SQL controlado).
7. Automatizar nutrição de leads, alerta de handoff e pós-venda com n8n.

## 4. Público beneficiado

Clientes residenciais e comerciais da Flow nas três cidades; atendentes, que passam a receber apenas os casos
que precisam de pessoa; e a gestão, que ganha visibilidade sobre vendas, leads e dúvidas frequentes.

## 5. Fundamentação teórica e técnicas aplicadas

| Técnica | Papel no Flow Assistente |
|---|---|
| Intent Classification | identifica o objetivo da mensagem (`fazer_pedido`, `consultar_preco`, `garantia`, `falar_atendente`...) |
| Entity Extraction | extrai produto, quantidade, CPF/CNPJ, número do pedido, filial, endereço |
| Conversation Memory | guarda slots (carrinho, endereço, cliente verificado) entre mensagens |
| Query Rewriting | reescreve perguntas dependentes de contexto ("e a mangueira?") em consultas completas |
| Query Expansion | sinônimos do domínio: botijão = P13 = gás de cozinha = GLP 13 kg; galão = água 20 L |
| Multi-Query | gera variações da pergunta para aumentar a cobertura da busca |
| HyDE | gera uma resposta hipotética e a usa como consulta vetorial |
| HyPE | no indexamento, gera perguntas hipotéticas para cada trecho da base |
| RAG híbrido | combina BM25 (palavras) e busca vetorial, fundidos por Reciprocal Rank Fusion |
| Reranking | reordena os candidatos por relevância antes de montar o contexto |
| GraphRAG | grafo produto–vasilhame–acessório–política que expande a busca por vizinhança |
| Agentic RAG + Tool Calling | o modelo decide quais ferramentas chamar (catálogo RevGás, estoque, pedido, `criar_venda`) |
| Text-to-SQL controlado | perguntas do gestor viram `SELECT` validado com `sqlglot` sobre views sem dados sensíveis |
| Guardrails | regras em código para emergência de gás, prompt injection, dados de terceiros e descontos |
| Human Handoff | transfere a conversa com resumo e dados coletados para o painel do atendente |

O modelo de linguagem é o Claude (Anthropic), acessado por um único módulo (`llm.py`). Um **modo mock**
reproduz todo o fluxo com regras e expressões regulares, o que permite rodar a demonstração sem custo e sem
internet e torna o comportamento dos guardrails independente do modelo.

## 6. Metodologia

1. **Levantamento:** reunião com o parceiro e leitura da API RevGás (endpoints `/products` e `/sales`), que
   revelou o formato das vendas, canais, formas de pagamento e a relação produto–vasilhame (`container_id`).
2. **Contrato entre módulos:** um documento único (`CONTRACT.md`) definiu tabelas, assinaturas e o JSON da API,
   permitindo que banco, RAG/back-end, front-end e documentação fossem desenvolvidos em paralelo.
3. **Desenvolvimento incremental** com testes automatizados por módulo (`backend/tests`).
4. **Segurança da integração:** a chave da RevGás fica apenas no `.env`; o adaptador tem três modos —
   `offline` (snapshot local), `dryrun` (monta e valida a venda sem gravar no ERP; padrão) e `real`
   (grava via `POST /sales`, habilitado só com autorização do parceiro).
5. **Validação** com o roteiro de demonstração (`docs/roteiro-demo.md`), uma mensagem por técnica.

## 7. Arquitetura

Front-end React (chat do cliente com painel "Por dentro do bot", painel do atendente e painel do gestor) →
API FastAPI → orquestrador em 8 etapas (guardrails de entrada, memória, NLU, Agentic RAG com ferramentas,
Text-to-SQL, guardrails de saída, handoff, lead scoring) → SQLite (CRM local, histórico, memória), índice RAG
e adaptador RevGás. O n8n recebe webhooks de lead e handoff e consulta a API para o pós-venda. Diagramas em
[`arquitetura.md`](arquitetura.md); detalhes da integração em [`revgas-api.md`](revgas-api.md).

## 8. Resultados

_[Preencher após a apresentação ao parceiro: número de conversas testadas, taxa de pedidos concluídos no
chat, tempo médio até a confirmação, perguntas que geraram handoff, avaliação dos atendentes.]_

Resultados técnicos obtidos:
- Fluxo de venda completo no chat, gerando o payload no formato da RevGás e registrando a venda
  (modo `dryrun` nos testes; modo `real` pronto para homologação).
- Todas as 15 técnicas exigidas visíveis no painel de depuração, mensagem a mensagem.
- Guardrails ativos mesmo sem modelo de linguagem (modo mock).
- Três automações n8n importáveis.

## 9. Limitações e próximos passos

- O formato do `POST /sales` foi inferido das vendas existentes; precisa ser confirmado com o suporte RevGás
  antes do uso em produção.
- A chave atual não tem acesso a `/customers`, por isso o cadastro de clientes é mantido localmente.
- A API não expõe preço de tabela: usamos o preço praticado nas vendas como referência.
- Próximos passos: canal WhatsApp oficial (Cloud API), roteirização de entregas por bairro com `lat/lon`,
  previsão de recompra (o cliente que compra P13 a cada 30 dias recebe lembrete).

## 10. Considerações finais

O projeto mostrou que técnicas atuais de IA conversacional podem ser aplicadas a um negócio de bairro com
ganho concreto: o pedido que antes dependia de um atendente disponível passa a ser registrado direto no ERP,
com segurança e rastreabilidade, e a equipe fica com os casos que realmente precisam de uma pessoa.

## Referências

- ANTHROPIC. *Claude API documentation*. Disponível em: https://docs.anthropic.com. Acesso em: nov. 2026.
- GAO, L. et al. *Precise Zero-Shot Dense Retrieval without Relevance Labels* (HyDE). ACL, 2023.
- LEWIS, P. et al. *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. NeurIPS, 2020.
- CORMACK, G.; CLARKE, C.; BUETTCHER, S. *Reciprocal Rank Fusion outperforms Condorcet and individual rank
  learning methods*. SIGIR, 2009.
- EDGE, D. et al. *From Local to Global: A Graph RAG Approach to Query-Focused Summarization*. Microsoft Research, 2024.
- ROBERTSON, S.; ZARAGOZA, H. *The Probabilistic Relevance Framework: BM25 and Beyond*. 2009.
- BRASIL. Lei nº 13.709/2018 (LGPD).
- ABNT NBR 15526 e orientações da ANP sobre instalação e uso de GLP em residências.
- n8n. *Documentation*. Disponível em: https://docs.n8n.io.
