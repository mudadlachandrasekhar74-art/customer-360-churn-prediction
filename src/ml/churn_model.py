"""
churn_model.py
Machine Learning Churn Prediction Pipeline for Olist E-Commerce.
Trains Logistic Regression, Random Forest, and XGBoost models to predict churn_flag
without data leakage, prioritizing Recall, F1-score, and ROC-AUC.
Outputs:
  - Model metrics comparison
  - Diagnostic figures (ROC curves, Confusion Matrices)
  - Trained model persistence (joblib)
  - Churn probabilities & risk levels added to customer_360
"""

import os
import sys
import sqlite3
import joblib
import logging
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, confusion_matrix, roc_curve, classification_report
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("ChurnModel")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROCESSED_DIR = os.path.join(BASE_DIR, 'data', 'processed')
FIGURES_DIR = os.path.join(BASE_DIR, 'reports', 'figures')
ML_DIR = os.path.join(BASE_DIR, 'src', 'ml')
DB_PATH = os.path.join(PROCESSED_DIR, 'olist_warehouse.db')

os.makedirs(FIGURES_DIR, exist_ok=True)
os.makedirs(ML_DIR, exist_ok=True)

class ChurnModelTrainer:
    """End-to-end churn model engineering, training, and evaluation suite."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.df_c360 = None
        self.models = {}
        self.metrics_report = []

    def load_and_prepare_data(self):
        logger.info("Loading customer_360 dataset from analytical warehouse...")
        self.df_c360 = pd.read_sql("SELECT * FROM customer_360", self.conn)
        logger.info(f"Loaded {len(self.df_c360):,} customers.")

        # STRICT DATA LEAKAGE PREVENTION:
        # Exclude: recency, days_since_last_order, last_order_date, first_order_date, tenure_days, purchase_frequency,
        # and segmentation tags derived from recency (rfm_score, rfm_segment, cluster_kmeans, cluster_label).
        feature_cols_num = [
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
            'high_value_customer_flag'
        ]

        feature_cols_cat = [
            'preferred_payment_method',
            'customer_state'
        ]

        logger.info(f"Selected {len(feature_cols_num)} numerical features and {len(feature_cols_cat)} categorical features.")
        logger.info(f"Target variable: 'churn_flag' (Class balance: {self.df_c360['churn_flag'].value_counts(normalize=True).to_dict()})")

        X = self.df_c360[feature_cols_num + feature_cols_cat].copy()
        y = self.df_c360['churn_flag'].copy()

        # Stratified 80/20 train/test split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.20, random_state=42, stratify=y
        )
        logger.info(f"Split data into Train: {X_train.shape[0]:,} records, Test: {X_test.shape[0]:,} records.")

        return X, y, X_train, X_test, y_train, y_test, feature_cols_num, feature_cols_cat

    def build_preprocessor(self, num_cols, cat_cols):
        from sklearn.impute import SimpleImputer

        num_transformer = Pipeline(steps=[
            ('imputer', SimpleImputer(strategy='median')),
            ('scaler', StandardScaler())
        ])

        cat_transformer = Pipeline(steps=[
            ('imputer', SimpleImputer(strategy='most_frequent')),
            ('onehot', OneHotEncoder(handle_unknown='ignore', sparse_output=False))
        ])

        preprocessor = ColumnTransformer(
            transformers=[
                ('num', num_transformer, num_cols),
                ('cat', cat_transformer, cat_cols)
            ]
        )
        return preprocessor

    def train_and_evaluate_models(self):
        X, y, X_train, X_test, y_train, y_test, num_cols, cat_cols = self.load_and_prepare_data()
        preprocessor = self.build_preprocessor(num_cols, cat_cols)

        # Scale pos weight for XGBoost
        neg_count = (y_train == 0).sum()
        pos_count = (y_train == 1).sum()
        scale_pos_weight = neg_count / pos_count if pos_count > 0 else 1.0

        candidate_configs = {
            'Logistic Regression': (
                LogisticRegression(class_weight='balanced', max_iter=1000, random_state=42)
            ),
            'Random Forest': (
                RandomForestClassifier(
                    n_estimators=150,
                    max_depth=12,
                    min_samples_split=10,
                    class_weight='balanced',
                    random_state=42,
                    n_jobs=-1
                )
            ),
            'XGBoost': (
                XGBClassifier(
                    n_estimators=150,
                    max_depth=5,
                    learning_rate=0.08,
                    scale_pos_weight=scale_pos_weight,
                    eval_metric='logloss',
                    random_state=42,
                    n_jobs=-1
                )
            )
        }

        eval_results = {}

        print("\n" + "=" * 90)
        print("CHURN MODEL EVALUATION BENCHMARK")
        print("=" * 90)

        for name, clf in candidate_configs.items():
            logger.info(f"Training {name} pipeline...")
            pipe = Pipeline(steps=[
                ('preprocessor', preprocessor),
                ('classifier', clf)
            ])

            pipe.fit(X_train, y_train)
            y_pred = pipe.predict(X_test)
            y_prob = pipe.predict_proba(X_test)[:, 1]

            acc = accuracy_score(y_test, y_pred)
            prec = precision_score(y_test, y_pred, zero_division=0)
            rec = recall_score(y_test, y_pred)
            f1 = f1_score(y_test, y_pred)
            auc = roc_auc_score(y_test, y_prob)
            cm = confusion_matrix(y_test, y_pred)

            eval_results[name] = {
                'pipeline': pipe,
                'accuracy': acc,
                'precision': prec,
                'recall': rec,
                'f1': f1,
                'roc_auc': auc,
                'confusion_matrix': cm,
                'y_prob': y_prob
            }

            self.metrics_report.append({
                'Model': name,
                'Accuracy': round(acc, 4),
                'Precision': round(prec, 4),
                'Recall': round(rec, 4),
                'F1-Score': round(f1, 4),
                'ROC-AUC': round(auc, 4)
            })

            print(f"\nModel: {name}")
            print(f"  Accuracy  : {acc*100:.2f}%")
            print(f"  Precision : {prec*100:.2f}%")
            print(f"  Recall    : {rec*100:.2f}% (Prioritized for Churn Mitigation)")
            print(f"  F1-Score  : {f1:.4f}")
            print(f"  ROC-AUC   : {auc:.4f}")
            print(f"  Confusion Matrix: TN={cm[0,0]:,}, FP={cm[0,1]:,}, FN={cm[1,0]:,}, TP={cm[1,1]:,}")

        print("\n" + "=" * 90)
        print("MODEL COMPARISON SUMMARY")
        print("=" * 90)
        df_bench = pd.DataFrame(self.metrics_report)
        print(df_bench.to_string(index=False))
        print("=" * 90)

        # Plot ROC curves and confusion matrices
        self._plot_model_diagnostics(eval_results, y_test)

        # Select Best Model based on F1-Score & ROC-AUC
        best_model_name = max(eval_results, key=lambda k: eval_results[k]['f1'])
        best_pipeline = eval_results[best_model_name]['pipeline']
        logger.info(f"Champion Model selected: {best_model_name} (F1: {eval_results[best_model_name]['f1']:.4f}, AUC: {eval_results[best_model_name]['roc_auc']:.4f})")

        # Save champion model
        model_save_path = os.path.join(ML_DIR, 'churn_champion_pipeline.joblib')
        joblib.dump(best_pipeline, model_save_path)
        logger.info(f"Persisted champion model to {model_save_path}")

        # Compute Churn Probabilities & Risk Levels for all customers
        logger.info("Computing churn probabilities across entire customer base...")
        all_probs = best_pipeline.predict_proba(X)[:, 1]
        self.df_c360['churn_probability'] = np.round(all_probs, 4)

        # Define Risk Level:
        # High Risk: churn_prob >= 0.70
        # Medium Risk: 0.40 <= churn_prob < 0.70
        # Low Risk: churn_prob < 0.40
        conditions = [
            (self.df_c360['churn_probability'] >= 0.70),
            (self.df_c360['churn_probability'] >= 0.40) & (self.df_c360['churn_probability'] < 0.70),
            (self.df_c360['churn_probability'] < 0.40)
        ]
        choices = ['High Risk', 'Medium Risk', 'Low Risk']
        self.df_c360['risk_level'] = np.select(conditions, choices, default='Medium Risk')

        logger.info("Risk Level distribution across customer base:")
        print(self.df_c360['risk_level'].value_counts())

        # Update CSV and SQLite table
        csv_path = os.path.join(PROCESSED_DIR, 'customer_360.csv')
        self.df_c360.to_csv(csv_path, index=False)
        logger.info(f"Exported updated customer_360.csv with churn predictions.")

        self.df_c360.to_sql('customer_360', self.conn, if_exists='replace', index=False, chunksize=10000)
        cur = self.conn.cursor()
        cur.execute("CREATE INDEX IF NOT EXISTS idx_c360_risk ON customer_360(risk_level);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_c360_prob ON customer_360(churn_probability);")
        self.conn.commit()
        logger.info("Updated warehouse customer_360 table and created churn prediction indexes.")

        return df_bench, best_model_name

    def _plot_model_diagnostics(self, eval_results, y_test):
        logger.info("Generating ROC curves and confusion matrix charts...")

        # 1. ROC Curves
        plt.figure(figsize=(9, 6))
        for name, res in eval_results.items():
            fpr, tpr, _ = roc_curve(y_test, res['y_prob'])
            plt.plot(fpr, tpr, linewidth=2, label=f"{name} (AUC = {res['roc_auc']:.3f})")

        plt.plot([0, 1], [0, 1], 'k--', alpha=0.5, label='Random Chance (AUC = 0.500)')
        plt.title('Receiver Operating Characteristic (ROC) Comparison', fontsize=13, fontweight='bold', pad=12)
        plt.xlabel('False Positive Rate (1 - Specificity)', fontsize=11)
        plt.ylabel('True Positive Rate (Recall / Sensitivity)', fontsize=11)
        plt.legend(loc='lower right', fontsize=10)
        plt.grid(True, linestyle='--', alpha=0.6)
        plt.tight_layout()
        roc_path = os.path.join(FIGURES_DIR, 'churn_model_roc_curves.png')
        plt.savefig(roc_path, dpi=200)
        plt.close()
        logger.info(f"Saved: {roc_path}")

        # 2. Confusion Matrices Comparison
        fig, axes = plt.subplots(1, 3, figsize=(16, 4.5))
        for ax, (name, res) in zip(axes, eval_results.items()):
            cm = res['confusion_matrix']
            sns.heatmap(cm, annot=True, fmt=',d', cmap='Blues', cbar=False, ax=ax,
                        annot_kws={'size': 11, 'weight': 'bold'})
            ax.set_title(f"{name}\nRecall: {res['recall']*100:.1f}% | Prec: {res['precision']*100:.1f}%", fontsize=11, fontweight='bold')
            ax.set_xlabel('Predicted Label', fontsize=10)
            ax.set_ylabel('Actual Label', fontsize=10)
            ax.set_xticklabels(['Active (0)', 'Churned (1)'])
            ax.set_yticklabels(['Active (0)', 'Churned (1)'])

        plt.tight_layout()
        cm_path = os.path.join(FIGURES_DIR, 'churn_confusion_matrices.png')
        plt.savefig(cm_path, dpi=200)
        plt.close()
        logger.info(f"Saved: {cm_path}")

    def close(self):
        self.conn.close()

if __name__ == '__main__':
    trainer = ChurnModelTrainer()
    df_bench, best_model = trainer.train_and_evaluate_models()
    trainer.close()
    print("\nPhase 8 Churn Prediction Modeling Finished Successfully!")
