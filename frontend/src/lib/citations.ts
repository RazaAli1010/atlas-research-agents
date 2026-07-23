// Pure report/citation helpers (F12). Kept side-effect-free so they can be unit-tested
// without rendering. The ReportViewer runs `splitReportBody` then `linkifyCitations` over
// the body before handing it to react-markdown.

// Matches a bare citation marker "[n]" that is NOT immediately followed by "(" — the
// negative lookahead leaves an already-formed link "[n](url)" (and "[title](url)", whose
// text is non-numeric anyway) untouched. Global + multiline via the /g flag.
const CITATION_RE = /\[(\d+)\](?!\()/g

/**
 * Rewrite bare "[n]" markers into markdown links "[n](#source-n)" so react-markdown parses
 * them as anchors we can style as superscripts pointing at the SourceList. Numbers in prose
 * ("item 1") and existing links are left alone.
 */
export function linkifyCitations(md: string): string {
  return md.replace(CITATION_RE, '[$1](#source-$1)')
}

// Line-anchored "## Sources" heading (allow trailing spaces); `m` so ^ matches line starts.
const SOURCES_HEADING_RE = /^##\s+Sources\s*$/gm

/**
 * Split off the trailing "## Sources" section of the report so the structured SourceList
 * renders it instead of the raw markdown list (avoids a duplicated source list). Splits at
 * the LAST "## Sources" heading. When no such heading exists, returns the whole string.
 */
export function splitReportBody(md: string): { body: string; hadSources: boolean } {
  let lastIndex = -1
  for (const match of md.matchAll(SOURCES_HEADING_RE)) {
    lastIndex = match.index
  }
  if (lastIndex < 0) return { body: md, hadSources: false }
  return { body: md.slice(0, lastIndex).trimEnd(), hadSources: true }
}
