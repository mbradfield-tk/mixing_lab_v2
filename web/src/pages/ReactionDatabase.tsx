import { useState } from "react";
import { useTable, type Row } from "../api/tables";
import { AdminPanel } from "../components/Admin";
import { AddForm, DatabaseTable, ImportExport, type Field } from "../components/Database";
import { NoticeBar, useNotice } from "../components/Notice";
import { Card, PageTitle } from "../components/ui";

const FIELDS: Field[] = [
  { key: "reaction_name", label: "Reaction name *", initial: "" },
  { key: "type", label: "Type (e.g. Cross-coupling)", initial: "" },
  { key: "class", label: "Reaction class? (yes/no)", type: "select", options: ["yes", "no"], initial: "no" },
  {
    key: "order",
    label: "Kinetic order",
    type: "select",
    options: ["1", "2", "pseudo-1", "pseudo-2", "n/a"],
    initial: "1",
  },
  { key: "k_value", label: "Rate constant k", type: "number", initial: 0.01 },
  { key: "k_units", label: "k units", initial: "1/s" },
  { key: "C0_mol_L", label: "C0 (mol/L)", type: "number", initial: 0.1 },
  { key: "t_rxn_s", label: "Reaction time (s, 0 = auto)", type: "number", initial: 0 },
  { key: "T_C", label: "Temperature (°C)", type: "number", initial: 25 },
  { key: "solvent", label: "Solvent", initial: "THF" },
  { key: "delta_H_kJ_mol", label: "ΔH_rxn (kJ/mol, negative = exothermic)", type: "number", initial: 0 },
  { key: "notes", label: "Notes", initial: "" },
  { key: "reaction_scheme", label: "Reaction scheme (e.g. A + B → C + D)", initial: "" },
];

const isClass = (r: Row) => String(r.class ?? "").trim().toLowerCase() === "yes";

function SchemeViewer({ rows }: { rows: Row[] }) {
  const [selected, setSelected] = useState("");
  const row = rows.find((r) => String(r.reaction_name) === selected);
  const scheme = row ? String(row.reaction_scheme ?? "").trim() : "";
  return (
    <>
      <label className="narrow">
        View scheme for reaction
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">— none —</option>
          {rows.map((r) => (
            <option key={String(r.reaction_name)}>{String(r.reaction_name)}</option>
          ))}
        </select>
      </label>
      {row && <p className="scheme-box">{scheme || "No reaction scheme available for this reaction."}</p>}
    </>
  );
}

export function ReactionDatabase() {
  const { notice, setNotice, run } = useNotice();
  const { list } = useTable("reactions");
  const rows = list.data?.records ?? [];

  return (
    <>
      <PageTitle pageKey="Reaction_Database">Reaction Database</PageTitle>
      <p>{list.data ? `${list.data.count} reactions in database.` : "…"}</p>

      <Card title="Databases">
        <p>
          After unlocking the <strong>Admin</strong> panel, kinetic edits are saved automatically.
          Search and browse remain available while the databases are locked.
        </p>
        <details>
          <summary>Reaction classes</summary>
          <DatabaseTable
            table="reactions"
            nameKey="reaction_name"
            run={run}
            rowFilter={isClass}
            searchLabel="Search reaction classes"
          />
        </details>
        <details>
          <summary>Measured kinetics</summary>
          <DatabaseTable
            table="reactions"
            nameKey="reaction_name"
            run={run}
            rowFilter={(r) => !isClass(r)}
            searchLabel="Search measured kinetics"
          />
        </details>
      </Card>

      <Card title="Reaction Scheme">
        <SchemeViewer rows={rows} />
      </Card>

      <Card title="Add Reaction">
        <AddForm
          table="reactions"
          fields={FIELDS}
          nameKey="reaction_name"
          noun="reaction"
          run={run}
          submitLabel="Add reaction"
        />
      </Card>

      <ImportExport table="reactions" noun="reaction" run={run} />
      <AdminPanel />
      <NoticeBar notice={notice} onClose={() => setNotice(null)} />
    </>
  );
}
