// Rótulos amigáveis em pt-BR para valores técnicos vindos da API.

export const INTENCOES: Record<string, string> = {
  consultar_preco: "Consultar preço",
  consultar_estoque: "Consultar estoque",
  consultar_pedido: "Consultar pedido",
  segunda_via_boleto: "2ª via de boleto",
  troca_devolucao: "Troca / devolução",
  garantia: "Garantia",
  duvida_politica: "Dúvida de política",
  recomendacao_produto: "Recomendação de produto",
  pedir_desconto: "Pedido de desconto",
  falar_atendente: "Falar com atendente",
  saudacao: "Saudação",
  relatorio_interno: "Relatório interno",
  outro: "Outro",
  em_atendimento_humano: "Em atendimento humano",
  fazer_pedido: "Fazer pedido",
  seguranca_vazamento: "Segurança: vazamento",
};

export const PAGAMENTOS: Record<string, string> = {
  MONEY: "Dinheiro",
  PIX: "Pix",
  CARTAO_DE_DEBITO: "Cartão de débito",
  CARTAO_DE_CREDITO: "Cartão de crédito",
  FETLOCK: "Boleto",
  WALLET: "Carteira",
  CREDITO_CLIENTE: "Crédito do cliente",
  CREDISHOP: "Credishop",
};
// Aceita o código da RevGás (PIX, MONEY...) ou um rótulo já pronto vindo do back ("Pix").
export const rotuloPagamento = (p: string) => PAGAMENTOS[p] ?? PAGAMENTOS[p.toUpperCase()] ?? (/^[A-Z_]+$/.test(p) ? p.replace(/_/g, " ").toLowerCase() : p);

/** O back grava datas do SQLite em UTC sem fuso ("2026-11-22 19:21:54"): sem fuso explícito, trata como UTC. */
export function parseData(iso: string): number {
  const s = iso.trim().replace(" ", "T");
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return Date.parse(s + "T12:00:00");
  return Date.parse(/(Z|[+-]\d{2}:?\d{2})$/.test(s) ? s : s + "Z");
}
export const brl = (v: number) => (Number(v) || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export const TECNICAS: Record<string, string> = {
  intent_classification: "Intent Classification",
  entity_extraction: "Entity Extraction",
  conversation_memory: "Conversation Memory",
  query_rewriting: "Query Rewriting",
  rewrite: "Query Rewriting",
  multi_query: "Multi-Query",
  query_expansion: "Query Expansion",
  expansion: "Query Expansion",
  hyde: "HyDE",
  hype: "HyPE",
  graph: "GraphRAG",
  graph_rag: "GraphRAG",
  graphrag: "GraphRAG",
  hybrid: "RAG híbrido",
  rag_hibrido: "RAG híbrido",
  rerank: "Reranking",
  reranking: "Reranking",
  agentic_rag: "Agentic RAG",
  tool_calling: "Tool Calling",
  text_to_sql: "Text-to-SQL",
  guardrails: "Guardrails",
  guardrails_entrada: "Guardrails (entrada)",
  guardrails_saida: "Guardrails (saída)",
  human_handoff: "Human Handoff",
  handoff: "Human Handoff",
  lead_scoring: "Lead Scoring",
  slot_filling: "Slot Filling (venda)",
  criar_venda: "Criar venda (RevGás)",
};

export const ESTAGIOS: { chave: string; rotulo: string }[] = [
  { chave: "novo", rotulo: "Novo" },
  { chave: "qualificado", rotulo: "Qualificado" },
  { chave: "proposta", rotulo: "Proposta" },
  { chave: "ganho", rotulo: "Ganho" },
  { chave: "perdido", rotulo: "Perdido" },
];

export const STATUS_HANDOFF: Record<string, string> = {
  pendente: "Pendente",
  em_atendimento: "Em atendimento",
  resolvido: "Resolvido",
};

export const rotuloIntencao = (i: string) => INTENCOES[i] ?? i.replace(/_/g, " ");
export const rotuloTecnica = (t: string) => TECNICAS[t] ?? t.replace(/_/g, " ");
export const rotuloChave = (k: string) => k.replace(/_/g, " ");

export function tempoRelativo(iso: string): string {
  const t = parseData(iso);
  if (Number.isNaN(t)) return iso;
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 45) return "agora";
  const m = Math.round(s / 60);
  if (m < 60) return `há ${m} min`;
  const h = Math.round(m / 60);
  if (h < 24) return `há ${h} h`;
  return new Date(t).toLocaleDateString("pt-BR");
}

export function hora(iso?: string): string {
  if (!iso) return "";
  const t = parseData(iso);
  if (Number.isNaN(t)) return "";
  return new Date(t).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

export function formatarValor(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") {
    return Number.isInteger(v) ? v.toLocaleString("pt-BR") : v.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
  }
  if (typeof v === "boolean") return v ? "sim" : "não";
  if (Array.isArray(v)) {
    return v
      .map((x) => {
        if (x && typeof x === "object" && "nome" in x) {
          const o = x as { nome: unknown; qtd?: unknown; quantidade?: unknown };
          const q = o.qtd ?? o.quantidade;
          return q != null ? `${q}× ${String(o.nome)}` : String(o.nome);
        }
        return typeof x === "object" ? JSON.stringify(x) : String(x);
      })
      .join(", ");
  }
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if ("rua" in o || "bairro" in o) return [o.rua && `${o.rua}${o.numero ? `, ${o.numero}` : ""}`, o.bairro, o.cidade].filter(Boolean).join(" – ");
    return JSON.stringify(v);
  }
  return String(v);
}
