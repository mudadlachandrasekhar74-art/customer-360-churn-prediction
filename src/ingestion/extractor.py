"""
extractor.py
Ingestion module for Customer 360 & Churn Prediction Platform.
Extracts raw CSV files from source directories with logging, telemetry, and error handling.
"""

import os
import time
import logging
import pandas as pd
from typing import Dict, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("ETL.Ingestion")

DEFAULT_DATASET_FILES = {
    'customers': 'olist_customers_dataset.csv',
    'orders': 'olist_orders_dataset.csv',
    'order_items': 'olist_order_items_dataset.csv',
    'payments': 'olist_order_payments_dataset.csv',
    'reviews': 'olist_order_reviews_dataset.csv',
    'products': 'olist_products_dataset.csv',
    'sellers': 'olist_sellers_dataset.csv',
    'geolocation': 'olist_geolocation_dataset.csv',
    'category_translation': 'product_category_name_translation.csv'
}

class CSVExtractor:
    """Extracts raw Olist CSV datasets into memory with schema safety and execution telemetry."""

    def __init__(self, raw_dir: str):
        self.raw_dir = raw_dir
        if not os.path.exists(self.raw_dir):
            raise FileNotFoundError(f"Source raw data directory not found at: {self.raw_dir}")

    def extract_file(self, filename: str) -> pd.DataFrame:
        filepath = os.path.join(self.raw_dir, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Missing required source file: {filepath}")

        start_time = time.time()
        logger.info(f"Extracting {filename}...")
        df = pd.read_csv(filepath)
        elapsed = time.time() - start_time
        logger.info(f"Extracted {filename}: {len(df):,} rows, {len(df.columns)} columns in {elapsed:.2f}s")
        return df

    def extract_all(self, file_map: Optional[Dict[str, str]] = None) -> Dict[str, pd.DataFrame]:
        mapping = file_map or DEFAULT_DATASET_FILES
        datasets = {}
        total_start = time.time()
        logger.info(f"Starting bulk extraction of {len(mapping)} raw datasets from {self.raw_dir}")

        for key, filename in mapping.items():
            datasets[key] = self.extract_file(filename)

        total_elapsed = time.time() - total_start
        total_rows = sum(len(df) for df in datasets.values())
        logger.info(f"Successfully extracted {len(datasets)} datasets ({total_rows:,} total rows) in {total_elapsed:.2f}s")
        return datasets
