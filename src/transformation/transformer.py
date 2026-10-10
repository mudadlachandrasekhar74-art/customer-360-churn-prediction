"""
transformer.py
Dimensional transformation module for Customer 360 & Churn Prediction Platform.
Maps cleaned operational datasets into conformed dimensions and transactional facts
with surrogate keys, foreign key references, and business integrity.
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("ETL.Transformer")

class DimensionalTransformer:
    """Constructs Conformed Dimension and Fact tables implementing the Star Schema design."""

    def __init__(self):
        pass

    def build_dimensions(self, cleaned: Dict[str, pd.DataFrame]) -> Tuple[Dict[str, pd.DataFrame], Dict[str, dict]]:
        logger.info("Transforming cleaned data into Conformed Dimensions...")
        dim_tables = {}
        lookup_maps = {}

        # 1. dim_customer
        df_c = cleaned['customers'].copy()
        dim_cust = pd.DataFrame({
            'customer_id': df_c['customer_id'],
            'customer_unique_id': df_c['customer_unique_id'],
            'customer_zip_code': df_c['customer_zip_code_prefix'],
            'customer_city': df_c['customer_city'],
            'customer_state': df_c['customer_state']
        }).reset_index(drop=True)
        dim_cust.insert(0, 'customer_key', dim_cust.index + 1)
        dim_tables['dim_customer'] = dim_cust
        lookup_maps['customer_key_map'] = dict(zip(dim_cust['customer_id'], dim_cust['customer_key']))

        # 2. dim_product
        df_p = cleaned['products'].copy()
        dim_prod = pd.DataFrame({
            'product_id': df_p['product_id'],
            'product_category': df_p['product_category'],
            'product_name_length': df_p['product_name_lenght'],
            'product_description_length': df_p['product_description_lenght'],
            'product_photos': df_p['product_photos_qty'],
            'product_weight': df_p['product_weight_g'],
            'product_length': df_p['product_length_cm'],
            'product_height': df_p['product_height_cm'],
            'product_width': df_p['product_width_cm']
        }).reset_index(drop=True)
        dim_prod.insert(0, 'product_key', dim_prod.index + 1)
        dim_tables['dim_product'] = dim_prod
        lookup_maps['product_key_map'] = dict(zip(dim_prod['product_id'], dim_prod['product_key']))

        # 3. dim_seller
        df_s = cleaned['sellers'].copy()
        dim_seller = pd.DataFrame({
            'seller_id': df_s['seller_id'],
            'seller_city': df_s['seller_city'],
            'seller_state': df_s['seller_state'],
            'seller_zip_code': df_s['seller_zip_code_prefix']
        }).reset_index(drop=True)
        dim_seller.insert(0, 'seller_key', dim_seller.index + 1)
        dim_tables['dim_seller'] = dim_seller
        lookup_maps['seller_key_map'] = dict(zip(dim_seller['seller_id'], dim_seller['seller_key']))

        # 4. dim_location
        df_g = cleaned['geolocation'].copy()
        dim_loc = pd.DataFrame({
            'zip_code': df_g['zip_code'],
            'city': df_g['city'],
            'state': df_g['state'],
            'latitude': df_g['latitude'],
            'longitude': df_g['longitude']
        }).reset_index(drop=True)
        dim_loc.insert(0, 'location_key', dim_loc.index + 1)
        dim_tables['dim_location'] = dim_loc

        # 5. dim_date (2016-01-01 to 2019-12-31)
        date_range = pd.date_range(start='2016-01-01', end='2019-12-31', freq='D')
        dim_date = pd.DataFrame({
            'date_key': date_range.strftime('%Y%m%d').astype(int),
            'date': date_range.strftime('%Y-%m-%d'),
            'year': date_range.year,
            'quarter': date_range.quarter,
            'month': date_range.month,
            'month_name': date_range.strftime('%B'),
            'week': date_range.isocalendar().week.astype(int),
            'day': date_range.day,
            'weekday': date_range.strftime('%A')
        })
        dim_tables['dim_date'] = dim_date

        logger.info(f"Dimensions successfully assembled: {list(dim_tables.keys())}")
        return dim_tables, lookup_maps

    def build_facts(self, cleaned: Dict[str, pd.DataFrame], lookup_maps: Dict[str, dict]) -> Dict[str, pd.DataFrame]:
        logger.info("Transforming cleaned data into Fact Tables with surrogate foreign keys...")
        fact_tables = {}

        # 1. fact_orders
        df_o = cleaned['orders'].copy()
        fact_orders = pd.DataFrame({
            'order_id': df_o['order_id'],
            'customer_key': df_o['customer_id'].map(lookup_maps['customer_key_map']),
            'order_status': df_o['order_status'],
            'purchase_date': df_o['order_purchase_timestamp'].astype(str),
            'approval_date': df_o['order_approved_at'].astype(str),
            'carrier_date': df_o['order_delivered_carrier_date'].astype(str),
            'delivery_date': df_o['order_delivered_customer_date'].astype(str),
            'estimated_delivery_date': df_o['order_estimated_delivery_date'].astype(str),
            'delivery_delay_days': df_o['delivery_delay_days']
        }).reset_index(drop=True)
        fact_orders.insert(0, 'order_key', fact_orders.index + 1)
        fact_tables['fact_orders'] = fact_orders

        order_key_map = dict(zip(fact_orders['order_id'], fact_orders['order_key']))

        # 2. fact_order_items
        df_i = cleaned['order_items'].copy()
        fact_items = pd.DataFrame({
            'order_key': df_i['order_id'].map(order_key_map),
            'product_key': df_i['product_id'].map(lookup_maps['product_key_map']),
            'seller_key': df_i['seller_id'].map(lookup_maps['seller_key_map']),
            'price': df_i['price'],
            'freight_value': df_i['freight_value'],
            'total_item_value': df_i['total_item_value']
        }).dropna(subset=['order_key']).copy()
        fact_items['order_key'] = fact_items['order_key'].astype(int)
        fact_tables['fact_order_items'] = fact_items.reset_index(drop=True)

        # 3. fact_payments
        df_p = cleaned['payments'].copy()
        fact_pay = pd.DataFrame({
            'order_key': df_p['order_id'].map(order_key_map),
            'payment_type': df_p['payment_type'],
            'payment_installments': df_p['payment_installments'],
            'payment_value': df_p['payment_value']
        }).dropna(subset=['order_key']).copy()
        fact_pay['order_key'] = fact_pay['order_key'].astype(int)
        fact_tables['fact_payments'] = fact_pay.reset_index(drop=True)

        # 4. fact_reviews
        df_r = cleaned['reviews'].copy()
        fact_rev = pd.DataFrame({
            'order_key': df_r['order_id'].map(order_key_map),
            'review_score': df_r['review_score'],
            'review_creation_date': df_r['review_creation_date'].astype(str),
            'review_answer_date': df_r['review_answer_timestamp'].astype(str)
        }).dropna(subset=['order_key']).copy()
        fact_rev['order_key'] = fact_rev['order_key'].astype(int)
        fact_tables['fact_reviews'] = fact_rev.reset_index(drop=True)

        logger.info(f"Fact tables successfully built: {list(fact_tables.keys())}")
        return fact_tables
