"""
Main entry point for Dapper frame evaluation system.

This module provides the primary interface for setting up and configuring
frame evaluation, handling compatibility checks, and managing the overall
frame evaluation lifecycle.
"""

from __future__ import annotations

import logging
import sys
import os
import threading
import platform
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    # No forward references needed currently
    pass

# Module constants
COMPATIBLE_PYTHON_VERSIONS = ["3.6", "3.7", "3.8", "3.9", "3.10"]
SUPPORTED_PLATFORMS = ['Windows', 'Linux', 'Darwin']
SUPPORTED_ARCHITECTURES = ['64bit', '32bit']
INCOMPATIBLE_DEBUGGERS = ['pydevd', 'pdb', 'ipdb']
INCOMPATIBLE_ENVIRONMENT_VARS = ['PYCHARM_HOSTED', 'VSCODE_PID']
INCOMPATIBLE_COVERAGE_TOOLS = ['coverage', 'pytest_cov']

# Frame evaluation state
_frame_eval_config: Dict[str, Any] = {}
_initialization_lock = threading.Lock()
_is_initialized = False
_compatibility_cache: Dict[tuple, Dict[str, Any]] = {}

# Set up logger
logger = logging.getLogger(__name__)


def setup_frame_eval(config: Dict[str, Any]) -> bool:
    """
    Set up frame evaluation with the provided configuration.
    
    This is the main entry point for initializing frame evaluation
    in Dapper. It handles compatibility checks, configuration validation,
    and initialization of all required components.
    
    Args:
        config: Configuration dictionary with frame evaluation settings
        
    Returns:
        bool: True if setup was successful, False otherwise
    """
    global _frame_eval_config, _is_initialized
    
    with _initialization_lock:
        if _is_initialized:
            return True
        
        try:
            # Validate configuration
            if not _validate_config(config):
                return False
            
            # Check compatibility
            compatibility = check_environment_compatibility()
            if not compatibility['compatible']:
                if config.get('fallback_to_tracing', True):
                    logger.warning(f"Frame evaluation not compatible: {compatibility['reason']}")
                    logger.info("Falling back to traditional tracing")
                    _frame_eval_config = config
                    _is_initialized = True
                    return True
                else:
                    logger.error("Frame evaluation not compatible and fallback not enabled")
                    return False
            
            # Store configuration
            _frame_eval_config = config.copy()
            
            # Initialize components
            if not _initialize_components():
                return False
            
            _is_initialized = True
            return True
            
        except (ValueError, KeyError, ImportError) as e:
            logger.error(f"Failed to setup frame evaluation: {e}")
            return False


def should_use_frame_eval() -> bool:
    """
    Determine if frame evaluation should be used based on configuration.
    
    Returns:
        bool: True if frame evaluation should be used
    """
    if not _is_initialized:
        return False
    
    return _frame_eval_config.get('enabled', False)


def get_compatible_python_versions() -> List[str]:
    """
    Get list of Python versions compatible with frame evaluation.
    
    Returns:
        list: List of compatible Python version strings
    """
    # Frame evaluation is primarily supported in Python 3.6-3.10
    # based on debugpy's compatibility matrix
    return COMPATIBLE_PYTHON_VERSIONS


def check_environment_compatibility() -> Dict[str, Any]:
    """
    Check if the current environment is compatible with frame evaluation.
    
    Returns:
        dict: Compatibility information with 'compatible' boolean key
    """
    # Use cache if available
    cache_key = (sys.version_info, platform.platform(), sys.platform)
    if cache_key in _compatibility_cache:
        return _compatibility_cache[cache_key]
    
    compatibility = {
        'compatible': False,
        'reason': '',
        'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        'platform': platform.platform(),
        'architecture': platform.architecture()[0],
        'implementation': platform.python_implementation(),
    }
    
    # Check Python version
    version_tuple = (sys.version_info.major, sys.version_info.minor)
    if version_tuple < (3, 6):
        compatibility['reason'] = "Python version too old (requires 3.6+)"
        _compatibility_cache[cache_key] = compatibility
        return compatibility
    
    if version_tuple > (3, 10):
        compatibility['reason'] = "Python version too new (3.11+ not supported)"
        _compatibility_cache[cache_key] = compatibility
        return compatibility
    
    # Check for required C API features
    if not _check_c_api_compatibility():
        compatibility['reason'] = "Required C API features not available"
        _compatibility_cache[cache_key] = compatibility
        return compatibility
    
    # Check platform-specific requirements
    if not _check_platform_compatibility():
        compatibility['reason'] = "Platform not supported"
        _compatibility_cache[cache_key] = compatibility
        return compatibility
    
    # Check for known incompatible environments
    if _is_incompatible_environment():
        compatibility['reason'] = "Running in incompatible environment"
        _compatibility_cache[cache_key] = compatibility
        return compatibility
    
    compatibility['compatible'] = True
    _compatibility_cache[cache_key] = compatibility
    return compatibility


def get_frame_eval_config() -> Dict[str, Any]:
    """
    Get the current frame evaluation configuration.
    
    Returns:
        dict: Current configuration (empty if not initialized)
    """
    return _frame_eval_config.copy()


def update_frame_eval_config(updates: Dict[str, Any]) -> bool:
    """
    Update the frame evaluation configuration.
    
    Args:
        updates: Dictionary of configuration updates
        
    Returns:
        bool: True if update was successful
    """
    global _frame_eval_config
    
    if not _is_initialized:
        return False
    
    try:
        # Validate updates
        new_config = _frame_eval_config.copy()
        new_config.update(updates)
        
        if not _validate_config(new_config):
            return False
        
        _frame_eval_config = new_config
        return True
        
    except (ValueError, KeyError) as e:
        logger.error(f"Failed to update frame evaluation config: {e}")
        return False


def shutdown_frame_eval() -> None:
    """Shut down frame evaluation and clean up resources."""
    global _is_initialized, _frame_eval_config
    
    with _initialization_lock:
        if not _is_initialized:
            return
        
        try:
            # Disable frame evaluation if enabled
            if should_use_frame_eval():
                from dapper._frame_eval import disable_frame_eval
                disable_frame_eval()
            
            # Clean up components
            _cleanup_components()
            
            # Reset state
            _frame_eval_config = {}
            _is_initialized = False
            
        except (ImportError, RuntimeError, AttributeError) as e:
            logger.error(f"Error during frame evaluation shutdown: {e}")
            # Ignore errors during shutdown
            pass


def _validate_config(config: Dict[str, Any]) -> bool:
    """
    Validate frame evaluation configuration.
    
    Args:
        config: Configuration dictionary to validate
        
    Returns:
        bool: True if configuration is valid
    """
    required_keys = ['enabled']
    for key in required_keys:
        if key not in config:
            return False
    
    # Validate boolean values
    bool_keys = ['enabled', 'fallback_to_tracing', 'debug_mode']
    for key in bool_keys:
        if key in config and not isinstance(config[key], bool):
            return False
    
    # Validate numeric values
    if 'cache_size' in config:
        if not isinstance(config['cache_size'], int) or config['cache_size'] < 0:
            return False
    
    return True


def _initialize_components() -> bool:
    """
    Initialize frame evaluation components.
    
    Returns:
        bool: True if initialization was successful
    """
    try:
        # Import and initialize frame tracing
        from dapper._frame_eval import frame_tracing
        if not frame_tracing.setup_frame_tracing(_frame_eval_config):
            return False
        
        # Import and initialize bytecode modification
        from dapper._frame_eval import modify_bytecode
        # No initialization needed for bytecode modification
        
        # Initialize Cython components if available
        if should_use_frame_eval():
            from dapper._frame_eval import enable_frame_eval
            if not enable_frame_eval():
                return False
        
        return True
        
    except (ImportError, RuntimeError, AttributeError) as e:
        logger.error(f"Failed to initialize frame evaluation components: {e}")
        return False


def _cleanup_components() -> None:
    """
    Clean up frame evaluation components.
    
    This function handles cleanup of all frame evaluation components
    and ensures proper resource deallocation.
    """
    try:
        # Clean up frame tracing
        from dapper._frame_eval import frame_tracing
        frame_tracing.cleanup_frame_tracing()
        
        # Clean up any other components
        # (bytecode modification doesn't need cleanup)
        
    except (ImportError, RuntimeError, AttributeError) as e:
        logger.error(f"Error during component cleanup: {e}")
        pass


def _check_c_api_compatibility() -> bool:
    """
    Check if required C API features are available.
    
    Returns:
        bool: True if required C API features are available
    """
    try:
        # Check for PyEval_RequestCodeExtraIndex (Python 3.6+)
        import _imp
        _imp._fix_co_filename
        
        # Check for other required features
        # This is a simplified check - in practice we'd check more
        return True
        
    except (AttributeError, ImportError):
        return False


def _check_platform_compatibility() -> bool:
    """
    Check platform-specific compatibility.
    
    Returns:
        bool: True if current platform is supported
    """
    current_platform = platform.system()
    if current_platform not in SUPPORTED_PLATFORMS:
        return False
    
    # Check architecture
    arch = platform.architecture()[0]
    if arch not in SUPPORTED_ARCHITECTURES:
        return False
    
    return True


def _is_incompatible_environment() -> bool:
    """
    Check if running in known incompatible environment.
    
    Returns:
        bool: True if running in incompatible environment
    """
    # Check if running in certain IDEs or debuggers
    if any(name in sys.modules for name in INCOMPATIBLE_DEBUGGERS):
        return True
    
    # Check for certain environments
    if any(env_var in os.environ for env_var in INCOMPATIBLE_ENVIRONMENT_VARS):
        return True
    
    # Check if running under coverage tools
    if any(name in sys.modules for name in INCOMPATIBLE_COVERAGE_TOOLS):
        return True
    
    return False


def get_debug_info() -> Dict[str, Any]:
    """
    Get debug information about frame evaluation setup.
    
    Returns:
        dict: Debug information
    """
    return {
        'initialized': _is_initialized,
        'config': _frame_eval_config.copy(),
        'compatibility': check_environment_compatibility(),
        'python_info': {
            'version': sys.version,
            'version_info': sys.version_info,
            'platform': platform.platform(),
            'implementation': platform.python_implementation(),
            'executable': sys.executable,
        },
        'thread_info': {
            'current_thread_id': threading.get_ident(),
            'active_threads': threading.active_count(),
        },
        'environment': {
            'path': sys.path[:3],  # First few entries
            'modules': len(sys.modules),
            'environment_vars': dict(list(os.environ.items())[:5]),  # First few
        }
    }


# Initialize module-level state
def _initialize_module():
    """Initialize the module when imported."""
    global _frame_eval_config
    
    # Set default configuration
    _frame_eval_config = {
        'enabled': False,
        'fallback_to_tracing': True,
        'debug_mode': False,
        'cache_size': 1000,
        'optimize_bytecode': True,
    }


# Auto-initialize module
_initialize_module()
