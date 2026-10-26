document.addEventListener("DOMContentLoaded", () => {
    checkHealth();
    loadCompanies();
});

async function checkHealth() {
    try {
        const resp = await fetch("/health");
        const data = await resp.json();
        const elem = document.getElementById("system-status");
        if (data.status === "healthy") {
            elem.className = "bg-emerald-950 text-emerald-400 border border-emerald-800/50 px-2.5 py-1 rounded-full";
            elem.innerHTML = `<i class="fa-solid fa-server mr-1"></i> ${data.companies_count} Companies | ${data.xbrl_facts_count} XBRL Facts`;
        }
    } catch (err) {
        const elem = document.getElementById("system-status");
        elem.className = "bg-rose-950 text-rose-400 border border-rose-800/50 px-2.5 py-1 rounded-full";
        elem.innerHTML = `<i class="fa-solid fa-circle-exclamation mr-1"></i> Offline`;
    }
}

async function loadCompanies() {
    try {
        const resp = await fetch("/api/companies");
        const companies = await resp.json();
        const select = document.getElementById("company-select");
        select.innerHTML = "";
        companies.forEach(c => {
            const opt = document.createElement("option");
            opt.value = c.ticker;
            opt.textContent = `${c.ticker} - ${c.name}`;
            select.appendChild(opt);
        });
    } catch (err) {
        console.error("Failed to load companies", err);
    }
}

function setPreset(ticker, question) {
    document.getElementById("company-select").value = ticker;
    document.getElementById("question-input").value = question;
}

async function submitQuery() {
    const ticker = document.getElementById("company-select").value;
    const question = document.getElementById("question-input").value.trim();

    if (!question) {
        alert("Please enter a research question.");
        return;
    }

    document.getElementById("empty-state").classList.add("hidden");
    document.getElementById("report-container").classList.add("hidden");
    document.getElementById("loading-state").classList.remove("hidden");

    try {
        const resp = await fetch("/api/query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question, ticker })
        });

        if (!resp.ok) {
            const errData = await resp.json();
            throw new Error(errData.detail || "Query failed");
        }

        const report = await resp.json();
        renderReport(report);
    } catch (err) {
        alert(`Error generating report: ${err.message}`);
        document.getElementById("empty-state").classList.remove("hidden");
    } finally {
        document.getElementById("loading-state").classList.add("hidden");
    }
}

function renderReport(report) {
    document.getElementById("report-title").textContent = `Research Report: ${report.target_tickers.join(", ")}`;
    document.getElementById("generated-timestamp").textContent = `Generated: ${new Date(report.generated_at).toLocaleString()}`;
    document.getElementById("executive-summary").textContent = report.executive_summary;

    // Claims
    const claimsList = document.getElementById("claims-list");
    claimsList.innerHTML = "";
    report.claims.forEach(c => {
        const card = document.createElement("div");
        card.className = "bg-slate-900 border border-slate-800 rounded-lg p-4 space-y-2";
        card.innerHTML = `
            <div class="flex justify-between items-center text-xs">
                <span class="bg-emerald-950 text-emerald-400 border border-emerald-800/50 px-2 py-0.5 rounded font-semibold uppercase tracking-wider">
                    <i class="fa-solid fa-check mr-1"></i> ${c.status}
                </span>
                <span class="text-slate-500">${c.claim_id}</span>
            </div>
            <p class="text-sm font-medium text-white">${c.claim_text}</p>
            <p class="text-xs text-slate-400 bg-slate-950 p-2.5 rounded border border-slate-800/80">${c.verification_notes}</p>
        `;
        claimsList.appendChild(card);
    });

    // Metrics Table
    const tableContainer = document.getElementById("metrics-table-container");
    if (report.metric_comparisons && report.metric_comparisons.length > 0) {
        let html = `
            <table class="w-full text-xs text-left text-slate-300 border-collapse">
                <thead class="bg-slate-900 border-b border-slate-800 uppercase tracking-wider text-slate-400">
                    <tr>
                        <th class="py-2.5 px-3">Metric Concept</th>
                        <th class="py-2.5 px-3">2023 FY</th>
                        <th class="py-2.5 px-3">2024 FY</th>
                        <th class="py-2.5 px-3">YoY Change</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-800">
        `;
        report.metric_comparisons.forEach(m => {
            const val23 = m.periods["2023-FY"] ? (m.periods["2023-FY"] / 1000000.0).toFixed(2) + "M" : "N/A";
            const val24 = m.periods["2024-FY"] ? (m.periods["2024-FY"] / 1000000.0).toFixed(2) + "M" : "N/A";
            const yoy = m.yoy_change_pct !== null && m.yoy_change_pct !== undefined ? `${m.yoy_change_pct > 0 ? '+' : ''}${m.yoy_change_pct}%` : "N/A";
            const yoyColor = m.yoy_change_pct > 0 ? "text-emerald-400" : (m.yoy_change_pct < 0 ? "text-rose-400" : "text-slate-400");

            html += `
                <tr class="hover:bg-slate-900/50">
                    <td class="py-2.5 px-3 font-semibold text-white">${m.metric_name}</td>
                    <td class="py-2.5 px-3">$${val23}</td>
                    <td class="py-2.5 px-3">$${val24}</td>
                    <td class="py-2.5 px-3 font-bold ${yoyColor}">${yoy}</td>
                </tr>
            `;
        });
        html += `</tbody></table>`;
        tableContainer.innerHTML = html;
    } else {
        tableContainer.innerHTML = `<p class="text-xs text-slate-500">No tabular metric comparisons available.</p>`;
    }

    // Citations
    const citationsList = document.getElementById("citations-list");
    citationsList.innerHTML = "";
    report.citations.forEach(c => {
        const citeCard = document.createElement("div");
        citeCard.className = "bg-slate-900 border border-slate-800 rounded-lg p-3 text-xs space-y-2";
        citeCard.innerHTML = `
            <div class="flex justify-between items-center text-slate-400 font-semibold">
                <span>${c.ticker} ${c.filing_type} (${c.fiscal_period} ${c.fiscal_year})</span>
                <span class="bg-blue-950 text-blue-400 px-2 py-0.5 rounded">Page ${c.page_number}</span>
            </div>
            <p class="text-slate-300 italic bg-slate-950 p-2 rounded border border-slate-800">"${c.excerpt}"</p>
            <a href="${c.source_url}" target="_blank" class="inline-block text-blue-400 hover:underline text-[11px]">
                <i class="fa-solid fa-arrow-up-right-from-square mr-1"></i> View Source SEC Edgar Record
            </a>
        `;
        citationsList.appendChild(citeCard);
    });

    document.getElementById("report-container").classList.remove("hidden");
}
