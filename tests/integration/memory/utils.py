from typing import Any, Generator

import numpy
import pytest
from pytest_mock import MockerFixture

import autogpt.memory.vector.memory_item as vector_memory_item
import autogpt.memory.vector.providers.base as memory_provider_base
from autogpt.config.config import Config
from autogpt.llm.providers.openai import OPEN_AI_EMBEDDING_MODELS
from autogpt.memory.vector import get_memory

"""
    Added #type: ignore because without it, mypy command gave following error:
        mypy
        tests/integration/memory/utils.py:5: error: Skipping analyzing ".autogpt.memory.vector.providers.base": module is installed, but missing library stubs or py.typed marker  [import]
        tests/integration/memory/utils.py:5: note: See https://mypy.readthedocs.io/en/stable/running_mypy.html#missing-imports
"""
from autogpt.memory.vector.providers.base import (
    VectorMemoryProvider as VectorMemory,  # type: ignore
)


@pytest.fixture
def embedding_dimension(
    config: Config,
) -> int:  ## Because embedding_dimensions has int type
    return OPEN_AI_EMBEDDING_MODELS[config.embedding_model].embedding_dimensions


@pytest.fixture
def mock_embedding(embedding_dimension: int) -> Any:
    return numpy.full((1, embedding_dimension), 0.0255, numpy.float32)[0]


@pytest.fixture
def mock_get_embedding(mocker: MockerFixture, embedding_dimension: int) -> None:
    mocker.patch.object(
        vector_memory_item,
        "get_embedding",
        return_value=[0.0255] * embedding_dimension,
    )
    mocker.patch.object(
        memory_provider_base,
        "get_embedding",
        return_value=[0.0255] * embedding_dimension,
    )


@pytest.fixture
def memory_none(
    agent_test_config: Config, mock_get_embedding: None
) -> Generator[VectorMemory, Any, None]:
    was_memory_backend = agent_test_config.memory_backend

    agent_test_config.memory_backend = "no_memory"
    yield get_memory(agent_test_config)

    agent_test_config.memory_backend = was_memory_backend
