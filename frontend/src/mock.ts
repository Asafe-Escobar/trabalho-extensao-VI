// Modo mock do FRONTEND: simula a API do CONTRACT.md no navegador, sem backend.
// Ativado com VITE_USE_MOCK=true (npm run dev:mock). As heurísticas imitam o pipeline
// do backend (guardrails → memória → NLU → RAG/ferramentas → venda/handoff) para a
// Flow Gás (revenda de GLP e água, ERP RevGás — ATUALIZAÇÃO 22/11 do contrato).
// NENHUMA chamada de rede: a venda é sempre "DRYRUN" (número local RV-DRY-0001).
// O estado fica no localStorage, então o painel do atendente/gestor (outra aba)
// enxerga handoffs e vendas criados no chat.
import type {
  ChatResponse,
  ChunkDebug,
  DebugInfo,
  EnderecoVenda,
  FerramentaDebug,
  GuardrailDebug,
  Handoff,
  Health,
  ItemVenda,
  Lead,
  Mensagem,
  Metricas,
  RetrievalTrace,
  RevgasPayload,
  RevgasStatus,
  SqlResponse,
  StatusConversa,
  StatusHandoff,
  TipoPagamento,
  VendaDebug,
  VendaRevgas,
} from "./api";

// ---------- Catálogo (ids reais do snapshot RevGás; preços de referência) ----------
interface ProdutoMock {
  id: number; // revgas_id
  nome: string; // descrição na RevGás
  apelido: string; // como o cliente chama
  categoria: string;
  preco: number;
  container_id: number | null;
  estoque: Record<string, number>;
  re: RegExp; // reconhecimento no texto normalizado (sem acentos)
}

const FILIAIS = ["Teresina", "Parnaíba", "São Luís"];

// Ordem importa: do mais específico para o mais genérico.
const PRODUTOS: ProdutoMock[] = [
  { id: 26276, nome: "KIT REGULADOR DE PRESSÃO", apelido: "Kit regulador + mangueira", categoria: "Acessórios", preco: 100, container_id: null, estoque: { Teresina: 60, "Parnaíba": 20, "São Luís": 17 }, re: /kit (de )?regulador/ },
  { id: 26318, nome: "REGULADOR DE PRESSÃO 123", apelido: "Regulador de pressão", categoria: "Acessórios", preco: 45, container_id: null, estoque: { Teresina: 55, "Parnaíba": 25, "São Luís": 20 }, re: /regulador|valvula/ },
  { id: 28534, nome: "MANGUEIRA C/ PIG TAIL", apelido: "Mangueira para gás", categoria: "Acessórios", preco: 35, container_id: null, estoque: { Teresina: 500, "Parnaíba": 200, "São Luís": 294 }, re: /mangueira/ },
  { id: 23974, nome: "GLP 45KG", apelido: "Cilindro P45", categoria: "Gás GLP", preco: 449.9, container_id: 23975, estoque: { Teresina: 92, "Parnaíba": 18, "São Luís": 40 }, re: /\bp-?45\b|45 ?kg|\bde 45\b|cilindro/ },
  { id: 28117, nome: "GLP 20KG", apelido: "Botijão P20", categoria: "Gás GLP", preco: 300, container_id: 28118, estoque: { Teresina: 3, "Parnaíba": 0, "São Luís": 0 }, re: /\bp-?20\b|20 ?kg|botij\w* de 20\b/ },
  { id: 26937, nome: "AGUA VIENA 500ML FD C/ 12", apelido: "Fardo água 500ml (12 un.)", categoria: "Água", preco: 18, container_id: null, estoque: { Teresina: 300, "Parnaíba": 95, "São Luís": 100 }, re: /500 ?ml|fardo/ },
  { id: 24615, nome: "AGUA REGINA 20L", apelido: "Galão de água 20L", categoria: "Água", preco: 14, container_id: 24616, estoque: { Teresina: 120, "Parnaíba": 30, "São Luís": 36 }, re: /gal(a|o)o|garrafao|agua (mineral )?(de )?20|agua\b/ },
  { id: 26717, nome: "GLP 13KG", apelido: "Botijão P13 (gás de cozinha)", categoria: "Gás GLP", preco: 125, container_id: 26718, estoque: { Teresina: 620, "Parnaíba": 180, "São Luís": 139 }, re: /\bp-?13\b|13 ?kg|\bde 13\b|botij|bujao|gas de cozinha|\bgas\b/ },
];

const VASILHAMES: Record<number, { nome: string; preco: number }> = {
  26718: { nome: "VASILHAME 13KG", preco: 170 },
  28118: { nome: "VASILHAME 20KG", preco: 190 },
  23975: { nome: "VASILHAME 45KG MA", preco: 480 },
  24616: { nome: "VASILHAME AGUA 20L", preco: 28 },
};

interface ClienteMock {
  nome: string;
  tipo: "PF" | "PJ";
  pedidos: { numero: string; status: string; valor: number; previsao: string; itens: string; entregador: string | null }[];
  boletos: { valor: number; vencimento: string; status: string; linha: string }[];
}

const CLIENTES: Record<string, ClienteMock> = {
  "12345678909": {
    nome: "Maria Souza",
    tipo: "PF",
    pedidos: [
      { numero: "FL-2026-00042", status: "enviado", valor: 139, previsao: "hoje, até 40 min", itens: "1× Botijão P13, 1× Galão de água 20L", entregador: "Francisco (moto 07)" },
      { numero: "FL-2026-00017", status: "entregue", valor: 125, previsao: "entregue em 02/11/2026", itens: "1× Botijão P13", entregador: null },
    ],
    boletos: [{ valor: 139, vencimento: "2026-11-30", status: "aberto", linha: "34191.79001 01043.510047 91020.150008 1 10240000013900" }],
  },
  "11222333000181": {
    nome: "Escritório Alfa Ltda",
    tipo: "PJ",
    pedidos: [{ numero: "FL-2026-00043", status: "separacao", valor: 899.8, previsao: "amanhã, 8h–12h", itens: "2× Cilindro P45", entregador: null }],
    boletos: [{ valor: 899.8, vencimento: "2026-11-15", status: "vencido", linha: "23793.38128 60082.837309 54000.063305 7 10170000089980" }],
  },
};

const STATUS_PEDIDO: Record<string, string> = {
  aguardando_pagamento: "aguardando pagamento",
  pago: "pago",
  separacao: "em separação",
  enviado: "saiu para entrega 🛵",
  entregue: "entregue",
  cancelado: "cancelado",
};

const PAGAMENTOS: Record<string, string> = {
  MONEY: "Dinheiro",
  PIX: "Pix",
  CARTAO_DE_DEBITO: "Cartão de débito",
  CARTAO_DE_CREDITO: "Cartão de crédito",
};

// ---------- Base de conhecimento (gás) ----------
interface KbChunk {
  titulo: string;
  texto: string;
  termos: string[];
}

const KB: KbChunk[] = [
  { titulo: "Segurança com GLP — vazamento", texto: "Sentiu cheiro de gás: não acenda luzes nem use interruptores, não acenda fósforo ou isqueiro, abra portas e janelas, feche o registro do botijão, saia do local e ligue para o Corpo de Bombeiros (193).", termos: ["cheiro", "vazamento", "vazando", "seguranca", "gas"] },
  { titulo: "Troca × compra de vasilhame", texto: "Na troca, você entrega o botijão vazio e paga só o gás. Se não tiver botijão vazio (primeira compra), é preciso comprar também o vasilhame.", termos: ["troca", "vasilhame", "vazio", "casco", "primeira", "botijao"] },
  { titulo: "Áreas e prazos de entrega", texto: "Entregamos em 30 a 60 minutos na zona urbana de Teresina, Parnaíba e São Luís, das 7h às 20h (domingo até 12h). Entrega grátis.", termos: ["entrega", "prazo", "demora", "horario", "chega", "frete"] },
  { titulo: "Formas de pagamento", texto: "Aceitamos dinheiro (com troco), Pix, cartão de débito e de crédito na entrega. Empresas com contrato podem faturar por boleto.", termos: ["pix", "pagamento", "cartao", "dinheiro", "troco", "boleto"] },
  { titulo: "Validade do regulador e da mangueira", texto: "O regulador de pressão deve ser trocado a cada 5 anos (a data vem gravada na peça). A mangueira tem validade impressa e deve ser trocada se estiver ressecada ou rachada.", termos: ["regulador", "mangueira", "validade", "trocar", "valvula"] },
  { titulo: "Água mineral 20L e higienização do galão", texto: "Os galões de 20L são higienizados e lacrados. A validade do galão retornável é de 3 anos; recusamos galões vencidos, sujos ou amassados.", termos: ["agua", "galao", "20l", "higienizacao", "lacre"] },
  { titulo: "Atendimento B2B — P45 e contrato mensal", texto: "Restaurantes, condomínios e empresas podem ter contrato mensal de P45 com entrega programada, central de gás e faturamento em 28 dias. Um consultor monta a proposta.", termos: ["restaurante", "condominio", "empresa", "contrato", "p45", "mensal", "central"] },
  { titulo: "Política comercial de descontos", texto: "O assistente virtual não concede descontos. Atendentes podem conceder até 5%; acima disso só com aprovação do gerente.", termos: ["desconto", "abatimento", "mais barato"] },
  { titulo: "Programa de fidelidade", texto: "A cada 9 botijões P13 comprados, o 10º sai com R$ 20 de desconto automático.", termos: ["fidelidade", "pontos", "10", "decimo"] },
  { titulo: "LGPD e privacidade", texto: "A Flow só informa dados de pedidos ao próprio titular, após confirmar CPF/CNPJ. Dados de terceiros nunca são compartilhados.", termos: ["dados", "cpf", "privacidade", "lgpd", "terceiro"] },
  { titulo: "Manual — como trocar o botijão", texto: "Feche o registro, desrosqueie o regulador do botijão vazio, encaixe no novo, aperte com a mão e teste com espuma de sabão: se fizer bolhas, há vazamento.", termos: ["instalar", "trocar", "como", "encaixar", "regulador", "manual"] },
  { titulo: "Devolução e produto com defeito", texto: "Botijão com defeito de válvula ou vazamento na entrega é trocado na hora sem custo. Acessórios podem ser devolvidos em até 7 dias.", termos: ["defeito", "devolver", "devolucao", "quebrado", "problema"] },
];

const SINONIMOS: Record<string, string[]> = {
  botijao: ["gás de cozinha", "P13", "bujão"],
  gas: ["GLP", "botijão"],
  pix: ["pagamento instantâneo", "transferência"],
  cheiro: ["vazamento", "escape de GLP"],
  vazamento: ["cheiro de gás", "escape"],
  galao: ["água 20L", "garrafão"],
  agua: ["água mineral", "galão 20L"],
  regulador: ["válvula", "registro"],
  entrega: ["frete", "prazo"],
  troca: ["vasilhame", "casco vazio"],
  desconto: ["abatimento", "condição comercial"],
};

// ---------- Estado persistido ----------
interface ItemCarrinho {
  revgas_id: number;
  nome: string;
  qtd: number;
  preco: number;
}

interface Mem {
  cliente_id?: string | null;
  cpf_cnpj?: string | null;
  pedido_numero?: string | null;
  produto_id?: number | null;
  filial?: string | null;
  intencao_anterior?: string | null;
  carrinho?: ItemCarrinho[];
  tem_botijao_para_troca?: boolean | null;
  endereco?: EnderecoVenda | null;
  pagamento?: TipoPagamento | null;
  troco_para?: number | null;
  aguardando?: string | null;
  ultima_venda?: string | null;
}

interface ConversaMock {
  id: string;
  status: StatusConversa;
  mensagens: Mensagem[];
  memoria: Mem;
}

interface Estado {
  versao: number;
  conversas: Record<string, ConversaMock>;
  handoffs: Handoff[];
  leads: Lead[];
  intencoes: Record<string, number>;
  vendas: VendaRevgas[];
}

const CHAVE = "flow-gas-mock-estado-v2";

function leadsIniciais(): Lead[] {
  const base: [string, string, string, string, number][] = [
    ["Restaurante Sabor do Piauí", "Contrato mensal de 8 P45", "chatbot", "proposta", 91],
    ["Condomínio Jardins", "Central de gás P45 para 40 aptos", "site", "qualificado", 84],
    ["Padaria Pão Quente", "4 P45 por semana", "whatsapp", "ganho", 78],
    ["Carlos Lima", "Botijão P13 + regulador", "chatbot", "novo", 32],
    ["Hotel Atlântico", "Água 20L para recepção", "whatsapp", "qualificado", 66],
    ["Ana Ribeiro", "Galão de água semanal", "instagram", "novo", 28],
    ["Lanchonete do Zé", "2 P13 por semana", "chatbot", "proposta", 70],
    ["Clínica Vida", "Fardos de água 500ml", "site", "ganho", 63],
    ["Lúcia Mendes", "Botijão P13", "chatbot", "perdido", 22],
    ["Escola Saber", "Contrato P45 cozinha", "indicação", "proposta", 88],
    ["Rafael Costa", "Mangueira e regulador", "chatbot", "novo", 18],
    ["Academia Fit", "Água 20L mensal", "whatsapp", "qualificado", 57],
    ["Marcos Viana", "P20 empilhadeira", "site", "perdido", 30],
    ["Pizzaria Forno a Lenha", "P45 quinzenal", "chatbot", "qualificado", 74],
    ["Paula Andrade", "Botijão P13", "site", "novo", 25],
  ];
  return base.map(([nome, interesse, origem, estagio, score], i) => ({
    id: i + 1,
    nome,
    interesse,
    origem,
    estagio,
    score,
    telefone: `(86) 99${String(4100 + i * 37)}-${String(2000 + i * 113).slice(0, 4)}`,
    email: null,
    criado_em: new Date(Date.now() - (i + 1) * 86400000 * 1.5).toISOString(),
  }));
}

function vendasIniciais(): VendaRevgas[] {
  const h = (min: number) => new Date(Date.now() - min * 60000).toISOString();
  return [
    { numero_local: "RV-DRY-0001", revgas_id: null, status: "DRYRUN", total: 250, itens: [{ nome: "GLP 13KG", qtd: 2, preco: 125 }], criado_em: h(190) },
    { numero_local: "RV-DRY-0002", revgas_id: null, status: "DRYRUN", total: 153, itens: [{ nome: "GLP 13KG", qtd: 1, preco: 125 }, { nome: "AGUA REGINA 20L", qtd: 2, preco: 14 }], criado_em: h(95) },
    { numero_local: "RV-DRY-0003", revgas_id: null, status: "DRYRUN", total: 929.9, itens: [{ nome: "GLP 45KG", qtd: 1, preco: 449.9 }, { nome: "VASILHAME 45KG MA", qtd: 1, preco: 480 }], criado_em: h(40) },
  ];
}

function estadoInicial(): Estado {
  return {
    versao: 2,
    conversas: {},
    handoffs: [
      {
        id: 1,
        conversa_id: "demo-conversa-01",
        motivo: "cliente_pediu_atendente",
        resumo: "Restaurante (Escritório Alfa Ltda) quer negociar o boleto vencido dos 2 cilindros P45 do pedido FL-2026-00043 e pediu para falar com uma pessoa.",
        dados: { cliente: "Escritório Alfa Ltda", cpf_cnpj: "11.222.***/****-81", pedido_numero: "FL-2026-00043", intencao: "segunda_via_boleto" },
        status: "pendente",
        criado_em: new Date(Date.now() - 18 * 60000).toISOString(),
      },
    ],
    leads: leadsIniciais(),
    intencoes: { fazer_pedido: 58, consultar_preco: 41, consultar_estoque: 22, consultar_pedido: 19, duvida_politica: 14, falar_atendente: 9, pedir_desconto: 7, seguranca_vazamento: 2 },
    vendas: vendasIniciais(),
  };
}

let memoriaRam: Estado | null = null;

// Relê do localStorage a cada chamada para enxergar o que outra aba gravou.
function estado(): Estado {
  try {
    const raw = globalThis.localStorage?.getItem(CHAVE);
    if (raw) {
      const e = JSON.parse(raw) as Estado;
      if (e?.versao === 2) memoriaRam = e;
    }
  } catch {
    /* sem localStorage (modo privado / node) */
  }
  if (!memoriaRam) memoriaRam = estadoInicial();
  return memoriaRam;
}

function salvar(e: Estado) {
  memoriaRam = e;
  try {
    globalThis.localStorage?.setItem(CHAVE, JSON.stringify(e));
  } catch {
    /* ignora */
  }
}

// ---------- Utilidades ----------
const esperar = (ms: number) => new Promise((r) => setTimeout(r, ms));
const agora = () => new Date().toISOString();
const brl = (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const dataBr = (iso: string) => iso.split("-").reverse().join("/");
const arred = (v: number) => Math.round(v * 100) / 100;

function uuid(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c?.randomUUID) return c.randomUUID();
  return "mock-" + Math.random().toString(16).slice(2) + Date.now().toString(16);
}

export function normalizar(s: string): string {
  return s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
}

export function mascararDoc(doc: string): string {
  const d = doc.replace(/\D/g, "");
  if (d.length === 11) return `***.${d.slice(3, 6)}.${d.slice(6, 9)}-**`;
  if (d.length === 14) return `${d.slice(0, 2)}.${d.slice(2, 5)}.***/****-${d.slice(12)}`;
  return "***";
}

const NUMEROS: Record<string, number> = { um: 1, uma: 1, dois: 2, duas: 2, tres: 3, quatro: 4, cinco: 5, seis: 6, sete: 7, oito: 8, nove: 9, dez: 10 };

/** Extrai itens do texto: "2 botijões de 13 e um galão de água" → [{P13×2},{galão×1}]. */
export function extrairItens(texto: string): { produto: ProdutoMock; qtd: number }[] {
  const t = normalizar(texto);
  const out: { produto: ProdutoMock; qtd: number }[] = [];
  for (const seg of t.split(/,|;|\+|\s+e\s+|\s+mais\s+/)) {
    // "tenho o botijão vazio pra troca" fala do casco, não é um item novo
    if (/vazio|casco|(pra|para) troca|nao tenho|sem botij/.test(seg) && !/\b(quero|pedir|manda|traz|comprar)\b/.test(seg)) continue;
    const prod = PRODUTOS.find((p) => p.re.test(seg));
    if (!prod) continue;
    const m = seg.match(/\b(\d{1,3}|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez)\s+(x\s+)?(botij|bujao|gal|garraf|p-?\d|cilindro|kit|regulador|mangueira|fardo|agua|unidade|gas)/);
    const qtd = m ? (NUMEROS[m[1]] ?? Number(m[1])) : 1;
    const ja = out.find((x) => x.produto.id === prod.id);
    if (ja) ja.qtd += qtd;
    else out.push({ produto: prod, qtd: Math.max(1, Math.min(qtd, 50)) });
  }
  return out;
}

/** "Rua Augusto Freire, 2003, Centro, Teresina" → {rua, numero, bairro, cidade}. */
export function extrairEndereco(texto: string, livre: boolean): EnderecoVenda | null {
  const m = texto.match(/((?:rua|r\.|av\.?|avenida|travessa|tv\.?|quadra|qd\.?|conjunto|residencial)\s+[^,\d]+?)\s*,?\s*(?:n[º°o]?\.?\s*)?(\d+[a-zA-Z]?)\b\s*(?:[,\-–]\s*(?:bairro\s+)?([^,.!]+))?\s*(?:[,\-–]\s*([^,.!]+))?/i);
  let rua: string | undefined, numero: string | undefined, bairro: string | undefined, cidade: string | undefined;
  if (m) {
    [rua, numero, bairro, cidade] = [m[1], m[2], m[3], m[4]].map((x) => x?.trim() || undefined);
  } else if (livre && /\d/.test(texto)) {
    const partes = texto.split(/,|-/).map((x) => x.trim()).filter(Boolean);
    const iNum = partes.findIndex((p) => /^\d+[a-zA-Z]?$/.test(p) || /\b\d+[a-zA-Z]?$/.test(p));
    if (iNum < 0) return null;
    if (/^\d+[a-zA-Z]?$/.test(partes[iNum])) {
      rua = partes[iNum - 1];
      numero = partes[iNum];
    } else {
      const mm = partes[iNum].match(/^(.*?)\s*(\d+[a-zA-Z]?)$/)!;
      rua = mm[1];
      numero = mm[2];
    }
    bairro = partes[iNum + 1];
    cidade = partes[iNum + 2];
  } else return null;
  if (!rua || !numero) return null;
  const cid = cidade ? FILIAIS.find((f) => normalizar(cidade!).includes(normalizar(f))) ?? cidade : undefined;
  return { rua, numero, bairro, cidade: cid };
}

function extrairPagamento(t: string): TipoPagamento | null {
  if (/\bpix\b/.test(t)) return "PIX";
  if (/dinheiro|especie|cash/.test(t)) return "MONEY";
  if (/debito/.test(t)) return "CARTAO_DE_DEBITO";
  if (/credito|cartao/.test(t)) return "CARTAO_DE_CREDITO";
  return null;
}

const enderecoTexto = (e: EnderecoVenda | null | undefined) =>
  e ? [`${e.rua ?? ""}, ${e.numero ?? "s/n"}`, e.bairro, e.cidade].filter(Boolean).join(" – ") : "—";

// ---------- NLU (regex) ----------
interface Nlu {
  intencao: string;
  confianca: number;
  entidades: Record<string, string>;
}

const RE_VAZAMENTO = /cheiro de gas|cheirando (a )?gas|vazamento|vazando|escapando gas|gas escapando/;
const RE_VERBO_PEDIDO = /\b(quero|queria|pedir|pede|peco|manda|mande|traz|traga|comprar|compra|me ve|preciso de|encomendar|vou querer|gostaria de)\b/;
const RE_LEAD = /\b(contrato|mensal|orcamento|cotacao|condominio|restaurante|minha empresa|programad)/;

const REGRAS_INTENCAO: [string, RegExp, number][] = [
  ["falar_atendente", /\b(atendente|humano|pessoa de verdade|falar com alguem|reclama)/, 0.95],
  ["pedir_desconto", /\b(desconto|abatimento|mais barato|faz por|baixa o preco)/, 0.93],
  ["segunda_via_boleto", /\b(boleto|2a via|2ª via|segunda via|linha digitavel)/, 0.94],
  ["consultar_pedido", /\b(meu pedido|o pedido|rastrei|cade|quando chega|ja saiu|fl-\d{4}-\d{5})/, 0.92],
  ["troca_devolucao", /\b(devolv|devoluc|arrepend|defeito|quebrad)/, 0.86],
  ["consultar_preco", /\b(preco|quanto (ta|esta|custa|e|sai|fica)|valor d|custa)/, 0.91],
  ["consultar_estoque", /\b(estoque|disponivel|tem .*(p-?\d+|botij|gal|agua|cilindro|regulador|mangueira)|pronta entrega)/, 0.9],
  ["duvida_politica", /\b(entrega|prazo|demora|pagamento|pix|cartao|lgpd|fidelidade|politica|aceita|validade|horario)/, 0.87],
  ["relatorio_interno", /\b(relatorio|faturamento|vendas do mes)/, 0.8],
  ["saudacao", /^(oi|ola|bom dia|boa tarde|boa noite|e ai|opa)\b/, 0.97],
];

function nlu(texto: string, mem: Mem): Nlu {
  const t = normalizar(texto);
  let intencao = "outro";
  let confianca = 0.42;
  const itens = extrairItens(texto);
  if (RE_VAZAMENTO.test(t)) {
    intencao = "seguranca_vazamento";
    confianca = 0.99;
  } else if (RE_LEAD.test(t) && /(p45|gas|agua|botij|cilindro|central)/.test(t)) {
    intencao = "recomendacao_produto";
    confianca = 0.85;
  } else if ((RE_VERBO_PEDIDO.test(t) && itens.length > 0) || /^pedir (botij|gas|agua|galao)/.test(t)) {
    intencao = "fazer_pedido";
    confianca = 0.94;
  } else {
    for (const [nome, re, conf] of REGRAS_INTENCAO) {
      if (re.test(t)) {
        intencao = nome;
        confianca = conf;
        break;
      }
    }
  }
  if (/^e\s/.test(t) && mem.intencao_anterior && intencao === "outro") {
    intencao = mem.intencao_anterior;
    confianca = 0.81;
  }
  const entidades: Record<string, string> = {};
  const doc = texto.match(/\b\d{2}\.?\d{3}\.?\d{3}\/?\d{4}-?\d{2}\b|\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b/);
  if (doc) entidades.cpf_cnpj = doc[0].replace(/\D/g, "");
  const ped = texto.match(/FL-\d{4}-\d{5}/i);
  if (ped) entidades.numero_pedido = ped[0].toUpperCase();
  if (itens.length) {
    entidades.produto = itens.map((i) => i.produto.apelido).join(", ");
    entidades.quantidade = itens.map((i) => i.qtd).join(", ");
  }
  const fil = FILIAIS.find((f) => t.includes(normalizar(f)));
  if (fil) entidades.filial = fil;
  const pg = extrairPagamento(t);
  if (pg) entidades.pagamento = pg;
  return { intencao, confianca, entidades };
}

// ---------- RAG simulado ----------
function recuperar(texto: string, mem: Mem, k = 3): { chunks: ChunkDebug[]; trace: RetrievalTrace } {
  const t = normalizar(texto);
  const tecnicas = ["rewrite", "multi_query", "expansion", "hybrid", "rerank", "hype"];

  let reescrita: string | null = null;
  if (/^(e |esse|essa|ele|ela|dele|dela|isso)\b/.test(t)) {
    const prod = mem.produto_id ? PRODUTOS.find((p) => p.id === mem.produto_id)?.apelido : null;
    const ctx = [prod, mem.pedido_numero && `pedido ${mem.pedido_numero}`].filter(Boolean).join(", ");
    if (ctx) reescrita = `${texto.replace(/^e\s+/i, "").replace(/\?$/, "")} — referente a ${ctx}?`;
  }
  const base = reescrita ?? texto;
  const multi = [base, `Qual a regra da Flow Gás sobre: ${base.replace(/\?$/, "")}?`, `Dúvida frequente de cliente de gás/água: ${base.replace(/\?$/, "")}`];
  const expansao: string[] = [];
  for (const [termo, sins] of Object.entries(SINONIMOS)) if (t.includes(termo)) expansao.push(...sins);

  let hyde: string | null = null;
  if (/(como|o que faco|posso|defeito|problema|vazando|cheiro)/.test(t)) {
    tecnicas.push("hyde");
    hyde = `Resposta hipotética: segundo as normas de segurança e a política da Flow Gás, quando ${base.replace(/\?$/, "").toLowerCase()}, o cliente deve seguir as orientações do manual e, se necessário, acionar o atendimento.`;
  }
  const usaGrafo = /(combina|compativ|regulador|mangueira|acessorio|p45|central)/.test(t);
  if (usaGrafo) tecnicas.push("graph");

  const termos = new Set([...t.split(/\W+/), ...expansao.map(normalizar)].filter((w) => w.length > 2));
  const pont = KB.map((c) => {
    let s = 0;
    for (const termo of c.termos) for (const q of termos) if (q.includes(termo) || termo.includes(q)) s += 1;
    return { c, s };
  })
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s);
  const fontes = usaGrafo ? ["grafo", "bm25", "vetorial"] : ["bm25", "vetorial", "hype"];
  const top = (pont.length ? pont : KB.slice(2, 4).map((c) => ({ c, s: 0.3 }))).slice(0, k);
  const max = Math.max(...top.map((x) => x.s), 1);
  return {
    chunks: top.map((x, i) => ({
      titulo: x.c.titulo,
      score: arred(0.55 + 0.4 * (x.s / max) - i * 0.04),
      fonte: fontes[i % fontes.length],
      trecho: x.c.texto,
    })),
    trace: { original: texto, reescrita, multi_queries: multi, expansao, hyde_doc: hyde, candidatos: 12 + pont.length * 3, tecnicas },
  };
}

// ---------- Orquestração ----------
interface Saida {
  resposta: string;
  sugestoes: string[];
  ferramentas: FerramentaDebug[];
  guardrails: GuardrailDebug[];
  tecnicas: string[];
  retrieval: RetrievalTrace | null;
  chunks: ChunkDebug[];
  handoff: { id: number; resumo: string } | null;
  sql: string | null;
  venda: VendaDebug | null;
}

const novaSaida = (): Saida => ({ resposta: "", sugestoes: [], ferramentas: [], guardrails: [], tecnicas: [], retrieval: null, chunks: [], handoff: null, sql: null, venda: null });

function pedirDocumento(s: Saida, motivo: string) {
  s.resposta = `Para ${motivo}, preciso confirmar sua identidade. Pode me informar o **CPF** ou **CNPJ** do titular?\n\n_Seus dados são usados só para localizar seus registros (LGPD)._`;
  s.sugestoes = ["Meu CPF é 123.456.789-09", "CNPJ 11.222.333/0001-81"];
  s.guardrails.push({ regra: "verificacao_titular", acao: "solicitado_cpf_cnpj" });
}

function criarHandoff(e: Estado, conv: ConversaMock, motivo: string, intencao: string, resumoExtra?: string): { id: number; resumo: string } {
  const mem = conv.memoria;
  const cliente = mem.cpf_cnpj ? CLIENTES[mem.cpf_cnpj]?.nome : null;
  const ultima = conv.mensagens.filter((m) => m.papel === "user").slice(-1)[0]?.conteudo ?? "";
  const resumo =
    resumoExtra ??
    [
      cliente ? `Cliente ${cliente}` : "Cliente não identificado",
      mem.pedido_numero ? ` tratando do pedido ${mem.pedido_numero}` : "",
      mem.carrinho?.length ? ` com carrinho aberto (${mem.carrinho.map((i) => `${i.qtd}× ${i.nome}`).join(", ")})` : "",
      ` — pediu atendimento humano (${motivo.replace(/_/g, " ")}). Última mensagem: "${ultima}".`,
    ].join("");
  const id = Math.max(0, ...e.handoffs.map((h) => h.id)) + 1;
  e.handoffs.unshift({
    id,
    conversa_id: conv.id,
    motivo,
    resumo,
    dados: {
      cliente: cliente ?? null,
      cpf_cnpj: mem.cpf_cnpj ? mascararDoc(mem.cpf_cnpj) : null,
      pedido_numero: mem.pedido_numero ?? null,
      carrinho: mem.carrinho?.length ? mem.carrinho : null,
      endereco: mem.endereco ?? null,
      intencao,
      prioridade: motivo.startsWith("emergencia") ? "URGENTE" : "normal",
    },
    status: "pendente",
    criado_em: agora(),
  });
  conv.status = "humano";
  return { id, resumo };
}

/** Itens finais da venda: carrinho + vasilhames quando o cliente não tem casco para troca. */
function itensDaVenda(mem: Mem): ItemCarrinho[] {
  const itens = [...(mem.carrinho ?? [])];
  if (mem.tem_botijao_para_troca === false) {
    for (const it of mem.carrinho ?? []) {
      const p = PRODUTOS.find((x) => x.id === it.revgas_id);
      if (p?.container_id && VASILHAMES[p.container_id]) {
        itens.push({ revgas_id: p.container_id, nome: VASILHAMES[p.container_id].nome, qtd: it.qtd, preco: VASILHAMES[p.container_id].preco });
      }
    }
  }
  return itens;
}

const totalDe = (itens: ItemCarrinho[]) => arred(itens.reduce((a, i) => a + i.qtd * i.preco, 0));

function montarPayload(mem: Mem, itens: ItemCarrinho[]): RevgasPayload {
  const total = totalDe(itens);
  const end = mem.endereco ?? {};
  const cidade = end.cidade ?? mem.filial ?? "Teresina";
  const obs = ["Pedido via Flow Assistente (chatbot).", mem.tem_botijao_para_troca === false ? "Cliente sem vasilhame: incluir casco." : "Cliente tem vasilhame para troca.", mem.pagamento === "MONEY" && mem.troco_para ? `Troco para ${mem.troco_para}.` : ""]
    .filter(Boolean)
    .join(" ");
  return {
    channel: "WHATSAPP",
    location: end.rua,
    number: end.numero,
    neighborhood: end.bairro,
    city: cidade,
    state_federation: normalizar(cidade).includes("sao luis") ? "MA" : "PI",
    observation: obs,
    products: itens.map((i) => ({ product_id: i.revgas_id, quantity: i.qtd, value: i.preco, discount: 0 })),
    payments: [{ payment_type: mem.pagamento ?? "MONEY", value: total, date: new Date().toISOString().slice(0, 10) }],
  };
}

function limparVenda(mem: Mem) {
  mem.carrinho = [];
  mem.tem_botijao_para_troca = null;
  mem.pagamento = null;
  mem.troco_para = null;
  mem.aguardando = null;
}

const RE_SIM = /^(sim|s\b|isso|confirmo|confirma|confirmado|pode (mandar|confirmar|ser)|ok|okay|fechado|beleza|manda|claro|com certeza)/;
const RE_NAO = /^(nao|n\b|cancela|cancelar|negativo|quero alterar|alterar|mudar)/;

function fluxoVenda(e: Estado, conv: ConversaMock, s: Saida, texto: string) {
  const mem = conv.memoria;
  const t = normalizar(texto).trim();
  s.tecnicas.push("slot_filling");
  mem.carrinho = mem.carrinho ?? [];

  // Confirmação explícita
  if (mem.aguardando === "confirmacao") {
    if (RE_SIM.test(t)) return confirmarVenda(e, conv, s);
    if (RE_NAO.test(t)) {
      limparVenda(mem);
      s.resposta = "Sem problemas, cancelei o rascunho. O que você gostaria de pedir?";
      s.sugestoes = ["Quero 1 botijão P13", "Quero 2 botijões de 13 e um galão de água", "1 cilindro P45"];
      return;
    }
  }

  // 1. Itens (respostas sobre troca/vasilhame não são itens novos, salvo verbo de pedido explícito)
  const falaDeTroca = /(para|pra) troca|vazio|casco|vasilhame/.test(t) && !RE_VERBO_PEDIDO.test(t);
  const aceitaItens = !falaDeTroca && (!mem.aguardando || mem.aguardando === "itens" || RE_VERBO_PEDIDO.test(t));
  const novos = aceitaItens ? extrairItens(texto) : [];
  for (const { produto, qtd } of novos) {
    const ja = mem.carrinho.find((i) => i.revgas_id === produto.id);
    if (ja) ja.qtd += qtd;
    else mem.carrinho.push({ revgas_id: produto.id, nome: produto.nome, qtd, preco: produto.preco });
    mem.produto_id = produto.id;
  }
  if (novos.length) {
    s.ferramentas.push({
      nome: "consultar_preco",
      entrada: { produtos: novos.map((n) => n.produto.id) },
      saida_resumo: novos.map((n) => `${n.produto.nome} (#${n.produto.id}) ${brl(n.produto.preco)}`).join("; "),
    });
    s.tecnicas.push("tool_calling");
  }

  // 2. Troca de vasilhame
  if (/(tenho|tem) (o |um )?(botij\w*|vasilhame|casco|galao)( vazio)?|pra troca|para troca|^sim/.test(t) && !/nao tenho/.test(t)) {
    if (mem.aguardando === "troca" || /troca|vazio|casco/.test(t)) mem.tem_botijao_para_troca = true;
  }
  if (/nao tenho|sem (botij|vasilhame|casco|galao)|primeir[oa] (botij|compra)|preciso do vasilhame|^nao\b/.test(t) && mem.aguardando === "troca") mem.tem_botijao_para_troca = false;
  if (/nao tenho (o |um )?(botij|vasilhame|casco)|sem (botij|vasilhame|casco)/.test(t)) mem.tem_botijao_para_troca = false;

  // 3. Endereço
  const end = extrairEndereco(texto, mem.aguardando === "endereco");
  if (end) mem.endereco = { ...end, cidade: end.cidade ?? mem.filial ?? "Teresina" };

  // 4. Pagamento e troco
  const pg = extrairPagamento(t);
  if (pg) mem.pagamento = pg;
  const troco = t.match(/troco (pra|para|de)?\s*(r\$)?\s*(\d+)/);
  if (troco) mem.troco_para = Number(troco[3]);
  else if (mem.aguardando === "troco") {
    const n = t.match(/(\d+)/);
    if (n) mem.troco_para = Number(n[1]);
    else if (/nao|sem troco|trocado|certinho|exato/.test(t)) mem.troco_para = 0;
  }

  // Próximo slot que falta
  const precisaVasilhame = mem.carrinho.some((i) => PRODUTOS.find((p) => p.id === i.revgas_id)?.container_id);
  if (!mem.carrinho.length) {
    mem.aguardando = "itens";
    s.resposta = "Claro! O que você vai querer? Temos **botijão P13** (gás de cozinha), **P20**, **cilindro P45**, **água mineral 20L** e acessórios.";
    s.sugestoes = ["1 botijão P13", "2 botijões de 13 e um galão de água", "1 cilindro P45"];
    return;
  }
  const carrinhoTxt = mem.carrinho.map((i) => `${i.qtd}× ${PRODUTOS.find((p) => p.id === i.revgas_id)?.apelido ?? i.nome}`).join(", ");
  if (precisaVasilhame && mem.tem_botijao_para_troca == null) {
    mem.aguardando = "troca";
    s.resposta = `Anotado: **${carrinhoTxt}**. 📝\n\nVocê tem o **botijão/galão vazio para troca**? Se não tiver, incluo o vasilhame no pedido.`;
    s.sugestoes = ["Sim, tenho para troca", "Não tenho, preciso do vasilhame"];
    return;
  }
  if (!mem.endereco) {
    mem.aguardando = "endereco";
    s.resposta = "Qual o **endereço de entrega**? (rua, número, bairro e cidade)";
    s.sugestoes = ["Rua Augusto Freire, 2003, Centro, Teresina", "Av. Frei Serafim, 1500, Centro, Teresina"];
    return;
  }
  if (!mem.pagamento) {
    mem.aguardando = "pagamento";
    s.resposta = "Como prefere **pagar na entrega**?";
    s.sugestoes = ["Pix", "Dinheiro", "Cartão de débito", "Cartão de crédito"];
    return;
  }
  if (mem.pagamento === "MONEY" && mem.troco_para == null) {
    mem.aguardando = "troco";
    s.resposta = "Vai precisar de **troco**? Se sim, para quanto?";
    s.sugestoes = ["Troco para R$ 200", "Não preciso de troco"];
    return;
  }

  // Resumo e pedido de confirmação
  const itens = itensDaVenda(mem);
  const total = totalDe(itens);
  mem.aguardando = "confirmacao";
  const linhas = itens.map((i) => `| ${i.nome} | ${i.qtd} | ${brl(i.preco)} | ${brl(i.qtd * i.preco)} |`).join("\n");
  s.resposta =
    `Confere o **resumo do pedido**:\n\n| Item | Qtd | Preço | Subtotal |\n|---|---|---|---|\n${linhas}\n\n` +
    `- **Total: ${brl(total)}**\n- Entrega: ${enderecoTexto(mem.endereco)}\n- Pagamento: ${PAGAMENTOS[mem.pagamento] ?? mem.pagamento}` +
    `${mem.pagamento === "MONEY" && mem.troco_para ? ` (troco para ${brl(mem.troco_para)})` : ""}\n\n**Confirma o pedido?**`;
  s.sugestoes = ["Sim, confirmo", "Não, quero alterar"];
}

function confirmarVenda(e: Estado, conv: ConversaMock, s: Saida) {
  const mem = conv.memoria;
  const itens = itensDaVenda(mem);
  const total = totalDe(itens);
  const payload = montarPayload(mem, itens);
  const seq = e.vendas.filter((v) => v.numero_local.startsWith("RV-DRY-")).length + 1;
  const numero = `RV-DRY-${String(seq).padStart(4, "0")}`;
  const itensVenda: ItemVenda[] = itens.map((i) => ({ nome: i.nome, qtd: i.qtd, preco: i.preco, revgas_id: i.revgas_id }));
  e.vendas.unshift({ numero_local: numero, revgas_id: null, status: "DRYRUN", total, itens: itensVenda, criado_em: agora() });
  s.ferramentas.push({ nome: "criar_venda", entrada: payload as Record<string, unknown>, saida_resumo: `status=DRYRUN numero=${numero} total=${brl(total)} (nenhum POST real enviado)` });
  s.tecnicas.push("tool_calling", "criar_venda");
  s.venda = { numero, status: "DRYRUN", total, itens: itensVenda, endereco: mem.endereco ?? null, pagamento: mem.pagamento ?? null, payload, troco_para: mem.troco_para ?? null, previsao: "30 a 60 min" };
  s.resposta = `✅ Pedido **${numero}** registrado! Previsão de entrega: **30 a 60 minutos** em ${enderecoTexto(mem.endereco)}.\n\nTotal: **${brl(total)}** · ${PAGAMENTOS[mem.pagamento ?? ""] ?? mem.pagamento}. Obrigado por comprar com a Flow Gás! 🔥`;
  s.sugestoes = ["Quanto tempo demora?", "Quero falar com um atendente"];
  mem.ultima_venda = numero;
  limparVenda(mem);
}

function responder(e: Estado, conv: ConversaMock, texto: string): { saida: Saida; n: Nlu } {
  const s = novaSaida();
  const mem = conv.memoria;
  const t = normalizar(texto);

  // 1. Guardrails de entrada
  if (/(ignore|esqueca|desconsidere).{0,30}(instruc|regras|prompt)|system prompt|prompt do sistema|modo desenvolvedor|jailbreak/.test(t)) {
    s.guardrails.push({ regra: "prompt_injection", acao: "bloqueado" });
    s.tecnicas.push("guardrails_entrada");
    s.resposta = "Não posso alterar minhas instruções de funcionamento. 🙂 Posso ajudar com **pedido de gás ou água, preços, estoque e entregas**?";
    s.sugestoes = ["Pedir botijão", "Preço do P13"];
    return { saida: s, n: { intencao: "outro", confianca: 0.99, entidades: {} } };
  }

  const n = nlu(texto, mem);
  s.tecnicas.push("intent_classification", "entity_extraction");

  // Segurança: vazamento de gás tem prioridade absoluta
  if (n.intencao === "seguranca_vazamento") {
    s.guardrails.push({ regra: "seguranca_vazamento_gas", acao: "instrucoes_de_emergencia" });
    s.tecnicas.push("guardrails_entrada", "human_handoff");
    const h = criarHandoff(e, conv, "emergencia_vazamento_gas", n.intencao, `🚨 URGENTE: cliente relatou cheiro/vazamento de gás. Mensagem: "${texto}". Instruções de segurança já enviadas; ligar de volta imediatamente.`);
    s.handoff = h;
    s.guardrails.push({ regra: "handoff_urgente", acao: "acionado" });
    s.ferramentas.push({ nome: "transferir_atendente", entrada: { motivo: "emergencia_vazamento_gas", prioridade: "urgente" }, saida_resumo: `handoff #${h.id} URGENTE criado` });
    s.resposta =
      "🚨 **Atenção — siga agora:**\n\n1. **Não acenda luzes** nem mexa em interruptores ou tomadas.\n2. **Não acenda** fósforo, isqueiro ou fogão.\n3. **Abra portas e janelas** para ventilar.\n4. **Feche o registro** do botijão.\n5. **Saia do local** e mantenha as pessoas afastadas.\n6. Ligue para os **Bombeiros: 193**.\n\nJá acionei um atendente da Flow com **prioridade urgente**; ele vai falar com você em instantes.";
    return { saida: s, n };
  }

  if (/(cpf|cnpj|endereco|telefone) d[oa] (cliente|outr|vizinh|dono)/.test(t)) {
    s.guardrails.push({ regra: "dados_de_terceiros", acao: "bloqueado" });
    s.tecnicas.push("guardrails_entrada");
    s.resposta = "Por segurança e em respeito à **LGPD**, não compartilho dados de outros clientes. Se o pedido for seu, me informe seu CPF/CNPJ.";
    s.sugestoes = ["Meu CPF é 123.456.789-09"];
    return { saida: s, n };
  }

  if (n.entidades.cpf_cnpj) {
    s.guardrails.push({ regra: "pii_mascarada", acao: "mascarado_no_log" });
    s.tecnicas.push("guardrails_entrada");
    mem.cpf_cnpj = n.entidades.cpf_cnpj;
  }
  if (n.entidades.numero_pedido) mem.pedido_numero = n.entidades.numero_pedido;
  if (n.entidades.filial) mem.filial = n.entidades.filial;
  const itensMsg = extrairItens(texto);
  if (itensMsg.length && n.intencao !== "fazer_pedido") mem.produto_id = itensMsg[0].produto.id;
  s.tecnicas.push("conversation_memory");

  const cliente = mem.cpf_cnpj ? CLIENTES[mem.cpf_cnpj] : undefined;
  if (cliente) mem.cliente_id = cliente.tipo === "PF" ? "1" : "2";
  const produto = mem.produto_id ? PRODUTOS.find((p) => p.id === mem.produto_id) : undefined;

  // Venda em andamento: respostas curtas ("sim", "pix", endereço...) continuam o fluxo
  const interrompe = ["consultar_preco", "consultar_estoque", "consultar_pedido", "falar_atendente", "pedir_desconto", "segunda_via_boleto", "troca_devolucao"];
  if (mem.aguardando && !interrompe.includes(n.intencao)) {
    n.intencao = "fazer_pedido";
    n.confianca = Math.max(n.confianca, 0.9);
  }

  const usarRag = (k = 3) => {
    const r = recuperar(texto, mem, k);
    s.retrieval = r.trace;
    s.chunks = r.chunks;
    s.ferramentas.push({ nome: "buscar_conhecimento", entrada: { query: r.trace.reescrita ?? texto, k }, saida_resumo: `${r.chunks.length} trechos: ${r.chunks.map((c) => c.titulo).join("; ")}` });
    s.tecnicas.push("agentic_rag", "rag_hibrido", "reranking", "multi_query", "query_expansion", "hype");
    if (r.trace.reescrita) s.tecnicas.push("query_rewriting");
    if (r.trace.hyde_doc) s.tecnicas.push("hyde");
    if (r.trace.tecnicas.includes("graph")) s.tecnicas.push("graph_rag");
    return r.chunks;
  };

  switch (n.intencao) {
    case "fazer_pedido":
      fluxoVenda(e, conv, s, texto);
      break;

    case "saudacao":
      s.resposta = `Olá${cliente ? `, ${cliente.nome.split(" ")[0]}` : ""}! Sou o **Flow Assistente**, da Flow Gás. 🔥 Posso **fazer seu pedido de gás ou água**, informar preços, estoque nas filiais e acompanhar sua entrega.`;
      s.sugestoes = ["Pedir botijão", "Preço do P13", "Tem P45?"];
      break;

    case "consultar_pedido": {
      if (!cliente) {
        if (mem.cpf_cnpj) {
          s.resposta = "Não encontrei cadastro com esse documento. Pode conferir os números?";
          s.sugestoes = ["Meu CPF é 123.456.789-09"];
        } else pedirDocumento(s, "consultar seu pedido");
        break;
      }
      const numero = mem.pedido_numero;
      const pedido = numero ? cliente.pedidos.find((p) => p.numero === numero) : cliente.pedidos[0];
      s.ferramentas.push({ nome: "consultar_cliente", entrada: { cpf_cnpj: mascararDoc(mem.cpf_cnpj!) }, saida_resumo: `${cliente.nome} (${cliente.tipo}), ${cliente.pedidos.length} pedido(s)` });
      s.tecnicas.push("tool_calling");
      if (numero && !pedido) {
        s.guardrails.push({ regra: "pedido_de_outro_titular", acao: "bloqueado" });
        s.resposta = `Não encontrei o pedido **${numero}** vinculado ao seu documento. Por segurança só mostro pedidos do próprio titular.`;
        mem.pedido_numero = null;
        break;
      }
      if (!pedido) break;
      mem.pedido_numero = pedido.numero;
      s.ferramentas.push({ nome: "consultar_pedido", entrada: { numero: pedido.numero, cpf_cnpj: mascararDoc(mem.cpf_cnpj!) }, saida_resumo: `status=${pedido.status}, previsão=${pedido.previsao}` });
      s.resposta = /^e\s/.test(t)
        ? `O pedido **${pedido.numero}** chega **${pedido.previsao}**.${pedido.entregador ? ` Entregador: ${pedido.entregador}.` : ""}`
        : `Encontrei, ${cliente.nome.split(" ")[0]}! 🛵\n\n**Pedido ${pedido.numero}**\n- Status: **${STATUS_PEDIDO[pedido.status] ?? pedido.status}**\n- Itens: ${pedido.itens}\n- Valor: ${brl(pedido.valor)}\n- Previsão: ${pedido.previsao}${pedido.entregador ? `\n- Entregador: ${pedido.entregador}` : ""}`;
      s.sugestoes = ["E quando chega?", "Pedir botijão", "Quero falar com um atendente"];
      break;
    }

    case "segunda_via_boleto": {
      if (!cliente) {
        pedirDocumento(s, "emitir a 2ª via do boleto");
        break;
      }
      const b = cliente.boletos.find((x) => x.status !== "pago");
      s.ferramentas.push({ nome: "consultar_financeiro", entrada: { cpf_cnpj: mascararDoc(mem.cpf_cnpj!) }, saida_resumo: b ? `1 título ${b.status}, ${brl(b.valor)}` : "nenhum título em aberto" });
      s.tecnicas.push("tool_calling");
      s.resposta = b
        ? `Aqui está a 2ª via (${b.status === "vencido" ? "**vencido** — valor atualizado com multa e juros" : "em aberto"}):\n\n- Valor: **${brl(b.valor)}**\n- Vencimento: ${dataBr(b.vencimento)}\n- Linha digitável:\n\n\`${b.linha}\``
        : "Você não tem boletos em aberto. 🎉";
      s.sugestoes = ["Pedir botijão", "Quero falar com um atendente"];
      break;
    }

    case "pedir_desconto":
      s.guardrails.push({ regra: "desconto_nao_autorizado", acao: "bloqueado" }, { regra: "preco_minimo_confidencial", acao: "omitido" });
      s.tecnicas.push("guardrails_saida");
      usarRag(1);
      s.resposta = "Eu não tenho autorização para conceder descontos. 😉 Mas no nosso **programa de fidelidade** o 10º botijão P13 sai com R$ 20 de desconto. Se quiser negociar volume, te passo para um atendente.";
      s.sugestoes = ["Quero falar com um atendente", "Pedir botijão"];
      break;

    case "falar_atendente": {
      const h = criarHandoff(e, conv, "cliente_pediu_atendente", mem.intencao_anterior ?? n.intencao);
      s.handoff = h;
      s.tecnicas.push("human_handoff");
      s.ferramentas.push({ nome: "transferir_atendente", entrada: { motivo: "cliente_pediu_atendente" }, saida_resumo: `handoff #${h.id} criado (pendente)` });
      s.resposta = "Certo! Transferi sua conversa para um **atendente da Flow Gás** com um resumo do que falamos, então você não precisa repetir nada. ⏳ Aguarde um instante.";
      break;
    }

    case "consultar_preco":
    case "consultar_estoque": {
      if (!produto) {
        s.resposta = "De qual produto? Temos **botijão P13**, **P20**, **cilindro P45**, **água mineral 20L**, regulador e mangueira.";
        s.sugestoes = ["Preço do P13", "Tem P45?", "Quanto tá o galão de água?"];
        break;
      }
      s.tecnicas.push("tool_calling");
      if (n.intencao === "consultar_preco") {
        s.ferramentas.push({ nome: "consultar_preco", entrada: { revgas_id: produto.id }, saida_resumo: `${produto.nome}: ${brl(produto.preco)}` });
        s.guardrails.push({ regra: "preco_minimo_confidencial", acao: "omitido" });
        const vas = produto.container_id ? VASILHAMES[produto.container_id] : null;
        s.resposta = `O **${produto.apelido}** está **${brl(produto.preco)}** na troca${vas ? ` (entregando o vazio). Sem vasilhame, soma ${brl(vas.preco)} do casco: ${brl(produto.preco + vas.preco)}` : ""}.\n\nEntrega grátis em 30–60 min. Quer pedir?`;
        s.sugestoes = [`Quero 1 ${produto.apelido.split(" (")[0].toLowerCase()}`, "Tem P45?", "Como faço pra pagar?"];
      } else {
        const filial = mem.filial;
        s.ferramentas.push({ nome: "consultar_estoque", entrada: { revgas_id: produto.id, filial: filial ?? "todas" }, saida_resumo: Object.entries(produto.estoque).map(([f, q]) => `${f}: ${q}`).join(", ") });
        const linhas = Object.entries(produto.estoque)
          .map(([f, q]) => `| ${f}${f === filial ? " ⭐" : ""} | ${q > 0 ? `${q} un.` : "esgotado"} |`)
          .join("\n");
        const q = filial ? produto.estoque[filial] : null;
        s.resposta = `${filial ? (q && q > 0 ? `Tem sim! **${q} unidades** de ${produto.apelido} em ${filial}.` : `Em ${filial} o ${produto.apelido} está **esgotado** agora.`) : `Estoque de **${produto.apelido}**:`}\n\n| Filial | Disponível |\n|---|---|\n${linhas}`;
        s.sugestoes = [`Quero 1 ${produto.apelido.split(" (")[0].toLowerCase()}`, `Preço do ${produto.apelido.match(/P\d+/)?.[0] ?? produto.apelido.split(" (")[0].toLowerCase()}`];
      }
      break;
    }

    case "relatorio_interno":
      s.guardrails.push({ regra: "relatorio_interno_restrito", acao: "bloqueado_no_chat_cliente" });
      s.resposta = "Relatórios internos ficam só no **Painel do gestor**. Posso ajudar com um pedido de gás ou água?";
      break;

    default: {
      const chunks = usarRag();
      if (RE_LEAD.test(t)) {
        const lead: Lead = { id: Math.max(0, ...e.leads.map((l) => l.id)) + 1, nome: cliente?.nome ?? "Visitante do chat", interesse: texto.slice(0, 80), origem: "chatbot", estagio: "qualificado", score: 86, criado_em: agora(), telefone: null, email: null };
        e.leads.unshift(lead);
        s.ferramentas.push({ nome: "registrar_lead", entrada: { interesse: lead.interesse, origem: "chatbot" }, saida_resumo: `lead #${lead.id} score=${lead.score} (qualificado) → webhook n8n` });
        s.tecnicas.push("lead_scoring", "tool_calling");
        s.resposta = `Ótimo! Registrei seu interesse e um **consultor B2B** vai montar a proposta. 📋\n\n${chunks.find((c) => c.titulo.includes("B2B"))?.trecho ?? ""}`;
        s.sugestoes = ["Preço do P45", "Quero falar com um atendente"];
        break;
      }
      const principal = chunks[0];
      s.resposta = principal ? `${principal.trecho}\n\n_Fonte: ${principal.titulo}_` : "Não encontrei essa informação. Quer que eu chame um atendente?";
      s.sugestoes = ["Pedir botijão", "Quanto tempo demora a entrega?", "Quero falar com um atendente"];
    }
  }

  if (/\d{3}\.?\d{3}\.?\d{3}-?\d{2}/.test(s.resposta)) {
    s.resposta = s.resposta.replace(/\d{3}\.?\d{3}\.?\d{3}-?\d{2}/g, (m) => mascararDoc(m));
    s.guardrails.push({ regra: "mascarar_cpf_cnpj", acao: "mascarado" });
  }
  mem.intencao_anterior = n.intencao;
  return { saida: s, n };
}

// ---------- Text-to-SQL mock ----------
function textoParaSql(pergunta: string): SqlResponse {
  const t = normalizar(pergunta);
  if (/(faturamento|vendas|receita)/.test(t)) {
    if (/filial/.test(t) || !/mes/.test(t)) {
      return {
        sql: "SELECT filial, SUM(qtd_pedidos) AS pedidos, ROUND(SUM(faturamento), 2) AS faturamento\nFROM vw_vendas_resumo\nWHERE mes LIKE '2026-%'\nGROUP BY filial\nORDER BY faturamento DESC\nLIMIT 50",
        colunas: ["filial", "pedidos", "faturamento"],
        linhas: [
          { filial: "Teresina", pedidos: 1284, faturamento: 168420.5 },
          { filial: "São Luís", pedidos: 702, faturamento: 92310.0 },
          { filial: "Parnaíba", pedidos: 415, faturamento: 51870.9 },
        ],
      };
    }
    return {
      sql: "SELECT mes, SUM(faturamento) AS faturamento\nFROM vw_vendas_resumo\nGROUP BY mes\nORDER BY mes\nLIMIT 50",
      colunas: ["mes", "faturamento"],
      linhas: ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"].map((mes, i) => ({ mes, faturamento: arred(41000 + i * 3800 + (i % 2) * 2600) })),
    };
  }
  if (/(estoque|esgotad|disponivel)/.test(t)) {
    const baixo = /(baixo|acabando|esgotad|menos)/.test(t);
    const linhas = PRODUTOS.flatMap((p) => Object.entries(p.estoque).map(([filial, quantidade]) => ({ sku: String(p.id), produto: p.nome, filial, quantidade })))
      .filter((r) => (baixo ? r.quantidade < 20 : true))
      .sort((a, b) => a.quantidade - b.quantidade)
      .slice(0, 20);
    return {
      sql: `SELECT sku, produto, filial, quantidade\nFROM vw_estoque${baixo ? "\nWHERE quantidade < 20" : ""}\nORDER BY quantidade ASC\nLIMIT ${baixo ? 50 : 20}`,
      colunas: ["sku", "produto", "filial", "quantidade"],
      linhas,
    };
  }
  const cat = /gas|botij|glp/.test(t) ? "Gás GLP" : /agua/.test(t) ? "Água" : /acessori|regulador|mangueira/.test(t) ? "Acessórios" : null;
  const linhas = PRODUTOS.filter((p) => !cat || p.categoria === cat)
    .sort((a, b) => b.preco - a.preco)
    .map((p) => ({ sku: String(p.id), nome: p.nome, categoria: p.categoria, marca: "RevGás", preco: p.preco, garantia_meses: p.categoria === "Acessórios" ? 12 : 0 }));
  return {
    sql: `SELECT sku, nome, categoria, marca, preco, garantia_meses\nFROM vw_catalogo${cat ? `\nWHERE categoria = '${cat}'` : ""}\nORDER BY preco DESC\nLIMIT 50`,
    colunas: ["sku", "nome", "categoria", "marca", "preco", "garantia_meses"],
    linhas,
  };
}

// ---------- API mock (mesma assinatura da real) ----------
function conversa(e: Estado, id: string): ConversaMock {
  let c = e.conversas[id];
  if (!c) {
    c = { id, status: "bot", mensagens: [], memoria: {} };
    e.conversas[id] = c;
  }
  return c;
}

function memoriaVisivel(m: Mem): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(m)) {
    if (v == null || (Array.isArray(v) && v.length === 0)) continue;
    out[k] = k === "cpf_cnpj" ? mascararDoc(String(v)) : v;
  }
  return out;
}

export const mockApi = {
  health: async (): Promise<Health> => {
    await esperar(80);
    return { ok: true, modo_llm: "mock" };
  },

  criarConversa: async (): Promise<{ conversa_id: string }> => {
    await esperar(120);
    const e = estado();
    const id = uuid();
    conversa(e, id);
    salvar(e);
    return { conversa_id: id };
  },

  enviarMensagem: async (conversa_id: string, mensagem: string): Promise<ChatResponse> => {
    const inicio = performance.now();
    await esperar(350 + Math.random() * 450);
    const e = estado();
    const conv = conversa(e, conversa_id);
    conv.mensagens.push({ papel: "user", conteudo: mensagem, criado_em: agora() });

    if (conv.status === "humano") {
      salvar(e);
      return {
        resposta: "",
        status_conversa: "humano",
        sugestoes: [],
        debug: { intencao: "em_atendimento_humano", confianca: 1, entidades: {}, memoria: memoriaVisivel(conv.memoria), retrieval: null, chunks: [], ferramentas: [], sql: null, guardrails: [], handoff: null, tecnicas: ["human_handoff"], latencia_ms: Math.round(performance.now() - inicio), modo_llm: "mock", venda: null },
      };
    }

    const { saida, n } = responder(e, conv, mensagem);
    e.intencoes[n.intencao] = (e.intencoes[n.intencao] ?? 0) + 1;
    if (saida.resposta) conv.mensagens.push({ papel: "assistant", conteudo: saida.resposta, criado_em: agora() });
    salvar(e);

    const debug: DebugInfo = {
      intencao: n.intencao,
      confianca: n.confianca,
      entidades: Object.fromEntries(Object.entries(n.entidades).map(([k, v]) => [k, k === "cpf_cnpj" ? mascararDoc(v) : v])),
      memoria: memoriaVisivel(conv.memoria),
      retrieval: saida.retrieval,
      chunks: saida.chunks,
      ferramentas: saida.ferramentas,
      sql: saida.sql,
      guardrails: saida.guardrails,
      handoff: saida.handoff,
      tecnicas: Array.from(new Set(saida.tecnicas)),
      latencia_ms: Math.round(performance.now() - inicio),
      modo_llm: "mock",
      venda: saida.venda,
    };
    const statusFinal = conv.status as StatusConversa; // responder() pode ter mudado para "humano"
    return { resposta: saida.resposta, status_conversa: statusFinal === "humano" ? "humano" : "bot", sugestoes: saida.sugestoes, debug };
  },

  mensagens: async (conversa_id: string): Promise<Mensagem[]> => {
    await esperar(60);
    const c = estado().conversas[conversa_id];
    if (!c) {
      if (conversa_id === "demo-conversa-01") {
        return [
          { papel: "user", conteudo: "Preciso da 2ª via do boleto dos P45. CNPJ 11.222.333/0001-81", criado_em: new Date(Date.now() - 20 * 60000).toISOString() },
          { papel: "assistant", conteudo: "Aqui está a 2ª via (**vencido** — valor atualizado com multa e juros).", criado_em: new Date(Date.now() - 19.5 * 60000).toISOString() },
          { papel: "user", conteudo: "Quero negociar esse valor, falar com uma pessoa", criado_em: new Date(Date.now() - 18 * 60000).toISOString() },
        ];
      }
      return [];
    }
    return c.mensagens;
  },

  handoffs: async (status?: StatusHandoff): Promise<Handoff[]> => {
    await esperar(100);
    const hs = estado().handoffs;
    return status ? hs.filter((h) => h.status === status) : hs;
  },

  assumirHandoff: async (id: number): Promise<unknown> => {
    await esperar(120);
    const e = estado();
    const h = e.handoffs.find((x) => x.id === id);
    if (h) h.status = "em_atendimento";
    salvar(e);
    return { ok: true };
  },

  resolverHandoff: async (id: number): Promise<unknown> => {
    await esperar(120);
    const e = estado();
    const h = e.handoffs.find((x) => x.id === id);
    if (h) {
      h.status = "resolvido";
      const c = e.conversas[h.conversa_id];
      if (c) {
        c.status = "bot";
        c.mensagens.push({ papel: "system", conteudo: "Atendimento humano encerrado. O assistente virtual voltou a responder.", criado_em: agora() });
      }
    }
    salvar(e);
    return { ok: true };
  },

  mensagemAtendente: async (conversa_id: string, mensagem: string): Promise<unknown> => {
    await esperar(100);
    const e = estado();
    conversa(e, conversa_id).mensagens.push({ papel: "assistant", conteudo: mensagem, criado_em: agora(), autor: "atendente" });
    salvar(e);
    return { ok: true };
  },

  leads: async (): Promise<Lead[]> => {
    await esperar(100);
    return estado().leads;
  },

  metricas: async (): Promise<Metricas> => {
    await esperar(120);
    const e = estado();
    const leads_por_estagio: Record<string, number> = { novo: 0, qualificado: 0, proposta: 0, ganho: 0, perdido: 0 };
    for (const l of e.leads) leads_por_estagio[l.estagio] = (leads_por_estagio[l.estagio] ?? 0) + 1;
    const intencoes_top = Object.entries(e.intencoes)
      .map(([intencao, qtd]) => ({ intencao, qtd }))
      .sort((a, b) => b.qtd - a.qtd)
      .slice(0, 8);
    return { conversas: 214 + Object.keys(e.conversas).length, handoffs_pendentes: e.handoffs.filter((h) => h.status === "pendente").length, leads_por_estagio, intencoes_top };
  },

  perguntarSql: async (pergunta: string): Promise<SqlResponse> => {
    await esperar(500 + Math.random() * 400);
    return textoParaSql(pergunta);
  },

  vendasRevgas: async (): Promise<VendaRevgas[]> => {
    await esperar(100);
    return estado().vendas;
  },

  revgasStatus: async (): Promise<RevgasStatus> => {
    await esperar(60);
    return { modo: "dryrun", chave_configurada: false, produtos: PRODUTOS.length + Object.keys(VASILHAMES).length };
  },
};
