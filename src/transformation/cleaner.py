"""
cleaner.py
Data cleaning and standardization module for Customer 360 & Churn Prediction Platform.
Handles data type coercion, missing value imputation, string standardization, and derived fields.
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("ETL.Cleaner")

class DataCleaner:
    """Performs rigorous data sanitization, null imputation, type standardization, and derived calculations."""

    @staticmethod
    def clean_customers(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['customer_city'] = df['customer_city'].astype(str).str.strip().str.title()
        df['customer_state'] = df['customer_state'].astype(str).str.strip().str.upper()
        df['customer_zip_code_prefix'] = pd.to_numeric(df['customer_zip_code_prefix'], errors='coerce').fillna(0).astype(int)
        return df

    @staticmethod
    def clean_orders(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        date_cols = [
            'order_purchase_timestamp',
            'order_approved_at',
            'order_delivered_carrier_date',
            'order_delivered_customer_date',
            'order_estimated_delivery_date'
        ]
        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')

        # Derived business field: delivery_delay_days
        # Positive = late, Negative = early
        delivered = df['order_delivered_customer_date']
        estimated = df['order_estimated_delivery_date']
        df['delivery_delay_days'] = ((delivered - estimated).dt.total_seconds() / 86400.0).round(2)
        df['is_late'] = (df['delivery_delay_days'] > 0).astype(int)
        return df

    @staticmethod
    def clean_order_items(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['shipping_limit_date'] = pd.to_datetime(df['shipping_limit_date'], errors='coerce')
        df['price'] = pd.to_numeric(df['price'], errors='coerce').fillna(0.0).round(2)
        df['freight_value'] = pd.to_numeric(df['freight_value'], errors='coerce').fillna(0.0).round(2)
        # Derived field: total item value
        df['total_item_value'] = (df['price'] + df['freight_value']).round(2)
        return df

    @staticmethod
    def clean_payments(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['payment_type'] = df['payment_type'].astype(str).str.strip().str.lower()
        df['payment_installments'] = pd.to_numeric(df['payment_installments'], errors='coerce').fillna(1).astype(int)
        df['payment_value'] = pd.to_numeric(df['payment_value'], errors='coerce').fillna(0.0).round(2)
        return df

    @staticmethod
    def clean_reviews(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['review_score'] = pd.to_numeric(df['review_score'], errors='coerce').fillna(3).astype(int)
        df['review_creation_date'] = pd.to_datetime(df['review_creation_date'], errors='coerce')
        df['review_answer_timestamp'] = pd.to_datetime(df['review_answer_timestamp'], errors='coerce')
        df['review_comment_title'] = df['review_comment_title'].fillna('').astype(str).str.strip()
        df['review_comment_message'] = df['review_comment_message'].fillna('').astype(str).str.strip()
        return df

    @staticmethod
    def clean_products(df_prod: pd.DataFrame, df_trans: pd.DataFrame) -> pd.DataFrame:
        df = df_prod.copy()
        # Translate category to english
        merged = pd.merge(df, df_trans, on='product_category_name', how='left')
        merged['product_category'] = merged['product_category_name_english'].fillna(merged['product_category_name']).fillna('unknown')
        
        numeric_specs = [
            'product_name_lenght', 'product_description_lenght', 'product_photos_qty',
            'product_weight_g', 'product_length_cm', 'product_height_cm', 'product_width_cm'
        ]
        for col in numeric_specs:
            if col in merged.columns:
                merged[col] = pd.to_numeric(merged[col], errors='coerce').fillna(0.0)

        return merged

    @staticmethod
    def clean_sellers(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['seller_city'] = df['seller_city'].astype(str).str.strip().str.title()
        df['seller_state'] = df['seller_state'].astype(str).str.strip().str.upper()
        df['seller_zip_code_prefix'] = pd.to_numeric(df['seller_zip_code_prefix'], errors='coerce').fillna(0).astype(int)
        return df

    @staticmethod
    def clean_geolocation(df: pd.DataFrame) -> pd.DataFrame:
        # Deduplicate 1M points by taking robust median lat/long per zip code prefix
        logger.info("Deduplicating geolocation coordinates per postal zip prefix...")
        df_geo = df.copy()
        df_geo['geolocation_city'] = df_geo['geolocation_city'].astype(str).str.strip().str.title()
        df_geo['geolocation_state'] = df_geo['geolocation_state'].astype(str).str.strip().str.upper()
        
        agg = df_geo.groupby('geolocation_zip_code_prefix').agg(
            latitude=('geolocation_lat', 'median'),
            longitude=('geolocation_lng', 'median'),
            city=('geolocation_city', lambda x: x.mode().iloc[0] if not x.mode().empty else x.iloc[0]),
            state=('geolocation_state', lambda x: x.mode().iloc[0] if not x.mode().empty else x.iloc[0])
        ).reset_index()

        agg.rename(columns={'geolocation_zip_code_prefix': 'zip_code'}, inplace=True)
        agg['latitude'] = agg['latitude'].round(6)
        agg['longitude'] = agg['longitude'].round(6)
        return agg

    def clean_all(self, raw_dfs: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        logger.info("Initiating comprehensive multi-dataset cleaning routine...")
        cleaned = {}
        cleaned['customers'] = self.clean_customers(raw_dfs['customers'])
        cleaned['orders'] = self.clean_orders(raw_dfs['orders'])
        cleaned['order_items'] = self.clean_order_items(raw_dfs['order_items'])
        cleaned['payments'] = self.clean_payments(raw_dfs['payments'])
        cleaned['reviews'] = self.clean_reviews(raw_dfs['reviews'])
        cleaned['products'] = self.clean_products(raw_dfs['products'], raw_dfs['category_translation'])
        cleaned['sellers'] = self.clean_sellers(raw_dfs['sellers'])
        cleaned['geolocation'] = self.clean_geolocation(raw_dfs['geolocation'])
        logger.info("All datasets successfully cleaned, normalized, and augmented with derived fields.")
        return cleaned
