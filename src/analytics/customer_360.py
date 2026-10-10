"""
customer_360.py
Feature Engineering module for Customer 360 & Churn Prediction Platform.
Constructs a unified analytical customer profile table at the customer_unique_id grain.
Calculates RFM metrics, behavioral indicators, and engagement features.
Outputs to:
  - data/processed/customer_360.csv
  - SQLite data warehouse (table: customer_360)
"""

import os
import sys
import sqlite3
import logging
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("Customer360")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROCESSED_DIR = os.path.join(BASE_DIR, 'data', 'processed')
DB_PATH = os.path.join(PROCESSED_DIR, 'olist_warehouse.db')

class Customer360Builder:
    """Builds the unified 360-degree customer feature store."""

    def __init__(self, db_path: str = DB_PATH, output_dir: str = PROCESSED_DIR):
        self.db_path = db_path
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def load_warehouse_tables(self) -> dict:
        logger.info(f"Connecting to data warehouse at {self.db_path}...")
        conn = sqlite3.connect(self.db_path)
        
        tables = {
            'dim_customer': pd.read_sql("SELECT * FROM dim_customer", conn),
            'dim_product': pd.read_sql("SELECT * FROM dim_product", conn),
            'dim_seller': pd.read_sql("SELECT * FROM dim_seller", conn),
            'fact_orders': pd.read_sql("SELECT * FROM fact_orders", conn),
            'fact_order_items': pd.read_sql("SELECT * FROM fact_order_items", conn),
            'fact_payments': pd.read_sql("SELECT * FROM fact_payments", conn),
            'fact_reviews': pd.read_sql("SELECT * FROM fact_reviews", conn)
        }
        conn.close()
        logger.info("Loaded warehouse tables into memory.")
        return tables

    def build_customer_360(self) -> pd.DataFrame:
        logger.info("Starting Customer 360 feature engineering...")
        t = self.load_warehouse_tables()

        df_cust = t['dim_customer']
        df_ord = t['fact_orders']
        df_items = t['fact_order_items']
        df_pay = t['fact_payments']
        df_rev = t['fact_reviews']
        df_prod = t['dim_product']

        # Parse order timestamps
        df_ord['purchase_dt'] = pd.to_datetime(df_ord['purchase_date'])
        df_ord['delivered_dt'] = pd.to_datetime(df_ord['delivery_date'])
        df_ord['estimated_dt'] = pd.to_datetime(df_ord['estimated_delivery_date'])
        
        # Link orders to customers to get customer_unique_id
        ord_cust = pd.merge(
            df_ord,
            df_cust[['customer_key', 'customer_unique_id', 'customer_city', 'customer_state']],
            on='customer_key',
            how='inner'
        )

        # Snapshot date: 1 day past the latest order in the database
        snapshot_date = ord_cust['purchase_dt'].max() + pd.Timedelta(days=1)
        logger.info(f"Analytical snapshot date established as: {snapshot_date}")

        # -------------------------------------------------------------
        # 1. Order-Level Customer Aggregations
        # -------------------------------------------------------------
        logger.info("Calculating RFM and order frequency metrics...")
        
        # Sort by purchase_dt to get latest city/state quickly
        ord_cust = ord_cust.sort_values('purchase_dt')
        
        ord_summary = ord_cust.groupby('customer_unique_id').agg(
            first_order_date=('purchase_dt', 'min'),
            last_order_date=('purchase_dt', 'max'),
            total_orders=('order_key', 'nunique'),
            total_canceled=('order_status', lambda s: (s == 'canceled').sum()),
            customer_city=('customer_city', 'last'),
            customer_state=('customer_state', 'last')
        ).reset_index()

        # Recency in days
        ord_summary['days_since_last_order'] = (snapshot_date - ord_summary['last_order_date']).dt.days
        ord_summary['recency'] = ord_summary['days_since_last_order']
        ord_summary['frequency'] = ord_summary['total_orders']
        ord_summary['cancellation_rate'] = (ord_summary['total_canceled'] / ord_summary['total_orders']).round(4)

        # -------------------------------------------------------------
        # 2. Financial Metrics (Monetary Value, AOV)
        # -------------------------------------------------------------
        logger.info("Calculating monetary spend and line-item metrics...")
        items_with_cust = pd.merge(
            df_items,
            ord_cust[['order_key', 'customer_unique_id']],
            on='order_key',
            how='inner'
        )

        fin_summary = items_with_cust.groupby('customer_unique_id').agg(
            total_revenue=('price', 'sum'),
            total_freight=('freight_value', 'sum'),
            total_items=('product_key', 'count'),
            number_of_sellers=('seller_key', 'nunique')
        ).reset_index()

        fin_summary['monetary_value'] = fin_summary['total_revenue'].round(2)
        fin_summary['total_spend'] = (fin_summary['total_revenue'] + fin_summary['total_freight']).round(2)

        # -------------------------------------------------------------
        # 3. Product Category Preferences
        # -------------------------------------------------------------
        logger.info("Computing product category diversity and preferences...")
        items_prod = pd.merge(
            items_with_cust,
            df_prod[['product_key', 'product_category']],
            on='product_key',
            how='inner'
        )

        # Efficient preferred category: most frequent per customer
        cat_counts = items_prod.groupby(['customer_unique_id', 'product_category']).size().reset_index(name='n')
        cat_counts = cat_counts.sort_values(['customer_unique_id', 'n'], ascending=[True, False])
        top_cats = cat_counts.drop_duplicates(subset=['customer_unique_id']).rename(columns={'product_category': 'preferred_category'})

        cat_div = items_prod.groupby('customer_unique_id')['product_category'].nunique().reset_index(name='number_of_categories')
        cat_summary = pd.merge(top_cats[['customer_unique_id', 'preferred_category']], cat_div, on='customer_unique_id')

        # -------------------------------------------------------------
        # 4. Payment Behavior
        # -------------------------------------------------------------
        logger.info("Analyzing payment behaviors and installment tenures...")
        pay_cust = pd.merge(
            df_pay,
            ord_cust[['order_key', 'customer_unique_id']],
            on='order_key',
            how='inner'
        )

        pay_counts = pay_cust.groupby(['customer_unique_id', 'payment_type']).size().reset_index(name='n')
        pay_counts = pay_counts.sort_values(['customer_unique_id', 'n'], ascending=[True, False])
        top_pay = pay_counts.drop_duplicates(subset=['customer_unique_id']).rename(columns={'payment_type': 'preferred_payment_method'})

        pay_inst = pay_cust.groupby('customer_unique_id')['payment_installments'].mean().round(1).reset_index(name='avg_installments')
        pay_summary = pd.merge(top_pay[['customer_unique_id', 'preferred_payment_method']], pay_inst, on='customer_unique_id')

        # -------------------------------------------------------------
        # 5. CSAT & Delivery Fulfillment Experience
        # -------------------------------------------------------------
        logger.info("Analyzing review satisfaction and delivery delays...")
        rev_cust = pd.merge(
            df_rev,
            ord_cust[['order_key', 'customer_unique_id']],
            on='order_key',
            how='inner'
        )

        rev_summary = rev_cust.groupby('customer_unique_id').agg(
            average_review_score=('review_score', 'mean')
        ).reset_index()
        rev_summary['average_review_score'] = rev_summary['average_review_score'].round(2)

        # Delivery delay metrics on delivered orders
        deliv_cust = ord_cust[ord_cust['order_status'] == 'delivered'].copy()
        deliv_summary = deliv_cust.groupby('customer_unique_id').agg(
            delivered_orders=('order_key', 'count'),
            late_orders=('delivery_delay_days', lambda d: (d > 0).sum()),
            average_delivery_delay=('delivery_delay_days', 'mean')
        ).reset_index()

        deliv_summary['late_delivery_rate'] = np.where(
            deliv_summary['delivered_orders'] > 0,
            (deliv_summary['late_orders'] / deliv_summary['delivered_orders']).round(4),
            0.0
        )
        deliv_summary['average_delivery_delay'] = deliv_summary['average_delivery_delay'].fillna(0.0).round(2)

        # -------------------------------------------------------------
        # 6. Merge Into Customer 360 Table
        # -------------------------------------------------------------
        logger.info("Assembling consolidated Customer 360 dataset...")
        c360 = ord_summary.merge(fin_summary, on='customer_unique_id', how='left')
        c360 = c360.merge(cat_summary, on='customer_unique_id', how='left')
        c360 = c360.merge(pay_summary, on='customer_unique_id', how='left')
        c360 = c360.merge(rev_summary, on='customer_unique_id', how='left')
        c360 = c360.merge(deliv_summary[['customer_unique_id', 'late_delivery_rate', 'average_delivery_delay']], on='customer_unique_id', how='left')

        # Fill potential NaNs for customers with unfulfilled orders
        c360['total_revenue'] = c360['total_revenue'].fillna(0.0).round(2)
        c360['monetary_value'] = c360['monetary_value'].fillna(0.0).round(2)
        c360['total_spend'] = c360['total_spend'].fillna(0.0).round(2)
        c360['total_items'] = c360['total_items'].fillna(0).astype(int)
        c360['number_of_sellers'] = c360['number_of_sellers'].fillna(0).astype(int)
        c360['number_of_categories'] = c360['number_of_categories'].fillna(0).astype(int)
        c360['preferred_category'] = c360['preferred_category'].fillna('unknown')
        c360['preferred_payment_method'] = c360['preferred_payment_method'].fillna('unknown')
        c360['average_review_score'] = c360['average_review_score'].fillna(c360['average_review_score'].median()).round(2)
        c360['late_delivery_rate'] = c360['late_delivery_rate'].fillna(0.0)
        c360['average_delivery_delay'] = c360['average_delivery_delay'].fillna(0.0)

        # Derived business fields
        c360['average_order_value'] = (c360['total_revenue'] / c360['total_orders']).round(2)
        
        # Customer tenure in days
        c360['tenure_days'] = (snapshot_date - c360['first_order_date']).dt.days
        # Purchase frequency: orders per month of tenure (minimum 1 month base)
        c360['purchase_frequency'] = (c360['total_orders'] / ((c360['tenure_days'] / 30.0).clip(lower=1.0))).round(4)

        # Engagement Flags
        c360['repeat_customer_flag'] = (c360['total_orders'] > 1).astype(int)
        
        # High value flag: Top 80th percentile of monetary spend
        revenue_80th_pctl = c360['total_revenue'].quantile(0.80)
        c360['high_value_customer_flag'] = (c360['total_revenue'] >= revenue_80th_pctl).astype(int)
        logger.info(f"High-Value Customer threshold (80th percentile): R$ {revenue_80th_pctl:.2f}")

        # Final column arrangement
        cols_order = [
            'customer_unique_id',
            'customer_city',
            'customer_state',
            'first_order_date',
            'last_order_date',
            'days_since_last_order',
            'recency',
            'frequency',
            'monetary_value',
            'total_orders',
            'total_revenue',
            'total_spend',
            'average_order_value',
            'total_items',
            'average_review_score',
            'cancellation_rate',
            'late_delivery_rate',
            'average_delivery_delay',
            'preferred_payment_method',
            'avg_installments',
            'preferred_category',
            'number_of_categories',
            'number_of_sellers',
            'tenure_days',
            'purchase_frequency',
            'repeat_customer_flag',
            'high_value_customer_flag'
        ]
        c360 = c360[cols_order].copy()
        c360['first_order_date'] = c360['first_order_date'].astype(str)
        c360['last_order_date'] = c360['last_order_date'].astype(str)

        logger.info(f"Customer 360 build complete: {len(c360):,} unique customers, {len(c360.columns)} attributes.")
        return c360

    def save_customer_360(self, c360: pd.DataFrame):
        # 1. Save CSV
        csv_path = os.path.join(self.output_dir, 'customer_360.csv')
        c360.to_csv(csv_path, index=False)
        logger.info(f"Exported customer_360.csv ({len(c360):,} rows) to {csv_path}")

        # 2. Save to SQLite warehouse
        conn = sqlite3.connect(self.db_path)
        logger.info("Writing customer_360 table to data warehouse...")
        c360.to_sql('customer_360', conn, if_exists='replace', index=False, chunksize=10000)
        
        # Create indexes
        cur = conn.cursor()
        cur.execute("CREATE INDEX IF NOT EXISTS idx_c360_uid ON customer_360(customer_unique_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_c360_state ON customer_360(customer_state);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_c360_repeat ON customer_360(repeat_customer_flag);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_c360_hvc ON customer_360(high_value_customer_flag);")
        conn.commit()
        conn.close()
        logger.info("Customer 360 table and indexes saved to warehouse successfully.")

if __name__ == '__main__':
    builder = Customer360Builder()
    df_c360 = builder.build_customer_360()
    builder.save_customer_360(df_c360)
    print("\nPhase 5 Customer 360 Feature Engineering Finished Successfully!")
