import { useQuery } from "@tanstack/react-query";
import "katex/dist/katex.min.css";
import { useEffect, useMemo, useState } from "react";
import { api, unwrap, type Schemas } from "../api/client";
import { Markdown, TeX } from "../components/Markdown";
import { ErrorNote, PageTitle } from "../components/ui";

type Entry = Schemas["EquationEntry"];
type Section = Schemas["EquationSection"];

const entryText = (e: Entry) =>
  [e.title, e.equation ?? "", e.body, ...e.sources, ...e.used_in].join(" ").toLowerCase();

/** Sections whose title matches keep all entries; otherwise only matching entries are kept. */
export function filterSections(sections: Section[], query: string): Section[] {
  const q = query.trim().toLowerCase();
  if (!q) return sections;
  return sections
    .map((s) => ({
      ...s,
      entries: s.title.toLowerCase().includes(q) ? s.entries : s.entries.filter((e) => entryText(e).includes(q)),
    }))
    .filter((s) => s.entries.length > 0);
}

const scrollTo = (id: string) => {
  document.getElementById(id)?.scrollIntoView({ block: "start" });
  history.replaceState(null, "", `#${id}`);
};

function EntryCard({ entry, open, onToggle }: { entry: Entry; open: boolean; onToggle: (o: boolean) => void }) {
  const hasDetails = entry.body !== "" || entry.sources.length > 0;
  return (
    <article className="eq-entry" id={entry.id}>
      <header className="eq-entry-head">
        <h3>{entry.title}</h3>
        {entry.used_in.length > 0 && (
          <ul className="eq-used-in" aria-label="Used in">
            {entry.used_in.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        )}
      </header>
      {entry.equation && <TeX math={entry.equation} />}
      {!entry.equation && entry.body && <Markdown>{entry.body}</Markdown>}
      {entry.equation && hasDetails && (
        <details className="eq-details" open={open} onToggle={(e) => onToggle(e.currentTarget.open)}>
          <summary>Variables, notes &amp; sources</summary>
          {entry.body && <Markdown>{entry.body}</Markdown>}
          <Sources sources={entry.sources} />
        </details>
      )}
      {!entry.equation && <Sources sources={entry.sources} />}
    </article>
  );
}

function Sources({ sources }: { sources: string[] }) {
  if (sources.length === 0) return null;
  return (
    <div className="eq-sources">
      <span className="eq-sources-label">Sources</span>
      <ul>
        {sources.map((s) => (
          <li key={s}>
            <Markdown inline>{s}</Markdown>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function EquationsReference() {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const equations = useQuery({
    queryKey: ["equations"],
    queryFn: async () => unwrap(await api.GET("/api/v1/equations")),
    staleTime: Infinity,
  });

  useEffect(() => {
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (equations.isSuccess && id) document.getElementById(id)?.scrollIntoView({ block: "start" });
  }, [equations.isSuccess]);

  const all: Section[] = equations.data?.sections ?? [];
  const total = all.reduce((n, s) => n + s.entries.length, 0);
  const q = query.trim().toLowerCase();
  const sections = useMemo(() => filterSections(all, q), [all, q]);
  const shown = sections.reduce((n, s) => n + s.entries.length, 0);
  const sectionNumber = new Map(all.map((s, i) => [s.id, i + 1]));
  const isOpen = (id: string) => expanded[id] ?? q !== "";
  const setAll = (open: boolean) =>
    setExpanded(Object.fromEntries(sections.flatMap((s) => s.entries.map((e) => [e.id, open]))));

  return (
    <>
      <PageTitle pageKey="Equations_Reference">Equations Reference</PageTitle>
      <p className="centered muted">
        Every correlation used in Mixing Lab, with its variables, validity notes and literature source.
      </p>
      <div className="eq-toolbar">
        <input
          className="search"
          type="search"
          placeholder="Search equations, symbols or sources (e.g. Reynolds, kLa, \mu, Zwietering)"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setExpanded({});
          }}
          aria-label="Search equations"
        />
        {equations.isSuccess && (
          <span className="muted">{q ? `${shown} of ${total} entries` : `${total} entries`}</span>
        )}
        <span className="eq-toolbar-actions">
          <button type="button" onClick={() => setAll(true)}>
            Expand all
          </button>
          <button type="button" onClick={() => setAll(false)}>
            Collapse all
          </button>
        </span>
      </div>
      {equations.isPending && <p>Loading equations…</p>}
      {equations.isError && <ErrorNote error={equations.error} />}
      {equations.isSuccess && sections.length === 0 && <p>No entry matches “{query}”.</p>}
      <div className="eq-layout">
        {sections.length > 0 && (
          <nav className="eq-toc" aria-label="Contents">
            <ol>
              {sections.map((s) => (
                <li key={s.id}>
                  <a href={`#${s.id}`} onClick={(e) => (e.preventDefault(), scrollTo(s.id))}>
                    {s.title}
                  </a>
                  <ol>
                    {s.entries.map((e) => (
                      <li key={e.id}>
                        <a href={`#${e.id}`} onClick={(ev) => (ev.preventDefault(), scrollTo(e.id))}>
                          {e.title}
                        </a>
                      </li>
                    ))}
                  </ol>
                </li>
              ))}
            </ol>
          </nav>
        )}
        <div className="eq-content">
          {sections.map((s, i) => (
            <section key={s.id} className="eq-section" id={s.id}>
              <h2>
                <span className="eq-section-num">{sectionNumber.get(s.id)}</span>
                {s.title}
              </h2>
              {s.intro && !q && <Markdown>{s.intro}</Markdown>}
              {s.entries.map((e) => (
                <EntryCard
                  key={e.id}
                  entry={e}
                  open={isOpen(e.id)}
                  onToggle={(open) => setExpanded((x) => (x[e.id] === open ? x : { ...x, [e.id]: open }))}
                />
              ))}
              {i < sections.length - 1 && <hr className="eq-divider" />}
            </section>
          ))}
        </div>
      </div>
    </>
  );
}
