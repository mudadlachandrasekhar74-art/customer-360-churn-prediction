"""
data_quality.py
Dedicated Enterprise Data Quality & Governance Framework for Olist E-Commerce.
Audits the platform across 4 core governance pillars:
  1. Completeness
  2. Accuracy
  3. Consistency
  4. Referential Integrity
Generates reports/data_quality_report.csv and computes the composite DATA QUALITY SCORE.
"""

import os
import sys
import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("DataGovernance")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE_DIR, 'data', 'raw')
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')

class DataQualityFramework:
    """Enterprise Data Quality & Governance Engine."""

    def __init__(self, raw_dir: str = RAW_DIR, reports_dir: str = REPORTS_DIR):
        self.raw_dir = raw_dir
        self.reports_dir = reports_dir
        os.makedirs(self.reports_dir, exist_ok=True)
        self.rules_log: List[Dict[str, Any]] = []

    def load_datasets(self) -> Dict[str, pd.DataFrame]:
        logger.info("Loading raw operational datasets for data quality audit...")
        return {
            'customers': pd.read_csv(os.path.join(self.raw_dir, 'olist_customers_dataset.csv')),
            'orders': pd.read_csv(os.path.join(self.raw_dir, 'olist_orders_dataset.csv')),
            'order_items': pd.read_csv(os.path.join(self.raw_dir, 'olist_order_items_dataset.csv')),
            'payments': pd.read_csv(os.path.join(self.raw_dir, 'olist_order_payments_dataset.csv')),
            'reviews': pd.read_csv(os.path.join(self.raw_dir, 'olist_order_reviews_dataset.csv')),
            'products': pd.read_csv(os.path.join(self.raw_dir, 'olist_products_dataset.csv')),
            'sellers': pd.read_csv(os.path.join(self.raw_dir, 'olist_sellers_dataset.csv')),
            'category_translation': pd.read_csv(os.path.join(self.raw_dir, 'product_category_name_translation.csv'))
        }

    def _record_result(self, rule_name: str, category: str, dataset: str, records_checked: int, failed_records: int, criticality: str = "HIGH"):
        fail_pct = round((failed_records / records_checked * 100), 4) if records_checked > 0 else 0.0
        
        # Status threshold
        if failed_records == 0:
            status = "PASSED"
        elif fail_pct < 2.0 and criticality != "HIGH":
            status = "WARNING"
        elif fail_pct < 0.5 and criticality == "HIGH":
            status = "WARNING"
        else:
            status = "FAILED"

        entry = {
            'rule_name': rule_name,
            'category': category,
            'dataset': dataset,
            'criticality': criticality,
            'records_checked': records_checked,
            'failed_records': failed_records,
            'failure_percentage': fail_pct,
            'status': status
        }
        self.rules_log.append(entry)
        logger.info(f"Rule [{category}] {rule_name:<38} | Checked: {records_checked:>7,} | Failed: {failed_records:>6,} ({fail_pct:>6.2f}%) | Status: {status}")

    # =========================================================================
    # 1. COMPLETENESS AUDITS
    # =========================================================================
    def audit_completeness(self, dfs: Dict[str, pd.DataFrame]):
        logger.info("Executing Pillar 1: Completeness Audits...")

        # Rule 1: Missing Customer IDs in customers dataset
        n_cust = len(dfs['customers'])
        missing_cust_id = dfs['customers']['customer_id'].isnull().sum()
        self._record_result("Missing Customer IDs", "Completeness", "customers", n_cust, missing_cust_id, "HIGH")

        # Rule 2: Missing Order Purchase Dates in orders
        n_ord = len(dfs['orders'])
        missing_ord_date = dfs['orders']['order_purchase_timestamp'].isnull().sum()
        self._record_result("Missing Order Purchase Dates", "Completeness", "orders", n_ord, missing_ord_date, "HIGH")

        # Rule 3: Missing Product Information (Category Name) in products
        n_prod = len(dfs['products'])
        missing_prod_cat = dfs['products']['product_category_name'].isnull().sum()
        self._record_result("Missing Product Categories", "Completeness", "products", n_prod, missing_prod_cat, "MEDIUM")

        # Rule 4: Missing Product Dimensions (Weight, Dimensions)
        missing_dimensions = dfs['products'][['product_weight_g', 'product_length_cm', 'product_height_cm', 'product_width_cm']].isnull().any(axis=1).sum()
        self._record_result("Missing Product Physical Dimensions", "Completeness", "products", n_prod, missing_dimensions, "LOW")

        # Rule 5: Missing Review Scores in reviews
        n_rev = len(dfs['reviews'])
        missing_rev_score = dfs['reviews']['review_score'].isnull().sum()
        self._record_result("Missing Review Scores", "Completeness", "reviews", n_rev, missing_rev_score, "HIGH")

    # =========================================================================
    # 2. ACCURACY AUDITS
    # =========================================================================
    def audit_accuracy(self, dfs: Dict[str, pd.DataFrame]):
        logger.info("Executing Pillar 2: Accuracy Audits...")

        # Rule 1: Negative or Zero Prices in order_items
        n_items = len(dfs['order_items'])
        non_pos_prices = (dfs['order_items']['price'] <= 0).sum()
        self._record_result("Negative or Zero Item Prices", "Accuracy", "order_items", n_items, non_pos_prices, "HIGH")

        # Rule 2: Negative Freight Values in order_items
        neg_freight = (dfs['order_items']['freight_value'] < 0).sum()
        self._record_result("Negative Freight Values", "Accuracy", "order_items", n_items, neg_freight, "HIGH")

        # Rule 3: Non-Positive Payment Values in payments
        n_pay = len(dfs['payments'])
        invalid_pay_val = (dfs['payments']['payment_value'] <= 0).sum()
        self._record_result("Zero or Negative Payment Values", "Accuracy", "payments", n_pay, invalid_pay_val, "HIGH")

        # Rule 4: Impossible Delivery Dates (Delivery Date before Purchase Date)
        orders = dfs['orders'].copy()
        orders['purchase_dt'] = pd.to_datetime(orders['order_purchase_timestamp'], errors='coerce')
        orders['delivered_dt'] = pd.to_datetime(orders['order_delivered_customer_date'], errors='coerce')
        delivered_orders = orders.dropna(subset=['purchase_dt', 'delivered_dt'])
        impossible_delivery = (delivered_orders['delivered_dt'] < delivered_orders['purchase_dt']).sum()
        self._record_result("Delivery Date Prior to Purchase Date", "Accuracy", "orders", len(delivered_orders), impossible_delivery, "HIGH")

        # Rule 5: Review Score Out of Bounds (Not in range 1-5)
        n_rev = len(dfs['reviews'])
        invalid_scores = (~dfs['reviews']['review_score'].isin([1, 2, 3, 4, 5])).sum()
        self._record_result("Out-of-Range Review Scores", "Accuracy", "reviews", n_rev, invalid_scores, "HIGH")

        # Rule 6: Payment Installments Less than 1
        invalid_installments = (dfs['payments']['payment_installments'] < 1).sum()
        self._record_result("Zero or Negative Payment Installments", "Accuracy", "payments", n_pay, invalid_installments, "MEDIUM")

    # =========================================================================
    # 3. CONSISTENCY AUDITS
    # =========================================================================
    def audit_consistency(self, dfs: Dict[str, pd.DataFrame]):
        logger.info("Executing Pillar 3: Consistency Audits...")

        # Rule 1: Duplicate Customer Primary Identifiers
        n_cust = len(dfs['customers'])
        dup_cust = dfs['customers']['customer_id'].duplicated().sum()
        self._record_result("Duplicate Customer IDs", "Consistency", "customers", n_cust, dup_cust, "HIGH")

        # Rule 2: Duplicate Order Primary Identifiers
        n_ord = len(dfs['orders'])
        dup_ord = dfs['orders']['order_id'].duplicated().sum()
        self._record_result("Duplicate Order IDs", "Consistency", "orders", n_ord, dup_ord, "HIGH")

        # Rule 3: Duplicate Order-Item Line Composite Keys
        n_items = len(dfs['order_items'])
        dup_items = dfs['order_items'].duplicated(subset=['order_id', 'order_item_id']).sum()
        self._record_result("Duplicate Order-Item Composite Keys", "Consistency", "order_items", n_items, dup_items, "HIGH")

        # Rule 4: Invalid Brazilian State Codes (Customer UF != 2-letter uppercase)
        valid_ufs = {'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA',
                     'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN',
                     'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO'}
        invalid_cust_states = (~dfs['customers']['customer_state'].str.upper().isin(valid_ufs)).sum()
        self._record_result("Invalid Customer State Codes (UF)", "Consistency", "customers", n_cust, invalid_cust_states, "HIGH")

        # Rule 5: Untranslated Product Categories
        known_cats = set(dfs['category_translation']['product_category_name'])
        prod_cats = dfs['products']['product_category_name'].dropna()
        untranslated = (~prod_cats.isin(known_cats)).sum()
        self._record_result("Untranslated Product Categories", "Consistency", "products", len(prod_cats), untranslated, "MEDIUM")

    # =========================================================================
    # 4. REFERENTIAL INTEGRITY AUDITS
    # =========================================================================
    def audit_referential_integrity(self, dfs: Dict[str, pd.DataFrame]):
        logger.info("Executing Pillar 4: Referential Integrity Audits...")

        # Rule 1: Orders referencing missing Customers
        n_ord = len(dfs['orders'])
        cust_set = set(dfs['customers']['customer_id'])
        orphaned_orders = (~dfs['orders']['customer_id'].isin(cust_set)).sum()
        self._record_result("Orders -> Customers Referential Link", "Referential Integrity", "orders -> customers", n_ord, orphaned_orders, "HIGH")

        # Rule 2: Order Items referencing missing Orders
        n_items = len(dfs['order_items'])
        order_set = set(dfs['orders']['order_id'])
        orphaned_items = (~dfs['order_items']['order_id'].isin(order_set)).sum()
        self._record_result("Order Items -> Orders Referential Link", "Referential Integrity", "order_items -> orders", n_items, orphaned_items, "HIGH")

        # Rule 3: Order Items referencing missing Products
        prod_set = set(dfs['products']['product_id'])
        orphaned_item_prods = (~dfs['order_items']['product_id'].isin(prod_set)).sum()
        self._record_result("Order Items -> Products Referential Link", "Referential Integrity", "order_items -> products", n_items, orphaned_item_prods, "HIGH")

        # Rule 4: Order Items referencing missing Sellers
        seller_set = set(dfs['sellers']['seller_id'])
        orphaned_item_sellers = (~dfs['order_items']['seller_id'].isin(seller_set)).sum()
        self._record_result("Order Items -> Sellers Referential Link", "Referential Integrity", "order_items -> sellers", n_items, orphaned_item_sellers, "HIGH")

        # Rule 5: Payments referencing missing Orders
        n_pay = len(dfs['payments'])
        orphaned_payments = (~dfs['payments']['order_id'].isin(order_set)).sum()
        self._record_result("Payments -> Orders Referential Link", "Referential Integrity", "payments -> orders", n_pay, orphaned_payments, "HIGH")

        # Rule 6: Reviews referencing missing Orders
        n_rev = len(dfs['reviews'])
        orphaned_reviews = (~dfs['reviews']['order_id'].isin(order_set)).sum()
        self._record_result("Reviews -> Orders Referential Link", "Referential Integrity", "reviews -> orders", n_rev, orphaned_reviews, "HIGH")

    # =========================================================================
    # COMPOSITE DATA QUALITY SCORE & EXPORT
    # =========================================================================
    def calculate_data_quality_score(self) -> float:
        """
        Calculates a composite Data Quality Score on a 0 - 100% scale.
        Weights assigned by Governance Pillar:
          - Referential Integrity: 30%
          - Accuracy: 30%
          - Consistency: 20%
          - Completeness: 20%
        """
        weights = {
            'Referential Integrity': 0.30,
            'Accuracy': 0.30,
            'Consistency': 0.20,
            'Completeness': 0.20
        }

        df_report = pd.DataFrame(self.rules_log)
        pillar_scores = {}

        for pillar, weight in weights.items():
            pillar_rules = df_report[df_report['category'] == pillar]
            if len(pillar_rules) > 0:
                # Average pass rate of rules in this pillar
                pass_rates = 100.0 - pillar_rules['failure_percentage']
                pillar_scores[pillar] = pass_rates.mean()
            else:
                pillar_scores[pillar] = 100.0

        overall_score = sum(pillar_scores[p] * weights[p] for p in weights)
        return round(overall_score, 2), pillar_scores

    def run_all_audits(self) -> pd.DataFrame:
        dfs = self.load_datasets()
        self.rules_log.clear()

        self.audit_completeness(dfs)
        self.audit_accuracy(dfs)
        self.audit_consistency(dfs)
        self.audit_referential_integrity(dfs)

        overall_score, pillar_scores = self.calculate_data_quality_score()
        df_report = pd.DataFrame(self.rules_log)

        # Output to CSV
        report_path = os.path.join(self.reports_dir, 'data_quality_report.csv')
        df_report.to_csv(report_path, index=False)
        logger.info(f"Data Quality Report successfully written to: {report_path}")

        print("\n" + "=" * 85)
        print("DELOITTE ENTERPRISE DATA QUALITY & GOVERNANCE REPORT")
        print("=" * 85)
        print(f"OVERALL DATA QUALITY SCORE: {overall_score:.2f}% / 100.00%")
        print("-" * 85)
        for pillar, score in pillar_scores.items():
            print(f"  * {pillar:<25} Pillar Score: {score:>6.2f}%")
        print("=" * 85)

        return df_report

if __name__ == '__main__':
    framework = DataQualityFramework()
    framework.run_all_audits()
