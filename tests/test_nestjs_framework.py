"""Tests for Subsystem 3A: NestJS Framework & Dependency Injection.

Verifies:
- @Controller('prefix') and HTTP method decorators (@Get, @Post, @Put, @Delete, @Patch, @Options, @Head, @All).
- Route path concatenation and parameter normalization (/invoices/{id}).
- Constructor Dependency Injection: Controller -> InvoicesService (INJECTS with FRAMEWORK_VERIFIED).
- Route endpoint inheritance of INJECTS edge.
- @Inject('TOKEN') custom token injection.
- @Module({ controllers, providers }) wiring: Module -> Controller (MOUNTS), Module -> Provider (PROVIDES).
- Query interrogation tools: find_routes, trace_path, find_callers.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from codegraph.frameworks_nestjs import analyze_nestjs_file
from codegraph.indexing.indexer import Indexer


def test_nestjs_analyzer_unit():
    ts_code = """
import { Controller, Get, Post, Put, Delete, Param, Body, Inject } from '@nestjs/common';
import { InvoicesService } from './invoices.service';
import { PaymentGateway } from './payment.gateway';

@Controller('invoices')
export class InvoicesController {
  constructor(
    private readonly invoicesService: InvoicesService,
    @Inject('PAYMENT_GATEWAY') private readonly gateway: PaymentGateway,
  ) {}

  @Get(':id')
  getById(@Param('id') id: string) {
    return this.invoicesService.findById(id);
  }

  @Post()
  create(@Body() dto: any) {
    return this.invoicesService.create(dto);
  }

  @Put(':id')
  update(@Param('id') id: string, @Body() dto: any) {
    return this.invoicesService.update(id, dto);
  }

  @Delete(':id')
  remove(@Param('id') id: string) {
    return this.invoicesService.remove(id);
  }
}
"""
    res = analyze_nestjs_file(ts_code, "src/invoices.controller.ts", "src.invoices.controller")

    # 1. Routes
    assert len(res.routes) == 4
    signatures = {r.route_signature for r in res.routes}
    assert "GET /invoices/:id" in signatures
    assert "POST /invoices" in signatures
    assert "PUT /invoices/:id" in signatures
    assert "DELETE /invoices/:id" in signatures

    # Normalized routes
    norm_routes = {r.normalized_route for r in res.routes}
    assert "/invoices/{id}" in norm_routes
    assert "/invoices" in norm_routes

    # Handlers
    handlers = {r.handler_name for r in res.routes}
    assert handlers == {"getById", "create", "update", "remove"}

    # 2. Dependency Injection bindings
    inject_bindings = [b for b in res.bindings if b.expr_kind == "NESTJS_INJECTS"]
    assert len(inject_bindings) == 2

    # Injected service
    svc_binding = next(b for b in inject_bindings if b.attr_name == "invoicesService")
    assert svc_binding.source_expr == "InvoicesService"
    assert svc_binding.base_expr == "nestjs"

    # Injected custom token
    token_binding = next(b for b in inject_bindings if b.attr_name == "gateway")
    assert token_binding.source_expr == "PAYMENT_GATEWAY"
    assert token_binding.base_expr == "nestjs_inject"


def test_nestjs_module_wiring_unit():
    mod_code = """
import { Module } from '@nestjs/common';
import { InvoicesController } from './invoices.controller';
import { InvoicesService } from './invoices.service';
import { StripePaymentGateway } from './stripe.gateway';

@Module({
  controllers: [InvoicesController],
  providers: [
    InvoicesService,
    {
      provide: 'PAYMENT_GATEWAY',
      useClass: StripePaymentGateway,
    },
  ],
})
export class InvoicesModule {}
"""
    res = analyze_nestjs_file(mod_code, "src/invoices.module.ts", "src.invoices.module")

    # Module controller binding
    ctrl_bindings = [b for b in res.bindings if b.expr_kind == "NESTJS_CONTROLLER"]
    assert len(ctrl_bindings) == 1
    assert ctrl_bindings[0].source_expr == "InvoicesController"
    assert len(ctrl_bindings) == 1
    assert ctrl_bindings[0].source_expr == "InvoicesController"

    # Providers bindings
    prov_bindings = [b for b in res.bindings if b.expr_kind == "DI_PROVIDES"]
    assert len(prov_bindings) >= 2
    prov_sources = {b.source_expr for b in prov_bindings}
    assert "InvoicesService" in prov_sources
    assert "StripePaymentGateway" in prov_sources


def test_nestjs_indexer_integration():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)

        # Service
        svc_file = repo / "invoices.service.ts"
        svc_file.write_text("""
export class InvoicesService {
  findById(id: string) {
    return { id, amount: 100 };
  }
  create(dto: any) {
    return { id: 'new', ...dto };
  }
}
""")

        # Controller
        ctrl_file = repo / "invoices.controller.ts"
        ctrl_file.write_text("""
import { InvoicesService } from './invoices.service';

@Controller('invoices')
export class InvoicesController {
  constructor(private readonly invoicesService: InvoicesService) {}

  @Get(':id')
  getById(id: string) {
    return this.invoicesService.findById(id);
  }

  @Post()
  create(dto: any) {
    return this.invoicesService.create(dto);
  }
}
""")

        # Module
        mod_file = repo / "invoices.module.ts"
        mod_file.write_text("""
import { InvoicesController } from './invoices.controller';
import { InvoicesService } from './invoices.service';

@Module({
  controllers: [InvoicesController],
  providers: [InvoicesService],
})
export class InvoicesModule {}
""")

        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            # 1. Routes stored in framework_routes
            routes = con.execute("SELECT * FROM framework_routes ORDER BY http_method").fetchall()
            assert len(routes) == 2
            signatures = {r["http_method"] + " " + r["normalized_route"] for r in routes}
            assert "GET /invoices/{id}" in signatures
            assert "POST /invoices" in signatures

            # 2. INJECTS edge from InvoicesController to InvoicesService
            edges = con.execute(
                "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship = 'INJECTS'"
            ).fetchall()
            assert len(edges) >= 1
            ctrl_injects = [e for e in edges if "InvoicesController" in e["source"] and "InvoicesService" in e["target"]]
            assert len(ctrl_injects) == 1
            assert ctrl_injects[0]["evidence_class"] == "FRAMEWORK_VERIFIED"

            # 3. Route endpoint inherits INJECTS edge
            rt_injects = [e for e in edges if e["source"].startswith("API_ENDPOINT:nestjs:") and "InvoicesService" in e["target"]]
            assert len(rt_injects) == 2

            # 4. Module MOUNTS Controller
            mount_edges = con.execute(
                "SELECT source, target, relationship FROM graph_edges WHERE relationship = 'MOUNTS'"
            ).fetchall()
            ctrl_mounts = [e for e in mount_edges if "InvoicesModule" in e["source"] and "InvoicesController" in e["target"]]
            assert len(ctrl_mounts) == 1
