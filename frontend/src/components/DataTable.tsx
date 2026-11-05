import { useMemo, useState, type ReactNode } from "react";

import { Button, Empty, Input } from "./ui";
import { cx } from "../lib/cx";

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  value?: (row: T) => string | number | null; // for client-side sort/search
  sortable?: boolean;
  align?: "left" | "right";
}

interface ServerPaging {
  total: number;
  page: number;
  pageSize: number;
  onPage: (page: number) => void;
  sort?: string;
  order?: "asc" | "desc";
  onSort?: (key: string) => void;
}

/**
 * Accessible table with sorting, search and pagination.
 * Client mode (default): sorts/searches/paginates `rows` in the browser.
 * Server mode (`server` prop): the parent fetches each page; sort keys go to the API.
 */
export function DataTable<T>({ columns, rows, rowKey, server, searchable = false, pageSize = 10, caption }: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  server?: ServerPaging;
  searchable?: boolean;
  pageSize?: number;
  caption?: string;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: string; desc: boolean } | null>(null);
  const [page, setPage] = useState(1);

  const view = useMemo(() => {
    if (server) return rows;
    let out = rows;
    if (query) {
      const q = query.toLowerCase();
      out = out.filter((r) => columns.some((c) => String(c.value?.(r) ?? "").toLowerCase().includes(q)));
    }
    if (sort) {
      const col = columns.find((c) => c.key === sort.key);
      if (col?.value) {
        out = [...out].sort((a, b) => {
          const va = col.value!(a), vb = col.value!(b);
          if (va === vb) return 0;
          if (va === null) return 1;
          if (vb === null) return -1;
          return (va < vb ? -1 : 1) * (sort.desc ? -1 : 1);
        });
      }
    }
    return out;
  }, [rows, query, sort, columns, server]);

  const total = server ? server.total : view.length;
  const size = server ? server.pageSize : pageSize;
  const current = server ? server.page : Math.min(page, Math.max(1, Math.ceil(total / size)));
  const pageRows = server ? view : view.slice((current - 1) * size, current * size);
  const pages = Math.max(1, Math.ceil(total / size));

  const onHeader = (c: Column<T>) => {
    if (!c.sortable) return;
    if (server?.onSort) return server.onSort(c.key);
    setSort((s) => ({ key: c.key, desc: s?.key === c.key ? !s.desc : true }));
  };
  const sortState = (c: Column<T>): "ascending" | "descending" | "none" => {
    const active = server ? server.sort === c.key : sort?.key === c.key;
    if (!active) return "none";
    const desc = server ? server.order === "desc" : sort?.desc;
    return desc ? "descending" : "ascending";
  };

  return (
    <div>
      {searchable && !server && (
        <div className="mb-3 max-w-xs">
          <Input aria-label="Search table" placeholder="Search…" value={query}
            onChange={(e) => { setQuery(e.target.value); setPage(1); }} />
        </div>
      )}
      {pageRows.length === 0 ? (
        <Empty />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            {caption && <caption className="sr-only">{caption}</caption>}
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
                {columns.map((c) => (
                  <th key={c.key} scope="col" aria-sort={c.sortable ? sortState(c) : undefined}
                    className={cx("px-3 py-2 font-medium", c.align === "right" && "text-right")}>
                    {c.sortable ? (
                      <button type="button" onClick={() => onHeader(c)} className="inline-flex items-center gap-1 uppercase hover:text-text">
                        {c.header}
                        <span aria-hidden="true">{{ ascending: "↑", descending: "↓", none: "↕" }[sortState(c)]}</span>
                      </button>
                    ) : c.header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pageRows.map((row) => (
                <tr key={rowKey(row)} className="border-b border-border last:border-0 hover:bg-surface-2">
                  {columns.map((c) => (
                    <td key={c.key} className={cx("px-3 py-2 text-text", c.align === "right" && "tabular text-right")}>
                      {c.render ? c.render(row) : String(c.value?.(row) ?? "—")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {total > size && (
        <nav aria-label="Pagination" className="mt-3 flex items-center justify-between text-xs text-text-2">
          <span className="tabular">
            {((current - 1) * size + 1).toLocaleString("en-US")}–{Math.min(current * size, total).toLocaleString("en-US")} of {total.toLocaleString("en-US")}
          </span>
          <div className="flex gap-2">
            <Button variant="secondary" disabled={current <= 1}
              onClick={() => (server ? server.onPage(current - 1) : setPage(current - 1))}>Previous</Button>
            <Button variant="secondary" disabled={current >= pages}
              onClick={() => (server ? server.onPage(current + 1) : setPage(current + 1))}>Next</Button>
          </div>
        </nav>
      )}
    </div>
  );
}
