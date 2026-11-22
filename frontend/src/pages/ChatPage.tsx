import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { api, errMsg, type DebugInfo, type Mensagem, type StatusConversa } from "../api";
import DebugPanel from "../components/DebugPanel";
import PedidoCard, { pedidoDoDebug } from "../components/PedidoCard";
import { Markdown } from "../markdown";
import { hora, rotuloIntencao } from "../rotulos";

const CHAVE_CONVERSA = "flow-conversa-id";

interface MsgView {
  id: string;
  papel: "user" | "assistant" | "system";
  conteudo: string;
  criado_em?: string;
  debug?: DebugInfo | null;
  autor?: "bot" | "atendente";
  erro?: boolean;
}

const BOAS_VINDAS: MsgView = {
  id: "boas-vindas",
  papel: "assistant",
  autor: "bot",
  conteudo:
    "Olá! Eu sou o **Flow Assistente**, da **Flow Gás** 🔥\n\nFaço seu **pedido de gás ou água** aqui mesmo, informo **preços** e **estoque** nas filiais de Teresina, Parnaíba e São Luís e acompanho sua **entrega**. O que vai ser hoje?",
};

const SUGESTOES_INICIAIS = [
  "Pedir botijão",
  "Preço do P13",
  "Tem P45?",
  "Quero 2 botijões de 13 e um galão de água",
  "Sentindo cheiro de gás",
  "Meu CPF é 123.456.789-09, cadê o pedido FL-2026-00042?",
];

const ehUrgente = (d?: DebugInfo | null) => !!d?.guardrails?.some((g) => /vazamento|seguranca|emergencia/i.test(g.regra));

/** Há atendimento humano aberto se, depois do último aviso de sistema (encerramento), houve transferência ou fala do atendente. */
function comHumano(lista: Mensagem[]): boolean {
  let ultimoSistema = -1;
  lista.forEach((m, i) => {
    if (m.papel === "system") ultimoSistema = i;
  });
  return lista
    .slice(ultimoSistema + 1)
    .some((m) => m.autor === "atendente" || (m.papel === "assistant" && /transferi sua conversa|acionei .{0,30}atendente|atendente humano/i.test(m.conteudo)));
}

let seq = 0;
const novoId = () => `m${Date.now().toString(36)}${(seq++).toString(36)}`;

function lerConversaSalva(): string | null {
  try {
    return localStorage.getItem(CHAVE_CONVERSA);
  } catch {
    return null;
  }
}
function salvarConversa(id: string | null) {
  try {
    if (id) localStorage.setItem(CHAVE_CONVERSA, id);
    else localStorage.removeItem(CHAVE_CONVERSA);
  } catch {
    /* ignora */
  }
}

export default function ChatPage() {
  const [conversaId, setConversaId] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<MsgView[]>([BOAS_VINDAS]);
  const [sugestoes, setSugestoes] = useState<string[]>(SUGESTOES_INICIAIS);
  const [status, setStatus] = useState<StatusConversa>("bot");
  const [texto, setTexto] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erroInicio, setErroInicio] = useState<string | null>(null);
  const [selecionada, setSelecionada] = useState<string | null>(null);
  const [painelAberto, setPainelAberto] = useState(false);

  const debugPorConteudo = useRef(new Map<string, DebugInfo | null>());
  const totalServidor = useRef(0);
  const jaTeveHumano = useRef(false);
  const fimRef = useRef<HTMLDivElement>(null);
  const entradaRef = useRef<HTMLTextAreaElement>(null);

  // Converte a lista do servidor em mensagens de tela, reaproveitando o debug já recebido.
  const reconstruir = useCallback((lista: Mensagem[]) => {
    totalServidor.current = lista.length;
    const views: MsgView[] = lista.map((m, i) => {
      const debug = m.papel === "assistant" ? debugPorConteudo.current.get(m.conteudo) : undefined;
      const autor: MsgView["autor"] =
        m.papel !== "assistant" ? undefined : m.autor ?? (debug !== undefined ? "bot" : jaTeveHumano.current ? "atendente" : "bot");
      return { id: `s${i}`, papel: m.papel, conteudo: m.conteudo, criado_em: m.criado_em, debug, autor };
    });
    setMsgs([BOAS_VINDAS, ...views]);
  }, []);

  const iniciar = useCallback(
    async (forcarNova = false) => {
      setErroInicio(null);
      debugPorConteudo.current.clear();
      jaTeveHumano.current = false;
      totalServidor.current = 0;
      setMsgs([BOAS_VINDAS]);
      setSugestoes(SUGESTOES_INICIAIS);
      setStatus("bot");
      setSelecionada(null);
      try {
        const salva = forcarNova ? null : lerConversaSalva();
        if (salva) {
          try {
            const lista = await api.mensagens(salva);
            setConversaId(salva);
            // A API não devolve o status da conversa: deduz "humano" pelo histórico.
            const humano = comHumano(lista);
            jaTeveHumano.current = humano;
            setStatus(humano ? "humano" : "bot");
            if (lista.length) setSugestoes([]);
            reconstruir(lista);
            return;
          } catch {
            /* conversa antiga não existe mais: cria outra */
          }
        }
        const { conversa_id } = await api.criarConversa();
        salvarConversa(conversa_id);
        setConversaId(conversa_id);
      } catch (e) {
        setConversaId(null);
        setErroInicio(errMsg(e));
      }
    },
    [reconstruir],
  );

  useEffect(() => {
    void iniciar();
  }, [iniciar]);

  // Enquanto um humano atende, busca novas mensagens periodicamente.
  useEffect(() => {
    if (status !== "humano" || !conversaId) return;
    const t = setInterval(async () => {
      try {
        const lista = await api.mensagens(conversaId);
        if (lista.length !== totalServidor.current) {
          reconstruir(lista);
          if (lista[lista.length - 1]?.papel === "system") setStatus("bot");
        }
      } catch {
        /* tenta de novo no próximo ciclo */
      }
    }, 3500);
    return () => clearInterval(t);
  }, [status, conversaId, reconstruir]);

  useEffect(() => {
    fimRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs, enviando]);

  async function enviar(conteudo: string) {
    const limpo = conteudo.trim();
    if (!limpo || enviando) return;
    if (!conversaId) {
      await iniciar(true);
      return;
    }
    setTexto("");
    setSugestoes([]);
    const idUser = novoId();
    setMsgs((m) => [...m, { id: idUser, papel: "user", conteudo: limpo, criado_em: new Date().toISOString() }]);
    setEnviando(true);
    try {
      const r = await api.enviarMensagem(conversaId, limpo);
      totalServidor.current += r.resposta ? 2 : 1;
      setStatus(r.status_conversa);
      if (r.status_conversa === "humano") jaTeveHumano.current = true;
      setSugestoes(r.sugestoes ?? []);
      if (r.resposta) {
        debugPorConteudo.current.set(r.resposta, r.debug);
        const id = novoId();
        setMsgs((m) => [...m, { id, papel: "assistant", autor: "bot", conteudo: r.resposta, debug: r.debug, criado_em: new Date().toISOString() }]);
        setSelecionada(id);
      } else if (r.debug) {
        // Sem resposta do bot (ex.: conversa com humano): o debug fica na mensagem do usuário
        setMsgs((m) => m.map((x) => (x.id === idUser ? { ...x, debug: r.debug } : x)));
        setSelecionada(idUser);
      }
    } catch (e) {
      setMsgs((m) => [...m, { id: novoId(), papel: "system", conteudo: errMsg(e), erro: true }]);
      setSugestoes([limpo]);
    } finally {
      setEnviando(false);
      entradaRef.current?.focus();
    }
  }

  function aoEnviar(e: FormEvent) {
    e.preventDefault();
    void enviar(texto);
  }

  function aoTeclar(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void enviar(texto);
    }
  }

  const comDebug = msgs.filter((m) => m.debug);
  const msgSel = msgs.find((m) => m.id === selecionada) ?? comDebug[comDebug.length - 1];
  const debugAtual = msgSel?.debug ?? null;

  return (
    <div className={`chat-layout ${painelAberto ? "painel-aberto" : ""}`}>
      <section className="chat">
        <div className="chat-topo">
          <div className="avatar-bot">
            <img src="/flow.svg" alt="" width={36} height={36} />
            <span className={`online ${status === "humano" ? "humano" : ""}`} />
          </div>
          <div className="chat-titulo">
            <strong>{status === "humano" ? "Atendimento Flow Gás" : "Flow Assistente"}</strong>
            <span>{status === "humano" ? "Você está falando com um atendente" : "Gás e água na sua porta · entrega em 30–60 min"}</span>
          </div>
          <div className="chat-acoes">
            <button type="button" className="btn btn-sec btn-peq so-mobile" onClick={() => setPainelAberto(true)}>
              Por dentro do bot
            </button>
            <button type="button" className="btn btn-sec btn-peq" onClick={() => void iniciar(true)} title="Começar uma nova conversa">
              Nova conversa
            </button>
          </div>
        </div>

        {status === "humano" && (
          <div className="faixa faixa-humano">
            <span className="ponto" /> Conversa transferida para um atendente humano. As respostas aparecem aqui automaticamente.
          </div>
        )}
        {erroInicio && (
          <div className="faixa faixa-erro">
            {erroInicio}{" "}
            <button type="button" className="link" onClick={() => void iniciar(true)}>
              Tentar de novo
            </button>
          </div>
        )}

        <div className="mensagens" role="log" aria-live="polite">
          {msgs.map((m) => {
            if (m.papel === "system")
              return (
                <div key={m.id} className={`msg-sistema ${m.erro ? "erro" : ""}`}>
                  {m.conteudo}
                </div>
              );
            const doBot = m.papel === "assistant";
            const ativo = msgSel?.id === m.id;
            return (
              <div key={m.id} className={`msg ${doBot ? "msg-bot" : "msg-user"} ${m.autor === "atendente" ? "msg-atendente" : ""}`}>
                <div className={`bolha ${ativo && m.debug ? "selecionada" : ""} ${doBot && ehUrgente(m.debug) ? "urgente" : ""}`}>
                  {doBot && m.autor === "atendente" && <span className="autor">Atendente Flow Gás</span>}
                  {doBot ? <Markdown texto={m.conteudo} /> : <p className="texto-user">{m.conteudo}</p>}
                </div>
                {doBot && (() => {
                  const pedido = pedidoDoDebug(m.debug, m.conteudo);
                  return pedido ? <PedidoCard p={pedido} /> : null;
                })()}
                <div className="msg-meta">
                  {hora(m.criado_em)}
                  {m.debug && (
                    <button
                      type="button"
                      className={`link-debug ${ativo ? "ativo" : ""}`}
                      onClick={() => {
                        setSelecionada(m.id);
                        setPainelAberto(true);
                      }}
                    >
                      ⚙ {rotuloIntencao(m.debug.intencao)} · {m.debug.latencia_ms} ms
                    </button>
                  )}
                </div>
              </div>
            );
          })}
          {enviando && (
            <div className="msg msg-bot">
              <div className="bolha digitando" aria-label="O assistente está digitando">
                <span />
                <span />
                <span />
              </div>
            </div>
          )}
          <div ref={fimRef} />
        </div>

        {sugestoes.length > 0 && !enviando && (
          <div className="chips" aria-label="Sugestões de resposta">
            {sugestoes.map((s) => (
              <button key={s} type="button" className="chip" onClick={() => void enviar(s)}>
                {s}
              </button>
            ))}
          </div>
        )}

        <form className="entrada" onSubmit={aoEnviar}>
          <textarea
            ref={entradaRef}
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            onKeyDown={aoTeclar}
            placeholder={status === "humano" ? "Escreva para o atendente…" : "Digite sua mensagem…"}
            rows={1}
            maxLength={2000}
            aria-label="Mensagem"
          />
          <button type="submit" className="btn btn-pri" disabled={!texto.trim() || enviando}>
            Enviar
          </button>
        </form>
      </section>

      <div className="debug-wrap">
        <div className="debug-fundo so-mobile" onClick={() => setPainelAberto(false)} />
        <DebugPanel debug={debugAtual} onFechar={() => setPainelAberto(false)} />
      </div>
    </div>
  );
}
