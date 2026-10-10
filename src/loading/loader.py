"""
loader.py
Database loading and data mart export module for Customer 360 & Churn Prediction Platform.
Loads data into relational staging and star-schema warehouse tables (PostgreSQL / SQLite)
and exports CSV marts with integrity checks and indexing.
"""

import os
import sqlite3
import logging
import pandas as pd
from typing import Dict, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("ETL.Loader")

class WarehouseLoader:
    """Loads staged and dimensional data into persistent relational storage and CSV marts."""

    def __init__(self, db_path: str, pg_conn_str: Optional[str] = None):
        self.db_path = db_path
        self.pg_conn_str = pg_conn_str or os.getenv("DATABASE_URL")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def load_to_sqlite(self, tables: Dict[str, pd.DataFrame], prefix: str = "") -> None:
        logger.info(f"Connecting to SQLite data warehouse at: {self.db_path}")
        conn = sqlite3.connect(self.db_path)

        for name, df in tables.items():
            table_name = f"{prefix}{name}"
            logger.info(f"Loading table '{table_name}' ({len(df):,} rows)...")
            df.to_sql(table_name, conn, if_exists='replace', index=False, chunksize=10000)

        conn.commit()
        conn.close()
        logger.info("SQLite table loading complete.")

    def create_indexes(self) -> None:
        logger.info("Creating analytical B-Tree indexes in warehouse...")
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        index_statements = [
            "CREATE INDEX IF NOT EXISTS idx_dim_cust_key ON dim_customer(customer_key);",
            "CREATE INDEX IF NOT EXISTS idx_dim_cust_uid ON dim_customer(customer_unique_id);",
            "CREATE INDEX IF NOT EXISTS idx_dim_prod_key ON dim_product(product_key);",
            "CREATE INDEX IF NOT EXISTS idx_dim_seller_key ON dim_seller(seller_key);",
            "CREATE INDEX IF NOT EXISTS idx_fact_orders_key ON fact_orders(order_key);",
            "CREATE INDEX IF NOT EXISTS idx_fact_orders_cust ON fact_orders(customer_key);",
            "CREATE INDEX IF NOT EXISTS idx_fact_items_order ON fact_order_items(order_key);",
            "CREATE INDEX IF NOT EXISTS idx_fact_items_prod ON fact_order_items(product_key);",
            "CREATE INDEX IF NOT EXISTS idx_fact_items_seller ON fact_order_items(seller_key);",
            "CREATE INDEX IF NOT EXISTS idx_fact_pay_order ON fact_payments(order_key);",
            "CREATE INDEX IF NOT EXISTS idx_fact_rev_order ON fact_reviews(order_key);"
        ]

        for stmt in index_statements:
            cur.execute(stmt)

        conn.commit()
        conn.close()
        logger.info("Warehouse indexes successfully generated.")

    def export_csv_marts(self, tables: Dict[str, pd.DataFrame], output_dir: str) -> None:
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Exporting processed CSV data marts to: {output_dir}")
        for name, df in tables.items():
            path = os.path.join(output_dir, f"{name}.csv")
            df.to_csv(path, index=False)
            logger.info(f"Saved {name}.csv ({len(df):,} records)")

    def load_to_postgres(self, tables: Dict[str, pd.DataFrame], schema: str = "warehouse") -> bool:
        if not self.pg_conn_str:
            logger.info("No PostgreSQL connection string specified. Skipping direct Postgres ingestion.")
            return False

        try:
            from sqlalchemy import create_engine
            logger.info(f"Connecting to PostgreSQL engine for schema '{schema}'...")
            engine = create_engine(self.pg_conn_str)
            for name, df in tables.items():
                logger.info(f"Uploading {name} to PostgreSQL {schema}.{name}...")
                df.to_sql(name, engine, schema=schema, if_exists='replace', index=False, chunksize=10000)
            logger.info("PostgreSQL batch loading complete.")
            return True
        except Exception as e:
            logger.error(f"PostgreSQL ingestion failed: {e}")
            return False
