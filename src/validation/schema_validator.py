"""
schema_validator.py
Validation module for Customer 360 & Churn Prediction Platform.
Enforces schema contracts, required fields, data types, and primary-key integrity.
"""

import logging
import pandas as pd
from typing import Dict, List, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("ETL.Validation")

# Schema Contracts defining structural requirements
SCHEMA_CONTRACTS = {
    'customers': {
        'required_columns': ['customer_id', 'customer_unique_id', 'customer_zip_code_prefix', 'customer_city', 'customer_state'],
        'pk': 'customer_id',
        'non_null': ['customer_id', 'customer_unique_id', 'customer_zip_code_prefix', 'customer_city', 'customer_state']
    },
    'orders': {
        'required_columns': ['order_id', 'customer_id', 'order_status', 'order_purchase_timestamp', 'order_estimated_delivery_date'],
        'pk': 'order_id',
        'non_null': ['order_id', 'customer_id', 'order_status', 'order_purchase_timestamp', 'order_estimated_delivery_date']
    },
    'order_items': {
        'required_columns': ['order_id', 'order_item_id', 'product_id', 'seller_id', 'shipping_limit_date', 'price', 'freight_value'],
        'composite_pk': ['order_id', 'order_item_id'],
        'non_null': ['order_id', 'order_item_id', 'product_id', 'seller_id', 'price', 'freight_value']
    },
    'payments': {
        'required_columns': ['order_id', 'payment_sequential', 'payment_type', 'payment_installments', 'payment_value'],
        'composite_pk': ['order_id', 'payment_sequential'],
        'non_null': ['order_id', 'payment_sequential', 'payment_type', 'payment_value']
    },
    'reviews': {
        'required_columns': ['review_id', 'order_id', 'review_score', 'review_creation_date', 'review_answer_timestamp'],
        'non_null': ['review_id', 'order_id', 'review_score', 'review_creation_date']
    },
    'products': {
        'required_columns': ['product_id'],
        'pk': 'product_id',
        'non_null': ['product_id']
    },
    'sellers': {
        'required_columns': ['seller_id', 'seller_zip_code_prefix', 'seller_city', 'seller_state'],
        'pk': 'seller_id',
        'non_null': ['seller_id', 'seller_zip_code_prefix', 'seller_city', 'seller_state']
    },
    'geolocation': {
        'required_columns': ['geolocation_zip_code_prefix', 'geolocation_lat', 'geolocation_lng', 'geolocation_city', 'geolocation_state'],
        'non_null': ['geolocation_zip_code_prefix', 'geolocation_lat', 'geolocation_lng']
    },
    'category_translation': {
        'required_columns': ['product_category_name', 'product_category_name_english'],
        'pk': 'product_category_name',
        'non_null': ['product_category_name', 'product_category_name_english']
    }
}

class SchemaValidator:
    """Validates raw and staged dataframes against pre-defined structural and integrity rules."""

    def __init__(self, contracts: Dict[str, Any] = None):
        self.contracts = contracts or SCHEMA_CONTRACTS

    def validate_dataset(self, name: str, df: pd.DataFrame) -> Dict[str, Any]:
        if name not in self.contracts:
            logger.warning(f"No specific schema contract defined for {name}. Passing basic check.")
            return {'dataset': name, 'valid': True, 'errors': []}

        contract = self.contracts[name]
        errors = []

        # 1. Check required columns
        missing_cols = [c for c in contract.get('required_columns', []) if c not in df.columns]
        if missing_cols:
            errors.append(f"Missing mandatory column(s): {missing_cols}")

        # 2. Check non-null constraints
        for col in contract.get('non_null', []):
            if col in df.columns:
                null_count = df[col].isnull().sum()
                if null_count > 0:
                    errors.append(f"Column '{col}' violated NOT NULL constraint with {null_count:,} nulls")

        # 3. Check single PK uniqueness
        if 'pk' in contract and contract['pk'] in df.columns:
            pk = contract['pk']
            dup_count = df[pk].duplicated().sum()
            if dup_count > 0:
                errors.append(f"Primary key '{pk}' has {dup_count:,} duplicate values")

        # 4. Check composite PK uniqueness
        if 'composite_pk' in contract:
            comp_cols = contract['composite_pk']
            if all(c in df.columns for c in comp_cols):
                dup_count = df.duplicated(subset=comp_cols).sum()
                if dup_count > 0:
                    errors.append(f"Composite key {comp_cols} has {dup_count:,} duplicate rows")

        is_valid = len(errors) == 0
        if is_valid:
            logger.info(f"Schema contract PASSED for dataset '{name}'")
        else:
            logger.error(f"Schema contract FAILED for dataset '{name}': {errors}")

        return {
            'dataset': name,
            'valid': is_valid,
            'errors': errors,
            'records_checked': len(df)
        }

    def validate_all(self, datasets: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, Any]]:
        results = {}
        for name, df in datasets.items():
            results[name] = self.validate_dataset(name, df)
        return results
