import { useTable } from "../api/tables";
import { AdminPanel } from "../components/Admin";
import { AddForm, DatabaseTable, ImportExport, type Field } from "../components/Database";
import { NoticeBar, useNotice } from "../components/Notice";
import { Card, PageTitle } from "../components/ui";

const FIELDS: Field[] = [
  { key: "particle_name", label: "Particle name *", initial: "" },
  { key: "rho_p_kg_m3", label: "Density ρ_p (kg/m³)", type: "number", initial: 1500 },
  { key: "shape_factor", label: "Shape factor", type: "number", initial: 1 },
  { key: "d10_um", label: "D10 (µm)", type: "number", initial: 10 },
  { key: "d50_um", label: "D50 (µm)", type: "number", initial: 50 },
  { key: "d90_um", label: "D90 (µm)", type: "number", initial: 150 },
  { key: "shape_description", label: "Shape description", initial: "" },
  { key: "notes", label: "Notes", initial: "" },
];

export function ParticleDatabase() {
  const { notice, setNotice, run } = useNotice();
  const { list } = useTable("particles");

  return (
    <>
      <PageTitle pageKey="Particle_Database">Particle Database</PageTitle>
      <p>{list.data ? `${list.data.count} particles in database.` : "…"}</p>

      <Card title="Database">
        <p>
          Edit particle properties inline after unlocking the <strong>Admin</strong> panel —{" "}
          <strong>every change is saved automatically</strong>. Use the search box to narrow the
          table, or the <strong>Add Particle</strong> form below for a validated entry.
        </p>
        <DatabaseTable table="particles" nameKey="particle_name" run={run} searchLabel="Search particles" />
      </Card>

      <Card title="Add Particle">
        <AddForm
          table="particles"
          fields={FIELDS}
          nameKey="particle_name"
          noun="particle"
          run={run}
          submitLabel="Add particle"
        />
      </Card>

      <ImportExport table="particles" noun="particle" run={run} />
      <AdminPanel />
      <NoticeBar notice={notice} onClose={() => setNotice(null)} />
    </>
  );
}
