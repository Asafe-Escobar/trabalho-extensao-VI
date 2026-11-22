// Renderizador de markdown mínimo e seguro (gera elementos React, sem innerHTML).
// Suporta: parágrafos, quebras de linha, **negrito**, *itálico*, `código`, links http(s),
// títulos (#), listas (- / 1.), citações (>), blocos ``` e tabelas no formato GFM.
import { Fragment, type ReactNode } from "react";

const RE_INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\s][^*\n]*\*)|(_[^_\s][^_\n]*_(?![A-Za-z0-9]))|(\[[^\]\n]+\]\([^)\s]+\))/g;

function inline(texto: string, chave: string): ReactNode[] {
  const out: ReactNode[] = [];
  let ultimo = 0;
  let i = 0;
  RE_INLINE.lastIndex = 0;
  const re = new RegExp(RE_INLINE.source, "g");
  let m: RegExpExecArray | null;
  while ((m = re.exec(texto))) {
    // "_" só vale como itálico no início de palavra (evita quebrar snake_case)
    if (m[4] && m.index > 0 && /[A-Za-z0-9]/.test(texto[m.index - 1])) continue;
    if (m.index > ultimo) out.push(texto.slice(ultimo, m.index));
    const tok = m[0];
    const k = `${chave}.${i++}`;
    if (m[1]) out.push(<code key={k}>{tok.slice(1, -1)}</code>);
    else if (m[2]) out.push(<strong key={k}>{inline(tok.slice(2, -2), k)}</strong>);
    else if (m[3] || m[4]) out.push(<em key={k}>{inline(tok.slice(1, -1), k)}</em>);
    else {
      const mm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok);
      if (mm && /^(https?:|mailto:|tel:)/i.test(mm[2])) {
        out.push(
          <a key={k} href={mm[2]} target="_blank" rel="noopener noreferrer">
            {mm[1]}
          </a>,
        );
      } else out.push(mm ? mm[1] : tok);
    }
    ultimo = m.index + tok.length;
  }
  if (ultimo < texto.length) out.push(texto.slice(ultimo));
  return out;
}

function comQuebras(linhas: string[], chave: string): ReactNode[] {
  return linhas.map((l, i) => (
    <Fragment key={`${chave}-${i}`}>
      {i > 0 && <br />}
      {inline(l, `${chave}-${i}`)}
    </Fragment>
  ));
}

const celulas = (linha: string) =>
  linha
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());

export function Markdown({ texto, className }: { texto: string; className?: string }) {
  const linhas = texto.replace(/\r\n/g, "\n").split("\n");
  const blocos: ReactNode[] = [];
  let i = 0;
  let b = 0;
  const RE_UL = /^\s*[-*•]\s+/;
  const RE_OL = /^\s*\d+[.)]\s+/;

  while (i < linhas.length) {
    const l = linhas[i];
    const k = `b${b++}`;

    if (!l.trim()) {
      i++;
      continue;
    }

    if (l.trim().startsWith("```")) {
      const corpo: string[] = [];
      i++;
      while (i < linhas.length && !linhas[i].trim().startsWith("```")) corpo.push(linhas[i++]);
      i++;
      blocos.push(
        <pre key={k}>
          <code>{corpo.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    const h = /^(#{1,4})\s+(.*)$/.exec(l);
    if (h) {
      blocos.push(
        <p key={k} className={`md-h md-h${h[1].length}`}>
          {inline(h[2], k)}
        </p>,
      );
      i++;
      continue;
    }

    if (/^\s*(---+|\*\*\*+)\s*$/.test(l)) {
      blocos.push(<hr key={k} />);
      i++;
      continue;
    }

    if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < linhas.length && /^\s*\|?\s*:?-{2,}/.test(linhas[i + 1])) {
      const cab = celulas(l);
      i += 2;
      const corpo: string[][] = [];
      while (i < linhas.length && /^\s*\|.*\|\s*$/.test(linhas[i])) corpo.push(celulas(linhas[i++]));
      blocos.push(
        <div key={k} className="md-tabela">
          <table>
            <thead>
              <tr>
                {cab.map((c, j) => (
                  <th key={j}>{inline(c, `${k}h${j}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {corpo.map((r, ri) => (
                <tr key={ri}>
                  {r.map((c, j) => (
                    <td key={j}>{inline(c, `${k}r${ri}c${j}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    if (RE_UL.test(l) || RE_OL.test(l)) {
      const ordenada = RE_OL.test(l);
      const re = ordenada ? RE_OL : RE_UL;
      const itens: string[] = [];
      while (i < linhas.length && re.test(linhas[i])) itens.push(linhas[i++].replace(re, ""));
      const filhos = itens.map((it, j) => <li key={j}>{inline(it, `${k}i${j}`)}</li>);
      blocos.push(ordenada ? <ol key={k}>{filhos}</ol> : <ul key={k}>{filhos}</ul>);
      continue;
    }

    if (/^\s*>/.test(l)) {
      const cit: string[] = [];
      while (i < linhas.length && /^\s*>/.test(linhas[i])) cit.push(linhas[i++].replace(/^\s*>\s?/, ""));
      blocos.push(<blockquote key={k}>{comQuebras(cit, k)}</blockquote>);
      continue;
    }

    const par: string[] = [];
    while (
      i < linhas.length &&
      linhas[i].trim() &&
      !linhas[i].trim().startsWith("```") &&
      !/^(#{1,4})\s/.test(linhas[i]) &&
      !RE_UL.test(linhas[i]) &&
      !RE_OL.test(linhas[i]) &&
      !/^\s*>/.test(linhas[i]) &&
      !/^\s*\|.*\|\s*$/.test(linhas[i])
    )
      par.push(linhas[i++]);
    if (par.length === 0) {
      // linha que parecia tabela/lista mas não fechou o padrão: trata como texto
      par.push(linhas[i++]);
    }
    blocos.push(<p key={k}>{comQuebras(par, k)}</p>);
  }

  return <div className={`md ${className ?? ""}`}>{blocos}</div>;
}
