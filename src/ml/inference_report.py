"""
inference_report.py
Phase 9 — Churn Inference Business Report Generator
Olist Customer 360 & Churn Prediction Platform

Reads churn_scores + customer_360 from the analytical warehouse and produces:

  1. reports/churn_inference_report.xlsx
       Sheet: Summary          — key KPIs & risk tier counts
       Sheet: Risk_By_State    — churn rate and risk distribution per state
       Sheet: Top_High_Risk    — top 500 high-risk customers (actionable list)
       Sheet: Decile_Analysis  — lift curve data by decile
       Sheet: Segment_Risk     — churn risk by RFM / K-Means segment (if present)

  2. reports/churn_inference_report.html
       A self-contained, styled HTML page with embedded tables and KPI cards.

  3. reports/figures/churn_state_heatmap.png
       Choropleth-style bar chart showing churn rate by Brazilian state.
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime, timezone

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# ─────────────────────────────────────────────────────────────
#  Path resolution
# ─────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROCESSED_DIR = os.path.join(BASE_DIR, 'data', 'processed')
REPORTS_DIR   = os.path.join(BASE_DIR, 'reports')
FIGURES_DIR   = os.path.join(BASE_DIR, 'reports', 'figures')
DB_PATH       = os.path.join(PROCESSED_DIR, 'olist_warehouse.db')

os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(FIGURES_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────
#  Logging
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("InferenceReport")

RISK_ORDER = ['High Risk', 'Medium Risk', 'Low Risk']
RISK_COLORS = {
    'High Risk':   '#e74c3c',
    'Medium Risk': '#f39c12',
    'Low Risk':    '#27ae60',
}

ACTION_MAP = {
    'High Risk':   'Immediate win-back campaign — personalised offer + CSR outreach within 48 h',
    'Medium Risk': 'Proactive engagement — targeted email/push with loyalty reward or bundle discount',
    'Low Risk':    'Sustain loyalty — routine newsletter, birthday reward, new-arrival highlights',
}


# ══════════════════════════════════════════════════════════════
#  Report Builder
# ══════════════════════════════════════════════════════════════
class InferenceReportBuilder:
    """Generates the Phase 9 business intelligence report from scored data."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path  = db_path
        self.conn     = None
        self.run_ts   = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.scores   = None
        self.c360     = None

    # ──────────────────────────────────────────────
    #  Data loading
    # ──────────────────────────────────────────────
    def _connect_and_load(self):
        logger.info(f"Connecting to warehouse: {self.db_path}")
        self.conn = sqlite3.connect(self.db_path)

        # Validate churn_scores exists
        tables = pd.read_sql(
            "SELECT name FROM sqlite_master WHERE type='table'", self.conn
        )['name'].tolist()
        if 'churn_scores' not in tables:
            raise RuntimeError(
                "Table 'churn_scores' not found. Run Phase 9 batch_inference.py first."
            )

        logger.info("Loading churn_scores and customer_360 ...")
        self.scores = pd.read_sql("SELECT * FROM churn_scores", self.conn)
        self.c360   = pd.read_sql("SELECT * FROM customer_360", self.conn)

        logger.info(f"  churn_scores : {len(self.scores):,} rows")
        logger.info(f"  customer_360 : {len(self.c360):,}  rows")

        # Merge for enriched analysis
        self.merged = self.c360.merge(
            self.scores[['customer_unique_id', 'churn_probability',
                         'churn_prediction', 'risk_level', 'risk_decile',
                         'recommended_action', 'inference_run_at']],
            on='customer_unique_id',
            how='left',
            suffixes=('', '_scored')
        )
        # Prefer scored columns over potentially stale c360 columns
        for col in ['churn_probability', 'risk_level', 'risk_decile',
                    'churn_prediction', 'recommended_action', 'inference_run_at']:
            if f'{col}_scored' in self.merged.columns:
                self.merged[col] = self.merged[f'{col}_scored']
                self.merged.drop(columns=[f'{col}_scored'], inplace=True)

    # ──────────────────────────────────────────────
    #  Sheet builders
    # ──────────────────────────────────────────────
    def _build_summary_sheet(self) -> pd.DataFrame:
        """KPI summary table."""
        n         = len(self.scores)
        high_ct   = (self.scores['risk_level'] == 'High Risk').sum()
        med_ct    = (self.scores['risk_level'] == 'Medium Risk').sum()
        low_ct    = (self.scores['risk_level'] == 'Low Risk').sum()
        pred_churn = self.scores['churn_prediction'].sum()
        avg_prob  = self.scores['churn_probability'].mean()
        med_prob  = self.scores['churn_probability'].median()

        rows = [
            ('Report Generated At (UTC)',    self.run_ts),
            ('Total Scored Customers',       f"{n:,}"),
            ('Predicted Churners',           f"{pred_churn:,}  ({pred_churn/n*100:.1f}%)"),
            ('Average Churn Probability',    f"{avg_prob:.4f}"),
            ('Median Churn Probability',     f"{med_prob:.4f}"),
            ('--- Risk Tier Breakdown ---',  ''),
            ('High Risk  (prob >= 0.70)',     f"{high_ct:,}  ({high_ct/n*100:.1f}%)"),
            ('Medium Risk (0.40 <= prob < 0.70)', f"{med_ct:,}  ({med_ct/n*100:.1f}%)"),
            ('Low Risk   (prob < 0.40)',     f"{low_ct:,}  ({low_ct/n*100:.1f}%)"),
            ('--- Recommended Actions ---',  ''),
            ('High Risk Action',             ACTION_MAP['High Risk']),
            ('Medium Risk Action',           ACTION_MAP['Medium Risk']),
            ('Low Risk Action',              ACTION_MAP['Low Risk']),
        ]
        return pd.DataFrame(rows, columns=['KPI', 'Value'])

    def _build_state_sheet(self) -> pd.DataFrame:
        """Churn metrics aggregated by Brazilian state."""
        if 'customer_state' not in self.merged.columns:
            return pd.DataFrame()

        state_grp = (
            self.merged
            .groupby('customer_state')
            .agg(
                total_customers    = ('customer_unique_id', 'count'),
                predicted_churners = ('churn_prediction',   'sum'),
                avg_churn_prob     = ('churn_probability',  'mean'),
                high_risk_count    = ('risk_level',         lambda s: (s == 'High Risk').sum()),
                avg_monetary_value = ('monetary_value',     'mean'),
            )
            .reset_index()
        )
        state_grp['churn_rate_pct']   = (state_grp['predicted_churners'] / state_grp['total_customers'] * 100).round(2)
        state_grp['high_risk_pct']    = (state_grp['high_risk_count']    / state_grp['total_customers'] * 100).round(2)
        state_grp['avg_churn_prob']   = state_grp['avg_churn_prob'].round(4)
        state_grp['avg_monetary_value'] = state_grp['avg_monetary_value'].round(2)
        state_grp.rename(columns={
            'customer_state':     'State',
            'total_customers':    'Total Customers',
            'predicted_churners': 'Predicted Churners',
            'avg_churn_prob':     'Avg Churn Probability',
            'high_risk_count':    'High Risk Count',
            'high_risk_pct':      'High Risk %',
            'churn_rate_pct':     'Churn Rate %',
            'avg_monetary_value': 'Avg Monetary Value (R$)',
        }, inplace=True)

        return state_grp.sort_values('Churn Rate %', ascending=False).reset_index(drop=True)

    def _build_top_high_risk_sheet(self, n: int = 500) -> pd.DataFrame:
        """Top N high-risk customers — ready for CRM export."""
        cols = ['customer_unique_id', 'customer_state', 'churn_probability',
                'risk_level', 'risk_decile', 'monetary_value', 'total_orders',
                'average_review_score', 'last_order_date', 'days_since_last_order',
                'preferred_payment_method', 'recommended_action']
        available = [c for c in cols if c in self.merged.columns]

        high_risk = (
            self.merged[self.merged['risk_level'] == 'High Risk'][available]
            .sort_values('churn_probability', ascending=False)
            .head(n)
            .reset_index(drop=True)
        )
        high_risk.index = high_risk.index + 1
        high_risk.index.name = 'Rank'
        return high_risk.reset_index()

    def _build_decile_sheet(self) -> pd.DataFrame:
        """Decile-level lift curve and capture metrics."""
        decile_tbl = (
            self.scores.groupby('risk_decile')
            .agg(
                customers          = ('customer_unique_id', 'count'),
                avg_churn_prob     = ('churn_probability',  'mean'),
                predicted_churners = ('churn_prediction',   'sum'),
            )
            .sort_index(ascending=False)
            .reset_index()
        )
        total_pred = max(decile_tbl['predicted_churners'].sum(), 1)
        decile_tbl['cumulative_churners']  = decile_tbl['predicted_churners'].cumsum()
        decile_tbl['churn_capture_pct']    = (decile_tbl['predicted_churners'] / total_pred * 100).round(1)
        decile_tbl['cumulative_capture_pct'] = decile_tbl['churn_capture_pct'].cumsum().round(1)
        decile_tbl['avg_churn_prob']       = decile_tbl['avg_churn_prob'].round(4)

        total_customers = max(self.scores['customer_unique_id'].count(), 1)
        baseline_rate   = self.scores['churn_prediction'].mean()
        decile_tbl['lift'] = (
            (decile_tbl['predicted_churners'] / decile_tbl['customers']) / baseline_rate
        ).round(2)

        decile_tbl.rename(columns={
            'risk_decile':           'Decile',
            'customers':             'Customers',
            'avg_churn_prob':        'Avg Churn Probability',
            'predicted_churners':    'Predicted Churners',
            'cumulative_churners':   'Cumulative Churners',
            'churn_capture_pct':     'Churn Captured %',
            'cumulative_capture_pct':'Cumulative Capture %',
            'lift':                  'Lift vs Baseline',
        }, inplace=True)
        return decile_tbl

    def _build_segment_sheet(self) -> pd.DataFrame:
        """Churn risk broken down by RFM segment or K-Means cluster (if present)."""
        seg_col = None
        for candidate in ['rfm_segment', 'cluster_label', 'cluster_kmeans']:
            if candidate in self.merged.columns:
                seg_col = candidate
                break
        if seg_col is None:
            return pd.DataFrame(columns=['Note'],
                                data=[['No segmentation column found in customer_360.']])

        seg_tbl = (
            self.merged.groupby(seg_col)
            .agg(
                customers          = ('customer_unique_id', 'count'),
                avg_churn_prob     = ('churn_probability',  'mean'),
                predicted_churners = ('churn_prediction',   'sum'),
                high_risk_count    = ('risk_level',         lambda s: (s == 'High Risk').sum()),
                avg_monetary_value = ('monetary_value',     'mean'),
            )
            .reset_index()
        )
        seg_tbl['churn_rate_pct']  = (seg_tbl['predicted_churners'] / seg_tbl['customers'] * 100).round(2)
        seg_tbl['high_risk_pct']   = (seg_tbl['high_risk_count']    / seg_tbl['customers'] * 100).round(2)
        seg_tbl['avg_churn_prob']  = seg_tbl['avg_churn_prob'].round(4)
        seg_tbl['avg_monetary_value'] = seg_tbl['avg_monetary_value'].round(2)
        seg_tbl.rename(columns={
            seg_col:               'Segment',
            'customers':           'Customers',
            'avg_churn_prob':      'Avg Churn Prob',
            'predicted_churners':  'Pred. Churners',
            'high_risk_count':     'High Risk Count',
            'high_risk_pct':       'High Risk %',
            'churn_rate_pct':      'Churn Rate %',
            'avg_monetary_value':  'Avg Monetary Value (R$)',
        }, inplace=True)
        return seg_tbl.sort_values('Churn Rate %', ascending=False).reset_index(drop=True)

    # ──────────────────────────────────────────────
    #  Chart: State churn heatmap bar
    # ──────────────────────────────────────────────
    def _generate_state_chart(self, df_state: pd.DataFrame):
        if df_state.empty or 'State' not in df_state.columns:
            logger.warning("State sheet is empty — skipping state chart.")
            return

        BG, PANEL_BG, TEXT_CLR = '#0f1117', '#1a1d27', '#c9d1d9'

        top_n = df_state.head(20).copy()
        top_n = top_n.sort_values('Churn Rate %', ascending=True)

        fig, ax = plt.subplots(figsize=(12, 8))
        fig.patch.set_facecolor(BG)
        ax.set_facecolor(PANEL_BG)
        ax.tick_params(colors=TEXT_CLR)
        ax.xaxis.label.set_color(TEXT_CLR)
        ax.yaxis.label.set_color(TEXT_CLR)
        ax.title.set_color('#e6edf3')
        for spine in ax.spines.values():
            spine.set_edgecolor('#30363d')

        cmap_vals = top_n['Churn Rate %'] / top_n['Churn Rate %'].max()
        bar_colors = plt.cm.RdYlGn_r(cmap_vals)

        bars = ax.barh(top_n['State'], top_n['Churn Rate %'],
                       color=bar_colors, edgecolor=BG, height=0.65)

        for bar, val in zip(bars, top_n['Churn Rate %']):
            ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                    f"{val:.1f}%", va='center', ha='left',
                    fontsize=8.5, color=TEXT_CLR, fontweight='bold')

        ax.set_xlabel('Churn Rate (%)', fontsize=11)
        ax.set_title('Customer Churn Rate by Brazilian State (Top 20)',
                     fontsize=13, fontweight='bold', pad=12)
        ax.xaxis.set_major_formatter(mticker.PercentFormatter(xmax=100))

        plt.tight_layout(pad=2.0)
        p = os.path.join(FIGURES_DIR, 'churn_state_heatmap.png')
        plt.savefig(p, dpi=180, bbox_inches='tight', facecolor=BG)
        plt.close()
        logger.info(f"  Saved: {p}")

    # ──────────────────────────────────────────────
    #  Excel export
    # ──────────────────────────────────────────────
    def _export_excel(
        self,
        df_summary:  pd.DataFrame,
        df_state:    pd.DataFrame,
        df_high_risk:pd.DataFrame,
        df_decile:   pd.DataFrame,
        df_segment:  pd.DataFrame,
    ):
        xlsx_path = os.path.join(REPORTS_DIR, 'churn_inference_report.xlsx')
        logger.info(f"Writing Excel report -> {xlsx_path}")

        try:
            with pd.ExcelWriter(xlsx_path, engine='openpyxl') as writer:
                df_summary.to_excel(writer,   sheet_name='Summary',        index=False)
                df_state.to_excel(writer,      sheet_name='Risk_By_State',  index=False)
                df_high_risk.to_excel(writer,  sheet_name='Top_High_Risk',  index=False)
                df_decile.to_excel(writer,     sheet_name='Decile_Analysis',index=False)
                df_segment.to_excel(writer,    sheet_name='Segment_Risk',   index=False)

                # Auto-width columns for readability
                for sheet_name in writer.sheets:
                    ws = writer.sheets[sheet_name]
                    for col_cells in ws.columns:
                        max_len = max(
                            (len(str(cell.value)) if cell.value is not None else 0)
                            for cell in col_cells
                        ) + 2
                        ws.column_dimensions[col_cells[0].column_letter].width = min(max_len, 60)

            logger.info(f"Excel report saved: {xlsx_path}")
        except ImportError:
            logger.warning("openpyxl not installed — skipping Excel export. "
                           "Install with: pip install openpyxl")

    # ──────────────────────────────────────────────
    #  HTML report
    # ──────────────────────────────────────────────
    def _export_html(
        self,
        df_summary:  pd.DataFrame,
        df_state:    pd.DataFrame,
        df_high_risk:pd.DataFrame,
        df_decile:   pd.DataFrame,
    ):
        html_path = os.path.join(REPORTS_DIR, 'churn_inference_report.html')
        logger.info(f"Writing HTML report -> {html_path}")

        n         = len(self.scores)
        high_ct   = (self.scores['risk_level'] == 'High Risk').sum()
        med_ct    = (self.scores['risk_level'] == 'Medium Risk').sum()
        low_ct    = (self.scores['risk_level'] == 'Low Risk').sum()
        pred_churn = self.scores['churn_prediction'].sum()

        kpi_html = f"""
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-label">Total Customers Scored</div>
                <div class="kpi-value">{n:,}</div>
            </div>
            <div class="kpi-card kpi-danger">
                <div class="kpi-label">Predicted Churners</div>
                <div class="kpi-value">{pred_churn:,}</div>
                <div class="kpi-sub">{pred_churn/n*100:.1f}% of customer base</div>
            </div>
            <div class="kpi-card kpi-danger">
                <div class="kpi-label">High Risk</div>
                <div class="kpi-value">{high_ct:,}</div>
                <div class="kpi-sub">{high_ct/n*100:.1f}% — Immediate Action</div>
            </div>
            <div class="kpi-card kpi-warning">
                <div class="kpi-label">Medium Risk</div>
                <div class="kpi-value">{med_ct:,}</div>
                <div class="kpi-sub">{med_ct/n*100:.1f}% — Proactive Engagement</div>
            </div>
            <div class="kpi-card kpi-success">
                <div class="kpi-label">Low Risk</div>
                <div class="kpi-value">{low_ct:,}</div>
                <div class="kpi-sub">{low_ct/n*100:.1f}% — Sustain Loyalty</div>
            </div>
        </div>"""

        def df_to_html_table(df: pd.DataFrame, max_rows: int = 50) -> str:
            return df.head(max_rows).to_html(
                index=False, classes='data-table', border=0, na_rep='—'
            )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Churn Inference Report — Deloitte Olist Platform</title>
<style>
  :root {{
    --bg: #0f1117; --panel: #1a1d27; --border: #30363d;
    --text: #c9d1d9; --heading: #e6edf3; --accent: #58a6ff;
    --danger: #e74c3c; --warning: #f39c12; --success: #27ae60;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif;
          font-size: 14px; line-height: 1.6; padding: 32px; }}
  h1 {{ color: var(--heading); font-size: 28px; font-weight: 700; margin-bottom: 4px; }}
  h2 {{ color: var(--heading); font-size: 18px; font-weight: 600; margin: 36px 0 12px;
        border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
  .meta {{ color: #8b949e; font-size: 12px; margin-bottom: 28px; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
               gap: 16px; margin: 20px 0 36px; }}
  .kpi-card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
               padding: 20px 22px; }}
  .kpi-danger  {{ border-top: 3px solid var(--danger);  }}
  .kpi-warning {{ border-top: 3px solid var(--warning); }}
  .kpi-success {{ border-top: 3px solid var(--success); }}
  .kpi-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: .8px;
                color: #8b949e; margin-bottom: 6px; }}
  .kpi-value {{ font-size: 28px; font-weight: 700; color: var(--heading); }}
  .kpi-sub   {{ font-size: 11px; color: #8b949e; margin-top: 4px; }}
  .action-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                  gap: 14px; margin: 16px 0 28px; }}
  .action-card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
                  padding: 16px 18px; }}
  .action-card h3 {{ font-size: 13px; font-weight: 600; margin-bottom: 6px; }}
  .action-card.danger  h3 {{ color: var(--danger);  }}
  .action-card.warning h3 {{ color: var(--warning); }}
  .action-card.success h3 {{ color: var(--success); }}
  .action-card p {{ font-size: 12px; color: var(--text); line-height: 1.5; }}
  table.data-table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
  table.data-table th {{ background: #21262d; color: var(--heading); font-weight: 600;
                         padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--border); }}
  table.data-table td {{ padding: 7px 12px; border-bottom: 1px solid #21262d; color: var(--text); }}
  table.data-table tr:hover td {{ background: #21262d; }}
  .table-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 8px;
                 background: var(--panel); margin-bottom: 8px; }}
  .note {{ font-size: 11px; color: #8b949e; margin-top: 6px; font-style: italic; }}
  footer {{ margin-top: 48px; padding-top: 16px; border-top: 1px solid var(--border);
            color: #8b949e; font-size: 11px; text-align: center; }}
</style>
</head>
<body>
<h1>Churn Prediction Inference Report</h1>
<p class="meta">Deloitte Olist Customer 360 Platform &nbsp;|&nbsp; Generated: {self.run_ts} &nbsp;|&nbsp; Champion Model: XGBoost</p>

<h2>Executive KPIs</h2>
{kpi_html}

<h2>Recommended Business Actions</h2>
<div class="action-grid">
  <div class="action-card danger">
    <h3>🔴 High Risk Customers ({high_ct:,})</h3>
    <p>{ACTION_MAP['High Risk']}</p>
  </div>
  <div class="action-card warning">
    <h3>🟡 Medium Risk Customers ({med_ct:,})</h3>
    <p>{ACTION_MAP['Medium Risk']}</p>
  </div>
  <div class="action-card success">
    <h3>🟢 Low Risk Customers ({low_ct:,})</h3>
    <p>{ACTION_MAP['Low Risk']}</p>
  </div>
</div>

<h2>Decile Analysis — Lift &amp; Capture</h2>
<div class="table-wrap">{df_to_html_table(df_decile, max_rows=10)}</div>
<p class="note">Decile 10 = highest churn risk. Lift vs Baseline = tier churn rate ÷ overall predicted churn rate.</p>

<h2>Churn Risk by Brazilian State</h2>
<div class="table-wrap">{df_to_html_table(df_state, max_rows=27)}</div>

<h2>Top High-Risk Customers (Actionable CRM List — Top 50 shown)</h2>
<div class="table-wrap">{df_to_html_table(df_high_risk, max_rows=50)}</div>
<p class="note">Full list (top 500) available in the Excel report: churn_inference_report.xlsx → Sheet: Top_High_Risk</p>

<footer>Deloitte Analytics Practice &nbsp;|&nbsp; Olist Churn Prediction Platform &nbsp;|&nbsp; Phase 9 Batch Inference Report</footer>
</body>
</html>"""

        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        logger.info(f"HTML report saved: {html_path}")

    # ──────────────────────────────────────────────
    #  Public entry-point
    # ──────────────────────────────────────────────
    def build(self):
        logger.info("=" * 70)
        logger.info("  PHASE 9 — CHURN INFERENCE BUSINESS REPORT GENERATOR")
        logger.info("=" * 70)

        self._connect_and_load()

        df_summary   = self._build_summary_sheet()
        df_state     = self._build_state_sheet()
        df_high_risk = self._build_top_high_risk_sheet(n=500)
        df_decile    = self._build_decile_sheet()
        df_segment   = self._build_segment_sheet()

        self._generate_state_chart(df_state)
        self._export_excel(df_summary, df_state, df_high_risk, df_decile, df_segment)
        self._export_html(df_summary, df_state, df_high_risk, df_decile)

        logger.info("=" * 70)
        logger.info("  Inference Report Generation Completed Successfully.")
        logger.info("=" * 70)

        if self.conn:
            self.conn.close()

        return {
            'summary':   df_summary,
            'state':     df_state,
            'high_risk': df_high_risk,
            'decile':    df_decile,
            'segment':   df_segment,
        }


# ══════════════════════════════════════════════════════════════
#  CLI entry-point
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    builder = InferenceReportBuilder()
    results = builder.build()

    print("\nPhase 9 Inference Report Generation Finished Successfully!")
    print(f"  Excel report : reports/churn_inference_report.xlsx")
    print(f"  HTML report  : reports/churn_inference_report.html")
    print(f"  State chart  : reports/figures/churn_state_heatmap.png")
