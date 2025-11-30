"""Configuration management for Dapper debug adapter."""

from dapper.config.config_manager import ConfigContext
from dapper.config.config_manager import get_config
from dapper.config.config_manager import reset_config
from dapper.config.config_manager import set_config
from dapper.config.config_manager import update_config
from dapper.config.dapper_config import DEFAULT_CONFIG
from dapper.config.dapper_config import DapperConfig
from dapper.config.dapper_config import DebuggeeConfig
from dapper.config.dapper_config import IPCConfig

__all__ = [
    "DEFAULT_CONFIG",
    "ConfigContext",
    "DapperConfig",
    "DebuggeeConfig",
    "IPCConfig",
    "get_config",
    "reset_config",
    "set_config",
    "update_config",
]
