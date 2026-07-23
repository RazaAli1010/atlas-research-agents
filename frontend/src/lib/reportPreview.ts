// Pure helper: a short plain-text teaser of the final report for the run page's "Report
// ready" card. The full, formatted report lives on its own page (ReportViewer) — this only
// needs to hint at the content, so we strip the trailing ## Sources block and the markdown
// noise (headings, emphasis, bare [n] citation markers) and join the first few prose lines.
import { splitReportBody } from './citations'

export function reportPreview(reportMd: string, maxChars = 320): string {
  const { body } = splitReportBody(reportMd)
  const text = body
    .split('\n')
    .map((line) =>
      line
        .replace(/^#{1,6}\s+/, '') // heading markers
        .replace(/\[(\d+)\](?!\()/g, '') // bare citation markers
        .replace(/[*_`>#]/g, '') // emphasis / code / quote / stray hashes
        .trim(),
    )
    .filter((line) => line.length > 0)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim()

  if (text.length <= maxChars) return text
  return text.slice(0, maxChars).replace(/\s+\S*$/, '') + '…'
}
