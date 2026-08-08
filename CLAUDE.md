# CLAUDE.md — Quality Guardian Agent

Contrato entre desenvolvedor e Claude Code para este projeto. Leia antes de gerar código.

## 1. Project Overview

O **Quality Guardian** é um agente **stateful** em LangGraph que consome o catálogo de dados do
W01 (DataOps Knowledge Hub, já em produção), valida a qualidade dos datasets percorrendo um
**grafo de estados**, e grava os resultados (`health_score`, `quality_flag`) de volta no Ledger
(Postgres do W01) — esse `quality_flag` é o trigger que a Crew do W03 consome para agir.

O conceito central é a **máquina de estados explícita**: em vez de um agente ReAct caixa-preta,
construímos nós e arestas condicionais à mão, com ciclos de auto-correção, checkpointing (estado
persistido a cada passo, retomável após crash) e human-in-the-loop (pausa para aprovação humana
em casos de risco). O objetivo é ver a máquina funcionando, não escondê-la atrás de uma abstração.

No fim, o agente é exposto como **servidor MCP** (3 tools) e como **UI Chainlit** (conversacional,
com botões de aprovação), consumível em linguagem natural.

## 2. Tech Stack

- **LangGraph 1.2** — grafo e estado (StateGraph, nós, arestas condicionais, ciclos).
- **LangChain 1.3** — modelo, tools, mensagens.
- **langchain-anthropic** — Claude como LLM do agente.
- **langgraph-checkpoint-sqlite / langgraph-checkpoint-postgres** — checkpointing.
- **psycopg** — acesso direto ao Ledger (Postgres do W01).
- **langchain-mcp-adapters** — consumir o MCP do W01 (opcional, enriquecimento semântico).
- **mcp / FastMCP** — expor o Guardian como servidor MCP.
- **Chainlit** — UI conversacional.
- **Python 3.11+**.

## 3. Architecture Rules (não-negociáveis)

- O grafo é uma **máquina de estados explícita** — construir `StateGraph` à mão. **NÃO** usar
  `create_react_agent`; o objetivo didático é ver os nós e arestas, não escondê-los atrás do ReAct.
- Todo nó é uma função `(state) -> dict` que retorna **atualização parcial** do state (nunca o
  state inteiro recriado).
- Loops **sempre** com contador de parada no state (ex.: `retry_count` vs. `MAX_RETRIES`) — evitar
  `GraphRecursionError`.
- Human-in-the-loop com `interrupt()` + `Command(resume=...)`. **NÃO** usar a API antiga
  `interrupt_before` no `compile()` — considerada legado, hoje serve só para debug.
- **LER** dados factuais via SQL direto no Postgres do W01. **ESCREVER** `health_score` /
  `quality_flag` também via SQL — o W01 não expõe API de escrita.

## 4. Code Standards

- Type hints e docstrings em todas as funções públicas.
- Layout `src/` (pacote `guardian` em `src/guardian/`).
- Segredos em `.env` (nunca hardcoded, nunca commitados).
- Imports do namespace novo do LangChain 1.x:
  - `from langchain.chat_models import init_chat_model`
  - `from langchain.tools import tool`
  - `from langchain.messages import ...`
  - **NÃO** importar de `langchain_core.*` diretamente.

## 5. Connection to W01

- Ledger: Postgres `dataops`, host **localhost:5442** (porta remapeada para não conflitar com
  outros Postgres locais).
- Connection string: `postgresql://dataops:dataops123@localhost:5442/dataops`
  (credenciais reais em `.env` — ver `.env.example`).
- Tabelas do Ledger:
  - `customers(id, name, email, plan, company, created_at)`
  - `orders(id, customer_id, ..., status, amount)`
  - `products(id, ...)`
- O W01 já roda (`docker compose up` no projeto do W01) — **não reconstruir**, só consumir.

## 6. Constraints (proibições)

- ❌ **NÃO** reconstruir o W01 (RAG/MCP) — ele já existe e roda.
- ❌ **NÃO** usar `create_react_agent` no fluxo principal — queremos a máquina de estados explícita.
- ❌ **NÃO** hardcodar nomes de modelo — sempre ler de env var (`GUARDIAN_LLM_MODEL` etc.).
- ❌ **NÃO** commitar segredos — `.env` é git-ignored; usar `.env.example` como referência.
