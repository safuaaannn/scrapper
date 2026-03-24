/* ═══════════════════════════════════════════════════════════════════════════
   Size Chart Scraper — Frontend Logic
   ═══════════════════════════════════════════════════════════════════════════ */

let allResults = [];

function getStoreFromUrl(url) {
    try {
        const host = new URL(url).hostname.toLowerCase();
        if (host.includes("snitch.co.in")) return "snitch";
        if (host.includes("fashionnova.com")) return "fashionnova";
        if (host.includes("libas.in")) return "libas";
        if (host.includes("thehouseofrare.com")) return "rarerabbit";
        if (host.includes("gymshark.com")) return "gymshark";
        if (host.includes("bombayshirts.com")) return "bombayshirts";
        if (host.includes("theloom.in")) return "theloom";
        if (host.includes("outdoorvoices.com")) return "outdoorvoices";
        if (host.includes("goodamerican.com")) return "goodamerican";
        return "unknown";
    } catch {
        return "unknown";
    }
}

function getStoreDomain(url) {
    try {
        const host = new URL(url).hostname.toLowerCase();
        return host.replace(/^www\./, '');
    } catch {
        return "unknown";
    }
}

function getStoreLabel(store, url) {
    const labels = {
        snitch: "Snitch",
        fashionnova: "Fashion Nova",
        libas: "Libas",
        rarerabbit: "Rare Rabbit",
        gymshark: "Gymshark",
        bombayshirts: "Bombay Shirts",
        theloom: "The Loom",
        outdoorvoices: "Outdoor Voices",
        goodamerican: "Good American",
    };
    if (labels[store]) return labels[store];
    if (url) return getStoreDomain(url);
    return store;
}

function getMethodLabel(method) {
    const labels = {
        "inline_html_table": "Inline Table",
        "cms_page": "CMS Page",
        "metafield_popup": "Popup Modal",
        "metafield_collapsible": "Collapsible Block",
        "metaobject_rendered": "Metaobject",
        "liquid_theme_section": "Theme Section",
        "image_in_description": "Image",
        "ocr_image": "OCR (GPU)",
        "app_kiwi_sizing": "Kiwi Sizing",
        "app_esc_size_charts": "ESC Size Charts",
        "app_clean_size_charts": "Clean Size Charts",
        "app_avada_size_chart": "Avada Size Chart",
        "app_roartheme_size_chart": "Roartheme",
        "headless_rendered": "Headless Browser",
    };
    return labels[method] || method || "Unknown";
}

function getConfidenceClass(confidence) {
    if (confidence >= 0.7) return "confidence-high";
    if (confidence >= 0.4) return "confidence-medium";
    return "confidence-low";
}

async function startScraping() {
    const textarea = document.getElementById("url-input");
    const rawText = textarea.value.trim();
    if (!rawText) return;

    const urls = rawText
        .split("\n")
        .map(u => u.trim())
        .filter(u => u.length > 0 && u.startsWith("http"));

    if (urls.length === 0) return;

    // UI: disable button, show status
    const btn = document.getElementById("scrape-btn");
    btn.disabled = true;
    btn.querySelector(".btn-text").textContent = "Scraping...";

    const statusSection = document.getElementById("status-section");
    const urlStatuses = document.getElementById("url-statuses");
    statusSection.style.display = "block";
    document.getElementById("spinner").style.display = "block";
    document.getElementById("status-text").textContent = `Scraping ${urls.length} URL${urls.length > 1 ? "s" : ""}...`;

    // Show per-URL statuses
    urlStatuses.innerHTML = urls
        .map(
            (url, idx) =>
                `<div class="url-status-item" id="url-status-${idx}">
                    <span class="status-dot pending" id="url-dot-${idx}"></span>
                    <span>${truncateUrl(url)}</span>
                </div>`
        )
        .join("");

    // Mark all as loading
    urls.forEach((_, idx) => {
        document.getElementById(`url-dot-${idx}`).className = "status-dot loading";
    });

    try {
        const ocrCheckbox = document.getElementById("ocr-toggle");
        const useOcr = ocrCheckbox ? ocrCheckbox.checked : false;
        const response = await fetch("/api/scrape", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ urls, ocr: useOcr }),
        });

        const data = await response.json();

        // Update statuses
        urls.forEach((url, idx) => {
            const dot = document.getElementById(`url-dot-${idx}`);
            const hasResult = data.results?.some(r => r.url === url);
            const hasError = data.errors?.some(e => e.url === url);
            dot.className = hasResult ? "status-dot success" : hasError ? "status-dot error" : "status-dot error";
        });

        document.getElementById("spinner").style.display = "none";
        document.getElementById("status-text").textContent = "Done!";

        // Render results
        if (data.results && data.results.length > 0) {
            allResults = [...allResults, ...data.results];
            renderResults(allResults);
        }

        // Render errors
        if (data.errors && data.errors.length > 0) {
            renderErrors(data.errors);
        }
    } catch (err) {
        document.getElementById("spinner").style.display = "none";
        document.getElementById("status-text").textContent = "Request failed.";
        renderErrors([{ url: "all", error: err.message }]);
    } finally {
        btn.disabled = false;
        btn.querySelector(".btn-text").textContent = "Scrape Size Charts";
    }
}

function renderResults(results) {
    const section = document.getElementById("results-section");
    const container = document.getElementById("results-container");
    section.style.display = "block";
    container.innerHTML = "";

    results.forEach((result, rIdx) => {
        const store = getStoreFromUrl(result.url);
        const storeLabel = getStoreLabel(store, result.url);
        const methodLabel = getMethodLabel(result.detection_method);
        const confidence = result.confidence || 0;
        const confClass = getConfidenceClass(confidence);
        const chartType = result.chart_type || "";
        const category = result.category || "";
        const unit = result.unit || "";

        const div = document.createElement("div");
        div.className = "product-result glass-card";

        // Build metadata badges
        let badges = `<span class="store-tag ${store}">${storeLabel}</span>`;
        if (result.detection_method) {
            badges += `<span class="method-tag">${methodLabel}</span>`;
        }
        if (confidence > 0) {
            badges += `<span class="confidence-tag ${confClass}">${Math.round(confidence * 100)}%</span>`;
        }

        // Build metadata row
        let metaInfo = [];
        if (unit && unit !== "unknown") metaInfo.push(`Unit: ${unit}`);
        if (chartType && chartType !== "unknown") metaInfo.push(`Type: ${chartType.replace("_", " ")}`);
        if (category && category !== "general") metaInfo.push(`Category: ${category}`);

        const metaRow = metaInfo.length > 0
            ? `<div class="meta-info">${metaInfo.join(" &middot; ")}</div>`
            : "";

        // Handle image-only results
        let contentHtml = "";
        if (result.data && result.data.length > 0) {
            contentHtml = `<div class="table-wrapper">${buildTable(result.columns, result.data)}</div>`;
        } else if (result.image_urls && result.image_urls.length > 0) {
            contentHtml = `<div class="image-charts">
                <p class="image-notice">Size chart found as image(s) — no structured data extracted:</p>
                ${result.image_urls.map(url => `<img src="${escapeHtml(url)}" class="chart-image" alt="Size chart">`).join("")}
            </div>`;
        }

        div.innerHTML = `
            <div class="product-header">
                <div class="product-title">
                    ${badges}
                    ${escapeHtml(result.product || "Unknown Product")}
                </div>
                <div class="product-url">${escapeHtml(result.url)}</div>
                ${metaRow}
            </div>
            ${contentHtml}
        `;
        container.appendChild(div);
    });
}

function buildTable(columns, data) {
    // Filter out "Product" and "Unit" from display columns (already shown above)
    const displayCols = columns.filter(c => c !== "Product" && c !== "Unit");

    let html = "<table><thead><tr>";
    displayCols.forEach(col => {
        html += `<th>${escapeHtml(col)}</th>`;
    });
    html += "</tr></thead><tbody>";

    data.forEach(row => {
        html += "<tr>";
        displayCols.forEach(col => {
            const val = row[col] ?? "";
            html += `<td>${escapeHtml(String(val))}</td>`;
        });
        html += "</tr>";
    });

    html += "</tbody></table>";
    return html;
}

function renderErrors(errors) {
    const section = document.getElementById("errors-section");
    const list = document.getElementById("error-list");
    section.style.display = "block";

    errors.forEach(e => {
        const li = document.createElement("li");
        li.innerHTML = `<strong>${escapeHtml(truncateUrl(e.url))}</strong> — ${escapeHtml(e.error)}`;
        list.appendChild(li);
    });
}

function clearAll() {
    allResults = [];
    document.getElementById("url-input").value = "";
    document.getElementById("status-section").style.display = "none";
    document.getElementById("results-section").style.display = "none";
    document.getElementById("errors-section").style.display = "none";
    document.getElementById("url-statuses").innerHTML = "";
    document.getElementById("results-container").innerHTML = "";
    document.getElementById("error-list").innerHTML = "";
}

function downloadCSV() {
    if (allResults.length === 0) return;

    // Collect all unique columns across all results
    const allCols = new Set();
    allResults.forEach(r => (r.columns || []).forEach(c => allCols.add(c)));
    const cols = Array.from(allCols);

    // Build CSV
    let csv = cols.map(c => `"${c}"`).join(",") + "\n";
    allResults.forEach(r => {
        (r.data || []).forEach(row => {
            csv +=
                cols
                    .map(c => {
                        const val = row[c] ?? "";
                        return `"${String(val).replace(/"/g, '""')}"`;
                    })
                    .join(",") + "\n";
        });
    });

    // Download
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "size_charts.csv";
    a.click();
    URL.revokeObjectURL(url);
}

function downloadJSON() {
    if (allResults.length === 0) return;

    const blob = new Blob([JSON.stringify(allResults, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "size_charts.json";
    a.click();
    URL.revokeObjectURL(url);
}

function truncateUrl(url) {
    if (url.length > 80) return url.substring(0, 77) + "...";
    return url;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

// Allow Ctrl+Enter to submit
document.getElementById("url-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        startScraping();
    }
});
