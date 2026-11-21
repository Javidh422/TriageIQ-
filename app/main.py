import os
import io
import subprocess
import pandas as pd
import httpx
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Response
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.database import (
    init_db, seed_incidents, get_all_incidents, get_all_incidents_df,
    get_jira_board_tickets, update_jira_ticket_status, upsert_jira_ticket,
    get_db_connection
)
from app.analytics import (
    run_etl_pipeline, detect_duplicate_clusters, find_duplicate_for_text,
    detect_statistical_anomalies, ai_triage_and_generate_jira,
    generate_styled_excel_mis
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(seed_if_empty=True)
    yield

app = FastAPI(
    title="TriageIQ",
    description="AI-Powered Defect, Ticket & Operational Data Triage Hub",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static folder
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Pydantic Request Models
class TriageRequest(BaseModel):
    raw_text: str

class JiraSyncRequest(BaseModel):
    ticket_id: Optional[str] = None
    summary: str
    description: Optional[str] = ""
    component: Optional[str] = "API"
    severity: Optional[str] = "P3"
    priority: Optional[str] = "Medium"
    labels: Optional[str] = "triageiq-ai"
    steps_to_reproduce: Optional[str] = ""
    root_cause_hypothesis: Optional[str] = ""
    jira_cloud_url: Optional[str] = None
    jira_email: Optional[str] = None
    jira_api_token: Optional[str] = None

class StatusUpdateRequest(BaseModel):
    status: str


# --- Core API Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse("<h1>TriageIQ is running. Please check static/index.html</h1>")


@app.get("/api/overview")
async def get_overview():
    """
    Returns live KPIs: Total Tickets, Data Quality Score %, Duplicate Rate %,
    SLA Breach %, Anomaly Alerts, Jira Board counts, and Data Mining Insights.
    """
    df = get_all_incidents_df()
    total_tickets = len(df)
    
    if total_tickets == 0:
        return {
            "kpis": {
                "total_tickets": 0,
                "data_quality_score_pct": 100.0,
                "duplicate_rate_pct": 0.0,
                "sla_breach_rate_pct": 0.0,
                "mean_latency_ms": 0.0
            },
            "anomalies": {},
            "duplicate_clusters": [],
            "jira_board_tickets": []
        }

    anomalies_info = detect_statistical_anomalies(df)
    incidents = df.to_dict(orient="records")
    duplicate_clusters = detect_duplicate_clusters(incidents, similarity_threshold=0.35)
    jira_tickets = get_jira_board_tickets()

    # Calculate duplicate rate
    dup_tickets_count = len(df[df["is_duplicate"] == 1])
    dup_rate = round((dup_tickets_count / total_tickets * 100), 1) if total_tickets > 0 else 0.0

    # Quality score based on completeness
    null_count = int(df[["title", "component", "severity", "latency_ms"]].isna().sum().sum())
    quality_score = max(50.0, round(100.0 - (null_count / (total_tickets * 4) * 100), 1))

    return {
        "kpis": {
            "total_tickets": total_tickets,
            "data_quality_score_pct": quality_score,
            "duplicate_rate_pct": dup_rate,
            "duplicate_clusters_count": len(duplicate_clusters),
            "sla_breach_rate_pct": anomalies_info.get("sla_breach_rate_pct", 0.0),
            "total_sla_breaches": anomalies_info.get("total_sla_breaches", 0),
            "mean_latency_ms": anomalies_info.get("mean_latency_ms", 0.0),
            "latency_anomalies_count": anomalies_info.get("latency_anomalies_count", 0),
            "jira_board_count": len(jira_tickets)
        },
        "anomalies": anomalies_info,
        "duplicate_clusters": duplicate_clusters,
        "jira_board_tickets": jira_tickets
    }


@app.post("/api/ingest/upload")
async def ingest_upload(file: UploadFile = File(...)):
    """
    Upload an Excel (.xlsx) or CSV (.csv) file, clean messy data through ETL pipeline,
    update database, and return a comprehensive Data Quality Audit report.
    """
    filename = file.filename.lower()
    contents = await file.read()

    try:
        if filename.endswith(".csv"):
            raw_df = pd.read_csv(io.BytesIO(contents))
        elif filename.endswith(".xlsx") or filename.endswith(".xls"):
            raw_df = pd.read_excel(io.BytesIO(contents))
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format. Please upload .csv or .xlsx")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

    cleaned_df, audit_report = run_etl_pipeline(raw_df)

    # Persist cleaned records to database
    conn = get_db_connection()
    cursor = conn.cursor()

    for _, row in cleaned_df.iterrows():
        cursor.execute("""
            INSERT INTO incidents (
                ticket_id, title, description, component, severity, latency_ms,
                status, sla_target_hours, created_at, resolved_at, resolution_time_hours,
                sla_breached, is_duplicate, duplicate_of, reporter, raw_log, jira_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticket_id) DO UPDATE SET
                title=excluded.title,
                description=excluded.description,
                component=excluded.component,
                severity=excluded.severity,
                latency_ms=excluded.latency_ms,
                status=excluded.status
        """, (
            row["ticket_id"], row["title"], row["description"], row["component"],
            row["severity"], row["latency_ms"], row["status"], row["sla_target_hours"],
            row["created_at"], row["resolved_at"], row["resolution_time_hours"],
            row["sla_breached"], row["is_duplicate"], row["duplicate_of"],
            row["reporter"], row["raw_log"], row["jira_key"]
        ))
        
        # Also ensure Jira board record
        priority_map = {"P1": "Highest", "P2": "High", "P3": "Medium", "P4": "Low"}
        cursor.execute("""
            INSERT INTO jira_board (
                ticket_id, summary, description, component, priority, severity,
                status, labels, steps_to_reproduce, root_cause_hypothesis,
                synced_at, cloud_sync_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticket_id) DO UPDATE SET
                summary=excluded.summary,
                component=excluded.component,
                priority=excluded.priority,
                severity=excluded.severity,
                status=excluded.status
        """, (
            row["ticket_id"], row["title"], row["description"], row["component"],
            priority_map.get(row["severity"], "Medium"), row["severity"], row["status"],
            f"triageiq-ai,{row['component'].lower()},{row['severity'].lower()}",
            f"1. Navigate to {row['component']}\n2. Perform operation related to: {row['title']}",
            f"Likely issue in {row['component']} module or third-party dependency.",
            datetime.utcnow().isoformat(), "Ingested"
        ))

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "message": f"Successfully ingested {len(cleaned_df)} records via ETL pipeline.",
        "audit_report": audit_report,
        "sample_cleaned_rows": cleaned_df.head(5).to_dict(orient="records")
    }


@app.post("/api/ingest/seed-sample")
async def seed_sample_data():
    """
    Resets and re-seeds database with the 25 realistic, messy incident records.
    """
    seed_incidents()
    df = get_all_incidents_df()
    cleaned_df, audit_report = run_etl_pipeline(df)
    return {
        "status": "success",
        "message": "Seeded 25 realistic software support & QA incident records into database.",
        "audit_report": audit_report,
        "records_count": len(df)
    }


@app.post("/api/triage/analyze")
async def analyze_defect(request: TriageRequest):
    """
    Accepts raw user complaint text or error logs:
    - Predicts Severity (P1-P4) & Component (API, UI, Database, Payments, Auth)
    - Finds matching duplicate tickets via TF-IDF + Cosine Similarity
    - Generates Jira REST API v3 structured JSON payload
    - Proposes root cause hypothesis & steps to reproduce
    """
    raw_text = request.raw_text.strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="Raw complaint or error text cannot be empty.")

    incidents = get_all_incidents()
    result = ai_triage_and_generate_jira(raw_text, incidents)
    return result


@app.post("/api/jira/sync")
async def sync_jira_ticket(payload: JiraSyncRequest):
    """
    Formats tickets into official Jira REST API v3 JSON payloads,
    allows optional live push to Atlassian Jira Cloud if credentials are provided,
    and updates/inserts into local Jira board.
    """
    ticket_data = {
        "ticket_id": payload.ticket_id,
        "summary": payload.summary,
        "description": payload.description,
        "component": payload.component,
        "priority": payload.priority,
        "severity": payload.severity,
        "labels": payload.labels,
        "steps_to_reproduce": payload.steps_to_reproduce,
        "root_cause_hypothesis": payload.root_cause_hypothesis,
        "status": "To Do",
        "cloud_sync_status": "Local Synced",
        "jira_cloud_url": payload.jira_cloud_url or ""
    }

    # Optional live push to Atlassian Jira Cloud if credentials provided
    cloud_pushed = False
    cloud_key = None
    if payload.jira_cloud_url and payload.jira_email and payload.jira_api_token:
        try:
            auth = (payload.jira_email, payload.jira_api_token)
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            api_endpoint = f"{payload.jira_cloud_url.rstrip('/')}/rest/api/3/issue"

            jira_body = {
                "fields": {
                    "project": {"key": "TIQ"},
                    "summary": payload.summary,
                    "issuetype": {"name": "Bug"},
                    "priority": {"name": payload.priority},
                    "labels": [lbl.strip() for lbl in payload.labels.split(",") if lbl.strip()],
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": payload.description or payload.summary}]
                            }
                        ]
                    }
                }
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(api_endpoint, json=jira_body, auth=auth, headers=headers)
                if res.status_code in [200, 201]:
                    cloud_data = res.json()
                    cloud_key = cloud_data.get("key")
                    ticket_data["cloud_sync_status"] = f"Pushed ({cloud_key})"
                    cloud_pushed = True
                else:
                    ticket_data["cloud_sync_status"] = f"Cloud Error ({res.status_code})"
        except Exception as e:
            ticket_data["cloud_sync_status"] = f"Sync Failed: {str(e)[:40]}"

    ticket_id = upsert_jira_ticket(ticket_data)

    return {
        "status": "success",
        "ticket_id": ticket_id,
        "cloud_pushed": cloud_pushed,
        "cloud_key": cloud_key,
        "cloud_sync_status": ticket_data["cloud_sync_status"],
        "message": f"Ticket {ticket_id} synced to Jira board."
    }


@app.patch("/api/jira/{ticket_id}/status")
async def update_status(ticket_id: str, request: StatusUpdateRequest):
    """
    Updates local Jira board ticket state (To Do -> In Progress -> QA Verification -> Done).
    """
    valid_statuses = ["To Do", "In Progress", "QA Verification", "Done"]
    if request.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    updated = update_jira_ticket_status(ticket_id, request.status)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found.")

    return {
        "status": "success",
        "ticket_id": ticket_id,
        "new_status": request.status,
        "message": f"Ticket {ticket_id} moved to {request.status}."
    }


@app.get("/api/jira/board")
async def get_jira_board():
    """
    Returns all Jira board tickets organized by status columns.
    """
    tickets = get_jira_board_tickets()
    board = {
        "To Do": [],
        "In Progress": [],
        "QA Verification": [],
        "Done": []
    }
    for t in tickets:
        st = t.get("status", "To Do")
        if st not in board:
            board[st] = []
        board[st].append(t)

    return {
        "total_tickets": len(tickets),
        "columns": board,
        "tickets": tickets
    }


@app.get("/api/export/excel")
async def export_excel_mis():
    """
    Generates and downloads a multi-tab formatted Microsoft Excel MIS workbook:
    - Tab 1: Executive_Summary (with KPI metrics, COUNTIF/AVERAGE formulas, openpyxl BarChart)
    - Tab 2: SLA_and_Anomalies (breached tickets, Z-score latency spikes)
    - Tab 3: Cleaned_Tickets_Data (dark slate headers, zebra striping, conditional severity styling)
    """
    df = get_all_incidents_df()
    if df.empty:
        seed_incidents()
        df = get_all_incidents_df()

    anomalies_info = detect_statistical_anomalies(df)
    excel_stream = generate_styled_excel_mis(df, anomalies_info)

    filename = f"TriageIQ_MIS_Report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        excel_stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.post("/api/test/run")
async def run_pytest_suite():
    """
    Runs pytest test suite programmatically and returns execution summary and log.
    Allows testing directly from the Apple-inspired UI.
    """
    try:
        # Run pytest inside the virtual environment or python3
        venv_pytest = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".venv", "bin", "pytest")
        cmd = [venv_pytest, "-v"] if os.path.exists(venv_pytest) else ["pytest", "-v"]

        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
        return {
            "status": "success" if process.returncode == 0 else "failed",
            "exit_code": process.returncode,
            "output": process.stdout
        }
    except Exception as e:
        return {
            "status": "error",
            "exit_code": 1,
            "output": f"Failed to execute pytest: {str(e)}"
        }
