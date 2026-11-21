import os
import sqlite3
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "triageiq.db")

RAW_SEED_INCIDENTS = [
    {
        "ticket_id": "TIQ-1001",
        "title": "Stripe checkout failing with 500 Internal Server Error",
        "description": "Users report checkout page spins indefinitely and returns HTTP 500 when processing Visa cards via Stripe gateway.",
        "component": "Payments",
        "severity": "P1",
        "latency_ms": 14500,  # Latency spike anomaly
        "status": "In Progress",
        "sla_target_hours": 2.0,
        "created_at": "2026-11-20 08:30:00",
        "resolved_at": None,
        "resolution_time_hours": 3.5,  # Breached
        "sla_breached": 1,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "alex.support@company.com",
        "raw_log": "ERROR: stripe.error.APIConnectionError: Connection reset by peer in payment_controller.py:142",
        "jira_key": "TIQ-101"
    },
    {
        "ticket_id": "TIQ-1002",
        "title": "Payment gateway 500 internal server error during checkout",
        "description": "Customer unable to complete purchase. Receives 500 error on Stripe payment charge API call.",
        "component": "Payments",
        "severity": "P1",
        "latency_ms": 13900,  # Latency spike
        "status": "To Do",
        "sla_target_hours": 2.0,
        "created_at": "2026-11-20 08:45:12",
        "resolved_at": None,
        "resolution_time_hours": None,
        "sla_breached": 1,
        "is_duplicate": 1,  # Semantic duplicate of TIQ-1001
        "duplicate_of": "TIQ-1001",
        "reporter": "sarah.qa@company.com",
        "raw_log": "POST /api/v1/charge returned 500 Internal Server Error with timeout from upstream gateway",
        "jira_key": "TIQ-102"
    },
    {
        "ticket_id": "TIQ-1003",
        "title": "Postgres connection pool exhausted on analytics dashboard query",
        "description": "Deadlocks observed on DB master node when heavy export queries run simultaneously. Max pool size (50) exceeded.",
        "component": "Database",
        "severity": "P1",
        "latency_ms": 18200,  # Huge latency spike
        "status": "QA Verification",
        "sla_target_hours": 2.0,
        "created_at": "2026-11-20 09:12:00",
        "resolved_at": "2026-11-20 10:45:00",
        "resolution_time_hours": 1.55,
        "sla_breached": 0,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "devops-alert@company.com",
        "raw_log": "FATAL: remaining connection slots are reserved for non-replication superuser connections (PG::ConnectionBad)",
        "jira_key": "TIQ-103"
    },
    {
        "ticket_id": "TIQ-1004",
        "title": "JWT Auth Token validation failing after 15 minutes refresh",
        "description": "Users repeatedly logged out mid-session. Auth header signature verification raises ExpiredSignatureError prematurely.",
        "component": "Auth",
        "severity": "P2",
        "latency_ms": 320,
        "status": "In Progress",
        "sla_target_hours": 4.0,
        "created_at": "2026-11-20 09:40:00",
        "resolved_at": None,
        "resolution_time_hours": 5.2,
        "sla_breached": 1,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "security-bot@company.com",
        "raw_log": "jwt.exceptions.ExpiredSignatureError: Signature has expired at verify_token()",
        "jira_key": "TIQ-104"
    },
    {
        "ticket_id": "TIQ-1005",
        "title": "Token refresh expiration causes unexpected session logout",
        "description": "Active users are kicked out to login page because JWT refresh token expiry is not renewing the access token correctly.",
        "component": "Auth",
        "severity": "P2",
        "latency_ms": 310,
        "status": "To Do",
        "sla_target_hours": 4.0,
        "created_at": "2026-11-20 10:05:30",
        "resolved_at": None,
        "resolution_time_hours": None,
        "sla_breached": 0,
        "is_duplicate": 1,  # Semantic duplicate of TIQ-1004
        "duplicate_of": "TIQ-1004",
        "reporter": "frontend-dev@company.com",
        "raw_log": "HTTP 401 Unauthorized returned from /api/auth/refresh",
        "jira_key": "TIQ-105"
    },
    {
        "ticket_id": "TIQ-1006",
        "title": "GraphQL inventory query latency exceeds 3000ms threshold",
        "description": "High latency on /graphql query ProductsWithStock due to N+1 problem on warehouse inventory resolution.",
        "component": "API",
        "severity": "P2",
        "latency_ms": 4800,  # Latency anomaly
        "status": "In Progress",
        "sla_target_hours": 4.0,
        "created_at": "2026-11-20 10:30:15",
        "resolved_at": None,
        "resolution_time_hours": 4.8,
        "sla_breached": 1,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "sre-monitor@company.com",
        "raw_log": "SLOW_QUERY: query ProductsWithStock execution time 4812ms (threshold 800ms)",
        "jira_key": "TIQ-106"
    },
    {
        "ticket_id": "TIQ-1007",
        "title": "Safari 17 rendering glitch on modal drawer blur backdrop",
        "description": "Backdrop-filter CSS property causes flickering and white artifacting in Safari on macOS Sonoma.",
        "component": "UI",
        "severity": "P3",
        "latency_ms": 110,
        "status": "Done",
        "sla_target_hours": 12.0,
        "created_at": "2026-11-20 11:00:00",
        "resolved_at": "2026-11-20 16:30:00",
        "resolution_time_hours": 5.5,
        "sla_breached": 0,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "design-qa@company.com",
        "raw_log": "WebKit CSS repaint lag reported on .drawer-backdrop blur(20px)",
        "jira_key": "TIQ-107"
    },
    {
        "ticket_id": "TIQ-1008",
        "title": "Webhook delivery failure to external CRM endpoints (HTTP 429)",
        "description": "Customer webhook deliveries failing with HTTP 429 Too Many Requests due to lack of exponential backoff retry.",
        "component": "API",
        "severity": "P2",
        "latency_ms": 780,
        "status": "To Do",
        "sla_target_hours": 4.0,
        "created_at": "2026-11-20 11:25:00",
        "resolved_at": None,
        "resolution_time_hours": None,
        "sla_breached": 0,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "integrations-lead@company.com",
        "raw_log": "Webhook dispatcher encountered HTTP 429 rate limit from api.hubspot.com/v3",
        "jira_key": "TIQ-108"
    },
    {
        "ticket_id": "TIQ-1009",
        "title": "Deadlock on order_items table during concurrent flash sale",
        "description": "Simultaneous row-level locks on stock reservation causes transaction rollback in order service.",
        "component": "Database",
        "severity": "P1",
        "latency_ms": 16400,  # Huge latency spike
        "status": "In Progress",
        "sla_target_hours": 2.0,
        "created_at": "2026-11-20 11:55:00",
        "resolved_at": None,
        "resolution_time_hours": 2.8,
        "sla_breached": 1,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "db-admin@company.com",
        "raw_log": "ERROR: deadlock detected; Process 3412 waits for ExclusiveLock on tuple (14, 8) of relation order_items",
        "jira_key": "TIQ-109"
    },
    {
        "ticket_id": "TIQ-1010",
        "title": "Flash sale concurrent transactions crashing order_items with deadlock",
        "description": "High traffic checkout causes PostgreSQL deadlock error in order_items table locking inventory.",
        "component": "Database",
        "severity": "P1",
        "latency_ms": 15800,  # Latency anomaly
        "status": "To Do",
        "sla_target_hours": 2.0,
        "created_at": "2026-11-20 12:10:00",
        "resolved_at": None,
        "resolution_time_hours": None,
        "sla_breached": 1,
        "is_duplicate": 1,  # Semantic duplicate of TIQ-1009
        "duplicate_of": "TIQ-1009",
        "reporter": "alex.support@company.com",
        "raw_log": "SQLSTATE[40P01]: Deadlock detected: 7 ERROR: deadlock detected on order_items",
        "jira_key": "TIQ-110"
    },
    {
        "ticket_id": "TIQ-1011",
        "title": "Dark mode toggle fails to persist preference in local storage",
        "description": "When reloading page, theme resets to light mode. LocalStorage key 'theme-pref' is overwritten by default state.",
        "component": "UI",
        "severity": "P4",
        "latency_ms": 85,
        "status": "Done",
        "sla_target_hours": 24.0,
        "created_at": "2026-11-20 12:40:00",
        "resolved_at": "2026-11-20 15:10:00",
        "resolution_time_hours": 2.5,
        "sla_breached": 0,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "community-user@company.com",
        "raw_log": "UI state hydration overwriting window.localStorage.themePreference",
        "jira_key": "TIQ-111"
    },
    {
        "ticket_id": "TIQ-1012",
        "title": "OAuth2 Google login button non-responsive on Firefox ESR",
        "description": "Popup window blocked silently because login trigger is not directly inside user click synthetic event.",
        "component": "Auth",
        "severity": "P2",
        "latency_ms": 290,
        "status": "In Progress",
        "sla_target_hours": 4.0,
        "created_at": "2026-11-20 13:15:00",
        "resolved_at": None,
        "resolution_time_hours": 4.3,
        "sla_breached": 1,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "qa-tester2@company.com",
        "raw_log": "SecurityError: The operation is insecure. Window.open blocked by Firefox popup manager",
        "jira_key": "TIQ-112"
    },
    {
        "ticket_id": "TIQ-1013",
        "title": "Stripe 3D-Secure 2.0 webhook verification signature mismatch",
        "description": "Payload signature verification fails on webhook handler due to raw body parser json stringification differences.",
        "component": "Payments",
        "severity": "P1",
        "latency_ms": 950,
        "status": "QA Verification",
        "sla_target_hours": 2.0,
        "created_at": "2026-11-20 13:45:00",
        "resolved_at": "2026-11-20 15:15:00",
        "resolution_time_hours": 1.5,
        "sla_breached": 0,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "finance-ops@company.com",
        "raw_log": "stripe.error.SignatureVerificationError: No signatures found matching the expected signature for payload",
        "jira_key": "TIQ-113"
    },
    {
        "ticket_id": "TIQ-1014",
        "title": "CSV customer export returns blank file for accounts with >50k rows",
        "description": "Memory limit exceeded on worker process during stream rendering. Node.js heap limit reached.",
        "component": "API",
        "severity": "P2",
        "latency_ms": 9200,  # Latency anomaly
        "status": "In Progress",
        "sla_target_hours": 4.0,
        "created_at": "2026-11-20 14:10:00",
        "resolved_at": None,
        "resolution_time_hours": 4.1,
        "sla_breached": 1,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "customer-success@company.com",
        "raw_log": "FATAL ERROR: Ineffective mark-compacts near heap limit Allocation failed - JavaScript heap out of memory",
        "jira_key": "TIQ-114"
    },
    {
        "ticket_id": "TIQ-1015",
        "title": "Typography font weight mismatch on pricing cards header",
        "description": "Heading uses font-weight 400 instead of SF Pro Display Semibold (600) on resolution >= 1440px.",
        "component": "UI",
        "severity": "P4",
        "latency_ms": 65,
        "status": "Done",
        "sla_target_hours": 24.0,
        "created_at": "2026-11-20 14:35:00",
        "resolved_at": "2026-11-20 18:00:00",
        "resolution_time_hours": 3.42,
        "sla_breached": 0,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "ui-designer@company.com",
        "raw_log": "CSS computed style check failed on .pricing-hero-title: 400 != 600",
        "jira_key": "TIQ-115"
    },
    {
        "ticket_id": "TIQ-1016",
        "title": "Redis cache eviction storm causing latency spike on product catalogue",
        "description": "TTL expiration synchronized across 10,000 SKUs caused sudden cache stampede to PostgreSQL backend.",
        "component": "Database",
        "severity": "P2",
        "latency_ms": 5600,  # Latency spike
        "status": "In Progress",
        "sla_target_hours": 4.0,
        "created_at": "2026-11-20 15:00:00",
        "resolved_at": None,
        "resolution_time_hours": 3.8,
        "sla_breached": 0,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "sre-lead@company.com",
        "raw_log": "Redis hit ratio dropped to 12.4%; Postgres query queue surged from 5 to 480 connections",
        "jira_key": "TIQ-116"
    },
    {
        "ticket_id": "TIQ-1017",
        "title": "Product catalog cache stampede slowing down database queries",
        "description": "Simultaneous cache expiry on inventory catalogue triggers massive latency spikes on db master.",
        "component": "Database",
        "severity": "P2",
        "latency_ms": 5400,  # Latency spike
        "status": "To Do",
        "sla_target_hours": 4.0,
        "created_at": "2026-11-20 15:20:00",
        "resolved_at": None,
        "resolution_time_hours": None,
        "sla_breached": 0,
        "is_duplicate": 1,  # Semantic duplicate of TIQ-1016
        "duplicate_of": "TIQ-1016",
        "reporter": "performance-qa@company.com",
        "raw_log": "Database connection saturation due to Redis TTL key expiration wave",
        "jira_key": "TIQ-117"
    },
    {
        "ticket_id": "TIQ-1018",
        "title": "SAML Single Sign-On certificate rotation expired",
        "description": "Okta enterprise enterprise users receive 'Invalid SAML Response' following annual cert renewal.",
        "component": "Auth",
        "severity": "P1",
        "latency_ms": 420,
        "status": "QA Verification",
        "sla_target_hours": 2.0,
        "created_at": "2026-11-20 15:45:00",
        "resolved_at": "2026-11-20 17:10:00",
        "resolution_time_hours": 1.42,
        "sla_breached": 0,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "enterprise-support@company.com",
        "raw_log": "saml2.exceptions.ValidationError: Certificate thumbprint mismatch on Okta metadata XML",
        "jira_key": "TIQ-118"
    },
    {
        "ticket_id": "TIQ-1019",
        "title": "Apple Pay sheet fails to open on iOS Safari 17.2",
        "description": "window.ApplePaySession.canMakePayments returns false because merchant validation certificate domain binding is missing subdomain.",
        "component": "Payments",
        "severity": "P2",
        "latency_ms": 310,
        "status": "In Progress",
        "sla_target_hours": 4.0,
        "created_at": "2026-11-20 16:15:00",
        "resolved_at": None,
        "resolution_time_hours": 4.7,
        "sla_breached": 1,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "mobile-qa@company.com",
        "raw_log": "ApplePaySession error: Merchant domain validation failed with status 400 on api.apple-pay.com",
        "jira_key": "TIQ-119"
    },
    {
        "ticket_id": "TIQ-1020",
        "title": "REST API pagination meta cursor returning duplicate items on page 3",
        "description": "Cursor-based pagination query lacks secondary tie-breaker order column, causing unstable sorting on duplicate timestamps.",
        "component": "API",
        "severity": "P3",
        "latency_ms": 380,
        "status": "Done",
        "sla_target_hours": 12.0,
        "created_at": "2026-11-20 16:45:00",
        "resolved_at": "2026-11-20 22:00:00",
        "resolution_time_hours": 5.25,
        "sla_breached": 0,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "external-dev@client.com",
        "raw_log": "SELECT * FROM events WHERE created_at <= ? ORDER BY created_at DESC LIMIT 20 yields duplicate ID #94102",
        "jira_key": "TIQ-120"
    },
    {
        "ticket_id": "TIQ-1021",
        "title": "Pagination cursor order missing tie-breaker yields duplicate records",
        "description": "Users see identical rows repeated when clicking Next Page because API cursor pagination is not deterministically ordered.",
        "component": "API",
        "severity": "P3",
        "latency_ms": 395,
        "status": "To Do",
        "sla_target_hours": 12.0,
        "created_at": "2026-11-20 17:10:00",
        "resolved_at": None,
        "resolution_time_hours": None,
        "sla_breached": 0,
        "is_duplicate": 1,  # Semantic duplicate of TIQ-1020
        "duplicate_of": "TIQ-1020",
        "reporter": "alex.support@company.com",
        "raw_log": "Duplicate item keys detected in table grid after paginating past page 2",
        "jira_key": "TIQ-121"
    },
    {
        "ticket_id": "TIQ-1022",
        "title": "Mobile navigation drawer close gesture conflicts with iOS swipe back",
        "description": "Horizontal swipe gesture on edge triggers both native safari back history navigation and drawer sliding.",
        "component": "UI",
        "severity": "P3",
        "latency_ms": 75,
        "status": "In Progress",
        "sla_target_hours": 12.0,
        "created_at": "2026-11-20 17:35:00",
        "resolved_at": None,
        "resolution_time_hours": 8.0,
        "sla_breached": 0,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "ux-team@company.com",
        "raw_log": "Touch event touchstart clientX < 20px triggering PopStateEvent before touchmove cleanup",
        "jira_key": "TIQ-122"
    },
    {
        "ticket_id": "TIQ-1023",
        "title": "PayPal sandbox IPN webhook payload drops invoice ID field",
        "description": "Missing custom data field in deserializer causes PayPal payments to remain in 'pending_approval' indefinitely.",
        "component": "Payments",
        "severity": "P2",
        "latency_ms": 440,
        "status": "To Do",
        "sla_target_hours": 4.0,
        "created_at": "2026-11-20 18:00:00",
        "resolved_at": None,
        "resolution_time_hours": None,
        "sla_breached": 0,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "billing-support@company.com",
        "raw_log": "KeyError: 'invoice_id' in paypal_ipn_parser.py:58",
        "jira_key": "TIQ-123"
    },
    {
        "ticket_id": "TIQ-1024",
        "title": "Database replica replication lag spikes to 850 seconds under load",
        "description": "Heavy write transaction batch causes WAL sender process to throttle read replicas, triggering stale data warnings in UI.",
        "component": "Database",
        "severity": "P2",
        "latency_ms": 11500,  # Latency anomaly
        "status": "In Progress",
        "sla_target_hours": 4.0,
        "created_at": "2026-11-20 18:30:00",
        "resolved_at": None,
        "resolution_time_hours": 4.9,
        "sla_breached": 1,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "db-monitor@company.com",
        "raw_log": "CRITICAL: pg_stat_replication replay_lag = 852.4 seconds on replica-02.us-east-1",
        "jira_key": "TIQ-124"
    },
    {
        "ticket_id": "TIQ-1025",
        "title": "CORS preflight OPTIONS request rejected on staging API subdomain",
        "description": "Missing Access-Control-Allow-Origin header on OPTIONS response causes front-end fetch to fail on staging environment.",
        "component": "API",
        "severity": "P3",
        "latency_ms": 190,
        "status": "Done",
        "sla_target_hours": 12.0,
        "created_at": "2026-11-20 19:00:00",
        "resolved_at": "2026-11-20 21:15:00",
        "resolution_time_hours": 2.25,
        "sla_breached": 0,
        "is_duplicate": 0,
        "duplicate_of": None,
        "reporter": "qa-automation@company.com",
        "raw_log": "Access to fetch at 'https://staging-api.example.com' from origin 'https://app-staging.example.com' blocked by CORS policy",
        "jira_key": "TIQ-125"
    }
]

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(seed_if_empty: bool = True):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Incidents / Tickets table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            component TEXT,
            severity TEXT,
            latency_ms REAL,
            status TEXT DEFAULT 'To Do',
            sla_target_hours REAL DEFAULT 4.0,
            created_at TEXT,
            resolved_at TEXT,
            resolution_time_hours REAL,
            sla_breached INTEGER DEFAULT 0,
            is_duplicate INTEGER DEFAULT 0,
            duplicate_of TEXT,
            reporter TEXT,
            raw_log TEXT,
            jira_key TEXT
        )
    """)

    # Jira Board table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jira_board (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT UNIQUE NOT NULL,
            summary TEXT NOT NULL,
            description TEXT,
            component TEXT,
            priority TEXT,
            severity TEXT,
            status TEXT DEFAULT 'To Do',
            labels TEXT,
            steps_to_reproduce TEXT,
            root_cause_hypothesis TEXT,
            synced_at TEXT,
            jira_cloud_url TEXT,
            cloud_sync_status TEXT DEFAULT 'Local Synced'
        )
    """)

    conn.commit()

    if seed_if_empty:
        cursor.execute("SELECT COUNT(*) FROM incidents")
        count = cursor.fetchone()[0]
        if count == 0:
            seed_incidents(conn)

    conn.close()

def seed_incidents(conn: Optional[sqlite3.Connection] = None):
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    
    cursor = conn.cursor()
    cursor.execute("DELETE FROM incidents")
    cursor.execute("DELETE FROM jira_board")

    for inc in RAW_SEED_INCIDENTS:
        cursor.execute("""
            INSERT INTO incidents (
                ticket_id, title, description, component, severity, latency_ms,
                status, sla_target_hours, created_at, resolved_at,
                resolution_time_hours, sla_breached, is_duplicate, duplicate_of,
                reporter, raw_log, jira_key
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """, (
            inc["ticket_id"], inc["title"], inc["description"], inc["component"],
            inc["severity"], inc["latency_ms"], inc["status"], inc["sla_target_hours"],
            inc["created_at"], inc["resolved_at"], inc["resolution_time_hours"],
            inc["sla_breached"], inc["is_duplicate"], inc["duplicate_of"],
            inc["reporter"], inc["raw_log"], inc["jira_key"]
        ))
        
        # Populate Jira board for the seeded tickets
        priority_map = {"P1": "Highest", "P2": "High", "P3": "Medium", "P4": "Low"}
        cursor.execute("""
            INSERT INTO jira_board (
                ticket_id, summary, description, component, priority, severity,
                status, labels, steps_to_reproduce, root_cause_hypothesis,
                synced_at, cloud_sync_status
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """, (
            inc["ticket_id"],
            inc["title"],
            inc["description"],
            inc["component"],
            priority_map.get(inc["severity"], "Medium"),
            inc["severity"],
            inc["status"],
            f"triageiq-ai,{inc['component'].lower()},{inc['severity'].lower()}",
            f"1. Navigate to {inc['component']} module\n2. Trigger action related to: {inc['title']}\n3. Observe system log and behavior",
            f"Likely bottleneck or exception in {inc['component']} layer: {inc.get('raw_log', 'No log')[:100]}",
            inc["created_at"],
            "Seeded"
        ))

    conn.commit()
    if should_close:
        conn.close()

def get_all_incidents() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM incidents ORDER BY id DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def get_all_incidents_df() -> pd.DataFrame:
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT * FROM incidents", conn)
    conn.close()
    return df

def get_jira_board_tickets() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jira_board ORDER BY id DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def update_jira_ticket_status(ticket_id: str, new_status: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE jira_board SET status = ? WHERE ticket_id = ?", (new_status, ticket_id))
    cursor.execute("UPDATE incidents SET status = ? WHERE ticket_id = ?", (new_status, ticket_id))
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    return rows_affected > 0

def upsert_jira_ticket(ticket_data: Dict[str, Any]) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    ticket_id = ticket_data.get("ticket_id")
    if not ticket_id:
        cursor.execute("SELECT COUNT(*) FROM jira_board")
        count = cursor.fetchone()[0]
        ticket_id = f"TIQ-{2000 + count + 1}"
    
    cursor.execute("""
        INSERT INTO jira_board (
            ticket_id, summary, description, component, priority, severity,
            status, labels, steps_to_reproduce, root_cause_hypothesis,
            synced_at, jira_cloud_url, cloud_sync_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticket_id) DO UPDATE SET
            summary=excluded.summary,
            description=excluded.description,
            component=excluded.component,
            priority=excluded.priority,
            severity=excluded.severity,
            status=excluded.status,
            labels=excluded.labels,
            steps_to_reproduce=excluded.steps_to_reproduce,
            root_cause_hypothesis=excluded.root_cause_hypothesis,
            synced_at=excluded.synced_at,
            jira_cloud_url=excluded.jira_cloud_url,
            cloud_sync_status=excluded.cloud_sync_status
    """, (
        ticket_id,
        ticket_data.get("summary", "AI Triaged Issue"),
        ticket_data.get("description", ""),
        ticket_data.get("component", "General"),
        ticket_data.get("priority", "Medium"),
        ticket_data.get("severity", "P3"),
        ticket_data.get("status", "To Do"),
        ticket_data.get("labels", "triageiq-ai"),
        ticket_data.get("steps_to_reproduce", ""),
        ticket_data.get("root_cause_hypothesis", ""),
        datetime.utcnow().isoformat(),
        ticket_data.get("jira_cloud_url", ""),
        ticket_data.get("cloud_sync_status", "Local Synced")
    ))
    
    # Also add or update incidents table
    cursor.execute("""
        INSERT INTO incidents (
            ticket_id, title, description, component, severity, latency_ms,
            status, sla_target_hours, created_at, is_duplicate, duplicate_of,
            raw_log, jira_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticket_id) DO UPDATE SET
            title=excluded.title,
            description=excluded.description,
            component=excluded.component,
            severity=excluded.severity,
            status=excluded.status
    """, (
        ticket_id,
        ticket_data.get("summary", "AI Triaged Issue"),
        ticket_data.get("description", ""),
        ticket_data.get("component", "General"),
        ticket_data.get("severity", "P3"),
        ticket_data.get("latency_ms", 250.0),
        ticket_data.get("status", "To Do"),
        ticket_data.get("sla_target_hours", 4.0),
        datetime.utcnow().isoformat(),
        ticket_data.get("is_duplicate", 0),
        ticket_data.get("duplicate_of", None),
        ticket_data.get("raw_log", ""),
        ticket_id
    ))
    
    conn.commit()
    conn.close()
    return ticket_id
