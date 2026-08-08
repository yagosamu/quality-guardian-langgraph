"""LLM layer for the Guardian agent (LangChain), with a deterministic fallback.

Robustness policy: if there's no ANTHROPIC_API_KEY, or the API call fails for
any reason (no credit, rate limit, network), every function below falls back
to a deterministic heuristic — the graph must never break live. The LLM only
ever emits text/a proposal; the GRAPH decides the flow, never the LLM.
"""

import json
import os
import re
from functools import lru_cache

from langchain.chat_models import init_chat_model

from . import config

_PATCH_KEYS = {"email", "company", "failed_orders"}


def _has_key() -> bool:
    """Only checks the env var is set — a placeholder or out-of-credit key
    still passes this gate and fails later at the actual API call."""
    return bool(os.getenv("ANTHROPIC_API_KEY"))


@lru_cache(maxsize=None)
def _model(spec: str):
    return init_chat_model(spec, temperature=0)


def _extract_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


# --- recommend: short diagnosis + suggested action ---------------------------


def recommend(dataset: str, health: float, flag: str, violations: list[str]) -> tuple[str, str]:
    if _has_key():
        try:
            model = _model(config.LLM_MODEL)
            prompt = (
                f"Dataset '{dataset}' tem health_score {health} (flag={flag}).\n"
                f"Violacoes encontradas: {violations or 'nenhuma'}.\n"
                "Em ate 2 frases, em portugues, diagnostique o problema principal e "
                "recomende uma acao objetiva."
            )
            text = model.invoke(prompt).content
            if text:
                return text, "llm"
        except Exception:
            pass
    return _recommend_fallback(dataset, health, flag, violations), "fallback"


def _recommend_fallback(dataset: str, health: float, flag: str, violations: list[str]) -> str:
    buckets = {"email": 0, "company": 0, "orders": 0}
    for v in violations:
        if "email" in v:
            buckets["email"] += 1
        elif "company" in v:
            buckets["company"] += 1
        elif "pedidos" in v:
            buckets["orders"] += 1

    breakdown = ", ".join(f"{k}={n}" for k, n in buckets.items() if n) or "sem violações"

    if flag == "green":
        action = "nenhuma ação necessária — manter monitoramento de rotina."
    elif flag == "yellow":
        action = "revisar os registros com violação antes do próximo ciclo; risco moderado."
    else:
        action = "ação imediata — requer aprovação humana antes de prosseguir."

    return f"[{dataset}] health={health} flag={flag}. Violações: {breakdown}. Recomendação: {action}"


# --- propose_fix: weak generator proposes a minimal patch --------------------


def propose_fix(row: dict, hardening: int = 0, feedback: str = "") -> tuple[dict, str]:
    if _has_key():
        try:
            model = _model(config.GENERATOR_MODEL)
            prompt = (
                "Voce corrige dados de clientes. Proponha uma correcao MINIMA para o "
                "registro abaixo. Responda so com um JSON contendo apenas as chaves que "
                "voce quer mudar, entre email, company, failed_orders.\n"
                f"Registro: {row}\n"
                f"Feedback da rejeicao anterior (se houver): {feedback or 'nenhum'}\n"
                "Responda apenas o JSON, sem texto adicional."
            )
            data = _extract_json(model.invoke(prompt).content)
            if data:
                patch = {k: v for k, v in data.items() if k in _PATCH_KEYS}
                if patch:
                    return patch, "llm"
        except Exception:
            pass
    return _propose_fix_fallback(row), "fallback"


def _propose_fix_fallback(row: dict) -> dict:
    patch: dict = {}

    email = row.get("email")
    if not email or "@" not in email:
        slug = (row.get("name") or "cliente").lower().replace(" ", ".")
        patch["email"] = f"{slug}@corrigido.example.com"

    if not row.get("company"):
        first_name = (row.get("name") or "Cliente").split()[0]
        patch["company"] = f"{first_name} Ltda"

    if row.get("failed_orders"):
        patch["failed_orders"] = 0

    return patch


# --- judge_fix: strong evaluator audits the proposal --------------------------


def judge_fix(row: dict, patch: dict) -> tuple[bool, str, str]:
    if _has_key():
        try:
            model = _model(config.EVALUATOR_MODEL)
            prompt = (
                "Voce e um auditor de qualidade de dados, rigoroso. Avalie se a correcao "
                "proposta abaixo resolve o problema do registro, sem inventar dados falsos.\n"
                f"Registro original: {row}\nCorrecao proposta: {patch}\n"
                'Responda apenas com JSON: {"aceita": true ou false, "motivo": "..."}'
            )
            data = _extract_json(model.invoke(prompt).content)
            if data and "aceita" in data:
                return bool(data["aceita"]), str(data.get("motivo", "")), "llm"
        except Exception:
            pass
    return _judge_fix_fallback(row, patch)


def _judge_fix_fallback(row: dict, patch: dict) -> tuple[bool, str, str]:
    email = patch.get("email", row.get("email"))
    company = patch.get("company", row.get("company"))
    if email and "@" in email and company:
        return True, "email válido e company preenchida", "fallback"
    return False, "correção ainda não resolve email/company", "fallback"
