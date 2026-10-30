"""
Gera a base enxuta do dashboard a partir da saída final do pipeline.

Entrada: vagas_enriquecidas_llm.csv   (saída do classificar_llm.py juntar)
Saída:   dados_dashboard.csv.gz       (só vagas distintas, sem o texto dos anúncios)

Uso:
    python preparar_dashboard.py
"""
import pandas as pd

ENTRADA = "vagas_enriquecidas_llm.csv"
SAIDA = "dados_dashboard.csv.gz"

COLUNAS = [
    "url", "repo", "titulo_limpo", "ano", "mes_ano", "periodo",
    "nivel_consolidado", "nivel_com_ia", "origem_nivel", "aceita_junior",
    "menciona_ia", "ia_exigida", "llm_ia_contexto", "tipo_ia",
    "stack", "qtd_tecnologias",
    "tem_salario", "salario_min", "salario_max",
    "autor_alto_volume", "qtd_postagens_grupo",
]

df = pd.read_csv(ENTRADA, low_memory=False)
print(f"Lidas {len(df)} linhas de {ENTRADA}")

# Só a postagem principal de cada vaga (repostagens e cross-posts ficam de fora)
df = df[df["eh_principal"].astype(str).str.lower() == "true"].copy()

# Vaga aberta a júnior: alguma das três fontes de nível cita júnior,
# inclusive quando lista vários níveis (Multinível).
fontes = df[["nivel_label", "nivel_campo", "nivel_titulo"]].fillna("").astype(str).agg("|".join, axis=1)
df["aceita_junior"] = fontes.str.contains("junior") | (df["nivel_com_ia"] == "Júnior")

for col in ["menciona_ia", "ia_exigida", "tem_salario", "autor_alto_volume"]:
    df[col] = df[col].astype(str).str.lower() == "true"

df["llm_ia_contexto"] = df["llm_ia_contexto"].fillna("Sem menção")
df["stack"] = df["stack"].fillna("")

faltando = [c for c in COLUNAS if c not in df.columns]
if faltando:
    raise SystemExit(f"ERRO: colunas ausentes na entrada: {faltando}")

df[COLUNAS].to_csv(SAIDA, index=False, encoding="utf-8", compression="gzip")
print(f"OK: {len(df)} vagas distintas em {SAIDA}")
