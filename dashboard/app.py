"""
app.py
Phase 10 — Customer 360 Churn Intelligence Dashboard (Flask Backend)
Deloitte Olist Analytics Platform

Serves a single-page dashboard with real-time data from the analytical warehouse.

API Endpoints:
  GET /                    → Dashboard HTML
  GET /api/kpis            → Headline KPI metrics
  GET /api/risk_dist       → Risk tier distribution (pie chart)
  GET /api/score_hist      → Churn probability histogram buckets
  GET /api/decile          → Decile lift table
  GET /api/state           → Churn metrics by state (bar chart)
  GET /api/payment         → Revenue & churn by payment method
  GET /api/segment         → Churn by RFM/K-Means segment
  GET /api/top_risk        → Top high-risk customers (table)
  GET /api/monthly_orders  → Orders over time (trend chart)

Run with:
  python dashboard/app.py
  → http://127.0.0.1:5000
"""

import os
import sys
import sqlite3
import json
import logging
from functools import lru_cache

from flask import Flask, jsonify, render_template, abort

# ─────────────────────────────────────────────────────────────
#  Path setup
# ─────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH       = os.path.join(BASE_DIR, 'data', 'processed', 'olist_warehouse.db')
TEMPLATE_DIR  = os.path.join(BASE_DIR, 'dashboard', 'templates')
STATIC_DIR    = os.path.join(BASE_DIR, 'dashboard', 'static')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("Dashboard")

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.config['JSON_SORT_KEYS'] = False


# ─────────────────────────────────────────────────────────────
#  DB helper
# ─────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def query(sql: str, params: tuple = ()):
    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_one(sql: str, params: tuple = ()):
    result = query(sql, params)
    return result[0] if result else {}


# ══════════════════════════════════════════════════════════════
#  Page route
# ══════════════════════════════════════════════════════════════
@app.route('/')
def index():
    return render_template('index.html')


# ══════════════════════════════════════════════════════════════
#  API — Headline KPIs
# ══════════════════════════════════════════════════════════════
@app.route('/api/kpis')
def api_kpis():
    sql = """
    SELECT
        COUNT(*)                                              AS total_customers,
        ROUND(AVG(churn_probability) * 100, 2)              AS avg_churn_prob_pct,
        SUM(churn_prediction)                                AS predicted_churners,
        ROUND(SUM(churn_prediction) * 100.0 / COUNT(*), 2)  AS churn_rate_pct,
        SUM(CASE WHEN risk_level = 'High Risk'   THEN 1 ELSE 0 END) AS high_risk_count,
        SUM(CASE WHEN risk_level = 'Medium Risk' THEN 1 ELSE 0 END) AS medium_risk_count,
        SUM(CASE WHEN risk_level = 'Low Risk'    THEN 1 ELSE 0 END) AS low_risk_count,
        ROUND(SUM(CASE WHEN risk_level = 'High Risk'   THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS high_risk_pct,
        ROUND(SUM(CASE WHEN risk_level = 'Medium Risk' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS medium_risk_pct,
        ROUND(SUM(CASE WHEN risk_level = 'Low Risk'    THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS low_risk_pct
    FROM churn_scores
    """
    kpis = query_one(sql)

    # Revenue KPIs from customer_360
    rev_sql = """
    SELECT
        ROUND(SUM(total_revenue), 2)              AS total_revenue,
        ROUND(AVG(average_order_value), 2)        AS avg_order_value,
        ROUND(AVG(average_review_score), 2)       AS avg_review_score,
        SUM(CASE WHEN repeat_customer_flag = 1 THEN 1 ELSE 0 END) AS repeat_customers,
        ROUND(SUM(CASE WHEN repeat_customer_flag=1 THEN 1 ELSE 0 END)*100.0/COUNT(*),2) AS repeat_rate_pct
    FROM customer_360
    WHERE total_revenue IS NOT NULL
    """
    rev = query_one(rev_sql)
    kpis.update(rev)

    inference_ts = query_one("SELECT inference_run_at FROM churn_scores LIMIT 1")
    kpis['inference_run_at'] = inference_ts.get('inference_run_at', 'N/A')

    return jsonify(kpis)


# ══════════════════════════════════════════════════════════════
#  API — Risk tier distribution
# ══════════════════════════════════════════════════════════════
@app.route('/api/risk_dist')
def api_risk_dist():
    rows = query("""
        SELECT risk_level, COUNT(*) AS count
        FROM churn_scores
        GROUP BY risk_level
        ORDER BY CASE risk_level
            WHEN 'High Risk'   THEN 1
            WHEN 'Medium Risk' THEN 2
            ELSE 3 END
    """)
    return jsonify(rows)


# ══════════════════════════════════════════════════════════════
#  API — Churn probability histogram (20 buckets)
# ══════════════════════════════════════════════════════════════
@app.route('/api/score_hist')
def api_score_hist():
    rows = query("""
        SELECT
            ROUND(CAST(CAST(churn_probability * 20 AS INTEGER) AS FLOAT) / 20, 2) AS bucket,
            COUNT(*) AS count
        FROM churn_scores
        GROUP BY bucket
        ORDER BY bucket
    """)
    return jsonify(rows)


# ══════════════════════════════════════════════════════════════
#  API — Decile lift table
# ══════════════════════════════════════════════════════════════
@app.route('/api/decile')
def api_decile():
    rows = query("""
        SELECT
            risk_decile                                          AS decile,
            COUNT(*)                                             AS customers,
            ROUND(AVG(churn_probability), 4)                    AS avg_churn_prob,
            SUM(churn_prediction)                                AS predicted_churners,
            ROUND(SUM(churn_prediction) * 100.0 / COUNT(*), 1)  AS tier_churn_rate_pct
        FROM churn_scores
        GROUP BY risk_decile
        ORDER BY risk_decile DESC
    """)
    # Compute lift vs baseline
    total_churn_rate = query_one(
        "SELECT ROUND(AVG(CAST(churn_prediction AS FLOAT)), 4) AS base FROM churn_scores"
    ).get('base', 1) or 1
    for r in rows:
        r['lift'] = round((r['tier_churn_rate_pct'] / 100) / total_churn_rate, 2) if total_churn_rate else 0
    return jsonify(rows)


# ══════════════════════════════════════════════════════════════
#  API — Churn metrics by state
# ══════════════════════════════════════════════════════════════
@app.route('/api/state')
def api_state():
    rows = query("""
        SELECT
            c.customer_state                                           AS state,
            COUNT(*)                                                   AS total_customers,
            SUM(s.churn_prediction)                                    AS predicted_churners,
            ROUND(SUM(s.churn_prediction) * 100.0 / COUNT(*), 2)      AS churn_rate_pct,
            ROUND(AVG(s.churn_probability), 4)                         AS avg_churn_prob,
            SUM(CASE WHEN s.risk_level='High Risk' THEN 1 ELSE 0 END)  AS high_risk_count,
            ROUND(AVG(c.monetary_value), 2)                            AS avg_monetary_value
        FROM customer_360 c
        JOIN churn_scores s ON c.customer_unique_id = s.customer_unique_id
        GROUP BY c.customer_state
        ORDER BY churn_rate_pct DESC
    """)
    return jsonify(rows)


# ══════════════════════════════════════════════════════════════
#  API — Revenue & churn by payment method
# ══════════════════════════════════════════════════════════════
@app.route('/api/payment')
def api_payment():
    rows = query("""
        SELECT
            c.preferred_payment_method                                 AS payment_method,
            COUNT(*)                                                   AS customers,
            ROUND(AVG(s.churn_probability) * 100, 2)                  AS avg_churn_prob_pct,
            ROUND(AVG(c.monetary_value), 2)                            AS avg_monetary_value,
            SUM(s.churn_prediction)                                    AS predicted_churners
        FROM customer_360 c
        JOIN churn_scores s ON c.customer_unique_id = s.customer_unique_id
        WHERE c.preferred_payment_method IS NOT NULL
          AND c.preferred_payment_method != 'unknown'
        GROUP BY c.preferred_payment_method
        ORDER BY customers DESC
    """)
    return jsonify(rows)


# ══════════════════════════════════════════════════════════════
#  API — Churn by RFM segment
# ══════════════════════════════════════════════════════════════
@app.route('/api/segment')
def api_segment():
    # Try rfm_segment first, then cluster_label
    seg_col = None
    conn = get_db()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(customer_360)").fetchall()]
    conn.close()
    for candidate in ['rfm_segment', 'cluster_label', 'cluster_kmeans']:
        if candidate in cols:
            seg_col = candidate
            break

    if not seg_col:
        return jsonify([])

    rows = query(f"""
        SELECT
            c.{seg_col}                                                 AS segment,
            COUNT(*)                                                    AS customers,
            ROUND(AVG(s.churn_probability) * 100, 2)                   AS avg_churn_prob_pct,
            SUM(s.churn_prediction)                                     AS predicted_churners,
            ROUND(SUM(s.churn_prediction) * 100.0 / COUNT(*), 1)       AS churn_rate_pct,
            ROUND(AVG(c.monetary_value), 2)                             AS avg_monetary_value,
            ROUND(AVG(c.average_review_score), 2)                       AS avg_review_score
        FROM customer_360 c
        JOIN churn_scores s ON c.customer_unique_id = s.customer_unique_id
        WHERE c.{seg_col} IS NOT NULL
        GROUP BY c.{seg_col}
        ORDER BY churn_rate_pct DESC
    """)
    return jsonify(rows)


# ══════════════════════════════════════════════════════════════
#  API — Top high-risk customers
# ══════════════════════════════════════════════════════════════
@app.route('/api/top_risk')
def api_top_risk():
    rows = query("""
        SELECT
            s.customer_unique_id,
            c.customer_state,
            ROUND(s.churn_probability, 4)         AS churn_probability,
            s.risk_level,
            s.risk_decile,
            ROUND(c.monetary_value, 2)            AS monetary_value,
            c.total_orders,
            ROUND(c.average_review_score, 2)      AS avg_review_score,
            c.days_since_last_order,
            c.preferred_payment_method
        FROM churn_scores s
        JOIN customer_360 c ON s.customer_unique_id = c.customer_unique_id
        WHERE s.risk_level = 'High Risk'
        ORDER BY s.churn_probability DESC
        LIMIT 100
    """)
    return jsonify(rows)


# ══════════════════════════════════════════════════════════════
#  API — Monthly order trend
# ══════════════════════════════════════════════════════════════
@app.route('/api/monthly_orders')
def api_monthly_orders():
    rows = query("""
        SELECT
            SUBSTR(fo.purchase_date, 1, 7)          AS month,
            COUNT(DISTINCT fo.order_key)             AS orders,
            ROUND(SUM(fp.payment_value), 2)          AS revenue
        FROM fact_orders fo
        LEFT JOIN fact_payments fp ON fo.order_key = fp.order_key
        WHERE fo.order_status != 'canceled'
          AND fo.purchase_date IS NOT NULL
          AND SUBSTR(fo.purchase_date, 1, 4) BETWEEN '2016' AND '2018'
        GROUP BY month
        ORDER BY month
    """)
    return jsonify(rows)


# ══════════════════════════════════════════════════════════════
#  API — Category performance
# ══════════════════════════════════════════════════════════════
@app.route('/api/category_churn')
def api_category_churn():
    rows = query("""
        SELECT
            c.preferred_category                                         AS category,
            COUNT(*)                                                     AS customers,
            ROUND(AVG(s.churn_probability) * 100, 2)                    AS avg_churn_prob_pct,
            ROUND(AVG(c.monetary_value), 2)                              AS avg_monetary_value,
            SUM(s.churn_prediction)                                      AS predicted_churners
        FROM customer_360 c
        JOIN churn_scores s ON c.customer_unique_id = s.customer_unique_id
        WHERE c.preferred_category IS NOT NULL AND c.preferred_category != 'unknown'
        GROUP BY c.preferred_category
        ORDER BY customers DESC
        LIMIT 15
    """)
    return jsonify(rows)


# ══════════════════════════════════════════════════════════════
#  Run
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    logger.info(f"Database path : {DB_PATH}")
    logger.info(f"Templates dir : {TEMPLATE_DIR}")
    if not os.path.exists(DB_PATH):
        logger.error(f"Database not found at {DB_PATH}. Run the ETL pipeline first.")
        sys.exit(1)
    logger.info("Starting Deloitte Customer 360 Dashboard on http://127.0.0.1:5000")
    app.run(debug=True, port=5000, host='127.0.0.1')
