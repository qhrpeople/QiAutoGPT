"""
This module contains the configuration classes for AutoGPT.
"""
try:
    from autogpt.config.ai_config import AIConfig
    from autogpt.config.config import Config, check_openai_api_key
    from autogpt.config.singleton import AbstractSingleton, Singleton
except ModuleNotFoundError:
    from .ai_config import AIConfig
    from .config import Config, check_openai_api_key
    from .singleton import AbstractSingleton, Singleton

__all__ = [
    "check_openai_api_key",
    "AbstractSingleton",
    "AIConfig",
    "Config",
    "Singleton",
]
