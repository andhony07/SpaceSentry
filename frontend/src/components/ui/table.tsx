import { createContext, useContext, type ReactNode } from "react";
import { cn } from "../../utils/cx";

const TableHeaderContext = createContext(false);

export function Table({
  className,
  children,
  ...rest
}: {
  className?: string;
  children: ReactNode;
  [key: string]: unknown;
}) {
  return (
    <table
      className={cn(
        "table w-full border-collapse text-left text-sm",
        className,
      )}
      {...rest}
    >
      {children}
    </table>
  );
}

export function TableHeader({
  className,
  children,
  ...rest
}: {
  className?: string;
  children: ReactNode;
  [key: string]: unknown;
}) {
  return (
    <thead
      className={cn("table-header border-b border-slate-800/80 bg-surface-2/50", className)}
      {...rest}
    >
      <TableHeaderContext.Provider value={true}>
        {children}
      </TableHeaderContext.Provider>
    </thead>
  );
}

export function TableRow({
  className,
  children,
  ...rest
}: {
  className?: string;
  children: ReactNode;
  [key: string]: unknown;
}) {
  return (
    <tr
      className={cn(
        "table-row border-b border-slate-800/50 transition-colors hover:bg-surface-2/40",
        className,
      )}
      {...rest}
    >
      {children}
    </tr>
  );
}

export function TableCell({
  className,
  children,
  as,
  ...rest
}: {
  className?: string;
  children?: ReactNode;
  as?: "th" | "td";
  [key: string]: unknown;
}) {
  const inHeader = useContext(TableHeaderContext);
  const Tag = as ?? (inHeader ? "th" : "td");

  return (
    <Tag
      className={cn(
        "table-cell px-4 py-3 align-middle text-sm",
        inHeader
          ? "text-xs font-semibold uppercase tracking-wider text-slate-400"
          : "text-slate-300",
        className,
      )}
      {...(inHeader && Tag === "th" ? { scope: "col" } : {})}
      {...rest}
    >
      {children}
    </Tag>
  );
}

export function TablePath({
  className,
  children,
  title,
  ...rest
}: {
  className?: string;
  children: ReactNode;
  title?: string;
  [key: string]: unknown;
}) {
  return (
    <code
      className={cn(
        "table-path font-mono text-xs text-slate-200 block truncate select-text",
        className,
      )}
      title={title}
      {...rest}
    >
      {children}
    </code>
  );
}

export function TableBody({
  className,
  children,
  ...rest
}: {
  className?: string;
  children: ReactNode;
  [key: string]: unknown;
}) {
  return (
    <tbody
      className={cn("table-body divide-y divide-slate-800/50", className)}
      {...rest}
    >
      {children}
    </tbody>
  );
}
