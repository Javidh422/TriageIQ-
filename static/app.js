// TriageIQ — Client-Side Application Engine

document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const kpiTotal = document.getElementById("kpi-total-tickets");
  const kpiQuality = document.getElementById("kpi-quality-score");
  const kpiDuplicates = document.getElementById("kpi-duplicates");
  const kpiSla = document.getElementById("kpi-sla-rate");
  
  const tbodyLatency = document.getElementById("tbody-latency-anomalies");
  const latencyCount = document.getElementById("latency-anomalies-count");
  const tbodyHotspots = document.getElementById("tbody-hotspots");
  
  const colTodo = document.getElementById("col-todo");
  const colInProgress = document.getElementById("col-inprogress");
  const colQa = document.getElementById("col-qa");
  const colDone = document.getElementById("col-done");
  const boardSearch = document.getElementById("board-search");
  const boardTotalCount = document.getElementById("board-total-count");

  // Triage Elements
  const triageForm = document.getElementById("triage-form");
  const triageInput = document.getElementById("triage-input");
  const triageLoader = document.getElementById("triage-loader");
  const triageResult = document.getElementById("triage-result");
  const resSeverity = document.getElementById("res-severity");
  const resComponent = document.getElementById("res-component");
  const resSla = document.getElementById("res-sla");
  const resSummary = document.getElementById("res-summary");
  const resRootCause = document.getElementById("res-root-cause");
  const resSteps = document.getElementById("res-steps");
  const resJiraJson = document.getElementById("res-jira-json");
  const duplicateAlert = document.getElementById("duplicate-alert");
  const dupDetails = document.getElementById("dup-details");
  const btnPushJira = document.getElementById("btn-push-jira");
  const pushStatusText = document.getElementById("push-status-text");
  const btnCopyJira = document.getElementById("btn-copy-jira");

  // Ingest Elements
  const fileInput = document.getElementById("file-input");
  const uploadZone = document.getElementById("upload-zone");
  const btnBrowseFile = document.getElementById("btn-browse-file");
  const btnLoadSampleEtl = document.getElementById("btn-load-sample-etl");
  const btnSeedSample = document.getElementById("btn-seed-sample");
  const etlAuditOutput = document.getElementById("etl-audit-output");
  const auditScorePill = document.getElementById("audit-score-pill");
  const auditRawRows = document.getElementById("audit-raw-rows");
  const auditCleanRows = document.getElementById("audit-clean-rows");
  const auditImputedNulls = document.getElementById("audit-imputed-nulls");
  const auditMalformed = document.getElementById("audit-malformed");
  const auditBreakdownDetails = document.getElementById("audit-breakdown-details");

  // Modal Elements
  const btnRunTests = document.getElementById("btn-run-tests");
  const testModal = document.getElementById("test-modal");
  const btnCloseModal = document.getElementById("btn-close-modal");
  const btnModalDone = document.getElementById("btn-modal-done");
  const testModalStatus = document.getElementById("test-modal-status");
  const testModalLog = document.getElementById("test-modal-log");

  // State
  let allJiraTickets = [];
  let currentTriageAnalysis = null;

  // --- Initial Data Load ---
  fetchOverview();

  // --- Core Fetch Functions ---
  async function fetchOverview() {
    try {
      const res = await fetch("/api/overview");
      if (!res.ok) throw new Error("Failed to fetch overview data");
      const data = await res.json();

      // Update KPIs
      kpiTotal.textContent = data.kpis.total_tickets || 0;
      kpiQuality.textContent = `${data.kpis.data_quality_score_pct || 98}%`;
      kpiDuplicates.textContent = data.duplicate_clusters.length || 0;
      kpiSla.textContent = `${data.kpis.sla_breach_rate_pct || 0}%`;

      // Update Latency Outliers Table
      renderLatencyAnomalies(data.anomalies.latency_anomalies || []);

      // Update Hotspots Table
      renderHotspots(data.anomalies.hotspots || []);

      // Update Jira Board
      allJiraTickets = data.jira_board_tickets || [];
      renderJiraBoard(allJiraTickets);

    } catch (err) {
      console.error(err);
      showToast("Error loading system metrics: " + err.message, "error");
    }
  }

  function renderLatencyAnomalies(anomalies) {
    latencyCount.textContent = `${anomalies.length} Detected`;
    if (!anomalies || anomalies.length === 0) {
      tbodyLatency.innerHTML = '<tr><td colspan="5" class="empty-cell">No severe latency anomalies detected.</td></tr>';
      return;
    }

    tbodyLatency.innerHTML = anomalies.map(a => `
      <tr>
        <td><strong>${escapeHtml(a.ticket_id)}</strong></td>
        <td>${escapeHtml(a.title.slice(0, 36))}${a.title.length > 36 ? '...' : ''}</td>
        <td><span class="badge badge-gray">${escapeHtml(a.component)}</span></td>
        <td class="text-red text-bold">${a.latency_ms.toLocaleString()} ms</td>
        <td><span class="badge badge-orange">${a.z_score}σ</span></td>
      </tr>
    `).join("");
  }

  function renderHotspots(hotspots) {
    if (!hotspots || hotspots.length === 0) {
      tbodyHotspots.innerHTML = '<tr><td colspan="5" class="empty-cell">No hotspots identified.</td></tr>';
      return;
    }

    tbodyHotspots.innerHTML = hotspots.map(h => {
      let riskBadge = "badge-green";
      if (h.risk_level === "High") riskBadge = "badge-red";
      else if (h.risk_level === "Medium") riskBadge = "badge-orange";

      return `
        <tr>
          <td><strong>${escapeHtml(h.component)}</strong></td>
          <td>${h.total_defects} (${h.percentage_of_all}%)</td>
          <td><span class="text-red text-bold">${h.p1_critical_count}</span></td>
          <td>${h.sla_breaches}</td>
          <td><span class="badge ${riskBadge}">${h.risk_level}</span></td>
        </tr>
      `;
    }).join("");
  }

  function renderJiraBoard(tickets) {
    const filter = (boardSearch.value || "").toLowerCase().trim();
    const filtered = tickets.filter(t => 
      !filter ||
      (t.summary && t.summary.toLowerCase().includes(filter)) ||
      (t.ticket_id && t.ticket_id.toLowerCase().includes(filter)) ||
      (t.component && t.component.toLowerCase().includes(filter))
    );

    boardTotalCount.textContent = `${filtered.length} Tickets`;

    const cols = {
      "To Do": [],
      "In Progress": [],
      "QA Verification": [],
      "Done": []
    };

    filtered.forEach(t => {
      const st = t.status || "To Do";
      if (cols[st]) cols[st].push(t);
      else cols["To Do"].push(t);
    });

    document.getElementById("count-todo").textContent = cols["To Do"].length;
    document.getElementById("count-inprogress").textContent = cols["In Progress"].length;
    document.getElementById("count-qa").textContent = cols["QA Verification"].length;
    document.getElementById("count-done").textContent = cols["Done"].length;

    renderColumnCards(colTodo, cols["To Do"]);
    renderColumnCards(colInProgress, cols["In Progress"]);
    renderColumnCards(colQa, cols["QA Verification"]);
    renderColumnCards(colDone, cols["Done"]);
  }

  function renderColumnCards(container, list) {
    if (list.length === 0) {
      container.innerHTML = '<div class="empty-cell" style="font-size:12px; padding:16px;">No tickets</div>';
      return;
    }

    container.innerHTML = list.map(t => {
      const pColor = t.priority === "Highest" ? "badge-red" : (t.priority === "High" ? "badge-orange" : "badge-gray");
      return `
        <div class="ticket-card" data-id="${t.ticket_id}">
          <div class="ticket-top">
            <span class="ticket-key">${escapeHtml(t.ticket_id)}</span>
            <span class="badge ${pColor}">${escapeHtml(t.priority || "Medium")}</span>
          </div>
          <div class="ticket-summary">${escapeHtml(t.summary)}</div>
          <div class="ticket-meta">
            <span class="badge badge-gray">${escapeHtml(t.component || "General")}</span>
            <select class="status-select" onchange="window.updateStatus('${t.ticket_id}', this.value)">
              <option value="To Do" ${t.status === 'To Do' ? 'selected' : ''}>To Do</option>
              <option value="In Progress" ${t.status === 'In Progress' ? 'selected' : ''}>In Progress</option>
              <option value="QA Verification" ${t.status === 'QA Verification' ? 'selected' : ''}>QA Verification</option>
              <option value="Done" ${t.status === 'Done' ? 'selected' : ''}>Done</option>
            </select>
          </div>
        </div>
      `;
    }).join("");
  }

  // Window status update handler
  window.updateStatus = async function(ticketId, newStatus) {
    try {
      const res = await fetch(`/api/jira/${ticketId}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus })
      });
      if (!res.ok) throw new Error("Status update failed");
      
      showToast(`Updated ${ticketId} -> ${newStatus}`);
      fetchOverview();
    } catch (err) {
      showToast(err.message, "error");
    }
  };

  boardSearch.addEventListener("input", () => {
    renderJiraBoard(allJiraTickets);
  });

  // --- Sample Chips Prompting ---
  document.querySelectorAll(".chip").forEach(chip => {
    chip.addEventListener("click", () => {
      triageInput.value = chip.getAttribute("data-sample");
      triageInput.focus();
    });
  });

  // --- AI Triage Form Submission ---
  triageForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = triageInput.value.trim();
    if (!text) return;

    triageLoader.style.display = "inline-block";
    pushStatusText.textContent = "";

    try {
      const res = await fetch("/api/triage/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw_text: text })
      });

      if (!res.ok) throw new Error("Failed to analyze text");
      const data = await res.json();
      currentTriageAnalysis = data;

      // Populate result
      resSummary.textContent = data.summary;
      resRootCause.textContent = data.root_cause_hypothesis;
      resSteps.textContent = data.steps_to_reproduce;
      resJiraJson.textContent = JSON.stringify(data.jira_v3_payload, null, 2);

      // Severity badge
      resSeverity.textContent = `${data.severity} ${data.priority}`;
      resSeverity.className = "badge " + (data.severity === "P1" ? "badge-red" : (data.severity === "P2" ? "badge-orange" : "badge-gray"));

      // Component badge
      resComponent.textContent = data.component;
      resSla.textContent = `SLA: ${data.sla_target_hours}h`;

      // Duplicate detection
      const dup = data.duplicate_detection;
      if (dup && dup.is_duplicate) {
        duplicateAlert.style.display = "flex";
        dupDetails.textContent = `Matches existing ticket ${dup.matched_ticket_id} ("${dup.matched_title}") with ${Math.round(dup.similarity_score * 100)}% cosine similarity.`;
      } else {
        duplicateAlert.style.display = "none";
      }

      triageResult.style.display = "block";
      showToast("Defect analyzed and classified successfully!");

    } catch (err) {
      showToast("Analysis failed: " + err.message, "error");
    } finally {
      triageLoader.style.display = "none";
    }
  });

  // Push to Jira Board
  btnPushJira.addEventListener("click", async () => {
    if (!currentTriageAnalysis) return;

    pushStatusText.textContent = "Syncing to Jira board...";
    try {
      const res = await fetch("/api/jira/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          summary: currentTriageAnalysis.summary,
          description: currentTriageAnalysis.actual_result,
          component: currentTriageAnalysis.component,
          severity: currentTriageAnalysis.severity,
          priority: currentTriageAnalysis.priority,
          steps_to_reproduce: currentTriageAnalysis.steps_to_reproduce,
          root_cause_hypothesis: currentTriageAnalysis.root_cause_hypothesis
        })
      });

      if (!res.ok) throw new Error("Jira sync failed");
      const data = await res.json();
      pushStatusText.textContent = `Synced as ${data.ticket_id} to Jira board!`;
      showToast(`Pushed to Jira board: ${data.ticket_id}`);
      fetchOverview();
    } catch (err) {
      pushStatusText.textContent = "Failed to sync: " + err.message;
      showToast(err.message, "error");
    }
  });

  // Copy Jira JSON
  btnCopyJira.addEventListener("click", () => {
    if (!resJiraJson.textContent) return;
    navigator.clipboard.writeText(resJiraJson.textContent);
    showToast("Jira REST v3 JSON copied to clipboard!");
  });

  // --- File Upload & ETL Pipeline ---
  btnBrowseFile.addEventListener("click", () => fileInput.click());
  uploadZone.addEventListener("click", (e) => {
    if (e.target !== btnLoadSampleEtl) {
      fileInput.click();
    }
  });

  uploadZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    uploadZone.classList.add("dragover");
  });

  uploadZone.addEventListener("dragleave", () => {
    uploadZone.classList.remove("dragover");
  });

  uploadZone.addEventListener("drop", (e) => {
    e.preventDefault();
    uploadZone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files && fileInput.files.length > 0) {
      handleFileUpload(fileInput.files[0]);
    }
  });

  async function handleFileUpload(file) {
    const formData = new FormData();
    formData.append("file", file);

    showToast(`Uploading and cleaning ${file.name}...`);
    try {
      const res = await fetch("/api/ingest/upload", {
        method: "POST",
        body: formData
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Upload failed");
      }

      const data = await res.json();
      renderAuditReport(data.audit_report);
      showToast("ETL processing complete!");
      fetchOverview();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  // Load Sample Dataset in ETL Panel
  btnLoadSampleEtl.addEventListener("click", async (e) => {
    e.stopPropagation();
    await seedFreshData();
  });

  // Reset Sample Data Header Button
  btnSeedSample.addEventListener("click", async () => {
    await seedFreshData();
  });

  async function seedFreshData() {
    showToast("Loading 25 realistic incident records...");
    try {
      const res = await fetch("/api/ingest/seed-sample", { method: "POST" });
      if (!res.ok) throw new Error("Failed to seed sample data");
      const data = await res.json();
      renderAuditReport(data.audit_report);
      showToast("Loaded 25 realistic incident records into database!");
      fetchOverview();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  function renderAuditReport(audit) {
    if (!audit) return;
    etlAuditOutput.style.display = "block";
    auditScorePill.textContent = `${audit.data_quality_score_pct}% Quality`;
    auditRawRows.textContent = audit.total_rows_raw;
    auditCleanRows.textContent = audit.valid_rows_retained;
    auditImputedNulls.textContent = audit.total_nulls_imputed;
    auditMalformed.textContent = audit.malformed_rows_flagged;

    const imputedEntries = Object.entries(audit.nulls_imputed || {})
      .filter(([_, count]) => count > 0)
      .map(([col, count]) => `<strong>${col}</strong>: ${count}`)
      .join(", ");

    auditBreakdownDetails.innerHTML = `
      <div><strong>Imputed Fields:</strong> ${imputedEntries || 'None'}</div>
      <div><strong>Sanitization Rules Applied:</strong> Timestamp standardization, negative latency reset to median, component keyword inference, and P1-P4 normalization.</div>
    `;
  }

  // --- Modal Test Execution ---
  btnRunTests.addEventListener("click", async () => {
    testModal.style.display = "flex";
    testModalStatus.textContent = "Running comprehensive pytest test suite...";
    testModalStatus.className = "test-status-banner";
    testModalLog.textContent = "Executing: pytest -v\nTesting ETL, TF-IDF Deduplication, Z-Score Outliers, Jira REST v3, and OpenPyXL Excel Export...\n\n";

    try {
      const res = await fetch("/api/test/run", { method: "POST" });
      const data = await res.json();

      if (data.status === "success") {
        testModalStatus.textContent = "All pytest test suites PASSED successfully!";
        testModalStatus.style.background = "var(--apple-green-light)";
        testModalStatus.style.color = "var(--apple-green-dark)";
      } else {
        testModalStatus.textContent = `Tests finished with exit code ${data.exit_code}`;
        testModalStatus.style.background = "var(--apple-red-light)";
        testModalStatus.style.color = "var(--apple-red-dark)";
      }
      testModalLog.textContent = data.output;
    } catch (err) {
      testModalStatus.textContent = "Failed to run pytest: " + err.message;
      testModalLog.textContent += "\nError: " + err.message;
    }
  });

  btnCloseModal.addEventListener("click", () => testModal.style.display = "none");
  btnModalDone.addEventListener("click", () => testModal.style.display = "none");

  // --- Toast Notification Helper ---
  function showToast(message, type = "success") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = "toast";
    
    const icon = type === "error" ? "❌" : "✓";
    toast.innerHTML = `<span>${icon}</span> <span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(12px)";
      toast.style.transition = "all 0.25s ease";
      setTimeout(() => toast.remove(), 250);
    }, 3200);
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
});
