"""Realistic Repository Corpus Generator for Multi-Language / Multi-Framework Evaluation.

Provisions realistic repositories with:
1. Python FastAPI / Flask / Django services and routes
2. TypeScript / JavaScript Express and Next.js APIs
3. Deliberately ambiguous targets (auth/login vs admin/login vs oauth/login)
4. Dynamic dispatch mechanisms (getattr / eval) for UNKNOWN verification
5. Multi-layer architecture: routes -> handlers -> services -> data/models -> tests
6. Git commit history and changesets for REVIEW / IMPACT evaluation
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def generate_full_corpus_repo(root: Path, init_git: bool = True) -> Path:
    """Generate a realistic multi-framework repository in root directory."""
    root.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # 1. FastAPI Web Subsystem (Python)
    # -------------------------------------------------------------------------
    fastapi_dir = root / "src" / "api"
    fastapi_dir.mkdir(parents=True, exist_ok=True)

    (fastapi_dir / "fastapi_app.py").write_text(
        """from fastapi import FastAPI, Depends, HTTPException
from src.services.auth_service import AuthService
from src.services.payment_service import PaymentService
from src.db.session import get_db

app = FastAPI(title="Core Commerce API")

@app.post("/api/v1/auth/login")
def login_route(email: str, password: str, db=Depends(get_db)):
    auth = AuthService(db)
    return auth.login(email, password)

@app.get("/api/v1/users/me")
def get_current_user_route(token: str, db=Depends(get_db)):
    auth = AuthService(db)
    return auth.get_user_by_token(token)

@app.post("/api/v1/payments/charge")
def charge_payment_route(amount: int, user_id: str, db=Depends(get_db)):
    payment = PaymentService(db)
    return payment.process_charge(user_id, amount)
""",
        encoding="utf-8",
    )

    # -------------------------------------------------------------------------
    # 2. Flask & Django Subsystems (Python)
    # -------------------------------------------------------------------------
    flask_dir = root / "src" / "legacy"
    flask_dir.mkdir(parents=True, exist_ok=True)

    (flask_dir / "flask_routes.py").write_text(
        """from flask import Flask, request, jsonify
from src.services.notification_service import NotificationService

flask_app = Flask(__name__)

@flask_app.route("/legacy/notify", methods=["POST"])
def legacy_notify():
    data = request.json or {}
    NotificationService().send_email(data.get("to"), data.get("msg"))
    return jsonify({"status": "sent"})
""",
        encoding="utf-8",
    )

    django_dir = root / "src" / "admin_panel"
    django_dir.mkdir(parents=True, exist_ok=True)

    (django_dir / "views.py").write_text(
        """class AdminDashboardView:
    def get(self, request):
        return {"dashboard": "admin"}

    def post(self, request):
        return {"action": "executed"}
""",
        encoding="utf-8",
    )

    # -------------------------------------------------------------------------
    # 3. Services Layer (Python)
    # -------------------------------------------------------------------------
    svc_dir = root / "src" / "services"
    svc_dir.mkdir(parents=True, exist_ok=True)

    (svc_dir / "auth_service.py").write_text(
        """from src.db.models import User
from src.db.session import DatabaseSession

class AuthService:
    def __init__(self, db: DatabaseSession):
        self.db = db

    def login(self, email: str, password: str) -> dict[str, str]:
        user = self.db.find_user(email)
        if not user or not user.verify_password(password):
            return {"error": "unauthorized"}
        return {"token": f"jwt_{user.id}"}

    def get_user_by_token(self, token: str) -> User | None:
        user_id = token.replace("jwt_", "")
        return self.db.get_user_by_id(user_id)
""",
        encoding="utf-8",
    )

    (svc_dir / "payment_service.py").write_text(
        """from src.db.session import DatabaseSession
from src.gateways.stripe_gateway import StripeGateway

class PaymentService:
    def __init__(self, db: DatabaseSession):
        self.db = db
        self.gateway = StripeGateway()

    def process_charge(self, user_id: str, amount: int) -> bool:
        if amount <= 0:
            return False
        tx_id = self.gateway.charge(amount, currency="usd")
        self.db.record_transaction(user_id, amount, tx_id)
        return True

    def refund(self, tx_id: str) -> bool:
        return self.gateway.refund(tx_id)
""",
        encoding="utf-8",
    )

    (svc_dir / "notification_service.py").write_text(
        """class NotificationService:
    def send_email(self, recipient: str, message: str) -> bool:
        return bool(recipient and message)

    def send_sms(self, phone: str, message: str) -> bool:
        return True
""",
        encoding="utf-8",
    )

    # -------------------------------------------------------------------------
    # 4. Ambiguity Subsystem (Identical names in distinct modules)
    # -------------------------------------------------------------------------
    (root / "src" / "auth").mkdir(parents=True, exist_ok=True)
    (root / "src" / "auth" / "login.py").write_text(
        """def login(credentials: dict) -> bool:
    # User authentication login
    return True
""",
        encoding="utf-8",
    )

    (root / "src" / "admin").mkdir(parents=True, exist_ok=True)
    (root / "src" / "admin" / "login.py").write_text(
        """def login(credentials: dict) -> bool:
    # Admin console login
    return False
""",
        encoding="utf-8",
    )

    (root / "src" / "oauth").mkdir(parents=True, exist_ok=True)
    (root / "src" / "oauth" / "login.py").write_text(
        """def login(credentials: dict) -> bool:
    # OAuth single-sign-on login
    return True
""",
        encoding="utf-8",
    )

    # -------------------------------------------------------------------------
    # 5. Dynamic Dispatch / Unknown Subsystem
    # -------------------------------------------------------------------------
    (root / "src" / "dynamic").mkdir(parents=True, exist_ok=True)
    (root / "src" / "dynamic" / "dispatcher.py").write_text(
        """class DynamicService:
    def execute_action(self, target_service: object, method_name: str, payload: dict):
        # Dynamic reflection without static AST evidence -> UNKNOWN relationship
        fn = getattr(target_service, method_name)
        return fn(payload)

    def run_eval(self, code_str: str):
        # Arbitrary dynamic code evaluation
        return eval(code_str)
""",
        encoding="utf-8",
    )

    # -------------------------------------------------------------------------
    # 6. Database / Persistence Layer (Python)
    # -------------------------------------------------------------------------
    db_dir = root / "src" / "db"
    db_dir.mkdir(parents=True, exist_ok=True)

    (db_dir / "models.py").write_text(
        """class User:
    def __init__(self, id: str, email: str, password_hash: str):
        self.id = id
        self.email = email
        self.password_hash = password_hash

    def verify_password(self, password: str) -> bool:
        return self.password_hash == f"hash_{password}"

class Transaction:
    def __init__(self, id: str, user_id: str, amount: int, tx_id: str):
        self.id = id
        self.user_id = user_id
        self.amount = amount
        self.tx_id = tx_id
""",
        encoding="utf-8",
    )

    (db_dir / "session.py").write_text(
        """from src.db.models import User

class DatabaseSession:
    def __init__(self):
        self.users = {
            "alice@example.com": User("u1", "alice@example.com", "hash_secret123"),
        }
        self.transactions = []

    def find_user(self, email: str) -> User | None:
        return self.users.get(email)

    def get_user_by_id(self, user_id: str) -> User | None:
        for u in self.users.values():
            if u.id == user_id:
                return u
        return None

    def record_transaction(self, user_id: str, amount: int, tx_id: str) -> None:
        self.transactions.append({"user_id": user_id, "amount": amount, "tx_id": tx_id})

def get_db() -> DatabaseSession:
    return DatabaseSession()
""",
        encoding="utf-8",
    )

    # -------------------------------------------------------------------------
    # 7. Gateway Layer (External integrations)
    # -------------------------------------------------------------------------
    gw_dir = root / "src" / "gateways"
    gw_dir.mkdir(parents=True, exist_ok=True)

    (gw_dir / "stripe_gateway.py").write_text(
        """class StripeGateway:
    def charge(self, amount: int, currency: str = "usd") -> str:
        return f"ch_stripe_{amount}"

    def refund(self, tx_id: str) -> bool:
        return True
""",
        encoding="utf-8",
    )

    # -------------------------------------------------------------------------
    # 8. TypeScript / JavaScript Subsystem (Express / Next.js)
    # -------------------------------------------------------------------------
    ts_dir = root / "frontend" / "api"
    ts_dir.mkdir(parents=True, exist_ok=True)

    (ts_dir / "server.ts").write_text(
        """import express, { Request, Response } from 'express';

const app = express();
app.use(express.json());

// Express route
app.post('/api/checkout', (req: Request, res: Response) => {
    const { cartId, amount } = req.body;
    res.json({ status: 'success', cartId, amount });
});

export default app;
""",
        encoding="utf-8",
    )

    next_dir = root / "frontend" / "pages" / "api"
    next_dir.mkdir(parents=True, exist_ok=True)

    (next_dir / "webhook.ts").write_text(
        """export default function handler(req: any, res: any) {
    if (req.method === 'POST') {
        res.status(200).json({ received: true });
    } else {
        res.status(405).end();
    }
}
""",
        encoding="utf-8",
    )

    # -------------------------------------------------------------------------
    # 9. Test Suite (Python & TypeScript)
    # -------------------------------------------------------------------------
    tests_dir = root / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    (tests_dir / "test_auth_service.py").write_text(
        """from src.services.auth_service import AuthService
from src.db.session import DatabaseSession

def test_auth_login_success():
    db = DatabaseSession()
    service = AuthService(db)
    res = service.login("alice@example.com", "secret123")
    assert "token" in res

def test_auth_login_failure():
    db = DatabaseSession()
    service = AuthService(db)
    res = service.login("alice@example.com", "wrong")
    assert res.get("error") == "unauthorized"
""",
        encoding="utf-8",
    )

    (tests_dir / "test_payment_service.py").write_text(
        """from src.services.payment_service import PaymentService
from src.db.session import DatabaseSession

def test_payment_charge_valid():
    db = DatabaseSession()
    service = PaymentService(db)
    assert service.process_charge("u1", 500) is True

def test_payment_charge_invalid():
    db = DatabaseSession()
    service = PaymentService(db)
    assert service.process_charge("u1", -10) is False
""",
        encoding="utf-8",
    )

    # -------------------------------------------------------------------------
    # 10. Optional Git Repository Initialization
    # -------------------------------------------------------------------------
    if init_git:
        try:
            subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Benchmark Author"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "benchmark@codegraph.dev"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "add", "."], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "Initial production architecture commit"], cwd=root, capture_output=True, check=True)

            # Create a second commit modifying auth_service to test REVIEW and Git diffs
            (svc_dir / "auth_service.py").write_text(
                """from src.db.models import User
from src.db.session import DatabaseSession

class AuthService:
    def __init__(self, db: DatabaseSession):
        self.db = db

    def login(self, email: str, password: str) -> dict[str, str]:
        # Revised auth logic with rate limiting hook
        user = self.db.find_user(email)
        if not user or not user.verify_password(password):
            return {"error": "unauthorized"}
        return {"token": f"jwt_{user.id}"}

    def get_user_by_token(self, token: str) -> User | None:
        user_id = token.replace("jwt_", "")
        return self.db.get_user_by_id(user_id)
""",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "src/services/auth_service.py"], cwd=root, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "Refactor AuthService login with rate limiting hook"], cwd=root, capture_output=True, check=True)
        except Exception:
            pass

    return root
