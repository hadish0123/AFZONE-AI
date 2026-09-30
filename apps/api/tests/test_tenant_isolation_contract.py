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
        "hard_delete_admin",
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


def test_global_plans_are_not_gated_by_materialized_admin_assignments():
    groups = function_block(MAIN, "list_groups")
    create_client = function_block(MAIN, "create_client")
    update_client = function_block(MAIN, "update_client")
    list_plans = function_block(MAIN, "list_plans")

    assert ".join(AdminPlan, AdminPlan.plan_id == Plan.id)" not in groups
    assert "plan is not assigned to this admin" not in create_client
    assert "plan is no longer assigned to this admin" not in update_client
    assert "outerjoin(" in list_plans
    assert '"automatic": admin_plan is None' in list_plans


def test_management_routes_are_not_duplicated():
    assert MAIN.count("# ---- Production management completion") == 1
    for name in (
        "update_admin",
        "update_connection",
        "update_plan",
        "update_my_retail_price",
        "get_bot_catalog",
        "update_bot_catalog",
        "directory_admins",
        "directory_clients",
    ):
        assert MAIN.count(f"async def {name}(") == 1, name


def test_bot_catalog_is_global_and_panel_has_no_native_prompts_or_selects():
    bot_source = (ROOT / "app" / "bot_worker.py").read_text(encoding="utf-8")
    web_source = (ROOT.parent / "web" / "components" / "PrimePanelV2.tsx").read_text(encoding="utf-8")

    show_plans = function_block(bot_source, "show_plans")
    assert "TelegramBotPlan" not in show_plans
    assert "outerjoin(" in show_plans
    assert "Plan.enabled.is_(True)" in show_plans

    assert "window.prompt" not in web_source
    assert "window.confirm" not in web_source
    assert "<select" not in web_source
    assert "تخصیص این پلن به نماینده" not in web_source
    assert "فقط پلن‌های انتخاب‌شده در این Bot" not in web_source


def test_deleted_clients_are_hidden_from_current_panel_views():
    deleted_filter = 'Client.remote_payload["deleted_remote"].astext.is_distinct_from("true")'
    for name in (
        "list_clients",
        "directory_clients",
        "dashboard_summary",
        "directory_admins",
    ):
        assert deleted_filter in function_block(MAIN, name), name


def test_deleted_client_username_can_be_recreated():
    block = function_block(MAIN, "create_client")
    assert 'Client.remote_payload["deleted_remote"].astext.is_distinct_from("true")' in block


def test_hard_delete_admin_purges_tenant_owned_data_and_remote_clients():
    block = function_block(MAIN, "hard_delete_admin")
    assert "Depends(require_owner)" in block
    assert "delete_user(client.username)" in block
    assert "delete_webhook(drop_pending_updates=True)" in block
    assert "delete(BillingEvent)" in block
    assert "delete(Payment)" in block
    assert "delete(Order)" in block
    assert "delete(Customer)" in block
    assert "delete(Client)" in block
    assert "delete(TelegramBot)" in block
    assert "delete(WalletTransaction)" in block
    assert "delete(Wallet)" in block
    assert "delete(PaymentProfile)" in block
    assert "delete(BankCard)" in block
    assert "delete(AuthSession)" in block
    assert "delete(UserSecurity)" in block
    assert "await db.delete(admin)" in block


def test_owner_panel_requires_username_confirmation_for_hard_admin_delete():
    web_source = (ROOT.parent / "web" / "components" / "PrimePanelV2.tsx").read_text(encoding="utf-8")
    assert "حذف دائمی نماینده" in web_source
    assert "confirm_username" in web_source
    assert "/hard" in web_source
