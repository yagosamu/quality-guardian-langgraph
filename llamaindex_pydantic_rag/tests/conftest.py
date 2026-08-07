"""Shared fixtures for all tests."""

import pytest

from src.engines.config import EngineConfig


@pytest.fixture(scope="session")
def config():
    """Load config from .env (must exist with valid values)."""
    return EngineConfig()
