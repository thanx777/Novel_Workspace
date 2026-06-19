"""Shared pytest fixtures for backend tests."""
import os
import sys
import tempfile
import pytest

# Ensure backend is on the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable auth for tests
os.environ["AUTH_DISABLED"] = "true"


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def mock_llm_config():
    """Provide a mock LLM configuration for testing."""
    return {
        "api_key": "test-key",
        "base_url": "https://api.test.com/v1",
        "model": "test-model",
        "api_format": "openai",
    }
