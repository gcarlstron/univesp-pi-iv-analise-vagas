"""
Análise exploratória da base (reproduz os números usados no relatório).
Entrada: vagas_limpas_bi.csv (saída do higienizacao_preparacao.py)
Saída:   imprime os resultados e salva as tabelas em ./tabelas_analise/
"""
from pathlib import Path

import pandas as pd

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
OUT = Path("tabelas_analise")
OUT.mkdir(exist_ok=True)


def titulo(t: str):
    print(f"\n{'=' * 70}\n{t}\n{'=' * 70}")


def salvar(tab: pd.DataFrame, nome: str):
    tab.to_csv(OUT / f"{nome}.csv", encoding="utf-8-sig")


df = pd.read_csv("vagas_limpas_bi.csv", low_memory=False)

# 1. Duplicatas exatas (mesma URL)
titulo("1. URLs duplicadas")
dup = df[df["url"].duplicated()]
print(f"Linhas totais: {len(df)} | URLs duplicadas: {len(dup)}")
print(dup["repo"].value_counts().to_string())
df = df.drop_duplicates("url")

# 2. Repostagens / cross-posts (mesmo autor + título no mesmo mês)
titulo("2. Repostagens e cross-posts")
# mesma normalização do enriquecimento_regras.py
df["_titulo_norm"] = df["titulo_limpo"].fillna("").str.lower().str.replace(r"\s+", " ", regex=True).str.strip()
df["_autor_norm"] = df["autor"].fillna("").str.lower()
df = df.sort_values("criado_em", kind="stable")
df["eh_principal"] = ~df.duplicated(["_autor_norm", "_titulo_norm", "mes_ano"])
print(f"Linhas após remover URL duplicada: {len(df)}")
print(f"Vagas distintas: {df['eh_principal'].sum()} | repostagens: {(~df['eh_principal']).sum()}")
p = df[df["eh_principal"]]

# 3. Volume por ano e nível (vagas distintas)
titulo("3. Vagas distintas por ano e nível")
tab = pd.crosstab(p["ano"], p["nivel_consolidado"], margins=True, margins_name="Total")
print(tab.to_string())
salvar(tab, "03_vagas_ano_nivel")

titulo("3b. Percentual de cada nível por ano")
tab = pd.crosstab(p["ano"], p["nivel_consolidado"], normalize="index").mul(100).round(1)
print(tab.to_string())
salvar(tab, "03b_pct_nivel_ano")

# 4. Concentração por autor (recrutadoras de alto volume)
titulo("4. Concentração: maior autor de cada ano")
conc = p.groupby("ano").apply(
    lambda g: pd.Series({
        "vagas": len(g),
        "vagas_maior_autor": g["autor"].value_counts().iloc[0],
        "pct_maior_autor": round(g["autor"].value_counts(normalize=True).iloc[0] * 100, 1),
    }),
    include_groups=False,
)
print(conc.to_string())
salvar(conc, "04_concentracao_autor")

# 5. Menção a IA: todas as vagas x sem autores de alto volume (>= 50 vagas/ano)
titulo("5. % de vagas que mencionam IA")
vol = p.groupby([p["autor"].fillna(""), "ano"])["url"].transform("size")
p = p.assign(alto_volume=vol >= 50)
ia = pd.DataFrame({
    "todas_%": p.groupby("ano")["menciona_ia"].mean().mul(100).round(1),
    "sem_alto_volume_%": p[~p["alto_volume"]].groupby("ano")["menciona_ia"].mean().mul(100).round(1),
    "n_sem_alto_volume": p[~p["alto_volume"]].groupby("ano").size(),
})
print(ia.to_string())
salvar(ia, "05_mencao_ia_ano")

# 6. Recorte júnior
titulo("6. Vagas júnior: volume e menção a IA")
j = p[p["nivel_consolidado"] == "Júnior"]
tab = j.groupby("ano").agg(vagas=("url", "size"), pct_ia=("menciona_ia", lambda s: round(s.mean() * 100, 1)))
print(tab.to_string())
salvar(tab, "06_junior_ano")

print(f"\nTabelas salvas em: {OUT.resolve()}")
