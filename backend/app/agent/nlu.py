"""Passo 3 — Intent Classification + Entity Extraction (domínio: revenda de gás GLP e água).

Modo Claude: 1 chamada `llm.structured` com o schema `NLUResult`.
Modo mock: regex + palavras-chave (determinístico).
Também extrai os dados do FLUXO DE VENDA (itens, troca de botijão, endereço, pagamento, troco),
sempre por regex — formatos fixos são mais confiáveis assim, nos dois modos.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .. import llm
from .deps import normalizar

Intencao = Literal[
    "fazer_pedido", "consultar_preco", "consultar_estoque", "consultar_pedido", "segunda_via_boleto",
    "troca_devolucao", "garantia", "duvida_politica", "recomendacao_produto", "pedir_desconto",
    "falar_atendente", "saudacao", "relatorio_interno", "outro",
]
INTENCOES: tuple[str, ...] = Intencao.__args__  # type: ignore[attr-defined]


class Entidades(BaseModel):
    cpf_cnpj: Optional[str] = Field(None, description="CPF (11 dígitos) ou CNPJ (14 dígitos), só dígitos")
    numero_pedido: Optional[str] = Field(None, description="Formato FL-AAAA-NNNNN")
    produto: Optional[str] = Field(None, description="Produto citado (ex.: botijão P13, galão de água, regulador)")
    sku: Optional[str] = None
    filial: Optional[str] = Field(None, description="Teresina, Parnaíba ou São Luís")
    periodo: Optional[str] = Field(None, description="Ex.: 2026, 2026-03")
    status: Optional[str] = None
    quantidade: Optional[int] = None


class NLUResult(BaseModel):
    intencao: Intencao = "outro"
    confianca: float = 0.5
    entidades: Entidades = Field(default_factory=Entidades)


# ---------------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------------
RE_PEDIDO = re.compile(r"\bFL[\s\-]?(\d{4})[\s\-]?(\d{1,5})\b", re.I)
RE_CNPJ = re.compile(r"(?<!\d)(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})(?!\d)")
RE_CPF = re.compile(r"(?<!\d)(\d{3}\.?\d{3}\.?\d{3}-?\d{2})(?!\d)")


def so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def cpf_valido(cpf: str) -> bool:
    d = so_digitos(cpf)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        s = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != int(d[n]):
            return False
    return True


def cnpj_valido(cnpj: str) -> bool:
    d = so_digitos(cnpj)
    if len(d) != 14 or d == d[0] * 14:
        return False
    for n, pesos in ((12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]), (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])):
        s = sum(int(d[i]) * pesos[i] for i in range(n))
        dv = 0 if s % 11 < 2 else 11 - s % 11
        if dv != int(d[n]):
            return False
    return True


FILIAIS = {"teresina": "Teresina", "parnaiba": "Parnaíba", "sao luis": "São Luís", "slz": "São Luís", "the": "Teresina"}
UF_FILIAL = {"Teresina": "PI", "Parnaíba": "PI", "São Luís": "MA"}
STATUS = {"aguardando pagamento": "aguardando_pagamento", "pago": "pago", "separacao": "separacao",
          "enviado": "enviado", "entregue": "entregue", "cancelado": "cancelado"}
MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
         "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
NUMEROS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
           "oito": 8, "nove": 9, "dez": 10, "meia duzia": 6, "uma duzia": 12, "duzia": 12}

# Termos que nomeiam produtos da revenda
RE_PRODUTO = re.compile(
    r"\b(botij\w*|gas|glp|p\s?-?(13|20|45)|\d{1,2} ?kg|vasilhame\w*|casco\w*|gal(ao|oes)|garraf(ao|oes)|agua\w*"
    r"|regulador\w*|mangueira\w*|kit|carvao|gelo|vela\w*|adaptador\w*|registro)\b"
)


def _limpar(n: str) -> str:
    return RE_PEDIDO.sub(" ", n)


def extrair_entidades(texto: str) -> Entidades:
    e = Entidades()
    n = normalizar(texto)

    m = RE_PEDIDO.search(texto)
    if m:
        e.numero_pedido = f"FL-{m.group(1)}-{int(m.group(2)):05d}"

    sem_pedido = RE_PEDIDO.sub(" ", texto)
    m = RE_CNPJ.search(sem_pedido)
    if m and len(so_digitos(m.group(1))) == 14:
        e.cpf_cnpj = so_digitos(m.group(1))
    else:
        m = RE_CPF.search(sem_pedido)
        if m and len(so_digitos(m.group(1))) == 11:
            e.cpf_cnpj = so_digitos(m.group(1))

    for chave, nome in FILIAIS.items():
        if re.search(rf"\b{chave}\b", n):
            e.filial = nome
            break
    for chave, st in STATUS.items():
        if re.search(rf"\b{chave}s?\b", n) and "pedido" in n:
            e.status = st
            break

    n2 = _limpar(n)
    m = re.search(r"\b(20[23]\d)\b", n2)
    mes = next((v for k, v in MESES.items() if re.search(rf"\b{k}\b", n2)), None)
    if mes and m:
        e.periodo = f"{m.group(1)}-{mes:02d}"
    elif m:
        e.periodo = m.group(1)

    itens = extrair_itens(texto)
    if itens:
        e.produto = itens[0]["termo"]
        e.quantidade = itens[0]["qtd"]
    elif (mp := RE_PRODUTO.search(n)):
        e.produto = n[mp.start():mp.end() + 12].strip()
    return e


# ---------------------------------------------------------------------------
# Fluxo de venda: itens, troca, endereço, pagamento, troco, confirmação
# ---------------------------------------------------------------------------
_RE_QTD = r"(\d{1,2}|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez|meia duzia|uma duzia)"


def _qtd(token: str | None) -> int:
    if not token:
        return 1
    token = token.strip()
    return int(token) if token.isdigit() else NUMEROS.get(token, 1)


def extrair_itens(texto: str) -> list[dict]:
    """'Quero 2 botijões de 13 e um galão de água' -> [{'termo':'botijoes de 13','qtd':2}, {'termo':'galao de agua','qtd':1}]"""
    n = _limpar(normalizar(texto))
    n = re.sub(r"\b(\d{1,2})\s*(kg|quilos?)\b", r"\1kg", n)
    partes = re.split(r",|\s+\+\s+|\s+e\s+(?=(?:\d|um|uma|dois|duas|tres|quatro|cinco|mais|tambem|o |a |os |as ))|\s+mais\s+|\s+tambem\s+", n)
    itens = []
    for parte in partes:
        mp = RE_PRODUTO.search(parte)
        if not mp:
            continue
        # quantidade imediatamente antes do produto ("2 botijões", "um galão")
        antes = parte[: mp.start()]
        mq = re.search(rf"{_RE_QTD}\s+(?:\w+\s+)?$", antes)
        if mq and re.search(r"\b(por|a|em|r\$)\s*$", antes[: mq.start()]):
            mq = None  # "faz por 90 o botijão": 90 é preço, não quantidade
        termo = parte[mp.start():].strip()
        termo = re.split(r"\b(para|pra|no|na|em|com|por|que|entregue|aqui)\b", termo)[0].strip() or mp.group(0)
        if re.fullmatch(r"(gas|agua)", termo) and re.search(r"cheiro|vaz", parte):
            continue
        # "botijão de 13" — o número que vem depois NÃO é quantidade
        itens.append({"termo": termo, "qtd": _qtd(mq.group(1) if mq else None)})
    return itens


RE_SIM = re.compile(r"^\s*(sim|s|isso|isso mesmo|pode|pode sim|pode mandar|pode enviar|manda|mande|confirmo|confirmado|confirma|"
                    r"ok|okay|beleza|blz|certo|correto|fechado|fechou|positivo|claro|com certeza|perfeito|bora|uhum|aham|ta certo|esta certo)\b")
RE_NAO = re.compile(r"^\s*(nao|n|negativo|nem|nada|cancela|cancelar|desisto|errado|ainda nao)\b")


def resposta_sim_nao(texto: str) -> Optional[bool]:
    n = normalizar(texto).strip(" !.?")
    if RE_NAO.search(n):
        return False
    if RE_SIM.search(n):
        return True
    return None


def extrair_troca(texto: str) -> Optional[bool]:
    """True = cliente TEM botijão vazio para trocar; False = precisa comprar o vasilhame."""
    n = normalizar(texto)
    if re.search(r"\b(nao tenho|sem (o )?(botijao|vasilhame|casco)|preciso do (botijao|vasilhame|casco)|com (o )?(botijao|vasilhame|casco)|"
                 r"botijao novo|primeiro botijao|nao tem botijao|comprar o (botijao|vasilhame|casco)|completo)\b", n):
        return False
    if re.search(r"\b(tenho (o |os |um |dois |uns )?(botij\w*|vasilhame\w*|casco\w*|vazio\w*)|tenho sim|e troca|so (o )?gas|so a recarga|recarga|"
                 r"troca do botijao|trocar o botijao|tenho o vazio|tenho vazio|ja tenho)\b", n):
        return True
    return None


def extrair_pagamento(texto: str) -> Optional[str]:
    n = normalizar(texto)
    if re.search(r"\bpix\b", n):
        return "PIX"
    if re.search(r"\b(debito)\b", n):
        return "CARTAO_DE_DEBITO"
    if re.search(r"\b(credito)\b", n):
        return "CARTAO_DE_CREDITO"
    if re.search(r"\b(cartao|maquininha|maquina)\b", n):
        return "CARTAO"  # ambíguo: perguntar débito ou crédito
    if re.search(r"\b(dinheiro|especie|cash|em maos|na entrega em dinheiro)\b", n):
        return "MONEY"
    return None


def extrair_troco(texto: str) -> Optional[float]:
    """Valor para troco; 0.0 = não precisa de troco; None = não falou."""
    n = normalizar(texto)
    if re.search(r"\b(sem troco|nao precisa(r)? (de )?troco|nao preciso de troco|valor (exato|certo|trocado)|dinheiro trocado|tenho trocado|nao precisa)\b", n):
        return 0.0
    m = re.search(r"(?:troco\s+(?:para|pra|de)\s*|nota de\s*|tenho\s*|r\$\s*)(\d{2,4})(?:[.,]\d{2})?", n)
    if m:
        return float(m.group(1))
    m = re.fullmatch(r"\s*(?:r\$\s*)?(\d{2,4})(?:[.,]\d{2})?\s*(reais)?\s*", n)
    if m:
        return float(m.group(1))
    return None


_TIPOS_LOGRADOURO = r"(rua|r\.|avenida|av\.?|travessa|tv\.?|alameda|al\.?|quadra|qd\.?|conjunto|cj\.?|estrada|rodovia|praca|residencial|condominio)"


def extrair_endereco(texto: str) -> dict:
    """'Rua Augusto Freire, 2003, Centro' -> {rua, numero, bairro}. Só devolve o que achar."""
    t = re.sub(r"\s+", " ", texto.strip())
    n = normalizar(t)
    out: dict = {}
    m = re.search(rf"\b{_TIPOS_LOGRADOURO}\s+([^,\d]+?)\s*(?:,|\s)\s*(?:n[ºo°.]?\s*|numero\s*)?(\d{{1,5}}[a-z]?|s/?n)\b", n)
    if m:
        ini, fim = m.span(0)
        # recupera do texto original (com acentos e maiúsculas) a mesma faixa
        orig = t[ini:fim]
        mo = re.match(r"(.+?)\s*(?:,|\s)\s*(?:n[ºo°.]?\s*|n[úu]mero\s*)?(\d{1,5}[a-zA-Z]?|[sS]/?[nN])$", orig)
        rua = (mo.group(1) if mo else orig).strip(" ,")
        out["rua"] = rua[0].upper() + rua[1:] if rua else rua
        out["numero"] = (mo.group(2) if mo else m.group(3)).upper().replace("SN", "S/N")
        resto = t[fim:]
        mb = re.search(r"(?:,|-|\s)\s*(?:bairro\s+)?([A-Za-zÀ-ú][A-Za-zÀ-ú0-9 .'-]{2,40}?)\s*(?:,|$|-|\.|\s+(?:em|na cidade de)\s)", resto + ",")
        if mb:
            bairro = mb.group(1).strip(" .-")
            bairro_n = normalizar(bairro)
            if bairro_n and not re.match(r"^(apto|apartamento|casa|bloco|perto|proximo|ao lado|referencia)\b", bairro_n) \
                    and bairro_n not in FILIAIS:
                out["bairro"] = bairro
    else:
        mb = re.search(r"\bbairro\s+([A-Za-zÀ-ú][A-Za-zÀ-ú0-9 .'-]{2,40}?)\s*(?:,|$|\.)", t + ",", re.I)
        if mb:
            out["bairro"] = mb.group(1).strip()
    for chave, nome in FILIAIS.items():
        if re.search(rf"\b{chave}\b", n):
            out["cidade"], out["uf"] = nome, UF_FILIAL[nome]
            break
    return out


# ---------------------------------------------------------------------------
# Classificação de intenção por regras (mock)
# ---------------------------------------------------------------------------
# Verbo de COMPRA. "preciso" sozinho NÃO é compra ("Preciso trocar o regulador?" é dúvida); "preciso de 2" é.
_PEDIR = (r"(quero|queria|gostaria de|manda|mande|pede|pedir|me (traz|traga|ve|manda|envia|arruma)|traz|traga|encomendar|"
          r"compra|comprar|vou querer|vou levar|preciso de (\d+|um|uma|dois|duas|tres)|entrega(r)? (um|uma|\d))")
_COMPRA_FORTE = re.compile(rf"\b{_PEDIR}\b")
_PERGUNTA = re.compile(r"\?|\b(preciso trocar|devo trocar|tem validade|qual a validade|quando (devo )?trocar|como (eu )?(troco|instalo|faco|funciona)|"
                       r"o que (eu )?faco|vale a pena|e normal|pode|posso|serve|combina)\b")
_DESCONTO = (r"\b(desconto|abatimento|baixa(r)? o pre[cç]o|abaix\w*|faz(er)? por menos|(me )?faz(er)? (por|a|em) (r\$ ?)?\d+|"
             r"deixa (por|a|em) (r\$ ?)?\d+|sai (por|a) (r\$ ?)?\d+ (pra|para) mim|fecha (por|em) (r\$ ?)?\d+|preco melhor|melhor preco|"
             r"\d+ ?%|mais barat\w*|chorinho|precinho|da (uma|um) (forca|desconto)|cupom)\b")

REGRAS: list[tuple[str, float, str]] = [
    ("falar_atendente", 0.95, r"\b(atendente|humano|pessoa de verdade|falar com (alguem|uma pessoa|o gerente|um vendedor|vendedor|gerente)|ser atendid[oa]|operador)\b"),
    ("relatorio_interno", 0.9, r"\b(faturamento|relatorio|ticket medio|vendas (por|de|do|da|em)|quantos pedidos|total vendido|ranking)\b"),
    ("pedir_desconto", 0.93, _DESCONTO),
    ("segunda_via_boleto", 0.93, r"\b(boleto|2a via|2ª via|segunda via|linha digitavel|codigo de barras|fatura em aberto)\b"),
    ("recomendacao_produto", 0.88, r"\b(contrato( mensal)?|orcamento|cotacao|proposta|fornecimento|para (o |a )?(meu|minha|nosso|nossa) (restaurante|empresa|lanchonete|condominio|padaria|hotel|comercio))\b"),
    ("fazer_pedido", 0.93, rf"\b(fazer (um |o )?pedido|novo pedido|{_PEDIR}\b.{{0,40}}\b(botij\w*|gas|glp|p\s?-?(13|20|45)|gal(ao|oes)|agua|regulador\w*|mangueira\w*|vasilhame\w*|carvao|gelo|kit)|trocar (o |meu )?(botijao|gas)|troca de (botijao|gas)|acabou (o|meu) gas|gas acabou|sem gas)"),
    ("garantia", 0.9, r"\b(garantia|defeito|validade|vencid\w*|vence|vencimento|(preciso|devo|tenho que|quando) trocar (o |a )?(regulador|mangueira)|faz \w+ anos|anos de uso|parou de funcionar|estragou)\b"),
    ("troca_devolucao", 0.9, r"\b(devolv\w*|devolucao|arrependi\w*|reembolso|estorno|trocar (o |um )?produto|chegou (quebrad|errad|danificad|amassad)\w*|veio (quebrad|errad|danificad)\w*|nao gostei)\b"),
    ("consultar_pedido", 0.92, r"\b(pedido|rastreio|rastrear|quando chega|cade|ja saiu|minha compra|chega quando|vai chegar|chega|demorando|entregador)\b"),
    ("consultar_estoque", 0.9, r"\b(estoque|disponivel|disponibilidade|pronta entrega|tem (o |a |um |uma )?.{1,30} (em|na|no) (teresina|parnaiba|sao luis)|tem unidade|ainda tem|tem p\s?-?(13|20|45))\b"),
    ("consultar_preco", 0.92, r"\b(quanto custa|quanto (e|sai|fica|ta|esta|tá)|pre[cç]o|valor d[oa]|custa|qual o valor|tabela)\b"),
    ("recomendacao_produto", 0.85, r"\b(recomend\w*|indica\w*|sugest\w*|sugere|combina\w*|acompanha\w*|qual (o )?melhor|qual botijao|que botijao|orcamento|cotacao|contrato mensal|para (meu|minha) (restaurante|empresa|condominio|lanchonete))\b"),
    ("duvida_politica", 0.85, r"\b(chiand\w*|chiado|o que (eu )?faco|politica|prazo|frete|taxa de entrega|pix|cartao|parcel\w*|pagamento|horario|endereco|lgpd|privacidade|nota fiscal|fidelidade|pontos|seguranca|instalar|instalacao|entregam|funcionamento|aceita\w*|bairro|area de entrega|higieniz\w*|validade)\b"),
    ("saudacao", 0.9, r"^\s*((oi+|ola|ol[aá]+|bom dia|boa tarde|boa noite|e ai|opa|hey|hello|tudo bem|tudo bom|tudo certo|como vai|beleza)[\s!?.,;]*)+$"),
]


def classificar_regras(texto: str, slots: dict | None = None) -> NLUResult:
    n = normalizar(texto)
    ent = extrair_entidades(texto)
    slots = slots or {}

    intencao, conf = "outro", 0.4
    for nome, c, padrao in REGRAS:
        if re.search(padrao, n):
            intencao, conf = nome, c
            break

    # Ajustes finos
    if intencao == "fazer_pedido" and _PERGUNTA.search(n) and not _COMPRA_FORTE.search(n):
        # pergunta sem verbo de compra é dúvida (RAG), não pedido
        intencao, conf = ("garantia", 0.85) if re.search(r"\b(regulador|mangueira|validade|anos|vence)\b", n) else ("duvida_politica", 0.8)
    if intencao == "consultar_pedido" and not (ent.numero_pedido or slots.get("pedido_numero") or ent.cpf_cnpj or "pedido" in n) \
            and re.search(r"\b(entregam|bairro|cidade|regiao|taxa|prazo)\b", n):
        intencao, conf = "duvida_politica", 0.8
    if intencao == "outro" and ent.numero_pedido:
        intencao, conf = "consultar_pedido", 0.85
    if intencao == "outro" and ent.cpf_cnpj and slots.get("intencao_anterior") in {"consultar_pedido", "segunda_via_boleto"}:
        intencao, conf = slots["intencao_anterior"], 0.85
    if intencao == "consultar_preco" and re.search(r"\b(estoque|disponivel)\b", n):
        intencao = "consultar_estoque"
    if intencao == "outro" and ent.produto and extrair_itens(texto) and re.search(_PEDIR, n):
        intencao, conf = "fazer_pedido", 0.8
    if intencao == "outro" and re.search(r"^\s*e (esse|essa|ele|ela|o|a)\b", n) and slots.get("intencao_anterior"):
        intencao, conf = slots["intencao_anterior"], 0.6

    return NLUResult(intencao=intencao, confianca=conf, entidades=ent)


SYSTEM_NLU = """Você é o módulo de NLU do Flow Assistente, chatbot da Flow (revenda de gás GLP — botijões P13, P20, P45 —
e água mineral em galão de 20 L, com filiais em Teresina-PI, Parnaíba-PI e São Luís-MA).
Classifique a INTENÇÃO da última mensagem do cliente e extraia ENTIDADES.

Intenções possíveis:
- fazer_pedido: quer COMPRAR/pedir gás, água ou acessórios ("quero 2 botijões", "manda um gás", "acabou o gás")
- consultar_preco: quer saber preço
- consultar_estoque: disponibilidade/estoque, possivelmente por filial
- consultar_pedido: status/entrega de um pedido já feito
- segunda_via_boleto: boleto, 2ª via
- troca_devolucao: devolver produto, produto veio com problema (NÃO é a troca de botijão vazio, que é fazer_pedido)
- garantia: garantia/validade de regulador e mangueira, defeito
- duvida_politica: áreas e taxa de entrega, formas de pagamento, horário, segurança, LGPD, fidelidade, B2B
- recomendacao_produto: pede indicação, orçamento, contrato para restaurante/condomínio
- pedir_desconto: pede desconto, abatimento, preço menor
- falar_atendente: quer falar com humano
- saudacao: apenas cumprimento
- relatorio_interno: pergunta analítica interna (faturamento, vendas por filial)
- outro: nada acima

Use o CONTEXTO da conversa para resolver referências. cpf_cnpj: só dígitos. numero_pedido: FL-AAAA-NNNNN."""


def analisar(texto: str, slots: dict | None = None) -> NLUResult:
    slots = slots or {}
    contexto = {k: v for k, v in slots.items()
                if k in {"pedido_numero", "produto_nome", "filial", "intencao_anterior", "etapa_venda"} and v}
    regras = classificar_regras(texto, slots)
    res = llm.structured(SYSTEM_NLU, f"CONTEXTO: {contexto}\nMENSAGEM: {texto}", NLUResult, max_tokens=600,
                         mock=lambda _u: regras)
    if not llm.is_mock():
        ent = res.entidades
        ent.cpf_cnpj = regras.entidades.cpf_cnpj or (so_digitos(ent.cpf_cnpj) if ent.cpf_cnpj else None)
        ent.numero_pedido = regras.entidades.numero_pedido or ent.numero_pedido
        ent.produto = ent.produto or regras.entidades.produto
    return res
