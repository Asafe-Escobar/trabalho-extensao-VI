"""Utilidades de texto em português: normalização, tokenização, stemming leve e
dicionário de domínio (sinônimos e tópicos) usado por expansão, multi-query e HyDE mock."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

STOPWORDS = set("""
a o as os um uma uns umas de do da dos das no na nos nas em ao aos à às por pelo pela pelos pelas
para pra pro com sem sob sobre entre ate até e ou mas que se ja já nao não sim eu tu ele ela nos nós
vos eles elas voce você voces vocês me te lhe lhes meu minha meus minhas seu sua seus suas teu tua
nosso nossa nossos nossas dele dela deles delas isso isto esse essa esses essas este esta estes estas
aquele aquela aquilo qual quais quanto quanta quantos quantas como quando onde porque por que
e é era sao são ser foi esta está estao estão estar tem têm ter tinha havia ha há vai vou pode posso
podem podemos fazer faço faz fiz muito muita mais menos tambem também so só ainda bem tudo todo toda
todos todas algum alguma alguns algumas outro outra outros outras mesmo mesma la lá aqui ai aí entao
então oi ola olá bom boa dia tarde noite favor obrigado obrigada gostaria queria quero preciso
""".split())


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize(s: str) -> str:
    """minúsculas, sem acentos, espaços colapsados."""
    s = strip_accents(s.lower())
    s = re.sub(r"[^\w\s\-/]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_SUFIXOS = ("amentos", "imentos", "amento", "imento", "mente", "acoes", "icoes", "ucoes", "coes",
            "acao", "icao", "ucao", "cao", "agem", "adores", "ador", "edor", "idor", "ancia",
            "encia", "istas", "ista", "aveis", "iveis", "avel", "ivel", "osos", "osas", "oso", "osa",
            "ados", "adas", "idos", "idas", "ado", "ada", "ido", "ida", "ando", "endo", "indo",
            "ar", "er", "ir", "ou", "eu", "iu", "am", "em", "es", "as", "os", "a", "o", "e", "s")


@lru_cache(maxsize=20000)
def stem(w: str) -> str:
    """Stemmer leve: remove sufixo comum e trunca em 5 letras (agrupa devolver/devolução, etc.)."""
    if w.isdigit() or len(w) <= 3 or any(ch.isdigit() for ch in w):
        return w
    for suf in _SUFIXOS:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)]
            break
    return w[:5]


_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def words(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize(text))


def content_words(text: str) -> list[str]:
    return [w for w in words(text) if w not in STOPWORDS and len(w) > 1]


def tokens(text: str) -> list[str]:
    """Tokens para BM25: palavras de conteúdo com stemming. SKUs (ex.: nb-del-001) são mantidos
    inteiros e também quebrados em partes."""
    out: list[str] = []
    for w in content_words(text):
        if "-" in w:
            out.append(w)
            out.extend(stem(p) for p in w.split("-") if p and p not in STOPWORDS)
        else:
            out.append(stem(w))
    return out


def bigrams(toks: list[str]) -> set[tuple[str, str]]:
    return set(zip(toks, toks[1:]))


# ---------------------------------------------------------------------------
# Dicionário de domínio da Flow (revenda de gás GLP e água mineral).
#
# CANONICOS: jeitos de falar do cliente -> termos canônicos do catálogo.
#   botijão = P13 = gás de cozinha = GLP 13 kg | galão = água 20L | P45 = cilindro 45 kg
#   ATENÇÃO: "gás" de cozinha != gasolina/GNV (tratado como tópico próprio).
# ---------------------------------------------------------------------------
CANONICOS: list[tuple[str, list[str]]] = [
    # (regex sobre texto normalizado, termos canônicos)
    (r"\b(botij(ao|oes|a)|bujao|bujoes|gas de cozinha|gas do fogao|p\s?13|13\s?kg|botijao de 13|de 13)\b",
     ["P13", "botijão 13 kg", "GLP 13 kg", "gás de cozinha"]),
    (r"\b(p\s?45|45\s?kg|cilindro grande|cilindro de 45|central de gas)\b",
     ["P45", "cilindro 45 kg", "GLP 45 kg", "central de gás"]),
    (r"\b(p\s?20|20\s?kg|empilhadeira)\b", ["P20", "cilindro 20 kg"]),
    (r"\b(gala(o|oes)|garrafao|agua de 20|20\s?l(itros)?|agua mineral)\b",
     ["água 20L", "galão 20 litros", "água mineral"]),
    (r"\b(casco|botijao vazio|vasilhame|vazio)\b", ["vasilhame", "botijão vazio", "troca"]),
    (r"\b(glp|gas)\b", ["GLP", "gás de cozinha"]),
    (r"\b(registro|valvula|relogio do gas|regulador)\b", ["regulador de pressão", "registro"]),
    (r"\b(mangueira|mangueirinha)\b", ["mangueira", "validade da mangueira"]),
]

TOPICOS: list[dict] = [
    {
        "nome": "segurança e vazamento de gás",
        "gatilhos": ["cheiro de gas", "vazamento", "vazando", "vaza", "cheirando gas", "explos", "pegou fogo",
                     "fogo", "chama amarela", "seguranca", "perigo", "bolhas", "espuma de sabao"],
        "sinonimos": ["vazamento", "segurança com GLP", "fechar o registro", "ventilar", "193", "espuma de sabão"],
        "hyde": "Se sentir cheiro de gás, não acenda luzes nem fósforos, feche o registro do regulador, abra "
                "portas e janelas, saia do local e ligue para os Bombeiros (193). Para testar vazamento use "
                "espuma de sabão nas conexões, nunca fogo.",
    },
    {
        "nome": "troca e compra de vasilhame",
        "gatilhos": ["vasilhame", "casco", "botijao vazio", "nao tenho botijao", "sem botijao", "primeira compra",
                     "mudanca", "nao tenho o vazio", "galao vazio", "nao tenho galao", "comodato"],
        "sinonimos": ["vasilhame", "botijão vazio", "troca", "primeira compra", "casco"],
        "hyde": "O preço do gás é para troca: o entregador leva o botijão cheio e recolhe o vazio. Quem não tem "
                "botijão para trocar compra também o vasilhame: Gás GLP P13 R$ 125,00 mais Vasilhame P13 "
                "R$ 180,00. O mesmo vale para o galão de água 20L.",
    },
    {
        "nome": "preço do gás",
        "gatilhos": ["quanto ta", "quanto esta", "quanto custa", "preco", "valor", "quanto e o", "quanto sai",
                     "tabela", "mais barato"],
        "sinonimos": ["preço", "troca", "tabela", "R$"],
        "hyde": "O Gás GLP P13 (botijão 13 kg) custa R$ 125,00 na troca do vasilhame; o cilindro P45 custa "
                "R$ 480,00 e a água mineral 20L R$ 12,00 na troca do galão.",
    },
    {
        "nome": "entrega e prazos",
        "gatilhos": ["entrega", "entregar", "entregam", "chega", "chegar", "demora", "prazo", "tempo", "bairro",
                     "taxa", "frete", "agendar", "agendamento", "saiu para entrega", "entregador", "motoboy",
                     "atendem", "retirar"],
        "sinonimos": ["prazo de entrega", "30 a 60 minutos", "áreas atendidas", "entrega grátis", "bairro"],
        "hyde": "A Flow entrega gás P13 e água 20L em 30 a 60 minutos nas áreas atendidas de Teresina, Parnaíba "
                "e São Luís, com entrega grátis. O cilindro P45 chega em até 4 horas com instalação.",
    },
    {
        "nome": "formas de pagamento",
        "gatilhos": ["pix", "pagar", "pagamento", "parcelar", "parcela", "cartao", "credito", "debito",
                     "dinheiro", "troco", "maquininha", "aceitam", "forma de pagamento"],
        "sinonimos": ["Pix", "dinheiro", "troco", "cartão de débito", "cartão de crédito", "maquininha"],
        "hyde": "Na entrega a Flow aceita dinheiro (informe o troco), Pix e cartão de débito ou crédito na "
                "maquininha do entregador. Boleto faturado é exclusivo para empresas com cadastro aprovado.",
    },
    {
        "nome": "boleto e 2ª via",
        "gatilhos": ["boleto", "segunda via", "2a via", "2 via", "linha digitavel", "codigo de barras",
                     "vencido", "vencimento", "fatura"],
        "sinonimos": ["2ª via do boleto", "linha digitável", "vencimento", "CPF ou CNPJ do titular"],
        "hyde": "Para a 2ª via do boleto informe o CPF ou CNPJ do titular no chatbot; boletos em aberto mostram "
                "valor, vencimento e linha digitável. Boleto vencido há até 30 dias pode ser pago com multa de 2% "
                "e juros de 1% ao mês.",
    },
    {
        "nome": "regulador e mangueira",
        "gatilhos": ["regulador", "registro", "mangueira", "validade", "vencido o regulador", "inmetro",
                     "pig tail", "abracadeira", "instalar", "instalacao", "rosquear", "conectar"],
        "sinonimos": ["regulador de pressão", "validade de 5 anos", "mangueira", "INMETRO", "kit regulador"],
        "hyde": "O regulador de pressão vale 5 anos a partir da fabricação e a mangueira tem a validade impressa "
                "nela. O Kit regulador de pressão (regulador + mangueira) custa R$ 100,00 e o entregador pode "
                "instalar na hora e testar com espuma de sabão.",
    },
    {
        "nome": "água mineral 20L",
        "gatilhos": ["agua", "galao", "garrafao", "bebedouro", "higieniz", "limpar o galao", "20l", "20 litros"],
        "sinonimos": ["água mineral 20L", "galão", "higienização", "validade do galão", "bebedouro"],
        "hyde": "A água mineral 20L custa R$ 12,00 na troca do galão. Antes de encaixar no bebedouro, limpe o "
                "gargalo com álcool 70%; o galão aberto deve ser consumido em até 30 dias e o vasilhame tem "
                "validade de 3 anos.",
    },
    {
        "nome": "troca por defeito e qualidade",
        "gatilhos": ["defeito", "lacre", "quebrado", "amassado", "enferrujado", "nao funciona", "veio vazio",
                     "veio errado", "gosto estranho", "devolver", "devolucao", "reclamacao", "trocar o"],
        "sinonimos": ["troca gratuita", "lacre rompido", "defeito", "garantia", "qualidade"],
        "hyde": "Botijão com lacre rompido, vazamento na válvula ou galão com gosto estranho é trocado na hora e "
                "sem custo. Reguladores e mangueiras têm garantia de 12 meses contra defeito de fabricação.",
    },
    {
        "nome": "descontos e negociação",
        "gatilhos": ["desconto", "descontinho", "abatimento", "baixar o preco", "negociar", "negociacao",
                     "cupom", "promocao", "faz por", "deixa por", "cobrir"],
        "sinonimos": ["política comercial", "alçada", "atendente", "gerente", "promoção"],
        "hyde": "O assistente virtual não concede descontos. Pedidos de desconto vão para um atendente: até 5% o "
                "vendedor aprova e acima disso o gerente da filial.",
    },
    {
        "nome": "privacidade e LGPD",
        "gatilhos": ["lgpd", "privacidade", "dados pessoais", "meus dados", "excluir meus dados", "dados de outro",
                     "consentimento", "por que pede cpf", "por que o bot pede"],
        "sinonimos": ["LGPD", "dados pessoais", "titular", "encarregado de dados"],
        "hyde": "A Flow segue a LGPD: o chatbot só mostra pedidos e boletos do próprio titular depois do CPF ou "
                "CNPJ, exibe documentos mascarados e usa o endereço apenas para a entrega.",
    },
    {
        "nome": "programa de fidelidade",
        "gatilhos": ["fidelidade", "selo", "selos", "cartela", "10o botijao", "decimo", "gratis", "brinde",
                     "flow+", "pontos"],
        "sinonimos": ["Flow+", "10º botijão grátis", "selos", "11º galão grátis"],
        "hyde": "No Flow+ cada botijão P13 vale um selo e, com 9 selos, o 10º botijão é grátis; na água, o 11º "
                "galão é grátis. Os selos valem 12 meses.",
    },
    {
        "nome": "atendimento B2B",
        "gatilhos": ["empresa", "cnpj", "b2b", "restaurante", "condominio", "padaria", "lanchonete", "hotel",
                     "contrato", "faturado", "faturamento", "pedido minimo", "orcamento", "comercial", "industria"],
        "sinonimos": ["contrato mensal", "P45", "central de gás", "comodato", "boleto faturado", "pedido mínimo"],
        "hyde": "Restaurantes e condomínios têm contrato mensal com entrega programada de P45, cilindros em "
                "comodato, instalação da central de gás e boleto faturado em 28 dias, com pedido mínimo de "
                "R$ 900,00.",
    },
    {
        "nome": "filiais e horários",
        "gatilhos": ["horario", "endereco da loja", "loja", "filial", "abre", "fecha", "funciona", "telefone",
                     "domingo", "feriado", "onde fica", "atendente", "humano", "disk"],
        "sinonimos": ["filial", "horário de funcionamento", "Teresina", "Parnaíba", "São Luís", "disk gás"],
        "hyde": "A Flow tem filiais em Teresina, Parnaíba e São Luís, abertas de segunda a sábado a partir das 7h "
                "e aos domingos e feriados pela manhã. O chatbot funciona 24 horas.",
    },
    {
        "nome": "como pedir e trocar botijão",
        "gatilhos": ["quero", "pedir", "pedido", "comprar", "manda", "mande", "traz", "trazer", "acabou",
                     "acabando", "trocar botijao", "trocar o botijao", "como troco"],
        "sinonimos": ["fazer pedido", "troca do botijão", "endereço", "confirmar pedido"],
        "hyde": "Para pedir gás pelo chatbot diga a quantidade (ex.: 1 botijão de 13); o assistente confirma se "
                "há botijão para troca, o endereço e o pagamento, mostra o total e envia após a confirmação. "
                "Para trocar o botijão, feche o registro, desrosqueie o regulador e teste com espuma de sabão.",
    },
    {
        "nome": "combustível veicular (não vendemos)",
        "gatilhos": ["gasolina", "etanol", "alcool combustivel", "diesel", "gnv", "posto", "abastecer", "carro",
                     "moto a gas"],
        "sinonimos": ["não vendemos combustível", "gás de cozinha GLP", "proibido GLP em veículos"],
        "hyde": "A Flow vende gás de cozinha (GLP) e água mineral; não vende gasolina, etanol, diesel nem GNV e "
                "não abastece veículos. Usar botijão de GLP em veículos é proibido.",
    },
]

# sinônimos de vocabulário (palavra normalizada -> termos)
SINONIMOS_PALAVRA: dict[str, list[str]] = {
    "botijao": ["P13", "GLP 13 kg"],
    "bujao": ["botijão", "P13"],
    "botija": ["botijão", "P13"],
    "galao": ["água 20L"],
    "garrafao": ["galão", "água 20L"],
    "cilindro": ["P45", "P20"],
    "casco": ["vasilhame"],
    "registro": ["regulador"],
    "nota": ["nota fiscal"],
    "zap": ["WhatsApp"],
}


def canonicos(text: str) -> list[str]:
    """Termos canônicos de produto citados no texto (botijão -> P13, galão -> água 20L...)."""
    n = normalize(text)
    out: list[str] = []
    for padrao, termos in CANONICOS:
        if re.search(padrao, n):
            out.extend(termos)
    # "gás" sozinho em frase sobre carro/gasolina NÃO vira GLP
    if re.search(r"\b(gasolina|etanol|diesel|gnv|abastecer)\b", n):
        out = [t for t in out if t not in ("GLP", "gás de cozinha")]
    return list(dict.fromkeys(out))


def match_topicos(text: str) -> list[dict]:
    n = " " + normalize(text) + " "
    achados = []
    for t in TOPICOS:
        if any((" " + g) in n for g in t["gatilhos"]):
            achados.append(t)
    return achados


