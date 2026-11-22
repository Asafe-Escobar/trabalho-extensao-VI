// Card de pedido exibido no chat quando a venda foi criada (debug.venda / ferramenta criar_venda)
// ou quando o bot mostra o resumo e aguarda "Confirma o pedido?".
import type { DebugInfo, EnderecoVenda, ItemVenda, RevgasPayload } from "../api";
import { brl, rotuloPagamento } from "../rotulos";

export interface PedidoView {
  numero: string | null;
  status: string; // DRYRUN | ENVIADA | ERRO | RASCUNHO
  itens: ItemVenda[];
  total: number;
  endereco: string | null;
  pagamento: string | null;
  troco_para?: number | null;
  previsao?: string | null;
}

const num = (v: unknown): number => (typeof v === "number" ? v : Number(v) || 0);

function normalizarItens(lista: unknown): ItemVenda[] {
  if (!Array.isArray(lista)) return [];
  return lista
    .filter((x): x is Record<string, unknown> => !!x && typeof x === "object")
    .map((x) => ({
      nome: String(x.nome ?? x.product_description ?? x.descricao ?? `Produto #${x.product_id ?? x.revgas_id ?? "?"}`),
      qtd: num(x.qtd ?? x.quantidade ?? x.quantity ?? 1),
      preco: num(x.preco ?? x.valor ?? x.value ?? 0),
      revgas_id: typeof (x.revgas_id ?? x.product_id) === "number" ? ((x.revgas_id ?? x.product_id) as number) : undefined,
    }));
}

export function enderecoParaTexto(e: unknown): string | null {
  if (!e) return null;
  if (typeof e === "string") return e;
  if (typeof e === "object") {
    const x = e as EnderecoVenda & Record<string, unknown>;
    const rua = x.rua ?? (x.location as string | undefined);
    const numero = x.numero ?? (x.number as string | undefined);
    const bairro = x.bairro ?? (x.neighborhood as string | undefined);
    const cidade = x.cidade ?? (x.city as string | undefined);
    const partes = [rua ? `${rua}${numero ? `, ${numero}` : ""}` : null, bairro, cidade].filter(Boolean);
    return partes.length ? partes.join(" – ") : null;
  }
  return null;
}

/** Extrai o pedido do debug, se houver. Ordem: debug.venda → criar_venda.entrada → resumo aguardando confirmação. */
export function pedidoDoDebug(d: DebugInfo | null | undefined, resposta: string): PedidoView | null {
  if (!d) return null;
  if (d.venda) {
    const v = d.venda;
    const itens = normalizarItens(v.itens?.length ? v.itens : v.payload?.products);
    return {
      numero: v.numero ?? null,
      status: String(v.status ?? "DRYRUN").toUpperCase(),
      itens,
      total: num(v.total) || itens.reduce((a, i) => a + i.qtd * i.preco, 0),
      endereco: enderecoParaTexto(v.endereco) ?? enderecoParaTexto(v.payload),
      pagamento: v.pagamento ?? v.payload?.payments?.[0]?.payment_type ?? null,
      troco_para: v.troco_para ?? null,
      previsao: v.previsao ?? "30 a 60 min",
    };
  }
  const f = d.ferramentas?.find((x) => x.nome === "criar_venda");
  if (f) {
    const bruto = f.entrada as Record<string, unknown>;
    const p = ((bruto?.payload_revgas ?? bruto?.payload ?? bruto) || {}) as RevgasPayload;
    const itens = normalizarItens(p.products);
    const numero = f.saida_resumo.match(/RV-[A-Z0-9-]+/)?.[0] ?? null;
    const status = /DRYRUN|dry-?run/i.test(f.saida_resumo) ? "DRYRUN" : /ERRO|erro/.test(f.saida_resumo) ? "ERRO" : "ENVIADA";
    return {
      numero,
      status,
      itens,
      total: itens.reduce((a, i) => a + i.qtd * i.preco, 0),
      endereco: enderecoParaTexto(p),
      pagamento: p.payments?.[0]?.payment_type ?? null,
      previsao: "30 a 60 min",
    };
  }
  const mem = d.memoria ?? {};
  const aguardando = mem.aguardando === "confirmacao" || /confirma o pedido\??/i.test(resposta);
  const carrinho = normalizarItens(mem.carrinho);
  if (aguardando && carrinho.length) {
    return {
      numero: null,
      status: "RASCUNHO",
      itens: carrinho,
      total: carrinho.reduce((a, i) => a + i.qtd * i.preco, 0),
      endereco: enderecoParaTexto(mem.endereco),
      pagamento: typeof mem.pagamento === "string" ? mem.pagamento : null,
      troco_para: typeof mem.troco_para === "number" ? mem.troco_para : null,
    };
  }
  return null;
}

const SELOS: Record<string, { rotulo: string; classe: string }> = {
  DRYRUN: { rotulo: "simulado (dry-run)", classe: "selo-dry" },
  ENVIADA: { rotulo: "enviado à RevGás", classe: "selo-ok" },
  ERRO: { rotulo: "erro no envio", classe: "selo-erro" },
  RASCUNHO: { rotulo: "aguardando confirmação", classe: "selo-rascunho" },
};

export default function PedidoCard({ p }: { p: PedidoView }) {
  const selo = SELOS[p.status] ?? { rotulo: p.status.toLowerCase(), classe: "selo-rascunho" };
  return (
    <div className={`pedido-card ${p.status === "RASCUNHO" ? "rascunho" : ""}`}>
      <div className="pc-topo">
        <div>
          <span className="pc-rot">{p.status === "RASCUNHO" ? "Resumo do pedido" : "Pedido"}</span>
          <strong className="pc-numero">{p.numero ?? "a confirmar"}</strong>
        </div>
        <span className={`selo ${selo.classe}`}>{selo.rotulo}</span>
      </div>
      <table className="pc-itens">
        <tbody>
          {p.itens.map((i, k) => (
            <tr key={k}>
              <td className="pc-qtd">{i.qtd}×</td>
              <td>{i.nome}</td>
              <td className="num">{brl(i.preco)}</td>
              <td className="num">{brl(i.qtd * i.preco)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={3}>Total</td>
            <td className="num">{brl(p.total)}</td>
          </tr>
        </tfoot>
      </table>
      <dl className="pc-info">
        <div>
          <dt>Entrega</dt>
          <dd>{p.endereco ?? "—"}</dd>
        </div>
        <div>
          <dt>Pagamento</dt>
          <dd>
            {p.pagamento ? rotuloPagamento(p.pagamento) : "—"}
            {p.troco_para ? ` · troco para ${brl(p.troco_para)}` : ""}
          </dd>
        </div>
        {p.previsao && p.status !== "RASCUNHO" && (
          <div>
            <dt>Previsão</dt>
            <dd>{p.previsao}</dd>
          </div>
        )}
      </dl>
      {p.status === "DRYRUN" && <p className="pc-nota">Modo dry-run: o payload foi validado e gravado localmente; nenhuma venda real foi enviada à RevGás.</p>}
    </div>
  );
}
