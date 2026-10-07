import { useQuery } from "@tanstack/react-query";
import "katex/dist/katex.min.css";
import { useMemo, useState } from "react";
import { api, unwrap, type Schemas } from "../api/client";
import { Markdown, TeX } from "../components/Markdown";
import { Card, ErrorNote, PageTitle } from "../components/ui";

type EquationItem = Schemas["EquationItem"];
type EquationSection = Schemas["EquationSection"];

function Item({ item }: { item: EquationItem }) {
  if (item.type === "header") {
    const text = <Markdown inline>{item.text ?? ""}</Markdown>;
    return (item.level ?? 3) <= 3 ? <h3>{text}</h3> : <h4>{text}</h4>;
  }
  if (item.type === "latex") {
    return <TeX math={item.latex ?? ""} />;
  }
  return <Markdown>{item.text ?? ""}</Markdown>;
}

const sectionText = (s: EquationSection) =>
  [s.title, ...s.items.map((i) => `${i.text ?? ""} ${i.latex ?? ""}`)].join(" ").toLowerCase();

export function EquationsReference() {
  const [query, setQuery] = useState("");
  const equations = useQuery({
    queryKey: ["equations"],
    queryFn: async () => unwrap(await api.GET("/api/v1/equations")),
    staleTime: Infinity,
  });

  const sections = useMemo(() => {
    const all = equations.data?.sections ?? [];
    const q = query.trim().toLowerCase();
    return q ? all.filter((s) => sectionText(s).includes(q)) : all;
  }, [equations.data, query]);

  return (
    <>
      <PageTitle pageKey="Equations_Reference">Equations Reference</PageTitle>
      <p>
        Reference correlations and equations used throughout Mixing Lab, with symbols, units and
        literature references. Expand a section for details.
      </p>
      <input
        className="search"
        type="search"
        placeholder="Search equations (e.g. Reynolds, kLa, Zwietering)"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Search equations"
      />
      {equations.isPending && <p>Loading equations…</p>}
      {equations.isError && <ErrorNote error={equations.error} />}
      {equations.isSuccess && sections.length === 0 && <p>No section matches “{query}”.</p>}
      {sections.map((section) => (
        <Card key={section.title}>
          <details open={query.trim() !== ""}>; search matches titles, text and the
        LaTeX source (e.g. <code>\mu</code>)
            <summary>{section.title}</summary>
            {section.items.map((item, i) => (
              <Item key={i} item={item} />
            ))}
          </details>
        </Card>
      ))}
    </>
  );
}
