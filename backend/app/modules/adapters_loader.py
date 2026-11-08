"""
Imports every source adapter module so its @register_adapter decorator runs.

Adapters register themselves at import time. Nothing else imports them, so any
process that executes pipelines (the API and the Celery worker) must call
load_adapters() at startup, or AdapterRegistry stays empty and every run fails.
"""
import importlib
import logging

from app.modules.scraping.registry import AdapterRegistry

logger = logging.getLogger("radar.scraping.adapters_loader")

ADAPTER_MODULES: tuple[str, ...] = (
    # BusinessRadar
    "app.modules.businesses.adapters.osm_overpass",
    "app.modules.businesses.adapters.google_places",
    # JobRadar
    "app.modules.jobs.adapters.greenhouse",
    "app.modules.jobs.adapters.remotive",
    # EventRadar
    "app.modules.events.adapters.devpost",
    "app.modules.events.adapters.zindi",
    "app.modules.events.adapters.kaggle",
    "app.modules.events.adapters.mlh",
)


def load_adapters() -> list[str]:
    """Imports all adapter modules (idempotent) and returns the registered keys."""
    for module_path in ADAPTER_MODULES:
        importlib.import_module(module_path)

    # If the registry was cleared after the modules were first imported (e.g. in
    # tests), a plain import is a no-op; reload so the decorators run again.
    if len(AdapterRegistry.list_keys()) < len(ADAPTER_MODULES):
        for module_path in ADAPTER_MODULES:
            importlib.reload(importlib.import_module(module_path))

    keys = AdapterRegistry.list_keys()
    logger.info("Loaded %d source adapters: %s", len(keys), ", ".join(keys))
    return keys
