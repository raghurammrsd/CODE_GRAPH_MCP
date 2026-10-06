"""Tests for Subsystem 3B: Next.js App Router & Server Actions.

Verifies:
- Directory-derived routes for app/**/route.ts and src/app/**/route.ts.
- Route group unwrapping: app/(auth)/login/route.ts -> /login.
- Dynamic segment normalization: [id] -> {id}, [...slug] -> {slug}, [[...slug]] -> {slug}.
- HTTP methods: GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS.
- Page routes: app/**/page.tsx -> GET route with default export handler.
- File-level 'use server' directives marking exported functions as Server Actions.
- Function-level 'use server' directives inside async functions.
- Client component hydration boundaries: file-level 'use client'.
- Indexer integration storing Next.js routes in framework_routes.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from codegraph.frameworks_nextjs import analyze_nextjs_file, resolve_nextjs_route_path
from codegraph.indexing.indexer import Indexer


def test_nextjs_route_path_resolution():
    # 1. Basic API route
    raw, norm = resolve_nextjs_route_path("app/api/invoices/[id]/route.ts")
    assert raw == "/api/invoices/[id]"
    assert norm == "/api/invoices/{id}"

    # 2. Nested src/app with route group
    raw, norm = resolve_nextjs_route_path("src/app/(auth)/login/route.ts")
    assert raw == "/login"
    assert norm == "/login"

    # 3. Multiple route groups and parallel slots
    raw, norm = resolve_nextjs_route_path("app/(marketing)/(homepage)/page.tsx")
    assert raw == "/"
    assert norm == "/"

    # 4. Catch-all dynamic segments
    raw, norm = resolve_nextjs_route_path("app/docs/[...slug]/page.tsx")
    assert raw == "/docs/[...slug]"
    assert norm == "/docs/{slug}"

    # 5. Optional catch-all
    raw, norm = resolve_nextjs_route_path("app/shop/[[...categories]]/page.tsx")
    assert raw == "/shop/[[...categories]]"
    assert norm == "/shop/{categories}"


def test_nextjs_route_handlers_unit():
    code = """
import { NextResponse } from 'next/server';

export async function GET(request: Request) {
  return NextResponse.json({ ok: true });
}

export async function POST(request: Request) {
  const body = await request.json();
  return NextResponse.json(body);
}

export const DELETE = async (request: Request) => {
  return new Response(null, { status: 204 });
};
"""
    res = analyze_nextjs_file(code, "app/api/invoices/[id]/route.ts", "app.api.invoices.id.route")
    assert len(res.routes) == 3
    sigs = {r.route_signature for r in res.routes}
    assert "GET /api/invoices/[id]" in sigs
    assert "POST /api/invoices/[id]" in sigs
    assert "DELETE /api/invoices/[id]" in sigs

    norm_routes = {r.normalized_route for r in res.routes}
    assert norm_routes == {"/api/invoices/{id}"}

    handlers = {r.handler_name for r in res.routes}
    assert handlers == {"GET", "POST", "DELETE"}


def test_nextjs_page_routes_unit():
    code = """
import React from 'react';

export default function InvoiceDetailsPage({ params }: { params: { id: string } }) {
  return <div>Invoice {params.id}</div>;
}
"""
    res = analyze_nextjs_file(code, "app/(dashboard)/invoices/[id]/page.tsx", "app.dashboard.invoices.id.page")
    assert len(res.routes) == 1
    rt = res.routes[0]
    assert rt.http_method == "GET"
    assert rt.route_path == "/invoices/[id]"
    assert rt.normalized_route == "/invoices/{id}"
    assert rt.handler_name == "InvoiceDetailsPage"


def test_nextjs_server_actions_unit():
    # File-level 'use server'
    code_file = """
'use server';

import { db } from '@/lib/db';

export async function createInvoice(formData: FormData) {
  const amount = formData.get('amount');
  return { success: true };
}

export const deleteInvoice = async (id: string) => {
  return { deleted: true };
};
"""
    res_file = analyze_nextjs_file(code_file, "app/actions/invoices.ts", "app.actions.invoices")
    assert res_file.is_server_actions_file
    assert set(res_file.server_actions) == {"createInvoice", "deleteInvoice"}
    action_bindings = [b for b in res_file.bindings if b.expr_kind == "SERVER_ACTION"]
    assert len(action_bindings) == 2

    # Inline 'use server'
    code_inline = """
export async function updateInvoice(id: string) {
  'use server';
  return { updated: true };
}
"""
    res_inline = analyze_nextjs_file(code_inline, "app/components/InvoiceForm.tsx", "app.components.InvoiceForm")
    assert "updateInvoice" in res_inline.server_actions


def test_nextjs_client_component_unit():
    code = """
'use client';

import { useState } from 'react';

export function InvoiceButton() {
  const [count, setCount] = useState(0);
  return <button onClick={() => setCount(count + 1)}>Clicked {count}</button>;
}
"""
    res = analyze_nextjs_file(code, "app/components/InvoiceButton.tsx", "app.components.InvoiceButton")
    assert res.is_client_component
    assert len(res.evidence) >= 1
    assert res.evidence[0].construct_type == "CLIENT_COMPONENT"


def test_nextjs_indexer_integration():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)

        # 1. API Route Handler: app/api/invoices/[id]/route.ts
        api_dir = repo / "app" / "api" / "invoices" / "[id]"
        api_dir.mkdir(parents=True, exist_ok=True)
        route_file = api_dir / "route.ts"
        route_file.write_text("""
import { NextResponse } from 'next/server';

export async function GET(request: Request) {
  return NextResponse.json({ id: '123' });
}

export async function DELETE(request: Request) {
  return new Response(null, { status: 204 });
}
""")

        # 2. Page route with route group: app/(dashboard)/invoices/page.tsx
        dash_dir = repo / "app" / "(dashboard)" / "invoices"
        dash_dir.mkdir(parents=True, exist_ok=True)
        page_file = dash_dir / "page.tsx"
        page_file.write_text("""
export default function InvoicesPage() {
  return <div>Invoices</div>;
}
""")

        # 3. Server Actions file: app/actions/invoices.ts
        act_dir = repo / "app" / "actions"
        act_dir.mkdir(parents=True, exist_ok=True)
        act_file = act_dir / "invoices.ts"
        act_file.write_text("""
'use server';

export async function archiveInvoice(id: string) {
  return { archived: true };
}
""")

        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            # Check framework_routes table
            routes = con.execute("SELECT * FROM framework_routes ORDER BY normalized_route, http_method").fetchall()
            assert len(routes) >= 3

            sigs = {r["http_method"] + " " + r["normalized_route"] for r in routes}
            assert "GET /api/invoices/{id}" in sigs
            assert "DELETE /api/invoices/{id}" in sigs
            assert "GET /invoices" in sigs
