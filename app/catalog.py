from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceRoute:
    list_path: str | None
    get_path: str | None
    create_path: str | None
    update_path: str | None
    delete_path: str | None
    update_method: str = "PUT"


RESOURCE_ROUTES: dict[str, ResourceRoute] = {
    "admins": ResourceRoute("/api/admins", "/api/admin/by-id/{id}", "/api/admin", "/api/admin/by-id/{id}", "/api/admin/by-id/{id}"),
    "users": ResourceRoute("/api/users", "/api/user/by-id/{id}", "/api/user", "/api/user/by-id/{id}", "/api/user/by-id/{id}"),
    "groups": ResourceRoute("/api/groups", "/api/group/{id}", "/api/group", "/api/group/{id}", "/api/group/{id}"),
    "hosts": ResourceRoute("/api/hosts", "/api/host/{id}", "/api/host/", "/api/host/{id}", "/api/host/{id}"),
    "nodes": ResourceRoute("/api/nodes", "/api/node/{id}", "/api/node", "/api/node/{id}", "/api/node/{id}"),
    "cores": ResourceRoute("/api/cores", "/api/core/{id}", "/api/core", "/api/core/{id}", "/api/core/{id}"),
    "user_templates": ResourceRoute("/api/user_templates", "/api/user_template/{id}", "/api/user_template", "/api/user_template/{id}", "/api/user_template/{id}"),
    "client_templates": ResourceRoute("/api/client_templates", "/api/client_template/{id}", "/api/client_template", "/api/client_template/{id}", "/api/client_template/{id}"),
    "admin_roles": ResourceRoute("/api/admin-roles", "/api/admin-role/{id}", "/api/admin-role", "/api/admin-role/{id}", "/api/admin-role/{id}"),
    "api_keys": ResourceRoute("/api/api_keys", "/api/api_key/{id}", "/api/api_key", "/api/api_key/{id}", "/api/api_key/{id}", "PATCH"),
}

ACTIONS: dict[str, dict[str, tuple[str, str]]] = {
    "admins": {
        "reset_usage": ("POST", "/api/admin/by-id/{id}/reset"),
        "disable_users": ("POST", "/api/admin/by-id/{id}/users/disable"),
        "activate_users": ("POST", "/api/admin/by-id/{id}/users/activate"),
        "delete_users": ("DELETE", "/api/admin/by-id/{id}/users"),
    },
    "users": {
        "reset_usage": ("POST", "/api/user/by-id/{id}/reset"),
        "revoke_subscription": ("POST", "/api/user/by-id/{id}/revoke_sub"),
        "activate_next_plan": ("POST", "/api/user/by-id/{id}/active_next"),
    },
    "nodes": {
        "reset_usage": ("POST", "/api/node/{id}/reset"),
        "reconnect": ("POST", "/api/node/{id}/reconnect"),
        "sync": ("PUT", "/api/node/{id}/sync"),
        "update_core": ("POST", "/api/node/{id}/update"),
        "realtime_stats": ("GET", "/api/node/{id}/realtime_stats"),
        "stats": ("GET", "/api/node/{id}/stats"),
        "outbounds_latency": ("GET", "/api/node/{id}/outbounds_latency"),
    },
    "cores": {"restart": ("POST", "/api/core/{id}/restart")},
    "api_keys": {"revoke": ("POST", "/api/api_key/{id}/revoke")},
}

READ_ONLY_PATHS = {
    "settings": "/api/settings",
    "general_settings": "/api/settings/general",
    "system": "/api/system",
    "system_resources": "/api/system/resources",
    "system_users": "/api/system/users",
    "inbounds": "/api/inbounds",
    "inbound_details": "/api/inbounds/details",
    "wireguard_subnets": "/api/wireguard/subnets",
    "workers_health": "/api/workers/health",
}
