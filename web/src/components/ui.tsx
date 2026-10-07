import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { menuIcon, navItem, taipyHref } from "../nav";

export function Card({ title, children }: { title?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {title && <h2>{title}</h2>}
      {children}
    </section>
  );
}

export function MenuIcon({ pageKey, size = "1.1em" }: { pageKey: string; size?: string }) {
  return <img className="menu-icon" src={menuIcon(pageKey)} alt="" style={{ height: size }} />;
}

/** Link to a page: in-app when it has been migrated, otherwise to the Taipy app. */
export function PageLink({ pageKey, children }: { pageKey: string; children?: ReactNode }) {
  const item = navItem(pageKey);
  const label = children ?? item.label;
  return item.path ? <Link to={item.path}>{label}</Link> : <a href={taipyHref(pageKey)}>{label}</a>;
}

export function PageTitle({ pageKey, children }: { pageKey: string; children: ReactNode }) {
  return (
    <h1 className="page-title">
      <MenuIcon pageKey={pageKey} size="72px" />
      {children}
    </h1>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  return <p className="error-note">⚠️ {message}</p>;
}
