// Builds a guide's .docx from its .md, so the two never drift.
// Needs the npm package docx@9: npm install docx, then for example
// node scripts/guides/build-guide-docx.js docs/guides/global-risk-contribute-guide.md docs/guides/global-risk-contribute-guide.docx
// node scripts/guides/build-guide-docx.js docs/guides/share-data-with-global-risk-guide.md docs/guides/share-data-with-global-risk-guide.docx "Share data with Global Risk"
// The optional third argument is the footer label; it defaults to the title.
// Understands the Markdown the guides use: #, ## and ### headings, paragraphs, **bold**, *italic*,
// `code`, links, > notes, - and 1. lists (nested by indentation), fenced code and pipe tables.
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType,
  ShadingType, BorderStyle, LevelFormat, AlignmentType, Footer, PageNumber,
} = require("docx");

const [, , source, target, footerLabel] = process.argv;
const lines = fs.readFileSync(source, "utf8").split(/\r?\n/);
const FONT = "Leelawadee UI";
const CODE = "Consolas";
const PAGE_WIDTH = 9026; // A4 minus 1" margins, in DXA

// Links keep their text only; a bare <https://…> keeps the address.
const plain = (text) => text
  .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
  .replace(/<(https?:[^>\s]+)>/g, "$1");

// Inline **bold**, *italic* and `code`.
const runs = (text, base = {}) => {
  const out = [];
  const source = plain(text);
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  let match;
  while ((match = pattern.exec(source))) {
    if (match.index > last) out.push(new TextRun({ text: source.slice(last, match.index), ...base }));
    const token = match[0];
    if (token.startsWith("**")) out.push(new TextRun({ text: token.slice(2, -2), bold: true, ...base }));
    else if (token.startsWith("`")) out.push(new TextRun({ text: token.slice(1, -1), font: CODE, size: 19, color: "1F4E79", ...base }));
    else out.push(new TextRun({ text: token.slice(1, -1), italics: true, ...base }));
    last = match.index + token.length;
  }
  if (last < source.length) out.push(new TextRun({ text: source.slice(last), ...base }));
  return out;
};

const border = { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" };
const cellBorders = { top: border, bottom: border, left: border, right: border };

// Column widths follow the longest cell in each column, within limits, and sum to the page.
const columnWidths = (rows) => {
  const cols = rows[0].length;
  const weights = Array.from({ length: cols }, (_, c) => Math.min(
    70, Math.max(10, ...rows.map((cells) => plain(cells[c] || "").replace(/[*`]/g, "").length)),
  ));
  const total = weights.reduce((a, b) => a + b, 0);
  const widths = weights.map((w) => Math.floor((PAGE_WIDTH * w) / total));
  widths[cols - 1] += PAGE_WIDTH - widths.reduce((a, b) => a + b, 0);
  return widths;
};

const table = (rows) => {
  const widths = columnWidths(rows);
  return new Table({
    width: { size: PAGE_WIDTH, type: WidthType.DXA },
    columnWidths: widths,
    rows: rows.map((cells, r) => new TableRow({
      tableHeader: r === 0,
      children: cells.map((cell, c) => new TableCell({
        width: { size: widths[c], type: WidthType.DXA },
        borders: cellBorders,
        shading: r === 0 ? { type: ShadingType.CLEAR, color: "auto", fill: "DCE6F1" } : undefined,
        margins: { top: 60, bottom: 60, left: 100, right: 100 },
        children: [new Paragraph({ children: runs(cell, { size: 19, bold: r === 0 || undefined }) })],
      })),
    })),
  });
};

const indentOf = (line) => line.length - line.trimStart().length;
const LIST_ITEM = /^(\s*)(- |\d+\. )/;

const children = [];
let title = "";
let paragraph = [];
let numberedList = 0;
const flush = () => {
  if (paragraph.length) children.push(new Paragraph({ children: runs(paragraph.join(" ")), spacing: { after: 120 } }));
  paragraph = [];
};

for (let i = 0; i < lines.length; i += 1) {
  const line = lines[i];
  const text = line.trim();
  if (text.startsWith("```")) {
    flush();
    const indent = indentOf(line);
    const code = [];
    for (i += 1; i < lines.length && !lines[i].trim().startsWith("```"); i += 1) code.push(lines[i].slice(Math.min(indent, indentOf(lines[i]))));
    const left = indent > 0 ? 740 : 200;
    code.forEach((row, n) => children.push(new Paragraph({
      children: [new TextRun({ text: row || " ", font: CODE, size: 18 })],
      shading: { type: ShadingType.CLEAR, color: "auto", fill: "F2F2F2" },
      indent: { left, right: 200 },
      spacing: { after: n === code.length - 1 ? 160 : 0 },
    })));
  } else if (text.startsWith("|")) {
    flush();
    const rows = [];
    for (; i < lines.length && lines[i].trim().startsWith("|"); i += 1) {
      const cells = lines[i].trim().split("|").slice(1, -1).map((c) => c.trim());
      if (!cells.every((c) => /^:?-+:?$/.test(c))) rows.push(cells);
    }
    i -= 1;
    children.push(table(rows), new Paragraph({ children: [], spacing: { after: 80 } }));
  } else if (line.startsWith("# ")) {
    flush();
    title = title || line.slice(2);
    children.push(new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun(line.slice(2))] }));
  } else if (line.startsWith("## ") || line.startsWith("### ")) {
    flush();
    const level3 = line.startsWith("### ");
    children.push(new Paragraph({
      heading: level3 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_1,
      children: [new TextRun(line.slice(level3 ? 4 : 3))],
    }));
  } else if (text.startsWith(">")) {
    flush();
    const quote = [];
    for (; i < lines.length && lines[i].trim().startsWith(">"); i += 1) quote.push(lines[i].trim().replace(/^>\s?/, ""));
    i -= 1;
    children.push(new Paragraph({
      children: runs(quote.join(" ")),
      shading: { type: ShadingType.CLEAR, color: "auto", fill: "FFF4E5" },
      border: { left: { style: BorderStyle.SINGLE, size: 18, color: "E8A33D", space: 8 } },
      indent: { left: 200 },
      spacing: { before: 80, after: 160 },
    }));
  } else if (LIST_ITEM.test(line)) {
    flush();
    const [, spaces, marker] = line.match(LIST_ITEM);
    const indent = spaces.length;
    const level = indent >= 2 ? 1 : 0;
    let body = line.slice(indent + marker.length);
    // Continuation lines are indented deeper than the marker and are not a new block.
    while (
      i + 1 < lines.length && lines[i + 1].trim()
      && indentOf(lines[i + 1]) > indent
      && !LIST_ITEM.test(lines[i + 1]) && !/^(```|\||>)/.test(lines[i + 1].trim())
    ) body += ` ${lines[++i].trim()}`;
    if (marker === "- ") {
      children.push(new Paragraph({ numbering: { reference: "bullets", level }, children: runs(body), spacing: { after: 60 } }));
    } else {
      // A list that starts at 1 restarts its numbering; later items continue it.
      if (marker === "1. " && level === 0) numberedList += 1;
      children.push(new Paragraph({ numbering: { reference: "steps", level, instance: numberedList }, children: runs(body), spacing: { after: 60 } }));
    }
  } else if (!text) {
    flush();
  } else {
    paragraph.push(text);
  }
}
flush();

const grey = { size: 16, color: "808080" };
const doc = new Document({
  creator: "ADPC GRP team",
  title,
  styles: {
    default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", run: { font: FONT, size: 40, bold: true, color: "1F3864" }, paragraph: { spacing: { after: 200 } } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: FONT, size: 28, bold: true, color: "1F4E79" }, paragraph: { spacing: { before: 280, after: 120 }, outlineLevel: 0, keepNext: true } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: FONT, size: 24, bold: true, color: "2E75B6" }, paragraph: { spacing: { before: 220, after: 100 }, outlineLevel: 1, keepNext: true } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [
        { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } },
        { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1000, hanging: 270 } } } },
      ] },
      { reference: "steps", levels: [
        { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 300 } } } },
        { level: 1, format: LevelFormat.LOWER_LETTER, text: "%2.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1000, hanging: 300 } } } },
      ] },
    ],
  },
  sections: [{
    properties: { page: { margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: `${footerLabel || title} · page `, ...grey }), new TextRun({ children: [PageNumber.CURRENT], ...grey })] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then((buffer) => fs.writeFileSync(target, buffer));
