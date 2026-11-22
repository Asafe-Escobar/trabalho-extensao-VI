// Painel "Por dentro do bot": mostra o campo `debug` do /api/chat técnica a técnica,
// na ordem do pipeline do orquestrador (CONTRACT.md → BACKEND).
import { useState, type ReactNode } from "react";
import type { DebugInfo, RevgasPayload } from "../api";
import { brl, formatarValor, rotuloChave, rotuloIntencao, rotuloPagamento, rotuloTecnica } from "../rotulos";

function Etapa({
  n,
  titulo,
  tecnica,
  ativo,
  children,
}: {
  n: number;
  titulo: string;
  tecnica: string;
  ativo: boolean;
  children?: ReactNode;
}) {
  return (
    <section className={`etapa ${ativo ? "ativa" : "inativa"}`}>
      <header>
        <span className="etapa-n">{n}</span>
        <div>
          <h4>{titulo}</h4>
          <span className="etapa-tec">{tecnica}</span>
        </div>
        <span className={`etapa-status ${ativo ? "on" : ""}`}>{ativo ? "acionada" : "não acionada"}</span>
      </header>
      {ativo && children && <div className="etapa-corpo">{children}</div>}
    </section>
  );
}

const preenchido = (v: unknown) => v !== null && v !== undefined && v !== "" && !(typeof v === "object" && Object.keys(v as object).length === 0);

function ChaveValor({ dados }: { dados: Record<string, unknown> }) {
  const entradas = Object.entries(dados ?? {}).filter(([, v]) => preenchido(v));
  if (!entradas.length) return <p className="vazio">vazio</p>;
  return (
    <dl className="kv">
      {entradas.map(([k, v]) => (
        <div key={k}>
          <dt>{rotuloChave(k)}</dt>
          <dd>{formatarValor(/(^id|_id)$/.test(k) ? String(v) : v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Barra({ valor, max = 1 }: { valor: number; max?: number }) {
  const pct = Math.max(0, Math.min(100, (valor / max) * 100));
  return (
    <span className="barra" aria-hidden>
      <span style={{ width: `${pct}%` }} />
    </span>
  );
}

function Expansivel({ resumo, children }: { resumo: string; children: ReactNode }) {
  const [aberto, setAberto] = useState(false);
  return (
    <div className="expansivel">
      <button type="button" className="link" onClick={() => setAberto((a) => !a)} aria-expanded={aberto}>
        {aberto ? "▾" : "▸"} {resumo}
      </button>
      {aberto && children}
    </div>
  );
}

export default function DebugPanel({ debug, onFechar }: { debug: DebugInfo | null; onFechar?: () => void }) {
  return (
    <aside className="debug" aria-label="Por dentro do bot">
      <div className="debug-topo">
        <div>
          <h3>Por dentro do bot</h3>
          <p>Cada etapa do pipeline para a mensagem selecionada.</p>
        </div>
        {onFechar && (
          <button type="button" className="btn-icone" onClick={onFechar} aria-label="Fechar painel">
            ✕
          </button>
        )}
      </div>

      {!debug ? (
        <div className="debug-vazio">
          <img src="/flow.svg" alt="" width={40} height={40} />
          <p>Envie uma mensagem no chat para ver aqui a intenção detectada, a busca na base de conhecimento, as ferramentas chamadas e os guardrails aplicados.</p>
        </div>
      ) : (
        <DebugConteudo d={debug} />
      )}
    </aside>
  );
}

function DebugConteudo({ d }: { d: DebugInfo }) {
  const r = d.retrieval;
  const ferramentas = d.ferramentas ?? [];
  const chunks = d.chunks ?? [];
  const guardrails = d.guardrails ?? [];
  const tecnicas = d.tecnicas ?? [];
  const maxScore = Math.max(1, ...chunks.map((c) => c.score));
  const temEntidades = Object.keys(d.entidades ?? {}).length > 0;
  const temMemoria = Object.keys(d.memoria ?? {}).length > 0;
  const fVenda = ferramentas.find((f) => f.nome === "criar_venda");
  const payload: RevgasPayload | null = d.venda?.payload ?? (fVenda ? payloadDaFerramenta(fVenda.entrada) : null);
  const statusFerramenta = fVenda ? (/dry-?run/i.test(fVenda.saida_resumo) ? "DRYRUN" : /erro/i.test(fVenda.saida_resumo) ? "ERRO" : "ENVIADA") : "";
  const numeroFerramenta = fVenda?.saida_resumo.match(/RV-[A-Z0-9-]+/)?.[0] ?? "";

  return (
    <div className="debug-corpo">
      <div className="debug-resumo">
        <div>
          <span className="rot">Latência</span>
          <strong>{d.latencia_ms?.toLocaleString("pt-BR") ?? "—"} ms</strong>
        </div>
        <div>
          <span className="rot">Modo LLM</span>
          <strong className={d.modo_llm === "anthropic" ? "cor-ok" : "cor-aviso"}>{d.modo_llm === "anthropic" ? "Claude" : d.modo_llm}</strong>
        </div>
        <div>
          <span className="rot">Técnicas</span>
          <strong>{tecnicas.length}</strong>
        </div>
      </div>
      {tecnicas.length > 0 && (
        <div className="tags">
          {tecnicas.map((t) => (
            <span key={t} className="tag">
              {rotuloTecnica(t)}
            </span>
          ))}
        </div>
      )}

      <Etapa n={1} titulo="Guardrails" tecnica="entrada e saída · LGPD · alçadas" ativo={guardrails.length > 0}>
        <ul className="lista-guard">
          {guardrails.map((g, i) => (
            <li key={i}>
              <code>{g.regra}</code>
              <span className={`acao ${/bloque/.test(g.acao) ? "bloq" : ""}`}>{g.acao.replace(/_/g, " ")}</span>
            </li>
          ))}
        </ul>
      </Etapa>

      <Etapa n={2} titulo="Classificação de intenção" tecnica="Intent Classification" ativo={!!d.intencao}>
        <div className="intencao">
          <strong>{rotuloIntencao(d.intencao)}</strong>
          <code>{d.intencao}</code>
        </div>
        <div className="confianca">
          <Barra valor={d.confianca ?? 0} />
          <span>{Math.round((d.confianca ?? 0) * 100)}% de confiança</span>
        </div>
      </Etapa>

      <Etapa n={3} titulo="Extração de entidades" tecnica="Entity Extraction" ativo={temEntidades}>
        <ChaveValor dados={d.entidades} />
      </Etapa>

      <Etapa n={4} titulo="Memória da conversa" tecnica="Conversation Memory (slots)" ativo={temMemoria}>
        <ChaveValor dados={d.memoria} />
      </Etapa>

      <Etapa n={5} titulo="Preparação da busca" tecnica="Rewrite · Multi-Query · Expansion · HyDE" ativo={!!r}>
        {r && (
          <div className="retrieval">
            <div className="ret-item">
              <span className="rot">Pergunta original</span>
              <p>{r.original}</p>
            </div>
            <div className="ret-item">
              <span className="rot">Query Rewriting</span>
              {r.reescrita ? <p className="destaque">{r.reescrita}</p> : <p className="vazio">não precisou reescrever</p>}
            </div>
            <div className="ret-item">
              <span className="rot">Multi-Query ({r.multi_queries?.length ?? 0})</span>
              {r.multi_queries?.length ? (
                <ol className="mq">
                  {r.multi_queries.map((q, i) => (
                    <li key={i}>{q}</li>
                  ))}
                </ol>
              ) : (
                <p className="vazio">—</p>
              )}
            </div>
            <div className="ret-item">
              <span className="rot">Query Expansion</span>
              {r.expansao?.length ? (
                <div className="tags">
                  {r.expansao.map((x, i) => (
                    <span key={i} className="tag tag-claro">
                      {x}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="vazio">sem termos adicionais</p>
              )}
            </div>
            <div className="ret-item">
              <span className="rot">HyDE — documento hipotético</span>
              {r.hyde_doc ? (
                <Expansivel resumo="ver documento gerado">
                  <p className="hyde">{r.hyde_doc}</p>
                </Expansivel>
              ) : (
                <p className="vazio">não usado nesta busca</p>
              )}
            </div>
            <div className="ret-linha">
              <span>
                <strong>{r.candidatos}</strong> candidatos
              </span>
              {r.tecnicas?.map((t) => (
                <span key={t} className="tag tag-claro">
                  {rotuloTecnica(t)}
                </span>
              ))}
            </div>
          </div>
        )}
      </Etapa>

      <Etapa n={6} titulo="Trechos recuperados" tecnica="RAG híbrido (BM25 + vetorial + RRF) · HyPE · GraphRAG · Reranking" ativo={chunks.length > 0}>
        <ol className="chunks">
          {chunks.map((c, i) => (
            <li key={i}>
              <div className="chunk-topo">
                <span className="chunk-pos">#{i + 1}</span>
                <strong>{c.titulo}</strong>
                <span className={`fonte fonte-${c.fonte}`}>{c.fonte}</span>
              </div>
              <div className="confianca">
                <Barra valor={c.score} max={maxScore} />
                <span>score {c.score.toFixed(3)}</span>
              </div>
              <p className="trecho">{c.trecho}</p>
            </li>
          ))}
        </ol>
      </Etapa>

      <Etapa n={7} titulo="Ferramentas chamadas" tecnica="Agentic RAG · Tool Calling (ERP)" ativo={ferramentas.length > 0}>
        <ol className="ferramentas">
          {ferramentas.map((f, i) => (
            <li key={i}>
              <code className="f-nome">{f.nome}()</code>
              {f.nome === "criar_venda" ? (
                <p className="f-saida">payload legível na etapa 8 ↓</p>
              ) : (
                Object.keys(f.entrada ?? {}).length > 0 && <pre className="f-entrada">{JSON.stringify(f.entrada, null, 2)}</pre>
              )}
              <p className="f-saida">→ {f.saida_resumo}</p>
            </li>
          ))}
        </ol>
      </Etapa>

      <Etapa n={8} titulo="Venda na RevGás" tecnica="criar_venda · POST /sales (payload sem chave)" ativo={!!payload}>
        {payload && <PayloadRevgas p={payload} status={d.venda?.status ?? statusFerramenta} numero={d.venda?.numero ?? numeroFerramenta} />}
      </Etapa>

      <Etapa n={9} titulo="Consulta SQL" tecnica="Text-to-SQL controlado (somente views vw_*)" ativo={!!d.sql}>
        {d.sql && <pre className="sql">{d.sql}</pre>}
      </Etapa>

      <Etapa n={10} titulo="Transferência para humano" tecnica="Human Handoff" ativo={!!d.handoff}>
        {d.handoff && (
          <div className="handoff-box">
            <strong>Handoff #{d.handoff.id}</strong> criado na fila do atendente
            <p>{d.handoff.resumo}</p>
          </div>
        )}
      </Etapa>
    </div>
  );
}

/** A entrada de criar_venda pode ser o payload puro ou {confirmado, payload_revgas: {...}} (back real). */
export function payloadDaFerramenta(entrada: Record<string, unknown>): RevgasPayload {
  const interno = entrada?.payload_revgas ?? entrada?.payload;
  return (interno && typeof interno === "object" ? interno : entrada) as RevgasPayload;
}

function PayloadRevgas({ p, status, numero }: { p: RevgasPayload; status: string; numero: string }) {
  const produtos = p.products ?? [];
  const total = produtos.reduce((a, x) => a + (Number(x.quantity) || 0) * (Number(x.value) || 0) - (Number(x.discount) || 0), 0);
  const endereco = [p.location && `${p.location}${p.number ? `, ${p.number}` : ""}`, p.neighborhood, p.city && `${p.city}${p.state_federation ? `/${p.state_federation}` : ""}`]
    .filter(Boolean)
    .join(" – ");
  return (
    <div className="payload">
      <div className="payload-topo">
        <code>POST /v1/sales</code>
        {numero && <strong>{numero}</strong>}
        <span className={`selo ${status === "DRYRUN" ? "selo-dry" : status === "ERRO" ? "selo-erro" : "selo-ok"}`}>
          {status === "DRYRUN" ? "dry-run: não enviado" : status === "ERRO" ? "erro" : "enviado"}
        </span>
      </div>
      <dl className="kv">
        <div>
          <dt>canal</dt>
          <dd>{p.channel ?? "—"}</dd>
        </div>
        <div>
          <dt>endereço</dt>
          <dd>{endereco || "—"}</dd>
        </div>
      </dl>
      <table className="payload-tabela">
        <thead>
          <tr>
            <th>product_id</th>
            <th className="num">qtd</th>
            <th className="num">valor</th>
            <th className="num">subtotal</th>
          </tr>
        </thead>
        <tbody>
          {produtos.map((x, i) => (
            <tr key={i}>
              <td>
                <code>{x.product_id}</code>
                {x.product_description && <span className="pd"> {x.product_description}</span>}
              </td>
              <td className="num">{x.quantity}</td>
              <td className="num">{brl(x.value)}</td>
              <td className="num">{brl(x.quantity * x.value - (x.discount ?? 0))}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={3}>total</td>
            <td className="num">{brl(total)}</td>
          </tr>
        </tfoot>
      </table>
      {p.payments?.length ? (
        <p className="payload-linha">
          <span className="rot">payments</span>
          {p.payments.map((x, i) => (
            <span key={i} className="tag tag-claro">
              {rotuloPagamento(String(x.payment_type))} · {brl(x.value)}
              {x.date ? ` · ${x.date}` : ""}
            </span>
          ))}
        </p>
      ) : null}
      {p.observation && (
        <p className="payload-linha">
          <span className="rot">observation</span>
          {p.observation}
        </p>
      )}
      <Expansivel resumo="ver JSON enviado">
        <pre className="sql">{JSON.stringify(p, null, 2)}</pre>
      </Expansivel>
    </div>
  );
}
