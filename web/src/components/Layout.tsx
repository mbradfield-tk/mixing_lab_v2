import { NavLink, Outlet } from "react-router-dom";
import { NAV, logoUrl, menuIcon, taipyHref } from "../nav";
import { setTheme, useTheme } from "../theme";

function ThemeToggle() {
  const dark = useTheme() === "dark";
  return (
    <button
      type="button"
      className="theme-toggle"
      aria-pressed={dark}
      onClick={() => setTheme(dark ? "light" : "dark")}
    >
      <span className="theme-icon" aria-hidden>{dark ? "☀️" : "🌙"}</span>
      <span>{dark ? "Light mode" : "Dark mode"}</span>
    </button>
  );
}

export function Layout() {
  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Main">
        <NavLink to="/" end className="brand">
          <img src={logoUrl()} alt="" />
          <span>Mixing Lab</span>
        </NavLink>
        <ul>
          {NAV.map((item) => (
            <li key={item.key}>
              {item.path ? (
                <NavLink to={item.path} end title={item.label}>
                  <img src={item.key === "Home" ? logoUrl() : menuIcon(item.key)} alt="" />
                  <span>{item.menu ?? item.label}</span>
                </NavLink>
              ) : (
                <a href={taipyHref(item.key)} title={`${item.label} — opens in the Taipy app (not migrated yet)`}>
                  <img src={menuIcon(item.key)} alt="" />
                  <span>{item.menu ?? item.label}</span>
                  <span className="external" aria-hidden>↗</span>
                </a>
              )}
            </li>
          ))}
        </ul>
        <ThemeToggle />
      </nav>
      <main className="content">
        <img className="page-logo" src="/vimages/general/takeda.svg" alt="Takeda" />
        <Outlet />
      </main>
    </div>
  );
}
