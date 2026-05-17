import { useReactTable, getCoreRowModel, getSortedRowModel, flexRender, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import StrengthDots from "./StrengthDots";

interface Row { symbol: string; score?: number; signals?: Record<string, unknown> }

export default function ResultsTable({ data }: { data: Row[] }) {
  const navigate = useNavigate();
  const [sorting, setSorting] = useState<SortingState>([]);

  const columns: ColumnDef<Row>[] = [
    { accessorKey: "symbol", header: "Symbol" },
    {
      accessorKey: "score",
      header: "Strength",
      cell: ({ getValue }) => {
        const score = (getValue() as number) ?? 0;
        return <StrengthDots score={Math.round(score)} />;
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
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        {table.getHeaderGroups().map((hg) => (
          <tr key={hg.id}>
            {hg.headers.map((h) => (
              <th key={h.id} onClick={h.column.getToggleSortingHandler()}
                  style={{ cursor: "pointer", textAlign: "left", padding: "8px 12px", borderBottom: "1px solid #333" }}>
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
              style={{ cursor: "pointer" }}>
            {row.getVisibleCells().map((cell) => (
              <td key={cell.id} style={{ padding: "8px 12px", borderBottom: "1px solid #222" }}>
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
