"""Seed determinístico do ERP local da Flow — revenda de gás GLP e água mineral.

Uso:  python -m app.db.seed      (recria o banco do zero)

Produtos: vêm de `app/integrations/revgas_catalogo_snapshot.json` (GET /products da RevGás).
Só entram os produtos "de verdade" listados em CATALOGO abaixo (sem TESTE/AAAA/2222/nomes de teste);
o `revgas_id` e o `container_revgas_id` (vasilhame) são lidos do snapshot. O preço é o
`preco_referencia` do snapshot quando existe; senão, um valor realista de Teresina (nov/2026).
Exceções documentadas em NOTES-database.md: P45 (amostra pequena no snapshot) e regulador simples.

Volumes: 3 filiais, 5 categorias, ~60 produtos (variações legadas com ativo=0), 28 clientes
(com endereço), 70 pedidos (todos os status), financeiro com boletos abertos/vencidos, 18 leads.

Clientes-demo fixos (apresentação):
- Maria Souza (PF, CPF 12345678909): pedido FL-2026-00042 'enviado' (= saiu para entrega)
  + boleto 'aberto' (pedido FL-2026-00061, aguardando pagamento).
- Escritório Alfa Ltda (PJ, CNPJ 11222333000181) — hoje opera um restaurante com central de gás P45:
  pedido FL-2026-00043 'separacao' (2 cilindros P45).
"""
from __future__ import annotations

import json
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

HOJE = date(2026, 11, 22)
SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "integrations" / "revgas_catalogo_snapshot.json"

FILIAIS = [
    (1, "Flow Teresina (Matriz)", "Teresina", "PI", "Av. Frei Serafim, 2280 - Centro, Teresina-PI",
     "(86) 3221-4500", "Seg a Sáb 7h-20h; Dom e feriados 7h-12h"),
    (2, "Flow Parnaíba", "Parnaíba", "PI", "Av. São Sebastião, 1150 - Centro, Parnaíba-PI",
     "(86) 3322-7800", "Seg a Sáb 7h-19h; Dom 7h-12h"),
    (3, "Flow São Luís", "São Luís", "MA", "Av. dos Holandeses, 400 - Calhau, São Luís-MA",
     "(98) 3235-6100", "Seg a Sáb 7h-20h; Dom e feriados 7h-12h"),
]

CATEGORIAS = [(1, "Gás GLP"), (2, "Vasilhames"), (3, "Água"), (4, "Acessórios"), (5, "Outros")]

# revgas_id: (sku, nome, categoria_id, marca, preco_fallback, garantia_meses, descricao, ativo)
# preco_fallback só é usado quando o snapshot não tem preco_referencia (ou em OVERRIDE_PRECO).
CATALOGO: dict[int, tuple] = {
    # ---- Gás GLP -------------------------------------------------------------------------
    26717: ("GLP-P13", "Gás GLP P13 (botijão 13 kg)", 1, "Flow Gás", 125.00, 0,
            "Gás de cozinha (GLP) no botijão de 13 kg, o botijão residencial. Preço para TROCA: o cliente "
            "entrega o botijão vazio na entrega. Sem botijão para trocar, some o Vasilhame P13 (botijão vazio 13 kg).", 1),
    25104: ("GLP-P10", "Gás GLP P10 (botijão 10 kg)", 1, "Flow Gás", 105.00, 0,
            "Botijão de 10 kg, alternativa menor ao P13. Preço para troca do vasilhame.", 1),
    28596: ("GLP-P16", "Gás GLP P16 (botijão 16 kg)", 1, "Flow Gás", 230.00, 0,
            "Botijão de 16 kg. Disponível sob encomenda.", 1),
    28117: ("GLP-P20", "Gás GLP P20 (cilindro 20 kg)", 1, "Flow Gás", 300.00, 0,
            "Cilindro de 20 kg usado em empilhadeiras e em alguns comércios. Preço para troca do cilindro.", 1),
    23974: ("GLP-P45", "Gás GLP P45 (cilindro 45 kg)", 1, "Flow Gás", 480.00, 0,
            "Cilindro de 45 kg para restaurantes, padarias, condomínios e casas com central de gás. Instalação na "
            "central feita por técnico da Flow. Usa a Mangueira com pig tail (central P45).", 1),
    28405: ("GLP-P2", "Gás GLP P2 (botijão 2 kg)", 1, "Flow Gás", 45.00, 0,
            "Botijão de 2 kg para camping e fogareiro. Sob encomenda.", 1),
    25106: ("GLP-P5", "Gás GLP P5 (botijão 5 kg)", 1, "Flow Gás", 65.00, 0,
            "Botijão de 5 kg para fogareiro e lanches. Sob encomenda.", 1),
    28379: ("GLP-P7", "Gás GLP P7 (botijão 7 kg)", 1, "Flow Gás", 85.00, 0,
            "Botijão de 7 kg. Sob encomenda.", 1),
    25112: ("GLP-P90", "Gás GLP P90 (cilindro 90 kg)", 1, "Flow Gás", 950.00, 0,
            "Cilindro de 90 kg para indústrias e grandes cozinhas. Sob contrato B2B.", 1),
    # variações legadas do P13/P20/P45 no cadastro da RevGás (não oferecer ao cliente)
    24230: ("GLP-P13-NORMAL", "Gás GLP P13 Normal (cadastro legado)", 1, "Flow Gás", 150.00, 0,
            "Variação antiga do P13 no cadastro da RevGás. Usar o Gás GLP P13 (botijão 13 kg).", 0),
    23934: ("GLP-P13-ALT", "Gás GLP P13 (cadastro alternativo)", 1, "Flow Gás", 125.00, 0,
            "Cadastro alternativo do P13 na RevGás.", 0),
    23740: ("GLP-P13-ENVASADO", "Gás GLP P13 envasado no botijão (cadastro legado)", 1, "Flow Gás", 150.00, 0,
            "Variação legada do P13.", 0),
    25313: ("GLP-P13-DUBOM", "Gás GLP P13 Du Bom (cadastro legado)", 1, "Du Bom", 125.00, 0, "Variação legada.", 0),
    25101: ("GLP-P13-SUPER", "Gás GLP P13 Super (cadastro legado)", 1, "Flow Gás", 130.00, 0, "Variação legada.", 0),
    30726: ("GLP-P20-ALT", "Gás GLP P20 (cadastro alternativo)", 1, "Flow Gás", 300.00, 0, "Cadastro alternativo.", 0),
    30728: ("GLP-P45-ALT", "Gás GLP P45 (cadastro alternativo)", 1, "Flow Gás", 480.00, 0, "Cadastro alternativo.", 0),
    # ---- Vasilhames ----------------------------------------------------------------------
    26718: ("VAS-P13", "Vasilhame P13 (botijão vazio 13 kg)", 2, "Flow Gás", 180.00, 0,
            "Botijão vazio de 13 kg para quem não tem vasilhame para trocar (primeira compra). "
            "Compatível com Gás GLP P13 (botijão 13 kg).", 1),
    25105: ("VAS-P10", "Vasilhame P10 (botijão vazio 10 kg)", 2, "Flow Gás", 150.00, 0,
            "Compatível com Gás GLP P10 (botijão 10 kg).", 1),
    28597: ("VAS-P16", "Vasilhame P16 (botijão vazio 16 kg)", 2, "Flow Gás", 200.00, 0,
            "Compatível com Gás GLP P16 (botijão 16 kg).", 1),
    28118: ("VAS-P20", "Vasilhame P20 (cilindro vazio 20 kg)", 2, "Flow Gás", 50.01, 0,
            "Compatível com Gás GLP P20 (cilindro 20 kg).", 1),
    23975: ("VAS-P45", "Vasilhame P45 (cilindro vazio 45 kg)", 2, "Flow Gás", 350.00, 0,
            "Cilindro vazio de 45 kg para montar ou ampliar a central de gás. Compatível com Gás GLP P45 (cilindro 45 kg).", 1),
    28406: ("VAS-P2", "Vasilhame P2 (botijão vazio 2 kg)", 2, "Flow Gás", 60.00, 0,
            "Compatível com Gás GLP P2 (botijão 2 kg).", 1),
    25107: ("VAS-P5", "Vasilhame P5 (botijão vazio 5 kg)", 2, "Flow Gás", 90.00, 0,
            "Compatível com Gás GLP P5 (botijão 5 kg).", 1),
    28380: ("VAS-P7", "Vasilhame P7 (botijão vazio 7 kg)", 2, "Flow Gás", 110.00, 0,
            "Compatível com Gás GLP P7 (botijão 7 kg).", 1),
    25113: ("VAS-P90", "Vasilhame P90 (cilindro vazio 90 kg)", 2, "Flow Gás", 700.00, 0,
            "Compatível com Gás GLP P90 (cilindro 90 kg).", 1),
    24616: ("VAS-AGUA-20L", "Vasilhame galão 20L (água, vazio)", 2, "Flow Água", 25.00, 0,
            "Galão vazio de 20 litros para quem não tem galão para trocar. Compatível com Água mineral 20L (galão).", 1),
    23935: ("VAS-P13-ALT", "Vasilhame P13 (cadastro alternativo)", 2, "Flow Gás", 180.00, 0, "Cadastro alternativo.", 0),
    24231: ("VAS-P13-NORMAL", "Vasilhame P13 Normal (cadastro legado)", 2, "Flow Gás", 180.00, 0, "Variação legada.", 0),
    23741: ("VAS-P13-ENVASADO", "Vasilhame P13 envasado (cadastro legado)", 2, "Flow Gás", 180.00, 0, "Variação legada.", 0),
    25314: ("VAS-P13-DUBOM", "Vasilhame P13 Du Bom (cadastro legado)", 2, "Du Bom", 180.00, 0, "Variação legada.", 0),
    25102: ("VAS-P13-SUPER", "Vasilhame P13 Super (cadastro legado)", 2, "Flow Gás", 180.00, 0, "Variação legada.", 0),
    30727: ("VAS-P20-ALT", "Vasilhame P20 (cadastro alternativo)", 2, "Flow Gás", 50.01, 0, "Cadastro alternativo.", 0),
    30729: ("VAS-P45-ALT", "Vasilhame P45 (cadastro alternativo)", 2, "Flow Gás", 350.00, 0, "Cadastro alternativo.", 0),
    24997: ("VAS-AGUA-20L-CRYSTAL", "Vasilhame galão 20L Crystal (cadastro legado)", 2, "Crystal", 25.00, 0,
            "Variação legada.", 0),
    # ---- Água ----------------------------------------------------------------------------
    26255: ("AGUA-20L", "Água mineral 20L (galão)", 3, "Flow Água", 12.00, 0,
            "Água mineral no galão de 20 litros, preço para TROCA do galão vazio. Sem galão, some o "
            "Vasilhame galão 20L (água, vazio).", 1),
    24615: ("AGUA-20L-REGINA", "Água mineral Regina 20L (galão)", 3, "Regina", 14.00, 0,
            "Galão de 20 litros da marca Regina, preço para troca do galão.", 1),
    24996: ("AGUA-20L-CRYSTAL", "Água mineral Crystal 20L (galão)", 3, "Crystal", 13.00, 0,
            "Galão de 20 litros Crystal. Sem estoque no momento.", 1),
    25316: ("AGUA-20L-DABOA", "Água mineral Da Boa 20L (galão)", 3, "Da Boa", 12.00, 0,
            "Galão de 20 litros Da Boa. Sem estoque no momento.", 1),
    28849: ("AGUA-10L-VOLPE", "Água mineral Volpe 10L", 3, "Volpe", 9.00, 0, "Garrafão descartável de 10 litros.", 1),
    24141: ("AGUA-10L", "Água mineral 10L", 3, "Flow Água", 8.00, 0, "Garrafão descartável de 10 litros.", 1),
    29092: ("AGUA-10L-CRISTAL", "Água mineral Cristal 10L", 3, "Cristal", 8.00, 0, "Garrafão descartável de 10 litros.", 1),
    28959: ("AGUA-1L5-REFRESQUE", "Água mineral Refresque 1,5L", 3, "Refresque", 5.00, 0, "Garrafa de 1,5 litro.", 1),
    28073: ("AGUA-1L5", "Água mineral 1,5L", 3, "Flow Água", 4.50, 0, "Garrafa de 1,5 litro.", 1),
    24142: ("AGUA-1L25", "Água mineral 1,25L", 3, "Flow Água", 4.00, 0, "Garrafa de 1,25 litro.", 1),
    26937: ("AGUA-500-VIENA-FD12", "Água mineral Viena 500ml (fardo com 12)", 3, "Viena", 18.00, 0,
            "Fardo com 12 garrafas de 500 ml.", 1),
    28258: ("AGUA-500-FD12", "Água mineral 500ml (fardo com 12)", 3, "Flow Água", 17.00, 0,
            "Fardo com 12 garrafas de 500 ml.", 1),
    29087: ("AGUA-510", "Água mineral 510ml", 3, "Flow Água", 2.50, 0, "Garrafa de 510 ml.", 1),
    29090: ("AGUA-350-VIDA", "Água mineral Vida 350ml", 3, "Vida", 5.00, 0, "Garrafa de 350 ml.", 1),
    24143: ("AGUA-330", "Água mineral 330ml", 3, "Flow Água", 2.50, 0, "Garrafa de 330 ml.", 1),
    28650: ("AGUA-200-FLOR", "Água mineral Flor de Água 200ml", 3, "Flor de Água", 1.50, 0, "Copo de 200 ml.", 1),
    # ---- Acessórios ----------------------------------------------------------------------
    26276: ("ACE-KIT-REG", "Kit regulador de pressão (regulador + mangueira)", 4, "Flow Gás", 100.00, 12,
            "Regulador de baixa pressão (registro INMETRO) com mangueira de 1,2 m e abraçadeiras, para fogão "
            "doméstico. Compatível com Gás GLP P13 (botijão 13 kg). Validade do regulador: 5 anos.", 1),
    28533: ("ACE-KIT-REG-DUPLO", "Kit regulador de pressão duplo", 4, "Flow Gás", 130.00, 12,
            "Regulador com duas saídas para ligar fogão e aquecedor no mesmo botijão. Compatível com Gás GLP P13 (botijão 13 kg).", 1),
    26318: ("ACE-REG", "Regulador de pressão", 4, "Flow Gás", 45.00, 12,
            "Regulador de baixa pressão avulso, com registro do INMETRO. Compatível com Gás GLP P13 (botijão 13 kg). "
            "Validade: 5 anos a partir da fabricação.", 1),
    26433: ("ACE-REG-STARRET", "Regulador de pressão Starret", 4, "Starret", 55.00, 12,
            "Regulador de baixa pressão Starret. Compatível com Gás GLP P13 (botijão 13 kg).", 1),
    28534: ("ACE-MANG-PIGTAIL", "Mangueira com pig tail (central P45)", 4, "Flow Gás", 35.00, 12,
            "Mangueira flexível metálica (pig tail) que liga o cilindro à central de gás. Compatível com Gás GLP P45 (cilindro 45 kg).", 1),
    27841: ("ACE-MANG", "Mangueira para gás 1,2 m", 4, "Flow Gás", 20.00, 12,
            "Mangueira transparente com tarja amarela (NBR 8613). Compatível com Gás GLP P13 (botijão 13 kg). "
            "Trocar no prazo de validade impresso nela.", 1),
    26432: ("ACE-ABRACADEIRA", "Abraçadeira Starret", 4, "Starret", 5.00, 0,
            "Abraçadeira metálica para fixar a mangueira no regulador e no fogão.", 1),
    29089: ("ACE-ADAPTADOR", "Adaptador Dubom", 4, "Du Bom", 15.00, 3,
            "Adaptador de conexão para regulador e mangueira.", 1),
    26326: ("ACE-BOMBA", "Bomba manual para galão", 4, "Flow Água", 25.00, 3,
            "Bomba manual para tirar água do galão sem precisar de suporte. Compatível com Água mineral 20L (galão).", 1),
    24452: ("ACE-BOMBA-AUTO", "Bomba elétrica automática para galão", 4, "Flow Água", 60.00, 6,
            "Bomba recarregável por USB. Compatível com Água mineral 20L (galão).", 1),
    24547: ("ACE-TORNEIRA", "Torneira para galão", 4, "Flow Água", 15.00, 3,
            "Torneira plástica para galão. Compatível com Água mineral 20L (galão).", 1),
    31998: ("ACE-SUPORTE", "Suporte para galão", 4, "Flow Água", 30.00, 3,
            "Suporte de mesa para galão de 20 litros. Compatível com Água mineral 20L (galão).", 1),
    30336: ("ACE-KIT-REG-ALT", "Kit regulador de pressão (cadastro alternativo)", 4, "Flow Gás", 100.00, 12,
            "Cadastro alternativo.", 0),
    24196: ("ACE-REG-ALT", "Regulador de pressão (cadastro alternativo)", 4, "Flow Gás", 45.00, 12, "Cadastro alternativo.", 0),
    24197: ("ACE-MANG-GRANDE", "Mangueira grande (cadastro legado)", 4, "Flow Gás", 30.00, 12, "Variação legada.", 0),
    30242: ("ACE-BOMBA-66", "Bomba 66 (cadastro legado)", 4, "Flow Água", 25.00, 3, "Variação legada.", 0),
    # ---- Outros --------------------------------------------------------------------------
    25103: ("OUT-CARVAO", "Carvão vegetal (saco)", 5, "Flow", 25.00, 0, "Saco de carvão vegetal para churrasco.", 1),
    29686: ("OUT-CARVAO-ARTUR", "Carvão vegetal Artur (saco)", 5, "Artur", 22.00, 0, "Saco de carvão vegetal.", 1),
    28999: ("OUT-GELO", "Gelo Ice Top (saco)", 5, "Ice Top", 10.00, 0, "Saco de gelo em cubos.", 1),
    31185: ("OUT-GELO-B", "Gelo (saco)", 5, "Flow", 10.00, 0, "Saco de gelo.", 1),
    31215: ("OUT-VELA", "Vela", 5, "Flow", 5.00, 0, "Vela comum.", 1),
}

# Preços do snapshot que NÃO usamos (ver NOTES-database.md):
# - 23974 GLP 45KG MA: mediana R$ 100 vem de amostra pequena (a própria doc da API avisa) -> R$ 480.
# - 26318 REGULADOR 123: R$ 12,31 é valor de teste -> R$ 45.
OVERRIDE_PRECO = {23974, 26318}
# Snapshot sem container para a água 20L principal: usa o galão vazio 24616 (mesmo das demais 20L).
OVERRIDE_CONTAINER = {26255: 24616}

NOMES_PF = [
    "João Pereira", "Ana Carvalho", "Pedro Lima", "Juliana Rocha", "Carlos Mendes",
    "Fernanda Alves", "Rafael Costa", "Larissa Martins", "Bruno Nascimento", "Camila Ribeiro",
    "Lucas Araújo", "Patrícia Gomes", "Thiago Barros", "Aline Moura", "Diego Freitas",
    "Beatriz Cardoso", "Marcos Teixeira", "Renata Dias",
]
EMPRESAS_PJ = [
    ("Restaurante Sabor do Delta Ltda", "Restaurante"),
    ("Condomínio Residencial Jardim das Palmeiras", "Condomínio"),
    ("Padaria Pão Quente Ltda", "Padaria"),
    ("Lanchonete Ponto do Açaí ME", "Lanchonete"),
    ("Hotel Litoral Norte Ltda", "Hotelaria"),
    ("Escola Saber Mais Ltda", "Educação (cozinha escolar)"),
    ("Clínica Vida Saudável Ltda", "Saúde (água mineral)"),
    ("Churrascaria Gaúcha do Norte Ltda", "Restaurante"),
]
ENDERECOS = {
    "Teresina": (["Rua das Acácias", "Rua Sete de Setembro", "Av. Nossa Senhora de Fátima", "Rua Firmino Pires",
                  "Rua Areolino de Abreu", "Av. Jóquei Clube", "Rua Desembargador Freitas"],
                 ["Fátima", "Jóquei", "Centro", "Ininga", "Dirceu Arcoverde", "Mocambinho", "São Cristóvão", "Horto"]),
    "Parnaíba": (["Av. Chagas Rodrigues", "Rua Riachuelo", "Av. Presidente Vargas", "Rua Almirante Gervásio Sampaio"],
                 ["Centro", "Pindorama", "São José", "Piauí", "Dirceu"]),
    "São Luís": (["Av. Colares Moreira", "Rua dos Azulejos", "Av. dos Holandeses", "Rua das Gaivotas"],
                 ["Calhau", "Renascença", "Cohama", "Turu", "Ponta d'Areia"]),
}
CIDADES = [("Teresina", "PI", 1), ("Parnaíba", "PI", 2), ("São Luís", "MA", 3)]


# ---------------------------------------------------------------------------
# Documentos fictícios válidos (dígitos verificadores corretos)
# ---------------------------------------------------------------------------
def cpf_dv(base9: str) -> str:
    nums = [int(c) for c in base9]
    for _ in range(2):
        peso = len(nums) + 1
        soma = sum(n * (peso - i) for i, n in enumerate(nums))
        d = (soma * 10) % 11
        nums.append(0 if d == 10 else d)
    return "".join(map(str, nums))


def cnpj_dv(base12: str) -> str:
    nums = [int(c) for c in base12]
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        soma = sum(n * p for n, p in zip(nums, pesos))
        r = soma % 11
        nums.append(0 if r < 2 else 11 - r)
    return "".join(map(str, nums))


def cpf_valido(cpf: str) -> bool:
    return len(cpf) == 11 and cpf.isdigit() and len(set(cpf)) > 1 and cpf_dv(cpf[:9]) == cpf


def cnpj_valido(cnpj: str) -> bool:
    return len(cnpj) == 14 and cnpj.isdigit() and len(set(cnpj)) > 1 and cnpj_dv(cnpj[:12]) == cnpj


def _linha_digitavel(rng: random.Random) -> str:
    d = "".join(str(rng.randint(0, 9)) for _ in range(47))
    return f"{d[0:5]}.{d[5:10]} {d[10:15]}.{d[15:21]} {d[21:26]}.{d[26:32]} {d[32]} {d[33:47]}"


def _dt(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


def carregar_snapshot() -> dict[int, dict]:
    dados = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    return {p["id"]: p for p in dados["produtos"]}


def produtos_catalogo(snapshot: dict[int, dict] | None = None) -> list[dict]:
    """Lista final de produtos (usada pelo seed e pelos testes)."""
    snap = snapshot if snapshot is not None else carregar_snapshot()
    out = []
    for rid, (sku, nome, cat, marca, preco_fb, gar, desc, ativo) in CATALOGO.items():
        p = snap.get(rid)
        if p is None:
            continue  # produto sumiu do snapshot: não inventa revgas_id
        ref = p.get("preco_referencia")
        preco = preco_fb if (ref is None or rid in OVERRIDE_PRECO) else float(ref)
        container = OVERRIDE_CONTAINER.get(rid, p.get("container_id"))
        out.append(dict(revgas_id=rid, sku=sku, nome=nome, categoria_id=cat, marca=marca, preco=round(preco, 2),
                        garantia_meses=gar, descricao=f"{desc} [RevGás: {p['descricao']}]", ativo=ativo,
                        container_revgas_id=container, estoque_revgas=int(p.get("estoque") or 0)))
    return out


# ---------------------------------------------------------------------------
def seed(conn: sqlite3.Connection) -> None:
    rng = random.Random(2026)
    cur = conn.cursor()
    cur.executemany("INSERT INTO filiais VALUES (?,?,?,?,?,?,?)", FILIAIS)
    cur.executemany("INSERT INTO categorias VALUES (?,?)", CATEGORIAS)

    prods = produtos_catalogo()
    sku_id: dict[str, int] = {}
    precos: dict[int, float] = {}
    for pid, p in enumerate(prods, start=1):
        minimo = round(p["preco"] * rng.uniform(0.90, 0.95), 2)  # CONFIDENCIAL
        cur.execute(
            "INSERT INTO produtos (id, sku, nome, descricao, categoria_id, marca, preco, preco_minimo,"
            " garantia_meses, ativo, revgas_id, container_revgas_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (pid, p["sku"], p["nome"], p["descricao"], p["categoria_id"], p["marca"], p["preco"], minimo,
             p["garantia_meses"], p["ativo"], p["revgas_id"], p["container_revgas_id"]),
        )
        sku_id[p["sku"]] = pid
        precos[pid] = p["preco"]

    # Estoque por filial: produto sem estoque na RevGás => 0 em todas as filiais.
    base_por_cat = {1: 60, 2: 25, 3: 120, 4: 30, 5: 20}
    for pid, p in enumerate(prods, start=1):
        for fid in (1, 2, 3):
            if not p["ativo"] or p["estoque_revgas"] <= 0:
                qtd = 0
            else:
                base = base_por_cat[p["categoria_id"]] * {1: 1.0, 2: 0.4, 3: 0.6}[fid]
                qtd = max(0, int(rng.gauss(base, base / 3)))
            cur.execute("INSERT INTO estoque VALUES (?,?,?)", (pid, fid, qtd))
    fixos = {("GLP-P13", 1): 180, ("GLP-P13", 2): 60, ("GLP-P13", 3): 95,
             ("GLP-P45", 1): 25, ("GLP-P45", 2): 12, ("GLP-P45", 3): 0,  # demo: "Tem P45 em Parnaíba?"
             ("AGUA-20L", 1): 300, ("AGUA-20L", 2): 90, ("AGUA-20L", 3): 140,
             ("VAS-P13", 1): 40, ("ACE-KIT-REG", 1): 35}
    for (sku, fid), qtd in fixos.items():
        cur.execute("UPDATE estoque SET quantidade=? WHERE produto_id=? AND filial_id=?", (qtd, sku_id[sku], fid))

    # Clientes ---------------------------------------------------------------
    clientes = [
        (1, "Maria Souza", "PF", "12345678909", "maria.souza@exemplo.com.br", "(86) 99812-3456",
         "Rua das Acácias", "120", "Fátima", "Teresina", "PI", "Residencial", "2025-08-14 09:30:00"),
        (2, "Escritório Alfa Ltda", "PJ", "11222333000181", "compras@escritorioalfa.exemplo.com.br",
         "(86) 3233-1100", "Av. Nossa Senhora de Fátima", "1500", "Jóquei", "Teresina", "PI",
         "Restaurante (central de gás P45)", "2025-03-02 14:00:00"),
    ]
    usados = {"12345678909", "11222333000181"}

    def _endereco(cidade: str) -> tuple[str, str, str]:
        ruas, bairros = ENDERECOS[cidade]
        return rng.choice(ruas), str(rng.randint(10, 2999)), rng.choice(bairros)

    cid = 3
    for nome in NOMES_PF:
        while True:
            doc = cpf_dv("".join(str(rng.randint(0, 9)) for _ in range(9)))
            if doc not in usados:
                break
        usados.add(doc)
        cidade, uf, _ = rng.choice(CIDADES)
        rua, num, bairro = _endereco(cidade)
        email = nome.lower().replace(" ", ".").translate(str.maketrans("áéíóúâêôãõç", "aeiouaeoaoc"))
        criado = datetime(2024, 1, 1, 10) + timedelta(days=rng.randint(0, 900))
        clientes.append((cid, nome, "PF", doc, f"{email}@exemplo.com.br",
                         f"({'98' if uf == 'MA' else '86'}) 9{rng.randint(8000, 9999)}-{rng.randint(1000, 9999)}",
                         rua, num, bairro, cidade, uf, "Residencial", _dt(criado)))
        cid += 1
    for nome, segmento in EMPRESAS_PJ:
        while True:
            doc = cnpj_dv("".join(str(rng.randint(0, 9)) for _ in range(8)) + "0001")
            if doc not in usados:
                break
        usados.add(doc)
        cidade, uf, _ = rng.choice(CIDADES)
        rua, num, bairro = _endereco(cidade)
        slug = "".join(ch for ch in nome.lower().split()[1] if ch.isalpha())
        criado = datetime(2023, 6, 1, 10) + timedelta(days=rng.randint(0, 1000))
        clientes.append((cid, nome, "PJ", doc, f"compras@{slug}.exemplo.com.br",
                         f"({'98' if uf == 'MA' else '86'}) 3{rng.randint(200, 399)}-{rng.randint(1000, 9999)}",
                         rua, num, bairro, cidade, uf, segmento, _dt(criado)))
        cid += 1
    cur.executemany(
        "INSERT INTO clientes (id, nome, tipo, cpf_cnpj, email, telefone, endereco, numero, bairro, cidade, uf,"
        " segmento, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", clientes)
    tipo_cliente = {c[0]: c[2] for c in clientes}
    filial_cliente = {c[0]: next(f for (cidade, _uf, f) in CIDADES if cidade == c[9]) for c in clientes}

    # Pedidos (histórico local da demo; vendas novas do chatbot vão para vendas_revgas) ----------
    pf_mix = [("GLP-P13", 1, 50), ("AGUA-20L", 2, 25), ("AGUA-20L-REGINA", 1, 8), ("ACE-KIT-REG", 1, 6),
              ("VAS-P13", 1, 4), ("ACE-MANG", 1, 3), ("AGUA-500-VIENA-FD12", 1, 2), ("OUT-CARVAO", 1, 2)]
    pj_mix = [("GLP-P45", 2, 35), ("GLP-P13", 4, 25), ("AGUA-20L", 10, 25), ("ACE-MANG-PIGTAIL", 1, 5),
              ("GLP-P20", 1, 5), ("OUT-GELO", 5, 5)]
    status_recentes = ["aguardando_pagamento", "pago", "separacao", "enviado", "entregue", "cancelado"]
    pedidos_fixos = {
        42: dict(cliente=1, filial=1, status="enviado", data=datetime(2026, 11, 22, 10, 40),
                 itens=[("GLP-P13", 1), ("AGUA-20L", 1)], previsao=datetime(2026, 11, 22, 11, 40),
                 rastreio="MOTO-07", pagamento="pix"),
        43: dict(cliente=2, filial=1, status="separacao", data=datetime(2026, 11, 22, 9, 15),
                 itens=[("GLP-P45", 2), ("ACE-MANG-PIGTAIL", 1)], previsao=datetime(2026, 11, 22, 14, 0),
                 rastreio=None, pagamento="boleto"),
        15: dict(cliente=1, filial=1, status="entregue", data=datetime(2026, 4, 13, 8, 30),
                 itens=[("GLP-P13", 1), ("ACE-KIT-REG", 1)], previsao=datetime(2026, 4, 13, 9, 30),
                 rastreio="MOTO-03", pagamento="dinheiro"),
        61: dict(cliente=1, filial=1, status="aguardando_pagamento", data=datetime(2026, 11, 20, 16, 0),
                 itens=[("GLP-P13", 1), ("VAS-P13", 1)], previsao=None, rastreio=None,
                 pagamento="boleto", venc=date(2026, 11, 28)),
        30: dict(cliente=2, filial=1, status="entregue", data=datetime(2026, 7, 27, 9, 0),
                 itens=[("GLP-P45", 3)], previsao=datetime(2026, 7, 27, 13, 0), rastreio="CAMINHAO-02",
                 pagamento="boleto"),
    }

    def _escolher(mix, pj):
        n_itens = rng.choice([1, 1, 2]) if not pj else rng.choice([1, 2])
        escolhidos = []
        for _ in range(n_itens):
            sku, qbase, _w = rng.choices(mix, weights=[m[2] for m in mix])[0]
            if sku not in [s for s, _ in escolhidos]:
                escolhidos.append((sku, max(1, qbase + (rng.randint(0, 3) if pj else rng.randint(0, 1)))))
        return escolhidos

    fin_id, item_id = 1, 1
    entregues: list[int] = []
    for n in range(1, 71):
        if n in pedidos_fixos:
            f = pedidos_fixos[n]
            cli, fil, status, quando = f["cliente"], f["filial"], f["status"], f["data"]
            itens = [(sku_id[s], q) for s, q in f["itens"]]
            previsao, rastreio, forma = f["previsao"], f["rastreio"], f["pagamento"]
        else:
            if n <= 41:
                quando = datetime(2026, 1, 5, 8) + timedelta(days=(n - 1) * 7, hours=rng.randint(0, 10))
            elif n < 62:
                quando = datetime(2026, 10, 20, 8) + timedelta(days=n - 44, hours=rng.randint(0, 10))
            else:  # últimos ~2 dias: pedidos em andamento (todos os status)
                quando = datetime(2026, 11, 21, 8) + timedelta(hours=(n - 62) * 3)
            cli = rng.randint(3, len(clientes))
            fil = filial_cliente[cli] if rng.random() < 0.85 else rng.randint(1, 3)
            pj = tipo_cliente[cli] == "PJ"
            idade = (HOJE - quando.date()).days
            if n < 62 and idade > 1:
                status = "cancelado" if rng.random() < 0.08 else "entregue"
            else:
                status = status_recentes[n % len(status_recentes)]
            itens = [(sku_id[s], q) for s, q in _escolher(pj_mix if pj else pf_mix, pj)]
            previsao = quando + timedelta(minutes=rng.choice([30, 45, 60])) if status != "cancelado" else None
            rastreio = f"MOTO-{rng.randint(1, 12):02d}" if status in ("enviado", "entregue") else None
            if pj:
                forma = "boleto" if rng.random() < 0.7 else "pix"
            else:
                forma = rng.choices(["pix", "dinheiro", "cartao", "boleto"], weights=[45, 30, 20, 5])[0]
            if status == "aguardando_pagamento":
                forma = "boleto"
            f = {}

        total = round(sum(precos[pid] * q for pid, q in itens), 2)
        cur.execute(
            "INSERT INTO pedidos (id, numero, cliente_id, filial_id, status, valor_total, criado_em,"
            " previsao_entrega, codigo_rastreio) VALUES (?,?,?,?,?,?,?,?,?)",
            (n, f"FL-2026-{n:05d}", cli, fil, status, total, _dt(quando),
             previsao.strftime("%Y-%m-%d %H:%M") if previsao else None, rastreio),
        )
        for pid, q in itens:
            cur.execute("INSERT INTO itens_pedido VALUES (?,?,?,?,?)", (item_id, n, pid, q, precos[pid]))
            item_id += 1

        # Financeiro
        if status == "aguardando_pagamento":
            venc = f.get("venc") or quando.date() + timedelta(days=3)
            fstatus = "aberto" if venc >= HOJE else "vencido"
        elif status == "cancelado":
            forma, venc, fstatus = "boleto", quando.date() + timedelta(days=3), "vencido"
        else:
            venc = quando.date() + timedelta(days=28 if (forma == "boleto" and tipo_cliente[cli] == "PJ")
                                             else 3 if forma == "boleto" else 0)
            fstatus = "pago" if (forma != "boleto" or venc < HOJE) else "aberto"
        linha = _linha_digitavel(rng) if forma == "boleto" else None
        cur.execute("INSERT INTO financeiro VALUES (?,?,?,?,?,?,?,?)",
                    (fin_id, cli, n, forma, total, venc.isoformat(), fstatus, linha))
        fin_id += 1
        if status == "entregue":
            entregues.append(n)

    # Boletos B2B avulsos (contrato mensal de gás), sem pedido vinculado
    for cli_pj, valor, venc, st in [(21, 1850.00, "2026-10-30", "vencido"), (22, 2390.50, "2026-12-10", "aberto"),
                                    (23, 980.00, "2026-11-05", "vencido"), (2, 1440.00, "2026-12-05", "aberto")]:
        cur.execute("INSERT INTO financeiro VALUES (?,?,?,?,?,?,?,?)",
                    (fin_id, cli_pj, None, "boleto", valor, venc, st, _linha_digitavel(rng)))
        fin_id += 1

    # Trocas / ocorrências -------------------------------------------------------
    motivos = [("Botijão com vazamento na válvula — substituído na hora", "concluida"),
               ("Galão de água com gosto estranho — trocado", "concluida"),
               ("Regulador com defeito (não regula a chama)", "em_analise"),
               ("Botijão entregue com lacre rompido", "aprovada"),
               ("Galão com rachadura", "aberta")]
    for i, (motivo, st) in enumerate(motivos, start=1):
        pid = entregues[(i * 5) % len(entregues)]
        cur.execute("SELECT criado_em FROM pedidos WHERE id=?", (pid,))
        base = datetime.strptime(cur.fetchone()[0], "%Y-%m-%d %H:%M:%S") + timedelta(hours=3)
        cur.execute("INSERT INTO trocas VALUES (?,?,?,?,?)", (i, pid, motivo, st, _dt(base)))

    # Leads ------------------------------------------------------------------
    leads = [
        ("Restaurante Panela de Barro", "(86) 3222-9090", "contato@paneladebarro.exemplo.com.br", "Contrato mensal P45 (6 cilindros/mês)", "chatbot", "qualificado", 85),
        ("Condomínio Solar das Dunas", "(86) 3321-6060", "sindico@solardasdunas.exemplo.com.br", "Central de gás P45 para 40 apartamentos", "indicacao", "proposta", 90),
        ("Helena Prado", "(98) 98877-6655", "helena.prado@exemplo.com.br", "Botijão P13 + kit regulador (mudança)", "instagram", "novo", 35),
        ("Igor Batista", "(86) 99444-3322", "igor.b@exemplo.com.br", "Água 20L semanal", "whatsapp", "novo", 40),
        ("Padaria Trigo de Ouro", "(86) 3301-4455", "compras@trigodeouro.exemplo.com.br", "P45 para forno", "site", "proposta", 80),
        ("Sofia Antunes", "(98) 98111-2233", "sofia.antunes@exemplo.com.br", "Primeiro botijão (sem vasilhame)", "chatbot", "ganho", 70),
        ("Rodrigo Lemos", "(86) 99555-6677", "rodrigo.lemos@exemplo.com.br", "Gás P13 mais barato", "site", "perdido", 20),
        ("Academia Corpo em Forma", "(86) 3218-7766", "adm@corpoemforma.exemplo.com.br", "Água 20L para bebedouros (30 galões/mês)", "feira", "qualificado", 72),
        ("Tatiane Reis", "(86) 99666-1212", "tatiane.reis@exemplo.com.br", "Galão 20L + suporte", "instagram", "novo", 30),
        ("Vinícius Melo", "(98) 98222-4545", "vinicius.melo@exemplo.com.br", "Botijão P13 recorrente", "chatbot", "ganho", 60),
        ("Hotel Delta do Parnaíba", "(86) 3323-5050", "ti@hoteldelta.exemplo.com.br", "Gás P45 e água mineral", "indicacao", "qualificado", 78),
        ("Paula Fontes", "(86) 99777-8080", "paula.fontes@exemplo.com.br", "Regulador novo", "whatsapp", "perdido", 15),
        ("Lanchonete Sabor da Praça", "(86) 3324-1212", "contato@sabordapraca.exemplo.com.br", "P20 e carvão", "chatbot", "proposta", 66),
        ("André Lustosa", "(86) 99888-1313", "andre.lustosa@exemplo.com.br", "Botijão P13", "chatbot", "novo", 25),
        ("Escola Municipal Criança Feliz", "(98) 3244-7070", "cozinha@criancafeliz.exemplo.com.br", "P45 cozinha escolar", "site", "qualificado", 74),
        ("Mariana Veloso", "(86) 99123-9898", "mariana.veloso@exemplo.com.br", "Água 20L + bomba elétrica", "instagram", "ganho", 55),
        ("Cooperativa Agro Piauí", "(89) 3422-1515", "compras@agropiaui.exemplo.com.br", "P90 para secador", "feira", "novo", 50),
        ("Daniel Portela", "(98) 98555-0101", "daniel.portela@exemplo.com.br", "2 botijões P13 + galão", "chatbot", "qualificado", 58),
    ]
    for i, (nome, tel, email, interesse, origem, estagio, score) in enumerate(leads, start=1):
        criado = datetime(2026, 9, 1, 10) + timedelta(days=i * 4)
        atualizado = criado + timedelta(days=rng.randint(0, 6))
        cur.execute(
            "INSERT INTO leads (id, nome, telefone, email, interesse, origem, estagio, score, criado_em, atualizado_em)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (i, nome, tel, email, interesse, origem, estagio, score, _dt(criado), _dt(atualizado)),
        )


if __name__ == "__main__":  # python -m app.db.seed
    from .connection import get_conn, init_db

    init_db(reset=True)
    with get_conn() as c:
        for t in ("filiais", "produtos", "clientes", "pedidos", "financeiro", "leads", "trocas", "vendas_revgas"):
            print(f"{t:14s} {c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
