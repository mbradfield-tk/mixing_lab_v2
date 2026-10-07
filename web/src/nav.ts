/** Sidebar entries, in the Taipy menu order. Pages without a React `path` still live
 * in the Taipy app and open there until they are migrated. */
export const TAIPY_URL: string =
  (import.meta.env.VITE_TAIPY_URL as string | undefined) ?? "http://127.0.0.1:5000";

export interface NavItem {
  key: string;
  label: string;
  path?: string;
}

export const NAV: NavItem[] = [
  { key: "Home", label: "Home", path: "/" },
  { key: "Vessel_Database", label: "Vessels", path: "/vessels" },
  { key: "Fluid_Database", label: "Fluids", path: "/fluids" },
  { key: "Reaction_Database", label: "Reactions", path: "/reactions" },
  { key: "Particle_Database", label: "Particles", path: "/particles" },
  { key: "Bourne_Protocol", label: "Bourne Protocol", path: "/bourne-protocol" },
  { key: "Mixing_Sensitivity", label: "Reaction Sensitivity Protocol", path: "/reaction-sensitivity" },
  { key: "Crystallization_Sensitivity", label: "Crystallization Sensitivity Protocol", path: "/crystallization-sensitivity" },
  { key: "Vessel_Assessment", label: "Vessel Assessment", path: "/vessel-assessment" },
  { key: "Vessel_Comparison", label: "Vessel Comparison", path: "/vessel-comparison" },
  { key: "Heat_Transfer", label: "Heat Transfer Tool", path: "/heat-transfer" },
  { key: "Recorded_Results", label: "Recorded Results", path: "/recorded-results" },
  { key: "Unit_Converter", label: "Unit Converter", path: "/unit-converter" },
  { key: "Equations_Reference", label: "Equations Reference", path: "/equations-reference" },
];

export const navItem = (key: string): NavItem => {
  const item = NAV.find((n) => n.key === key);
  if (!item) throw new Error(`Unknown page ${key}`);
  return item;
};

export const menuIcon = (key: string, px = 96): string => `/api/v1/media/icons/${key}?px=${px}`;

export const logoUrl = (px = 96): string => menuIcon("logo", px);

export const taipyHref = (key: string): string => `${TAIPY_URL.replace(/\/$/, "")}/${key}`;
