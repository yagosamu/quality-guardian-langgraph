"""Entry point for running the API server: `python -m src.api.main` or via uvicorn/Makefile."""

import uvicorn

from src.api.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
