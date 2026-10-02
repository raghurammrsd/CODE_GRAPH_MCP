from auth import AuthService


def post_login(email: str) -> dict[str, str]:
    """API entry point for POST /login."""
    user = AuthService().login(email)
    if user is None:
        raise ValueError("invalid credentials")
    return {"status": "ok"}
