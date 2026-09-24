#!/usr/bin/env python3
"""Plain text from an EDGAR filing's HTML, with every committee-table mark named by its row and column.

    python3 converter.py filing.htm > filing.txt
    python3 converter.py --no-marks filing.htm      # the plain text alone

A proxy statement's committee-membership table states each seat with a tick image, a glyph or a
short code in an otherwise empty cell. Flattened to text, the marks vanish or arrive with nothing
joining them to a committee, and a model asked which committees a director sits on fills the blanks
from memory. This converter keeps the document's block structure (one line per block element and
table cell, so adjacent cells never fuse) and, in every table that looks like a membership grid,
rewrites each mark in its cell as

    [mark <what the mark is> | row <the director> | column <the committee>]

where "what the mark is" is the glyph, the word, or the image's file stem. A legend's image beside
its word is named too (`[image <stem>]`), so a reader that sees only text can join the two.

The rules, in short. A table builds a grid only if some cell is a mark on its own: a glyph, a
membership word or code, or an image at a glyph's size (a stated size past 30px is a portrait or
logo; under 3px, or a file named like a spacer, a spacer; no stated size means the image is judged
on repetition). Cells are placed at the columns they occupy, colspan and rowspan resolved, within
a budget (500 rows, 50,000 slots, spans of at most 64x256) beyond which the table is left alone. An
image is a mark where it repeats in the table, or, appearing once, where it stands in a column of
repeating marks; an image in four of five cells of the marked rows holds them open and is not a
mark. The rows above the first marked one are headers: a header row holds words in at least two
cells and nothing else, a column takes the deepest label covering it and keeps its banner where two
columns end in the same word, and a header row met again below the marks (naming the columns that
carry marks) renames them for the rows that follow. A row is named by its own first worded cell,
before a group heading held down from above. A mark spanning several columns is named only where
they agree, and a mark with no column is left as it is: a mark attached to the wrong committee is
worse than one attached to none.

This is a port of the authors' production converter (TypeScript, on cheerio); on the benchmark's
27 filings it emits the same committee marks. It needs beautifulsoup4, and parses with html5lib
(browser-grade, like cheerio's parse5) when that is installed, else the standard library parser.
"""
import re
import sys
import warnings

from bs4 import BeautifulSoup, NavigableString, Comment, Doctype, ProcessingInstruction, Declaration, CData

try:  # a filing that declares XML namespaces is still HTML to a browser, and to this converter
    from bs4 import XMLParsedAsHTMLWarning

    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except ImportError:
    pass

SKIP_TAGS = {"script", "style", "head", "noscript", "meta", "link", "title"}
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "caption", "center", "dd", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header",
    "hr", "li", "main", "nav", "ol", "p", "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead",
    "tr", "ul",
}
MARK_GLYPHS = re.compile(r"^[\s•✓✔✕✖✗✘●○■□◆◇×xX]+$")
MEMBERSHIP_WORDS = {"chair", "chairman", "chairwoman", "chairperson", "co-chair", "vice chair", "member", "c", "m"}
MAX_COLSPAN, MAX_ROWSPAN = 64, 256
MARK_MAX_PX, MARK_MIN_PX = 30, 3
SPACER_STEM = re.compile(r"spacer|blank|pixel|transparent|clear|1x1|shim", re.I)
MAX_GRID_ROWS, MAX_GRID_SLOTS = 500, 50_000
MAX_LABEL_CHARS, MAX_MARK_NAME_CHARS, MAX_GLYPH_CHARS, MAX_LEGEND_CHARS = 80, 60, 12, 40
MAX_LEGEND_WORDS, MAX_LEGEND_ROWS = 3, 3
SAFE_CHARS = {"<": "‹", ">": "›", "|": "/", "[": "(", "]": ")"}
NON_TEXT = (Comment, Doctype, ProcessingInstruction, Declaration, CData)


def is_text(node):
    return isinstance(node, NavigableString) and not isinstance(node, NON_TEXT)


def tag_name(node):
    return node.name.lower() if getattr(node, "name", None) else ""


# ── text ────────────────────────────────────────────────────────────────────
def collect_text(node):
    if is_text(node):
        return str(node)
    if isinstance(node, NavigableString):
        return ""
    name = tag_name(node)
    if name in SKIP_TAGS:
        return ""
    inner = "".join(collect_text(c) for c in node.children)
    return f"\n{inner}\n" if name in BLOCK_TAGS else inner


def own_text(node):
    if is_text(node):
        return str(node)
    if isinstance(node, NavigableString):
        return ""
    name = tag_name(node)
    if name == "br":
        return " "
    if name == "table" or name in SKIP_TAGS:
        return ""
    inner = "".join(own_text(c) for c in node.children)
    return f" {inner} " if name in BLOCK_TAGS else inner


def cell_text(cell):
    return re.sub(r"\s+", " ", own_text(cell).replace("​", " ").replace("\xa0", " ")).strip()


def own_images(node, found=None):
    found = [] if found is None else found
    for child in node.children:
        if len(found) >= 2:
            break
        if isinstance(child, NavigableString):
            continue
        name = tag_name(child)
        if name == "img":
            found.append(child)
        elif name != "table":
            own_images(child, found)
    return found


def span_of(cell, attribute, maximum):
    try:
        stated = int(str(cell.get(attribute, "1")).strip().split()[0])
    except (ValueError, IndexError):
        return 1
    if stated < 1:
        return 1
    return None if stated > maximum else stated


def stated_size(image):
    style = image.get("style") or ""

    def px(value):
        m = re.match(r"^\s*([\d.]+)\s*(px)?\s*$", value or "", re.I)
        if not m:
            return None
        try:
            v = float(m.group(1))
        except ValueError:
            return None
        return v if v > 0 else None

    def declared(name):
        m = re.search(r"(?:^|[;\s])" + name + r":\s*([^;]*)", style, re.I)
        return m.group(1) if m else None

    sw, sh = declared("width"), declared("height")
    if sw is not None or sh is not None:
        styled = [v for v in (px(sw), px(sh)) if v is not None]
        return max(styled) if styled else None
    attributed = [v for v in (px(_attr(image, "width")), px(_attr(image, "height"))) if v is not None]
    return max(attributed) if attributed else None


def _attr(node, name):
    v = node.get(name)
    if isinstance(v, list):
        v = " ".join(v)
    return v


def stem_of(image):
    source = _attr(image, "src") or _attr(image, "alt") or ""
    if re.match(r"^\s*data:", source, re.I):
        return "inline-image"
    return re.sub(r"\.[a-z0-9]+$", "", source.split("/")[-1], flags=re.I).strip()


def read_cell(cell):
    text = cell_text(cell)
    if text != "":
        return {"text": text, "mark": bool(MARK_GLYPHS.match(text)) or text.lower() in MEMBERSHIP_WORDS, "image": None}
    images = own_images(cell)
    if not images or len(images) > 1:
        return {"text": text, "mark": False, "image": None}
    image = images[0]
    if SPACER_STEM.search(stem_of(image)):
        return {"text": text, "mark": False, "image": image}
    size = stated_size(image)
    return {"text": text, "mark": size is None or (MARK_MIN_PX <= size <= MARK_MAX_PX), "image": image}


def mark_label(facts):
    if facts["image"] is not None:
        return stem_of(facts["image"])[:MAX_MARK_NAME_CHARS] or "image"
    return facts["text"][:MAX_GLYPH_CHARS] if facts["text"] else None


def is_label_text(text):
    return len(text) >= 2 and re.search(r"[a-z]", text, re.I) is not None and text.lower() not in MEMBERSHIP_WORDS


def safe(value):
    value = re.sub(r"[<>|\[\]]", lambda m: SAFE_CHARS.get(m.group(0), " "), value)
    return re.sub(r"\s+", " ", value).strip()[:MAX_LABEL_CHARS]


# ── the grid ────────────────────────────────────────────────────────────────
class Record:
    __slots__ = ("cell", "facts", "start", "colspan", "rowspan", "first_row")

    def __init__(self, cell, facts, start, colspan, rowspan, first_row):
        self.cell, self.facts, self.start, self.colspan, self.rowspan, self.first_row = cell, facts, start, colspan, rowspan, first_row


def table_rows(table):
    rows = []
    for section in table.find_all(["thead", "tbody", "tfoot", "tr"], recursive=False):
        if tag_name(section) == "tr":
            rows.append(section)
        else:
            rows.extend(section.find_all("tr", recursive=False))
    return rows


def annotate_grid_marks(soup):
    for table in soup.find_all("table"):
        rows = table_rows(table)
        if len(rows) < 2 or len(rows) > MAX_GRID_ROWS:
            continue
        cells_by_row = [row.find_all(["td", "th"], recursive=False) for row in rows]
        facts_of = {}

        def facts(cell):
            k = id(cell)
            if k not in facts_of:
                facts_of[k] = read_cell(cell)
            return facts_of[k]

        if not any(facts(c)["mark"] for cells in cells_by_row for c in cells):
            continue

        grid, carried, slots, abandoned = [], {}, 0, False
        for r, cells in enumerate(cells_by_row):
            row = {}
            for column, held in list(carried.items()):
                row[column] = held["record"]
                slots += 1
                held["rows"] -= 1
                if held["rows"] <= 0:
                    del carried[column]
            column = 0
            for cell in cells:
                while column in row:
                    column += 1
                colspan = span_of(cell, "colspan", MAX_COLSPAN)
                rowspan = span_of(cell, "rowspan", MAX_ROWSPAN)
                if colspan is None or rowspan is None:
                    abandoned = True
                    break
                record = Record(cell, facts(cell), column, colspan, rowspan, r)
                for k in range(colspan):
                    row[column + k] = record
                if rowspan > 1:
                    for k in range(colspan):
                        carried[column + k] = {"record": record, "rows": rowspan - 1}
                column += colspan
                slots += colspan
            if abandoned or slots > MAX_GRID_SLOTS:
                abandoned = True
                break
            grid.append(row)
        if abandoned:
            continue

        def is_origin(record, r, column):
            return record.first_row == r and record.start == column

        stems, placed, cells_in_marked_rows = {}, [], 0
        for r, row in enumerate(grid):
            own = [rec for column, rec in row.items() if is_origin(rec, r, column)]
            if any(rec.facts["mark"] for rec in own):
                cells_in_marked_rows += len(own)
            for column, rec in row.items():
                if not is_origin(rec, r, column) or not rec.facts["mark"] or rec.facts["image"] is None:
                    continue
                stem = stem_of(rec.facts["image"]).lower()
                stems[stem] = stems.get(stem, 0) + 1
                placed.append((column, stem))

        def repeats(stem):
            return stems.get(stem, 0) > 1

        def fills_the_grid(stem):
            return cells_in_marked_rows >= 4 and stems.get(stem, 0) >= 0.8 * cells_in_marked_rows

        marked_columns = {column for column, stem in placed if repeats(stem) and not fills_the_grid(stem)}

        def is_mark_alone(rec):
            if not rec.facts["mark"]:
                return False
            if rec.facts["image"] is None:
                return True
            stem = stem_of(rec.facts["image"]).lower()
            return repeats(stem) and not fills_the_grid(stem)

        def is_mark(rec, column):
            if is_mark_alone(rec):
                return True
            if not rec.facts["mark"] or rec.facts["image"] is None:
                return False
            return not fills_the_grid(stem_of(rec.facts["image"]).lower()) and column in marked_columns

        first_marked = next((r for r, row in enumerate(grid) if any(is_origin(rec, r, c) and is_mark_alone(rec) for c, rec in row.items())), -1)
        if first_marked < 0:
            continue
        columns_with_marks = {c for r, row in enumerate(grid) for c, rec in row.items() if is_origin(rec, r, c) and is_mark_alone(rec)}

        def is_header_row(row, r):
            labels = 0
            for column, rec in row.items():
                if not is_origin(rec, r, column) or rec.facts["text"] == "":
                    continue
                if is_mark(rec, column):
                    return False
                if not is_label_text(rec.facts["text"]):
                    return False
                labels += 1
            return labels >= 2

        stacks = {}

        def read_header_row(row):
            for column, rec in row.items():
                if rec.facts["mark"] or not is_label_text(rec.facts["text"]):
                    continue
                stacks.setdefault(column, []).append(rec.facts["text"])

        def column_labels():
            deepest, holders = {}, {}
            for column, stack in stacks.items():
                label = stack[-1]
                deepest[column] = label
                holders[label] = holders.get(label, 0) + 1
            labels = {}
            for column, label in deepest.items():
                banner = next((t for t in reversed(stacks[column]) if t != label), None)
                labels[column] = f"{banner} {label}" if holders.get(label, 0) > 1 and banner else label
            return labels

        for r in range(first_marked):
            if is_header_row(grid[r], r):
                read_header_row(grid[r])
        column_label = column_labels()
        if not column_label:
            continue

        def row_label_of(r):
            own_spanning_word = held_word = any_text = ""
            for column in sorted(grid[r]):
                rec = grid[r][column]
                if is_mark(rec, column) or rec.facts["text"] == "":
                    continue
                own = rec.first_row == r
                word = is_label_text(rec.facts["text"])
                if own and word and rec.rowspan == 1:
                    return rec.facts["text"]
                if own and word and not own_spanning_word:
                    own_spanning_word = rec.facts["text"]
                if not own and word and not held_word:
                    held_word = rec.facts["text"]
                if not any_text:
                    any_text = rec.facts["text"]
            return own_spanning_word or held_word or any_text

        pending = []
        for r in range(first_marked, len(grid)):
            row = grid[r]
            row_has_marks = any(is_origin(rec, r, c) and is_mark(rec, c) for c, rec in row.items())
            if not row_has_marks:
                if r > first_marked and is_header_row(row, r):
                    named = sum(1 for c, rec in row.items() if is_origin(rec, r, c) and c in columns_with_marks and is_label_text(rec.facts["text"]))
                    if named >= min(2, len(columns_with_marks)):
                        read_header_row(row)
                        column_label = column_labels()
                continue
            for column in sorted(row):
                rec = row[column]
                if not is_origin(rec, r, column) or not is_mark(rec, column):
                    continue
                label = mark_label(rec.facts)
                if not label:
                    continue
                parts = [f"mark {safe(label)}"]
                row_labels = []
                for k in range(rec.rowspan):
                    if r + k >= len(grid) or grid[r + k].get(column) is not rec:
                        break
                    text = row_label_of(r + k)
                    if text and text not in row_labels:
                        row_labels.append(text)
                if row_labels:
                    parts.append(f"row {safe('; '.join(row_labels))}")
                covered = {column_label[column + k] for k in range(rec.colspan) if column_label.get(column + k)}
                if len(covered) != 1:
                    continue
                parts.append(f"column {safe(next(iter(covered)))}")
                pending.append((rec.cell, " [" + " | ".join(parts) + "]"))
        for cell, text in pending:
            cell.append(NavigableString(text))


def annotate_legend_images(soup):
    rows_of = {}
    for cell in soup.find_all(["td", "th"]):
        text = cell_text(cell)
        if text == "" or len(text) > MAX_LEGEND_CHARS or not re.search(r"[a-z]", text, re.I):
            continue
        if len(text.split(" ")) > MAX_LEGEND_WORDS:
            continue
        images = own_images(cell)
        if not images or len(images) > 1:
            continue
        stem = stem_of(images[0])
        if not stem or SPACER_STEM.search(stem):
            continue
        table = cell.find_parent("table")
        if table is not None:
            k = id(table)
            if k not in rows_of:
                rows_of[k] = len(table.find_all("tr"))
            if rows_of[k] > MAX_LEGEND_ROWS:
                continue
        cell.append(NavigableString(f" [image {safe(stem[:MAX_MARK_NAME_CHARS])}]"))


def parser_name():
    try:
        import html5lib  # noqa: F401
        return "html5lib"
    except ImportError:
        return "html.parser"


def edgar_html_to_text_blocks(html, annotate_marks=True):
    processed = html
    if "xmlns:ix=" in html or "<ix:" in html:
        processed = re.sub(r"<ix:header[\s\S]*?</ix:header>", "", processed, flags=re.I)
        processed = re.sub(r"</?ix:[a-zA-Z][^>]*>", "", processed, flags=re.I)
    soup = BeautifulSoup(processed, parser_name())
    if annotate_marks:
        annotate_grid_marks(soup)
        annotate_legend_images(soup)
    root = soup.body or soup
    raw = collect_text(root).replace("\xa0", " ").replace("\ufeff", "")
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit("usage: converter.py [--no-marks] filing.htm")
    with open(args[0], "r", encoding="utf-8", errors="replace") as fh:
        print(edgar_html_to_text_blocks(fh.read(), annotate_marks="--no-marks" not in sys.argv))
