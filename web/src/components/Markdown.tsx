import katex from "katex";
import { Fragment } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

// Keep remark-math's class names through the sanitiser so rehype-katex can find them.
const schema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    code: [
      ...(defaultSchema.attributes?.code ?? []),
      ["className", "language-math", "math-inline", "math-display"],
    ],
  },
};

const KATEX_OPTIONS = { throwOnError: false, strict: "ignore" } as const;

/** GitHub-flavoured Markdown with $inline$ / $$display$$ LaTeX; raw HTML is sanitised
 * before KaTeX renders, so only KaTeX's own markup is trusted. */
export function Markdown({ children, inline = false }: { children: string; inline?: boolean }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeRaw, [rehypeSanitize, schema], [rehypeKatex, KATEX_OPTIONS]]}
      components={inline ? { p: Fragment } : undefined}
    >
      {children}
    </ReactMarkdown>
  );
}

/** One LaTeX expression rendered by KaTeX (display style unless ``inline``). */
export function TeX({ math, inline = false }: { math: string; inline?: boolean }) {
  const html = katex.renderToString(math, { ...KATEX_OPTIONS, displayMode: !inline });
  return inline ? (
    <span dangerouslySetInnerHTML={{ __html: html }} />
  ) : (
    <div className="tex-display" dangerouslySetInnerHTML={{ __html: html }} />
  );
}
