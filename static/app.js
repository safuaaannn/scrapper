/* ═══════════════════════════════════════════════════════════════════════════
   Size Chart Scraper — Frontend Logic
   ═══════════════════════════════════════════════════════════════════════════ */

let allResults = [];

function getStoreFromUrl(url) {
    try {
        const host = new URL(url).hostname.toLowerCase();
        if (host.includes("snitch.com")) return "snitch";
        if (host.includes("fashionnova.com")) return "fashionnova";
        if (host.includes("libas.in")) return "libas";
        if (host.includes("thehouseofrare.com")) return "rarerabbit";
        if (host.includes("gymshark.com")) return "gymshark";
        if (host.includes("bombayshirts.com")) return "bombayshirts";
        if (host.includes("theloom.in")) return "theloom";
        if (host.includes("outdoorvoices.com")) return "outdoorvoices";
        if (host.includes("goodamerican.com")) return "goodamerican";
        // For unknown stores, extract a short name from the domain
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
    // For unknown stores, show the domain name
    if (url) return getStoreDomain(url);
    return store;
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
        const response = await fetch("/api/scrape", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ urls }),
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

        const div = document.createElement("div");
        div.className = "product-result glass-card";
        div.innerHTML = `
            <div class="product-title">
                <span class="store-tag ${store}">${storeLabel}</span>
                ${escapeHtml(result.product || "Unknown Product")}
            </div>
            <div class="product-url">${escapeHtml(result.url)}</div>
            <div class="table-wrapper">
                ${buildTable(result.columns, result.data)}
            </div>
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
    allResults.forEach(r => r.columns.forEach(c => allCols.add(c)));
    const cols = Array.from(allCols);

    // Build CSV
    let csv = cols.map(c => `"${c}"`).join(",") + "\n";
    allResults.forEach(r => {
        r.data.forEach(row => {
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
