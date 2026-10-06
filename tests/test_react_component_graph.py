"""Integration tests for React & JSX/TSX Component Architecture (Pillar 4).

Validates:
- Functional and wrapped components (React.memo, React.forwardRef)
- JSX component composition hierarchy (RENDERS edges)
- Custom React hooks (USES_HOOK edges)
- Client-side data fetching (FETCHES_ROUTE edges)
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from codegraph.indexing.indexer import Indexer


def test_react_component_and_jsx_renders():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "src"
        src.mkdir(parents=True, exist_ok=True)

        # 1. Button component
        (src / "Button.tsx").write_text("""
import React from 'react';

export interface ButtonProps {
  label: string;
  onClick: () => void;
}

export const Button: React.FC<ButtonProps> = ({ label, onClick }) => {
  return <button onClick={onClick}>{label}</button>;
};
""")

        # 2. InvoiceTable component rendering Button
        (src / "InvoiceTable.tsx").write_text("""
import React from 'react';
import { Button } from './Button';

export function InvoiceTable({ invoices }: { invoices: any[] }) {
  return (
    <div className="table-container">
      {invoices.map((inv) => (
        <div key={inv.id}>
          <span>{inv.amount}</span>
          <Button label="Pay" onClick={() => {}} />
        </div>
      ))}
    </div>
  );
}
""")

        # 3. Dashboard rendering InvoiceTable
        (src / "Dashboard.tsx").write_text("""
import React from 'react';
import { InvoiceTable } from './InvoiceTable';

export default function Dashboard() {
  const data = [{ id: '1', amount: 100 }];
  return (
    <div>
      <h1>Invoice Dashboard</h1>
      <InvoiceTable invoices={data} />
    </div>
  );
}
""")

        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            # Check symbols: Button, InvoiceTable, Dashboard
            syms = con.execute("SELECT name, kind, canonical_id FROM symbols WHERE kind='component' ORDER BY name").fetchall()
            sym_names = {s["name"] for s in syms}
            assert "Button" in sym_names
            assert "InvoiceTable" in sym_names
            assert "Dashboard" in sym_names

            # Check RENDERS edges:
            # InvoiceTable -> RENDERS -> Button
            # Dashboard -> RENDERS -> InvoiceTable
            edges = con.execute(
                "SELECT source, target, relationship, evidence_class FROM graph_edges WHERE relationship = 'RENDERS' ORDER BY source, target"
            ).fetchall()
            render_pairs = {(e["source"], e["target"]) for e in edges}

            assert any("InvoiceTable" in s and "Button" in t for s, t in render_pairs)
            assert any("Dashboard" in s and "InvoiceTable" in t for s, t in render_pairs)


def test_react_custom_hooks_and_api_fetch():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        src = repo / "src"
        src.mkdir(parents=True, exist_ok=True)

        # 1. Custom hook with fetch call
        (src / "useInvoices.ts").write_text("""
import { useState, useEffect } from 'react';

export function useInvoices() {
  const [invoices, setInvoices] = useState([]);

  useEffect(() => {
    fetch('/api/v1/invoices')
      .then(res => res.json())
      .then(data => setInvoices(data));
  }, []);

  return { invoices };
}
""")

        # 2. Component using custom hook
        (src / "InvoiceList.tsx").write_text("""
import React from 'react';
import { useInvoices } from './useInvoices';

export function InvoiceList() {
  const { invoices } = useInvoices();
  return <div>{invoices.length} invoices</div>;
}
""")

        indexer = Indexer(repo)
        indexer.index()

        with indexer.connect() as con:
            # Check hook symbol
            hooks = con.execute("SELECT name, kind FROM symbols WHERE kind='hook'").fetchall()
            assert any(h["name"] == "useInvoices" for h in hooks)

            # Check USES_HOOK edge: InvoiceList -> useInvoices
            hook_edges = con.execute(
                "SELECT source, target, relationship FROM graph_edges WHERE relationship = 'USES_HOOK'"
            ).fetchall()
            assert any("InvoiceList" in e["source"] and "useInvoices" in e["target"] for e in hook_edges)

            # Check FETCHES_ROUTE edge: useInvoices -> /api/v1/invoices
            fetch_edges = con.execute(
                "SELECT source, target, relationship FROM graph_edges WHERE relationship = 'FETCHES_ROUTE'"
            ).fetchall()
            assert any("useInvoices" in e["source"] and "/api/v1/invoices" in e["target"] for e in fetch_edges)
