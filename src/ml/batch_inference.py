"""
batch_inference.py
Phase 9 — Batch Inference & Scoring Engine
Olist Customer 360 & Churn Prediction Platform

Responsibilities:
  1. Load champion XGBoost churn pipeline from disk (joblib).
  2. Retrieve the full customer_360 feature set from the analytical warehouse.
  3. Score every customer → churn_probability, risk_level, risk_decile.
  4. Persist scored results to:
       - SQLite table:  churn_scores          (warehouse)
       - SQLite table:  customer_360          (updated in-place with scores)
       - CSV export:    data/processed/churn_scores.csv
  5. Emit a concise scoring run summary (counts, risk distribution, decile table).
  6. Generate diagnostic artifacts:
       - reports/figures/churn_score_distribution.png   (histogram by risk tier)
       - reports/figures/churn_risk_decile_chart.png    (bar chart by decile)

Design Principles:
  - Zero retraining: inference only — champion pipeline is consumed as-is.
  - Idempotent: re-running always replaces the previous scoring run.
  - Leakage-safe: same feature set used during training; no target columns forwarded.
  - Run-stamped: every scoring record carries inference_run_at (UTC ISO-8601).
"""

import os
import sys
import sqlite3
import joblib
import logging
import traceback
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
FIGURES_DIR   = os.path.join(BASE_DIR, 'reports', 'figures')
ML_DIR        = os.path.join(BASE_DIR, 'src', 'ml')
DB_PATH       = os.path.join(PROCESSED_DIR, 'olist_warehouse.db')
MODEL_PATH    = os.path.join(ML_DIR, 'churn_champion_pipeline.joblib')

os.makedirs(FIGURES_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────
#  Logging
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("BatchInference")

# ─────────────────────────────────────────────────────────────
#  Feature manifest — MUST mirror Phase 8 training features
# ─────────────────────────────────────────────────────────────
NUMERICAL_FEATURES = [
    'monetary_value',
    'total_spend',
    'average_order_value',
    'total_items',
    'average_review_score',
    'cancellation_rate',
    'late_delivery_rate',
    'average_delivery_delay',
    'avg_installments',
    'number_of_categories',
    'number_of_sellers',
    'repeat_customer_flag',
    'high_value_customer_flag',
]
CATEGORICAL_FEATURES = [
    'preferred_payment_method',
    'customer_state',
]
ALL_FEATURES = NUMERICAL_FEATURES + CATEGORICAL_FEATURES

# Risk tier boundaries (churn_probability thresholds)
RISK_ORDER = ['High Risk', 'Medium Risk', 'Low Risk']

# Recommended business action per risk tier
ACTION_MAP = {
    'High Risk':   'Immediate win-back campaign — personalised offer + CSR outreach within 48 h',
    'Medium Risk': 'Proactive engagement — targeted email/push with loyalty reward or bundle discount',
    'Low Risk':    'Sustain loyalty — routine newsletter, birthday reward, new-arrival highlights',
}


# ══════════════════════════════════════════════════════════════
#  Main scoring class
# ══════════════════════════════════════════════════════════════
class BatchInferenceEngine:
    """
    Loads the champion churn pipeline and scores the full customer base.
    Results are persisted to the analytical warehouse and exported as CSV.
    """

    def __init__(
        self,
        model_path: str = MODEL_PATH,
        db_path:    str = DB_PATH,
    ):
        self.model_path = model_path
        self.db_path    = db_path
        self.pipeline   = None
        self.conn       = None
        self.run_ts     = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # ──────────────────────────────────────────────
    #  Connection & model helpers
    # ──────────────────────────────────────────────
    def _connect(self):
        logger.info(f"Connecting to warehouse: {self.db_path}")
        self.conn = sqlite3.connect(self.db_path)

    def _load_model(self):
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"Champion model not found at {self.model_path}. "
                "Run Phase 8 (churn_model.py) first."
            )
        logger.info(f"Loading champion pipeline from {self.model_path} ...")
        self.pipeline = joblib.load(self.model_path)
        logger.info("Champion pipeline loaded successfully.")

    # ──────────────────────────────────────────────
    #  Data retrieval
    # ──────────────────────────────────────────────
    def _load_customer_360(self) -> pd.DataFrame:
        logger.info("Retrieving customer_360 feature table from warehouse ...")
        df = pd.read_sql("SELECT * FROM customer_360", self.conn)
        logger.info(f"  -> {len(df):,} customers loaded, {len(df.columns)} attributes.")
        return df

    # ──────────────────────────────────────────────
    #  Scoring
    # ──────────────────────────────────────────────
    def _score(self, df: pd.DataFrame) -> pd.DataFrame:
        logger.info("Extracting feature matrix ...")

        # Guard: ensure all expected feature columns are present
        missing = [c for c in ALL_FEATURES if c not in df.columns]
        if missing:
            raise ValueError(
                f"Feature columns missing from customer_360 table: {missing}. "
                "Re-run Phase 5 (customer_360.py) to rebuild the feature store."
            )

        X = df[ALL_FEATURES].copy()

        logger.info(f"Scoring {len(X):,} customers with champion model ...")
        churn_probs = self.pipeline.predict_proba(X)[:, 1]
        churn_preds = self.pipeline.predict(X)

        scores = df[['customer_unique_id']].copy()
        scores['churn_probability'] = np.round(churn_probs, 4)
        scores['churn_prediction']  = churn_preds.astype(int)

        # Risk level using boundary thresholds
        conditions = [
            churn_probs >= 0.70,
            (churn_probs >= 0.40) & (churn_probs < 0.70),
            churn_probs < 0.40,
        ]
        choices = ['High Risk', 'Medium Risk', 'Low Risk']
        scores['risk_level'] = np.select(conditions, choices, default='Medium Risk')

        # Risk decile (10 = highest churn probability)
        scores['risk_decile'] = pd.qcut(
            scores['churn_probability'],
            q=10,
            labels=False,
            duplicates='drop'
        ).fillna(0).astype(int) + 1

        # Recommended action per tier
        scores['recommended_action'] = scores['risk_level'].map(ACTION_MAP)

        # Run timestamp for auditability
        scores['inference_run_at'] = self.run_ts

        logger.info("Scoring complete.")
        return scores

    # ──────────────────────────────────────────────
    #  Persistence
    # ──────────────────────────────────────────────
    def _persist_scores(self, scores: pd.DataFrame, df_c360: pd.DataFrame) -> pd.DataFrame:
        # 1. Dedicated churn_scores table
        logger.info("Writing churn_scores table to warehouse ...")
        scores.to_sql('churn_scores', self.conn, if_exists='replace', index=False, chunksize=10000)

        cur = self.conn.cursor()
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cs_uid    ON churn_scores(customer_unique_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cs_risk   ON churn_scores(risk_level);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cs_prob   ON churn_scores(churn_probability);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cs_decile ON churn_scores(risk_decile);")
        self.conn.commit()

        # 2. Back-patch customer_360 with scoring columns (drop stale cols first)
        logger.info("Back-patching customer_360 with churn scores ...")
        SCORE_COLS = ['churn_probability', 'churn_prediction', 'risk_level',
                      'risk_decile', 'recommended_action', 'inference_run_at']
        stale = [c for c in SCORE_COLS if c in df_c360.columns]
        if stale:
            df_c360 = df_c360.drop(columns=stale)

        merge_cols = ['customer_unique_id'] + SCORE_COLS
        df_updated = df_c360.merge(scores[merge_cols], on='customer_unique_id', how='left')

        df_updated.to_sql('customer_360', self.conn, if_exists='replace', index=False, chunksize=10000)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_c360_risk   ON customer_360(risk_level);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_c360_prob   ON customer_360(churn_probability);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_c360_decile ON customer_360(risk_decile);")
        self.conn.commit()
        logger.info("Warehouse tables updated successfully.")

        # 3. CSV export
        csv_path = os.path.join(PROCESSED_DIR, 'churn_scores.csv')
        scores.to_csv(csv_path, index=False)
        logger.info(f"Exported churn_scores.csv -> {csv_path}")

        return df_updated

    # ──────────────────────────────────────────────
    #  Summary reporting (console)
    # ──────────────────────────────────────────────
    def _print_summary(self, scores: pd.DataFrame):
        n_total  = len(scores)
        risk_cts = scores['risk_level'].value_counts().reindex(RISK_ORDER).fillna(0).astype(int)

        print("\n" + "=" * 80)
        print("  PHASE 9 — BATCH CHURN INFERENCE SCORING SUMMARY")
        print("=" * 80)
        print(f"  Run Timestamp      : {self.run_ts}")
        print(f"  Champion Model     : {os.path.basename(self.model_path)}")
        print(f"  Total Customers    : {n_total:,}")
        print(f"  Predicted Churners : {scores['churn_prediction'].sum():,}  "
              f"({scores['churn_prediction'].mean()*100:.1f}%)")
        print()
        print(f"  {'Risk Tier':<18} {'Count':>8} {'Share':>8}   Recommended Action")
        print(f"  {'-'*18} {'-'*8} {'-'*8}   {'-'*50}")
        for tier in RISK_ORDER:
            ct  = risk_cts[tier]
            pct = ct / n_total * 100
            action = ACTION_MAP[tier].split('—')[0].strip()
            print(f"  {tier:<18} {ct:>8,} {pct:>7.1f}%   {action}")
        print()

        # Decile breakdown table
        decile_tbl = (
            scores.groupby('risk_decile')
            .agg(
                customers          = ('customer_unique_id', 'count'),
                avg_churn_prob     = ('churn_probability',  'mean'),
                predicted_churners = ('churn_prediction',   'sum'),
            )
            .sort_index(ascending=False)
            .reset_index()
        )
        decile_tbl['avg_churn_prob']   = decile_tbl['avg_churn_prob'].round(4)
        decile_tbl['churn_capture_pct'] = (
            decile_tbl['predicted_churners'] / max(decile_tbl['predicted_churners'].sum(), 1) * 100
        ).round(1)
        decile_tbl.rename(columns={
            'risk_decile':        'Decile',
            'customers':          'Customers',
            'avg_churn_prob':     'Avg Churn Prob',
            'predicted_churners': 'Pred. Churners',
            'churn_capture_pct':  'Churn Captured %',
        }, inplace=True)

        print("  RISK DECILE TABLE  (Decile 10 = Highest Churn Risk)")
        print("  " + "-" * 64)
        print("  " + decile_tbl.to_string(index=False).replace('\n', '\n  '))
        print("=" * 80)

    # ──────────────────────────────────────────────
    #  Diagnostic charts
    # ──────────────────────────────────────────────
    def _generate_charts(self, scores: pd.DataFrame):
        logger.info("Generating scoring diagnostic charts ...")

        PALETTE = {
            'High Risk':   '#e74c3c',
            'Medium Risk': '#f39c12',
            'Low Risk':    '#27ae60',
        }
        BG       = '#0f1117'
        PANEL_BG = '#1a1d27'
        TEXT_CLR = '#c9d1d9'

        def _style_ax(ax):
            ax.set_facecolor(PANEL_BG)
            ax.tick_params(colors=TEXT_CLR)
            ax.xaxis.label.set_color(TEXT_CLR)
            ax.yaxis.label.set_color(TEXT_CLR)
            ax.title.set_color('#e6edf3')
            for spine in ax.spines.values():
                spine.set_edgecolor('#30363d')

        # ── Chart 1: Distribution histogram + pie ──────────────────────
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
        fig.patch.set_facecolor(BG)
        _style_ax(ax1)
        _style_ax(ax2)

        for tier in RISK_ORDER:
            subset = scores[scores['risk_level'] == tier]['churn_probability']
            ax1.hist(subset, bins=40, alpha=0.68, color=PALETTE[tier],
                     label=f"{tier} ({len(subset):,})", edgecolor='none')

        ax1.axvline(0.40, color='#f39c12', linestyle='--', linewidth=1.6, alpha=0.9, label='Medium threshold (0.40)')
        ax1.axvline(0.70, color='#e74c3c', linestyle='--', linewidth=1.6, alpha=0.9, label='High threshold (0.70)')
        ax1.set_title('Churn Probability Distribution by Risk Tier',
                      fontsize=13, fontweight='bold', pad=12)
        ax1.set_xlabel('Churn Probability', fontsize=11)
        ax1.set_ylabel('Customer Count',    fontsize=11)
        ax1.legend(fontsize=9.5, framealpha=0.25, labelcolor=TEXT_CLR,
                   facecolor=PANEL_BG, edgecolor='#30363d')
        ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{int(x):,}'))

        risk_cts = scores['risk_level'].value_counts().reindex(RISK_ORDER).fillna(0)
        wedges, texts, autotexts = ax2.pie(
            risk_cts,
            labels=RISK_ORDER,
            colors=[PALETTE[t] for t in RISK_ORDER],
            autopct='%1.1f%%',
            startangle=90,
            pctdistance=0.78,
            wedgeprops=dict(linewidth=2.5, edgecolor=BG),
        )
        for t in texts:
            t.set_color(TEXT_CLR); t.set_fontsize(11)
        for at in autotexts:
            at.set_color('white'); at.set_fontsize(10); at.set_fontweight('bold')
        ax2.set_title('Customer Risk Tier Breakdown', fontsize=13, fontweight='bold', pad=12)
        ax2.title.set_color('#e6edf3')

        plt.tight_layout(pad=2.5)
        p1 = os.path.join(FIGURES_DIR, 'churn_score_distribution.png')
        plt.savefig(p1, dpi=180, bbox_inches='tight', facecolor=BG)
        plt.close()
        logger.info(f"  Saved: {p1}")

        # ── Chart 2: Decile bar chart ───────────────────────────────────
        decile_stats = (
            scores.groupby('risk_decile')
            .agg(avg_prob=('churn_probability', 'mean'),
                 churn_ct=('churn_prediction',  'sum'))
            .sort_index()
            .reset_index()
        )

        fig2, ax = plt.subplots(figsize=(14, 6))
        fig2.patch.set_facecolor(BG)
        _style_ax(ax)

        bar_colors = [
            '#e74c3c' if p >= 0.70 else '#f39c12' if p >= 0.40 else '#27ae60'
            for p in decile_stats['avg_prob']
        ]
        bars = ax.bar(
            decile_stats['risk_decile'],
            decile_stats['avg_prob'],
            color=bar_colors,
            edgecolor=BG,
            linewidth=1.2,
            width=0.7,
        )

        for bar, (_, row) in zip(bars, decile_stats.iterrows()):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.005,
                f"{int(row['churn_ct']):,}",
                ha='center', va='bottom',
                fontsize=8.5, color=TEXT_CLR, fontweight='bold'
            )

        ax.axhline(0.70, color='#e74c3c', linestyle='--', linewidth=1.4, alpha=0.75,
                   label='High Risk threshold (0.70)')
        ax.axhline(0.40, color='#f39c12', linestyle='--', linewidth=1.4, alpha=0.75,
                   label='Medium Risk threshold (0.40)')
        ax.set_xticks(decile_stats['risk_decile'])
        ax.set_xticklabels([f"D{d}" for d in decile_stats['risk_decile']], fontsize=10)
        ax.set_xlabel('Risk Decile  (D10 = Highest Churn Risk)', fontsize=11)
        ax.set_ylabel('Average Churn Probability',               fontsize=11)
        ax.set_title('Average Churn Probability & Predicted Churners per Risk Decile',
                     fontsize=13, fontweight='bold', pad=12)
        ax.set_ylim(0, min(1.05, decile_stats['avg_prob'].max() + 0.15))
        ax.legend(fontsize=10, framealpha=0.25, labelcolor=TEXT_CLR,
                  facecolor=PANEL_BG, edgecolor='#30363d')
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0))

        plt.tight_layout(pad=2.0)
        p2 = os.path.join(FIGURES_DIR, 'churn_risk_decile_chart.png')
        plt.savefig(p2, dpi=180, bbox_inches='tight', facecolor=BG)
        plt.close()
        logger.info(f"  Saved: {p2}")

    # ──────────────────────────────────────────────
    #  Public entry-point
    # ──────────────────────────────────────────────
    def run(self) -> pd.DataFrame:
        """
        Execute the full batch inference pipeline.

        Returns
        -------
        pd.DataFrame
            Scored customer table (churn_scores) with risk tiers, probabilities, deciles.
        """
        logger.info("=" * 70)
        logger.info("  PHASE 9 — BATCH INFERENCE & SCORING ENGINE")
        logger.info("=" * 70)

        self._connect()
        self._load_model()
        df_c360  = self._load_customer_360()
        scores   = self._score(df_c360)
        _        = self._persist_scores(scores, df_c360)
        self._print_summary(scores)
        self._generate_charts(scores)

        logger.info("=" * 70)
        logger.info("  Phase 9 Batch Inference Completed Successfully.")
        logger.info("=" * 70)

        self.conn.close()
        return scores

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════
#  CLI entry-point
# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    engine = BatchInferenceEngine()
    try:
        scores_df = engine.run()
        print(f"\nPhase 9 Batch Inference & Scoring Finished Successfully!")
        print(f"  Scored customers  : {len(scores_df):,}")
        print(f"  Output table      : churn_scores  (warehouse + CSV)")
        print(f"  Diagnostic charts : reports/figures/")
    except FileNotFoundError as exc:
        logger.error(str(exc))
        sys.exit(1)
    except Exception:
        logger.error("Unexpected error during batch inference:")
        traceback.print_exc()
        sys.exit(1)
