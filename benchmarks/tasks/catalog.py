"""Benchmark Task Catalog: 50 Versioned Tasks across 10 Standard Categories."""
from __future__ import annotations

from benchmarks.tasks.models import BenchmarkCategory, BenchmarkTask


def get_standard_benchmark_catalog() -> list[BenchmarkTask]:
    """Return 50 standard benchmark tasks across 10 distinct categories."""
    tasks: list[BenchmarkTask] = []

    # =========================================================================
    # 1. UNDERSTAND (5 tasks)
    # =========================================================================
    tasks.append(
        BenchmarkTask(
            task_id="understand_01_auth_flow",
            repository_id="commerce_core",
            category=BenchmarkCategory.UNDERSTAND.value,
            intent="UNDERSTAND",
            prompt="How does authentication work from login route to database verification?",
            expected_entry_points=("/api/v1/auth/login", "login_route"),
            expected_symbols=("AuthService", "login", "find_user", "verify_password"),
            expected_relationships=(
                ("login_route", "AuthService", "CALLS"),
                ("AuthService", "find_user", "CALLS"),
            ),
            expected_tests=("tests/test_auth_service.py", "test_auth_login_success"),
            allowed_files=("src/api/fastapi_app.py", "src/services/auth_service.py", "src/db/session.py", "src/db/models.py"),
            excluded_files=("src/admin_panel/views.py", "frontend/api/server.ts"),
            excluded_symbols=("AdminDashboardView", "charge_payment_route"),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="understand_02_payment_flow",
            repository_id="commerce_core",
            category=BenchmarkCategory.UNDERSTAND.value,
            intent="UNDERSTAND",
            prompt="Explain the payment charge and transaction persistence flow.",
            expected_entry_points=("/api/v1/payments/charge", "charge_payment_route"),
            expected_symbols=("PaymentService", "process_charge", "StripeGateway", "record_transaction"),
            expected_relationships=(
                ("charge_payment_route", "PaymentService", "CALLS"),
                ("PaymentService", "charge", "CALLS"),
            ),
            expected_tests=("tests/test_payment_service.py", "test_payment_charge_valid"),
            allowed_files=("src/api/fastapi_app.py", "src/services/payment_service.py", "src/gateways/stripe_gateway.py", "src/db/session.py"),
            excluded_files=("src/legacy/flask_routes.py",),
            excluded_symbols=("NotificationService",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="understand_03_user_verification",
            repository_id="commerce_core",
            category=BenchmarkCategory.UNDERSTAND.value,
            intent="UNDERSTAND",
            prompt="Where does user lookup and password verification happen?",
            expected_entry_points=(),
            expected_symbols=("User", "verify_password", "find_user", "DatabaseSession"),
            expected_relationships=(("DatabaseSession", "User", "USES"),),
            expected_tests=("tests/test_auth_service.py",),
            allowed_files=("src/db/models.py", "src/db/session.py"),
            excluded_files=("src/gateways/stripe_gateway.py",),
            excluded_symbols=("StripeGateway",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="understand_04_legacy_notifications",
            repository_id="commerce_core",
            category=BenchmarkCategory.UNDERSTAND.value,
            intent="UNDERSTAND",
            prompt="What components handle background email and SMS notifications?",
            expected_entry_points=("/legacy/notify", "legacy_notify"),
            expected_symbols=("NotificationService", "send_email", "send_sms"),
            expected_relationships=(("legacy_notify", "NotificationService", "CALLS"),),
            expected_tests=(),
            allowed_files=("src/legacy/flask_routes.py", "src/services/notification_service.py"),
            excluded_files=("src/api/fastapi_app.py",),
            excluded_symbols=("PaymentService", "AuthService"),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="understand_05_admin_console",
            repository_id="commerce_core",
            category=BenchmarkCategory.UNDERSTAND.value,
            intent="UNDERSTAND",
            prompt="Explain the admin console view structure and handlers.",
            expected_entry_points=(),
            expected_symbols=("AdminDashboardView", "get", "post"),
            expected_relationships=(),
            expected_tests=(),
            allowed_files=("src/admin_panel/views.py",),
            excluded_files=("src/api/fastapi_app.py",),
            excluded_symbols=("AuthService",),
        )
    )

    # =========================================================================
    # 2. DEBUG (5 tasks)
    # =========================================================================
    tasks.append(
        BenchmarkTask(
            task_id="debug_01_login_failure",
            repository_id="commerce_core",
            category=BenchmarkCategory.DEBUG.value,
            intent="DEBUG",
            prompt="Why does login fail after the recent auth change in AuthService?",
            expected_entry_points=("/api/v1/auth/login", "login_route"),
            expected_symbols=("AuthService", "login", "verify_password"),
            expected_relationships=(("login_route", "AuthService", "CALLS"),),
            expected_tests=("tests/test_auth_service.py", "test_auth_login_failure"),
            allowed_files=("src/services/auth_service.py", "src/db/session.py", "src/db/models.py"),
            excluded_files=("src/gateways/stripe_gateway.py",),
            excluded_symbols=("StripeGateway",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="debug_02_negative_charge",
            repository_id="commerce_core",
            category=BenchmarkCategory.DEBUG.value,
            intent="DEBUG",
            prompt="Why does POST /api/v1/payments/charge fail when amount is negative?",
            expected_entry_points=("/api/v1/payments/charge", "charge_payment_route"),
            expected_symbols=("PaymentService", "process_charge"),
            expected_relationships=(("charge_payment_route", "PaymentService", "CALLS"),),
            expected_tests=("tests/test_payment_service.py", "test_payment_charge_invalid"),
            allowed_files=("src/services/payment_service.py", "src/api/fastapi_app.py"),
            excluded_files=("src/services/notification_service.py",),
            excluded_symbols=("NotificationService",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="debug_03_missing_token",
            repository_id="commerce_core",
            category=BenchmarkCategory.DEBUG.value,
            intent="DEBUG",
            prompt="Why are users receiving unauthorized on get_current_user_route?",
            expected_entry_points=("/api/v1/users/me", "get_current_user_route"),
            expected_symbols=("AuthService", "get_user_by_token", "get_user_by_id"),
            expected_relationships=(("get_current_user_route", "AuthService", "CALLS"),),
            expected_tests=(),
            allowed_files=("src/services/auth_service.py", "src/api/fastapi_app.py", "src/db/session.py"),
            excluded_files=("src/admin_panel/views.py",),
            excluded_symbols=("AdminDashboardView",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="debug_04_empty_notification",
            repository_id="commerce_core",
            category=BenchmarkCategory.DEBUG.value,
            intent="DEBUG",
            prompt="Why does email delivery fail when recipient is empty in NotificationService?",
            expected_entry_points=("/legacy/notify", "legacy_notify"),
            expected_symbols=("NotificationService", "send_email"),
            expected_relationships=(),
            expected_tests=(),
            allowed_files=("src/services/notification_service.py", "src/legacy/flask_routes.py"),
            excluded_files=("src/services/payment_service.py",),
            excluded_symbols=("PaymentService",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="debug_05_refund_failure",
            repository_id="commerce_core",
            category=BenchmarkCategory.DEBUG.value,
            intent="DEBUG",
            prompt="Why does PaymentService refund fail when gateway transaction is invalid?",
            expected_entry_points=(),
            expected_symbols=("PaymentService", "refund", "StripeGateway"),
            expected_relationships=(("PaymentService", "refund", "CALLS"),),
            expected_tests=(),
            allowed_files=("src/services/payment_service.py", "src/gateways/stripe_gateway.py"),
            excluded_files=("src/legacy/flask_routes.py",),
            excluded_symbols=("legacy_notify",),
        )
    )

    # =========================================================================
    # 3. TRACE (5 tasks)
    # =========================================================================
    tasks.append(
        BenchmarkTask(
            task_id="trace_01_login_to_database",
            repository_id="commerce_core",
            category=BenchmarkCategory.TRACE.value,
            intent="TRACE",
            prompt="Trace POST /api/v1/auth/login through handler, service, to user lookup.",
            expected_entry_points=("/api/v1/auth/login", "login_route"),
            expected_symbols=("login_route", "AuthService", "login", "find_user", "User"),
            expected_relationships=(
                ("login_route", "AuthService", "CALLS"),
                ("AuthService", "find_user", "CALLS"),
            ),
            expected_path_nodes=("login_route", "AuthService", "find_user", "User"),
            expected_tests=("tests/test_auth_service.py",),
            allowed_files=("src/api/fastapi_app.py", "src/services/auth_service.py", "src/db/session.py", "src/db/models.py"),
            excluded_files=("src/gateways/stripe_gateway.py",),
            excluded_symbols=("StripeGateway",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="trace_02_payment_to_gateway",
            repository_id="commerce_core",
            category=BenchmarkCategory.TRACE.value,
            intent="TRACE",
            prompt="Trace POST /api/v1/payments/charge from API endpoint to StripeGateway and DB record.",
            expected_entry_points=("/api/v1/payments/charge", "charge_payment_route"),
            expected_symbols=("charge_payment_route", "PaymentService", "process_charge", "StripeGateway", "record_transaction"),
            expected_relationships=(
                ("charge_payment_route", "PaymentService", "CALLS"),
                ("PaymentService", "charge", "CALLS"),
                ("PaymentService", "record_transaction", "CALLS"),
            ),
            expected_path_nodes=("charge_payment_route", "PaymentService", "StripeGateway", "record_transaction"),
            expected_tests=("tests/test_payment_service.py",),
            allowed_files=("src/api/fastapi_app.py", "src/services/payment_service.py", "src/gateways/stripe_gateway.py", "src/db/session.py"),
            excluded_files=("src/services/notification_service.py",),
            excluded_symbols=("NotificationService",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="trace_03_current_user_me",
            repository_id="commerce_core",
            category=BenchmarkCategory.TRACE.value,
            intent="TRACE",
            prompt="Trace GET /api/v1/users/me from endpoint to user lookup by token.",
            expected_entry_points=("/api/v1/users/me", "get_current_user_route"),
            expected_symbols=("get_current_user_route", "AuthService", "get_user_by_token", "get_user_by_id"),
            expected_relationships=(("get_current_user_route", "AuthService", "CALLS"),),
            expected_path_nodes=("get_current_user_route", "AuthService", "get_user_by_id"),
            expected_tests=(),
            allowed_files=("src/api/fastapi_app.py", "src/services/auth_service.py", "src/db/session.py"),
            excluded_files=("src/admin_panel/views.py",),
            excluded_symbols=("AdminDashboardView",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="trace_04_legacy_notify",
            repository_id="commerce_core",
            category=BenchmarkCategory.TRACE.value,
            intent="TRACE",
            prompt="Trace POST /legacy/notify from Flask route to email dispatch.",
            expected_entry_points=("/legacy/notify", "legacy_notify"),
            expected_symbols=("legacy_notify", "NotificationService", "send_email"),
            expected_relationships=(("legacy_notify", "NotificationService", "CALLS"),),
            expected_path_nodes=("legacy_notify", "NotificationService", "send_email"),
            expected_tests=(),
            allowed_files=("src/legacy/flask_routes.py", "src/services/notification_service.py"),
            excluded_files=("src/services/payment_service.py",),
            excluded_symbols=("PaymentService",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="trace_05_express_checkout",
            repository_id="commerce_core",
            category=BenchmarkCategory.TRACE.value,
            intent="TRACE",
            prompt="Trace POST /api/checkout in frontend Express server.",
            expected_entry_points=("/api/checkout",),
            expected_symbols=("app",),
            expected_relationships=(),
            expected_path_nodes=("/api/checkout",),
            expected_tests=(),
            allowed_files=("frontend/api/server.ts",),
            excluded_files=("src/services/auth_service.py",),
            excluded_symbols=("AuthService",),
        )
    )

    # =========================================================================
    # 4. CHANGE (5 tasks)
    # =========================================================================
    tasks.append(
        BenchmarkTask(
            task_id="change_01_rate_limiting",
            repository_id="commerce_core",
            category=BenchmarkCategory.CHANGE.value,
            intent="CHANGE",
            prompt="Add rate limiting to AuthService.login without changing return signature.",
            expected_entry_points=("/api/v1/auth/login", "login_route"),
            expected_symbols=("AuthService", "login", "login_route"),
            expected_relationships=(("login_route", "AuthService", "CALLS"),),
            expected_tests=("tests/test_auth_service.py",),
            allowed_files=("src/services/auth_service.py", "src/api/fastapi_app.py"),
            excluded_files=("src/gateways/stripe_gateway.py",),
            excluded_symbols=("StripeGateway",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="change_02_oauth_sso",
            repository_id="commerce_core",
            category=BenchmarkCategory.CHANGE.value,
            intent="CHANGE",
            prompt="Add OAuth SSO login without modifying the User database model.",
            expected_entry_points=(),
            expected_symbols=("AuthService", "User", "DatabaseSession"),
            expected_relationships=(),
            expected_tests=("tests/test_auth_service.py",),
            allowed_files=("src/services/auth_service.py", "src/db/session.py", "src/db/models.py"),
            excluded_files=("src/admin_panel/views.py",),
            excluded_symbols=("AdminDashboardView",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="change_03_multi_currency_payments",
            repository_id="commerce_core",
            category=BenchmarkCategory.CHANGE.value,
            intent="CHANGE",
            prompt="Modify PaymentService to support multi-currency charges via StripeGateway.",
            expected_entry_points=("/api/v1/payments/charge", "charge_payment_route"),
            expected_symbols=("PaymentService", "process_charge", "StripeGateway", "charge"),
            expected_relationships=(("PaymentService", "charge", "CALLS"),),
            expected_tests=("tests/test_payment_service.py",),
            allowed_files=("src/services/payment_service.py", "src/gateways/stripe_gateway.py"),
            excluded_files=("src/legacy/flask_routes.py",),
            excluded_symbols=("NotificationService",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="change_04_sms_endpoint",
            repository_id="commerce_core",
            category=BenchmarkCategory.CHANGE.value,
            intent="CHANGE",
            prompt="Add an API endpoint exposing NotificationService.send_sms.",
            expected_entry_points=(),
            expected_symbols=("NotificationService", "send_sms"),
            expected_relationships=(),
            expected_tests=(),
            allowed_files=("src/services/notification_service.py", "src/api/fastapi_app.py"),
            excluded_files=("src/gateways/stripe_gateway.py",),
            excluded_symbols=("StripeGateway",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="change_05_user_profile_endpoint",
            repository_id="commerce_core",
            category=BenchmarkCategory.CHANGE.value,
            intent="CHANGE",
            prompt="Add user profile update endpoint backed by DatabaseSession.",
            expected_entry_points=(),
            expected_symbols=("DatabaseSession", "User", "AuthService"),
            expected_relationships=(),
            expected_tests=(),
            allowed_files=("src/db/session.py", "src/db/models.py", "src/api/fastapi_app.py"),
            excluded_files=("src/admin_panel/views.py",),
            excluded_symbols=("AdminDashboardView",),
        )
    )

    # =========================================================================
    # 5. IMPACT (5 tasks)
    # =========================================================================
    tasks.append(
        BenchmarkTask(
            task_id="impact_01_auth_login",
            repository_id="commerce_core",
            category=BenchmarkCategory.IMPACT.value,
            intent="IMPACT",
            prompt="What breaks downstream if AuthService.login is renamed or changes signature?",
            expected_entry_points=("/api/v1/auth/login", "login_route"),
            expected_symbols=("AuthService", "login", "login_route"),
            expected_relationships=(("login_route", "AuthService", "CALLS"),),
            expected_tests=("tests/test_auth_service.py", "test_auth_login_success", "test_auth_login_failure"),
            allowed_files=("src/services/auth_service.py", "src/api/fastapi_app.py", "tests/test_auth_service.py"),
            excluded_files=("src/gateways/stripe_gateway.py",),
            excluded_symbols=("StripeGateway",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="impact_02_payment_service",
            repository_id="commerce_core",
            category=BenchmarkCategory.IMPACT.value,
            intent="IMPACT",
            prompt="What components and endpoints depend on PaymentService?",
            expected_entry_points=("/api/v1/payments/charge", "charge_payment_route"),
            expected_symbols=("PaymentService", "charge_payment_route", "StripeGateway"),
            expected_relationships=(("charge_payment_route", "PaymentService", "CALLS"),),
            expected_tests=("tests/test_payment_service.py",),
            allowed_files=("src/services/payment_service.py", "src/api/fastapi_app.py", "tests/test_payment_service.py"),
            excluded_files=("src/services/notification_service.py",),
            excluded_symbols=("NotificationService",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="impact_03_user_model",
            repository_id="commerce_core",
            category=BenchmarkCategory.IMPACT.value,
            intent="IMPACT",
            prompt="What services and tests are affected by modifying the User model?",
            expected_entry_points=(),
            expected_symbols=("User", "verify_password", "AuthService", "DatabaseSession"),
            expected_relationships=(("AuthService", "find_user", "CALLS"),),
            expected_tests=("tests/test_auth_service.py",),
            allowed_files=("src/db/models.py", "src/db/session.py", "src/services/auth_service.py"),
            excluded_files=("src/admin_panel/views.py",),
            excluded_symbols=("AdminDashboardView",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="impact_04_stripe_gateway",
            repository_id="commerce_core",
            category=BenchmarkCategory.IMPACT.value,
            intent="IMPACT",
            prompt="What breaks if StripeGateway.charge changes its parameter signature?",
            expected_entry_points=(),
            expected_symbols=("StripeGateway", "charge", "PaymentService", "process_charge"),
            expected_relationships=(("PaymentService", "charge", "CALLS"),),
            expected_tests=("tests/test_payment_service.py",),
            allowed_files=("src/gateways/stripe_gateway.py", "src/services/payment_service.py"),
            excluded_files=("src/legacy/flask_routes.py",),
            excluded_symbols=("legacy_notify",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="impact_05_database_session",
            repository_id="commerce_core",
            category=BenchmarkCategory.IMPACT.value,
            intent="IMPACT",
            prompt="Downstream blast radius of modifying DatabaseSession.find_user.",
            expected_entry_points=(),
            expected_symbols=("DatabaseSession", "find_user", "AuthService", "login"),
            expected_relationships=(("AuthService", "find_user", "CALLS"),),
            expected_tests=("tests/test_auth_service.py",),
            allowed_files=("src/db/session.py", "src/services/auth_service.py"),
            excluded_files=("frontend/api/server.ts",),
            excluded_symbols=("app",),
        )
    )

    # =========================================================================
    # 6. REVIEW (5 tasks)
    # =========================================================================
    tasks.append(
        BenchmarkTask(
            task_id="review_01_auth_rate_limiting",
            repository_id="commerce_core",
            category=BenchmarkCategory.REVIEW.value,
            intent="REVIEW",
            prompt="Review recent Git commit modifying AuthService and identify affected tests.",
            expected_entry_points=("/api/v1/auth/login", "login_route"),
            expected_symbols=("AuthService", "login"),
            expected_relationships=(("login_route", "AuthService", "CALLS"),),
            expected_tests=("tests/test_auth_service.py",),
            allowed_files=("src/services/auth_service.py",),
            excluded_files=("src/gateways/stripe_gateway.py",),
            excluded_symbols=("StripeGateway",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="review_02_payment_changes",
            repository_id="commerce_core",
            category=BenchmarkCategory.REVIEW.value,
            intent="REVIEW",
            prompt="Review changes touching PaymentService and identify downstream callers.",
            expected_entry_points=("/api/v1/payments/charge", "charge_payment_route"),
            expected_symbols=("PaymentService", "process_charge", "charge_payment_route"),
            expected_relationships=(("charge_payment_route", "PaymentService", "CALLS"),),
            expected_tests=("tests/test_payment_service.py",),
            allowed_files=("src/services/payment_service.py",),
            excluded_files=("src/admin_panel/views.py",),
            excluded_symbols=("AdminDashboardView",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="review_03_admin_view_diff",
            repository_id="commerce_core",
            category=BenchmarkCategory.REVIEW.value,
            intent="REVIEW",
            prompt="Review modifications to AdminDashboardView handlers.",
            expected_entry_points=(),
            expected_symbols=("AdminDashboardView", "get", "post"),
            expected_relationships=(),
            expected_tests=(),
            allowed_files=("src/admin_panel/views.py",),
            excluded_files=("src/api/fastapi_app.py",),
            excluded_symbols=("AuthService",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="review_04_express_checkout_changes",
            repository_id="commerce_core",
            category=BenchmarkCategory.REVIEW.value,
            intent="REVIEW",
            prompt="Review changes in frontend Express server checkout route.",
            expected_entry_points=("/api/checkout",),
            expected_symbols=("app",),
            expected_relationships=(),
            expected_tests=(),
            allowed_files=("frontend/api/server.ts",),
            excluded_files=("src/services/auth_service.py",),
            excluded_symbols=("AuthService",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="review_05_notification_diff",
            repository_id="commerce_core",
            category=BenchmarkCategory.REVIEW.value,
            intent="REVIEW",
            prompt="Review changes in NotificationService email dispatch.",
            expected_entry_points=("/legacy/notify", "legacy_notify"),
            expected_symbols=("NotificationService", "send_email"),
            expected_relationships=(("legacy_notify", "NotificationService", "CALLS"),),
            expected_tests=(),
            allowed_files=("src/services/notification_service.py", "src/legacy/flask_routes.py"),
            excluded_files=("src/services/payment_service.py",),
            excluded_symbols=("PaymentService",),
        )
    )

    # =========================================================================
    # 7. REFACTOR (5 tasks)
    # =========================================================================
    tasks.append(
        BenchmarkTask(
            task_id="refactor_01_extract_token_helper",
            repository_id="commerce_core",
            category=BenchmarkCategory.REFACTOR.value,
            intent="REFACTOR",
            prompt="Refactor AuthService to extract JWT token creation into a helper.",
            expected_entry_points=("/api/v1/auth/login", "login_route"),
            expected_symbols=("AuthService", "login", "get_user_by_token"),
            expected_relationships=(),
            expected_tests=("tests/test_auth_service.py",),
            allowed_files=("src/services/auth_service.py",),
            excluded_files=("src/gateways/stripe_gateway.py",),
            excluded_symbols=("StripeGateway",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="refactor_02_gateway_interface",
            repository_id="commerce_core",
            category=BenchmarkCategory.REFACTOR.value,
            intent="REFACTOR",
            prompt="Refactor PaymentService to decouple concrete StripeGateway with an interface.",
            expected_entry_points=("/api/v1/payments/charge",),
            expected_symbols=("PaymentService", "StripeGateway", "charge"),
            expected_relationships=(("PaymentService", "charge", "CALLS"),),
            expected_tests=("tests/test_payment_service.py",),
            allowed_files=("src/services/payment_service.py", "src/gateways/stripe_gateway.py"),
            excluded_files=("src/legacy/flask_routes.py",),
            excluded_symbols=("NotificationService",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="refactor_03_migrate_flask_to_fastapi",
            repository_id="commerce_core",
            category=BenchmarkCategory.REFACTOR.value,
            intent="REFACTOR",
            prompt="Refactor legacy Flask notification route into modern FastAPI route.",
            expected_entry_points=("/legacy/notify", "legacy_notify"),
            expected_symbols=("legacy_notify", "NotificationService", "send_email"),
            expected_relationships=(("legacy_notify", "NotificationService", "CALLS"),),
            expected_tests=(),
            allowed_files=("src/legacy/flask_routes.py", "src/services/notification_service.py", "src/api/fastapi_app.py"),
            excluded_files=("src/admin_panel/views.py",),
            excluded_symbols=("AdminDashboardView",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="refactor_04_session_caching",
            repository_id="commerce_core",
            category=BenchmarkCategory.REFACTOR.value,
            intent="REFACTOR",
            prompt="Refactor DatabaseSession user lookup with in-memory caching.",
            expected_entry_points=(),
            expected_symbols=("DatabaseSession", "find_user", "User"),
            expected_relationships=(),
            expected_tests=("tests/test_auth_service.py",),
            allowed_files=("src/db/session.py", "src/db/models.py"),
            excluded_files=("frontend/api/server.ts",),
            excluded_symbols=("app",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="refactor_05_checkout_middleware",
            repository_id="commerce_core",
            category=BenchmarkCategory.REFACTOR.value,
            intent="REFACTOR",
            prompt="Refactor Express checkout handler to validate payload via middleware.",
            expected_entry_points=("/api/checkout",),
            expected_symbols=("app",),
            expected_relationships=(),
            expected_tests=(),
            allowed_files=("frontend/api/server.ts",),
            excluded_files=("src/services/auth_service.py",),
            excluded_symbols=("AuthService",),
        )
    )

    # =========================================================================
    # 8. TEST (5 tasks)
    # =========================================================================
    tasks.append(
        BenchmarkTask(
            task_id="test_01_find_auth_tests",
            repository_id="commerce_core",
            category=BenchmarkCategory.TEST.value,
            intent="TEST",
            prompt="Find all test cases covering AuthService and user login.",
            expected_entry_points=(),
            expected_symbols=("AuthService", "login"),
            expected_relationships=(),
            expected_tests=("tests/test_auth_service.py", "test_auth_login_success", "test_auth_login_failure"),
            allowed_files=("tests/test_auth_service.py", "src/services/auth_service.py"),
            excluded_files=("tests/test_payment_service.py",),
            excluded_symbols=("test_payment_charge_valid",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="test_02_find_payment_tests",
            repository_id="commerce_core",
            category=BenchmarkCategory.TEST.value,
            intent="TEST",
            prompt="Find tests covering PaymentService and payment charge operations.",
            expected_entry_points=(),
            expected_symbols=("PaymentService", "process_charge"),
            expected_relationships=(),
            expected_tests=("tests/test_payment_service.py", "test_payment_charge_valid", "test_payment_charge_invalid"),
            allowed_files=("tests/test_payment_service.py", "src/services/payment_service.py"),
            excluded_files=("tests/test_auth_service.py",),
            excluded_symbols=("test_auth_login_success",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="test_03_find_user_model_tests",
            repository_id="commerce_core",
            category=BenchmarkCategory.TEST.value,
            intent="TEST",
            prompt="Find tests asserting User password verification.",
            expected_entry_points=(),
            expected_symbols=("User", "verify_password"),
            expected_relationships=(),
            expected_tests=("tests/test_auth_service.py",),
            allowed_files=("tests/test_auth_service.py", "src/db/models.py"),
            excluded_files=("tests/test_payment_service.py",),
            excluded_symbols=("PaymentService",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="test_04_find_route_tests",
            repository_id="commerce_core",
            category=BenchmarkCategory.TEST.value,
            intent="TEST",
            prompt="Find integration tests for login endpoint.",
            expected_entry_points=("/api/v1/auth/login", "login_route"),
            expected_symbols=("login_route", "AuthService"),
            expected_relationships=(),
            expected_tests=("tests/test_auth_service.py",),
            allowed_files=("tests/test_auth_service.py", "src/api/fastapi_app.py"),
            excluded_files=("src/admin_panel/views.py",),
            excluded_symbols=("AdminDashboardView",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="test_05_find_gateway_tests",
            repository_id="commerce_core",
            category=BenchmarkCategory.TEST.value,
            intent="TEST",
            prompt="Find unit and mock tests for StripeGateway.",
            expected_entry_points=(),
            expected_symbols=("StripeGateway", "PaymentService"),
            expected_relationships=(),
            expected_tests=("tests/test_payment_service.py",),
            allowed_files=("tests/test_payment_service.py", "src/gateways/stripe_gateway.py"),
            excluded_files=("tests/test_auth_service.py",),
            excluded_symbols=("AuthService",),
        )
    )

    # =========================================================================
    # 9. ARCHITECTURE (5 tasks)
    # =========================================================================
    tasks.append(
        BenchmarkTask(
            task_id="arch_01_high_level_boundaries",
            repository_id="commerce_core",
            category=BenchmarkCategory.ARCHITECTURE.value,
            intent="ARCHITECTURE",
            prompt="Identify high-level subsystem boundaries, frameworks, and entry points.",
            expected_entry_points=("/api/v1/auth/login", "/api/v1/payments/charge", "/legacy/notify"),
            expected_symbols=("AuthService", "PaymentService", "NotificationService", "AdminDashboardView"),
            expected_relationships=(),
            expected_tests=(),
            allowed_files=("src/api/fastapi_app.py", "src/legacy/flask_routes.py", "src/admin_panel/views.py"),
            excluded_files=(),
            excluded_symbols=(),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="arch_02_routes_and_handlers",
            repository_id="commerce_core",
            category=BenchmarkCategory.ARCHITECTURE.value,
            intent="ARCHITECTURE",
            prompt="Map all HTTP routes and handlers across FastAPI and Flask.",
            expected_entry_points=("/api/v1/auth/login", "/api/v1/users/me", "/api/v1/payments/charge", "/legacy/notify"),
            expected_symbols=("login_route", "get_current_user_route", "charge_payment_route", "legacy_notify"),
            expected_relationships=(),
            expected_tests=(),
            allowed_files=("src/api/fastapi_app.py", "src/legacy/flask_routes.py"),
            excluded_files=("src/db/models.py",),
            excluded_symbols=("User",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="arch_03_dependency_layers",
            repository_id="commerce_core",
            category=BenchmarkCategory.ARCHITECTURE.value,
            intent="ARCHITECTURE",
            prompt="Analyze architectural layers between routes, services, gateways, and database.",
            expected_entry_points=(),
            expected_symbols=("AuthService", "PaymentService", "DatabaseSession", "StripeGateway"),
            expected_relationships=(
                ("AuthService", "DatabaseSession", "USES"),
                ("PaymentService", "StripeGateway", "USES"),
            ),
            expected_tests=(),
            allowed_files=("src/services/auth_service.py", "src/services/payment_service.py", "src/db/session.py", "src/gateways/stripe_gateway.py"),
            excluded_files=(),
            excluded_symbols=(),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="arch_04_external_gateways",
            repository_id="commerce_core",
            category=BenchmarkCategory.ARCHITECTURE.value,
            intent="ARCHITECTURE",
            prompt="Identify all external third-party service gateways and integrations.",
            expected_entry_points=(),
            expected_symbols=("StripeGateway", "charge", "refund"),
            expected_relationships=(),
            expected_tests=(),
            allowed_files=("src/gateways/stripe_gateway.py", "src/services/payment_service.py"),
            excluded_files=("src/admin_panel/views.py",),
            excluded_symbols=("AdminDashboardView",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="arch_05_monorepo_frontend_backend",
            repository_id="commerce_core",
            category=BenchmarkCategory.ARCHITECTURE.value,
            intent="ARCHITECTURE",
            prompt="Map monorepo layout and frontend API routes versus backend services.",
            expected_entry_points=("/api/checkout", "/api/v1/auth/login"),
            expected_symbols=("app", "AuthService"),
            expected_relationships=(),
            expected_tests=(),
            allowed_files=("frontend/api/server.ts", "src/api/fastapi_app.py"),
            excluded_files=(),
            excluded_symbols=(),
        )
    )

    # =========================================================================
    # 10. EXPLAIN (5 tasks)
    # =========================================================================
    tasks.append(
        BenchmarkTask(
            task_id="explain_01_auth_login",
            repository_id="commerce_core",
            category=BenchmarkCategory.EXPLAIN.value,
            intent="EXPLAIN",
            prompt="Explain AuthService credential lookup and password hash verification.",
            expected_entry_points=(),
            expected_symbols=("AuthService", "login", "find_user", "verify_password"),
            expected_relationships=(("AuthService", "find_user", "CALLS"),),
            expected_tests=("tests/test_auth_service.py",),
            allowed_files=("src/services/auth_service.py", "src/db/session.py", "src/db/models.py"),
            excluded_files=("src/gateways/stripe_gateway.py",),
            excluded_symbols=("StripeGateway",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="explain_02_payment_transaction_record",
            repository_id="commerce_core",
            category=BenchmarkCategory.EXPLAIN.value,
            intent="EXPLAIN",
            prompt="Explain how transactions are recorded in DatabaseSession by PaymentService.",
            expected_entry_points=(),
            expected_symbols=("PaymentService", "process_charge", "record_transaction", "DatabaseSession"),
            expected_relationships=(("PaymentService", "record_transaction", "CALLS"),),
            expected_tests=("tests/test_payment_service.py",),
            allowed_files=("src/services/payment_service.py", "src/db/session.py"),
            excluded_files=("src/services/notification_service.py",),
            excluded_symbols=("NotificationService",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="explain_03_admin_view_methods",
            repository_id="commerce_core",
            category=BenchmarkCategory.EXPLAIN.value,
            intent="EXPLAIN",
            prompt="Explain AdminDashboardView get and post method implementations.",
            expected_entry_points=(),
            expected_symbols=("AdminDashboardView", "get", "post"),
            expected_relationships=(),
            expected_tests=(),
            allowed_files=("src/admin_panel/views.py",),
            excluded_files=("src/api/fastapi_app.py",),
            excluded_symbols=("AuthService",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="explain_04_notification_dispatch",
            repository_id="commerce_core",
            category=BenchmarkCategory.EXPLAIN.value,
            intent="EXPLAIN",
            prompt="Explain email and SMS dispatch mechanisms in NotificationService.",
            expected_entry_points=(),
            expected_symbols=("NotificationService", "send_email", "send_sms"),
            expected_relationships=(),
            expected_tests=(),
            allowed_files=("src/services/notification_service.py",),
            excluded_files=("src/services/payment_service.py",),
            excluded_symbols=("PaymentService",),
        )
    )
    tasks.append(
        BenchmarkTask(
            task_id="explain_05_dynamic_dispatcher",
            repository_id="commerce_core",
            category=BenchmarkCategory.EXPLAIN.value,
            intent="EXPLAIN",
            prompt="Explain how DynamicService executes reflective actions via getattr and eval.",
            expected_entry_points=(),
            expected_symbols=("DynamicService", "execute_action", "run_eval"),
            expected_relationships=(),
            expected_unknowns=("getattr", "eval"),
            expected_tests=(),
            allowed_files=("src/dynamic/dispatcher.py",),
            excluded_files=("src/services/payment_service.py",),
            excluded_symbols=("PaymentService",),
        )
    )

    return tasks
