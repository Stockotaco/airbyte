#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#


import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Dict, Generic, Iterable, List, Mapping, MutableMapping, Optional, TypeVar, Union

from airbyte_cdk.connector import BaseConnector, DefaultConnectorMixin, TConfig
from airbyte_cdk.models import AirbyteCatalog, AirbyteMessage, AirbyteStateMessage, AirbyteStateType, ConfiguredAirbyteCatalog

TState = TypeVar("TState")
TCatalog = TypeVar("TCatalog")


class BaseSource(BaseConnector[TConfig], ABC, Generic[TConfig, TState, TCatalog]):
    @abstractmethod
    def read_state(self, state_path: str) -> TState:
        ...

    @abstractmethod
    def read_catalog(self, catalog_path: str) -> TCatalog:
        ...

    @abstractmethod
    def read(self, logger: logging.Logger, config: TConfig, catalog: TCatalog, state: Optional[TState] = None) -> Iterable[AirbyteMessage]:
        """
        Returns a generator of the AirbyteMessages generated by reading the source with the given configuration, catalog, and state.
        """

    @abstractmethod
    def discover(self, logger: logging.Logger, config: TConfig) -> AirbyteCatalog:
        """
        Returns an AirbyteCatalog representing the available streams and fields in this integration. For example, given valid credentials to a
        Postgres database, returns an Airbyte catalog where each postgres table is a stream, and each table column is a field.
        """


class Source(
    DefaultConnectorMixin,
    BaseSource[Mapping[str, Any], Union[List[AirbyteStateMessage], MutableMapping[str, Any]], ConfiguredAirbyteCatalog],
    ABC,
):
    # can be overridden to change an input state.
    @classmethod
    def read_state(cls, state_path: str) -> Union[List[AirbyteStateMessage], MutableMapping[str, Any]]:
        """
        Retrieves the input state of a sync by reading from the specified JSON file. Incoming state can be deserialized into either
        a JSON object for legacy state input or as a list of AirbyteStateMessages for the per-stream state format. Regardless of the
        incoming input type, it will always be transformed and output as a list of AirbyteStateMessage(s).
        :param state_path: The filepath to where the stream states are located
        :return: The complete stream state based on the connector's previous sync
        """
        if state_path:
            state_obj = BaseConnector._read_json_file(state_path)
            if not state_obj:
                return cls._emit_legacy_state_format({})
            if isinstance(state_obj, List):
                parsed_state_messages = []
                for state in state_obj:  # type: ignore  # `isinstance(state_obj, List)` ensures that this is a list
                    parsed_message = AirbyteStateMessage.model_validate(state)
                    if not parsed_message.stream and not parsed_message.data and not parsed_message.global_:
                        raise ValueError("AirbyteStateMessage should contain either a stream, global, or state field")
                    parsed_state_messages.append(parsed_message)
                return parsed_state_messages
            else:
                return cls._emit_legacy_state_format(state_obj)  # type: ignore  # assuming it is a dict
        return cls._emit_legacy_state_format({})

    @classmethod
    def _emit_legacy_state_format(cls, state_obj: Dict[str, Any]) -> Union[List[AirbyteStateMessage], MutableMapping[str, Any]]:
        """
        Existing connectors that override read() might not be able to interpret the new state format. We temporarily
        send state in the old format for these connectors, but once all have been upgraded, this method can be removed,
        and we can then emit state in the list format.
        """
        # vars(self.__class__) checks if the current class directly overrides the read() function
        if "read" in vars(cls):
            return defaultdict(dict, state_obj)
        else:
            if state_obj:
                return [AirbyteStateMessage(type=AirbyteStateType.LEGACY, data=state_obj)]
            else:
                return []

    # can be overridden to change an input catalog
    @classmethod
    def read_catalog(cls, catalog_path: str) -> ConfiguredAirbyteCatalog:
        return ConfiguredAirbyteCatalog.model_validate(cls._read_json_file(catalog_path))
