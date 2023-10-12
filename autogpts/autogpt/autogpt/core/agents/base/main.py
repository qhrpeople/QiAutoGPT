from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
import os
import yaml
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable, List, Dict, Tuple, Optional
from pydantic import Field


if TYPE_CHECKING:
    from autogpt.core.agents.base.loop import (  # Import only where it's needed
        BaseLoop,
        BaseLoopHook,
    )
    from autogpt.core.tools.base import BaseToolsRegistry

from autogpt.core.configuration import SystemConfiguration , SystemSettings

from autogpt.core.agents.base.loop import (
    BaseLoopHook,
)


from autogpt.core.agents.base.models import (
    BaseAgentConfiguration,
    BaseAgentSystems,
    BaseAgentDirectives,
)
from autogpt.core.memory.base import AbstractMemory
# from autogpt.core.workspace import AbstractWorkspace
from autogpt.core.workspace.simple import SimpleWorkspace
from autogpt.core.configuration import Configurable


class AbstractAgent(ABC):

    @classmethod
    def get_agent_class(cls) -> BaseAgent:
        """
        Returns the agent class.

        Returns:
            Agent: The class of the agent.

        Example:
            >>> agent_class = BaseAgent.get_agent_class()
            >>> print(agent_class)
            <class '__main__.BaseAgent'>
        """
        return cls

    @abstractmethod
    def __init__(self, *args, **kwargs):
        """
        Abstract method for the initialization of the agent.

        Note: Implementation required in subclass.
        """
        ...

    @classmethod
    @abstractmethod
    def get_agent_from_settings(
        cls,
        agent_settings: BaseAgent.SystemSettings,
        logger: logging.Logger,
    ) -> "AbstractAgent":
        """
        Abstract method to retrieve an agent instance using provided settings.

        Args:
            agent_settings (BaseAgent.SystemSettings): The settings for the agent.
            logger (logging.Logger): Logger instance for logging purposes.

        Returns:
            BaseAgent: An instance of BaseAgent.

        Note: Implementation required in subclass.
        """
        ...

    @abstractmethod
    def __repr__(self):
        """
        Abstract method for the string representation of the agent.

        Returns:
            str: A string representation of the agent.

        Note: Implementation required in subclass.
        """
        ...

    _loop: BaseLoop = None
    # _loophooks: Dict[str, BaseLoop.LoophooksDict] = {}


class BaseAgent(Configurable, AbstractAgent):

    CLASS_CONFIGURATION = BaseAgentConfiguration
    CLASS_SYSTEMS = BaseAgentSystems # BaseAgentSystems() = cls.SystemSettings().configuration.systems


    class SystemSettings(SystemSettings):
        configuration: BaseAgentConfiguration = BaseAgentConfiguration()
        
        # user_id: Optional[uuid.UUID] = Field(default=None)
        agent_id: str = Field(default_factory=lambda: "A" + str(uuid.uuid4()))
        agent_class: str

        memory: AbstractMemory.SystemSettings = AbstractMemory.SystemSettings()
        workspace: SystemSettings = SimpleWorkspace.SystemSettings()

        class Config(SystemSettings.Config):
            # This is a list of Field to Exclude during serialization
            json_encoders = {uuid.UUID: lambda v: str(v)}  # Custom encoder for UUID4
            extra = "allow"
            default_exclude = {
                "agent",
                "workspace",
                "prompt_manager",
                "chat_model_provider",
                "memory",
                "tool_registry",
            }

        def dict(self, remove_technical_values=True, *args, **kwargs):
            """
            Serialize the object to a dictionary representation.

            Args:
                remove_technical_values (bool, optional): Whether to exclude technical values. Default is True.
                *args: Additional positional arguments to pass to the base class's dict method.
                **kwargs: Additional keyword arguments to pass to the base class's dict method.
                kwargs['exclude'] excludes the fields from the serialization

            Returns:
                dict: A dictionary representation of the object.
            """
            self.prepare_values_before_serialization()  # Call the custom treatment before .dict()

            kwargs["exclude"] = kwargs.get("exclude", set())  # Get the exclude_arg
            if remove_technical_values:
                # Add the default technical fields to exclude_arg
                kwargs["exclude"] |= self.__class__.Config.default_exclude

            # Call the .dict() method with the updated exclude_arg
            return super().dict(*args, **kwargs)

        def json(self, remove_technical_values=True, *args, **kwargs):
            """
            Serialize the object to a dictionary representation.

            Args:
                remove_technical_values (bool, optional): Whether to exclude technical values. Default is True.
                *args: Additional positional arguments to pass to the base class's dict method.
                **kwargs: Additional keyword arguments to pass to the base class's dict method.
                kwargs['exclude'] excludes the fields from the serialization

            Returns:
                dict: A dictionary representation of the object.
            """
            self.prepare_values_before_serialization()  # Call the custom treatment before .json()

            kwargs["exclude"] = kwargs.get("exclude", set())  # Get the exclude_arg
            if remove_technical_values:
                # Add the default technical fields to exclude_arg
                kwargs["exclude"] |= self.__class__.Config.default_exclude

            return super().json(*args, **kwargs)

        # NOTE : To be implemented in the future
        def load_root_values(self, *args, **kwargs):
            pass  # NOTE : Currently not used
            self.agent_name = self.agent.configuration.agent_name
            self.agent_role = self.agent.configuration.agent_role
            self.agent_goals = self.agent.configuration.agent_goals
            self.agent_goal_sentence = self.agent.configuration.agent_goal_sentence

        # TODO Implement a BaseSettings class and move it to the BaseSettings ?
        def prepare_values_before_serialization(self):
            self.agent_setting_module = (
                f"{self.__class__.__module__}.{self.__class__.__name__}"
            )
            self.agent_setting_class = self.__class__.__name__

        def update_agent_name_and_goals(self, agent_goals: dict) -> None:
            for key, value in agent_goals.items():
                # if key != 'agent' and key != 'workspace'  :
                setattr(self, key, value)


    def __init__(
        self,
        settings: BaseAgent.SystemSettings,
        logger: logging.Logger,
        memory: AbstractMemory,
        workspace: SimpleWorkspace,
        user_id: uuid.UUID,
        agent_id: uuid.UUID = None,
    ) -> Any:
        self._settings = settings
        self._configuration = settings.configuration
        self._logger = logger
        self._memory = memory
        self._workspace = workspace

        self.user_id = user_id
        self.agent_id = agent_id

        # NOTE : Move to Configurable class ?
        self.agent_class = f"{self.__class__.__name__}"

    def add_hook(self, hook: BaseLoopHook, hook_id: uuid.UUID = uuid.uuid4()):
        """
        Adds a hook to the loop.

        Args:
            hook (BaseLoopHook): The hook to be added.
            hook_id (uuid.UUID, optional): Unique ID for the hook. Defaults to a new UUID.

        Example:
            >>> my_hook = BaseLoopHook(...)
            >>> agent = Agent(...)
            >>> agent.add_hook(my_hook)
        """
        self._loop._loophooks[hook["name"]][str(hook_id)] = hook

    def remove_hook(self, name: str, hook_id: uuid.UUID) -> bool:
        """
        Removes a hook from the loop based on its name and ID.

        Args:
            name (str): Name of the hook.
            hook_id (uuid.UUID): Unique ID of the hook.

        Returns:
            bool: True if removal was successful, otherwise False.

        Example:
            >>> agent = Agent(...)
            >>> removed = agent.remove_hook("my_hook_name", some_uuid)
            >>> print(removed)
            True
        """
        if name in self._loop._loophooks and hook_id in self._loop._loophooks[name]:
            del self._loop._loophooks[name][hook_id]
            return True
        return False

    async def start(
        self,
        user_input_handler: Callable[[str], Awaitable[str]],
        user_message_handler: Callable[[str], Awaitable[str]],
    ) -> None:
        self._logger.info(str(self.__class__) + ".start()")
        return_var = await self._loop.start(
            agent=self,
            user_input_handler=user_input_handler,
            user_message_handler=user_message_handler,
        )
        return return_var

    async def stop(
        self,
        user_input_handler: Callable[[str], Awaitable[str]],
        user_message_handler: Callable[[str], Awaitable[str]],
    ) -> None:
        return_var = await self._loop.stop(
            agent=self,
            user_input_handler=user_input_handler,
            user_message_handler=user_message_handler,
        )
        return return_var

    async def run(
        self,
        user_input_handler: Callable[[str], Awaitable[str]],
        user_message_handler: Callable[[str], Awaitable[str]],
        **kwargs,
    ) -> None | dict:
        """
        Asynchronously run the agent's loop.

        Args:
            user_input_handler (Callable[[str], Awaitable[str]]): Callback for handling user input.
            user_message_handler (Callable[[str], Awaitable[str]]): Callback for handling user messages.
            **kwargs: Additional keyword arguments.

        Returns:
            None | dict: Returns either None or a dictionary based on the loop's run method.

        Raises:
            BaseException: If the agent is already running.

        Example:
            async def input_handler(prompt: str) -> str:
                return input(prompt)

            async def message_handler(message: str) -> str:
                print(message)

            agent = YourClass()
            await agent.run(input_handler, message_handler)
        """
        self._logger.debug(str(self.__class__) + ".run() *kwarg : " + str(kwargs))
        self._user_input_handler  = user_input_handler
        self._user_message_handler = user_message_handler

        if not self._loop._is_running:
            self._loop._is_running = True
            # Very important, start the loop :-)
            await self.start(
                user_input_handler=user_input_handler,
                user_message_handler=user_message_handler,
            )

            return await self._loop.run(
                agent=self,
                hooks=self._loop._loophooks,
                user_input_handler=user_input_handler,
                user_message_handler=user_message_handler,
                # *kwargs,
            )

        else:
            raise BaseException("Agent Already Running")

    def exit(self, *kwargs) -> None:
        """
        Exit the agent's loop if it's running.

        Args:
            *kwargs: Additional arguments.

        Example:
            agent = YourClass()
            agent.exit()
        """
        if self._loop._is_running:
            self._loop._is_running = False

    @classmethod
    def get_agent_from_settings(
        cls,
        agent_settings: BaseAgent.SystemSettings,
        logger: logging.Logger,
    ) -> BaseAgent:
        """
        Retrieve an agent instance based on the provided settings and logger.

        Args:
            agent_settings (BaseAgent.SystemSettings): Configuration settings for the agent.
            logger (logging.Logger): Logger to use for the agent.

        Returns:
            Agent: An agent instance configured according to the provided settings.

        Example:
            logger = logging.getLogger()
            settings = BaseAgent.SystemSettings(user_id="123", ...other_settings...)
            agent = YourClass.get_agent_from_settings(settings, logger)
        """
        # if not isinstance(agent_settings, BaseAgent.SystemSettings):
        #     agent_settings: BaseAgent.SystemSettings = agent_settings
        if not isinstance(agent_settings, cls.SystemSettings):
            agent_settings = cls.SystemSettings.parse_obj(agent_settings)
        agent_args = {}

        agent_args["user_id"] = agent_settings.user_id
        agent_args["settings"] = agent_settings
        agent_args["logger"] = logger
        agent_args["workspace"] = cls._get_system_instance(
            "workspace",
            agent_settings,
            logger,
        )

        memory_settings = agent_settings.memory
        agent_args["memory"] = AbstractMemory.get_adapter(
            memory_settings=memory_settings, logger=logger
        )

        from importlib import import_module

        module_path, class_name = agent_settings._type_.rsplit(".", 1)
        module = import_module(module_path)
        agent_class = getattr(module, class_name)

        agent_settings, agent_args = agent_class._get_agent_from_settings(
            agent_settings=agent_settings, agent_args=agent_args, logger=logger
        )

        agent = agent_class(**agent_args)

        items = agent_settings.dict().items()
        for key, value in items:
            if key not in agent_class.SystemSettings.Config.default_exclude:
                setattr(agent, key, value)

        return agent

    @classmethod
    @abstractmethod
    def _get_agent_from_settings(
        cls, agent_settings: BaseAgent.SystemSettings, agent_args: list, logger: logging.Logger
    ) -> Tuple[BaseAgent.SystemSettings, list]:
        return agent_settings, agent_args

    ################################################################
    # Factory interface for agent bootstrapping and initialization #
    ################################################################

    # @classmethod
    # def build_user_configuration(cls) -> dict[str, Any]:
    #     """
    #     Build and return the user's agent configuration.

    #     Returns:
    #         dict[str, Any]: A dictionary containing the user's agent configuration.

    #     Example:
    #         agent_configuration = YourClass.build_user_configuration()
    #         print(agent_configuration)
    #     """
    #     configuration_dict = {
    #         "agent": cls.get_user_config(),
    #     }

    #     system_locations = configuration_dict["agent"]["configuration"]["systems"]
    #     for system_name, system_location in system_locations.items():
    #         system_class = SimplePluginService.get_plugin(system_location)
    #         configuration_dict[system_name] = system_class.get_user_config()
    #     configuration_dict = _prune_empty_dicts(configuration_dict)
    #     return configuration_dict

    # @classmethod
    # def compile_settings(cls, logger: logging.Logger) -> BaseAgent.SystemSettings:
    #     """
    #     Compile the user's configuration settings with the default agent settings.

    #     Args:
    #         logger (logging.Logger): Logger to use for the agent.

    #     Returns:
    #         BaseAgent.SystemSettings: Combined agent settings.

    #     Example:
    #         logger = logging.getLogger()
    #         user_config = {"agent": ...}
    #         agent_settings = YourClass.compile_settings(logger, user_config)
    #     """
    #     logger.debug("Processing agent system configuration.")
    #     logger.debug("compile_settings" + str(cls))
    #     configuration_dict = {}
    #     configuration_dict["agent"] = cls.SystemSettings().dict()

    #     system_locations = configuration_dict["agent"]["configuration"]["systems"]

    #     for system_name, system_location in system_locations.items():
    #         if system_location is not None and not isinstance(
    #             system_location, uuid.UUID
    #         ):
    #             logger.debug(f"Compiling configuration for system {system_name}")
    # #             system_settings = getattr(cls.CLASS_SETTINGS, system_name, None)
    # #             if system_settings:
    # #                 configuration_dict[system_name] = system_settings
    # #             else:
    # #                 raise ValueError(f"No system class found for {system_name} in CLASS_SETTINGS")

    #             system_class : Configurable = cls.CLASS_SYSTEMS.load_from_import_path( system_location = system_locations[system_name])  #SimplePluginService.get_plugin(system_location)

    #             configuration_dict[
    #                 system_name
    #             ] = system_class.SystemSettings().dict()
    #         else:
    #             configuration_dict[system_name] = system_location

    #     return cls.CLASS_SETTINGS.parse_obj(configuration_dict)

    ################################################################
    # Factory interface for agent bootstrapping and initialization #
    ################################################################

    # def check_user_context(self, min_len=250, max_len=300):
    #     pass

    @classmethod
    def create_agent(
        cls,
        agent_settings: BaseAgent.SystemSettings,
        logger: logging.Logger,
    ) -> AbstractAgent:
        """
        Create and return a new agent based on the provided settings and logger.

        Args:
            agent_settings (BaseAgent.SystemSettings): Configuration settings for the agent.
            logger (logging.Logger): Logger to use for the agent.

        Returns:
            BaseAgent: An agent instance configured according to the provided settings.

        Example:
            logger = logging.getLogger()
            settings = BaseAgent.SystemSettings(user_id="123", ...other_settings...)
            agent = YourClass.create_agent(settings, logger)
        """
        logger.info(f"Starting creation of {cls.__name__}")
        logger.debug(f"{cls.__module__}.{cls.__name__}")

        if not isinstance(agent_settings, cls.SystemSettings):
            agent_settings = cls.SystemSettings.parse_obj(agent_settings)

        agent_id = cls._create_agent_in_memory(
            agent_settings=agent_settings, logger=logger, user_id=agent_settings.user_id
        )
        logger.info(
            f"{cls.__name__} id #{agent_id} created in memory. Now, finalizing creation..."
        )
        # Adding agent_id to the settingsagent_id
        agent_settings.agent_id = agent_id

        # Processing to custom treatments
        cls._create_agent_custom_treatment(agent_settings=agent_settings, logger=logger)

        logger.info(f"Loaded Agent ({cls}) with ID {agent_id}")

        agent = cls.get_agent_from_settings(
            agent_settings=agent_settings,
            logger=logger,
        )

        return agent

    @classmethod
    @abstractmethod
    def _create_agent_custom_treatment(
        cls, agent_settings: BaseAgent.SystemSettings, logger: logging.Logger
    ) -> None:
        pass

    @classmethod
    def _create_agent_in_memory(
        cls,
        agent_settings: BaseAgent.SystemSettings,
        logger: logging.Logger,
        user_id: uuid.UUID,
    ) -> uuid.UUID:

        # TODO : Remove the user_id argument
        # NOTE : Monkey Patching
        BaseAgent.SystemSettings.Config.extra = "allow"
        BaseAgent.SystemSettings.Config.extra = "allow"
        BaseAgentSystems.Config.extra = "allow"
        BaseAgentConfiguration.Config.extra = "allow"
        BaseAgentSystems.user_id: uuid.UUID
        agent_settings.user_id = str(user_id)

        from autogpt.core.memory.base import AbstractMemory

        memory_settings = agent_settings.memory

        memory = AbstractMemory.get_adapter(memory_settings=memory_settings, logger=logger)
        agent_table = memory.get_table("agents")
        agent_id = agent_table.add(agent_settings, id = agent_settings.agent_id)
        return agent_id

    def save_agent_in_memory(self) -> uuid.UUID:
        self._logger.debug(self._memory)
        agent_table = self._memory.get_table("agents")
        agent_id = agent_table.update(
            agent_id=self.agent_id, user_id=self.user_id, value=self
        )
        return agent_id

    @classmethod
    def _get_system_instance(
        cls,
        system_name: str,
        agent_settings: BaseAgent.SystemSettings,
        logger: logging.Logger,
        *args,
        **kwargs,
    ):
        system_settings : SystemSettings = getattr(agent_settings, system_name)
        #system_class = getattr(cls.CLASS_SETTINGS, system_name, None)
        system_class : Configurable = cls.CLASS_SYSTEMS.load_from_import_path(getattr( cls.CLASS_SYSTEMS(), system_name ))

        if not system_class:
            raise ValueError(f"No system class found for {system_name} in CLASS_SETTINGS")
        system_instance = system_class(
            system_settings,
            *args,
            logger=logger.getChild(system_name),
            **kwargs,
        )
        return system_instance

    @classmethod
    @abstractmethod
    def load_prompt_settings(
        cls, erase=False, file_path: str = ""
    ) -> BaseAgentDirectives:
        # Get the directory containing the current class file
        base_agent_dir = os.path.dirname(__file__)
        # Construct the path to the YAML file based on __file__
        current_settings_path = os.path.join(base_agent_dir, "prompt_settings.yaml")

        settings = {}
        # Load settings from the current directory (based on __file__)
        if os.path.exists(current_settings_path):
            with open(current_settings_path, "r") as file:
                settings = yaml.load(file, Loader=yaml.FullLoader)
        else:
            raise FileNotFoundError(f"Can't locate file {current_settings_path}")

        agent_directives = BaseAgentDirectives(
            constraints=settings.get("constraints", []),
            resources=settings.get("resources", []),
            best_practices=settings.get("best_practices", []),
        )

        # Load settings from the specified directory (based on 'file')
        if file_path:
            specified_settings_path = os.path.join(
                os.path.dirname(file_path), "prompt_settings.yaml"
            )

            if os.path.exists(specified_settings_path):
                with open(specified_settings_path, "r") as file_path:
                    specified_settings = yaml.safe_load(file_path)
                    for key, items in specified_settings.items():
                        if key not in agent_directives.keys():
                            agent_directives[key]: list[str] = items
                        else:
                            # If the item already exists, update it with specified_settings
                            if erase:
                                agent_directives[key] = items
                            else:
                                agent_directives[key] += items

        return agent_directives

    ################################################################################
    ################################ DB INTERACTIONS ################################
    ################################################################################

    @classmethod
    def get_agentsetting_list_from_memory(
        self, user_id: uuid.UUID, logger: logging.Logger
    ) -> list[BaseAgent.SystemSettings]:
        """
        Fetch a list of agent settings from memory based on the user ID.

        Args:
            user_id (uuid.UUID): The unique identifier for the user.
            logger (logging.Logger): Logger to use.

        Returns:
            list[BaseAgent.SystemSettings]: List of agent settings from memory.

        Example:
            logger = logging.getLogger()
            user_id = uuid.uuid4()
            agent_settings_list = YourClass.get_agentsetting_list_from_memory(user_id, logger)
            print(agent_settings_list)
        """
        from autogpt.core.memory.base import (
            AbstractMemory,
            MemoryConfig,
            AbstractMemory,
        )
        from autogpt.core.memory.table.base import AgentsTable, BaseTable

        """Warning !!!
        Returns a list of agent settings not a list of agent

        Returns:
            /
        """

        memory_settings = AbstractMemory.SystemSettings()

        memory = AbstractMemory.get_adapter(memory_settings=memory_settings, logger=logger)
        agent_table: AgentsTable = memory.get_table("agents")

        filter = BaseTable.FilterDict(
            {
                "user_id": [
                    BaseTable.FilterItem(
                        value=str(user_id), operator=BaseTable.Operators.EQUAL_TO
                    )
                ],
                "agent_class": [
                    BaseTable.FilterItem(
                        value=str(self.__name__), operator=BaseTable.Operators.EQUAL_TO
                    )
                ],
            }
        )
        agent_list = agent_table.list(filter=filter)
        return agent_list

    @classmethod
    def get_agent_from_memory(
        cls,
        agent_settings: BaseAgent.SystemSettings,
        agent_id: uuid.UUID,
        user_id: uuid.UUID,
        logger: logging.Logger,
    ) -> BaseAgent:
        from autogpt.core.memory.base import (
            AbstractMemory,
        )
        from autogpt.core.memory.table.base import AgentsTable

        # memory_settings = Memory.SystemSettings(configuration=agent_settings.memory)
        memory_settings = agent_settings.memory

        memory = AbstractMemory.get_adapter(memory_settings=memory_settings, logger=logger)
        agent_table: AgentsTable = memory.get_table("agents")
        agent = agent_table.get(agent_id=str(agent_id), user_id=str(user_id))

        if not agent:
            return None
        agent = cls.get_agent_from_settings(
            agent_settings=agent_settings,
            logger=logger,
        )
        return agent


def _prune_empty_dicts(d: dict) -> dict:
    """
    Prune branches from a nested dictionary if the branch only contains empty dictionaries at the leaves.

    Args:
        d (dict): The dictionary to prune.

    Returns:
        dict: The pruned dictionary.

    Example:
        input_dict = {"a": {}, "b": {"c": {}, "d": "value"}}
        pruned_dict = _prune_empty_dicts(input_dict)
        print(pruned_dict)  # Expected: {"b": {"d": "value"}}
    """
    pruned = {}
    for key, value in d.items():
        if isinstance(value, dict):
            pruned_value = _prune_empty_dicts(value)
            if (
                pruned_value
            ):  # if the pruned dictionary is not empty, add it to the result
                pruned[key] = pruned_value
        else:
            pruned[key] = value
    return pruned
