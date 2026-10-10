-- ============================================================================
-- Customer 360 & Churn Prediction Platform: Olist E-Commerce
-- Phase 2: Data Modeling - ETL Staging-to-Warehouse Transformations (PostgreSQL)
-- ============================================================================

-- 1. Populate dim_date (2016 through 2019)
INSERT INTO warehouse.dim_date (date_key, date, year, quarter, month, month_name, week, day, weekday)
SELECT
    TO_CHAR(d, 'YYYYMMDD')::INTEGER AS date_key,
    d::DATE AS date,
    EXTRACT(YEAR FROM d)::INTEGER AS year,
    EXTRACT(QUARTER FROM d)::INTEGER AS quarter,
    EXTRACT(MONTH FROM d)::INTEGER AS month,
    TO_CHAR(d, 'Month') AS month_name,
    EXTRACT(WEEK FROM d)::INTEGER AS week,
    EXTRACT(DAY FROM d)::INTEGER AS day,
    TO_CHAR(d, 'Day') AS weekday
FROM GENERATE_SERIES('2016-01-01'::DATE, '2019-12-31'::DATE, '1 day'::INTERVAL) AS d
ON CONFLICT (date_key) DO NOTHING;

-- 2. Populate dim_location (Aggregated median coordinates per zip prefix)
INSERT INTO warehouse.dim_location (zip_code, city, state, latitude, longitude)
SELECT 
    geolocation_zip_code_prefix AS zip_code,
    INITCAP(MODE() WITHIN GROUP (ORDER BY geolocation_city)) AS city,
    UPPER(MODE() WITHIN GROUP (ORDER BY geolocation_state)) AS state,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY geolocation_lat) AS latitude,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY geolocation_lng) AS longitude
FROM staging.stg_geolocation
GROUP BY geolocation_zip_code_prefix
ON CONFLICT (zip_code) DO NOTHING;

-- 3. Populate dim_customer
INSERT INTO warehouse.dim_customer (customer_id, customer_unique_id, customer_zip_code, customer_city, customer_state)
SELECT 
    customer_id,
    customer_unique_id,
    customer_zip_code_prefix AS customer_zip_code,
    INITCAP(customer_city) AS customer_city,
    UPPER(customer_state) AS customer_state
FROM staging.stg_customers
ON CONFLICT (customer_id) DO NOTHING;

-- 4. Populate dim_product (Joining category translation and replacing nulls)
INSERT INTO warehouse.dim_product (
    product_id,
    product_category,
    product_name_length,
    product_description_length,
    product_photos,
    product_weight,
    product_length,
    product_height,
    product_width
)
SELECT 
    p.product_id,
    COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS product_category,
    p.product_name_lenght,
    p.product_description_lenght,
    p.product_photos_qty,
    p.product_weight_g,
    p.product_length_cm,
    p.product_height_cm,
    p.product_width_cm
FROM staging.stg_products p
LEFT JOIN staging.stg_category_translation t 
    ON p.product_category_name = t.product_category_name
ON CONFLICT (product_id) DO NOTHING;

-- 5. Populate dim_seller
INSERT INTO warehouse.dim_seller (seller_id, seller_city, seller_state, seller_zip_code)
SELECT 
    seller_id,
    INITCAP(seller_city),
    UPPER(seller_state),
    seller_zip_code_prefix AS seller_zip_code
FROM staging.stg_sellers
ON CONFLICT (seller_id) DO NOTHING;

-- 6. Populate fact_orders
INSERT INTO warehouse.fact_orders (
    order_id,
    customer_key,
    order_status,
    purchase_date,
    approval_date,
    carrier_date,
    delivery_date,
    estimated_delivery_date,
    delivery_delay_days,
    purchase_date_key
)
SELECT 
    o.order_id,
    c.customer_key,
    o.order_status,
    o.order_purchase_timestamp,
    o.order_approved_at,
    o.order_delivered_carrier_date,
    o.order_delivered_customer_date,
    o.order_estimated_delivery_date,
    CASE 
        WHEN o.order_delivered_customer_date IS NOT NULL 
        THEN ROUND(EXTRACT(EPOCH FROM (o.order_delivered_customer_date - o.order_estimated_delivery_date)) / 86400.0, 2)
        ELSE NULL 
    END AS delivery_delay_days,
    TO_CHAR(o.order_purchase_timestamp, 'YYYYMMDD')::INTEGER AS purchase_date_key
FROM staging.stg_orders o
JOIN warehouse.dim_customer c ON o.customer_id = c.customer_id
ON CONFLICT (order_id) DO NOTHING;

-- 7. Populate fact_order_items
INSERT INTO warehouse.fact_order_items (
    order_key,
    order_id,
    order_item_id,
    product_key,
    seller_key,
    price,
    freight_value,
    total_item_value
)
SELECT 
    fo.order_key,
    oi.order_id,
    oi.order_item_id,
    dp.product_key,
    ds.seller_key,
    oi.price,
    oi.freight_value,
    (oi.price + oi.freight_value) AS total_item_value
FROM staging.stg_order_items oi
JOIN warehouse.fact_orders fo ON oi.order_id = fo.order_id
JOIN warehouse.dim_product dp ON oi.product_id = dp.product_id
JOIN warehouse.dim_seller ds ON oi.seller_id = ds.seller_id;

-- 8. Populate fact_payments
INSERT INTO warehouse.fact_payments (
    order_key,
    order_id,
    payment_sequential,
    payment_type,
    payment_installments,
    payment_value
)
SELECT 
    fo.order_key,
    p.order_id,
    p.payment_sequential,
    p.payment_type,
    p.payment_installments,
    p.payment_value
FROM staging.stg_payments p
JOIN warehouse.fact_orders fo ON p.order_id = fo.order_id;

-- 9. Populate fact_reviews
INSERT INTO warehouse.fact_reviews (
    order_key,
    order_id,
    review_score,
    review_creation_date,
    review_answer_date
)
SELECT 
    fo.order_key,
    r.order_id,
    r.review_score,
    r.review_creation_date,
    r.review_answer_timestamp
FROM staging.stg_reviews r
JOIN warehouse.fact_orders fo ON r.order_id = fo.order_id;
