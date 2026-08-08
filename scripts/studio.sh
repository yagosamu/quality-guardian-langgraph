#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# studio.sh — sobe o LangGraph Studio (a lente visual "produto" do grafo).
#
# Abre o servidor de dev do LangGraph (`langgraph dev`), que serve o Studio:
# o grafo interativo no navegador, execução passo a passo e time-travel de
# checkpoints. Mac-only no app nativo; no navegador funciona via smith.langchain.com.
#
# Pré-req: W01 de pé (bash scripts/bootstrap.sh) e venv do agente instalado.
#
# Uso:
#   bash scripts/studio.sh           # sobe o Studio (abre o navegador)
#   bash scripts/studio.sh --no-open # sobe sem abrir navegador
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PORT="${GUARDIAN_STUDIO_PORT:-2024}"

if [[ -t 1 ]]; then BOLD=$'\033[1m'; CYN=$'\033[36m'; GRN=$'\033[32m'; YLW=$'\033[33m'; RST=$'\033[0m'
else BOLD=""; CYN=""; GRN=""; YLW=""; RST=""; fi

cd "$REPO_DIR"

# venv check — Windows (.venv/Scripts) vs POSIX (.venv/bin) layout
if [[ -x ".venv/Scripts/python.exe" ]]; then
  PY=".venv/Scripts/python.exe"
elif [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
else
  echo "${YLW}venv não encontrado.${RST} Rode: python -m venv .venv && pip install -r requirements.txt && pip install -e ." >&2
  exit 1
fi

# langgraph-cli check
if ! "$PY" -c "import langgraph_cli" >/dev/null 2>&1; then
  echo "Instalando langgraph-cli[inmem] no venv…"
  "$PY" -m pip install "langgraph-cli[inmem]" >/dev/null 2>&1
fi

# pacote guardian registrado? (langgraph.json referencia por módulo, não por caminho)
if ! "$PY" -c "import guardian" >/dev/null 2>&1; then
  echo "Registrando o pacote guardian (pip install -e .)…"
  "$PY" -m pip install -e . >/dev/null 2>&1
fi

# W01 de pé? (o grafo lê o Ledger ao executar)
if ! docker inspect guardian-postgres >/dev/null 2>&1; then
  echo "${YLW}! W01 não parece estar de pé${RST} — o grafo desenha, mas executar vai falhar na leitura do Ledger."
  echo "  Suba antes: bash scripts/bootstrap.sh"
fi

OPEN_FLAG=""
[[ "${1:-}" == "--no-open" ]] && OPEN_FLAG="--no-browser"

printf "${BOLD}${CYN}▸ Subindo LangGraph Studio em http://127.0.0.1:%s${RST}\n" "$PORT"
printf "  ${GRN}grafo:${RST} quality_guardian  ·  ${GRN}config:${RST} langgraph.json\n"
printf "  Studio (navegador): https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:%s\n\n" "$PORT"

# --allow-blocking: os nós fazem I/O síncrono de propósito (psycopg, chamadas
# LLM via .invoke()) — é a "máquina de estados explícita" do CLAUDE.md, não
# um bug a esconder atrás de async.
PYTHONIOENCODING=utf-8 exec "$PY" -m langgraph_cli dev --port "$PORT" --allow-blocking $OPEN_FLAG
