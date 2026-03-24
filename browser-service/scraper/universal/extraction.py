"""
Extraction module — extract table data from the page after the size chart is revealed.

Extractors (tried in order):
  1. HTML <table> extraction with scoring
  2. CSS grid/flexbox div-based table extraction
  3. Iframe table extraction (Kiwi Sizing, etc.)
  4. Text-based extraction (fallback)
"""

from ..config import MEASUREMENT_KEYWORDS, NEGATIVE_KEYWORDS, SIZE_LABELS

# JS: extract ALL visible tables from page with metadata
EXTRACT_ALL_TABLES_JS = """() => {
    const results = [];
    const allTables = document.querySelectorAll('table');

    for (let tIdx = 0; tIdx < allTables.length; tIdx++) {
        const table = allTables[tIdx];
        if (table.offsetParent === null && getComputedStyle(table).display === 'none') continue;
        if (table.rows.length < 2) continue;

        const rows = [];
        for (const tr of table.rows) {
            const cells = [];
            for (const td of tr.cells) {
                cells.push(td.textContent.trim());
            }
            rows.push(cells);
        }

        // Check if the table is inside a modal/dialog
        let inModal = false;
        let parent = table.parentElement;
        while (parent) {
            const cls = (parent.className || '').toLowerCase();
            const role = parent.getAttribute('role') || '';
            if (role === 'dialog' || cls.includes('modal') || cls.includes('drawer') ||
                cls.includes('popup') || cls.includes('overlay') || parent.tagName === 'DIALOG') {
                inModal = true;
                break;
            }
            parent = parent.parentElement;
        }

        results.push({
            rows: rows,
            numRows: rows.length,
            numCols: rows[0] ? rows[0].length : 0,
            inModal: inModal,
            index: tIdx,
        });
    }

    return results;
}"""

# JS: extract div-based grid tables
EXTRACT_DIV_TABLES_JS = """() => {
    const results = [];

    // Look for grid/flex containers that might be pseudo-tables
    const containers = document.querySelectorAll(
        '[class*="size-chart"] *, [class*="size-guide"] *, [class*="sizing"] *, ' +
        '[role="dialog"] *, [class*="modal"] *, [class*="drawer"] *'
    );

    // Find containers with display:grid or display:flex that have regular children
    const candidates = new Set();
    for (const el of containers) {
        const style = getComputedStyle(el);
        if (style.display === 'grid' || (style.display === 'flex' && style.flexWrap === 'wrap')) {
            candidates.add(el);
        }
    }

    for (const container of candidates) {
        const children = Array.from(container.children);
        if (children.length < 4) continue;

        // Try to detect grid dimensions
        const firstTop = children[0].getBoundingClientRect().top;
        let colsInFirstRow = 0;
        for (const child of children) {
            if (Math.abs(child.getBoundingClientRect().top - firstTop) < 5) {
                colsInFirstRow++;
            } else {
                break;
            }
        }

        if (colsInFirstRow < 2) continue;
        if (children.length % colsInFirstRow !== 0) continue;

        const numRows = children.length / colsInFirstRow;
        if (numRows < 2) continue;

        const rows = [];
        for (let r = 0; r < numRows; r++) {
            const row = [];
            for (let c = 0; c < colsInFirstRow; c++) {
                row.push(children[r * colsInFirstRow + c].textContent.trim());
            }
            rows.push(row);
        }

        results.push({
            rows: rows,
            numRows: numRows,
            numCols: colsInFirstRow,
            inModal: true,
            index: results.length,
        });
    }

    return results;
}"""

# JS: extract list-based tables (ul/li grids used by some stores like sheetalbatra.com)
EXTRACT_LIST_TABLES_JS = """() => {
    const results = [];

    // Strategy 1: ul.size-table pattern — each <ul> is a row, <li> are cells
    const sizeTableUls = document.querySelectorAll('ul.size-table, ul.main-size');
    if (sizeTableUls.length >= 2) {
        const rows = [];
        for (const ul of sizeTableUls) {
            const cells = [];
            for (const li of ul.querySelectorAll(':scope > li')) {
                cells.push(li.textContent.trim());
            }
            if (cells.length >= 2) rows.push(cells);
        }
        if (rows.length >= 2) {
            // Check if inside modal
            let inModal = false;
            let parent = sizeTableUls[0].parentElement;
            while (parent) {
                const cls = (parent.className || '').toLowerCase();
                const role = parent.getAttribute('role') || '';
                if (role === 'dialog' || cls.includes('modal') || cls.includes('drawer') ||
                    cls.includes('popup') || parent.tagName === 'DIALOG' ||
                    parent.tagName.includes('-MODAL')) {
                    inModal = true; break;
                }
                parent = parent.parentElement;
            }
            results.push({ rows, numRows: rows.length, numCols: rows[0].length, inModal, index: 0 });
        }
    }

    // Strategy 2: Generic dl/dt/dd pattern — definition lists used as size charts
    if (results.length === 0) {
        const dls = document.querySelectorAll('dl');
        for (const dl of dls) {
            const text = dl.textContent.toLowerCase();
            if (!text.includes('size') && !text.includes('bust') && !text.includes('chest')) continue;
            const dts = dl.querySelectorAll('dt');
            const dds = dl.querySelectorAll('dd');
            if (dts.length >= 2 && dts.length === dds.length) {
                const rows = [];
                for (let i = 0; i < dts.length; i++) {
                    rows.push([dts[i].textContent.trim(), dds[i].textContent.trim()]);
                }
                results.push({ rows, numRows: rows.length, numCols: 2, inModal: false, index: 0 });
            }
        }
    }

    // Strategy 3: Any visible container with class containing "size" that has
    // multiple child <ul> lists with equal-length <li> children
    if (results.length === 0) {
        const containers = document.querySelectorAll(
            '[class*="size-chart"], [class*="sizechart"], [class*="size-guide"], ' +
            '[id*="size-chart"], x-modal[open], [class*="chart"]'
        );
        for (const container of containers) {
            if (container.offsetParent === null && getComputedStyle(container).display === 'none') continue;
            const uls = container.querySelectorAll('ul');
            if (uls.length < 2) continue;

            // Group ULs that have the same number of LIs (likely rows of the same table)
            const byCount = {};
            for (const ul of uls) {
                const lis = ul.querySelectorAll(':scope > li');
                if (lis.length < 2) continue;
                const key = lis.length;
                if (!byCount[key]) byCount[key] = [];
                byCount[key].push(ul);
            }

            for (const [count, ulGroup] of Object.entries(byCount)) {
                if (ulGroup.length < 2 || parseInt(count) < 2) continue;
                const rows = [];
                for (const ul of ulGroup) {
                    const cells = Array.from(ul.querySelectorAll(':scope > li')).map(li => li.textContent.trim());
                    rows.push(cells);
                }
                if (rows.length >= 2) {
                    results.push({ rows, numRows: rows.length, numCols: parseInt(count), inModal: true, index: 0 });
                    break;
                }
            }
            if (results.length > 0) break;
        }
    }

    return results;
}"""

# JS: extract table from iframe
EXTRACT_IFRAME_TABLE_JS = """() => {
    const iframes = document.querySelectorAll('iframe');
    for (const iframe of iframes) {
        try {
            const doc = iframe.contentDocument || iframe.contentWindow?.document;
            if (!doc) continue;

            const tables = doc.querySelectorAll('table');
            for (const table of tables) {
                if (table.rows.length < 2) continue;
                const rows = [];
                for (const tr of table.rows) {
                    const cells = [];
                    for (const td of tr.cells) cells.push(td.textContent.trim());
                    rows.push(cells);
                }
                return { rows, numRows: rows.length, numCols: rows[0].length, inModal: false };
            }
        } catch(e) {
            // Cross-origin iframe — can't access
            continue;
        }
    }
    return null;
}"""

# JS: extract text from the modal/visible content for text-based parsing
EXTRACT_TEXT_JS = """() => {
    // Try modal/dialog first
    const modals = document.querySelectorAll(
        '[role="dialog"], [class*="modal"]:not([style*="display: none"]), ' +
        '[class*="drawer"]:not([style*="display: none"]), dialog[open]'
    );
    for (const m of modals) {
        if (m.offsetParent !== null || getComputedStyle(m).display !== 'none') {
            return m.innerText;
        }
    }
    // Fallback: whole page
    return document.body.innerText;
}"""


def _skip_title_rows(rows: list) -> list:
    """
    Skip title/caption rows at the start of a table.
    Title rows are single-cell rows like ['Garment Size Chart'] that span the full width.
    Also skips toggle indicator rows like ['cmin', ...] or ['incm', ...].
    Returns rows starting from the actual header row.
    """
    # Toggle indicators that appear as merged first-row artifacts
    toggle_indicators = {"cmin", "incm", "cm/in", "in/cm", "cmincm", "incmin"}

    for i, row in enumerate(rows):
        non_empty = [c for c in row if c.strip()]

        # Skip toggle indicator rows
        if non_empty and non_empty[0].strip().lower().replace(" ", "") in toggle_indicators:
            continue

        # A real header row has 2+ non-empty cells
        if len(non_empty) >= 2:
            return rows[i:]
        # Single non-empty cell with no digits — likely a title
        if len(non_empty) == 1 and not any(c.isdigit() for c in non_empty[0]):
            continue
        # If we hit a row with numbers or multiple cells, stop skipping
        break
    return rows


def score_table(table_info: dict) -> float:
    """
    Score a candidate table to determine if it's a size chart.
    Higher score = more likely to be the measurement table.
    """
    rows = _skip_title_rows(table_info["rows"])
    if not rows or len(rows) < 2:
        return -100

    headers = [h.lower().strip() for h in rows[0]]
    num_cols = len(headers)
    num_rows = len(rows)
    score = 0.0

    # Check for "Size" column
    has_size_col = any("size" in h for h in headers)
    if has_size_col:
        score += 15

    # Check first column of data rows for known size labels
    size_label_matches = 0
    for row in rows[1:]:
        if row and row[0].strip().upper() in SIZE_LABELS:
            size_label_matches += 1
    if size_label_matches > 0:
        score += min(size_label_matches * 2, 10)

    # Check for measurement keywords in headers
    measurement_hits = 0
    for h in headers:
        for kw in MEASUREMENT_KEYWORDS:
            if kw in h:
                measurement_hits += 1
                break
    score += measurement_hits * 5

    # Check if first column contains measurement keywords (transposed table)
    first_col_measurements = 0
    for row in rows[1:]:
        if row:
            cell_lower = row[0].strip().lower()
            if cell_lower in MEASUREMENT_KEYWORDS or any(kw in cell_lower for kw in MEASUREMENT_KEYWORDS):
                first_col_measurements += 1
    if first_col_measurements >= 2:
        score += first_col_measurements * 5

    # Check for numeric data in body cells
    numeric_count = 0
    total_cells = 0
    for row in rows[1:]:
        for cell in row[1:]:
            total_cells += 1
            cell_clean = cell.strip().replace(".", "").replace("-", "").replace(" ", "")
            if cell_clean and cell_clean.replace(",", "").isdigit():
                numeric_count += 1
            # Also count ranges like "31 - 33"
            elif any(c.isdigit() for c in cell):
                numeric_count += 0.5

    if total_cells > 0:
        numeric_ratio = numeric_count / total_cells
        score += numeric_ratio * 10

    # Reasonable dimensions bonus
    if 3 <= num_rows <= 20 and 3 <= num_cols <= 15:
        score += 5

    # Penalty for negative keywords (shipping, returns, etc.)
    all_text = " ".join(" ".join(row) for row in rows).lower()
    for neg in NEGATIVE_KEYWORDS:
        if neg in all_text:
            score -= 20

    # Bonus for being inside a modal (more likely to be the size chart)
    if table_info.get("inModal"):
        score += 8

    # Bonus for more columns (richer data)
    score += min(num_cols, 8)

    return score


def pick_best_table(tables: list) -> dict | None:
    """Score all candidate tables and return the best one."""
    if not tables:
        return None

    scored = [(score_table(t), t) for t in tables]
    scored.sort(key=lambda x: x[0], reverse=True)

    best_score, best_table = scored[0]
    if best_score < 5:
        return None

    return best_table


def parse_table_data(table_info: dict) -> tuple:
    """
    Parse a raw table into (headers, data_rows, orientation).
    Detects if the table is normal (rows=sizes) or transposed (cols=sizes).
    Returns (headers: list[str], rows: list[dict], orientation: str)
    """
    rows = _skip_title_rows(table_info["rows"])
    if not rows or len(rows) < 2:
        return [], [], "unknown"

    header_row = rows[0]
    data_rows = rows[1:]

    # Check orientation: are sizes in the header row (normal) or first column (transposed)?
    header_size_count = sum(1 for h in header_row if h.strip().upper() in SIZE_LABELS)
    first_col_size_count = sum(1 for row in data_rows if row and row[0].strip().upper() in SIZE_LABELS)

    # Normal: headers contain measurement names, first data column is sizes
    if first_col_size_count >= len(data_rows) * 0.5:
        # Normal table: rows are sizes
        headers = [h.strip() for h in header_row]
        parsed_rows = []
        for row in data_rows:
            if not any(c.strip() for c in row):
                continue
            d = {}
            for j, header in enumerate(headers):
                if j < len(row):
                    d[header] = row[j].strip()
            parsed_rows.append(d)
        return headers, parsed_rows, "normal"

    # Transposed: headers are sizes (first cell is empty or "Size")
    if header_size_count >= 2:
        sizes = [h.strip() for h in header_row[1:] if h.strip()]
        parsed_rows = []
        for i, size in enumerate(sizes):
            d = {"Size": size}
            for data_row in data_rows:
                if not data_row or not data_row[0].strip():
                    continue
                measure_name = data_row[0].strip()
                if i + 1 < len(data_row):
                    d[measure_name] = data_row[i + 1].strip()
            parsed_rows.append(d)
        headers = ["Size"] + [row[0].strip() for row in data_rows if row and row[0].strip()]
        return headers, parsed_rows, "transposed"

    # Fallback: treat as normal table
    headers = [h.strip() for h in header_row]
    parsed_rows = []
    for row in data_rows:
        if not any(c.strip() for c in row):
            continue
        d = {}
        for j, header in enumerate(headers):
            if j < len(row):
                d[header] = row[j].strip()
        parsed_rows.append(d)
    return headers, parsed_rows, "normal"


def parse_text_as_table(text: str) -> tuple:
    """
    Try to parse plain text as a size chart table.
    Handles tab-separated lines and vertical label-values structure.
    Returns (headers: list[str], rows: list[dict]) or ([], []) on failure.
    """
    lines = text.split("\n")

    # Strategy 1: Look for tab-separated header + data rows
    for i, line in enumerate(lines):
        if "\t" not in line:
            continue
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if len(parts) < 3:
            continue

        # Check if this looks like a header row (has "Size" or measurement keywords)
        header_text = " ".join(parts).lower()
        if "size" in header_text or any(kw in header_text for kw in MEASUREMENT_KEYWORDS):
            headers = parts
            data_rows = []
            for j in range(i + 1, len(lines)):
                row_line = lines[j].strip()
                if not row_line:
                    continue
                if "\t" not in row_line:
                    # End of table data
                    if data_rows:
                        break
                    continue
                row_parts = [p.strip() for p in row_line.split("\t") if p.strip()]
                if len(row_parts) >= 2:
                    row = {}
                    for k, header in enumerate(headers):
                        if k < len(row_parts):
                            row[header] = row_parts[k]
                    data_rows.append(row)
                else:
                    if data_rows:
                        break

            if data_rows:
                return headers, data_rows

    # Strategy 2: Vertical/grid structure — labels on individual lines followed by values
    # Handles div-grid layouts where headers and values are each on their own line
    # e.g.: Size\nChest\nSleeve\nNeck\n S\n36"-38"\n33"\n15"-15.5"\n ...
    measurement_kws = {
        "chest", "bust", "waist", "hip", "hips", "shoulder", "shoulders",
        "sleeve", "length", "inseam", "thigh", "neck", "size",
        "across shoulder", "body length", "arm", "bicep", "rise", "collar",
    }

    # Clean lines: strip whitespace and non-breaking spaces
    cleaned_lines = []
    for line in lines:
        cleaned = line.replace('\xa0', ' ').strip()
        if cleaned:
            cleaned_lines.append(cleaned)

    # Find a sequence of measurement keyword lines (the header row of a grid)
    best_headers = []
    best_header_start = -1
    for i, line in enumerate(cleaned_lines):
        if line.lower() in measurement_kws:
            # Look ahead to see how many consecutive keyword lines there are
            header_group = [line]
            for j in range(i + 1, min(i + 15, len(cleaned_lines))):
                next_line = cleaned_lines[j]
                if next_line.lower() in measurement_kws:
                    header_group.append(next_line)
                else:
                    break
            if len(header_group) >= 3 and len(header_group) > len(best_headers):
                best_headers = header_group
                best_header_start = i

    if best_headers and best_header_start >= 0:
        num_cols = len(best_headers)
        data_start = best_header_start + num_cols
        remaining = cleaned_lines[data_start:]

        # Collect data values in chunks of num_cols
        sections = {h.capitalize(): [] for h in best_headers}
        header_keys = [h.capitalize() for h in best_headers]
        idx = 0
        while idx + num_cols <= len(remaining):
            chunk = remaining[idx:idx + num_cols]
            # Verify first value looks like a size or number
            first = chunk[0]
            if first.upper() in SIZE_LABELS or any(c.isdigit() for c in first):
                for k, key in enumerate(header_keys):
                    sections[key].append(chunk[k])
                idx += num_cols
            else:
                break

        if "Size" in sections and len(sections) >= 2 and len(sections["Size"]) > 0:
            sizes = sections.pop("Size")
            headers = ["Size"] + list(sections.keys())
            data_rows = []
            for i, size in enumerate(sizes):
                row = {"Size": size}
                for label, values in sections.items():
                    if i < len(values):
                        row[label] = values[i]
                data_rows.append(row)
            return headers, data_rows

    # Strategy 2b: Classic vertical — single label then N values
    sections = {}
    current_label = None

    for line in cleaned_lines:
        stripped = line.strip()
        if stripped.lower() in measurement_kws:
            current_label = stripped.capitalize()
            sections[current_label] = []
            continue

        if current_label and current_label in sections:
            if any(c.isdigit() for c in stripped) or stripped.upper() in SIZE_LABELS:
                sections[current_label].append(stripped)
            else:
                if stripped.lower() in measurement_kws:
                    current_label = stripped.capitalize()
                    sections[current_label] = []
                else:
                    current_label = None

    if "Size" in sections and len(sections) >= 2 and len(sections["Size"]) > 0:
        sizes = sections.pop("Size")
        headers = ["Size"] + list(sections.keys())
        data_rows = []
        for i, size in enumerate(sizes):
            row = {"Size": size}
            for label, values in sections.items():
                if i < len(values):
                    row[label] = values[i]
            data_rows.append(row)
        return headers, data_rows

    return [], []


async def extract_tables(page, discovery_result: str) -> list:
    """
    Extract all candidate tables from the page.
    Returns a list of table_info dicts with 'rows', 'numRows', 'numCols', 'inModal'.
    """
    all_tables = []

    # Extract HTML tables
    html_tables = await page.evaluate(EXTRACT_ALL_TABLES_JS)
    if html_tables:
        all_tables.extend(html_tables)

    # Extract div-based tables
    div_tables = await page.evaluate(EXTRACT_DIV_TABLES_JS)
    if div_tables:
        all_tables.extend(div_tables)

    # Extract list-based tables (ul/li grids)
    list_tables = await page.evaluate(EXTRACT_LIST_TABLES_JS)
    if list_tables:
        all_tables.extend(list_tables)

    # Try iframe extraction if discovery found an iframe
    if discovery_result == "found_iframe":
        iframe_table = await page.evaluate(EXTRACT_IFRAME_TABLE_JS)
        if iframe_table:
            all_tables.append(iframe_table)

    return all_tables


async def extract_text_content(page) -> str:
    """Extract text content from modal or page for text-based parsing."""
    return await page.evaluate(EXTRACT_TEXT_JS)
