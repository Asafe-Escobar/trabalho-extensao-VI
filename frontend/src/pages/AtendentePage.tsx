import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, errMsg, type Handoff, type Mensagem, type StatusHandoff } from "../api";
import { Markdown } from "../markdown";
import { STATUS_HANDOFF, formatarValor, hora, rotuloChave, tempoRelativo } from "../rotulos";

const ehUrgente = (h: Handoff) => /emergencia|vazamento|urgente/i.test(h.motivo) || h.dados?.prioridade === "URGENTE";

const FILTROS: StatusHandoff[] = ["pendente", "em_atendimento", "resolvido"];

export default function AtendentePage() {
  const [filtro, setFiltro] = useState<StatusHandoff>("pendente");
  const [fila, setFila] = useState<Handoff[]>([]);
  const [contagem, setContagem] = useState<Record<string, number>>({});
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [selId, setSelId] = useState<number | null>(null);
  const [selecionado, setSelecionado] = useState<Handoff | null>(null);

  const carregarFila = useCallback(async () => {
    try {
      // Uma chamada por status (forma do contrato: ?status=...) para mostrar os contadores.
      const porStatus = await Promise.all(FILTROS.map((s) => api.handoffs(s)));
      const todos = porStatus.flat();
      const c: Record<string, number> = {};
      for (const h of todos) c[h.status] = (c[h.status] ?? 0) + 1;
      setContagem(c);
      setFila(
        todos
          .filter((h) => h.status === filtro)
          .sort((a, b) => Number(ehUrgente(b)) - Number(ehUrgente(a)) || b.criado_em.localeCompare(a.criado_em)),
      );
      setErro(null);
      setSelecionado((atual) => (atual ? todos.find((h) => h.id === atual.id) ?? atual : atual));
    } catch (e) {
      setErro(errMsg(e));
    } finally {
      setCarregando(false);
    }
  }, [filtro]);

  useEffect(() => {
    setCarregando(true);
    void carregarFila();
    const t = setInterval(() => void carregarFila(), 5000);
    return () => clearInterval(t);
  }, [carregarFila]);

  useEffect(() => {
    if (selId == null) return setSelecionado(null);
    const h = fila.find((x) => x.id === selId);
    if (h) setSelecionado(h);
  }, [selId, fila]);

  return (
    <div className={`painel-atendente ${selecionado ? "com-detalhe" : ""}`}>
      <section className="fila card">
        <div className="card-topo">
          <h2>Fila de atendimento</h2>
          <button type="button" className="btn btn-sec btn-peq" onClick={() => void carregarFila()}>
            Atualizar
          </button>
        </div>
        <div className="segmentado" role="tablist">
          {FILTROS.map((f) => (
            <button key={f} type="button" role="tab" aria-selected={filtro === f} className={filtro === f ? "ativo" : ""} onClick={() => setFiltro(f)}>
              {STATUS_HANDOFF[f]}
              <span className="contador">{contagem[f] ?? 0}</span>
            </button>
          ))}
        </div>

        {erro && <div className="faixa faixa-erro">{erro}</div>}
        {carregando && !fila.length ? (
          <div className="esqueleto-lista">
            <div />
            <div />
            <div />
          </div>
        ) : fila.length === 0 ? (
          <div className="vazio-grande">
            <p>Nenhuma conversa {STATUS_HANDOFF[filtro].toLowerCase()}.</p>
            <span>Quando um cliente pedir um atendente no chat, ela aparece aqui.</span>
          </div>
        ) : (
          <ul className="lista-handoffs">
            {fila.map((h) => (
              <li key={h.id}>
                <button type="button" className={`item-handoff ${selecionado?.id === h.id ? "ativo" : ""} ${ehUrgente(h) ? "urgente" : ""}`} onClick={() => setSelId(h.id)}>
                  <div className="ih-topo">
                    <strong>#{h.id} · {String(h.dados?.cliente ?? "Cliente não identificado")}</strong>
                    <span className="ih-tempo">{tempoRelativo(h.criado_em)}</span>
                  </div>
                  <p>{h.resumo}</p>
                  <div className="ih-rodape">
                    <span className={`status status-${h.status}`}>{STATUS_HANDOFF[h.status] ?? h.status}</span>
                    {ehUrgente(h) && <span className="status status-urgente">URGENTE</span>}
                    <span className="motivo">{h.motivo.replace(/_/g, " ")}</span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {selecionado ? (
        <DetalheHandoff
          key={selecionado.id}
          h={selecionado}
          onVoltar={() => setSelId(null)}
          onMudou={async (novoFiltro) => {
            if (novoFiltro) setFiltro(novoFiltro);
            await carregarFila();
          }}
        />
      ) : (
        <section className="card detalhe-vazio">
          <img src="/flow.svg" alt="" width={44} height={44} />
          <h3>Selecione uma conversa</h3>
          <p>O bot já entrega um resumo e os dados coletados, para o cliente não precisar repetir nada.</p>
        </section>
      )}
    </div>
  );
}

function DetalheHandoff({ h, onVoltar, onMudou }: { h: Handoff; onVoltar: () => void; onMudou: (f?: StatusHandoff) => Promise<void> }) {
  const [msgs, setMsgs] = useState<Mensagem[]>([]);
  const [texto, setTexto] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const fimRef = useRef<HTMLDivElement>(null);

  const carregarMsgs = useCallback(async () => {
    try {
      setMsgs(await api.mensagens(h.conversa_id));
    } catch (e) {
      setErro(errMsg(e));
    }
  }, [h.conversa_id]);

  useEffect(() => {
    void carregarMsgs();
    const t = setInterval(() => void carregarMsgs(), 3500);
    return () => clearInterval(t);
  }, [carregarMsgs]);

  useEffect(() => {
    fimRef.current?.scrollIntoView({ block: "end" });
  }, [msgs.length]);

  async function acao(fn: () => Promise<unknown>, filtro?: StatusHandoff) {
    setOcupado(true);
    setErro(null);
    try {
      await fn();
      await onMudou(filtro);
      await carregarMsgs();
    } catch (e) {
      setErro(errMsg(e));
    } finally {
      setOcupado(false);
    }
  }

  async function responder(e: FormEvent) {
    e.preventDefault();
    const m = texto.trim();
    if (!m) return;
    setTexto("");
    await acao(() => api.mensagemAtendente(h.conversa_id, m));
  }

  const dados = Object.entries(h.dados ?? {}).filter(
    ([, v]) => v !== null && v !== undefined && v !== "" && !(typeof v === "object" && Object.keys(v as object).length === 0),
  );

  return (
    <section className="card detalhe">
      <div className="card-topo">
        <button type="button" className="btn btn-sec btn-peq so-mobile" onClick={onVoltar}>
          ← Fila
        </button>
        <div className="detalhe-titulo">
          <h2>Handoff #{h.id}</h2>
          <span className={`status status-${h.status}`}>{STATUS_HANDOFF[h.status] ?? h.status}</span>
        </div>
        <div className="detalhe-acoes">
          {h.status === "pendente" && (
            <button type="button" className="btn btn-pri" disabled={ocupado} onClick={() => void acao(() => api.assumirHandoff(h.id), "em_atendimento")}>
              Assumir conversa
            </button>
          )}
          {h.status === "em_atendimento" && (
            <button type="button" className="btn btn-ok" disabled={ocupado} onClick={() => void acao(() => api.resolverHandoff(h.id), "resolvido")}>
              Marcar como resolvido
            </button>
          )}
        </div>
      </div>

      {erro && <div className="faixa faixa-erro">{erro}</div>}

      <div className="detalhe-grade">
        <div className="resumo-box">
          <span className="rot">Resumo gerado pelo bot</span>
          <p>{h.resumo}</p>
          <span className="rot">Motivo</span>
          <p>{h.motivo.replace(/_/g, " ")}</p>
        </div>
        <div className="dados-box">
          <span className="rot">Dados coletados</span>
          {dados.length ? (
            <dl className="kv">
              {dados.map(([k, v]) => (
                <div key={k}>
                  <dt>{rotuloChave(k)}</dt>
                  <dd>{formatarValor(/(^id|_id)$/.test(k) ? String(v) : v)}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="vazio">nenhum dado coletado</p>
          )}
        </div>
      </div>

      <div className="transcricao">
        <span className="rot">Conversa · {h.conversa_id.slice(0, 8)}</span>
        <div className="transcricao-lista">
          {msgs.length === 0 && <p className="vazio">Sem mensagens registradas.</p>}
          {msgs.map((m, i) =>
            m.papel === "system" ? (
              <div key={i} className="msg-sistema">
                {m.conteudo}
              </div>
            ) : (
              <div key={i} className={`t-msg t-${m.papel} ${m.autor === "atendente" ? "t-atendente" : ""}`}>
                <span className="t-autor">
                  {m.papel === "user" ? "Cliente" : m.autor === "atendente" ? "Atendente" : "Bot"} · {hora(m.criado_em)}
                </span>
                <Markdown texto={m.conteudo} />
              </div>
            ),
          )}
          <div ref={fimRef} />
        </div>
      </div>

      <form className="entrada" onSubmit={responder}>
        <textarea
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void responder(e);
            }
          }}
          placeholder={h.status === "em_atendimento" ? "Responder ao cliente…" : h.status === "pendente" ? "Assuma a conversa para responder" : "Atendimento encerrado"}
          disabled={h.status !== "em_atendimento" || ocupado}
          rows={1}
          aria-label="Resposta ao cliente"
        />
        <button type="submit" className="btn btn-pri" disabled={h.status !== "em_atendimento" || !texto.trim() || ocupado}>
          Enviar
        </button>
      </form>
    </section>
  );
}
