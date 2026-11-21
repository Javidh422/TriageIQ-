import re
import io
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, Reference

# --- 1. Data Cleaning & ETL Pipeline ---

COMPONENT_SYNONYMS = {
    "auth": "Auth",
    "authentication": "Auth",
    "jwt": "Auth",
    "oauth": "Auth",
    "sso": "Auth",
    "payment": "Payments",
    "payments": "Payments",
    "billing": "Payments",
    "stripe": "Payments",
    "paypal": "Payments",
    "db": "Database",
    "database": "Database",
    "postgres": "Database",
    "sql": "Database",
    "redis": "Database",
    "ui": "UI",
    "frontend": "UI",
    "front-end": "UI",
    "design": "UI",
    "css": "UI",
    "api": "API",
    "backend": "API",
    "endpoint": "API",
    "graphql": "API",
    "rest": "API"
}

SEVERITY_SYNONYMS = {
    "critical": "P1",
    "highest": "P1",
    "blocker": "P1",
    "p1": "P1",
    "high": "P2",
    "p2": "P2",
    "medium": "P3",
    "normal": "P3",
    "p3": "P3",
    "low": "P4",
    "minor": "P4",
    "trivial": "P4",
    "p4": "P4"
}

SLA_MAP = {"P1": 2.0, "P2": 4.0, "P3": 12.0, "P4": 24.0}

def normalize_component(val: Any, text_fallback: str = "") -> str:
    if pd.isna(val) or str(val).strip() == "" or str(val).lower() == "nan":
        # Attempt heuristic guess from text
        lower = text_fallback.lower()
        if any(k in lower for k in ["stripe", "pay", "card", "checkout", "billing", "invoice"]):
            return "Payments"
        if any(k in lower for k in ["jwt", "auth", "token", "login", "sso", "saml"]):
            return "Auth"
        if any(k in lower for k in ["postgres", "mysql", "database", "deadlock", "redis", "query", "sql"]):
            return "Database"
        if any(k in lower for k in ["safari", "ui", "css", "button", "drawer", "modal", "font", "theme"]):
            return "UI"
        return "API"
    
    clean = str(val).strip().lower()
    return COMPONENT_SYNONYMS.get(clean, str(val).strip().capitalize())

def normalize_severity(val: Any, text_fallback: str = "") -> str:
    if pd.isna(val) or str(val).strip() == "" or str(val).lower() == "nan":
        lower = text_fallback.lower()
        if any(k in lower for k in ["outage", "fatal", "deadlock", "500", "crash", "loss"]):
            return "P1"
        if any(k in lower for k in ["slow", "spike", "timeout", "latency", "429"]):
            return "P2"
        if any(k in lower for k in ["typo", "cosmetic", "color", "font"]):
            return "P4"
        return "P3"
    
    clean = str(val).strip().lower()
    return SEVERITY_SYNONYMS.get(clean, "P3")

def normalize_timestamp(val: Any) -> str:
    if pd.isna(val) or str(val).strip() == "":
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    val_str = str(val).strip()
    try:
        # Common formats
        parsed = pd.to_datetime(val_str)
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def run_etl_pipeline(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Cleans raw DataFrame, imputes missing values, normalizes timestamps and categories,
    flags malformed rows, and computes Data Quality Audit metrics.
    """
    total_rows_raw = len(df)
    nulls_imputed = {"component": 0, "severity": 0, "latency_ms": 0, "status": 0, "sla_target_hours": 0}
    malformed_rows = []
    
    # Standardize column names
    col_map = {}
    for col in df.columns:
        norm = col.strip().lower().replace(" ", "_")
        if norm in ["issue_title", "summary", "name"]:
            col_map[col] = "title"
        elif norm in ["desc", "details", "body"]:
            col_map[col] = "description"
        elif norm in ["service", "module", "system"]:
            col_map[col] = "component"
        elif norm in ["priority", "level", "sev"]:
            col_map[col] = "severity"
        elif norm in ["response_time", "latency", "duration", "latency(ms)"]:
            col_map[col] = "latency_ms"
        elif norm in ["timestamp", "time", "date"]:
            col_map[col] = "created_at"
        else:
            col_map[col] = norm
    
    df = df.rename(columns=col_map)
    
    required_cols = ["ticket_id", "title", "description", "component", "severity", 
                     "latency_ms", "status", "sla_target_hours", "created_at", "raw_log"]
    for col in required_cols:
        if col not in df.columns:
            df[col] = np.nan

    cleaned_records = []
    
    # Calculate baseline median latency for fallback imputation
    numeric_latencies = pd.to_numeric(df["latency_ms"], errors="coerce")
    global_median_latency = float(numeric_latencies.median()) if not np.isnan(numeric_latencies.median()) else 250.0

    for idx, row in df.iterrows():
        title = str(row.get("title", "")).strip() if not pd.isna(row.get("title")) else ""
        desc = str(row.get("description", "")).strip() if not pd.isna(row.get("description")) else ""
        text_context = f"{title} {desc}"

        # Malformed check 1: Completely empty title and description
        if not title and not desc:
            malformed_rows.append({"row_index": idx, "reason": "Empty title and description"})
            continue
        
        # If title missing, use truncated description
        if not title:
            title = desc[:60] + "..." if len(desc) > 60 else desc
            nulls_imputed["title"] = nulls_imputed.get("title", 0) + 1

        # Check Component
        raw_comp = row.get("component")
        if pd.isna(raw_comp) or str(raw_comp).strip() == "":
            nulls_imputed["component"] += 1
        comp = normalize_component(raw_comp, text_context)

        # Check Severity
        raw_sev = row.get("severity")
        if pd.isna(raw_sev) or str(raw_sev).strip() == "":
            nulls_imputed["severity"] += 1
        sev = normalize_severity(raw_sev, text_context)

        # Check Latency
        raw_latency = row.get("latency_ms")
        try:
            latency_val = float(raw_latency)
            if np.isnan(latency_val):
                latency_val = global_median_latency
                nulls_imputed["latency_ms"] += 1
            elif latency_val < 0:
                malformed_rows.append({"row_index": idx, "reason": f"Negative latency ({latency_val}ms) flagged and reset to median"})
                latency_val = global_median_latency
                nulls_imputed["latency_ms"] += 1
            elif latency_val > 1000000:
                malformed_rows.append({"row_index": idx, "reason": f"Extreme unrealistic latency ({latency_val}ms) flagged"})
                latency_val = 60000.0
        except (ValueError, TypeError):
            latency_val = global_median_latency
            nulls_imputed["latency_ms"] += 1

        # Status
        raw_status = str(row.get("status", "To Do")).strip()
        status = raw_status if raw_status in ["To Do", "In Progress", "QA Verification", "Done"] else "To Do"
        if pd.isna(row.get("status")):
            nulls_imputed["status"] += 1

        # SLA target
        sla_target = SLA_MAP.get(sev, 4.0)

        # Timestamp
        created_at = normalize_timestamp(row.get("created_at"))

        # Ticket ID
        ticket_id = str(row.get("ticket_id", "")).strip()
        if not ticket_id or ticket_id == "nan":
            ticket_id = f"TIQ-IMP-{idx+1:04d}"

        raw_log = str(row.get("raw_log", "")).strip() if not pd.isna(row.get("raw_log")) else f"Log auto-generated for {title}"

        cleaned_records.append({
            "ticket_id": ticket_id,
            "title": title,
            "description": desc,
            "component": comp,
            "severity": sev,
            "latency_ms": latency_val,
            "status": status,
            "sla_target_hours": sla_target,
            "created_at": created_at,
            "resolved_at": row.get("resolved_at") if not pd.isna(row.get("resolved_at")) else None,
            "resolution_time_hours": float(row.get("resolution_time_hours")) if not pd.isna(row.get("resolution_time_hours")) else None,
            "sla_breached": int(row.get("sla_breached", 0)) if not pd.isna(row.get("sla_breached")) else 0,
            "is_duplicate": int(row.get("is_duplicate", 0)) if not pd.isna(row.get("is_duplicate")) else 0,
            "duplicate_of": row.get("duplicate_of") if not pd.isna(row.get("duplicate_of")) else None,
            "reporter": str(row.get("reporter", "system-import@triageiq.internal")),
            "raw_log": raw_log,
            "jira_key": ticket_id
        })

    cleaned_df = pd.DataFrame(cleaned_records)
    
    # Calculate Data Quality Score
    total_cells = max(total_rows_raw * 7, 1)
    imputed_count_total = sum(nulls_imputed.values())
    malformed_count = len(malformed_rows)
    penalty = (imputed_count_total * 1.5) + (malformed_count * 5.0)
    data_quality_score_pct = max(10.0, min(100.0, round(100.0 - (penalty / total_cells * 100), 1)))

    audit_report = {
        "total_rows_raw": total_rows_raw,
        "valid_rows_retained": len(cleaned_df),
        "malformed_rows_flagged": malformed_count,
        "malformed_details": malformed_rows,
        "nulls_imputed": nulls_imputed,
        "total_nulls_imputed": imputed_count_total,
        "data_quality_score_pct": data_quality_score_pct,
        "audit_timestamp": datetime.utcnow().isoformat()
    }

    return cleaned_df, audit_report


# --- 2. TF-IDF + Cosine Similarity Duplicate Detector ---

def detect_duplicate_clusters(tickets: List[Dict[str, Any]], similarity_threshold: float = 0.35) -> List[Dict[str, Any]]:
    """
    Computes TF-IDF pairwise similarity across existing tickets to find duplicate clusters.
    """
    if len(tickets) < 2:
        return []

    texts = [f"{t.get('title', '')} {t.get('description', '')}" for t in tickets]
    vectorizer = TfidfVectorizer(stop_words='english', min_df=1, ngram_range=(1, 1))
    
    try:
        tfidf_matrix = vectorizer.fit_transform(texts)
        sim_matrix = cosine_similarity(tfidf_matrix)
    except Exception:
        return []

    duplicates = []
    n = len(tickets)

    for i in range(n):
        for j in range(i + 1, n):
            score = float(sim_matrix[i, j])
            if score >= similarity_threshold:
                t1 = tickets[i]
                t2 = tickets[j]
                duplicates.append({
                    "ticket_id_1": t1.get("ticket_id"),
                    "title_1": t1.get("title"),
                    "ticket_id_2": t2.get("ticket_id"),
                    "title_2": t2.get("title"),
                    "similarity_score": round(score, 3),
                    "component": t1.get("component"),
                    "severity": t1.get("severity")
                })
    
    return duplicates

def find_duplicate_for_text(query_text: str, existing_tickets: List[Dict[str, Any]], threshold: float = 0.35) -> Dict[str, Any]:
    """
    Given a new bug report/query text, vectorizes against existing tickets and checks for duplicates.
    """
    if not existing_tickets or not query_text.strip():
        return {"is_duplicate": False, "match": None, "similarity_score": 0.0}

    corpus = [f"{t.get('title', '')} {t.get('description', '')}" for t in existing_tickets]

    vectorizer = TfidfVectorizer(stop_words='english', min_df=1, ngram_range=(1, 1))
    try:
        tfidf_corpus = vectorizer.fit_transform(corpus)
        tfidf_query = vectorizer.transform([query_text])
        scores = cosine_similarity(tfidf_query, tfidf_corpus).flatten()
        max_idx = int(np.argmax(scores))
        best_score = float(scores[max_idx])

        matched_ticket = existing_tickets[max_idx]
        if best_score >= threshold:
            return {
                "is_duplicate": True,
                "similarity_score": round(best_score, 3),
                "matched_ticket_id": matched_ticket.get("ticket_id"),
                "matched_title": matched_ticket.get("title"),
                "matched_component": matched_ticket.get("component"),
                "matched_severity": matched_ticket.get("severity")
            }
        else:
            return {
                "is_duplicate": False,
                "similarity_score": round(best_score, 3),
                "matched_ticket_id": matched_ticket.get("ticket_id") if best_score > 0.20 else None,
                "matched_title": matched_ticket.get("title") if best_score > 0.20 else None
            }
    except Exception:
        return {"is_duplicate": False, "similarity_score": 0.0, "matched_ticket_id": None}


# --- 3. Statistical Anomaly & Data Mining Engine ---

def detect_statistical_anomalies(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Surfaces latency spikes (Z-score & IQR), SLA breach hotspots, and peak failure modules.
    """
    if df.empty or "latency_ms" not in df.columns:
        return {"latency_anomalies": [], "component_breakdown": {}, "sla_breach_rate": 0.0, "hotspots": []}

    # Convert numeric latency
    latencies = pd.to_numeric(df["latency_ms"], errors="coerce").dropna()
    mean_lat = float(latencies.mean()) if not latencies.empty else 0.0
    std_lat = float(latencies.std()) if not latencies.empty and len(latencies) > 1 else 1.0

    # IQR method
    q25 = float(latencies.quantile(0.25)) if not latencies.empty else 0.0
    q75 = float(latencies.quantile(0.75)) if not latencies.empty else 0.0
    iqr = q75 - q25
    iqr_upper_bound = q75 + (1.5 * iqr)

    latency_anomalies = []
    for _, row in df.iterrows():
        try:
            val = float(row.get("latency_ms", 0))
            z_score = (val - mean_lat) / std_lat if std_lat > 0 else 0
            if z_score >= 1.95 or val > iqr_upper_bound:
                latency_anomalies.append({
                    "ticket_id": row.get("ticket_id"),
                    "title": row.get("title"),
                    "component": row.get("component"),
                    "latency_ms": round(val, 1),
                    "z_score": round(z_score, 2),
                    "iqr_upper_bound": round(iqr_upper_bound, 1),
                    "severity": row.get("severity")
                })
        except (ValueError, TypeError):
            continue

    # Component breakdown & hotspot identification
    comp_counts = df["component"].value_counts().to_dict()
    total_tickets = len(df)
    
    # SLA breaches
    breached_count = int(df["sla_breached"].sum()) if "sla_breached" in df.columns else 0
    sla_breach_rate = round((breached_count / total_tickets * 100), 1) if total_tickets > 0 else 0.0

    # SLA breach rate by component
    breaches_by_comp = {}
    if "sla_breached" in df.columns and "component" in df.columns:
        breaches_by_comp = df[df["sla_breached"] == 1]["component"].value_counts().to_dict()

    hotspots = []
    for comp, count in comp_counts.items():
        comp_breaches = breaches_by_comp.get(comp, 0)
        p1_count = len(df[(df["component"] == comp) & (df["severity"] == "P1")])
        hotspots.append({
            "component": comp,
            "total_defects": count,
            "percentage_of_all": round(count / total_tickets * 100, 1),
            "p1_critical_count": p1_count,
            "sla_breaches": comp_breaches,
            "risk_level": "High" if (p1_count >= 2 or comp_breaches >= 2) else ("Medium" if count >= 4 else "Low")
        })

    hotspots.sort(key=lambda x: (x["p1_critical_count"], x["total_defects"]), reverse=True)

    return {
        "mean_latency_ms": round(mean_lat, 1),
        "std_latency_ms": round(std_lat, 1),
        "iqr_upper_bound_ms": round(iqr_upper_bound, 1),
        "latency_anomalies_count": len(latency_anomalies),
        "latency_anomalies": latency_anomalies,
        "component_breakdown": comp_counts,
        "total_tickets": total_tickets,
        "sla_breach_rate_pct": sla_breach_rate,
        "total_sla_breaches": breached_count,
        "hotspots": hotspots
    }


# --- 4. AI Defect Triage & Jira Ticket Generator ---

def ai_triage_and_generate_jira(raw_text: str, existing_tickets: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Accepts raw user complaint or error log, classifies component and severity,
    identifies duplicate bug reports, and builds a standard Jira REST API v3 JSON payload.
    """
    if not existing_tickets:
        existing_tickets = []

    text_lower = raw_text.lower()

    # 1. Component Prediction
    comp_scores = {
        "Payments": sum(k in text_lower for k in ["stripe", "paypal", "checkout", "payment", "card", "billing", "3d-secure", "charge", "refund", "invoice"]),
        "Auth": sum(k in text_lower for k in ["jwt", "token", "login", "oauth", "sso", "saml", "okta", "unauthorized", "401", "session", "logout", "auth"]),
        "Database": sum(k in text_lower for k in ["deadlock", "postgres", "sql", "redis", "cache", "pool", "query", "database", "replica", "table", "lock"]),
        "UI": sum(k in text_lower for k in ["safari", "css", "render", "button", "drawer", "modal", "flicker", "theme", "dark mode", "font", "swipe", "layout"]),
        "API": sum(k in text_lower for k in ["graphql", "endpoint", "rest", "429", "500", "cors", "webhook", "pagination", "cursor", "json", "heap", "payload"])
    }
    predicted_comp = max(comp_scores, key=comp_scores.get)
    if comp_scores[predicted_comp] == 0:
        predicted_comp = "API"

    # 2. Severity Prediction
    p1_triggers = ["outage", "deadlock", "500", "fatal", "crash", "data loss", "payment failing", "connection pool exhausted", "critical", "down"]
    p2_triggers = ["timeout", "slow", "latency", "429", "rate limit", "memory leak", "heap", "replication lag", "high", "expired"]
    p4_triggers = ["typo", "cosmetic", "color", "font weight", "dark mode toggle", "padding", "minor", "trivial"]

    if any(k in text_lower for k in p1_triggers):
        predicted_sev = "P1"
        priority_name = "Highest"
    elif any(k in text_lower for k in p2_triggers):
        predicted_sev = "P2"
        priority_name = "High"
    elif any(k in text_lower for k in p4_triggers):
        predicted_sev = "P4"
        priority_name = "Low"
    else:
        predicted_sev = "P3"
        priority_name = "Medium"

    # 3. Duplicate Detection
    dup_result = find_duplicate_for_text(raw_text, existing_tickets)

    # 4. Generate structured summary & root cause hypothesis
    # Clean up first sentence or make concise summary
    clean_first_line = raw_text.strip().split("\n")[0][:80]
    summary = f"[{predicted_comp}] {clean_first_line}" if not clean_first_line.startswith("[") else clean_first_line

    root_cause = ""
    if predicted_comp == "Payments":
        root_cause = "Potential gateway API timeout, unhandled 500 response from payment provider, or missing webhook signature validation."
    elif predicted_comp == "Database":
        root_cause = "Contention on database connection pool, unindexed queries causing table locks, or Redis cache eviction cascade."
    elif predicted_comp == "Auth":
        root_cause = "Token signature expiration mismatch, clock skew on JWT validation, or popup-blocker restrictions in browser sandbox."
    elif predicted_comp == "UI":
        root_cause = "Browser-specific CSS rendering divergence (e.g. WebKit backdrop-filter), or state hydration desynchronization."
    else:
        root_cause = "Upstream microservice failure, rate limiting threshold exceeded, or unbounded memory allocation during response streaming."

    steps_to_reproduce = (
        f"1. Open application client and authenticate.\n"
        f"2. Navigate to {predicted_comp} workflow.\n"
        f"3. Execute scenario: '{clean_first_line}'.\n"
        f"4. Observe returned response status and console error logs."
    )

    expected_result = f"{predicted_comp} service executes smoothly within normal latency bounds (<350ms) with zero unhandled exceptions."
    actual_result = f"Action triggers error or latency anomaly: {raw_text[:150]}..."

    # 5. Jira REST API v3 Payload (Compliant with Jira Cloud REST v3 ADF specification)
    jira_v3_payload = {
        "fields": {
            "project": {
                "key": "TIQ"
            },
            "summary": summary,
            "issuetype": {
                "name": "Bug"
            },
            "priority": {
                "name": priority_name
            },
            "labels": [
                "triageiq-ai",
                predicted_comp.lower(),
                predicted_sev.lower()
            ],
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "Generated by TriageIQ AI Defect Triage Engine.", "marks": [{"type": "strong"}]}
                        ]
                    },
                    {
                        "type": "heading",
                        "attrs": {"level": 3},
                        "content": [{"type": "text", "text": "Observed Defect / Error Details"}]
                    },
                    {
                        "type": "codeBlock",
                        "attrs": {"language": "text"},
                        "content": [{"type": "text", "text": raw_text}]
                    },
                    {
                        "type": "heading",
                        "attrs": {"level": 3},
                        "content": [{"type": "text", "text": "Steps to Reproduce"}]
                    },
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": steps_to_reproduce}]
                    },
                    {
                        "type": "heading",
                        "attrs": {"level": 3},
                        "content": [{"type": "text", "text": "Root Cause Hypothesis"}]
                    },
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": root_cause}]
                    }
                ]
            },
            "environment": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": f"Component: {predicted_comp} | Predicted Severity: {predicted_sev}"}]
                    }
                ]
            }
        }
    }

    return {
        "summary": summary,
        "component": predicted_comp,
        "severity": predicted_sev,
        "priority": priority_name,
        "sla_target_hours": SLA_MAP.get(predicted_sev, 4.0),
        "steps_to_reproduce": steps_to_reproduce,
        "expected_result": expected_result,
        "actual_result": actual_result,
        "root_cause_hypothesis": root_cause,
        "duplicate_detection": dup_result,
        "jira_v3_payload": jira_v3_payload
    }


# --- 5. Styled Microsoft Excel MIS Report Export (openpyxl) ---

def generate_styled_excel_mis(df: pd.DataFrame, anomalies_info: Dict[str, Any]) -> io.BytesIO:
    """
    Builds a professional, multi-tab Microsoft Excel MIS Report (.xlsx) using openpyxl:
    - Tab 1: Executive_Summary with KPI formulas (COUNTIF, AVERAGE) and embedded BarChart
    - Tab 2: SLA_and_Anomalies highlighting breached SLAs & Z-score latency anomalies
    - Tab 3: Cleaned_Tickets_Data with styled slate headers, zebra striping, conditional severity fills
    """
    wb = openpyxl.Workbook()
    # Default sheet
    ws_exec = wb.active
    ws_exec.title = "Executive_Summary"
    ws_sla = wb.create_sheet(title="SLA_and_Anomalies")
    ws_data = wb.create_sheet(title="Cleaned_Tickets_Data")

    # Styling definitions (Executive Slate Theme)
    font_title = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
    font_section = Font(name="Calibri", size=12, bold=True, color="1E293B")
    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    font_bold = Font(name="Calibri", size=11, bold=True, color="000000")
    font_regular = Font(name="Calibri", size=10, color="000000")
    font_muted = Font(name="Calibri", size=9, italic=True, color="64748B")

    fill_dark_slate = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    fill_slate_blue = PatternFill(start_color="334155", end_color="334155", fill_type="solid")
    fill_accent_blue = PatternFill(start_color="0284C7", end_color="0284C7", fill_type="solid")
    fill_zebra_light = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    fill_red_alert = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
    fill_orange_alert = PatternFill(start_color="FFEDD5", end_color="FFEDD5", fill_type="solid")
    fill_yellow_alert = PatternFill(start_color="FEF9C3", end_color="FEF9C3", fill_type="solid")
    fill_green_ok = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")

    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    # ================= TAB 3: Cleaned_Tickets_Data =================
    data_headers = [
        "Ticket ID", "Title", "Component", "Severity", "Latency (ms)", 
        "Status", "SLA Target (hrs)", "Resolution Time (hrs)", "SLA Breached", "Duplicate Of", "Reporter"
    ]
    
    # Write headers
    for col_idx, h in enumerate(data_headers, 1):
        cell = ws_data.cell(row=1, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_dark_slate
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border
    ws_data.row_dimensions[1].height = 25

    total_data_rows = len(df)
    for r_idx, row in df.iterrows():
        excel_row = r_idx + 2
        ws_data.row_dimensions[excel_row].height = 20
        is_even = (r_idx % 2 == 0)
        row_fill = fill_zebra_light if is_even else PatternFill(fill_type=None)

        ticket_id = str(row.get("ticket_id", ""))
        title = str(row.get("title", ""))
        component = str(row.get("component", ""))
        severity = str(row.get("severity", ""))
        latency = float(row.get("latency_ms", 0.0))
        status = str(row.get("status", "To Do"))
        sla_target = float(row.get("sla_target_hours", 4.0))
        res_time = row.get("resolution_time_hours")
        res_val = float(res_time) if res_time is not None and not pd.isna(res_time) else ""
        sla_breached = int(row.get("sla_breached", 0))
        dup_of = str(row.get("duplicate_of", "")) if not pd.isna(row.get("duplicate_of")) else ""
        reporter = str(row.get("reporter", ""))

        values = [ticket_id, title, component, severity, latency, status, sla_target, res_val, sla_breached, dup_of, reporter]

        for col_idx, val in enumerate(values, 1):
            cell = ws_data.cell(row=excel_row, column=col_idx, value=val)
            cell.font = font_regular
            cell.border = thin_border
            cell.fill = row_fill

            # Formatting
            if col_idx in [1, 3, 4, 6, 9]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx in [5, 7, 8]:
                cell.alignment = Alignment(horizontal="right", vertical="center")
                if col_idx == 5:
                    cell.number_format = '#,##0.0'
                else:
                    cell.number_format = '0.0'
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

            # Conditional formatting for severity
            if col_idx == 4:
                if severity == "P1":
                    cell.fill = fill_red_alert
                    cell.font = Font(name="Calibri", size=10, bold=True, color="991B1B")
                elif severity == "P2":
                    cell.fill = fill_orange_alert
                    cell.font = Font(name="Calibri", size=10, bold=True, color="9A3412")
                elif severity == "P3":
                    cell.fill = fill_yellow_alert
                    cell.font = Font(name="Calibri", size=10, bold=True, color="854D0E")
                elif severity == "P4":
                    cell.fill = fill_green_ok
                    cell.font = Font(name="Calibri", size=10, bold=True, color="166534")

    # Auto-adjust column widths
    for col in ws_data.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws_data.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)

    # ================= TAB 2: SLA_and_Anomalies =================
    ws_sla.row_dimensions[1].height = 25
    sla_headers = ["Ticket ID", "Title", "Component", "Severity", "Latency (ms)", "SLA Breached", "Anomaly Reason"]
    for col_idx, h in enumerate(sla_headers, 1):
        cell = ws_sla.cell(row=1, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = PatternFill(start_color="991B1B", end_color="991B1B", fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    sla_row_counter = 2
    for r_idx, row in df.iterrows():
        is_breach = int(row.get("sla_breached", 0)) == 1
        lat_val = float(row.get("latency_ms", 0.0))
        mean_lat = anomalies_info.get("mean_latency_ms", 1000.0)
        std_lat = anomalies_info.get("std_latency_ms", 500.0)
        z = (lat_val - mean_lat) / std_lat if std_lat > 0 else 0
        is_latency_spike = (z >= 1.95)

        if is_breach or is_latency_spike:
            reasons = []
            if is_breach:
                reasons.append("SLA Target Exceeded")
            if is_latency_spike:
                reasons.append(f"Latency Spike (Z-Score: {round(z, 1)}, {round(lat_val)}ms)")

            reason_str = " | ".join(reasons)
            ws_sla.row_dimensions[sla_row_counter].height = 20

            values = [
                str(row.get("ticket_id")),
                str(row.get("title")),
                str(row.get("component")),
                str(row.get("severity")),
                lat_val,
                "YES" if is_breach else "NO",
                reason_str
            ]

            for col_idx, val in enumerate(values, 1):
                cell = ws_sla.cell(row=sla_row_counter, column=col_idx, value=val)
                cell.font = font_regular
                cell.border = thin_border
                cell.fill = fill_red_alert if is_breach else fill_orange_alert
                if col_idx in [1, 3, 4, 6]:
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                elif col_idx == 5:
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                    cell.number_format = '#,##0.0'
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

            sla_row_counter += 1

    for col in ws_sla.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws_sla.column_dimensions[col_letter].width = min(max(max_len + 3, 14), 50)

    # ================= TAB 1: Executive_Summary =================
    # Banner
    ws_exec.merge_cells("A1:G1")
    banner = ws_exec["A1"]
    banner.value = "TRIAGEIQ — OPERATIONAL DEFECT & SLA MIS REPORT"
    banner.font = font_title
    banner.fill = fill_dark_slate
    banner.alignment = Alignment(horizontal="center", vertical="center")
    ws_exec.row_dimensions[1].height = 35

    # Sub-banner timestamp
    ws_exec.merge_cells("A2:G2")
    sub = ws_exec["A2"]
    sub.value = f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} | Automated Data Pipeline"
    sub.font = font_muted
    sub.alignment = Alignment(horizontal="center", vertical="center")
    ws_exec.row_dimensions[2].height = 18

    # KPI Summary Cards Table
    ws_exec.cell(row=4, column=1, value="Operational KPI Overview").font = font_section

    kpi_headers = ["Metric Name", "Value", "Benchmark Formula", "Notes"]
    for col_idx, h in enumerate(kpi_headers, 1):
        cell = ws_exec.cell(row=5, column=col_idx, value=h)
        cell.font = font_header
        cell.fill = fill_slate_blue
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border
    ws_exec.row_dimensions[5].height = 22

    last_data_row = total_data_rows + 1
    kpis = [
        ("Total Tickets Ingested", f"=COUNTA(Cleaned_Tickets_Data!A2:A{last_data_row})", "COUNTA()", "Live Count"),
        ("Critical Defects (P1)", f'=COUNTIF(Cleaned_Tickets_Data!D2:D{last_data_row}, "P1")', 'COUNTIF(..., "P1")', "High priority outage/blocker"),
        ("Major Defects (P2)", f'=COUNTIF(Cleaned_Tickets_Data!D2:D{last_data_row}, "P2")', 'COUNTIF(..., "P2")', "Performance or timeout defects"),
        ("Medium Defects (P3)", f'=COUNTIF(Cleaned_Tickets_Data!D2:D{last_data_row}, "P3")', 'COUNTIF(..., "P3")', "Normal priority functional defects"),
        ("Minor Defects (P4)", f'=COUNTIF(Cleaned_Tickets_Data!D2:D{last_data_row}, "P4")', 'COUNTIF(..., "P4")', "Cosmetic & UI issues"),
        ("Average Latency (ms)", f"=AVERAGE(Cleaned_Tickets_Data!E2:E{last_data_row})", "AVERAGE()", "Mean service response time"),
        ("Total SLA Breaches", f"=SUM(Cleaned_Tickets_Data!I2:I{last_data_row})", "SUM()", "Tickets breaching SLA target"),
        ("SLA Compliance Rate (%)", f'=ROUND((1 - (SUM(Cleaned_Tickets_Data!I2:I{last_data_row}) / COUNTA(Cleaned_Tickets_Data!A2:A{last_data_row}))) * 100, 1)', "1 - (Breaches/Total)", "Target >= 95.0%")
    ]

    for idx, (m_name, formula, bmark, notes) in enumerate(kpis, 6):
        ws_exec.row_dimensions[idx].height = 20
        c1 = ws_exec.cell(row=idx, column=1, value=m_name)
        c2 = ws_exec.cell(row=idx, column=2, value=formula)
        c3 = ws_exec.cell(row=idx, column=3, value=bmark)
        c4 = ws_exec.cell(row=idx, column=4, value=notes)

        for c in [c1, c2, c3, c4]:
            c.font = font_regular
            c.border = thin_border
        c1.font = font_bold
        c2.alignment = Alignment(horizontal="right", vertical="center")
        c3.alignment = Alignment(horizontal="center", vertical="center")

    # Severity Distribution Table for openpyxl Chart Reference
    ws_exec.cell(row=16, column=1, value="Defect Breakdown by Severity").font = font_section

    ws_exec.cell(row=17, column=1, value="Severity").font = font_header
    ws_exec.cell(row=17, column=1).fill = fill_accent_blue
    ws_exec.cell(row=17, column=1).border = thin_border
    ws_exec.cell(row=17, column=2, value="Incident Count").font = font_header
    ws_exec.cell(row=17, column=2).fill = fill_accent_blue
    ws_exec.cell(row=17, column=2).border = thin_border

    severities = ["P1", "P2", "P3", "P4"]
    for i, s in enumerate(severities, 18):
        ws_exec.row_dimensions[i].height = 20
        cell_s = ws_exec.cell(row=i, column=1, value=s)
        cell_val = ws_exec.cell(row=i, column=2, value=f'=COUNTIF(Cleaned_Tickets_Data!D2:D{last_data_row}, "{s}")')
        cell_s.font = font_bold
        cell_s.border = thin_border
        cell_s.alignment = Alignment(horizontal="center", vertical="center")
        cell_val.font = font_regular
        cell_val.border = thin_border
        cell_val.alignment = Alignment(horizontal="right", vertical="center")

    # Embedded openpyxl BarChart
    chart = BarChart()
    chart.type = "col"
    chart.style = 10
    chart.title = "Incident Distribution by Severity"
    chart.y_axis.title = "Count of Tickets"
    chart.x_axis.title = "Severity Level"
    chart.width = 15
    chart.height = 10

    data_ref = Reference(ws_exec, min_col=2, min_row=17, max_row=21)
    cats_ref = Reference(ws_exec, min_col=1, min_row=18, max_row=21)
    chart.add_data(data_ref, titles_from_data=True)
    chart.set_categories(cats_ref)
    chart.legend = None

    ws_exec.add_chart(chart, "D16")

    # Column widths for Tab 1
    ws_exec.column_dimensions["A"].width = 28
    ws_exec.column_dimensions["B"].width = 18
    ws_exec.column_dimensions["C"].width = 24
    ws_exec.column_dimensions["D"].width = 24
    ws_exec.column_dimensions["E"].width = 15
    ws_exec.column_dimensions["F"].width = 15
    ws_exec.column_dimensions["G"].width = 15

    # Save to BytesIO stream
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output
