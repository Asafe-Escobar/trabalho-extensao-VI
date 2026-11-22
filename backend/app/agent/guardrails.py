"""Passos 1 e 6 — Guardrails de entrada e de saída (código determinístico, vale nos dois modos).

Entrada: SEGURANÇA (cheiro de gás / vazamento → instruções imediatas + handoff urgente),
prompt injection, pedido de dados de terceiros / dados confidenciais, PII (CPF/CNPJ, cartão).
Saída: bloqueio de desconto não autorizado, nunca citar `preco_minimo`, mascarar CPF/CNPJ.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .deps import normalizar
from .nlu import cnpj_valido, cpf_valido, so_digitos


@dataclass
class ResultadoGuardrail:
    eventos: list[dict] = field(default_factory=list)
    bloqueado: bool = False
    resposta: Optional[str] = None
    emergencia: bool = False

    def add(self, regra: str, acao: str, detalhe: str | None = None) -> None:
        ev = {"regra": regra, "acao": acao}
        if detalhe:
            ev["detalhe"] = detalhe
        self.eventos.append(ev)


# ---------------------------------------------------------------------------
# Máscaras
# ---------------------------------------------------------------------------
def mascarar_doc(doc: str | None) -> str | None:
    if not doc:
        return doc
    d = so_digitos(doc)
    if len(d) == 11:
        return f"***.{d[3:6]}.{d[6:9]}-**"
    if len(d) == 14:
        return f"**.{d[2:5]}.{d[5:8]}/{d[8:12]}-**"
    return "***"


_RE_DOC_TEXTO = re.compile(
    r"(?<![\d*])(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}|\d{3}\.?\d{3}\.?\d{3}-?\d{2})(?![\d*])"
)
_RE_CARTAO = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_RE_LINHA_DIGITAVEL = re.compile(r"\d{5}\.\d{5}\s\d{5}\.\d{6}\s\d{5}\.\d{6}\s\d\s\d{14}")


def _luhn(d: str) -> bool:
    total, alt = 0, False
    for ch in reversed(d):
        n = int(ch)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


def mascarar_texto(texto: str) -> str:
    """Mascara CPF/CNPJ e números de cartão (respostas e histórico).

    Linhas digitáveis de boleto são preservadas (o último bloco tem 14 dígitos e
    seria confundido com CNPJ).
    """
    protegidos: list[str] = []

    def _proteger(m: re.Match) -> str:
        protegidos.append(m.group(0))
        return f"§§{len(protegidos) - 1}§§"

    texto = _RE_LINHA_DIGITAVEL.sub(_proteger, texto)

    def _doc(m: re.Match) -> str:
        d = so_digitos(m.group(1))
        return mascarar_doc(d) if len(d) in (11, 14) else m.group(1)

    texto = _RE_DOC_TEXTO.sub(_doc, texto)

    def _cartao(m: re.Match) -> str:
        d = so_digitos(m.group(0))
        if 13 <= len(d) <= 19 and len(d) != 14 and _luhn(d):
            return "**** **** **** " + d[-4:]
        return m.group(0)

    texto = _RE_CARTAO.sub(_cartao, texto)
    return re.sub(r"§§(\d+)§§", lambda m: protegidos[int(m.group(1))], texto)


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
_VAZAMENTO = re.compile(
    r"\b(cheiro (forte )?de gas|cheirando (a )?gas|cheiro de (botijao|glp)|vazamento|vazando|vaza(ndo)? gas|"
    r"escapando gas|gas escapando|botijao (esta |ta )?vazando|ta saindo gas|saindo gas|"
    r"mangueira (furada|rachada|vazando)|registro vazando|pegou fogo|fogo no botijao|explos\w*|"
    r"chiand\w*|chiado|assobi\w*)\b"  # chiado/assobio no botijão = gás escapando: tratar como vazamento
)
# Sinal de ALERTA (sem cheiro/vazamento declarado): responde com RAG + aviso de segurança, sem bloquear
_ALERTA_SEGURANCA = re.compile(r"\b(barulho no (botijao|regulador)|regulador (gelad|congelad)\w*)\b")
AVISO_SEGURANCA = ("🛟 **Por segurança:** se sentir **cheiro de gás**, feche o registro, abra as janelas, não acenda luzes "
                   "e saia do local — Bombeiros **193**.")

RESP_VAZAMENTO = (
    "⚠️ **ATENÇÃO — possível vazamento de gás. Faça isto AGORA:**\n\n"
    "1. **Não acenda** luzes, fósforos ou isqueiros e **não ligue/desligue** aparelhos elétricos ou interruptores.\n"
    "2. **Abra portas e janelas** para ventilar o ambiente.\n"
    "3. **Feche o registro** do gás (ou o regulador do botijão), se for seguro.\n"
    "4. **Saia do local** com todas as pessoas e animais.\n"
    "5. De fora de casa, ligue para os **Bombeiros: 193**.\n\n"
    "Não use o celular dentro do ambiente com cheiro de gás. Já acionei **com urgência** um atendente da Flow "
    "para te ajudar (protocolo **#{protocolo}**)."
)

_INJECTION = [
    r"ignor\w* (todas |as |suas |tuas |os |seus )*(instruc\w*|regras|orientac\w*|diretrizes|comandos|prompt)",
    r"esque\w* (todas |as |suas |os |seus )*(instruc\w*|regras|orientac\w*|diretrizes)",
    r"desconsider\w* (todas |as |suas )*(instruc\w*|regras)",
    r"(mostr|revel|exib|imprim|repit|diga|me (de|passe|mostre))\w* (o |a |seu |sua |as |os |suas |seus )*(prompt|instruc\w* (do sistema|iniciais|internas|originais)|system prompt|regras internas)",
    r"\bsystem prompt\b", r"\bprompt (do|de) sistema\b", r"\bjailbreak\b", r"\bmodo (desenvolvedor|developer|dan|deus|admin)\b",
    r"\bvoce agora e\b", r"\ba partir de agora voce\b", r"\bfinja (ser|que)\b", r"\baja como\b", r"\bdo anything now\b",
    r"\bignore (previous|all|your) (instructions|rules)\b", r"\bsudo\b", r"</?system>", r"\[\s*system\s*\]",
    r"\b(drop|delete|truncate|update|insert)\s+(table|from|into)\b", r";\s*--", r"\bapi[_ ]?key\b", r"\bchave da (api|revgas)\b",
]
_TERCEIROS = [
    r"\b(cpf|cnpj|rg|endereco|telefone|celular|e-?mail|dados|nome|documento)\b.{0,30}\b(d[oa]s? (outr[oa]s? )?(cliente|clientes|comprador|titular|pessoa|usuario|vizinh[oa])|de (outr[oa]|terceir|alguem)\w*|d[oa] (dono|dona))",
    r"\b(quem (comprou|fez|e o dono|e a dona)|de quem e o pedido)\b",
    r"\b(lista|listar|todos os|todas as)\b.{0,20}\b(clientes|cpfs|cnpjs|e-?mails|telefones|enderecos)\b",
]
_CONFIDENCIAL = [
    r"\bpreco[_ ]?minimo\b", r"\b(menor|ultimo) preco (que voces|possivel|que da)\b", r"\bpiso (de|do) (desconto|preco)\b",
    r"\bmargem( de lucro)?\b", r"\bpreco de custo\b", r"\bquanto (voces|vcs) pagaram\b",
]

RESP_INJECTION = (
    "Não posso mudar minhas instruções nem revelar configurações internas. 🙂\n\n"
    "Posso te ajudar a **pedir gás ou água**, ver **preços**, **acompanhar um pedido** ou tirar dúvidas. O que você precisa?"
)
RESP_TERCEIROS = (
    "Por segurança e em respeito à **LGPD**, não informo dados pessoais de outros clientes "
    "(CPF, endereço, telefone, quem fez um pedido etc.).\n\n"
    "Se o pedido for seu, me informe o **seu CPF/CNPJ** que eu consulto para você."
)
RESP_CONFIDENCIAL = (
    "Essa informação é interna da Flow e não posso compartilhar. Posso te passar o **preço de tabela** "
    "e, se quiser negociar condições, te encaminho para um vendedor."
)


def verificar_entrada(texto: str) -> ResultadoGuardrail:
    r = ResultadoGuardrail()
    n = normalizar(texto)

    # Segurança da vida vem antes de tudo
    if _VAZAMENTO.search(n):
        r.add("seguranca_vazamento_gas", "instrucoes_emergencia+handoff_urgente")
        r.bloqueado, r.emergencia, r.resposta = True, True, RESP_VAZAMENTO
        return r

    if _ALERTA_SEGURANCA.search(n):
        r.add("seguranca_alerta", "orientacao+rag")

    if any(re.search(p, n) for p in _INJECTION):
        r.add("prompt_injection", "bloqueado")
        r.bloqueado, r.resposta = True, RESP_INJECTION
        return r

    if any(re.search(p, n) for p in _TERCEIROS):
        r.add("dados_de_terceiros", "bloqueado")
        r.bloqueado, r.resposta = True, RESP_TERCEIROS
        return r

    if any(re.search(p, n) for p in _CONFIDENCIAL):
        r.add("dado_confidencial", "bloqueado", "preco_minimo/margem")
        r.bloqueado, r.resposta = True, RESP_CONFIDENCIAL
        return r

    for m in _RE_CARTAO.finditer(texto):
        d = so_digitos(m.group(0))
        if 13 <= len(d) <= 19 and len(d) not in (11, 14) and _luhn(d):
            r.add("pii_cartao", "mascarado", "número de cartão removido do histórico")
            break

    for m in _RE_DOC_TEXTO.finditer(re.sub(r"FL-\d{4}-\d{1,5}", " ", texto, flags=re.I)):
        d = so_digitos(m.group(1))
        if len(d) == 11:
            r.add("pii_cpf", "mascarado" if cpf_valido(d) else "invalido")
        elif len(d) == 14:
            r.add("pii_cnpj", "mascarado" if cnpj_valido(d) else "invalido")
    return r


# ---------------------------------------------------------------------------
# Saída
# ---------------------------------------------------------------------------
_RE_DESCONTO_CONCEDIDO = re.compile(
    r"(te dou|vou (te )?dar|posso (te )?dar|consigo (te )?dar|concedo|aplico|aplicar|liberei|liberar|fica com|fechado com|ofereco|oferecer)"
    r"[^.\n]{0,40}\b\d{1,2}([.,]\d+)? ?%",
    re.I,
)
_RE_PRECO_MIN = re.compile(r"[^.\n]*\bpre[cç]o[_ ]m[ií]nimo\b[^.\n]*[.\n]?", re.I)

RESP_DESCONTO = (
    "Eu não tenho autorização para conceder descontos. Pela nossa política comercial, "
    "descontos de até **5%** são avaliados por um **vendedor** e acima disso pelo **gerente**."
)


def formatar_brl(v: float) -> str:
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def verificar_saida(texto: str, *, precos_minimos: list[float] | None = None) -> tuple[str, list[dict]]:
    eventos: list[dict] = []
    novo = texto

    if _RE_DESCONTO_CONCEDIDO.search(normalizar(novo)):
        novo = RESP_DESCONTO + "\n\nPosso te encaminhar para um vendedor?"
        eventos.append({"regra": "desconto_nao_autorizado", "acao": "bloqueado"})

    if _RE_PRECO_MIN.search(novo):
        novo = _RE_PRECO_MIN.sub("", novo).strip() or RESP_CONFIDENCIAL
        eventos.append({"regra": "preco_minimo_confidencial", "acao": "removido"})
    # valores de piso só são checados quando aparecem rotulados (evita apagar preço legítimo igual ao piso de outro item)
    for pm in precos_minimos or []:
        alvo = re.compile(rf"(piso|m[ií]nimo|abaixo de|at[eé])[^.\n]{{0,20}}{re.escape(formatar_brl(pm))}", re.I)
        if alvo.search(novo):
            novo = alvo.sub("[confidencial]", novo)
            eventos.append({"regra": "preco_minimo_confidencial", "acao": "removido"})

    mascarado = mascarar_texto(novo)
    if mascarado != novo:
        eventos.append({"regra": "mascarar_cpf_cnpj", "acao": "mascarado"})
    return mascarado, eventos
