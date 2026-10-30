import re
import sys
import unicodedata

import pandas as pd

ARQUIVO_ENTRADA = "vagas.csv"
ARQUIVO_SAIDA = "vagas_limpas_bi.csv"


def normalizar_nome(nome: str) -> str:
    """Remove acentos, espaços extras e deixa minúsculo: ' Nível ' -> 'nivel'."""
    nome = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    return nome.strip().lower()


def achar_coluna(df: pd.DataFrame, candidatas: list[str]) -> str | None:
    for c in candidatas:
        if c in df.columns:
            return c
    return None


# ---------------------------------------------------------------------------
# Carregar os dados
# ---------------------------------------------------------------------------
df = pd.read_csv(ARQUIVO_ENTRADA, encoding="utf-8")
df.columns = [normalizar_nome(c) for c in df.columns]
print("Colunas encontradas:", df.columns.tolist())

col_corpo = achar_coluna(df, ["corpo", "descricao", "description"])
col_titulo = achar_coluna(df, ["titulo", "title", "cargo"])
col_nivel = achar_coluna(df, ["nivel_final", "nivel", "senioridade", "level", "seniority"])
col_data = achar_coluna(df, ["criado_em", "data", "data_publicacao", "created_at"])

faltando = [n for n, c in [("corpo", col_corpo), ("titulo", col_titulo), ("criado_em", col_data)] if c is None]
if faltando:
    sys.exit(f"ERRO: colunas obrigatórias não encontradas: {faltando}")

# ---------------------------------------------------------------------------
# 1. Sanitização LGPD (e-mails e telefones)
# ---------------------------------------------------------------------------
regex_email = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
# Exige separador (hífen/espaço) entre as duas metades do número,
# para não apagar CEPs, códigos de vaga e outros números de 8 dígitos.
regex_telefone = re.compile(r"(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?9?\d{4}[-\s]\d{4}\b")


def sanitizar_texto(texto):
    if not isinstance(texto, str):
        return texto
    texto = regex_email.sub("[EMAIL_REMOVIDO]", texto)
    texto = regex_telefone.sub("[TELEFONE_REMOVIDO]", texto)
    return texto


df["corpo_limpo"] = df[col_corpo].apply(sanitizar_texto)
df["titulo_limpo"] = df[col_titulo].apply(sanitizar_texto)

# ---------------------------------------------------------------------------
# 2. Consolidação de senioridade (só se a coluna existir)
# ---------------------------------------------------------------------------
mapa_senioridade = {
    "indefinido": "Indefinido",
    "pleno_fonte_unica": "Pleno",
    "pleno": "Pleno",
    "senior": "Sênior",
    "senior_fonte_unica": "Sênior",
    "junior_fonte_unica": "Júnior",
    "junior": "Júnior",
    "divergente": "Divergente",
    "multinivel": "Multinível",  # vaga aberta a vários níveis (ex.: Júnior a Sênior)
    "estagio_fonte_unica": "Estágio",
    "estagio": "Estágio",
}

if col_nivel:
    nivel_norm = df[col_nivel].astype(str).map(normalizar_nome)
    df["nivel_consolidado"] = nivel_norm.map(mapa_senioridade).fillna("Não mapeado")
    df["fonte_unica"] = nivel_norm.str.contains("fonte_unica", na=False)

    nao_mapeados = nivel_norm[df["nivel_consolidado"] == "Não mapeado"].unique()
    if len(nao_mapeados):
        print("AVISO: valores de nível sem mapeamento:", list(nao_mapeados))
else:
    print("AVISO: coluna de nível não encontrada; etapa de senioridade ignorada.")

# ---------------------------------------------------------------------------
# 3. Datas
# ---------------------------------------------------------------------------
# Converte para horário de Brasília e remove o fuso (evita o UserWarning e
# garante que vagas postadas perto da meia-noite caiam no mês certo).
df["criado_em"] = (
    pd.to_datetime(df[col_data], errors="coerce", utc=True)
    .dt.tz_convert("America/Sao_Paulo")
    .dt.tz_localize(None)
)
invalidas = df["criado_em"].isna().sum()
if invalidas:
    print(f"AVISO: {invalidas} linha(s) com data inválida (ficarão sem ano/mês).")

df["ano"] = df["criado_em"].dt.year.astype("Int64")
df["mes_ano"] = df["criado_em"].dt.to_period("M").astype(str).replace("NaT", pd.NA)

# ---------------------------------------------------------------------------
# 4. Flag de IA
# ---------------------------------------------------------------------------
# Siglas IA/AI só em MAIÚSCULAS, para não pegar o verbo "ia" ("a empresa ia contratar").
regex_ia_sigla = r"\b(?:IA|AI|LLMs?|GPT|RAG|GenAI)\b"
# Termos por extenso: sem diferenciar maiúsculas/minúsculas.
regex_ia_termos = (
    r"\b(?:intelig[eê]ncia artificial|artificial intelligence|machine learning|"
    r"aprendizado de m[aá]quina|chatgpt|copilot|ia generativa|generative ai)\b"
)


def menciona_ia(serie: pd.Series) -> pd.Series:
    return serie.str.contains(regex_ia_sigla, case=True, regex=True, na=False) | serie.str.contains(
        regex_ia_termos, case=False, regex=True, na=False
    )


# O CSV já traz uma flag menciona_ia da coleta; guardamos para comparar.
if "menciona_ia" in df.columns:
    df = df.rename(columns={"menciona_ia": "menciona_ia_coleta"})

df["menciona_ia"] = menciona_ia(df["corpo_limpo"]) | menciona_ia(df["titulo_limpo"])

if "menciona_ia_coleta" in df.columns:
    coleta = df["menciona_ia_coleta"].astype(str).str.lower().isin(["true", "1", "sim"])
    print("\nComparação flag IA (coleta x nova):")
    print(pd.crosstab(coleta, df["menciona_ia"], rownames=["coleta"], colnames=["nova"]).to_string())

if "menciona_ia_coleta" in df.columns:
    div = df[coleta != df["menciona_ia"]]
    div[["url", "titulo_limpo", "termos_ia", "menciona_ia_coleta", "menciona_ia"]].to_csv(
        "divergencias_ia.csv", index=False, encoding="utf-8-sig"
    )
    
print(pd.crosstab(df["ano"], df["nivel_consolidado"]).to_string())
# ---------------------------------------------------------------------------
# Exportar (sem o texto original, que pode conter dados pessoais)
# ---------------------------------------------------------------------------
df = df.drop(columns=[col_corpo, col_titulo])
df.to_csv(ARQUIVO_SAIDA, index=False, encoding="utf-8-sig")  # utf-8-sig: acentos ok no Excel/Power BI

print(f"\nOK: {len(df)} linhas exportadas para {ARQUIVO_SAIDA}")
print(f"Vagas que mencionam IA: {df['menciona_ia'].sum()} ({df['menciona_ia'].mean():.1%})")
if col_nivel:
    print(df["nivel_consolidado"].value_counts().to_string())