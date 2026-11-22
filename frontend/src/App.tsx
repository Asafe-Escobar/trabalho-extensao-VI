import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, USE_MOCK, type RevgasStatus } from "./api";
import ChatPage from "./pages/ChatPage";
import AtendentePage from "./pages/AtendentePage";
import GestorPage from "./pages/GestorPage";

type Saude = { estado: "carregando" } | { estado: "ok"; modo: string } | { estado: "offline" };

function StatusServidor() {
  const [saude, setSaude] = useState<Saude>({ estado: "carregando" });

  useEffect(() => {
    let vivo = true;
    const checar = () =>
      api
        .health()
        .then((h) => vivo && setSaude({ estado: "ok", modo: h.modo_llm }))
        .catch(() => vivo && setSaude({ estado: "offline" }));
    checar();
    const t = setInterval(checar, 30000);
    return () => {
      vivo = false;
      clearInterval(t);
    };
  }, []);

  if (saude.estado === "carregando") return <span className="pill pill-neutro">verificando…</span>;
  if (saude.estado === "offline")
    return (
      <span className="pill pill-erro" title="Backend fora do ar. Rode o backend ou use npm run dev:mock.">
        <span className="ponto" /> API offline
      </span>
    );
  const rotulo = USE_MOCK ? "Demo local (mock)" : saude.modo === "anthropic" ? "Claude conectado" : "LLM em modo mock";
  return (
    <span className={`pill ${saude.modo === "anthropic" && !USE_MOCK ? "pill-ok" : "pill-aviso"}`} title={`modo_llm: ${saude.modo}`}>
      <span className="ponto" /> {rotulo}
    </span>
  );
}

function StatusRevgas() {
  const [st, setSt] = useState<RevgasStatus | null>(null);
  useEffect(() => {
    api.revgasStatus().then(setSt).catch(() => setSt(null));
  }, []);
  if (!st) return null;
  const rot = st.modo === "real" ? "RevGás: REAL" : st.modo === "offline" ? "RevGás: offline" : "RevGás: dry-run";
  return (
    <span className={`pill ${st.modo === "real" ? "pill-erro" : "pill-neutro"} pill-revgas`} title={st.modo === "real" ? "Vendas confirmadas são gravadas na RevGás" : "Vendas simuladas: nenhum POST real é feito"}>
      {rot}
    </span>
  );
}

export default function App() {
  return (
    <div className="app">
      <header className="topo">
        <div className="marca">
          <img src="/flow.svg" alt="" width={30} height={30} />
          <div>
            <strong>Flow Gás</strong> <span>Assistente</span>
          </div>
        </div>
        <nav className="abas" aria-label="Telas">
          <NavLink to="/" end>
            Chat do cliente
          </NavLink>
          <NavLink to="/atendente">Atendente</NavLink>
          <NavLink to="/gestor">Gestor</NavLink>
        </nav>
        <div className="topo-status">
          <StatusRevgas />
          <StatusServidor />
        </div>
      </header>
      <main className="conteudo">
        <Routes>
          <Route path="/" element={<ChatPage />} />
          <Route path="/atendente" element={<AtendentePage />} />
          <Route path="/gestor" element={<GestorPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
