import logging
from typing import Dict, List, Optional, Type
from app.modules.scraping.adapter_base import SourceAdapter

logger = logging.getLogger("radar.scraping.registry")


class AdapterRegistry:
    _registry: Dict[str, Type[SourceAdapter]] = {}

    @classmethod
    def register(cls, key: str, adapter_cls: Type[SourceAdapter]) -> None:
        if key in cls._registry:
            logger.warning("Overwriting registered adapter for key '%s'", key)
        cls._registry[key] = adapter_cls
        logger.info("Registered source adapter: %s -> %s", key, adapter_cls.__name__)

    @classmethod
    def get(cls, key: str) -> Optional[Type[SourceAdapter]]:
        return cls._registry.get(key)

    @classmethod
    def list_keys(cls) -> List[str]:
        return sorted(list(cls._registry.keys()))

    @classmethod
    def clear(cls) -> None:
        cls._registry.clear()


def register_adapter(key: str):
    """Decorator to register a SourceAdapter implementation."""
    def decorator(cls: Type[SourceAdapter]):
        cls.adapter_key = key
        AdapterRegistry.register(key, cls)
        return cls
    return decorator
