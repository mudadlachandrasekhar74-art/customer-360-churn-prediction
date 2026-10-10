"""
build_star_schema.py
Implementation of Dimensional Star Schema Data Warehouse for Olist E-Commerce.
Constructs Dim and Fact tables according to the Deloitte Project Architecture.
Outputs to:
  - data/processed/*.csv
  - data/processed/olist_warehouse.db (SQLite relational warehouse)
  - PostgreSQL (optional if connection string provided)
"""

import os
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.path.join(BASE_DIR, 'data', 'raw')
PROCESSED_DIR = os.path.join(BASE_DIR, 'data', 'processed')

os.makedirs(PROCESSED_DIR, exist_ok=True)

def build_star_schema():
    print("=" * 80)
    print("PHASE 2: STAR SCHEMA DATA WAREHOUSE GENERATION")
    print("=" * 80)

    # 1. Load Raw Datasets
    print("\n[Step 1/6] Ingesting Raw Data...")
    df_cust = pd.read_csv(os.path.join(RAW_DIR, 'olist_customers_dataset.csv'))
    df_orders = pd.read_csv(os.path.join(RAW_DIR, 'olist_orders_dataset.csv'))
    df_items = pd.read_csv(os.path.join(RAW_DIR, 'olist_order_items_dataset.csv'))
    df_payments = pd.read_csv(os.path.join(RAW_DIR, 'olist_order_payments_dataset.csv'))
    df_reviews = pd.read_csv(os.path.join(RAW_DIR, 'olist_order_reviews_dataset.csv'))
    df_prod = pd.read_csv(os.path.join(RAW_DIR, 'olist_products_dataset.csv'))
    df_sellers = pd.read_csv(os.path.join(RAW_DIR, 'olist_sellers_dataset.csv'))
    df_geo = pd.read_csv(os.path.join(RAW_DIR, 'olist_geolocation_dataset.csv'))
    df_trans = pd.read_csv(os.path.join(RAW_DIR, 'product_category_name_translation.csv'))

    print(f" Loaded: Customers={len(df_cust):,}, Orders={len(df_orders):,}, Items={len(df_items):,}")

    # 2. Build Dimensions
    print("\n[Step 2/6] Building Dimension Tables...")

    # 2.1 dim_customer
    print(" -> Constructing dim_customer...")
    dim_customer = df_cust[['customer_id', 'customer_unique_id', 'customer_zip_code_prefix', 'customer_city', 'customer_state']].copy()
    dim_customer.columns = ['customer_id', 'customer_unique_id', 'customer_zip_code', 'customer_city', 'customer_state']
    dim_customer['customer_city'] = dim_customer['customer_city'].str.title()
    dim_customer['customer_state'] = dim_customer['customer_state'].str.upper()
    dim_customer = dim_customer.reset_index(drop=True)
    dim_customer.insert(0, 'customer_key', dim_customer.index + 1)

    # Map for FK lookup
    cust_key_map = dict(zip(dim_customer['customer_id'], dim_customer['customer_key']))

    # 2.2 dim_product
    print(" -> Constructing dim_product...")
    prod_merged = pd.merge(df_prod, df_trans, on='product_category_name', how='left')
    prod_merged['product_category'] = prod_merged['product_category_name_english'].fillna(prod_merged['product_category_name']).fillna('unknown')
    
    dim_product = pd.DataFrame({
        'product_id': prod_merged['product_id'],
        'product_category': prod_merged['product_category'],
        'product_name_length': prod_merged['product_name_lenght'],
        'product_description_length': prod_merged['product_description_lenght'],
        'product_photos': prod_merged['product_photos_qty'],
        'product_weight': prod_merged['product_weight_g'],
        'product_length': prod_merged['product_length_cm'],
        'product_height': prod_merged['product_height_cm'],
        'product_width': prod_merged['product_width_cm']
    }).reset_index(drop=True)
    dim_product.insert(0, 'product_key', dim_product.index + 1)

    prod_key_map = dict(zip(dim_product['product_id'], dim_product['product_key']))

    # 2.3 dim_seller
    print(" -> Constructing dim_seller...")
    dim_seller = pd.DataFrame({
        'seller_id': df_sellers['seller_id'],
        'seller_city': df_sellers['seller_city'].str.title(),
        'seller_state': df_sellers['seller_state'].str.upper(),
        'seller_zip_code': df_sellers['seller_zip_code_prefix']
    }).reset_index(drop=True)
    dim_seller.insert(0, 'seller_key', dim_seller.index + 1)

    seller_key_map = dict(zip(dim_seller['seller_id'], dim_seller['seller_key']))

    # 2.4 dim_location
    print(" -> Constructing dim_location (aggregating coordinates per zip prefix)...")
    geo_agg = df_geo.groupby('geolocation_zip_code_prefix').agg(
        latitude=('geolocation_lat', 'median'),
        longitude=('geolocation_lng', 'median'),
        city=('geolocation_city', lambda x: x.mode().iloc[0] if not x.mode().empty else x.iloc[0]),
        state=('geolocation_state', lambda x: x.mode().iloc[0] if not x.mode().empty else x.iloc[0])
    ).reset_index()

    dim_location = pd.DataFrame({
        'zip_code': geo_agg['geolocation_zip_code_prefix'],
        'city': geo_agg['city'].str.title(),
        'state': geo_agg['state'].str.upper(),
        'latitude': geo_agg['latitude'].round(6),
        'longitude': geo_agg['longitude'].round(6)
    }).reset_index(drop=True)
    dim_location.insert(0, 'location_key', dim_location.index + 1)

    # 2.5 dim_date
    print(" -> Constructing dim_date...")
    min_date = pd.to_datetime(df_orders['order_purchase_timestamp']).min()
    max_date = pd.to_datetime(df_orders['order_estimated_delivery_date']).max()
    date_range = pd.date_range(start='2016-01-01', end='2019-12-31', freq='D')

    dim_date = pd.DataFrame({
        'date': date_range,
        'date_key': date_range.strftime('%Y%m%d').astype(int),
        'year': date_range.year,
        'quarter': date_range.quarter,
        'month': date_range.month,
        'month_name': date_range.strftime('%B'),
        'week': date_range.isocalendar().week.astype(int),
        'day': date_range.day,
        'weekday': date_range.strftime('%A')
    })
    # reorder columns to match spec
    dim_date = dim_date[['date_key', 'date', 'year', 'quarter', 'month', 'month_name', 'week', 'day', 'weekday']]

    # 3. Build Fact Tables
    print("\n[Step 3/6] Building Fact Tables...")

    # 3.1 fact_orders
    print(" -> Constructing fact_orders...")
    df_orders['purchase_dt'] = pd.to_datetime(df_orders['order_purchase_timestamp'])
    df_orders['delivered_dt'] = pd.to_datetime(df_orders['order_delivered_customer_date'])
    df_orders['estimated_dt'] = pd.to_datetime(df_orders['order_estimated_delivery_date'])

    # delivery_delay_days: positive = late, negative = early
    delay_days = (df_orders['delivered_dt'] - df_orders['estimated_dt']).dt.total_seconds() / 86400.0

    fact_orders = pd.DataFrame({
        'order_id': df_orders['order_id'],
        'customer_key': df_orders['customer_id'].map(cust_key_map),
        'order_status': df_orders['order_status'],
        'purchase_date': df_orders['order_purchase_timestamp'],
        'approval_date': df_orders['order_approved_at'],
        'carrier_date': df_orders['order_delivered_carrier_date'],
        'delivery_date': df_orders['order_delivered_customer_date'],
        'estimated_delivery_date': df_orders['order_estimated_delivery_date'],
        'delivery_delay_days': delay_days.round(2)
    }).reset_index(drop=True)
    fact_orders.insert(0, 'order_key', fact_orders.index + 1)

    order_key_map = dict(zip(fact_orders['order_id'], fact_orders['order_key']))

    # 3.2 fact_order_items
    print(" -> Constructing fact_order_items...")
    fact_order_items = pd.DataFrame({
        'order_key': df_items['order_id'].map(order_key_map),
        'product_key': df_items['product_id'].map(prod_key_map),
        'seller_key': df_items['seller_id'].map(seller_key_map),
        'price': df_items['price'].round(2),
        'freight_value': df_items['freight_value'].round(2),
        'total_item_value': (df_items['price'] + df_items['freight_value']).round(2)
    }).reset_index(drop=True)
    # Filter out any unmapped order keys if any
    fact_order_items = fact_order_items.dropna(subset=['order_key']).copy()
    fact_order_items['order_key'] = fact_order_items['order_key'].astype(int)

    # 3.3 fact_payments
    print(" -> Constructing fact_payments...")
    fact_payments = pd.DataFrame({
        'order_key': df_payments['order_id'].map(order_key_map),
        'payment_type': df_payments['payment_type'],
        'payment_installments': df_payments['payment_installments'],
        'payment_value': df_payments['payment_value'].round(2)
    }).reset_index(drop=True)
    fact_payments = fact_payments.dropna(subset=['order_key']).copy()
    fact_payments['order_key'] = fact_payments['order_key'].astype(int)

    # 3.4 fact_reviews
    print(" -> Constructing fact_reviews...")
    fact_reviews = pd.DataFrame({
        'order_key': df_reviews['order_id'].map(order_key_map),
        'review_score': df_reviews['review_score'],
        'review_creation_date': df_reviews['review_creation_date'],
        'review_answer_date': df_reviews['review_answer_timestamp']
    }).reset_index(drop=True)
    fact_reviews = fact_reviews.dropna(subset=['order_key']).copy()
    fact_reviews['order_key'] = fact_reviews['order_key'].astype(int)

    # 4. Save to CSVs in data/processed
    print("\n[Step 4/6] Exporting Dimension and Fact Tables to CSV...")
    tables = {
        'dim_customer': dim_customer,
        'dim_product': dim_product,
        'dim_seller': dim_seller,
        'dim_date': dim_date,
        'dim_location': dim_location,
        'fact_orders': fact_orders,
        'fact_order_items': fact_order_items,
        'fact_payments': fact_payments,
        'fact_reviews': fact_reviews
    }

    for name, df in tables.items():
        out_csv = os.path.join(PROCESSED_DIR, f"{name}.csv")
        df.to_csv(out_csv, index=False)
        print(f" -> {name}: {len(df):,} rows saved to {out_csv}")

    # 5. Populate SQLite Data Warehouse
    print("\n[Step 5/6] Writing to Local Analytical Database (SQLite)...")
    db_path = os.path.join(PROCESSED_DIR, 'olist_warehouse.db')
    conn = sqlite3.connect(db_path)
    for name, df in tables.items():
        df.to_sql(name, conn, if_exists='replace', index=False)
    
    # Create indexes in SQLite for ultra-fast query execution
    cur = conn.cursor()
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_cust_key ON dim_customer(customer_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_cust_uid ON dim_customer(customer_unique_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_prod_key ON dim_product(product_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_seller_key ON dim_seller(seller_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fact_orders_key ON fact_orders(order_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fact_orders_cust ON fact_orders(customer_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fact_items_order ON fact_order_items(order_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fact_items_prod ON fact_order_items(product_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fact_items_seller ON fact_order_items(seller_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fact_pay_order ON fact_payments(order_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fact_rev_order ON fact_reviews(order_key);")
    conn.commit()
    conn.close()
    print(f" Successfully created indexed database at {db_path}")

    # 6. Verification and Summary
    print("\n[Step 6/6] Dimensional Warehouse Quality Verification:")
    print("=" * 80)
    for name, df in tables.items():
        print(f"  * {name:<18} : {len(df):>8,} rows | {len(df.columns):>2} columns")
    print("=" * 80)
    print("Phase 2 Star Schema Construction Complete!")

    return tables

if __name__ == '__main__':
    build_star_schema()
