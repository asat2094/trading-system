import { useReactTable, getCoreRowModel, getSortedRowModel, flexRender, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

interface Row { symbol: string; score?: number; signals?: Record<string, unknown> }

export default function ResultsTable({ data }: { data: Row[] }) {
  const navigate = useNavigate();
  const [sorting, setSorting] = useState<SortingState>([]);

  const columns: ColumnDef<Row>[] = [
    {
      accessorKey: "symbol",
      header: "Symbol",
      cell: ({ getValue }) => (
        <span style={{ fontFamily: "monospace", color: "#7ba7ff", fontWeight: 600 }}>{getValue() as string}</span>
      ),
    },
    {
      accessorKey: "score",
      header: "Strength",
      cell: ({ getValue }) => {
        const score = Math.round((getValue() as number) ?? 0);
        return (
          <div style={{ display: "flex", alignItems: "center", gap: 3 }}>
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} style={{ width: 14, height: 4, borderRadius: 2, background: i < score ? "#26a69a" : "#2a2e39" }} />
            ))}
          </div>
        );
      },
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
              <th key={h.id} onClick={h.column.getToggleSortingHandler()}
                style={{ cursor: "pointer", textAlign: "left", padding: "10px 16px", borderBottom: "1px solid #2a2e39", fontSize: 11, color: "#787b86", textTransform: "uppercase", letterSpacing: "0.8px", fontWeight: 600, userSelect: "none" }}>
                {flexRender(h.column.columnDef.header, h.getContext())}
                {h.column.getIsSorted() === "asc" ? " ▲" : h.column.getIsSorted() === "desc" ? " ▼" : ""}
              </th>
            ))}
          </tr>
        ))}
      </thead>
      <tbody>
        {table.getRowModel().rows.map((row) => (
          <tr key={row.id}
            onClick={() => navigate(`/chart/${row.original.symbol}`)}
            style={{ cursor: "pointer", borderBottom: "1px solid #1e222d" }}
            onMouseEnter={e => (e.currentTarget.style.background = "#1e222d")}
            onMouseLeave={e => (e.currentTarget.style.background = "transparent")}>
            {row.getVisibleCells().map((cell) => (
              <td key={cell.id} style={{ padding: "10px 16px" }}>
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
