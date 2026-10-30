#!/usr/bin/env python3
"""
Coletor de vagas publicadas como issues em repositórios do GitHub.

Baixa título, corpo, data, labels e autor de todas as issues (abertas e fechadas)
dos repositórios listados, deriva o nível de senioridade por três vias
independentes (labels, campo do template e título) e deteta menções a Inteligência Artificial.

Uso:
    set GITHUB_TOKEN=ghp_xxxxxxxx        (Windows CMD)
    $env:GITHUB_TOKEN="ghp_xxxxxxxx"     (PowerShell)
    export GITHUB_TOKEN=ghp_xxxxxxxx     (Linux/Mac)

    python3 coletor_vagas.py

Saídas:
    vagas_brutas.jsonl    registro cru de cada issue, um JSON por linha
    vagas.csv             tabela pronta para o pandas (UTF-8 com BOM, abre no Excel)
    coleta_estado.json    controle de retomada
"""

import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# --------------------------------------------------------------- configuração

REPOS = [
    # Repositórios Principais / Comunidades
    "frontendbr/vagas",
    "backend-br/vagas",
    "react-brasil/vagas",
    "androiddevbr/vagas",
    "phpdevbr/vagas",
    "soujava/vagas-java",
    "qa-brasil/vagas",
    "dotnetdevbr/vagas",
    "vuejs-br/vagas",
    "DevOps-Brasil/Vagas",
    "datascience-br/vagas",
    "flutterbr/vagas",
    "CocoaHeadsBrasil/vagas",
    "pythonsul/vagas",
    "clojure-br/vagas",
    "rustdevbr/vagas",
    "GopherconBrasil/vagas",
    "kotlin-br/vagas",
    "alinebastos/vagas-junior-estagio",
    "remotejobsbr/vagas",
    "UIUX-BR/vagas",
]

ANO_MIN = 2021          # descarta issues anteriores
ANO_MAX = 2026

ARQ_JSONL = "vagas_brutas.jsonl"
ARQ_CSV = "vagas.csv"
ARQ_ESTADO = "coleta_estado.json"

TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
API = "https://api.github.com"

# --------------------------------------------------------------- senioridade

# A ordem importa: estágio antes de júnior, para evitar sobreposição em termos ambíguos
NIVEIS = [
    ("estagio", [r"\best[áa]gi[oá]ri[oa]\b", r"\best[áa]gio\b", r"\btrainee\b", r"\bintern\b"]),
    ("junior",  [r"\bj[úu]nior\b", r"\bjr\b", r"\biniciante\b", r"\bentry[\s-]?level\b"]),
    ("pleno",   [r"\bpleno\b", r"\bpl\b", r"\bmid[\s-]?level\b", r"\bintermedi[áa]rio\b"]),
    ("senior",  [r"\bs[êe]nior\b", r"\bsr\b", r"\bespecialista\b"]),
]

# Expressões regulares para detecção de IA
TERMOS_IA = [
    (r"\bcopilot\b", "copilot"),
    (r"\bchatgpt\b", "chatgpt"),
    (r"\bgpt-?4\b", "gpt-4"),
    (r"\bgpt-?3\.?:?5?\b", "gpt-3.5"),
    (r"\bllm\b", "llm"),
    (r"\bllms\b", "llms"),
    (r"\bopenai\b", "openai"),
    (r"\banthropic\b", "anthropic"),
    (r"\bclaude\b", "claude"),
    (r"\bcursor\b", "cursor"),
    (r"\bprompt\b", "prompt engineering"),
    (r"intelig[êe]ncia artificial", "inteligencia artificial"),
    (r"\bia\b", "ia"),
    (r"\bai\b", "ai"),
    (r"machine learning", "machine learning"),
    (r"langchain", "langchain"),
    (r"genai", "genai"),
    (r"generative ai", "generative ai"),
    (r"ia generativa", "ia generativa"),
]

# Linha de template na MESMA linha: "Nivel: Junior", "**Senioridade:** Pleno / Sênior".
# [ \t]* (e não \s*) impede que a busca pule para a linha de baixo.
RE_CAMPO = re.compile(
    r"\b(?:n[íi]vel(?:\s+de\s+experi[êe]ncia)?|senioridade)[ \t]*\**[ \t]*[:\-–][ \t]*\**[ \t]*([^\n\r]{1,80})",
    re.IGNORECASE,
)
# Cabeçalho seguido de uma LISTA nas linhas de baixo:
#   #### Nível
#   - Júnior
#   - Pleno
# Captura todos os itens da lista (até 8), não só o primeiro. Antes, só o
# primeiro item era lido e vagas multinível viravam "Júnior" por engano.
RE_CABECALHO = re.compile(
    r"(?:^|\n)[ \t]*(?:#{1,6}[ \t]*|\*\*)?\b(?:n[íi]vel(?:\s+de\s+experi[êe]ncia)?|senioridade)\b[^\n]*\n"
    r"((?:[ \t]*\n)*(?:[ \t]*(?:[-*+•]|\d+[.)])[^\n]*(?:\n|$)){1,8})",
    re.IGNORECASE,
)


def niveis_em(texto):
    """Retorna o conjunto de níveis mencionados no texto."""
    if not texto:
        return set()
    achados = set()
    for nome, padroes in NIVEIS:
        for p in padroes:
            if re.search(p, texto, re.IGNORECASE):
                achados.add(nome)
                break
    return achados


def nivel_por_campo(corpo):
    """Procura o campo do template que declara o nível (mesma linha ou lista abaixo)."""
    if not corpo:
        return set()
    corpo = corpo.replace("\r", "")
    m = RE_CABECALHO.search(corpo)
    if m:
        achados = niveis_em(m.group(1))
        if achados:
            return achados
    m = RE_CAMPO.search(corpo)
    if m:
        return niveis_em(m.group(1))
    return set()


def consenso(por_label, por_campo, por_titulo):
    """
    Decide o nível final. Só conta o voto de uma fonte que apontou
    exatamente um nível; fonte ambígua ou vazia não vota.
    Retornos: <nivel>, <nivel>_fonte_unica, divergente, multinivel, indefinido.
    """
    votos = {}
    for fonte in (por_label, por_campo, por_titulo):
        if len(fonte) == 1:
            n = next(iter(fonte))
            votos[n] = votos.get(n, 0) + 1
    if not votos:
        # Nenhuma fonte apontou um nível único. Se alguma listou vários
        # (ex.: "Júnior / Pleno / Sênior"), a vaga é multinível, não indefinida.
        if any(len(f) > 1 for f in (por_label, por_campo, por_titulo)):
            return "multinivel"
        return "indefinido"
    maximo = max(votos.values())
    vencedores = [n for n, v in votos.items() if v == maximo]
    if len(vencedores) > 1:
        return "divergente"
    if maximo >= 2:
        return vencedores[0]
    return vencedores[0] + "_fonte_unica"


def detectar_ia(texto):
    """Deteta se há menção a IA/LLM no texto e quais os termos identificados."""
    if not texto:
        return False, []
    achados = set()
    for padrao, rotulo in TERMOS_IA:
        if re.search(padrao, texto, re.IGNORECASE):
            achados.add(rotulo)
    return len(achados) > 0, sorted(list(achados))


# --------------------------------------------------------------- rede

def requisicao(url):
    """GET na API, respeitando limites de taxa. Retorna (dados, link_proximo)."""
    for tentativa in range(6):
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "PI-IV-coletor")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if TOKEN:
            req.add_header("Authorization", "Bearer " + TOKEN)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                dados = json.load(r)
                restante = r.headers.get("X-RateLimit-Remaining")
                if restante is not None and int(restante) < 5:
                    reset = int(r.headers.get("X-RateLimit-Reset", "0"))
                    espera = max(reset - int(time.time()), 0) + 5
                    print(f"    limite quase no fim, aguardando {espera}s...")
                    time.sleep(espera)
                return dados, proximo_link(r.headers.get("Link", ""))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, None
            if e.code in (403, 429):
                retry = e.headers.get("Retry-After")
                if retry:
                    espera = int(retry) + 2
                else:
                    reset = int(e.headers.get("X-RateLimit-Reset", "0"))
                    espera = max(reset - int(time.time()), 0) + 5 or 60
                print(f"    limite atingido, aguardando {espera}s...")
                time.sleep(espera)
                continue
            print(f"    HTTP {e.code} em {url}", file=sys.stderr)
            time.sleep(10)
        except Exception as e:
            print(f"    erro de rede: {e}", file=sys.stderr)
            time.sleep(10)
    return None, None


def proximo_link(cabecalho):
    """Extrai a URL rel=\"next\" do cabeçalho Link."""
    if not cabecalho:
        return None
    for parte in cabecalho.split(","):
        if 'rel="next"' in parte:
            inicio = parte.find("<")
            fim = parte.find(">")
            if inicio != -1 and fim != -1:
                return parte[inicio + 1:fim]
    return None


# --------------------------------------------------------------- coleta

def carregar_estado():
    if os.path.exists(ARQ_ESTADO):
        try:
            with open(ARQ_ESTADO, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"concluidos": []}


def salvar_estado(estado):
    with open(ARQ_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def coletar_repo(repo, saida):
    """Baixa todas as issues do repositório e grava no JSONL. Retorna a contagem."""
    url = (f"{API}/repos/{repo}/issues?state=all&per_page=100"
           f"&sort=created&direction=asc")
    total = 0
    pagina = 0
    while url:
        pagina += 1
        dados, proxima = requisicao(url)
        if dados is None:
            print(f"    repositório inacessível ou não encontrado, pulando")
            return -1
        if not isinstance(dados, list) or not dados:
            break
        for it in dados:
            # A API de issues devolve pull requests junto; são descartados.
            if "pull_request" in it:
                continue
            criado = it.get("created_at") or ""
            ano = int(criado[:4]) if criado[:4].isdigit() else 0
            if ano < ANO_MIN or ano > ANO_MAX:
                continue
            reg = {
                "repo": repo,
                "numero": it.get("number"),
                "titulo": it.get("title") or "",
                "corpo": it.get("body") or "",
                "autor": (it.get("user") or {}).get("login") or "",
                "criado_em": criado,
                "fechado_em": it.get("closed_at") or "",
                "estado": it.get("state") or "",
                "labels": [l.get("name", "") for l in (it.get("labels") or [])],
                "comentarios": it.get("comments", 0),
                "url": it.get("html_url") or "",
            }
            saida.write(json.dumps(reg, ensure_ascii=False) + "\n")
            total += 1
        print(f"    página {pagina}: {total} vagas até agora")
        saida.flush()
        url = proxima
    return total


def gerar_csv():
    """Lê o JSONL e escreve a tabela final com níveis derivados e análise de IA."""
    colunas = [
        "repo", "numero", "url", "titulo", "autor", "criado_em", "ano", "mes",
        "fechado_em", "estado", "comentarios", "labels",
        "nivel_label", "nivel_campo", "nivel_titulo", "nivel_final",
        "menciona_ia", "termos_ia", "tamanho_corpo", "corpo"
    ]
    linhas = 0
    resumo_nivel = {}
    por_ano_nivel = {}
    ia_por_ano = {}
    ia_por_nivel = {}

    with open(ARQ_JSONL, encoding="utf-8") as ent, \
         open(ARQ_CSV, "w", encoding="utf-8-sig", newline="") as sai:
        w = csv.DictWriter(sai, fieldnames=colunas, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for linha in ent:
            linha = linha.strip()
            if not linha:
                continue
            r = json.loads(linha)
            corpo = r.get("corpo") or ""
            titulo = r.get("titulo") or ""
            rotulos = " ".join(r.get("labels") or [])

            por_label = niveis_em(rotulos)
            por_campo = nivel_por_campo(corpo)
            por_titulo = niveis_em(titulo)
            final = consenso(por_label, por_campo, por_titulo)

            # Detecção de IA
            texto_completo = f"{titulo}\n{rotulos}\n{corpo}"
            tem_ia, termos = detectar_ia(texto_completo)

            criado = r.get("criado_em") or ""
            ano = criado[:4]

            w.writerow({
                "repo": r.get("repo", ""),
                "numero": r.get("numero", ""),
                "url": r.get("url", ""),
                "titulo": titulo,
                "autor": r.get("autor", ""),
                "criado_em": criado,
                "ano": ano,
                "mes": criado[:7],
                "fechado_em": r.get("fechado_em", ""),
                "estado": r.get("estado", ""),
                "comentarios": r.get("comentarios", 0),
                "labels": "|".join(r.get("labels") or []),
                "nivel_label": "|".join(sorted(por_label)),
                "nivel_campo": "|".join(sorted(por_campo)),
                "nivel_titulo": "|".join(sorted(por_titulo)),
                "nivel_final": final,
                "menciona_ia": tem_ia,
                "termos_ia": "|".join(termos),
                "tamanho_corpo": len(corpo),
                "corpo": corpo,
            })
            linhas += 1

            # Estatísticas
            resumo_nivel[final] = resumo_nivel.get(final, 0) + 1
            por_ano_nivel.setdefault(ano, {})
            por_ano_nivel[ano][final] = por_ano_nivel[ano].get(final, 0) + 1

            if tem_ia:
                ia_por_ano[ano] = ia_por_ano.get(ano, 0) + 1
                ia_por_nivel[final] = ia_por_nivel.get(final, 0) + 1

    return linhas, resumo_nivel, por_ano_nivel, ia_por_ano, ia_por_nivel


def main():
    if not TOKEN:
        print("AVISO: sem GITHUB_TOKEN. Limite de 60 requisições por hora.")
        print("       A coleta provavelmente não vai terminar. Gere um token em")
        print("       github.com/settings/tokens (sem marcar nenhum escopo).\n")

    estado = carregar_estado()
    concluidos = set(estado.get("concluidos", []))
    if concluidos:
        print(f"Retomando. Já concluídos: {len(concluidos)} repositório(s).\n")

    inicio = time.time()
    with open(ARQ_JSONL, "a", encoding="utf-8") as saida:
        for repo in REPOS:
            if repo in concluidos:
                print(f"{repo}  (já coletado, pulando)")
                continue
            print(f"{repo}")
            n = coletar_repo(repo, saida)
            if n >= 0:
                print(f"    concluído: {n} vagas\n")
            concluidos.add(repo)
            estado["concluidos"] = sorted(concluidos)
            salvar_estado(estado)

    print("=" * 52)
    print("Montando a tabela final com análise de IA...")
    linhas, resumo_nivel, por_ano_nivel, ia_por_ano, ia_por_nivel = gerar_csv()

    print(f"\n{linhas} vagas gravadas em {ARQ_CSV}")
    print(f"Registro cru preservado em {ARQ_JSONL}")
    print(f"Tempo total: {int(time.time() - inicio)}s\n")

    print("--- Distribuição de Níveis ---")
    for k in sorted(resumo_nivel, key=lambda x: -resumo_nivel[x]):
        print(f"  {k:<26}{resumo_nivel[k]:>7}  ({resumo_nivel[k]/linhas*100:.1f}%)")

    print("\n--- Menções a IA por Ano ---")
    for ano in sorted(por_ano_nivel):
        total_ano = sum(por_ano_nivel[ano].values())
        com_ia = ia_por_ano.get(ano, 0)
        pct = (com_ia / total_ano * 100) if total_ano > 0 else 0
        print(f"  {ano}: {com_ia:>5} / {total_ano:>5} vagas ({pct:.1f}%)")

    print("\n--- Menções a IA por Senioridade ---")
    for niv in sorted(resumo_nivel):
        total_niv = resumo_nivel[niv]
        com_ia = ia_por_nivel.get(niv, 0)
        pct = (com_ia / total_niv * 100) if total_niv > 0 else 0
        print(f"  {niv:<26}: {com_ia:>5} / {total_niv:>5} vagas ({pct:.1f}%)")

    print("\nAtenção: o corpo dos anúncios pode conter nome, e-mail e telefone")
    print("de recrutadores. Antes de compartilhar o CSV ou anexá-lo ao relatório,")
    print("remova esses dados (LGPD).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrompido. Rode de novo para retomar de onde parou.")
