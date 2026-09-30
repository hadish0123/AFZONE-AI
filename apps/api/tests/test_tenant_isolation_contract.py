from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
BOT = (ROOT / "app" / "bot_worker.py").read_text(encoding="utf-8")


def function_block(source: str, name: str) -> str:
    marker = f"async def {name}("
    start = source.index(marker)
    next_route = source.find("\n@app.", start)
    next_def = source.find("\nasync def ", start + len(marker))
    candidates = [i for i in (next_route, next_def) if i != -1]
    end = min(candidates) if candidates else len(source)
    return source[start:end]


def test_owner_only_control_plane_routes_stay_owner_only():
    for name in (
        "create_admin",
        "list_connections",
        "create_connection",
        "sync_groups",
        "create_plan",
        "audit_logs",
        "restore_backup",
        "directory_admins",
    ):
        assert "Depends(require_owner)" in function_block(MAIN, name), name


def test_admin_directories_are_tenant_scoped():
    expected = {
        "directory_clients": "Client.admin_id == user.id",
        "directory_orders": "Order.admin_id == user.id",
        "directory_payments": "Payment.admin_id == user.id",
        "directory_customers": "Customer.admin_id == user.id",
        "list_telegram_bots": "TelegramBot.admin_id == user.id",
    }
    for name, guard in expected.items():
        assert guard in function_block(MAIN, name), name


def test_object_mutations_reject_cross_admin_access():
    expected = {
        "update_client": "client.admin_id != user.id",
        "reset_client_usage": "client.admin_id != user.id",
        "revoke_client_subscription": "client.admin_id != user.id",
        "delete_client": "client.admin_id != user.id",
        "update_telegram_bot": "row.admin_id != user.id",
        "disable_telegram_bot": "row.admin_id != user.id",
        "get_bot_catalog": "bot.admin_id != user.id",
        "update_bot_catalog": "bot.admin_id != user.id",
        "get_payment_receipt": "payment.admin_id != user.id",
        "upload_payment_receipt": "payment.admin_id != user.id",
        "customer_wallet_transactions": "customer.admin_id != user.id",
    }
    for name, guard in expected.items():
        assert guard in function_block(MAIN, name), name


def test_admin_group_response_hides_central_pasarguard_metadata():
    block = function_block(MAIN, "list_groups")
    assert "Do not expose central PasarGuard connection IDs" in block
    assert '"name": group.name' in block
    assert "if user.role == Role.OWNER" in block


def test_telegram_manager_requires_active_owner_of_enabled_bot():
    block = function_block(BOT, "manager_context")
    assert "TelegramBot.enabled.is_(True)" in block
    assert "User.role == Role.ADMIN" in block
    assert "User.status == AccountStatus.ACTIVE" in block
    assert "int(admin.telegram_id) != int(tg_user.id)" in block
