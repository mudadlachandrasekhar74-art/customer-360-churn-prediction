-- ============================================================================
-- Customer 360 & Churn Prediction Platform: Olist E-Commerce
-- Phase 2: Data Modeling - Staging DDL (PostgreSQL)
-- ============================================================================

DROP SCHEMA IF EXISTS staging CASCADE;
CREATE SCHEMA staging;

-- 1. Staging Customers
DROP TABLE IF EXISTS staging.stg_customers;
CREATE TABLE staging.stg_customers (
    customer_id VARCHAR(50) NOT NULL PRIMARY KEY,
    customer_unique_id VARCHAR(50) NOT NULL,
    customer_zip_code_prefix INTEGER NOT NULL,
    customer_city VARCHAR(100) NOT NULL,
    customer_state VARCHAR(5) NOT NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Staging Orders
DROP TABLE IF EXISTS staging.stg_orders;
CREATE TABLE staging.stg_orders (
    order_id VARCHAR(50) NOT NULL PRIMARY KEY,
    customer_id VARCHAR(50) NOT NULL,
    order_status VARCHAR(30) NOT NULL,
    order_purchase_timestamp TIMESTAMP NOT NULL,
    order_approved_at TIMESTAMP,
    order_delivered_carrier_date TIMESTAMP,
    order_delivered_customer_date TIMESTAMP,
    order_estimated_delivery_date TIMESTAMP NOT NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Staging Order Items
DROP TABLE IF EXISTS staging.stg_order_items;
CREATE TABLE staging.stg_order_items (
    order_id VARCHAR(50) NOT NULL,
    order_item_id INTEGER NOT NULL,
    product_id VARCHAR(50) NOT NULL,
    seller_id VARCHAR(50) NOT NULL,
    shipping_limit_date TIMESTAMP NOT NULL,
    price NUMERIC(10, 2) NOT NULL,
    freight_value NUMERIC(10, 2) NOT NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_stg_order_items PRIMARY KEY (order_id, order_item_id)
);

-- 4. Staging Order Payments
DROP TABLE IF EXISTS staging.stg_payments;
CREATE TABLE staging.stg_payments (
    order_id VARCHAR(50) NOT NULL,
    payment_sequential INTEGER NOT NULL,
    payment_type VARCHAR(30) NOT NULL,
    payment_installments INTEGER NOT NULL,
    payment_value NUMERIC(10, 2) NOT NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_stg_payments PRIMARY KEY (order_id, payment_sequential)
);

-- 5. Staging Order Reviews
DROP TABLE IF EXISTS staging.stg_reviews;
CREATE TABLE staging.stg_reviews (
    review_id VARCHAR(50) NOT NULL,
    order_id VARCHAR(50) NOT NULL,
    review_score INTEGER NOT NULL,
    review_comment_title TEXT,
    review_comment_message TEXT,
    review_creation_date TIMESTAMP NOT NULL,
    review_answer_timestamp TIMESTAMP NOT NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. Staging Products
DROP TABLE IF EXISTS staging.stg_products;
CREATE TABLE staging.stg_products (
    product_id VARCHAR(50) NOT NULL PRIMARY KEY,
    product_category_name VARCHAR(100),
    product_name_lenght NUMERIC(6, 0),
    product_description_lenght NUMERIC(6, 0),
    product_photos_qty NUMERIC(6, 0),
    product_weight_g NUMERIC(10, 2),
    product_length_cm NUMERIC(10, 2),
    product_height_cm NUMERIC(10, 2),
    product_width_cm NUMERIC(10, 2),
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 7. Staging Sellers
DROP TABLE IF EXISTS staging.stg_sellers;
CREATE TABLE staging.stg_sellers (
    seller_id VARCHAR(50) NOT NULL PRIMARY KEY,
    seller_zip_code_prefix INTEGER NOT NULL,
    seller_city VARCHAR(100) NOT NULL,
    seller_state VARCHAR(5) NOT NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 8. Staging Geolocation
DROP TABLE IF EXISTS staging.stg_geolocation;
CREATE TABLE staging.stg_geolocation (
    geolocation_zip_code_prefix INTEGER NOT NULL,
    geolocation_lat DOUBLE PRECISION NOT NULL,
    geolocation_lng DOUBLE PRECISION NOT NULL,
    geolocation_city VARCHAR(100) NOT NULL,
    geolocation_state VARCHAR(5) NOT NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 9. Staging Category Translation
DROP TABLE IF EXISTS staging.stg_category_translation;
CREATE TABLE staging.stg_category_translation (
    product_category_name VARCHAR(100) NOT NULL PRIMARY KEY,
    product_category_name_english VARCHAR(100) NOT NULL,
    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
