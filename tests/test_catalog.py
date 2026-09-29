from app.catalog import RESOURCE_ROUTES


def test_core_resources_have_crud_routes():
    for name in ("admins", "users", "groups", "hosts", "nodes", "cores"):
        route = RESOURCE_ROUTES[name]
        assert route.list_path
        assert route.get_path
        assert route.create_path
        assert route.update_path
        assert route.delete_path
