// Cliente tipado da API do Flow Assistente (ver CONTRACT.md).
import { mockApi } from "./mock";

export const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true";

// ---------- Tipos ----------
export type StatusConversa = "bot" | "humano" | "encerrada";
export type FonteChunk = "bm25" | "vetorial" | "grafo" | "hype" | string;

export interface RetrievalTrace {
  original: string;
  reescrita: string | null;
  multi_queries: string[];
  expansao: string[];
  hyde_doc: string | null;
  candidatos: number;
  tecnicas: string[];
}

export interface ChunkDebug {
  titulo: string;
  score: number;
  fonte: FonteChunk;
  trecho: string;
}

export interface FerramentaDebug {
  nome: string;
  entrada: Record<string, unknown>;
  saida_resumo: string;
}

export interface GuardrailDebug {
  regra: string;
  acao: string;
}

export interface DebugInfo {
  intencao: string;
  confianca: number;
  entidades: Record<string, unknown>;
  memoria: Record<string, unknown>;
  retrieval: RetrievalTrace | null;
  chunks: ChunkDebug[];
  ferramentas: FerramentaDebug[];
  sql: string | null;
  guardrails: GuardrailDebug[];
  handoff: { id: number; resumo: string } | null;
  tecnicas: string[];
  latencia_ms: number;
  modo_llm: "anthropic" | "mock" | string;
  /** Presente quando a ferramenta `criar_venda` foi executada (ATUALIZAÇÃO 22/11). */
  venda?: VendaDebug | null;
}

// ---------- RevGás (ATUALIZAÇÃO 22/11) ----------
export type StatusVenda = "DRYRUN" | "ENVIADA" | "ERRO";
export type TipoPagamento = "MONEY" | "PIX" | "CARTAO_DE_DEBITO" | "CARTAO_DE_CREDITO" | string;

export interface ItemVenda {
  nome: string;
  qtd: number;
  preco: number;
  revgas_id?: number;
}

export interface EnderecoVenda {
  rua?: string;
  numero?: string;
  bairro?: string;
  cidade?: string;
}

/** Payload enviado ao POST /sales da RevGás (docs/revgas-api.md). Nunca contém a chave. */
export interface RevgasPayload {
  channel?: string;
  location?: string;
  number?: string;
  neighborhood?: string;
  city?: string;
  state_federation?: string;
  observation?: string;
  products?: { product_id: number; quantity: number; value: number; discount?: number; product_description?: string }[];
  payments?: { payment_type: TipoPagamento; value: number; date?: string }[];
}

export interface VendaDebug {
  numero: string;
  status: StatusVenda | string;
  total: number;
  itens: ItemVenda[];
  endereco: EnderecoVenda | string | null;
  pagamento: TipoPagamento | null;
  payload: RevgasPayload | null;
  troco_para?: number | null;
  previsao?: string | null;
}

export interface VendaRevgas {
  numero_local: string;
  revgas_id: number | null;
  status: StatusVenda | string;
  total: number;
  itens: ItemVenda[];
  criado_em: string;
}

export interface RevgasStatus {
  modo: "dryrun" | "real" | "offline" | string;
  chave_configurada: boolean;
  produtos: number;
}

export interface ChatResponse {
  resposta: string;
  status_conversa: StatusConversa;
  sugestoes: string[];
  debug: DebugInfo | null;
}

export interface Mensagem {
  papel: "user" | "assistant" | "system";
  conteudo: string;
  criado_em: string;
  /** Opcional (fora do contrato): o backend pode indicar quem escreveu a mensagem. */
  autor?: "bot" | "atendente";
}

export type StatusHandoff = "pendente" | "em_atendimento" | "resolvido";

export interface Handoff {
  id: number;
  conversa_id: string;
  motivo: string;
  resumo: string;
  dados: Record<string, unknown> | null;
  status: StatusHandoff;
  criado_em: string;
}

export interface Lead {
  id: number;
  nome: string;
  telefone?: string | null;
  email?: string | null;
  interesse?: string | null;
  origem?: string | null;
  estagio: string;
  score: number;
  criado_em?: string;
  atualizado_em?: string;
}

export interface Metricas {
  conversas: number;
  handoffs_pendentes: number;
  leads_por_estagio: Record<string, number>;
  intencoes_top: { intencao: string; qtd: number }[];
}

export interface SqlResponse {
  sql: string;
  linhas: Record<string, unknown>[] | unknown[][];
  colunas: string[];
  /** Opcional: o back real explica a consulta em linguagem natural. */
  explicacao?: string;
}

export interface Health {
  ok: boolean;
  modo_llm: string;
}

// ---------- Erros ----------
export class ApiError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.status = status;
  }
}

function mensagemAmigavel(status: number, detalhe?: string): string {
  if (status === 404) return "Recurso não encontrado no servidor.";
  if (status === 422) return "Os dados enviados não foram aceitos pelo servidor.";
  if (status === 429) return "Muitas requisições em sequência. Aguarde alguns segundos.";
  if (status >= 500) return "O servidor encontrou um erro interno. Tente novamente em instantes.";
  return detalhe || `Erro inesperado (HTTP ${status}).`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
  } catch {
    throw new ApiError(
      `Não foi possível conectar ao servidor (${API_URL}). Verifique se o backend está rodando ou use VITE_USE_MOCK=true.`,
    );
  }
  if (!res.ok) {
    let detalhe: string | undefined;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detalhe = body.detail;
    } catch {
      /* corpo não-JSON */
    }
    throw new ApiError(mensagemAmigavel(res.status, detalhe), res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export function errMsg(e: unknown): string {
  if (e instanceof Error) return e.message;
  return "Ocorreu um erro inesperado.";
}

// ---------- API ----------
const realApi = {
  health: () => request<Health>("/api/health"),
  criarConversa: () => post<{ conversa_id: string }>("/api/conversas"),
  enviarMensagem: (conversa_id: string, mensagem: string) =>
    post<ChatResponse>("/api/chat", { conversa_id, mensagem }),
  mensagens: (conversa_id: string) =>
    request<Mensagem[]>(`/api/conversas/${encodeURIComponent(conversa_id)}/mensagens`),
  handoffs: (status?: StatusHandoff) =>
    request<Handoff[]>(`/api/handoffs${status ? `?status=${status}` : ""}`),
  assumirHandoff: (id: number) => post<unknown>(`/api/handoffs/${id}/assumir`),
  resolverHandoff: (id: number) => post<unknown>(`/api/handoffs/${id}/resolver`),
  mensagemAtendente: (conversa_id: string, mensagem: string) =>
    post<unknown>("/api/atendente/mensagem", { conversa_id, mensagem }),
  leads: () => request<Lead[]>("/api/leads"),
  metricas: () => request<Metricas>("/api/metricas"),
  perguntarSql: (pergunta: string) => post<SqlResponse>("/api/sql", { pergunta }),
  vendasRevgas: () => request<VendaRevgas[]>("/api/vendas-revgas"),
  revgasStatus: () => request<RevgasStatus>("/api/revgas/status"),
};

export type Api = typeof realApi;

export const api: Api = USE_MOCK ? mockApi : realApi;
