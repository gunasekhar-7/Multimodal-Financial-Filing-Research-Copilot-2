document.addEventListener("DOMContentLoaded", () => {
    checkHealth();
    loadCompanies();
});

async function checkHealth() {
    const elem = document.getElementById("system-status");
    const modeBadge = document.getElementById("data-mode-badge");
    try {
        const resp = await fetch("/health");
        if (!resp.ok) throw new Error("Health check failed");
        const data = await resp.json();
        elem.className = "bg-emerald-950 text-emerald-400 border border-emerald-800/50 px-2.5 py-1 rounded-full";
        elem.textContent = `Online · ${data.companies_count} companies · ${data.xbrl_facts_count} facts`;
        const isDemo = data.data_mode === "demo";
        modeBadge.textContent = isDemo ? "Demo data · synthetic" : "SEC facts · text unavailable";
        modeBadge.className = isDemo
            ? "bg-amber-950 text-amber-300 border border-amber-800/50 px-2.5 py-1 rounded-full font-medium"
            : "bg-blue-950 text-blue-300 border border-blue-800/50 px-2.5 py-1 rounded-full font-medium";
    } catch (err) {
        elem.className = "bg-rose-950 text-rose-400 border border-rose-800/50 px-2.5 py-1 rounded-full";
        elem.textContent = "API offline";
    }
}

async function loadCompanies() {
    const select = document.getElementById("company-select");
    try {
        const resp = await fetch("/api/companies");
        if (!resp.ok) throw new Error("Company list unavailable");
        const companies = await resp.json();
        select.replaceChildren();
        companies.forEach(company => {
            const option = document.createElement("option");
            option.value = company.ticker;
            option.textContent = `${company.ticker} - ${company.name}`;
            select.appendChild(option);
        });
    } catch (err) {
        showError(`Could not load companies: ${err.message}. Refresh the page or check that the API is running.`);
    }
}

function setPreset(ticker, question) {
    document.getElementById("company-select").value = ticker;
    document.getElementById("question-input").value = question;
}

function showError(message) {
    const container = document.getElementById("error-state");
    container.textContent = message;
    container.classList.remove("hidden");
}

async function submitQuery() {
    const button = document.getElementById("btn-submit");
    const ticker = document.getElementById("company-select").value;
    const question = document.getElementById("question-input").value.trim();
    const error = document.getElementById("error-state");
    error.classList.add("hidden");
    if (question.length < 3) {
        showError("Enter a research question of at least three characters.");
        document.getElementById("question-input").focus();
        return;
    }

    document.getElementById("empty-state").classList.add("hidden");
    document.getElementById("report-container").classList.add("hidden");
    document.getElementById("loading-state").classList.remove("hidden");
    button.disabled = true;
    button.classList.add("opacity-60", "cursor-wait");

    try {
        const resp = await fetch("/api/query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question, ticker })
        });
        const result = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            const suffix = resp.status === 429 ? " Please wait before trying again." : " Check the query and server configuration.";
            throw new Error(`${result.detail || "Query failed"}.${suffix}`);
        }
        renderReport(result);
    } catch (err) {
        document.getElementById("empty-state").classList.remove("hidden");
        showError(`Unable to generate report: ${err.message}`);
    } finally {
        button.disabled = false;
        button.classList.remove("opacity-60", "cursor-wait");
        document.getElementById("loading-state").classList.add("hidden");
    }
}

function addText(parent, tag, text, className) {
    const element = document.createElement(tag);
    element.textContent = text ?? "";
    if (className) element.className = className;
    parent.appendChild(element);
    return element;
}

function renderReport(report) {
    document.getElementById("report-title").textContent = `Research Report: ${(report.target_tickers || []).join(", ")}`;
    document.getElementById("generated-timestamp").textContent = `Generated: ${new Date(report.generated_at).toLocaleString()}`;
    document.getElementById("executive-summary").textContent = report.executive_summary;

    const provenance = document.getElementById("report-provenance");
    provenance.textContent = report.data_mode === "demo"
        ? "DEMO CORPUS · SYNTHETIC VALUES · NOT SEC-REPORTED"
        : "SEC EDGAR STRUCTURED FACTS · FILING-TEXT SEARCH UNAVAILABLE";
    provenance.className = report.data_mode === "demo"
        ? "rounded-lg border border-amber-700/60 bg-amber-950/40 p-3 text-xs font-semibold text-amber-200"
        : "rounded-lg border border-blue-700/60 bg-blue-950/40 p-3 text-xs font-semibold text-blue-200";

    // Render Multimodal Visual Artifacts & Charts
    const artifactsCard = document.getElementById("visual-artifacts-card");
    const artifactsContainer = document.getElementById("visual-artifacts-container");
    if (artifactsContainer) {
        artifactsContainer.replaceChildren();
        if (report.visual_artifacts && report.visual_artifacts.length > 0) {
            artifactsCard?.classList.remove("hidden");
            report.visual_artifacts.forEach(artifact => {
                const wrapper = document.createElement("div");
                wrapper.className = "bg-slate-900 border border-slate-800 rounded-lg p-4 space-y-3";
                
                const header = document.createElement("div");
                header.className = "flex justify-between items-center";
                addText(header, "h4", artifact.title, "text-sm font-semibold text-white");
                addText(header, "span", artifact.artifact_type.toUpperCase().replace("_", " "), "text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-sky-950 text-sky-300 border border-sky-800/60");
                wrapper.appendChild(header);

                if (artifact.svg_content) {
                    const svgHolder = document.createElement("div");
                    svgHolder.className = "w-full overflow-hidden rounded-md border border-slate-800/80 shadow-inner";
                    svgHolder.innerHTML = artifact.svg_content;
                    wrapper.appendChild(svgHolder);
                }

                if (artifact.caption) {
                    addText(wrapper, "p", artifact.caption, "text-xs text-slate-400 italic");
                }
                artifactsContainer.appendChild(wrapper);
            });
        } else {
            artifactsCard?.classList.add("hidden");
        }
    }

    const claimsHeading = document.querySelector("#claims-list")?.parentElement?.querySelector("h3");
    if (claimsHeading) claimsHeading.textContent = "Claims & Verification Status";
    const citationsHeading = document.querySelector("#citations-list")?.parentElement?.querySelector("h3");
    if (citationsHeading) citationsHeading.textContent = "Sources & Citations";
    const claimsList = document.getElementById("claims-list");
    claimsList.replaceChildren();
    (report.claims || []).forEach(claim => {
        const card = document.createElement("div");
        card.className = "bg-slate-900 border border-slate-800 rounded-lg p-4 space-y-2";
        const verified = claim.status === "verified";
        const badge = addText(card, "span", claim.status.toUpperCase(), `inline-flex rounded px-2 py-1 text-xs font-semibold ${verified ? "bg-emerald-950 text-emerald-300" : "bg-slate-800 text-amber-200"}`);
        badge.setAttribute("aria-label", `Verification status: ${claim.status}`);
        addText(card, "p", claim.claim_text, "text-sm font-medium text-white");
        addText(card, "p", claim.verification_notes, "text-xs text-slate-400 bg-slate-950 p-2.5 rounded border border-slate-800/80");
        claimsList.appendChild(card);
    });
    if (!report.claims?.length) addText(claimsList, "p", "No claims were produced for this report.", "text-sm text-slate-400");

    const tableContainer = document.getElementById("metrics-table-container");
    tableContainer.replaceChildren();
    if (report.metric_comparisons?.length) {
        const table = document.createElement("table");
        table.className = "w-full text-xs text-left text-slate-300 border-collapse";
        const head = table.createTHead().insertRow();
        ["Metric", "2023 FY", "2024 FY", "YoY Change", "Source"].forEach(label => {
            const th = document.createElement("th");
            th.textContent = label;
            th.className = "py-2.5 px-3 bg-slate-900 text-slate-400";
            head.appendChild(th);
        });
        const body = table.createTBody();
        report.metric_comparisons.forEach(metric => {
            const row = body.insertRow();
            const periodValue = key => {
                const value = metric.periods?.[key];
                if (value == null) return "N/A";
                if (metric.unit === "USD") return `$${(value / 1_000_000).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}M`;
                return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${metric.unit || ""}`.trim();
            };
            const yoy = metric.yoy_change_pct == null ? "N/A" : `${metric.yoy_change_pct > 0 ? "+" : ""}${metric.yoy_change_pct}%`;
            [metric.metric_name, periodValue("2023-FY"), periodValue("2024-FY"), yoy, report.data_mode === "demo" ? "Synthetic demo" : "SEC facts"].forEach(value => {
                const cell = row.insertCell();
                cell.textContent = value;
                cell.className = "py-2.5 px-3 border-b border-slate-800";
            });
        });
        tableContainer.appendChild(table);
    } else {
        addText(tableContainer, "p", "No tabular metric comparisons are available for this query.", "text-xs text-slate-400");
    }

    const citationsList = document.getElementById("citations-list");
    citationsList.replaceChildren();
    (report.citations || []).forEach(citation => {
        const card = document.createElement("article");
        card.className = "bg-slate-900 border border-slate-800 rounded-lg p-3 text-xs space-y-2";
        addText(card, "p", `${citation.ticker} ${citation.filing_type} (${citation.fiscal_period} ${citation.fiscal_year}) · Page ${citation.page_number}`, "text-slate-300 font-semibold");
        addText(card, "p", `Source type: ${citation.data_source === "demo" ? "Synthetic demo corpus" : citation.data_source}`, "text-amber-200");
        addText(card, "p", `“${citation.excerpt}”`, "text-slate-300 italic bg-slate-950 p-2 rounded border border-slate-800");
        if (citation.data_source === "sec_edgar" && citation.source_url?.startsWith("https://www.sec.gov/")) {
            const link = document.createElement("a");
            link.href = citation.source_url;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.textContent = "Open SEC source";
            link.className = "inline-block text-blue-400 hover:underline";
            card.appendChild(link);
        }
        citationsList.appendChild(card);
    });
    if (!report.citations?.length) addText(citationsList, "p", "No source citations were available.", "text-sm text-slate-400");
    document.getElementById("report-container").classList.remove("hidden");
}
