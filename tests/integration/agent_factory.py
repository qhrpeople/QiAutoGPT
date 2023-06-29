from typing import Generator

import pytest

from autogpt.agent import Agent
from autogpt.config import AIConfig, Config
from autogpt.memory.vector import get_memory
from autogpt.models.command_registry import CommandRegistry
from autogpt.workspace import Workspace

"""
    Added #type: ignore because without it, mypy command gave following error:
        mypy
        tests/integration/memory/utils.py:5: error: Skipping analyzing ".autogpt.memory.vector.providers.base": module is installed, but missing library stubs or py.typed marker  [import]
        tests/integration/memory/utils.py:5: note: See https://mypy.readthedocs.io/en/stable/running_mypy.html#missing-imports
    This import file is necessary for giving the type hint for memory_json_file function
"""
from autogpt.memory.vector.providers.base import (
    VectorMemoryProvider as VectorMemory,  # type: ignore
)


@pytest.fixture
def memory_json_file(config: Config) -> Generator[VectorMemory, None, None]:
    was_memory_backend = config.memory_backend

    config.memory_backend = "json_file"
    memory = get_memory(config)
    memory.clear()
    yield memory

    config.memory_backend = was_memory_backend


@pytest.fixture
def dummy_agent(
    config: Config,
    memory_json_file: Generator[VectorMemory, None, None],
    workspace: Workspace,
) -> Agent:
    command_registry = CommandRegistry()

    ai_config = AIConfig(
        ai_name="Dummy Agent",
        ai_role="Dummy Role",
        ai_goals=[
            "Dummy Task",
        ],
    )
    ai_config.command_registry = command_registry

    agent = Agent(
        ai_name="Dummy Agent",
        memory=memory_json_file,
        command_registry=command_registry,
        ai_config=ai_config,
        config=config,
        next_action_count=0,
        system_prompt="dummy_prompt",
        triggering_prompt="dummy triggering prompt",
        workspace_directory=workspace.root,
    )

    return agent
