"""
Dashboard do PI IV: requisitos em vagas de desenvolvimento no Brasil (2021–2026).

Rodar localmente:
    python -m streamlit run app.py
"""
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DADOS = Path(__file__).parent / "dados_dashboard.csv.gz"

# Paleta: níveis de entrada em verde-petróleo (foco da pesquisa), demais em cinza-azulado;
# IA em violeta, para não competir com os níveis.
CORES_NIVEL = {
    "Estágio": "#5EB1A9",
    "Júnior": "#0F766E",
    "Pleno": "#94A3B8",
    "Sênior": "#475569",
    "Multinível": "#CBD5E1",
    "Indefinido": "#E2E8F0",
    "Divergente": "#F1F5F9",
}
ORDEM_NIVEL = list(CORES_NIVEL)
COR_IA = "#7C3AED"
COR_IA_CLARA = "#C4B5FD"
CORES_CONTEXTO = {
    "Requisito do candidato": "#7C3AED",
    "Atividade da vaga": "#A78BFA",
    "Só empresa/processo": "#CBD5E1",
    "Sem menção real": "#E2E8F0",
}
PERIODOS = ["2021-22", "2023-24", "2025-26"]
N_MINIMO = 30  # abaixo disso, o percentual é marcado como instável

st.set_page_config(page_title="Vagas júnior e IA — PI IV", page_icon="📊", layout="wide")


def estilo(fig: go.Figure, altura: int = 380, eixo_ano: bool = False) -> go.Figure:
    fig.update_layout(
        template="simple_white",
        height=altura,
        margin=dict(l=10, r=10, t=30, b=10),
        font=dict(size=13, color="#1E293B"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None),
        hoverlabel=dict(bgcolor="white"),
        separators=",.",  # vírgula decimal, ponto de milhar
    )
    fig.update_xaxes(title=None)
    if eixo_ano:  # um rótulo por ano, sem "2021.5"
        fig.update_xaxes(dtick=1, tickformat="d")
    return fig


@st.cache_data
def carregar() -> pd.DataFrame:
    df = pd.read_csv(DADOS, low_memory=False)
    df["ano"] = df["ano"].astype(int)
    df["stack"] = df["stack"].fillna("")
    return df


def pct(serie: pd.Series) -> float:
    return float(serie.mean() * 100) if len(serie) else float("nan")


def br_int(n) -> str:
    """16537 -> '16.537'"""
    return f"{int(n):,}".replace(",", ".")


def br_pct(x: float) -> str:
    """12.63 -> '12,6%'"""
    return f"{x:.1f}%".replace(".", ",")


# ------------------------------------------------------------------ dados e filtros
if not DADOS.exists():
    st.error(
        f"Arquivo {DADOS.name} não encontrado. Rode `python preparar_dashboard.py` "
        "na mesma pasta do app para gerá-lo."
    )
    st.stop()

base = carregar()

with st.sidebar:
    st.header("Filtros")
    anos = st.slider("Anos", int(base["ano"].min()), int(base["ano"].max()),
                     (int(base["ano"].min()), int(base["ano"].max())))
    usar_llm = st.toggle(
        "Incluir senioridade atribuída pelo LLM", value=True,
        help="Vagas sem nível identificado por regra que o modelo classificou "
             "(precisão de 89,9% na validação).",
    )
    sem_alto_volume = st.toggle(
        "Excluir recrutadoras de alto volume", value=False,
        help="Autores com 50 ou mais vagas no ano. Em 2026, um único recrutador "
             "publicou 36,5% das vagas.",
    )
    repos = st.multiselect("Repositórios", sorted(base["repo"].unique()),
                           placeholder="Todos")
    st.caption("Contagens sempre de vagas distintas: repostagens e cross-posts "
               "contam uma vez.")

col_nivel = "nivel_com_ia" if usar_llm else "nivel_consolidado"
df = base[base["ano"].between(*anos)].copy()
if sem_alto_volume:
    df = df[~df["autor_alto_volume"]]
if repos:
    df = df[df["repo"].isin(repos)]
df["nivel"] = pd.Categorical(df[col_nivel], ORDEM_NIVEL, ordered=True)

if df.empty:
    st.warning("Nenhuma vaga com esses filtros. Amplie o intervalo de anos ou os repositórios.")
    st.stop()

# ------------------------------------------------------------------ cabeçalho
st.title("O que as vagas júnior de TI passaram a exigir (2021–2026)")

ini, fim = df[df["periodo"] == PERIODOS[0]], df[df["periodo"] == PERIODOS[-1]]
if len(ini) and len(fim):
    st.markdown(
        f"Em **2025–26**, **{br_pct(pct(fim['ia_exigida']))}** das vagas exigiam IA do candidato "
        f"ou envolviam desenvolver IA, contra **{br_pct(pct(ini['ia_exigida']))}** em 2021–22. "
        f"No mesmo intervalo, o número de vagas publicadas caiu de "
        f"{br_int(len(ini))} para {br_int(len(fim))}."
    )
st.caption("Fonte: 16 repositórios de vagas de comunidades brasileiras no GitHub. "
           "Projeto Integrador IV, UNIVESP.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Vagas distintas", br_int(len(df)))
c2.metric("Vagas júnior", br_int((df["nivel"] == "Júnior").sum()))
c3.metric("Exigem IA", br_pct(pct(df["ia_exigida"])))
c4.metric("Tecnologias por vaga (média)", f"{df['qtd_tecnologias'].mean():.1f}".replace(".", ","))

aba_geral, aba_ia, aba_jr, aba_tec, aba_sal, aba_vagas, aba_sobre = st.tabs(
    ["Visão geral", "Inteligência artificial", "Recorte júnior", "Tecnologias",
     "Salários", "Explorar vagas", "Sobre os dados"]
)

# ------------------------------------------------------------------ visão geral
with aba_geral:
    esq, dir_ = st.columns(2)
    por_ano = df.groupby("ano").size().reset_index(name="vagas")
    fig = px.bar(por_ano, x="ano", y="vagas", color_discrete_sequence=["#475569"],
                 labels={"vagas": "Vagas distintas"})
    esq.subheader("Vagas publicadas por ano")
    esq.plotly_chart(estilo(fig, eixo_ano=True), width="stretch")

    comp = (df.groupby(["ano", "nivel"], observed=True).size()
              .groupby(level=0).transform(lambda s: s / s.sum() * 100)
              .reset_index(name="pct"))
    fig = px.bar(comp, x="ano", y="pct", color="nivel", color_discrete_map=CORES_NIVEL,
                 category_orders={"nivel": ORDEM_NIVEL},
                 labels={"pct": "% das vagas do ano", "nivel": "Nível"})
    fig.update_traces(hovertemplate="%{x}: %{y:.1f}%")
    dir_.subheader("Composição por senioridade")
    dir_.plotly_chart(estilo(fig, eixo_ano=True), width="stretch")
    st.caption("A queda no volume muda o peso de cada ano: compare percentuais, não contagens.")

# ------------------------------------------------------------------ IA
with aba_ia:
    st.subheader("Vagas com IA, por ano")
    g = df.groupby("ano").agg(n=("url", "size"), menciona=("menciona_ia", "mean"),
                              exigida=("ia_exigida", "mean")).reset_index()
    fig = go.Figure()
    fig.add_scatter(x=g["ano"], y=g["menciona"] * 100, name="Cita IA no texto",
                    mode="lines+markers", line=dict(color=COR_IA_CLARA, width=3),
                    customdata=g["n"], hovertemplate="%{x}: %{y:.1f}% (n=%{customdata})")
    fig.add_scatter(x=g["ano"], y=g["exigida"] * 100, name="Exige ou envolve IA",
                    mode="lines+markers", line=dict(color=COR_IA, width=3),
                    customdata=g["n"], hovertemplate="%{x}: %{y:.1f}% (n=%{customdata})")
    fig.update_yaxes(title="% das vagas do ano", rangemode="tozero")
    st.plotly_chart(estilo(fig, 400, eixo_ano=True), width="stretch")
    st.caption("“Cita IA” conta qualquer menção. “Exige ou envolve IA” considera só as vagas "
               "em que o LLM identificou IA como requisito do candidato ou atividade do cargo. "
               "A diferença entre as linhas são menções à própria empresa ou ao processo seletivo.")

    st.subheader("O que a menção a IA significa")
    ctx = df[df["menciona_ia"]]
    if len(ctx):
        cg = (ctx.groupby(["ano", "llm_ia_contexto"]).size()
                 .groupby(level=0).transform(lambda s: s / s.sum() * 100)
                 .reset_index(name="pct"))
        fig = px.bar(cg, x="ano", y="pct", color="llm_ia_contexto",
                     color_discrete_map=CORES_CONTEXTO,
                     category_orders={"llm_ia_contexto": list(CORES_CONTEXTO)},
                     labels={"pct": "% das vagas que citam IA", "llm_ia_contexto": "Contexto"})
        fig.update_traces(hovertemplate="%{x}: %{y:.1f}%")
        st.plotly_chart(estilo(fig, 380, eixo_ano=True), width="stretch")
        st.caption("Ative “Excluir recrutadoras de alto volume” para ver o efeito do texto "
                   "padrão de um único recrutador em 2026.")

# ------------------------------------------------------------------ júnior
with aba_jr:
    recorte = st.radio(
        "Recorte", ["Só vagas Júnior", "Júnior + vagas multinível que aceitam júnior"],
        horizontal=True,
    )
    jr = df[df["nivel"] == "Júnior"] if recorte.startswith("Só") else df[df["aceita_junior"]]
    resto = df.drop(jr.index)

    t = (pd.concat([jr.assign(grupo="Júnior"), resto.assign(grupo="Demais vagas")])
           .groupby(["ano", "grupo"])
           .agg(n=("url", "size"), ia=("ia_exigida", "mean"), tec=("qtd_tecnologias", "mean"))
           .reset_index())
    t["ia"] *= 100

    esq, dir_ = st.columns(2)
    for alvo, coluna, titulo, eixo in [
        (esq, "tec", "Tecnologias por vaga (média)", "Tecnologias"),
        (dir_, "ia", "Vagas que exigem ou envolvem IA", "% das vagas"),
    ]:
        fig = px.line(t, x="ano", y=coluna, color="grupo", markers=True, custom_data=["n"],
                      color_discrete_map={"Júnior": "#0F766E", "Demais vagas": "#94A3B8"},
                      labels={coluna: eixo})
        fig.update_traces(hovertemplate="%{x}: %{y:.1f} (n=%{customdata[0]})", line=dict(width=3))
        fig.update_yaxes(rangemode="tozero")
        alvo.subheader(titulo)
        alvo.plotly_chart(estilo(fig, eixo_ano=True), width="stretch")

    n_ano = jr.groupby("ano").size()
    fracos = n_ano[n_ano < N_MINIMO]
    if len(fracos):
        st.warning(
            "Poucas vagas júnior em " + ", ".join(f"{a} (n={n})" for a, n in fracos.items())
            + f". Com menos de {N_MINIMO} vagas, os percentuais desses anos são instáveis: "
              "trate como indício, não como conclusão."
        )
    st.dataframe(
        t.pivot(index="ano", columns="grupo", values="n").rename_axis(None, axis=1),
        column_config={c: st.column_config.NumberColumn(f"Vagas ({c})") for c in ["Júnior", "Demais vagas"]},
    )

# ------------------------------------------------------------------ tecnologias
with aba_tec:
    nivel_tec = st.selectbox("Nível", ["Todos"] + ORDEM_NIVEL[:5], index=0)
    base_tec = df if nivel_tec == "Todos" else df[df["nivel"] == nivel_tec]
    longo = base_tec.assign(tecnologia=base_tec["stack"].str.split("|")).explode("tecnologia")
    longo = longo[longo["tecnologia"].fillna("") != ""]
    tot = base_tec.groupby("periodo").size()
    freq = (longo.groupby(["periodo", "tecnologia"]).size()
                 .div(tot, level="periodo").mul(100).rename("pct").reset_index())

    if freq.empty:
        st.info("Sem tecnologias para esse filtro.")
    else:
        esq, dir_ = st.columns([3, 2])
        top = (freq.groupby("tecnologia")["pct"].mean().nlargest(15).index)
        f_top = freq[freq["tecnologia"].isin(top)]
        fig = px.bar(f_top, y="tecnologia", x="pct", color="periodo", barmode="group",
                     orientation="h", category_orders={"periodo": PERIODOS, "tecnologia": list(top)},
                     color_discrete_sequence=["#CBD5E1", "#94A3B8", "#0F766E"],
                     labels={"pct": "% das vagas do período", "periodo": "Período"})
        fig.update_traces(hovertemplate="%{y}: %{x:.1f}%")
        fig.update_yaxes(title=None)
        esq.subheader("15 tecnologias mais pedidas")
        esq.plotly_chart(estilo(fig, 560), width="stretch")

        piv = freq.pivot(index="tecnologia", columns="periodo", values="pct").fillna(0)
        if {PERIODOS[0], PERIODOS[-1]} <= set(piv.columns):
            var = (piv[PERIODOS[-1]] - piv[PERIODOS[0]]).rename("pp").reset_index()
            var = pd.concat([var.nlargest(8, "pp"), var.nsmallest(8, "pp")]).drop_duplicates()
            var = var.sort_values("pp")
            fig = px.bar(var, y="tecnologia", x="pp", orientation="h",
                         color=var["pp"] > 0,
                         color_discrete_map={True: "#0F766E", False: "#94A3B8"},
                         labels={"pp": "Variação (pontos percentuais)"})
            fig.update_traces(hovertemplate="%{y}: %{x:+.1f} p.p.")
            fig.update_layout(showlegend=False)
            fig.update_yaxes(title=None)
            dir_.subheader("O que mais ganhou e perdeu espaço")
            dir_.plotly_chart(estilo(fig, 560), width="stretch")
            dir_.caption("Diferença entre a % de vagas que pedem a tecnologia em 2025–26 e em 2021–22.")

# ------------------------------------------------------------------ salários
with aba_sal:
    sal = df[df["tem_salario"]].copy()
    st.markdown(f"Só **{br_pct(pct(df['tem_salario']))}** das vagas informam salário. "
                "Os valores abaixo valem para esse subconjunto.")
    if len(sal):
        sal["salario_medio"] = (sal["salario_min"] + sal["salario_max"]) / 2
        sal = sal[sal["nivel"].isin(["Estágio", "Júnior", "Pleno", "Sênior"])]
        s = (sal.groupby(["periodo", "nivel"], observed=True)["salario_medio"]
                .agg(mediana="median", n="size").reset_index())
        s = s[s["n"] >= 5]
        fig = px.bar(s, x="nivel", y="mediana", color="periodo", barmode="group",
                     custom_data=["n"], category_orders={"periodo": PERIODOS, "nivel": ORDEM_NIVEL},
                     color_discrete_sequence=["#CBD5E1", "#94A3B8", "#0F766E"],
                     labels={"mediana": "Mediana do ponto médio da faixa (R$)", "periodo": "Período",
                             "nivel": "Nível"})
        fig.update_traces(hovertemplate="%{x}: R$ %{y:,.0f} (n=%{customdata[0]})")
        st.plotly_chart(estilo(fig, 400), width="stretch")
        st.caption("Grupos com menos de 5 vagas foram omitidos. Valores nominais, sem correção pela inflação.")

# ------------------------------------------------------------------ explorar
with aba_vagas:
    busca = st.text_input("Buscar no título ou nas tecnologias", placeholder="ex.: React, Python, júnior")
    tabela = df
    if busca:
        alvo = tabela["titulo_limpo"].fillna("") + " " + tabela["stack"]
        tabela = tabela[alvo.str.contains(busca, case=False, regex=False)]
    st.caption(f"{br_int(len(tabela))} vagas")
    st.dataframe(
        tabela.sort_values("ano", ascending=False)[
            ["ano", "titulo_limpo", "nivel", "ia_exigida", "stack", "repo", "url"]],
        hide_index=True, width="stretch", height=520,
        column_config={
            "ano": st.column_config.NumberColumn("Ano", format="%d"),
            "titulo_limpo": "Título",
            "nivel": "Nível",
            "ia_exigida": st.column_config.CheckboxColumn("Exige IA"),
            "stack": "Tecnologias",
            "repo": "Repositório",
            "url": st.column_config.LinkColumn("Anúncio", display_text="abrir"),
        },
    )

# ------------------------------------------------------------------ sobre
with aba_sobre:
    st.markdown(
        """
**Fonte.** Vagas publicadas como *issues* em 16 repositórios de comunidades brasileiras de
desenvolvimento no GitHub, de janeiro de 2021 a outubro de 2026, coletadas pela API do GitHub.

**Tratamento.** Remoção de e-mails, telefones e autores (LGPD); exclusão de registros duplicados;
repostagens e cross-posts contados uma vez.

**Senioridade.** Identificada por etiquetas, campo “Nível” do anúncio e título. Vagas sem nível
foram classificadas pelo modelo Qwen2.5 14B, que teve 89,9% de precisão e 52% de cobertura
na validação. As que o modelo não conseguiu classificar seguem como Indefinidas.

**IA.** “Cita IA” usa palavras-chave. “Exige ou envolve IA” usa a classificação do modelo
sobre o contexto da menção: requisito do candidato ou atividade do cargo.

**Limitações.** Os repositórios do GitHub representam parte do mercado. O volume de vagas
caiu cerca de 92% entre 2021 e 2026, e o recorte júnior de 2026 tem poucas vagas.
"""
    )
