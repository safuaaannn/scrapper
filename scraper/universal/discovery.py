"""
Discovery module — find and reveal the size chart on any product page.

Strategies (tried in order):
  1. Inline scan — check if a table is already visible
  2. Text trigger — find buttons/links with size chart keywords, click them
  3. Attribute search — find elements by class/id/data attributes
  4. Accordion/tab — find collapsible sections with size keywords
  5. Iframe detection — Kiwi Sizing and similar embedded widgets
"""

from ..helpers import _wait_for, _click_and_wait

# JS: find all clickable elements whose text matches size chart keywords
FIND_TRIGGERS_JS = """() => {
    const keywords = [
        'size chart', 'size guide', 'sizing guide', 'sizing chart',
        'measurement chart', 'view size chart', 'view size guide',
        'find your size', 'fit guide', 'size & fit', 'size and fit',
    ];
    const candidates = [];
    const seen = new Set();

    for (const el of document.querySelectorAll('button, a, span, div, label, summary, li, p, b, strong')) {
        const text = el.textContent.trim().toLowerCase();
        if (text.length > 60 || text.length < 4) continue;

        const match = keywords.some(kw => text === kw || text.includes(kw));
        if (!match) continue;

        // Avoid picking parent containers that contain the actual trigger
        if (el.children.length > 3) continue;

        // Deduplicate by text + position
        const rect = el.getBoundingClientRect();
        const key = text + '|' + Math.round(rect.top) + '|' + Math.round(rect.left);
        if (seen.has(key)) continue;
        seen.add(key);

        // Priority: button > a > summary > others
        let priority = 3;
        const tag = el.tagName.toLowerCase();
        if (tag === 'button') priority = 0;
        else if (tag === 'a') priority = 1;
        else if (tag === 'summary') priority = 1;
        else if (getComputedStyle(el).cursor === 'pointer') priority = 2;

        candidates.push({
            priority,
            tag,
            text: text.substring(0, 50),
            visible: rect.width > 0 && rect.height > 0,
            index: candidates.length,
        });
    }

    // Sort: visible first, then by priority
    candidates.sort((a, b) => {
        if (a.visible !== b.visible) return b.visible - a.visible;
        return a.priority - b.priority;
    });

    return candidates.slice(0, 8);
}"""

# JS: click the Nth trigger candidate
CLICK_TRIGGER_JS = """(idx) => {
    const keywords = [
        'size chart', 'size guide', 'sizing guide', 'sizing chart',
        'measurement chart', 'view size chart', 'view size guide',
        'find your size', 'fit guide', 'size & fit', 'size and fit',
    ];
    const candidates = [];
    const seen = new Set();

    for (const el of document.querySelectorAll('button, a, span, div, label, summary, li, p, b, strong')) {
        const text = el.textContent.trim().toLowerCase();
        if (text.length > 60 || text.length < 4) continue;
        if (!keywords.some(kw => text === kw || text.includes(kw))) continue;
        if (el.children.length > 3) continue;

        const rect = el.getBoundingClientRect();
        const key = text + '|' + Math.round(rect.top) + '|' + Math.round(rect.left);
        if (seen.has(key)) continue;
        seen.add(key);

        let priority = 3;
        const tag = el.tagName.toLowerCase();
        if (tag === 'button') priority = 0;
        else if (tag === 'a') priority = 1;
        else if (tag === 'summary') priority = 1;
        else if (getComputedStyle(el).cursor === 'pointer') priority = 2;

        candidates.push({ el, priority, visible: rect.width > 0 && rect.height > 0 });
    }

    candidates.sort((a, b) => {
        if (a.visible !== b.visible) return b.visible - a.visible;
        return a.priority - b.priority;
    });

    if (idx < candidates.length) {
        candidates[idx].el.click();
        return true;
    }
    return false;
}"""

# JS: find elements by attribute patterns (class, id, data-*)
FIND_BY_ATTRS_JS = """() => {
    const patterns = ['size-chart', 'size-guide', 'sizing', 'size_chart',
                      'fit-guide', 'kiwi-sizing', 'size_guide', 'sizeguide',
                      'sizechart', 'fit_guide', 'fitguide'];
    const candidates = [];

    for (const el of document.querySelectorAll('*')) {
        const attrs = (el.className || '') + ' ' + (el.id || '');
        for (const attr of el.attributes) {
            if (attr.name.startsWith('data-')) {
                attrs + ' ' + attr.value;
            }
        }
        const lower = attrs.toLowerCase();
        if (patterns.some(p => lower.includes(p))) {
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                candidates.push({
                    tag: el.tagName.toLowerCase(),
                    text: el.textContent.trim().substring(0, 30),
                    clickable: el.tagName === 'BUTTON' || el.tagName === 'A' ||
                               getComputedStyle(el).cursor === 'pointer',
                });
                if (candidates.length >= 5) break;
            }
        }
    }
    return candidates;
}"""

# JS: click element by attribute pattern
CLICK_BY_ATTR_JS = """() => {
    const patterns = ['size-chart', 'size-guide', 'sizing', 'size_chart',
                      'fit-guide', 'kiwi-sizing', 'size_guide', 'sizeguide',
                      'sizechart', 'fit_guide', 'fitguide'];

    for (const el of document.querySelectorAll('button, a, span, div, summary')) {
        const lower = ((el.className || '') + ' ' + (el.id || '')).toLowerCase();
        if (patterns.some(p => lower.includes(p))) {
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                el.click();
                return true;
            }
        }
    }
    return false;
}"""

# JS: find and click accordion/tab with size keywords
CLICK_ACCORDION_JS = """() => {
    // Try <details><summary> first
    for (const summary of document.querySelectorAll('summary')) {
        const text = summary.textContent.trim().toLowerCase();
        if (text.includes('size') || text.includes('fit') || text.includes('measurement')) {
            summary.click();
            return true;
        }
    }

    // Try role="tab" elements
    for (const tab of document.querySelectorAll('[role="tab"]')) {
        const text = tab.textContent.trim().toLowerCase();
        if (text.includes('size') || text.includes('fit') || text.includes('measurement')) {
            tab.click();
            return true;
        }
    }

    // Try accordion-like divs
    for (const el of document.querySelectorAll('[class*="accordion"], [class*="collapsible"], [class*="toggle"]')) {
        const text = el.textContent.trim().toLowerCase();
        if (text.length < 100 && (text.includes('size') || text.includes('fit'))) {
            const clickTarget = el.querySelector('button, a, summary, [role="button"]') || el;
            clickTarget.click();
            return true;
        }
    }

    return false;
}"""

# JS: check for sizing app iframes (Kiwi Sizing, BodyFit, etc.)
CHECK_IFRAME_JS = """() => {
    const iframes = document.querySelectorAll('iframe');
    // Only match known sizing app domains, not generic tracking/analytics iframes
    const sizingPatterns = ['kiwisizing', 'bodyfit', 'sizeguide', 'sizechart',
                           'size-guide', 'size-chart', 'fitting', 'sizeme'];
    for (const iframe of iframes) {
        const src = (iframe.src || '').toLowerCase();
        // Skip Shopify web-pixel and analytics iframes
        if (src.includes('web-pixel') || src.includes('analytics') || src.includes('tracking')) continue;
        if (sizingPatterns.some(p => src.includes(p))) {
            return {
                src: iframe.src,
                visible: iframe.offsetParent !== null,
            };
        }
    }
    return null;
}"""

# JS: try to click CM toggle
CLICK_CM_TOGGLE_JS = """() => {
    // Strategy 1: exact text match for CM/Cm/cm
    for (const el of document.querySelectorAll('button, span, div, label, a, input')) {
        const text = el.textContent.trim();
        if ((text === 'CM' || text === 'Cm' || text === 'cm') && el.children.length === 0) {
            el.click();
            return 'clicked_text';
        }
    }

    // Strategy 2: radio/checkbox inputs with cm value
    for (const input of document.querySelectorAll('input[type="radio"], input[type="checkbox"]')) {
        const val = (input.value || '').toLowerCase();
        const label = input.labels?.[0]?.textContent?.trim()?.toLowerCase() || '';
        if (val === 'cm' || label === 'cm') {
            input.click();
            return 'clicked_input';
        }
    }

    // Strategy 3: look for toggle/switch with cm
    for (const el of document.querySelectorAll('[class*="toggle"], [class*="switch"], [class*="tab"]')) {
        const text = el.textContent.trim().toLowerCase();
        if (text === 'cm' || text === 'centimeters') {
            el.click();
            return 'clicked_toggle';
        }
    }

    return null;
}"""

# JS: check if new content appeared (modal, drawer, expanded section)
CHECK_NEW_CONTENT_JS = """() => {
    // Check for modals/drawers that just appeared
    const containers = document.querySelectorAll(
        '[role="dialog"], [class*="modal"], [class*="drawer"], [class*="popup"], ' +
        '[class*="overlay"], [class*="panel"], [class*="sidebar"], dialog[open]'
    );
    for (const c of containers) {
        if (c.offsetParent !== null || getComputedStyle(c).display !== 'none') {
            // Found a visible overlay — check if it has tables or measurement content
            const tables = c.querySelectorAll('table');
            const text = c.textContent.toLowerCase();
            if (tables.length > 0 || text.includes('size') || text.includes('measurement')) {
                return 'modal';
            }
        }
    }

    // Check for tables on the page
    const tables = document.querySelectorAll('table');
    for (const t of tables) {
        if (t.offsetParent !== null && t.rows.length > 1) {
            return 'table';
        }
    }

    return null;
}"""


async def discover_size_chart(page) -> str:
    """
    Try to find and reveal the size chart on the page.
    Returns a status string: 'found_inline', 'found_clicked', 'found_accordion',
    'found_iframe', 'found_attr', or 'not_found'.
    """

    # Strategy 1: Check for inline tables already visible
    inline = await page.evaluate("""() => {
        for (const table of document.querySelectorAll('table')) {
            if (table.offsetParent === null) continue;
            if (table.rows.length < 2) continue;
            const text = table.textContent.toLowerCase();
            if (text.includes('size') || text.includes('chest') || text.includes('waist') ||
                text.includes('bust') || text.includes('hip') || text.includes('shoulder') ||
                text.includes('length')) {
                return true;
            }
        }
        return false;
    }""")
    if inline:
        return "found_inline"

    # Strategy 2: Text-based trigger search — find and click
    triggers = await page.evaluate(FIND_TRIGGERS_JS)
    if triggers:
        for i in range(min(len(triggers), 3)):
            await page.evaluate(CLICK_TRIGGER_JS, i)
            await page.wait_for_timeout(800)

            # Check if content appeared
            content = await _wait_for(page, CHECK_NEW_CONTENT_JS, timeout=5000, interval=400)
            if content:
                return "found_clicked"

    # Strategy 2b: Playwright native click — handles frameworks where JS click() doesn't work
    # Also uses a broader content check (includes text-based measurement detection)
    BROAD_CONTENT_CHECK_JS = """() => {
        // Check for modals/drawers with tables
        const containers = document.querySelectorAll(
            '[role="dialog"], [class*="modal"], [class*="drawer"], [class*="popup"], ' +
            '[class*="overlay"], [class*="panel"], [class*="sidebar"], dialog[open]'
        );
        for (const c of containers) {
            if (c.offsetParent !== null || getComputedStyle(c).display !== 'none') {
                const text = c.textContent.toLowerCase();
                const tables = c.querySelectorAll('table');
                const measureKws = ['chest', 'waist', 'bust', 'hip', 'shoulder', 'sleeve', 'inseam', 'neck'];
                const hits = measureKws.filter(kw => text.includes(kw)).length;
                if (tables.length > 0 || hits >= 3) {
                    return 'modal';
                }
            }
        }
        // Check for tables
        for (const t of document.querySelectorAll('table')) {
            if (t.offsetParent !== null && t.rows.length > 1) return 'table';
        }
        return null;
    }"""

    if triggers:
        # Prefer <a> and <span> triggers (more likely to be actual clickable links)
        sorted_triggers = sorted(
            [t for t in triggers if t.get("visible")],
            key=lambda t: {"A": 0, "SPAN": 1, "BUTTON": 2}.get(t.get("tag", ""), 3)
        )
        trigger_texts = [t.get("text", "") for t in sorted_triggers]
        for text in trigger_texts[:3]:
            try:
                locator = page.get_by_text(text, exact=True).first
                if await locator.is_visible():
                    await locator.click(timeout=3000)
                    await page.wait_for_timeout(1500)
                    content = await _wait_for(page, BROAD_CONTENT_CHECK_JS, timeout=5000, interval=400)
                    if content:
                        return "found_clicked"
            except Exception:
                continue

    # Strategy 3: Attribute-based search
    attr_click = await page.evaluate(CLICK_BY_ATTR_JS)
    if attr_click:
        await page.wait_for_timeout(800)
        content = await _wait_for(page, CHECK_NEW_CONTENT_JS, timeout=5000, interval=400)
        if content:
            return "found_attr"

    # Strategy 4: Accordion/tab detection
    acc_click = await page.evaluate(CLICK_ACCORDION_JS)
    if acc_click:
        await page.wait_for_timeout(800)
        content = await _wait_for(page, CHECK_NEW_CONTENT_JS, timeout=4000, interval=400)
        if content:
            return "found_accordion"

    # Strategy 5: Iframe detection
    iframe_info = await page.evaluate(CHECK_IFRAME_JS)
    if iframe_info:
        return "found_iframe"

    # Last resort: check if any table appeared on the page at all after all clicking
    has_table = await page.evaluate("""() => {
        for (const table of document.querySelectorAll('table')) {
            if (table.offsetParent !== null && table.rows.length > 1) return true;
        }
        return false;
    }""")
    if has_table:
        return "found_inline"

    return "not_found"


async def try_cm_toggle(page) -> bool:
    """Attempt to click a CM toggle. Returns True if clicked."""
    result = await page.evaluate(CLICK_CM_TOGGLE_JS)
    if result:
        await page.wait_for_timeout(600)
        return True
    return False
