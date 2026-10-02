class UserRepository:
    def find_by_email(self, email: str) -> dict[str, str] | None:
        return {"email": email} if email.endswith("@example.com") else None


class AuthService:
    def login(self, email: str) -> dict[str, str] | None:
        return UserRepository().find_by_email(email)
