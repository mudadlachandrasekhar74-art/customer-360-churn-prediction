"""
test_etl_pipeline.py
Automated test suite for Olist ETL Pipeline components and warehouse integrity.
"""

import os
import sqlite3
import unittest
import pandas as pd
import numpy as np

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.ingestion.extractor import CSVExtractor
from src.validation.schema_validator import SchemaValidator
from src.transformation.cleaner import DataCleaner
from src.transformation.transformer import DimensionalTransformer

class TestETLPipeline(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.raw_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw')
        cls.processed_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')
        cls.db_path = os.path.join(cls.processed_dir, 'olist_warehouse.db')

    def test_01_extractor_loads_core_files(self):
        extractor = CSVExtractor(raw_dir=self.raw_dir)
        df_cust = extractor.extract_file('olist_customers_dataset.csv')
        self.assertGreater(len(df_cust), 90000)
        self.assertIn('customer_id', df_cust.columns)

    def test_02_schema_validator_catches_valid_and_invalid(self):
        validator = SchemaValidator()
        valid_df = pd.DataFrame({
            'customer_id': ['c1', 'c2'],
            'customer_unique_id': ['u1', 'u2'],
            'customer_zip_code_prefix': [1234, 5678],
            'customer_city': ['sao paulo', 'campinas'],
            'customer_state': ['SP', 'SP']
        })
        res = validator.validate_dataset('customers', valid_df)
        self.assertTrue(res['valid'])

        invalid_df = valid_df.drop(columns=['customer_id'])
        res_inv = validator.validate_dataset('customers', invalid_df)
        self.assertFalse(res_inv['valid'])

    def test_03_cleaner_calculates_delivery_delay(self):
        sample_orders = pd.DataFrame({
            'order_id': ['o1', 'o2'],
            'customer_id': ['c1', 'c2'],
            'order_status': ['delivered', 'delivered'],
            'order_purchase_timestamp': ['2018-01-01 10:00:00', '2018-01-02 10:00:00'],
            'order_approved_at': ['2018-01-01 11:00:00', '2018-01-02 11:00:00'],
            'order_delivered_carrier_date': ['2018-01-02 10:00:00', '2018-01-03 10:00:00'],
            'order_delivered_customer_date': ['2018-01-10 10:00:00', '2018-01-20 10:00:00'],
            'order_estimated_delivery_date': ['2018-01-15 00:00:00', '2018-01-15 00:00:00']
        })
        cleaned = DataCleaner.clean_orders(sample_orders)
        self.assertIn('delivery_delay_days', cleaned.columns)
        # o1 delivered before estimate -> negative delay
        self.assertLess(cleaned.loc[0, 'delivery_delay_days'], 0)
        # o2 delivered after estimate -> positive delay
        self.assertGreater(cleaned.loc[1, 'delivery_delay_days'], 0)

    def test_04_warehouse_database_referential_integrity(self):
        self.assertTrue(os.path.exists(self.db_path), "Warehouse database file does not exist!")
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # Check fact_orders FK to dim_customer
        orphaned_orders = cur.execute("""
            SELECT COUNT(*) FROM fact_orders fo
            LEFT JOIN dim_customer dc ON fo.customer_key = dc.customer_key
            WHERE dc.customer_key IS NULL;
        """).fetchone()[0]
        self.assertEqual(orphaned_orders, 0, "Found fact_orders with invalid customer_key!")

        # Check fact_order_items FK to dim_product
        orphaned_products = cur.execute("""
            SELECT COUNT(*) FROM fact_order_items foi
            LEFT JOIN dim_product dp ON foi.product_key = dp.product_key
            WHERE dp.product_key IS NULL;
        """).fetchone()[0]
        self.assertEqual(orphaned_products, 0, "Found fact_order_items with invalid product_key!")

        conn.close()

if __name__ == '__main__':
    unittest.main()
