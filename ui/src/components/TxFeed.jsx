import React from "react";

/**
 * A live sample of real attempts. `provider said` vs `we stored` sit next to each
 * other on purpose: that is where a mapping bug becomes visible to a human.
 */
export default function TxFeed({ transactions }) {
  const rows = (transactions || []).slice(0, 14);
  if (!rows.length) return null;
  return (
    <table className="tx">
      <thead>
        <tr>
          <th>provider</th><th>raw code</th><th>provider said</th>
          <th>we stored</th><th>category</th><th>segment</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((t) => {
          const said = t.raw_status === "APPROVED" ? "approved"
                     : t.raw_status === "ERROR" ? "error" : "declined";
          const mismatch = said !== t.status;
          return (
            <tr key={t.id}>
              <td>{t.provider}</td>
              <td>{t.raw_code}</td>
              <td className={mismatch ? "mismatch" : ""}>{t.raw_status}</td>
              <td className={mismatch ? "mismatch" : `st-${t.status}`}>{t.status}</td>
              <td>{t.decline_category}</td>
              <td className="muted">{t.country}/{t.method}{t.issuer ? `/${t.issuer}` : ""}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
