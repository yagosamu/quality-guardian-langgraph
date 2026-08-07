"""Text cleanup for LLM-generated prose.

OpenAI completions occasionally mis-transcribe multi-byte UTF-8 characters
during generation (observed: "Leão" regenerated as "LeÃ£o" -- a classic
double-encoding artifact -- specifically inside RouterEngine's synthesis call,
while the exact same name round-tripped correctly through LedgerEngine's own
synthesis 5/5 times in the same session). Postgres, psycopg2, and FastAPI's
JSON encoding were all confirmed correct via direct codepoint inspection, so
this is a generation-side quirk, not a bug in our pipeline. ftfy repairs the
common mojibake patterns and is a safe no-op on already-correct text.
"""

import ftfy


def clean_llm_text(text: str) -> str:
    return ftfy.fix_text(text)
