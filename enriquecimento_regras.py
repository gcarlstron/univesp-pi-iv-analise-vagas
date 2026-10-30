"""
Etapas 2 e 3 do enriquecimento, sem LLM (regras + dicionário).
Entrada:  vagas_limpas_bi.csv   (saída do higienizacao_preparacao.py)
Saídas:   vagas_enriquecidas.csv          -> base para o BI (1 linha por vaga)
          vagas_stack_long.csv            -> 1 linha por (vaga, tecnologia), p/ gráficos no BI
          resumo_skills_ia_periodo.csv    -> insumo da etapa 3
"""
import re
import pandas as pd

ENTRADA = "vagas_limpas_bi.csv"

df = pd.read_csv(ENTRADA, low_memory=False)

# ---------------------------------------------------------------------------
# 0. Duplicatas
#    a) mesma URL repetida (erro na coleta) -> remove
#    b) mesma vaga postada em mais de um repo/mais de uma vez no mês -> agrupa
#       em grupo_vaga; use eh_principal=True para contar vagas distintas
# ---------------------------------------------------------------------------
antes = len(df)
df = df.drop_duplicates("url").reset_index(drop=True)
print(f"Removidas {antes - len(df)} linhas com URL duplicada")

chave = (df["autor"].fillna("").str.lower() + "|" +
         df["titulo_limpo"].fillna("").str.lower().str.replace(r"\s+", " ", regex=True).str.strip() + "|" +
         df["mes_ano"].astype(str))
# hash: identifica o grupo sem expor o usuário do GitHub (LGPD)
df["grupo_vaga"] = pd.util.hash_pandas_object(chave, index=False).astype("uint64").map(lambda h: f"{h:016x}")
df = df.sort_values("criado_em", kind="stable").reset_index(drop=True)
df["eh_principal"] = ~df["grupo_vaga"].duplicated()
df["qtd_postagens_grupo"] = df.groupby("grupo_vaga")["url"].transform("size")
# Concentração: quantas vagas o mesmo autor postou no ano (recrutadoras em massa
# distorcem os percentuais; ex.: em 2026 um único autor tem ~1/3 das vagas).
df["vagas_autor_ano"] = df.groupby([df["autor"].fillna(""), "ano"])["url"].transform("size")
df["autor_alto_volume"] = df["vagas_autor_ano"] >= 50
print(f"{df['eh_principal'].sum()} vagas distintas ({(~df['eh_principal']).sum()} repostagens/cross-posts)")

corpo = df["corpo_limpo"].fillna("")
titulo = df["titulo_limpo"].fillna("")
labels = df["labels"].fillna("")
texto = titulo + "\n" + corpo

# ---------------------------------------------------------------------------
# 2a. Tech stack: labels do GitHub + regex no texto, nomes padronizados
# ---------------------------------------------------------------------------
# tag padronizada -> regex (case-insensitive). \b evita "Go" em "Google" etc.
STACK = {
    "JavaScript": r"\bjavascript\b|\bjs\b",
    "TypeScript": r"\btypescript\b|\bts\b",
    "React": r"\breact(?:\.?js)?\b(?!\s*native)",
    "React Native": r"\breact[\s-]?native\b",
    "Vue": r"\bvue(?:\.?js)?\b",
    "Angular": r"\bangular\b",
    "Node.js": r"\bnode(?:\.?js)?\b",
    "Python": r"\bpython\b",
    "Java": r"\bjava\b(?!\s*script)",
    "Kotlin": r"\bkotlin\b",
    "Swift": r"\bswift\b",
    "Flutter": r"\bflutter\b",
    "PHP": r"\bphp\b",
    "Laravel": r"\blaravel\b",
    ".NET": r"(?<![\w.])\.net\b|\bc#|\basp\.net\b|\bdotnet\b",
    "Ruby": r"\bruby\b|\brails\b",
    "Go": r"\bgolang\b|\bgo\b(?=\s*(?:lang|,|/|\)|e\s|\.))",
    "Django": r"\bdjango\b",
    "Spring": r"\bspring(?:\s*boot)?\b",
    "SQL": r"\bsql\b",
    "PostgreSQL": r"\bpostgres(?:ql)?\b",
    "MySQL": r"\bmysql\b",
    "MongoDB": r"\bmongo(?:db)?\b",
    "Redis": r"\bredis\b",
    "AWS": r"\baws\b|\bamazon web services\b",
    "Azure": r"\bazure\b",
    "GCP": r"\bgcp\b|\bgoogle cloud\b",
    "Docker": r"\bdocker\b",
    "Kubernetes": r"\bkubernetes\b|\bk8s\b",
    "CI/CD": r"\bci\s*/\s*cd\b",
    "Git": r"\bgit\b",
    "Testes automatizados": r"\btdd\b|\btestes? (?:unit[aá]rios|automatizados)\b|\bjest\b|\bcypress\b|\bjunit\b",
    "Microsserviços": r"\bmicro-?s?servi[cç]os\b|\bmicroservices?\b",
    "Inglês": r"\bingl[eê]s\b|\benglish\b",
}
# labels do GitHub que já são tecnologia -> tag padronizada
LABEL_ALIAS = {"node.js": "Node.js", "nodejs": "Node.js", ".net": ".NET", "asp": ".NET",
               "tdd": "Testes automatizados", "golang": "Go"}
TAGS_LOWER = {t.lower(): t for t in STACK}


def stack_da_vaga(i: int) -> list[str]:
    achadas = set()
    for lab in labels.iat[i].split("|"):
        lab = re.sub(r"[^\w.#+/ -]", "", lab).strip().lower()  # tira emojis
        if lab in LABEL_ALIAS:
            achadas.add(LABEL_ALIAS[lab])
        elif lab in TAGS_LOWER:
            achadas.add(TAGS_LOWER[lab])
    return sorted(achadas)


STACK_RX = {t: re.compile(p, re.I) for t, p in STACK.items()}
stacks = []
for i, t in enumerate(texto):
    s = set(stack_da_vaga(i))
    s.update(tag for tag, rx in STACK_RX.items() if rx.search(t))
    stacks.append(sorted(s))
df["stack"] = ["|".join(s) for s in stacks]
df["qtd_tecnologias"] = [len(s) for s in stacks]

# ---------------------------------------------------------------------------
# 2b. Faixa salarial (conservador: só linhas que falam de salário/remuneração,
#     ignorando VR/VA/benefícios)
# ---------------------------------------------------------------------------
RX_LINHA_SAL = re.compile(r"sal[aá]ri|remunera|faixa|compensa|\bpretens", re.I)
RX_BENEF = re.compile(r"\bv\.?[ra]\b|vale|refei|aliment|aux[ií]lio|plano|gympass|b[oô]nus|plr|day ?off", re.I)
RX_VALOR = re.compile(r"R\$\s*(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)\s*(k|mil)?|(\d{1,2}(?:[.,]\d)?)\s*(k|mil)\b", re.I)
RX_LABEL_SAL = re.compile(r"(\d+)k\s*-\s*(\d+)k", re.I)


def _valor(m) -> float | None:
    num, mult = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    if not num:
        return None
    if mult:  # 5k, 5,5 mil
        return float(num.replace(",", ".")) * 1000
    v = float(num.replace(".", "").replace(" ", "").replace(",", "."))
    return v


def salario(i: int):
    # 1) label "💰 5k-10k"
    m = RX_LABEL_SAL.search(labels.iat[i])
    if m:
        return float(m.group(1)) * 1000, float(m.group(2)) * 1000, "label"
    # 2) texto
    for linha in corpo.iat[i].splitlines():
        if not RX_LINHA_SAL.search(linha) or RX_BENEF.search(linha):
            continue
        vals = [v for v in (_valor(m) for m in RX_VALOR.finditer(linha)) if v and 1000 <= v <= 60000]
        if vals:
            return min(vals), max(vals), "texto"
    return None, None, None


sal = [salario(i) for i in range(len(df))]
df["salario_min"], df["salario_max"], df["salario_fonte"] = zip(*sal)
df["tem_salario"] = df["salario_min"].notna()

# ---------------------------------------------------------------------------
# 2c. Tipo de menção a IA
# ---------------------------------------------------------------------------
IA_DESENV = r"\bpytorch\b|\btensorflow\b|\bkeras\b|\bscikit|\bsklearn\b|\bhugging ?face\b|\blangchain\b|\bllamaindex\b|" \
            r"\brag\b|\bfine[- ]?tun|\bembeddings?\b|\bvector (?:db|database|store)\b|\bpinecone\b|\bpgvector\b|" \
            r"\bmlops\b|\bopenai api\b|\bapi (?:da |of )?openai\b|\bagent(?:e|s|es)? (?:de )?(?:ia|ai)\b|\bai agents?\b|" \
            r"\bmachine learning\b|\baprendizado de m[aá]quina\b|\bdeep learning\b|\bnlp\b|\bmodelos? de (?:ia|linguagem|ml)\b"
IA_USO = r"\bcopilot\b|\bcursor\b|\bchatgpt\b|\bclaude(?: code)?\b|\bprompt engineering\b|\bengenharia de prompt\b|" \
         r"\bferramentas de (?:ia|ai)\b|\bai tools\b|\bai[- ]assisted\b|\bassistentes? de (?:ia|c[oó]digo)\b|\bwindsurf\b|\bcodeium\b"
rx_des, rx_uso = re.compile(IA_DESENV, re.I), re.compile(IA_USO, re.I)


def tipo_ia(t: str, menciona: bool) -> str:
    if not menciona:
        return "Sem menção"
    d, u = bool(rx_des.search(t)), bool(rx_uso.search(t))
    if d and u:
        return "Desenvolvimento + Uso"
    if d:
        return "Desenvolvimento de IA"
    if u:
        return "Uso de ferramentas de IA"
    return "Menção genérica"


df["tipo_ia"] = [tipo_ia(t, m) for t, m in zip(texto, df["menciona_ia"])]

# ---------------------------------------------------------------------------
# Exportar
# ---------------------------------------------------------------------------
df["periodo"] = pd.cut(df["ano"], [2020, 2022, 2024, 2026], labels=["2021-22", "2023-24", "2025-26"])
df.drop(columns=["autor"], errors="ignore").to_csv("vagas_enriquecidas.csv", index=False, encoding="utf-8-sig")

long = df[["url", "grupo_vaga", "eh_principal", "ano", "periodo", "nivel_consolidado", "menciona_ia", "stack"]].assign(
    tecnologia=df["stack"].str.split("|")).explode("tecnologia")
long = long[long["tecnologia"].fillna("") != ""].drop(columns="stack")
long.to_csv("vagas_stack_long.csv", index=False, encoding="utf-8-sig")

# ---------------------------------------------------------------------------
# 3. Insumo do resumo: % das vagas de cada grupo que pede cada tecnologia
#    (percentual, não contagem: o volume de vagas cai muito de 2021 a 2026)
# ---------------------------------------------------------------------------
#    Só vagas distintas (eh_principal), para cross-posts não pesarem em dobro.
tot = df[df["eh_principal"]].groupby(["periodo", "menciona_ia"], observed=True).size().rename("total_vagas")
freq = long[long["eh_principal"]].groupby(["periodo", "menciona_ia", "tecnologia"], observed=True).size().rename("vagas")
resumo = freq.reset_index().merge(tot.reset_index(), on=["periodo", "menciona_ia"])
resumo["pct"] = (resumo["vagas"] / resumo["total_vagas"] * 100).round(1)
resumo.sort_values(["menciona_ia", "periodo", "pct"], ascending=[False, True, False]) \
      .to_csv("resumo_skills_ia_periodo.csv", index=False, encoding="utf-8-sig")

print(f"OK: {len(df)} linhas | {df['tem_salario'].mean():.1%} com salário | média de {df['qtd_tecnologias'].mean():.1f} tecnologias/vaga")
print(df["tipo_ia"].value_counts().to_string())
