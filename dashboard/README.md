# Deloitte Customer 360 & Churn Intelligence Dashboard

This directory contains the production-grade Flask business dashboard for exploring churn predictions, RFM customer segments, geographic risk, and priority intervention lists.

## Quick Start

1. **Activate Virtual Environment** (if applicable) and ensure requirements are installed:
   ```bash
   pip install flask
   ```

2. **Run the Dashboard Server**:
   ```bash
   python dashboard/app.py
   ```

3. **Open in Browser**:
   Navigate to [http://127.0.0.1:5000](http://127.0.0.1:5000)

---

## Architecture & Features

- **Backend (`dashboard/app.py`)**: Flask 3.1.3 serving 10 analytical REST endpoints querying `data/processed/olist_warehouse.db` directly:
  - `/api/kpis` — Aggregate KPIs and risk metrics
  - `/api/risk_dist` — High / Medium / Low risk counts
  - `/api/score_hist` — 20-bin histogram of churn probabilities
  - `/api/decile` — Decile lift table and cumulative capture
  - `/api/state` — Churn rates and metrics across Brazilian states
  - `/api/payment` — Metrics grouped by payment method
  - `/api/segment` — Metrics grouped by RFM / K-Means segment
  - `/api/top_risk` — Top 100 high-risk customers for action
  - `/api/monthly_orders` — Order volume and revenue trend
  - `/api/category_churn` — Churn breakdown by product category

- **Frontend (`dashboard/templates/index.html`)**:
  - Dark-mode design with glowing risk indicators and modern typography (Inter)
  - Interactive Chart.js 4.4.0 visualizations
  - Lazy-rendered tabs: Overview, Risk Analysis, Segments, Geography, Customers
  - Sortable/formatted customer intervention priority tables
