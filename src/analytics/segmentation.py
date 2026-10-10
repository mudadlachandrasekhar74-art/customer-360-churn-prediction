"""
segmentation.py
Customer Segmentation Module for Customer 360 Platform.
Implements:
  1. Rule-based RFM Segmentation (Champions, Loyal Customers, Potential Loyalists, New Customers, At Risk, Lost Customers)
  2. Unsupervised Machine Learning K-Means Clustering with Elbow Method & Silhouette Score
  3. Comparative Analysis & Profiling
Saves enriched customer_360 table and diagnostic figures.
"""

import os
import sys
import sqlite3
import logging
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("Segmentation")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROCESSED_DIR = os.path.join(BASE_DIR, 'data', 'processed')
FIGURES_DIR = os.path.join(BASE_DIR, 'reports', 'figures')
DB_PATH = os.path.join(PROCESSED_DIR, 'olist_warehouse.db')

os.makedirs(FIGURES_DIR, exist_ok=True)

class CustomerSegmenter:
    """Performs RFM heuristic scoring and ML K-Means clustering."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.df_c360: pd.DataFrame = None

    def load_data(self) -> pd.DataFrame:
        logger.info(f"Loading customer_360 from {self.db_path}...")
        conn = sqlite3.connect(self.db_path)
        self.df_c360 = pd.read_sql("SELECT * FROM customer_360", conn)
        conn.close()
        logger.info(f"Loaded {len(self.df_c360):,} customers.")
        return self.df_c360

    # =========================================================================
    # 1. RULE-BASED RFM SEGMENTATION
    # =========================================================================
    def calculate_rfm_segments(self) -> pd.DataFrame:
        logger.info("Computing empirical RFM scores and business segments...")
        df = self.df_c360.copy()

        # Recency Score (R: 1 to 5, where 5 is most recent)
        # Using quintiles on recency
        df['r_score'] = pd.qcut(df['recency'], q=5, labels=[5, 4, 3, 2, 1]).astype(int)

        # Monetary Score (M: 1 to 5, where 5 is highest spend)
        df['m_score'] = pd.qcut(df['monetary_value'].rank(method='first'), q=5, labels=[1, 2, 3, 4, 5]).astype(int)

        # Frequency Score (F: 1 to 5)
        # 96.9% have frequency = 1. We allocate F based on repeat purchases and order density:
        # F >= 3: 5
        # F == 2 and M >= 3: 4
        # F == 2 and M < 3: 3
        # F == 1 and M >= 4: 2
        # F == 1 and M < 4: 1
        conditions = [
            (df['frequency'] >= 3),
            (df['frequency'] == 2) & (df['m_score'] >= 3),
            (df['frequency'] == 2) & (df['m_score'] < 3),
            (df['frequency'] == 1) & (df['m_score'] >= 4),
            (df['frequency'] == 1) & (df['m_score'] < 4)
        ]
        choices = [5, 4, 3, 2, 1]
        df['f_score'] = np.select(conditions, choices, default=1)

        # Composite RFM String (e.g., '545')
        df['rfm_score'] = df['r_score'].astype(str) + df['f_score'].astype(str) + df['m_score'].astype(str)

        # Segment Assignment Logic
        def assign_segment(row):
            r = row['r_score']
            f = row['f_score']
            m = row['m_score']

            # Champions: High R, High F/M
            if r >= 4 and f >= 4 and m >= 4:
                return 'Champions'
            # Loyal Customers: Consistent repeat or high spend with moderate-to-high recency
            elif (r >= 3 and f >= 3) or (f >= 4 and r >= 2):
                return 'Loyal Customers'
            # Potential Loyalists: Recent buyers with good basket size
            elif r >= 4 and m >= 3 and f < 4:
                return 'Potential Loyalists'
            # New Customers: Very recent buyers with low frequency
            elif r == 5 and f <= 2:
                return 'New Customers'
            # At Risk: Previously high-value/repeat buyers who have lapsed
            elif r <= 2 and (f >= 3 or m >= 4):
                return 'At Risk'
            # Lost Customers: Highly inactive with low historical spend
            elif r <= 2 and m <= 2:
                return 'Lost Customers'
            # Promising / Mainstream: Average recency and monetary spend
            else:
                return 'Promising'

        df['rfm_segment'] = df.apply(assign_segment, axis=1)

        logger.info("RFM Segment distribution:")
        dist = df['rfm_segment'].value_counts()
        for seg, count in dist.items():
            logger.info(f"  * {seg:<20}: {count:>6,} ({count/len(df)*100:>5.2f}%)")

        self.df_c360 = df
        return df

    # =========================================================================
    # 2. ML K-MEANS CLUSTERING
    # =========================================================================
    def run_kmeans_clustering(self, max_k: int = 7) -> pd.DataFrame:
        logger.info("Starting K-Means Clustering on customer behavioral features...")
        df = self.df_c360.copy()

        # Features requested: Recency, Frequency, Monetary Value, Average Order Value, Review Score
        feature_cols = ['recency', 'frequency', 'monetary_value', 'average_order_value', 'average_review_score']
        X = df[feature_cols].copy()

        # Handle extreme retail skew: log1p on monetary and AOV
        X['monetary_value'] = np.log1p(X['monetary_value'].clip(lower=0))
        X['average_order_value'] = np.log1p(X['average_order_value'].clip(lower=0))

        # Standardize
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # Elbow Method & Silhouette Evaluation
        logger.info(f"Evaluating K values from 2 to {max_k}...")
        inertias = []
        sil_scores = []
        k_values = list(range(2, max_k + 1))

        # Sample for fast, statistically sound silhouette score calculation
        sample_size = min(15000, len(X_scaled))
        np.random.seed(42)
        sample_indices = np.random.choice(len(X_scaled), size=sample_size, replace=False)
        X_sample = X_scaled[sample_indices]

        for k in k_values:
            km = KMeans(n_clusters=k, random_state=42, n_init=10)
            km.fit(X_scaled)
            inertias.append(km.inertia_)
            
            # Silhouette on sample
            sil = silhouette_score(X_sample, km.predict(X_sample))
            sil_scores.append(sil)
            logger.info(f"  K = {k} | Inertia = {km.inertia_:>12,.1f} | Silhouette Score = {sil:.4f}")

        # Optimal K selection (K=4 yields distinct, interpretable clusters)
        best_k = 4
        logger.info(f"Training final KMeans model with K={best_k}...")
        final_kmeans = KMeans(n_clusters=best_k, random_state=42, n_init=15)
        df['cluster_kmeans'] = final_kmeans.fit_predict(X_scaled)

        # Profile the clusters to assign business labels
        cluster_profile = df.groupby('cluster_kmeans')[feature_cols].mean()
        logger.info("\nCluster Profiling Centroids (Raw Means):")
        logger.info("\n" + cluster_profile.to_string())

        # Dynamic label assignment based on profiling:
        # Cluster with highest monetary_value -> High-Spenders
        # Cluster with lowest review_score -> Dissatisfied Customers
        # Cluster with lowest recency -> Active Recent Buyers
        # Cluster with highest recency -> Dormant One-Time Buyers
        cluster_labels = {}
        for c in range(best_k):
            row = cluster_profile.loc[c]
            if row['average_review_score'] < 3.0:
                cluster_labels[c] = 'Dissatisfied Buyers'
            elif row['monetary_value'] > cluster_profile['monetary_value'].mean() * 1.5:
                cluster_labels[c] = 'High-Value VIPs'
            elif row['recency'] < cluster_profile['recency'].mean():
                cluster_labels[c] = 'Recent Active'
            else:
                cluster_labels[c] = 'Dormant Low-Touch'

        df['cluster_label'] = df['cluster_kmeans'].map(cluster_labels)

        self.df_c360 = df
        self._plot_diagnostics(k_values, inertias, sil_scores, df)
        return df

    def _plot_diagnostics(self, k_values, inertias, sil_scores, df: pd.DataFrame):
        logger.info("Generating segmentation figures...")

        # 1. Elbow Method & Silhouette Score
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

        ax1.plot(k_values, inertias, 'bo-', linewidth=2, markersize=7)
        ax1.set_title('Elbow Method: Inertia vs. Number of Clusters (K)', fontsize=12, fontweight='bold')
        ax1.set_xlabel('Number of Clusters (K)')
        ax1.set_ylabel('Inertia (Within-Cluster Sum of Squares)')
        ax1.grid(True, linestyle='--', alpha=0.6)

        ax2.plot(k_values, sil_scores, 'rs-', linewidth=2, markersize=7)
        ax2.set_title('Silhouette Score vs. Number of Clusters (K)', fontsize=12, fontweight='bold')
        ax2.set_xlabel('Number of Clusters (K)')
        ax2.set_ylabel('Silhouette Score')
        ax2.grid(True, linestyle='--', alpha=0.6)

        plt.tight_layout()
        p1 = os.path.join(FIGURES_DIR, 'kmeans_elbow_silhouette.png')
        plt.savefig(p1, dpi=200)
        plt.close()
        logger.info(f"Saved: {p1}")

        # 2. RFM Segments Distribution (Customers and Revenue)
        seg_summary = df.groupby('rfm_segment').agg(
            customers=('customer_unique_id', 'count'),
            revenue=('monetary_value', 'sum')
        ).sort_values('revenue', ascending=False)

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

        palette = sns.color_palette("mako", len(seg_summary))
        sns.barplot(x=seg_summary.index, y=seg_summary['customers'], palette=palette, ax=ax1)
        ax1.set_title('Customer Count by RFM Segment', fontsize=13, fontweight='bold')
        ax1.set_ylabel('Number of Customers')
        ax1.set_xlabel('Segment')
        ax1.tick_params(axis='x', rotation=30)
        for p in ax1.patches:
            ax1.annotate(f"{int(p.get_height()):,}", (p.get_x() + p.get_width() / 2., p.get_height()),
                         ha='center', va='bottom', fontsize=8, xytext=(0, 3), textcoords='offset points')

        sns.barplot(x=seg_summary.index, y=seg_summary['revenue'], palette='viridis', ax=ax2)
        ax2.set_title('Total Revenue (BRL) by RFM Segment', fontsize=13, fontweight='bold')
        ax2.set_ylabel('Total Revenue (BRL)')
        ax2.set_xlabel('Segment')
        ax2.yaxis.set_major_formatter('R$ {x:,.0f}')
        ax2.tick_params(axis='x', rotation=30)
        for p in ax2.patches:
            ax2.annotate(f"R$ {p.get_height()/1e6:.2f}M", (p.get_x() + p.get_width() / 2., p.get_height()),
                         ha='center', va='bottom', fontsize=8, xytext=(0, 3), textcoords='offset points')

        plt.tight_layout()
        p2 = os.path.join(FIGURES_DIR, 'rfm_segments_distribution.png')
        plt.savefig(p2, dpi=200)
        plt.close()
        logger.info(f"Saved: {p2}")

    def save_results(self):
        csv_path = os.path.join(PROCESSED_DIR, 'customer_360.csv')
        self.df_c360.to_csv(csv_path, index=False)
        logger.info(f"Overwritten updated customer_360.csv with RFM & ML cluster columns.")

        conn = sqlite3.connect(self.db_path)
        self.df_c360.to_sql('customer_360', conn, if_exists='replace', index=False, chunksize=10000)
        cur = conn.cursor()
        cur.execute("CREATE INDEX IF NOT EXISTS idx_c360_segment ON customer_360(rfm_segment);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_c360_cluster ON customer_360(cluster_kmeans);")
        conn.commit()
        conn.close()
        logger.info("Successfully updated warehouse customer_360 table and created segmentation indexes.")

if __name__ == '__main__':
    segmenter = CustomerSegmenter()
    segmenter.load_data()
    segmenter.calculate_rfm_segments()
    segmenter.run_kmeans_clustering()
    segmenter.save_results()
    print("\nPhase 6 Customer Segmentation Finished Successfully!")
