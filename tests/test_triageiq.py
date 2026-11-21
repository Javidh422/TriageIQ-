import os
import io
import pytest
import pandas as pd
import openpyxl
from fastapi.testclient import TestClient

from app.database import init_db, seed_incidents, get_all_incidents_df, get_jira_board_tickets
from app.analytics import (
    run_etl_pipeline,
    detect_duplicate_clusters,
    find_duplicate_for_text,
    detect_statistical_anomalies,
    ai_triage_and_generate_jira,
    generate_styled_excel_mis
)
from app.main import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_fresh_db():
    """Ensure database is seeded fresh before tests."""
    init_db(seed_if_empty=True)
    seed_incidents()


def test_seed_incidents_count_and_fields():
    """Verify that startup seeding creates 25 realistic incident records with all fields."""
    df = get_all_incidents_df()
    assert len(df) == 25
    expected_cols = [
        "ticket_id", "title", "component", "severity",
        "latency_ms", "status", "sla_target_hours", "sla_breached"
    ]
    for col in expected_cols:
        assert col in df.columns
    # Ensure components have diverse realistic distribution
    components = set(df["component"].unique())
    assert {"Payments", "Database", "Auth", "API", "UI"}.issubset(components)


def test_etl_pipeline_cleaning_and_audit():
    """Test ETL data cleaning: missing values imputation, normalization, and malformed row flags."""
    raw_data = pd.DataFrame([
        {
            "ticket_id": "RAW-01",
            "title": "Stripe checkout failing",
            "description": "User cannot checkout with Visa card",
            "component": None,          # Missing component -> should infer 'Payments'
            "severity": "CRITICAL",      # Non-standard -> should normalize to 'P1'
            "latency_ms": -50.0,         # Negative latency -> malformed, reset to median
            "status": None               # Missing status -> default 'To Do'
        },
        {
            "ticket_id": "RAW-02",
            "title": "",                 # Empty title and desc -> malformed row skipped
            "description": "",
            "component": "API",
            "severity": "P2",
            "latency_ms": 350.0
        },
        {
            "ticket_id": "RAW-03",
            "title": "Safari button alignment",
            "description": "Button misaligned on iOS",
            "component": "ui",           # Lowercase -> normalized to 'UI'
            "severity": None,            # Missing severity -> infer or default 'P3'
            "latency_ms": 120.0
        }
    ])

    cleaned_df, audit = run_etl_pipeline(raw_data)

    assert len(cleaned_df) == 2  # RAW-02 should be dropped
    assert audit["malformed_rows_flagged"] >= 2  # Negative latency and empty row flagged
    assert audit["valid_rows_retained"] == 2
    assert audit["data_quality_score_pct"] > 0

    # Verify imputation & normalization
    row1 = cleaned_df[cleaned_df["ticket_id"] == "RAW-01"].iloc[0]
    assert row1["component"] == "Payments"
    assert row1["severity"] == "P1"
    assert row1["latency_ms"] > 0
    assert row1["status"] == "To Do"

    row3 = cleaned_df[cleaned_df["ticket_id"] == "RAW-03"].iloc[0]
    assert row3["component"] == "UI"
    assert row3["severity"] in ["P3", "P4"]


def test_tfidf_duplicate_detection():
    """Verify TF-IDF + Cosine Similarity identifies semantic duplicate tickets."""
    df = get_all_incidents_df()
    incidents = df.to_dict(orient="records")

    # Detect duplicate pairs within the 25 seeded incidents
    clusters = detect_duplicate_clusters(incidents, similarity_threshold=0.35)
    assert len(clusters) > 0

    # Test an incoming bug query
    query = "Customer unable to complete purchase. Receives 500 error on Stripe payment charge API call."
    match = find_duplicate_for_text(query, incidents, threshold=0.35)
    assert match["is_duplicate"] is True
    assert match["matched_ticket_id"] in ["TIQ-1001", "TIQ-1002"]
    assert match["similarity_score"] > 0.35


def test_statistical_anomaly_detection():
    """Verify Z-score and IQR statistical anomaly detection surfaces latency spikes and hotspots."""
    df = get_all_incidents_df()
    anomalies = detect_statistical_anomalies(df)

    assert anomalies["total_tickets"] == 25
    assert anomalies["mean_latency_ms"] > 0
    assert anomalies["latency_anomalies_count"] > 0

    # Ensure spike incidents (>10,000ms) are flagged
    flagged_ids = [a["ticket_id"] for a in anomalies["latency_anomalies"]]
    assert any(tid in flagged_ids for tid in ["TIQ-1001", "TIQ-1003", "TIQ-1009", "TIQ-1010"])

    # Ensure component hotspots are computed
    assert len(anomalies["hotspots"]) > 0
    components = [h["component"] for h in anomalies["hotspots"]]
    assert "Database" in components or "Payments" in components


def test_ai_triage_and_jira_v3_payload():
    """Verify AI triage classification and Atlassian Jira Cloud REST API v3 JSON payload generation."""
    error_text = "FATAL: PostgreSQL deadlock detected on order_items table during checkout transactions"
    result = ai_triage_and_generate_jira(error_text)

    assert result["component"] == "Database"
    assert result["severity"] == "P1"
    assert result["priority"] == "Highest"
    assert "steps_to_reproduce" in result
    assert "root_cause_hypothesis" in result

    # Validate Jira v3 ADF (Atlassian Document Format) payload
    jira_payload = result["jira_v3_payload"]
    fields = jira_payload["fields"]
    assert fields["project"]["key"] == "TIQ"
    assert fields["issuetype"]["name"] == "Bug"
    assert fields["priority"]["name"] == "Highest"
    assert "triageiq-ai" in fields["labels"]
    assert fields["description"]["type"] == "doc"
    assert fields["description"]["version"] == 1
    assert len(fields["description"]["content"]) >= 3


def test_openpyxl_excel_mis_report_generation():
    """Verify openpyxl multi-tab Excel export with formulas, charts, and conditional styling."""
    df = get_all_incidents_df()
    anomalies = detect_statistical_anomalies(df)
    stream = generate_styled_excel_mis(df, anomalies)

    # Read back generated workbook with openpyxl
    wb = openpyxl.load_workbook(stream)
    sheet_names = wb.sheetnames
    assert "Executive_Summary" in sheet_names
    assert "SLA_and_Anomalies" in sheet_names
    assert "Cleaned_Tickets_Data" in sheet_names

    ws_exec = wb["Executive_Summary"]
    assert ws_exec["A1"].value == "TRIAGEIQ — OPERATIONAL DEFECT & SLA MIS REPORT"
    # Check that Excel formulas exist in column B
    formula_found = False
    for r in range(5, 15):
        val = str(ws_exec[f"B{r}"].value or "")
        if "COUNTIF" in val or "AVERAGE" in val or "COUNTA" in val or "SUM" in val:
            formula_found = True
            break
    assert formula_found, "Executive Summary must contain Excel summary formulas"

    # Check chart presence
    assert len(ws_exec._charts) > 0, "Executive Summary must have an embedded openpyxl BarChart"

    # Check Cleaned Data tab
    ws_data = wb["Cleaned_Tickets_Data"]
    assert ws_data["A1"].value == "Ticket ID"
    assert ws_data.max_row >= 26  # Header + 25 rows


# --- Full REST API Integration Tests ---

def test_api_overview_endpoint():
    """Test GET /api/overview returns all live KPIs and insights."""
    res = client.get("/api/overview")
    assert res.status_code == 200
    data = res.json()
    assert "kpis" in data
    assert data["kpis"]["total_tickets"] == 25
    assert data["kpis"]["data_quality_score_pct"] > 0
    assert "anomalies" in data
    assert "duplicate_clusters" in data


def test_api_triage_analyze_endpoint():
    """Test POST /api/triage/analyze with complaint text."""
    payload = {"raw_text": "Customer receiving HTTP 500 error when submitting payment with Stripe card"}
    res = client.post("/api/triage/analyze", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["component"] == "Payments"
    assert data["severity"] in ["P1", "P2"]
    assert "jira_v3_payload" in data
    assert data["duplicate_detection"]["is_duplicate"] is True


def test_api_jira_sync_and_status_update():
    """Test POST /api/jira/sync and PATCH /api/jira/{ticket_id}/status."""
    sync_payload = {
        "summary": "Fix connection pool exhaustion in database",
        "description": "Detailed description of DB pool limits",
        "component": "Database",
        "severity": "P1",
        "priority": "Highest",
        "labels": "triageiq-ai,database,p1",
        "steps_to_reproduce": "Run 50 parallel export queries",
        "root_cause_hypothesis": "Pool limit 50 is too low"
    }
    res = client.post("/api/jira/sync", json=sync_payload)
    assert res.status_code == 200
    ticket_id = res.json()["ticket_id"]
    assert ticket_id.startswith("TIQ-")

    # Update status to "In Progress"
    res_status = client.patch(f"/api/jira/{ticket_id}/status", json={"status": "In Progress"})
    assert res_status.status_code == 200
    assert res_status.json()["new_status"] == "In Progress"

    # Update status to "Done"
    res_done = client.patch(f"/api/jira/{ticket_id}/status", json={"status": "Done"})
    assert res_done.status_code == 200
    assert res_done.json()["new_status"] == "Done"


def test_api_ingest_seed_sample_endpoint():
    """Test POST /api/ingest/seed-sample."""
    res = client.post("/api/ingest/seed-sample")
    assert res.status_code == 200
    assert res.json()["records_count"] == 25


def test_api_ingest_upload_csv():
    """Test POST /api/ingest/upload with a CSV file."""
    csv_content = (
        "ticket_id,title,description,component,severity,latency_ms,status\n"
        "TIQ-CSV-1,Payment token expired,Stripe token expired,Payments,P1,1200,To Do\n"
        "TIQ-CSV-2,Database deadlock,Order items deadlock,Database,P1,8500,In Progress\n"
    )
    files = {"file": ("test_incidents.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    res = client.post("/api/ingest/upload", files=files)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["audit_report"]["valid_rows_retained"] == 2


def test_api_export_excel():
    """Test GET /api/export/excel returns binary spreadsheet with attachment headers."""
    res = client.get("/api/export/excel")
    assert res.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in res.headers["content-type"]
    assert "attachment; filename=TriageIQ_MIS_Report_" in res.headers["content-disposition"]
    # Check binary content can be parsed by openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(res.content))
    assert len(wb.sheetnames) == 3
