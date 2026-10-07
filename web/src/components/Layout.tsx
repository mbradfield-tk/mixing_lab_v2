import { NavLink, Outlet } from "react-router-dom";
import { NAV, logoUrl, menuIcon, taipyHref } from "../nav";

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
                <NavLink to={item.path} end>
                  <img src={item.key === "Home" ? logoUrl() : menuIcon(item.key)} alt="" />
                  {item.label}
                </NavLink>
              ) : (
                <a href={taipyHref(item.key)} title="Opens in the Taipy app (not migrated yet)">
                  <img src={menuIcon(item.key)} alt="" />
                  {item.label}
                  <span className="external" aria-hidden>↗</span>
                </a>
              )}
            </li>
          ))}
        </ul>
      </nav>
      <main className="content">
        <img className="page-logo" src="/vimages/general/takeda.svg" alt="Takeda" />
        <Outlet />
      </main>
    </div>
  );
}
