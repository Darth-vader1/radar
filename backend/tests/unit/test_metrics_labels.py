from types import SimpleNamespace

from app.core.metrics import route_label


def scope(path, route_path, params=None):
    route = SimpleNamespace(path=route_path, path_format=route_path)
    return {"path": path, "route": route, "path_params": params or {}}


def test_prefix_of_included_router_is_restored():
    s = scope("/api/v1/tasks/runs/3f1c", "/tasks/runs/{run_id}", {"run_id": "3f1c"})
    assert route_label(s) == "/api/v1/tasks/runs/{run_id}"


def test_parameter_values_never_leak_into_label():
    run_id = "123e4567-e89b-12d3-a456-426614174000"
    label = route_label(scope(f"/api/v1/tasks/runs/{run_id}", "/tasks/runs/{run_id}", {"run_id": run_id}))
    assert run_id not in label


def test_route_without_prefix():
    assert route_label(scope("/metrics", "/metrics")) == "/metrics"


def test_unmatched_requests_share_one_label():
    assert route_label({"path": "/wp-admin/x.php"}) == "unmatched"


def test_falls_back_to_template_when_rendering_fails():
    s = scope("/api/v1/items/1", "/items/{item_id}", {})  # params missing
    assert route_label(s) == "/items/{item_id}"
