-- ============================================================================
-- Customer 360 & Churn Prediction Platform: Olist E-Commerce
-- Phase 2: Data Modeling - Star Schema DDL (PostgreSQL)
-- ============================================================================

DROP SCHEMA IF EXISTS warehouse CASCADE;
CREATE SCHEMA warehouse;

-- ============================================================================
-- 1. DIMENSION TABLES
-- ============================================================================

-- 1.1 dim_customer
DROP TABLE IF EXISTS warehouse.dim_customer;
CREATE TABLE warehouse.dim_customer (
    customer_key SERIAL PRIMARY KEY,
    customer_id VARCHAR(50) NOT NULL UNIQUE,
    customer_unique_id VARCHAR(50) NOT NULL,
    customer_zip_code INTEGER NOT NULL,
    customer_city VARCHAR(100) NOT NULL,
    customer_state VARCHAR(5) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_dim_cust_unique_id ON warehouse.dim_customer(customer_unique_id);
CREATE INDEX idx_dim_cust_state ON warehouse.dim_customer(customer_state);

-- 1.2 dim_product
DROP TABLE IF EXISTS warehouse.dim_product;
CREATE TABLE warehouse.dim_product (
    product_key SERIAL PRIMARY KEY,
    product_id VARCHAR(50) NOT NULL UNIQUE,
    product_category VARCHAR(100) DEFAULT 'unknown',
    product_name_length NUMERIC(6, 0),
    product_description_length NUMERIC(6, 0),
    product_photos NUMERIC(6, 0),
    product_weight NUMERIC(10, 2),
    product_length NUMERIC(10, 2),
    product_height NUMERIC(10, 2),
    product_width NUMERIC(10, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_dim_prod_category ON warehouse.dim_product(product_category);

-- 1.3 dim_seller
DROP TABLE IF EXISTS warehouse.dim_seller;
CREATE TABLE warehouse.dim_seller (
    seller_key SERIAL PRIMARY KEY,
    seller_id VARCHAR(50) NOT NULL UNIQUE,
    seller_city VARCHAR(100) NOT NULL,
    seller_state VARCHAR(5) NOT NULL,
    seller_zip_code INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_dim_seller_state ON warehouse.dim_seller(seller_state);

-- 1.4 dim_date
DROP TABLE IF EXISTS warehouse.dim_date;
CREATE TABLE warehouse.dim_date (
    date_key INTEGER PRIMARY KEY, -- Formatted as YYYYMMDD
    date DATE NOT NULL UNIQUE,
    year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    month INTEGER NOT NULL,
    month_name VARCHAR(20) NOT NULL,
    week INTEGER NOT NULL,
    day INTEGER NOT NULL,
    weekday VARCHAR(20) NOT NULL
);
CREATE INDEX idx_dim_date_year_month ON warehouse.dim_date(year, month);

-- 1.5 dim_location
DROP TABLE IF EXISTS warehouse.dim_location;
CREATE TABLE warehouse.dim_location (
    location_key SERIAL PRIMARY KEY,
    zip_code INTEGER NOT NULL UNIQUE,
    city VARCHAR(100) NOT NULL,
    state VARCHAR(5) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_dim_location_state_city ON warehouse.dim_location(state, city);

-- ============================================================================
-- 2. FACT TABLES
-- ============================================================================

-- 2.1 fact_orders
DROP TABLE IF EXISTS warehouse.fact_orders;
CREATE TABLE warehouse.fact_orders (
    order_key SERIAL PRIMARY KEY,
    order_id VARCHAR(50) NOT NULL UNIQUE,
    customer_key INTEGER NOT NULL REFERENCES warehouse.dim_customer(customer_key),
    order_status VARCHAR(30) NOT NULL,
    purchase_date TIMESTAMP NOT NULL,
    approval_date TIMESTAMP,
    carrier_date TIMESTAMP,
    delivery_date TIMESTAMP,
    estimated_delivery_date TIMESTAMP NOT NULL,
    delivery_delay_days NUMERIC(8, 2), -- Positive: Late, Negative: Early, NULL: Incomplete/Canceled
    purchase_date_key INTEGER REFERENCES warehouse.dim_date(date_key),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_fact_orders_customer ON warehouse.fact_orders(customer_key);
CREATE INDEX idx_fact_orders_status ON warehouse.fact_orders(order_status);
CREATE INDEX idx_fact_orders_purchase_date ON warehouse.fact_orders(purchase_date);

-- 2.2 fact_order_items
DROP TABLE IF EXISTS warehouse.fact_order_items;
CREATE TABLE warehouse.fact_order_items (
    order_item_key SERIAL PRIMARY KEY,
    order_key INTEGER NOT NULL REFERENCES warehouse.fact_orders(order_key),
    order_id VARCHAR(50) NOT NULL,
    order_item_id INTEGER NOT NULL,
    product_key INTEGER NOT NULL REFERENCES warehouse.dim_product(product_key),
    seller_key INTEGER NOT NULL REFERENCES warehouse.dim_seller(seller_key),
    price NUMERIC(10, 2) NOT NULL,
    freight_value NUMERIC(10, 2) NOT NULL,
    total_item_value NUMERIC(10, 2) NOT NULL, -- price + freight_value
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_fact_items_order ON warehouse.fact_order_items(order_key);
CREATE INDEX idx_fact_items_product ON warehouse.fact_order_items(product_key);
CREATE INDEX idx_fact_items_seller ON warehouse.fact_order_items(seller_key);

-- 2.3 fact_payments
DROP TABLE IF EXISTS warehouse.fact_payments;
CREATE TABLE warehouse.fact_payments (
    payment_key SERIAL PRIMARY KEY,
    order_key INTEGER NOT NULL REFERENCES warehouse.fact_orders(order_key),
    order_id VARCHAR(50) NOT NULL,
    payment_sequential INTEGER NOT NULL,
    payment_type VARCHAR(30) NOT NULL,
    payment_installments INTEGER NOT NULL,
    payment_value NUMERIC(10, 2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_fact_payments_order ON warehouse.fact_payments(order_key);
CREATE INDEX idx_fact_payments_type ON warehouse.fact_payments(payment_type);

-- 2.4 fact_reviews
DROP TABLE IF EXISTS warehouse.fact_reviews;
CREATE TABLE warehouse.fact_reviews (
    review_key SERIAL PRIMARY KEY,
    order_key INTEGER NOT NULL REFERENCES warehouse.fact_orders(order_key),
    order_id VARCHAR(50) NOT NULL,
    review_score INTEGER NOT NULL,
    review_creation_date TIMESTAMP NOT NULL,
    review_answer_date TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_fact_reviews_order ON warehouse.fact_reviews(order_key);
CREATE INDEX idx_fact_reviews_score ON warehouse.fact_reviews(review_score);
