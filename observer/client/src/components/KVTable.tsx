import React from "react";

interface KVRow {
  key: string;
  value: React.ReactNode;
  /** Optional extra element after the value (e.g. copy button) */
  action?: React.ReactNode;
}

interface KVTableProps {
  rows: KVRow[];
}

/** Unified key-value table used in all detail panels. */
export function KVTable({ rows }: KVTableProps): React.ReactElement | null {
  if (rows.length === 0) return null;
  return (
    <table className="kv-table">
      <tbody>
        {rows.map(({ key, value, action }) => (
          <tr key={key} className="kv-table__row">
            <td className="kv-table__key">{key}</td>
            <td className="kv-table__val">
              {value}
              {action ? <span className="kv-table__action">{action}</span> : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
