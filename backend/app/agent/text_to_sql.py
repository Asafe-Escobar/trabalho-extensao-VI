"""Passo 5 — Text-to-SQL controlado.

O LLM (ou, no mock, um conjunto de padrões) gera um SELECT; o `sqlglot` valida:
- exatamente 1 instrução, e ela é um SELECT (sem INSERT/UPDATE/DELETE/DDL/PRAGMA/ATTACH);
- só lê das views `vw_*` permitidas (nunca das tabelas com dados sensíveis);
- LIMIT ≤ 50 (acrescentado/reduzido automaticamente);
e executa numa conexão somente-leitura.
"""
from __future__ import annotations

import re

import sqlglot
from pydantic import BaseModel
from sqlglot import exp

from .. import llm
from .deps import conn_ro, normalizar

LIMITE_MAX = 50
VIEWS_TODAS = {"vw_catalogo", "vw_estoque", "vw_vendas_resumo", "vw_vendas_chatbot"}
VIEWS_PUBLICAS = {"vw_catalogo", "vw_estoque"}  # cliente no chat não vê faturamento

ESQUEMA = """Views disponíveis (SQLite):
- vw_catalogo(sku TEXT, nome TEXT, categoria TEXT, marca TEXT, preco REAL, garantia_meses INT)
- vw_estoque(sku TEXT, produto TEXT, filial TEXT, cidade TEXT, quantidade INT)
- vw_vendas_resumo(mes TEXT 'AAAA-MM', filial TEXT, qtd_pedidos INT, faturamento REAL)
- vw_vendas_chatbot(dia TEXT 'AAAA-MM-DD', status TEXT 'DRYRUN'|'ENVIADA'|'ERRO', qtd_vendas INT, total REAL)  -- vendas criadas pelo chatbot na RevGás
Categorias: 'Gás GLP', 'Vasilhames', 'Água', 'Acessórios', 'Outros'. Filiais: use LIKE '%Teresina%', '%Parnaíba%', '%São Luís%'."""

SYSTEM_SQL = f"""Você converte perguntas de gestores da Flow em UMA consulta SQLite somente-leitura.
{ESQUEMA}
Regras: apenas SELECT; use somente essas views; sempre inclua LIMIT (máx. {LIMITE_MAX});
nomes de colunas de saída em português; arredonde valores monetários com ROUND(x, 2).
Responda com o SQL e uma explicação curta."""


class SQLGerado(BaseModel):
    sql: str = ""
    explicacao: str = ""


class SQLInvalido(ValueError):
    pass


_FUNCOES_PROIBIDAS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer", "sqlite_version"}


def validar_sql(sql: str, views_permitidas: set[str] | None = None) -> str:
    views_permitidas = views_permitidas or VIEWS_TODAS
    bruto = sql.strip().rstrip(";").strip()
    if not bruto:
        raise SQLInvalido("SQL vazio.")
    if ";" in bruto:
        raise SQLInvalido("Somente uma instrução é permitida (';' múltiplo).")
    if re.search(r"--|/\*", bruto):
        raise SQLInvalido("Comentários não são permitidos.")
    try:
        arvores = sqlglot.parse(bruto, read="sqlite")
    except sqlglot.errors.ParseError as e:
        raise SQLInvalido(f"SQL inválido: {e}") from e
    if len(arvores) != 1 or arvores[0] is None:
        raise SQLInvalido("Somente uma instrução é permitida.")
    arvore = arvores[0]
    if not isinstance(arvore, (exp.Select, exp.Union)):
        raise SQLInvalido("Somente SELECT é permitido.")

    proibidos = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Command,
                 exp.Pragma, exp.Attach, exp.Detach, exp.Transaction, exp.Merge)
    for no in arvore.walk():
        if isinstance(no, proibidos):
            raise SQLInvalido(f"Operação não permitida: {type(no).__name__}.")
        if isinstance(no, exp.Anonymous) and str(no.name).lower() in _FUNCOES_PROIBIDAS:
            raise SQLInvalido(f"Função não permitida: {no.name}.")

    ctes = {c.alias_or_name.lower() for c in arvore.find_all(exp.CTE)}
    for t in arvore.find_all(exp.Table):
        nome = t.name.lower()
        if nome in ctes:
            continue
        if t.args.get("db") or nome not in views_permitidas:
            raise SQLInvalido(f"Acesso negado à tabela/view '{t.name}'. Permitidas: {', '.join(sorted(views_permitidas))}.")

    limite = arvore.args.get("limit")
    if limite is None:
        arvore = arvore.limit(LIMITE_MAX)
    else:
        try:
            valor = int(limite.expression.this)
        except (AttributeError, TypeError, ValueError):
            raise SQLInvalido("LIMIT deve ser um número inteiro.")
        if valor > LIMITE_MAX or valor < 0:
            arvore.set("limit", exp.Limit(expression=exp.Literal.number(LIMITE_MAX)))
    return arvore.sql(dialect="sqlite")


# ---------------------------------------------------------------------------
# Geração (mock por padrões)
# ---------------------------------------------------------------------------
def _filtro_periodo(n: str) -> str:
    m = re.search(r"\b(20\d{2})\b", n)
    return f" WHERE mes LIKE '{m.group(1)}-%'" if m else ""


def _filtro_filial(n: str, coluna: str = "filial") -> str:
    for chave, nome in (("teresina", "Teresina"), ("parnaiba", "Parnaíba"), ("sao luis", "São Luís")):
        if chave in n:
            return f"{coluna} LIKE '%{nome}%'"
    return ""


def gerar_sql_mock(pergunta: str) -> SQLGerado:
    n = normalizar(pergunta)
    per = _filtro_periodo(n)
    fil = _filtro_filial(n)

    def onde(*conds: str) -> str:
        cs = [c for c in conds if c]
        return (" WHERE " + " AND ".join(cs)) if cs else ""

    per_cond = per.replace(" WHERE ", "") if per else ""

    if re.search(r"(faturamento|vendas|vendeu|receita).*(por|cada) filial|filial.*(faturamento|vend)", n):
        return SQLGerado(
            sql=("SELECT filial, SUM(qtd_pedidos) AS qtd_pedidos, ROUND(SUM(faturamento), 2) AS faturamento "
                 f"FROM vw_vendas_resumo{onde(per_cond, fil)} GROUP BY filial ORDER BY faturamento DESC LIMIT 50"),
            explicacao="Soma do faturamento e dos pedidos por filial.")
    if re.search(r"(faturamento|vendas|receita).*(por |cada |mes a mes|mensal)|evolucao", n) or "por mes" in n:
        return SQLGerado(
            sql=("SELECT mes, SUM(qtd_pedidos) AS qtd_pedidos, ROUND(SUM(faturamento), 2) AS faturamento "
                 f"FROM vw_vendas_resumo{onde(per_cond, fil)} GROUP BY mes ORDER BY mes LIMIT 50"),
            explicacao="Faturamento mês a mês.")
    if re.search(r"(vendas|pedidos) (do|pelo|feitas pelo|criadas pelo) (chatbot|bot|assistente)|chatbot", n):
        return SQLGerado(
            sql="SELECT dia, status, qtd_vendas, total FROM vw_vendas_chatbot ORDER BY dia DESC LIMIT 50",
            explicacao="Vendas criadas pelo chatbot na RevGás, por dia e status.")
    if re.search(r"ticket medio", n):
        return SQLGerado(
            sql=("SELECT filial, ROUND(SUM(faturamento) / SUM(qtd_pedidos), 2) AS ticket_medio "
                 f"FROM vw_vendas_resumo{onde(per_cond, fil)} GROUP BY filial ORDER BY ticket_medio DESC LIMIT 50"),
            explicacao="Faturamento dividido pela quantidade de pedidos, por filial.")
    if re.search(r"faturamento|total vendido|receita|quantos pedidos", n):
        return SQLGerado(
            sql=("SELECT SUM(qtd_pedidos) AS qtd_pedidos, ROUND(SUM(faturamento), 2) AS faturamento "
                 f"FROM vw_vendas_resumo{onde(per_cond, fil)} LIMIT 50"),
            explicacao="Faturamento total.")
    if re.search(r"estoque (baixo|critico|acabando)|acabando|sem estoque|zerad", n):
        return SQLGerado(
            sql=("SELECT produto, filial, quantidade FROM vw_estoque"
                 f"{onde('quantidade < 5', _filtro_filial(n))} ORDER BY quantidade, produto LIMIT 50"),
            explicacao="Itens com menos de 5 unidades.")
    m_lim = re.search(r"\b(menos|abaixo) de (\d{1,4})\b", n)
    if "estoque" in n and m_lim:
        return SQLGerado(
            sql=("SELECT produto, filial, quantidade FROM vw_estoque"
                 f"{onde(f'quantidade < {int(m_lim.group(2))}', _filtro_filial(n))} ORDER BY quantidade, produto LIMIT 50"),
            explicacao=f"Itens com menos de {int(m_lim.group(2))} unidades em estoque.")
    if "estoque" in n:
        return SQLGerado(
            sql=("SELECT filial, SUM(quantidade) AS unidades, COUNT(DISTINCT sku) AS produtos FROM vw_estoque"
                 f"{onde(_filtro_filial(n))} GROUP BY filial ORDER BY unidades DESC LIMIT 50"),
            explicacao="Unidades em estoque por filial.")
    if re.search(r"mais caros?|maior(es)? preco", n):
        return SQLGerado(sql="SELECT nome, marca, categoria, preco FROM vw_catalogo ORDER BY preco DESC LIMIT 10",
                         explicacao="Produtos de maior preço.")
    if re.search(r"mais barat|menor(es)? preco", n):
        return SQLGerado(sql="SELECT nome, marca, categoria, preco FROM vw_catalogo ORDER BY preco ASC LIMIT 10",
                         explicacao="Produtos de menor preço.")
    if re.search(r"preco medio", n):
        grupo = "marca" if "marca" in n else "categoria"
        return SQLGerado(
            sql=f"SELECT {grupo}, ROUND(AVG(preco), 2) AS preco_medio, COUNT(*) AS produtos FROM vw_catalogo GROUP BY {grupo} ORDER BY preco_medio DESC LIMIT 50",
            explicacao=f"Preço médio por {grupo}.")
    if re.search(r"(produtos|itens).*(por|cada) (categoria|marca)|quantos produtos", n):
        grupo = "marca" if "marca" in n else "categoria"
        return SQLGerado(
            sql=f"SELECT {grupo}, COUNT(*) AS produtos FROM vw_catalogo GROUP BY {grupo} ORDER BY produtos DESC LIMIT 50",
            explicacao=f"Quantidade de produtos por {grupo}.")
    return SQLGerado(
        sql=("SELECT mes, filial, qtd_pedidos, faturamento FROM vw_vendas_resumo"
             f"{per} ORDER BY mes DESC, faturamento DESC LIMIT 20"),
        explicacao="Não reconheci um padrão específico; mostrando o resumo de vendas mais recente.")


def gerar_sql(pergunta: str) -> SQLGerado:
    return llm.structured(SYSTEM_SQL, pergunta, SQLGerado, max_tokens=800, mock=gerar_sql_mock)


def executar(pergunta: str, *, views_permitidas: set[str] | None = None) -> dict:
    """Gera, valida e executa. Retorna {sql, colunas, linhas, explicacao}.

    Levanta SQLInvalido se a consulta gerada violar alguma regra.
    """
    gerado = gerar_sql(pergunta)
    try:
        sql = validar_sql(gerado.sql, views_permitidas)
    except SQLInvalido:
        if llm.is_mock():
            raise
        # modo Claude: uma segunda chance com o gerador determinístico
        gerado = gerar_sql_mock(pergunta)
        sql = validar_sql(gerado.sql, views_permitidas)
    with conn_ro() as c:
        cur = c.execute(sql)
        colunas = [d[0] for d in cur.description or []]
        linhas = [dict(zip(colunas, r)) for r in cur.fetchall()]
    return {"sql": sql, "colunas": colunas, "linhas": linhas, "explicacao": gerado.explicacao}
