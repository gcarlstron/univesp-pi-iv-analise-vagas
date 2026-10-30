"""
Classificações com LLM local (Ollama), com cache para interromper e retomar.

Tarefas:
  senioridade  -> nível das vagas Indefinido/Divergente           (etapa 1)
  ia_contexto  -> o que a menção a IA significa naquela vaga        (etapa 2, IA)

Uso:
  python classificar_llm.py validar senioridade 200   # acurácia em vagas já rotuladas
  python classificar_llm.py rodar senioridade
  python classificar_llm.py rodar ia_contexto
  python classificar_llm.py juntar                     # gera vagas_enriquecidas_llm.csv

Pré-requisito: Ollama rodando (https://ollama.com) e o modelo baixado:
  ollama pull qwen2.5:7b
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

ENTRADA = "vagas_enriquecidas.csv"  # saída do enriquecimento_regras.py
SAIDA = "vagas_enriquecidas_llm.csv"
OLLAMA_URL = "http://localhost:11434/api/chat"
MODELO = "qwen2.5:7b"  # qualquer modelo instalado no Ollama
MAX_CHARS = 4000  # cobre ~90% das vagas inteiras; requisitos costumam vir no fim

TAREFAS = {
    "senioridade": {
        "valores": ["Estágio", "Júnior", "Pleno", "Sênior", "Indefinido"],
        "padrao": "Indefinido",
        "prompt": """Você classifica a senioridade de vagas de desenvolvimento de software no Brasil.
Responda SOMENTE com JSON: {"valor": "...", "evidencia": "..."}.
"valor" deve ser exatamente um de: Estágio, Júnior, Pleno, Sênior, Indefinido.
"evidencia": trecho curto (até 15 palavras) copiado da vaga que justifica a escolha.
Critérios:
- Use menção explícita ao nível quando existir (Jr, pleno, sênior, estágio).
- Sem menção explícita, use o tempo de experiência exigido: até 2 anos = Júnior; 2 a 5 = Pleno; mais de 5 = Sênior.
- Tech lead, especialista, staff, principal = Sênior.
- Se a vaga aceita vários níveis ou não há evidência suficiente: Indefinido. Não chute.""",
    },
    "ia_contexto": {
        "valores": ["Requisito do candidato", "Atividade da vaga", "Só empresa/processo", "Sem menção real"],
        "padrao": "Sem menção real",
        "prompt": """Você analisa vagas de desenvolvimento de software e diz o que a menção a Inteligência Artificial significa.
Responda SOMENTE com JSON: {"valor": "...", "evidencia": "..."}.
"valor" deve ser exatamente um de:
- "Requisito do candidato": a vaga EXIGE ou DESEJA que o candidato saiba usar ferramentas de IA ou conheça IA/ML/LLM.
- "Atividade da vaga": o trabalho envolve construir ou integrar soluções de IA (modelos, LLM, RAG, agentes, ML), sem listar isso como requisito.
- "Só empresa/processo": IA aparece apenas descrevendo a empresa, seu produto ou o processo seletivo (ex.: "usamos IA para analisar seu CV").
- "Sem menção real": a palavra apareceu por acaso (ex.: "ia" como verbo, sigla de outra coisa).
Se houver requisito E atividade, escolha "Requisito do candidato".
"evidencia": trecho curto (até 15 palavras) copiado da vaga.""",
    },
}


def cache_path(tarefa: str, modo: str) -> Path:
    return Path(f"cache_{tarefa}_{modo}_{MODELO.replace(':', '_').replace('/', '_')}.jsonl")


def carregar_cache(p: Path) -> pd.DataFrame:
    linhas = [json.loads(l) for l in p.open(encoding="utf-8")] if p.exists() else []
    return pd.DataFrame(linhas, columns=["url", "valor", "evidencia"]).drop_duplicates("url", keep="last")


def perguntar(tarefa: str, titulo: str, corpo: str) -> dict:
    cfg = TAREFAS[tarefa]
    payload = {
        "model": MODELO, "stream": False, "format": "json",
        "keep_alive": "30m",  # mantém o modelo carregado entre execuções
        # num_predict limita o tamanho da resposta (só precisamos de um JSON curto)
        "options": {"temperature": 0, "num_predict": 80, "num_ctx": 4096},
        "messages": [
            {"role": "system", "content": cfg["prompt"]},
            {"role": "user", "content": f"Título: {titulo}\n\nDescrição:\n{corpo[:MAX_CHARS]}"},
        ],
    }
    req = urllib.request.Request(OLLAMA_URL, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        conteudo = json.loads(r.read())["message"]["content"]
    try:
        resp = json.loads(conteudo)
    except json.JSONDecodeError:
        resp = {}
    valor = resp.get("valor")
    if valor not in cfg["valores"]:
        valor = cfg["padrao"]
    return {"valor": valor, "evidencia": str(resp.get("evidencia", ""))[:200]}


def processar(df: pd.DataFrame, tarefa: str, modo: str) -> pd.DataFrame:
    p = cache_path(tarefa, modo)
    feitos = set(carregar_cache(p)["url"])
    pendentes = df[~df["url"].isin(feitos)]
    print(f"{tarefa}: {len(df)} vagas | {len(feitos)} no cache | {len(pendentes)} a processar | {MODELO}")
    if len(pendentes):
        print("  (a 1ª vaga demora mais: o Ollama carrega o modelo na memória)")
    inicio = time.time()
    n = 0
    with p.open("a", encoding="utf-8") as f:
        try:
            for n, (url, tit, corpo) in enumerate(
                zip(pendentes["url"], pendentes["titulo_limpo"], pendentes["corpo_limpo"]), 1
            ):
                try:
                    r = {"url": url, **perguntar(tarefa, str(tit), str(corpo))}
                except Exception as e:  # Ollama fora do ar, timeout...: para e preserva o cache
                    print(f"\nERRO em {url}: {e}\nProgresso salvo; rode de novo para continuar.")
                    n -= 1
                    break
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
                if n == 1 or n % 10 == 0:
                    seg = (time.time() - inicio) / n
                    falta = (len(pendentes) - n) * seg / 60
                    print(f"  {n}/{len(pendentes)} | {seg:.1f}s por vaga | faltam ~{falta:.0f} min")
        except KeyboardInterrupt:
            n -= 1  # a vaga em andamento não foi salva
            print(f"\nInterrompido. {max(n, 0)} vaga(s) salvas nesta execução; rode de novo para continuar.")
            sys.exit(0)
    return df.merge(carregar_cache(p), on="url", how="inner")


def alvo(df: pd.DataFrame, tarefa: str) -> pd.DataFrame:
    # Só a postagem principal de cada vaga; repostagens herdam o resultado no "juntar".
    if tarefa == "senioridade":
        return df[df["eh_principal"] & df["nivel_consolidado"].isin(["Indefinido", "Divergente"])]
    return df[df["eh_principal"] & df["menciona_ia"]]


# Campo "Nível" do template (mesma linha ou lista abaixo). Na validação ele é
# removido do texto: as vagas Indefinido não têm esse campo, então o teste só é
# representativo se o modelo também tiver que inferir o nível sem ele.
RX_CAMPO_NIVEL = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*|\*\*)?\b(?:n[íi]vel(?:\s+de\s+experi[êe]ncia)?|senioridade)\b[^\n]*\n?"
    r"(?:(?:[ \t]*\n)*[ \t]*(?:[-*+•]|\d+[.)])[^\n]*\n?){0,8}",
    re.IGNORECASE | re.MULTILINE,
)


def remover_campo_nivel(texto) -> str:
    return RX_CAMPO_NIVEL.sub("", str(texto).replace("\r", ""))


def validar(tarefa: str, n: int):
    if tarefa != "senioridade":
        sys.exit("Para ia_contexto, valide manualmente: rode, abra o cache e confira ~50 linhas.")
    df = pd.read_csv(ENTRADA, low_memory=False)
    # Gabarito confiável: nível confirmado por 2+ fontes (fonte_unica=False), e que
    # NÃO veio do título (caso mais parecido com as Indefinido, que não têm nível no título).
    base = df[df["eh_principal"] & df["nivel_titulo"].isna() & ~df["fonte_unica"]
              & df["nivel_consolidado"].isin(["Estágio", "Júnior", "Pleno", "Sênior"])]
    print("Vagas disponíveis por nível para validação:", base["nivel_consolidado"].value_counts().to_dict())
    amostra = pd.concat([g.sample(min(len(g), n // 4), random_state=42) for _, g in base.groupby("nivel_consolidado")])
    amostra = amostra.assign(corpo_limpo=amostra["corpo_limpo"].map(remover_campo_nivel))
    res = processar(amostra, tarefa, "validacao")
    if res.empty:
        return
    decidiu = res["valor"] != "Indefinido"
    acertou = res["valor"] == res["nivel_consolidado"]
    print(f"\nAcurácia geral: {acertou.mean():.1%} (n={len(res)})")
    print(f"Cobertura (respondeu um nível): {decidiu.mean():.1%}")
    print(f"Precisão quando respondeu um nível: {acertou[decidiu].mean():.1%} (n={decidiu.sum()})")
    print("Linhas = rótulo original | colunas = LLM")
    print(pd.crosstab(res["nivel_consolidado"], res["valor"]).to_string())
    res.to_csv("validacao_senioridade.csv", index=False, encoding="utf-8-sig")


def rodar(tarefa: str):
    df = pd.read_csv(ENTRADA, low_memory=False)
    res = processar(alvo(df, tarefa), tarefa, "rodada")
    if not res.empty:
        print(res["valor"].value_counts().to_string())


def juntar():
    df = pd.read_csv(ENTRADA, low_memory=False)
    for tarefa in TAREFAS:
        res = carregar_cache(cache_path(tarefa, "rodada")).merge(df[["url", "grupo_vaga"]], on="url")
        res = res.drop(columns="url").drop_duplicates("grupo_vaga")
        res.columns = ["llm_" + tarefa, "llm_" + tarefa + "_evidencia", "grupo_vaga"]
        df = df.merge(res, on="grupo_vaga", how="left")

    usar = df["nivel_consolidado"].isin(["Indefinido", "Divergente"]) & df["llm_senioridade"].notna()
    df["nivel_com_ia"] = df["nivel_consolidado"].where(~usar, df["llm_senioridade"])
    df["origem_nivel"] = "Regra (coleta)"
    df.loc[usar, "origem_nivel"] = f"LLM ({MODELO})"
    # IA como exigência real: requisito do candidato ou atividade da vaga
    df["ia_exigida"] = df["llm_ia_contexto"].isin(["Requisito do candidato", "Atividade da vaga"])

    df.to_csv(SAIDA, index=False, encoding="utf-8-sig")
    p = df[df["eh_principal"]]
    print(f"OK: {SAIDA}\n\nVagas distintas por ano e nível:")
    print(pd.crosstab(p["ano"], p["nivel_com_ia"]).to_string())
    print("\n% com IA (palavra-chave x exigência real):")
    print(p.groupby("ano")[["menciona_ia", "ia_exigida"]].mean().mul(100).round(1).to_string())


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["juntar"]:
        juntar()
    elif len(a) >= 2 and a[0] in ("validar", "rodar") and a[1] in TAREFAS:
        validar(a[1], int(a[2]) if len(a) > 2 else 200) if a[0] == "validar" else rodar(a[1])
    else:
        print(__doc__)
