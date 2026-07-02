#!/usr/bin/env python3
"""Render a Markdown doc to a clean, print-styled PDF via headless Chrome.

No third-party deps. Handles the Markdown subset used in this repo: #/##/### headings,
**bold**, *italic*, `code`, - bullets, [ ]/[x] checkboxes, --- rules, [text](url) links,
tables, and paragraphs. Falls back to leaving an .html next to the .pdf if Chrome is absent.

USAGE: python3 code/md_to_pdf.py report/visit_agenda.md
"""
import sys, re, html, subprocess, tempfile, os
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

def inline(s):
    s = html.escape(s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s

BLOCK_START = re.compile(r"^\s*(#{1,4}\s|[-*]\s|---+\s*$|\|)")

def convert(md):
    out, lines, i = [], md.splitlines(), 0
    in_ul = False
    def close_ul():
        nonlocal in_ul
        if in_ul: out.append("</ul>"); in_ul = False
    def continuation(j):
        """True if line j continues the current paragraph/list item (soft wrap)."""
        return j < len(lines) and lines[j].strip() and not BLOCK_START.match(lines[j])
    while i < len(lines):
        ln = lines[i]
        if re.match(r"^\s*\|.*\|\s*$", ln) and i+1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i+1]):
            close_ul()
            header = [c.strip() for c in ln.strip().strip("|").split("|")]
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in header) + "</tr></thead><tbody>")
            i += 2
            while i < len(lines) and re.match(r"^\s*\|.*\|\s*$", lines[i]):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
                i += 1
            out.append("</tbody></table>")
            continue
        if not ln.strip():
            close_ul(); i += 1; continue
        m = re.match(r"^(#{1,4})\s+(.*)", ln)
        if m:
            close_ul(); lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>"); i += 1; continue
        if re.match(r"^\s*---+\s*$", ln):
            close_ul(); out.append("<hr>"); i += 1; continue
        # list item (checkbox or bullet) — absorb soft-wrapped continuation lines
        m = re.match(r"^\s*[-*]\s+\[([ xX])\]\s+(.*)", ln)
        if m:
            if not in_ul: out.append('<ul class="checks">'); in_ul = True
            box = "☑" if m.group(1).lower() == "x" else "☐"
            text = m.group(2)
            i += 1
            while continuation(i): text += " " + lines[i].strip(); i += 1
            out.append(f'<li><span class="box">{box}</span> {inline(text)}</li>'); continue
        m = re.match(r"^\s*[-*]\s+(.*)", ln)
        if m:
            if not in_ul: out.append("<ul>"); in_ul = True
            text = m.group(1)
            i += 1
            while continuation(i): text += " " + lines[i].strip(); i += 1
            out.append(f"<li>{inline(text)}</li>"); continue
        # paragraph — join soft-wrapped lines
        close_ul()
        text = ln.strip()
        i += 1
        while continuation(i): text += " " + lines[i].strip(); i += 1
        out.append(f"<p>{inline(text)}</p>")
    close_ul()
    return "\n".join(out)

CSS = """
@page { size: letter; margin: 0.6in 0.7in; }
* { box-sizing: border-box; }
body { font: 11pt/1.45 -apple-system, 'Helvetica Neue', Arial, sans-serif; color: #1a1a1a; max-width: 7.1in; }
h1 { font-size: 19pt; margin: 0 0 2px; }
h2 { font-size: 13pt; margin: 16px 0 4px; padding-bottom: 3px; border-bottom: 1.5px solid #2b6cb0; color: #1a3e63; }
h3 { font-size: 11.5pt; margin: 11px 0 3px; }
p { margin: 5px 0; }
ul { margin: 5px 0 8px; padding-left: 20px; }
li { margin: 2.5px 0; }
ul.checks { list-style: none; padding-left: 2px; }
ul.checks .box { display: inline-block; width: 1.1em; }
hr { border: none; border-top: 1px solid #ccc; margin: 12px 0; }
a { color: #2b6cb0; text-decoration: none; }
code { background: #f0f2f5; padding: 1px 4px; border-radius: 3px; font-size: 9.5pt; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 9.5pt; }
th, td { border: 1px solid #d4d8de; padding: 4px 7px; text-align: left; vertical-align: top; }
th { background: #eef2f7; }
strong { color: #111; }
h2 { break-after: avoid; } h3 { break-after: avoid; }
"""

def main():
    if len(sys.argv) < 2:
        print("usage: md_to_pdf.py <file.md> [out.pdf]"); sys.exit(1)
    src = Path(sys.argv[1])
    pdf = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".pdf")
    body = convert(src.read_text())
    page = f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"
    html_path = src.with_suffix(".print.html")
    html_path.write_text(page)
    if not os.path.exists(CHROME):
        print(f"Chrome not found; wrote {html_path} — open it and Print → Save as PDF."); return
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", html_path.resolve().as_uri()],
                   check=True, capture_output=True)
    html_path.unlink(missing_ok=True)
    print(f"Wrote {pdf} ({pdf.stat().st_size//1024} KB)")

if __name__ == "__main__":
    main()
