import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, errMsg, type Lead, type Metricas, type RevgasStatus, type SqlResponse, type VendaRevgas } from "../api";
import { ESTAGIOS, brl, formatarValor, rotuloIntencao, tempoRelativo } from "../rotulos";

const EXEMPLOS_SQL = [
  "Faturamento por filial em 2026",
  "Produtos com estoque baixo",
  "Preço dos botijões de gás",
  "Vendas por mês",
];

export default function GestorPage() {
  const [metricas, setMetricas] = useState<Metricas | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      const [m, l] = await Promise.all([api.metricas(), api.leads()]);
      setMetricas(m);
      setLeads(l);
      setErro(null);
    } catch (e) {
      setErro(errMsg(e));
    }
  }, []);

  useEffect(() => {
    void carregar();
    const t = setInterval(() => void carregar(), 15000);
    return () => clearInterval(t);
  }, [carregar]);

  const porEstagio = metricas?.leads_por_estagio ?? {};
  const totalLeads = Object.values(porEstagio).reduce((a, b) => a + b, 0) || leads.length;
  const ganhos = porEstagio.ganho ?? 0;
  const fechados = ganhos + (porEstagio.perdido ?? 0);
  const conversao = fechados ? Math.round((ganhos / fechados) * 100) : null;
  const maxEstagio = Math.max(1, ...Object.values(porEstagio));
  const intencoes = metricas?.intencoes_top ?? [];
  const maxIntencao = Math.max(1, ...intencoes.map((i) => i.qtd));
  const estagiosExtras = Object.keys(porEstagio).filter((k) => !ESTAGIOS.some((e) => e.chave === k));
  const estagios = [...ESTAGIOS, ...estagiosExtras.map((k) => ({ chave: k, rotulo: k }))];

  return (
    <div className="painel-gestor">
      <div className="gestor-topo">
        <div>
          <h1>Painel do gestor</h1>
          <p>Vendas criadas pelo chatbot, atendimento, funil de leads B2B e consultas em linguagem natural.</p>
        </div>
        <button type="button" className="btn btn-sec btn-peq" onClick={() => void carregar()}>
          Atualizar
        </button>
      </div>

      {erro && <div className="faixa faixa-erro">{erro}</div>}

      <div className="kpis">
        <Kpi rotulo="Conversas" valor={metricas?.conversas} />
        <Kpi rotulo="Handoffs pendentes" valor={metricas?.handoffs_pendentes} destaque={!!metricas?.handoffs_pendentes} />
        <Kpi rotulo="Leads no funil" valor={metricas ? totalLeads : undefined} />
        <Kpi rotulo="Taxa de ganho" valor={conversao} sufixo="%" dica="ganhos ÷ (ganhos + perdidos)" />
      </div>

      <div className="gestor-grade">
        <section className="card">
          <h2>Leads por estágio</h2>
          <div className="funil">
            {estagios.map((e) => {
              const v = porEstagio[e.chave] ?? 0;
              return (
                <div key={e.chave} className="funil-linha">
                  <span className="funil-rot">{e.rotulo}</span>
                  <span className="funil-barra">
                    <span className={`est-${e.chave}`} style={{ width: `${(v / maxEstagio) * 100}%` }} />
                  </span>
                  <strong>{v}</strong>
                </div>
              );
            })}
          </div>
        </section>

        <section className="card">
          <h2>Intenções mais frequentes</h2>
          {intencoes.length === 0 ? (
            <p className="vazio">Sem dados ainda.</p>
          ) : (
            <div className="funil">
              {intencoes.map((i) => (
                <div key={i.intencao} className="funil-linha">
                  <span className="funil-rot" title={i.intencao}>
                    {rotuloIntencao(i.intencao)}
                  </span>
                  <span className="funil-barra">
                    <span className="est-intencao" style={{ width: `${(i.qtd / maxIntencao) * 100}%` }} />
                  </span>
                  <strong>{i.qtd}</strong>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <VendasChatbot />

      <TextToSql />

      <section className="card">
        <div className="card-topo">
          <h2>Leads recentes</h2>
          <span className="sub">ordenados por score</span>
        </div>
        <div className="tabela-wrap">
          <table className="tabela">
            <thead>
              <tr>
                <th>Nome</th>
                <th>Interesse</th>
                <th>Origem</th>
                <th>Estágio</th>
                <th className="num">Score</th>
                <th>Criado</th>
              </tr>
            </thead>
            <tbody>
              {[...leads]
                .sort((a, b) => b.score - a.score)
                .slice(0, 12)
                .map((l) => (
                  <tr key={l.id}>
                    <td>{l.nome}</td>
                    <td className="trunc">{l.interesse ?? "—"}</td>
                    <td>{l.origem ?? "—"}</td>
                    <td>
                      <span className={`estagio est-${l.estagio}`}>{l.estagio}</span>
                    </td>
                    <td className="num">
                      <span className={`score ${l.score >= 70 ? "alto" : l.score >= 40 ? "medio" : ""}`}>{l.score}</span>
                    </td>
                    <td>{l.criado_em ? tempoRelativo(l.criado_em) : "—"}</td>
                  </tr>
                ))}
              {leads.length === 0 && (
                <tr>
                  <td colSpan={6} className="vazio">
                    Nenhum lead registrado.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function Kpi({ rotulo, valor, sufixo, destaque, dica }: { rotulo: string; valor?: number | null; sufixo?: string; destaque?: boolean; dica?: string }) {
  return (
    <div className={`kpi card ${destaque ? "kpi-alerta" : ""}`} title={dica}>
      <span>{rotulo}</span>
      <strong>{valor === undefined ? <span className="esq-num" /> : valor === null ? "—" : `${valor.toLocaleString("pt-BR")}${sufixo ?? ""}`}</strong>
    </div>
  );
}

function TextToSql() {
  const [pergunta, setPergunta] = useState("");
  const [res, setRes] = useState<SqlResponse | null>(null);
  const [perguntaFeita, setPerguntaFeita] = useState("");
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  async function perguntar(p: string) {
    const q = p.trim();
    if (!q || carregando) return;
    setPergunta(q);
    setCarregando(true);
    setErro(null);
    try {
      setRes(await api.perguntarSql(q));
      setPerguntaFeita(q);
    } catch (e) {
      setErro(errMsg(e));
      setRes(null);
    } finally {
      setCarregando(false);
    }
  }

  function aoEnviar(e: FormEvent) {
    e.preventDefault();
    void perguntar(pergunta);
  }

  // `linhas` pode vir como lista de objetos ou de arrays; normaliza para arrays na ordem de `colunas`.
  const colunas = res?.colunas ?? [];
  const linhas: unknown[][] = (res?.linhas ?? []).map((l) =>
    Array.isArray(l) ? l : colunas.map((c) => (l as Record<string, unknown>)[c]),
  );
  const numericas = colunas.map((_, j) => linhas.length > 0 && linhas.every((r) => typeof r[j] === "number" || r[j] == null));

  return (
    <section className="card sql-card">
      <div className="card-topo">
        <div>
          <h2>Pergunte aos dados</h2>
          <span className="sub">Text-to-SQL controlado: só SELECT nas views vw_*, LIMIT ≤ 50, conexão somente-leitura</span>
        </div>
      </div>
      <form className="sql-form" onSubmit={aoEnviar}>
        <input value={pergunta} onChange={(e) => setPergunta(e.target.value)} placeholder="Ex.: faturamento por filial em 2026" aria-label="Pergunta em linguagem natural" maxLength={300} />
        <button type="submit" className="btn btn-pri" disabled={!pergunta.trim() || carregando}>
          {carregando ? "Consultando…" : "Gerar SQL"}
        </button>
      </form>
      <div className="chips chips-esq">
        {EXEMPLOS_SQL.map((x) => (
          <button key={x} type="button" className="chip" onClick={() => void perguntar(x)} disabled={carregando}>
            {x}
          </button>
        ))}
      </div>

      {erro && <div className="faixa faixa-erro">{erro}</div>}

      {res && (
        <div className="sql-resultado">
          <span className="rot">SQL gerado para “{perguntaFeita}”</span>
          {res.explicacao && <p className="sql-explicacao">{res.explicacao}</p>}
          <pre className="sql">{res.sql}</pre>
          <span className="rot">
            {linhas.length} linha{linhas.length === 1 ? "" : "s"}
          </span>
          <div className="tabela-wrap">
            <table className="tabela">
              <thead>
                <tr>
                  {colunas.map((c, j) => (
                    <th key={c} className={numericas[j] ? "num" : ""}>
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {linhas.map((r, i) => (
                  <tr key={i}>
                    {r.map((v, j) => (
                      <td key={j} className={numericas[j] ? "num" : ""}>
                        {typeof v === "number" && /faturamento|valor|preco|total|receita|ticket/i.test(colunas[j] ?? "") ? brl(v) : formatarValor(v)}
                      </td>
                    ))}
                  </tr>
                ))}
                {linhas.length === 0 && (
                  <tr>
                    <td colSpan={Math.max(1, colunas.length)} className="vazio">
                      A consulta não retornou linhas.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

const MODOS: Record<string, string> = { dryrun: "dry-run (simulado)", real: "REAL (grava na RevGás)", offline: "offline (snapshot)" };

function VendasChatbot() {
  const [vendas, setVendas] = useState<VendaRevgas[] | null>(null);
  const [status, setStatus] = useState<RevgasStatus | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      setVendas(await api.vendasRevgas());
      setErro(null);
    } catch (e) {
      setErro(errMsg(e));
    }
    try {
      setStatus(await api.revgasStatus());
    } catch {
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    void carregar();
    const t = setInterval(() => void carregar(), 10000);
    return () => clearInterval(t);
  }, [carregar]);

  const lista = [...(vendas ?? [])].sort((a, b) => b.criado_em.localeCompare(a.criado_em));
  const validas = lista.filter((v) => v.status !== "ERRO");
  const faturamento = validas.reduce((a, v) => a + (Number(v.total) || 0), 0);
  const ticket = validas.length ? faturamento / validas.length : 0;
  const botijoes = validas.reduce((a, v) => a + (v.itens ?? []).filter((i) => /^GLP/i.test(i.nome)).reduce((x, i) => x + i.qtd, 0), 0);
  const itensTxt = (v: VendaRevgas) => (v.itens ?? []).map((i) => `${i.qtd}× ${i.nome}`).join(", ");

  return (
    <section className="card vendas-card">
      <div className="card-topo">
        <div>
          <h2>Vendas pelo chatbot</h2>
          <span className="sub">Pedidos fechados na conversa e enviados ao ERP RevGás (POST /sales)</span>
        </div>
        {status && (
          <span className={`pill ${status.modo === "real" ? "pill-erro" : "pill-aviso"}`} title={`chave configurada: ${status.chave_configurada ? "sim" : "não"} · ${status.produtos} produtos no catálogo`}>
            <span className="ponto" /> RevGás: {MODOS[status.modo] ?? status.modo}
          </span>
        )}
      </div>
      {erro && <div className="faixa faixa-erro">{erro}</div>}
      <div className="mini-kpis">
        <div>
          <span>Vendas</span>
          <strong>{vendas ? validas.length : "…"}</strong>
        </div>
        <div>
          <span>Valor total</span>
          <strong>{vendas ? brl(faturamento) : "…"}</strong>
        </div>
        <div>
          <span>Ticket médio</span>
          <strong>{vendas ? brl(ticket) : "…"}</strong>
        </div>
        <div>
          <span>Botijões vendidos</span>
          <strong>{vendas ? botijoes : "…"}</strong>
        </div>
      </div>
      <div className="tabela-wrap">
        <table className="tabela">
          <thead>
            <tr>
              <th>Pedido</th>
              <th>Status</th>
              <th>Itens</th>
              <th className="num">Total</th>
              <th>Quando</th>
            </tr>
          </thead>
          <tbody>
            {lista.slice(0, 10).map((v) => (
              <tr key={v.numero_local}>
                <td>
                  <code>{v.numero_local}</code>
                  {v.revgas_id ? <span className="sub"> · RevGás #{v.revgas_id}</span> : null}
                </td>
                <td>
                  <span className={`selo ${v.status === "DRYRUN" ? "selo-dry" : v.status === "ERRO" ? "selo-erro" : "selo-ok"}`}>
                    {v.status === "DRYRUN" ? "simulado (dry-run)" : v.status === "ENVIADA" ? "enviada" : String(v.status).toLowerCase()}
                  </span>
                </td>
                <td className="trunc" title={itensTxt(v)}>
                  {itensTxt(v)}
                </td>
                <td className="num">{brl(v.total)}</td>
                <td>{tempoRelativo(v.criado_em)}</td>
              </tr>
            ))}
            {vendas && lista.length === 0 && (
              <tr>
                <td colSpan={5} className="vazio">
                  Nenhuma venda ainda. Faça um pedido no chat: “Quero 2 botijões de 13 e um galão de água”.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
