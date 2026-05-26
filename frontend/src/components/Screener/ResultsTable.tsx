// frontend/src/components/Screener/ResultsTable.tsx
import React, { useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useNavigate } from "react-router-dom";
import { ScanResultItem, SignalDetail } from "../../api/scanner";

// ── ScoreDots ─────────────────────────────────────────────────────────────────

function ScoreDots({ score }: { score: number }) {
  const filled = Math.round(score * 5);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 3 }}>
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          style={{
            width: 14, height: 4, borderRadius: 2,
            background: i < filled ? "#26a69a" : "#2a2e39",
          }}
        />
      ))}
    </div>
  );
}

// ── SignalChip ────────────────────────────────────────────────────────────────

function SignalChip({ name, detail }: { name: string; detail: SignalDetail }) {
  return (
    <span
      style={{
        display: "inline-flex", alignItems: "center", gap: 4,
        padding: "2px 8px", borderRadius: 10, fontSize: 11,
        border: `1px solid ${detail.display.color}`,
        background: `${detail.display.color}22`,
        color: detail.display.color,
        marginRight: 4,
      }}
    >
      {detail.display.icon} {name.replace(/_/g, " ")}
    </span>
  );
}

// ── ExpandedRow ───────────────────────────────────────────────────────────────

function ExpandedRow({ item }: { item: ScanResultItem }) {
  return (
    <tr>
      <td colSpan={4} style={{ padding: "0 16px 12px 32px" }}>
        {Object.entries(item.signal_details).map(([name, detail]) => (
          <div key={name} style={{ marginTop: 8 }}>
            <div style={{ fontSize: 11, color: "#787b86", marginBottom: 4 }}>
              <span style={{ color: detail.display.color }}>
                {detail.display.icon} {name.replace(/_/g, " ")}
              </span>
              {" — "}{detail.conditions_passed}/{detail.conditions_total} conditions
            </div>
            {detail.details.children?.map((child, i) => (
              <div
                key={i}
                style={{
                  display: "flex", alignItems: "center", gap: 8,
                  fontSize: 12, color: child.passed ? "#d1d4dc" : "#787b86",
                  marginBottom: 2, paddingLeft: 8,
                }}
              >
                <span style={{ color: child.passed ? "#26a69a" : "#f23645", fontSize: 10 }}>
                  {child.passed ? "✓" : "✗"}
                </span>
                <span style={{ fontFamily: "monospace", color: "#7ba7ff" }}>{child.node_type}</span>
                {Object.entries(child)
                  .filter(([k]) => !["passed", "score", "node_type"].includes(k))
                  .map(([k, v]) => (
                    <span key={k} style={{ fontSize: 11, color: "#787b86" }}>
                      {k}: <span style={{ color: "#d1d4dc" }}>{String(v)}</span>
                    </span>
                  ))}
                <ScoreDots score={child.score} />
              </div>
            ))}
          </div>
        ))}
      </td>
    </tr>
  );
}

// ── ResultsTable ──────────────────────────────────────────────────────────────

export default function ResultsTable({ data }: { data: ScanResultItem[] }) {
  const navigate = useNavigate();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggleExpand = (symbol: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(symbol) ? next.delete(symbol) : next.add(symbol);
      return next;
    });
  };

  const columns: ColumnDef<ScanResultItem>[] = [
    {
      id: "expand",
      header: "",
      size: 32,
      cell: ({ row }) => (
        <span
          onClick={(e) => toggleExpand(row.original.symbol, e)}
          style={{ cursor: "pointer", color: "#787b86", fontSize: 10, padding: "0 4px" }}
        >
          {expanded.has(row.original.symbol) ? "▼" : "▶"}
        </span>
      ),
    },
    {
      accessorKey: "symbol",
      header: "Symbol",
      cell: ({ getValue }) => (
        <span style={{ fontFamily: "monospace", color: "#7ba7ff", fontWeight: 600 }}>
          {getValue() as string}
        </span>
      ),
    },
    {
      id: "matched_signals",
      header: "Signals",
      cell: ({ row }) => (
        <div>
          {row.original.matched_signals.map((name) => {
            const detail = row.original.signal_details[name];
            return detail ? <SignalChip key={name} name={name} detail={detail} /> : null;
          })}
        </div>
      ),
    },
    {
      accessorKey: "overall_score",
      header: "Strength",
      cell: ({ getValue }) => <ScoreDots score={getValue() as number} />,
    },
  ];

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    state: { sorting },
    onSortingChange: setSorting,
  });

  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <thead>
        {table.getHeaderGroups().map((hg) => (
          <tr key={hg.id} style={{ background: "#131722" }}>
            {hg.headers.map((h) => (
              <th
                key={h.id}
                onClick={h.column.getToggleSortingHandler()}
                style={{
                  cursor: "pointer", textAlign: "left", padding: "10px 12px",
                  borderBottom: "1px solid #2a2e39", fontSize: 11, color: "#787b86",
                  textTransform: "uppercase", letterSpacing: "0.8px",
                  fontWeight: 600, userSelect: "none",
                }}
              >
                {flexRender(h.column.columnDef.header, h.getContext())}
                {h.column.getIsSorted() === "asc" ? " ▲" : h.column.getIsSorted() === "desc" ? " ▼" : ""}
              </th>
            ))}
          </tr>
        ))}
      </thead>
      <tbody>
        {table.getRowModel().rows.map((row) => (
          <React.Fragment key={row.id}>
            <tr
              onClick={() => navigate(`/chart/${row.original.symbol}`)}
              style={{ cursor: "pointer", borderBottom: "1px solid #1e222d" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "#1e222d")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} style={{ padding: "8px 12px" }}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
            {expanded.has(row.original.symbol) && (
              <ExpandedRow item={row.original} />
            )}
          </React.Fragment>
        ))}
      </tbody>
    </table>
  );
}
