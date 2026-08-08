"""Chainlit UI for the Quality Guardian — the conversational face over the
same api.py that the MCP server (prompt 09) calls. Same graph, same
checkpointer, same human-in-the-loop; just buttons instead of a CLI prompt.
"""

import uuid

import chainlit as cl

from src.guardian.api import GuardianResult, resume_guardian, run_guardian

FLAG_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


async def _present(result: GuardianResult, thread_id: str) -> None:
    if result.status == "paused":
        interrupt = result.interrupt or {}
        question = interrupt.get("question", "Aprovação necessária.")
        violations = interrupt.get("violations") or []

        content = f"🔴 **{question}**"
        if violations:
            content += "\n\n**Violações encontradas:**\n" + "\n".join(f"- {v}" for v in violations)
        content += "\n\nEscolha como prosseguir:"

        actions = [
            cl.Action(
                name="approve",
                payload={"thread_id": thread_id, "decision": "approve"},
                label="✅ Aprovar (grava RED)",
            ),
            cl.Action(
                name="override",
                payload={"thread_id": thread_id, "decision": "override"},
                label="↩️ Override (rebaixa p/ yellow)",
            ),
        ]
        await cl.Message(content=content, actions=actions).send()
        return

    emoji = FLAG_EMOJI.get(result.quality_flag, "⚪")
    content = (
        f"{emoji} **{result.quality_flag}** — dataset `{result.dataset}`\n\n"
        f"- health_score: **{result.health_score}**\n"
        f"- registros validados: {result.rows_checked}\n"
        f"- registros red: {result.n_red}"
    )
    await cl.Message(content=content).send()


@cl.on_chat_start
async def start() -> None:
    thread_id = str(uuid.uuid4())
    cl.user_session.set("thread_id", thread_id)

    await cl.Message(
        content=(
            "**Quality Guardian** 🛡️ — agente de qualidade de dados (LangGraph) sobre o "
            "Ledger do W01.\n\n"
            "Digite **validar** para rodar uma checagem no dataset `customers`. Se o "
            "resultado vier RED, o agente pausa e pede sua aprovação antes de gravar."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    thread_id = cl.user_session.get("thread_id")

    async with cl.Step(name="Quality Guardian (LangGraph)") as step:
        result = await cl.make_async(run_guardian)(dataset="customers", thread_id=thread_id)
        step.output = " → ".join(result.steps)

    await _present(result, thread_id)


async def _handle_decision(action: cl.Action, decision: str) -> None:
    thread_id = action.payload["thread_id"]
    await action.remove()

    async with cl.Step(name="Quality Guardian (LangGraph)") as step:
        result = await cl.make_async(resume_guardian)(thread_id, decision)
        step.output = " → ".join(result.steps)

    await _present(result, thread_id)


@cl.action_callback("approve")
async def on_approve(action: cl.Action) -> None:
    await _handle_decision(action, "approve")


@cl.action_callback("override")
async def on_override(action: cl.Action) -> None:
    await _handle_decision(action, "override")
