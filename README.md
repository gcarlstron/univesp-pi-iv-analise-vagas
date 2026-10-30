# PI IV — Requisitos em vagas júnior de TI (2021–2026)

Pipeline de dados do Projeto Integrador em Computação IV (UNIVESP). O objetivo é verificar se os requisitos das vagas de desenvolvedor júnior no Brasil mudaram entre 2021 e 2026, especialmente após a popularização da IA generativa.

Os dados vêm de vagas publicadas como *issues* em repositórios de comunidades brasileiras no GitHub, como `frontendbr/vagas` e `backend-br/vagas`.

---

## Visão geral

```
coletor_vagas.py            GitHub API  ->  vagas.csv
        │
higienizacao_preparacao.py  vagas.csv   ->  vagas_limpas_bi.csv   (LGPD, níveis, datas, flag IA)
        │
        ├── analise_exploratoria.py  ->  tabelas_analise/*.csv   (números do relatório)
        │
enriquecimento_regras.py    ->  vagas_enriquecidas.csv           (duplicatas, stack, salário, tipo de IA)
        │                       vagas_stack_long.csv
        │                       resumo_skills_ia_periodo.csv
        │
classificar_llm.py          ->  vagas_enriquecidas_llm.csv       (senioridade e contexto de IA via LLM)
        │
     Power BI
```

Cada script lê a saída do anterior. Todos devem ficar **na mesma pasta**.

---

## Pré-requisitos

| Item | Para quê | Como instalar |
|---|---|---|
| Python 3.12+ | todos os scripts | python.org |
| pandas | scripts 2 a 5 | `python -m pip install pandas` |
| Token do GitHub | coletor (passo 1) | github.com/settings/tokens, sem marcar nenhum escopo |
| Ollama + modelo | classificação com LLM (passo 5) | ollama.com, depois `ollama pull qwen2.5:7b` |

O ideal é usar um ambiente virtual:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install pandas
```

> No Windows, se o comando `pip` não for reconhecido, use sempre `python -m pip`.

---

## Ordem de execução

### 1. `coletor_vagas.py`: coleta

```powershell
$env:GITHUB_TOKEN="ghp_xxxxxxxx"
python .\coletor_vagas.py
```

**O que faz:** baixa todas as issues (abertas e fechadas) de 2021 a 2026 dos repositórios listados em `REPOS`. Também:
- deriva a senioridade por três fontes independentes: labels, campo do template e título;
- marca as menções a IA.

**Por quê:** os repositórios de vagas do GitHub guardam o histórico completo com data de publicação. Isso permite comparar o antes e o depois da IA generativa, coisa que portais de emprego não oferecem.

**Saídas:**

| Arquivo | Conteúdo |
|---|---|
| `vagas_brutas.jsonl` | registro cru, uma issue por linha |
| `vagas.csv` | tabela para o pandas |
| `coleta_estado.json` | controle de retomada; pode interromper e rodar de novo |

**Senioridade (`nivel_final`):** cada fonte só vota se apontar exatamente um nível.
- Duas ou mais fontes concordam: o resultado é o próprio nível (ex.: `junior`).
- Só uma fonte votou: o resultado ganha o sufixo `_fonte_unica`.
- Há empate entre fontes: `divergente`.
- Nenhuma fonte votou, mas alguma listou vários níveis (ex.: "Júnior / Pleno / Sênior"): `multinivel`.
- Nenhuma fonte trouxe nível: `indefinido`.

> **Correção aplicada:** até a versão anterior, o campo "Nível" do template era lido só no primeiro item da lista. Uma vaga com `- Júnior / - Pleno / - Sênior` virava "Júnior". Isso inflava o recorte júnior em ~95% (1.159 vagas, quando o real é ~594). Se o `vagas.csv` foi gerado antes da correção, regenere o arquivo (veja abaixo).
>
> **Para regenerar o CSV sem baixar tudo de novo:** mantenha o `vagas_brutas.jsonl` e o `coleta_estado.json` e rode o coletor outra vez. Todos os repositórios já constam como concluídos, então ele só remonta o `vagas.csv` com as regras novas.

> **Atenção:** o JSONL é aberto em modo *append*. Se a coleta for interrompida no meio de um repositório, esse repositório é baixado de novo e as linhas se repetem. Foi isso que gerou 1.658 linhas duplicadas do `frontendbr/vagas`. O `enriquecimento_regras.py` remove essas duplicatas. Para uma coleta do zero, apague antes os três arquivos de saída.

---

### 2. `higienizacao_preparacao.py`: limpeza e LGPD

```powershell
python .\higienizacao_preparacao.py
```

**O que faz:**
1. Remove e-mails e telefones do título e do corpo, gerando `corpo_limpo` e `titulo_limpo`. Os textos originais saem do arquivo.
2. Consolida a senioridade em `nivel_consolidado`: Estágio, Júnior, Pleno, Sênior, Multinível, Indefinido ou Divergente.
3. Converte as datas para o horário de Brasília e cria `ano` e `mes_ano`.
4. Recalcula a flag `menciona_ia`. As siglas (IA, AI, LLM, GPT, RAG) só contam em MAIÚSCULAS, para não confundir com o verbo "ia". A flag original da coleta fica em `menciona_ia_coleta`, para comparação.

**Por quê:** os anúncios trazem dados pessoais de recrutadores, e a LGPD exige removê-los antes de compartilhar a base. Além disso, a flag de IA da coleta gerava falsos positivos.

**Saídas:**
- `vagas_limpas_bi.csv`
- `divergencias_ia.csv`: vagas em que as duas flags de IA discordam, para revisão manual.

---

### 3. `analise_exploratoria.py`: números do relatório

```powershell
python .\analise_exploratoria.py
```

**O que faz:** reproduz a análise exploratória da base. Ele calcula:
- duplicatas e repostagens;
- volume por ano e nível;
- concentração de vagas por autor;
- percentual de menção a IA com e sem recrutadoras de alto volume;
- recorte júnior.

**Por quê:** deixa os números do relatório reproduzíveis. Qualquer integrante roda o script e chega nos mesmos valores.

**Saída:** `tabelas_analise/*.csv`, uma tabela por análise, prontas para o relatório.

Este script é independente dos passos 4 e 5 e pode rodar a qualquer momento depois do passo 2.

---

### 4. `enriquecimento_regras.py`: enriquecimento sem IA

```powershell
python .\enriquecimento_regras.py
```

**O que faz:**

| Etapa | Colunas geradas |
|---|---|
| Remove URLs duplicadas | — |
| Agrupa repostagens e cross-posts (mesmo autor e título no mesmo mês) | `grupo_vaga` (hash, não expõe o autor), `eh_principal`, `qtd_postagens_grupo` |
| Marca recrutadoras que publicam em massa (≥ 50 vagas/ano) | `vagas_autor_ano`, `autor_alto_volume` |
| Extrai a stack: labels do GitHub + regex, 34 tags padronizadas | `stack`, `qtd_tecnologias` |
| Extrai a faixa salarial, ignorando VR/VA/benefícios | `salario_min`, `salario_max`, `salario_fonte`, `tem_salario` |
| Classifica a menção a IA por regra | `tipo_ia` |
| Agrupa por período | `periodo` (2021-22, 2023-24, 2025-26) |

**Por quê:** stack e salário são extraídos por regra, e não por LLM, porque regra é determinística, gratuita e fácil de justificar na metodologia. A coluna `autor` é removida aqui.

**Saídas:**

| Arquivo | Uso |
|---|---|
| `vagas_enriquecidas.csv` | base com uma linha por postagem |
| `vagas_stack_long.csv` | uma linha por par vaga/tecnologia, para gráficos de stack no BI |
| `resumo_skills_ia_periodo.csv` | percentual de vagas que pede cada tecnologia, por período e com ou sem IA; base para os textos do dashboard |

---

### 5. `classificar_llm.py`: classificação com LLM local

O Ollama precisa estar instalado e rodando, e o modelo precisa estar baixado:

```powershell
ollama pull qwen2.5:7b        # ~4,7 GB; para máquinas fracas: qwen2.5:3b (troque MODELO no script)
```

Ordem dos comandos:

```powershell
python .\classificar_llm.py validar senioridade 200   # 1º: mede a acurácia
python .\classificar_llm.py rodar senioridade         # ~4,1 mil vagas
python .\classificar_llm.py rodar ia_contexto         # ~1,4 mil vagas
python .\classificar_llm.py juntar                    # gera a base final
```

**O que faz:**
- **`senioridade`:** classifica as vagas Indefinido e Divergente como Estágio, Júnior, Pleno, Sênior ou Indefinido. As vagas Multinível não passam pelo LLM, porque o nível delas já é conhecido: são abertas a vários.
- **`ia_contexto`:** classifica cada menção a IA como *Requisito do candidato*, *Atividade da vaga*, *Só empresa/processo* ou *Sem menção real*.
- **`validar`:** testa o modelo em vagas cujo nível foi confirmado por duas ou mais fontes (gabarito confiável) e mostra a acurácia e a matriz de confusão.
- **`juntar`:** junta os resultados à base. As repostagens herdam a classificação da postagem principal.

**Por quê:**
- **Senioridade:** um terço da base estava sem nível definido. Sem classificar essas vagas, o recorte júnior fica ainda menor.
- **Contexto de IA:** palavra-chave não diferencia uma vaga que exige IA de uma empresa que só *usa* IA. Em 2026, um único recrutador publicou 36% das vagas, e o texto padrão dele cita IA no processo seletivo. Isso inflava a métrica de 40% para 61%.

**Saídas:**
- `vagas_enriquecidas_llm.csv`, a base final para o Power BI. Novas colunas:
  - `nivel_com_ia` e `origem_nivel`;
  - `llm_senioridade` e `llm_ia_contexto`, com as evidências;
  - `ia_exigida`.
- `cache_*.jsonl`: as respostas do modelo. **Guarde esses arquivos.** Eles documentam o que o LLM respondeu e permitem refazer o `juntar` sem rodar o modelo de novo.
- `validacao_senioridade.csv`: resultado da validação.

O processamento pode ser interrompido com **Ctrl+C**. Ao rodar de novo, ele continua de onde parou.

**Tempo estimado:** com GPU, ~1–2 s por vaga (2–4 h no total). Só com CPU, 5–15 s por vaga, então deixe rodando de noite.

---

## Cuidados na análise

1. **Conte vagas distintas:** filtre `eh_principal = True` para não contar cross-posts em dobro.
2. **Use percentuais, não contagens:** o volume cai de ~8 mil vagas em 2021 para ~650 em 2026.
3. **Recorte júnior pequeno:** são só ~32 vagas em 2026. Cite isso como limitação no relatório.
4. **Faça análise de sensibilidade:** compare os resultados com e sem `autor_alto_volume`.
5. **Prefira `ia_exigida` a `menciona_ia`** como métrica principal de IA.
6. **Registre a acurácia do `validar`** na metodologia, junto com o modelo usado e a data.

---

## Problemas comuns

| Erro | Solução |
|---|---|
| `pip` não é reconhecido | use `python -m pip install pandas` |
| `ModuleNotFoundError: pandas` | instale o pandas no mesmo Python que roda o script, ou ative a `.venv` |
| `KeyError` em alguma coluna | confira a lista "Colunas encontradas" impressa pelo `higienizacao_preparacao.py` |
| `Connection refused` no `classificar_llm.py` | o Ollama não está rodando; abra o app ou rode `ollama serve` |
| Coletor parado em "limite atingido" | é o rate limit do GitHub; o script espera sozinho. Sem token, o limite é de 60 req/h |
| pandas falha ao instalar no Python muito recente | use uma versão estável, como 3.12 ou 3.13, via `py -3.13 -m venv .venv` |
