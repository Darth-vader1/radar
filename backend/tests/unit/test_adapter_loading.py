from app.modules.adapters_loader import ADAPTER_MODULES, load_adapters
from app.modules.scraping.registry import AdapterRegistry
from app.seed import PERMISSIONS, ROLES, default_sources


def test_load_adapters_registers_every_module():
    keys = load_adapters()
    assert len(keys) >= len(ADAPTER_MODULES)


def test_load_adapters_recovers_after_registry_cleared():
    load_adapters()
    snapshot = dict(AdapterRegistry._registry)
    AdapterRegistry.clear()
    try:
        keys = load_adapters()
        assert "remotive_jobs" in keys
        assert "devpost_hackathons" in keys
    finally:
        # Restore adapters other test modules registered at import time.
        AdapterRegistry._registry.update({k: v for k, v in snapshot.items() if k not in AdapterRegistry._registry})


def test_every_seeded_source_has_a_registered_adapter():
    load_adapters()
    missing = [s["adapter_key"] for s in default_sources() if AdapterRegistry.get(s["adapter_key"]) is None]
    assert not missing, f"Seeded sources reference unregistered adapters: {missing}"


def test_seeded_module_type_matches_adapter_module_type():
    load_adapters()
    mismatched = [
        (s["adapter_key"], s["module_type"], AdapterRegistry.get(s["adapter_key"]).module_type)
        for s in default_sources()
        if AdapterRegistry.get(s["adapter_key"]).module_type != s["module_type"]
    ]
    assert not mismatched, f"Seed module_type disagrees with adapter: {mismatched}"


def test_seed_roles_only_reference_defined_permissions():
    codes = {code for code, _ in PERMISSIONS}
    for _, _, role_perms in ROLES:
        assert set(role_perms) <= codes
