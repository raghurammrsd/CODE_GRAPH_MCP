from __future__ import annotations

from codegraph.frameworks import normalize_route_path
from codegraph.indexing.parser import parse


def test_normalize_route_path_matrix() -> None:
    """Verify route parameter normalization across multiple framework syntaxes."""
    # Flask conversions
    assert normalize_route_path("/users/<id>", "flask") == "/users/{id}"
    assert normalize_route_path("/users/<int:id>", "flask") == "/users/{id}"
    assert normalize_route_path("/posts/<uuid:post_id>/comments", "flask") == "/posts/{post_id}/comments"

    # Express conversions
    assert normalize_route_path("/users/:id", "express") == "/users/{id}"
    assert normalize_route_path("/api/:orgId/members/:memberId", "express") == "/api/{orgId}/members/{memberId}"

    # Next.js conversions
    assert normalize_route_path("/users/[id]", "nextjs") == "/users/{id}"
    assert normalize_route_path("/docs/[...slug]", "nextjs") == "/docs/{slug}"

    # Trailing slash stripping
    assert normalize_route_path("/api/items/", "fastapi") == "/api/items"
    assert normalize_route_path("/", "fastapi") == "/"


def test_flask_multi_method_route_detection() -> None:
    """Verify Flask routes with multiple HTTP methods generate distinct RouteDetection objects."""
    code = """
from flask import Flask, request

app = Flask(__name__)

@app.route("/api/v1/auth/login", methods=["GET", "POST"])
def auth_login():
    return "ok"

@app.get("/items/<int:item_id>")
def get_item(item_id):
    return "item"
"""
    result = parse(code, "python", "src/views.py")
    assert not result.parse_failed

    routes = result.routes
    assert len(routes) == 3

    methods = {r.http_method for r in routes}
    assert {"GET", "POST"} <= methods

    signatures = {r.route_signature for r in routes}
    assert "GET /api/v1/auth/login" in signatures
    assert "POST /api/v1/auth/login" in signatures

    # Check normalized route parameter
    item_route = next(r for r in routes if r.handler_name == "get_item")
    assert item_route.http_method == "GET"
    assert item_route.normalized_route == "/items/{item_id}"
    assert "API_ENDPOINT" in item_route.endpoint_id


def test_fastapi_route_detection() -> None:
    """Verify FastAPI router decorators are detected during single-pass scan."""
    code = """
from fastapi import APIRouter, FastAPI

app = FastAPI()
router = APIRouter()

@router.post("/auth/token")
def create_token():
    return {}

@app.delete("/users/{user_id}")
async def delete_user(user_id: int):
    return {"deleted": True}
"""
    result = parse(code, "python", "routers/auth.py")
    assert not result.parse_failed

    routes = result.routes
    assert len(routes) == 2

    tok_route = next(r for r in routes if r.handler_name == "create_token")
    assert tok_route.http_method == "POST"
    assert tok_route.normalized_route == "/auth/token"
    assert tok_route.handler_canonical_id == "routers.auth.create_token"

    del_route = next(r for r in routes if r.handler_name == "delete_user")
    assert del_route.http_method == "DELETE"
    assert del_route.normalized_route == "/users/{user_id}"


def test_django_urlpatterns_route_detection() -> None:
    """Verify Django urlpatterns path() calls are detected."""
    code = """
from django.urls import path
from . import views

urlpatterns = [
    path("api/v1/checkout/", views.checkout_handler, name="checkout"),
    path("healthz", views.healthz_view),
]
"""
    result = parse(code, "python", "myapp/urls.py")
    assert not result.parse_failed

    routes = result.routes
    assert len(routes) >= 2

    handlers = {r.handler_name for r in routes}
    assert {"checkout_handler", "healthz_view"} <= handlers


def test_express_route_detection() -> None:
    """Verify Express.js app and router method calls are detected in JS/TS."""
    code = """
const express = require('express');
const app = express();
const router = express.Router();

app.post('/api/auth/login', loginHandler);
router.get('/users/:userId/profile', getUserProfile);
"""
    result = parse(code, "javascript", "src/server.js")
    assert not result.parse_failed

    routes = result.routes
    assert len(routes) == 2

    signatures = {r.route_signature for r in routes}
    assert "POST /api/auth/login" in signatures
    assert "GET /users/:userId/profile" in signatures

    profile_route = next(r for r in routes if r.handler_name == "getUserProfile")
    assert profile_route.normalized_route == "/users/{userId}/profile"


def test_nextjs_app_router_detection() -> None:
    """Verify Next.js App Router HTTP handlers in route.ts are detected."""
    code = """
import { NextResponse } from 'next/server';

export async function GET(request: Request) {
    return NextResponse.json({ ok: true });
}

export async function POST(request: Request) {
    return NextResponse.json({ created: true });
}
"""
    result = parse(code, "typescript", "app/api/users/route.ts")
    assert not result.parse_failed

    routes = result.routes
    assert len(routes) == 2

    methods = {r.http_method for r in routes}
    assert methods == {"GET", "POST"}

    for r in routes:
        assert r.framework == "nextjs"
        assert r.normalized_route == "/api/users"
