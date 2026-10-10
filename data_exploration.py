import os
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# Set style
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams['font.sans-serif'] = 'Arial'
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['figure.dpi'] = 150

DATA_DIR = os.path.join(os.getcwd(), 'data', 'raw')
FIGURES_DIR = os.path.join(os.getcwd(), 'reports', 'figures')
REPORTS_DIR = os.path.join(os.getcwd(), 'reports')

os.makedirs(FIGURES_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

DATASET_FILES = {
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

def inspect_datasets():
    print("=" * 80)
    print("PHASE 1: OLIST DATASET INSPECTION")
    print("=" * 80)

    dfs = {}
    inspection_results = {}

    for name, filename in DATASET_FILES.items():
        filepath = os.path.join(DATA_DIR, filename)
        if not os.path.exists(filepath):
            print(f"Error: {filepath} not found!")
            continue
        
        df = pd.read_csv(filepath)
        dfs[name] = df

        row_count, col_count = df.shape
        duplicates = df.duplicated().sum()
        missing = df.isnull().sum()
        missing_pct = (df.isnull().sum() / row_count) * 100

        # Classify columns
        date_cols = [c for c in df.columns if 'date' in c.lower() or 'timestamp' in c.lower()]
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        categorical_cols = [c for c in df.columns if c not in numeric_cols and c not in date_cols]

        # Check candidate PKs
        pk_candidates = [c for c in df.columns if df[c].nunique() == row_count and df[c].isnull().sum() == 0]

        col_details = []
        for col in df.columns:
            col_details.append({
                'column_name': col,
                'data_type': str(df[col].dtype),
                'non_null_count': int(df[col].notnull().sum()),
                'null_count': int(df[col].isnull().sum()),
                'null_percentage': round(float((df[col].isnull().sum() / row_count) * 100), 2),
                'unique_count': int(df[col].nunique()),
                'sample_values': [str(x) for x in df[col].dropna().head(3).tolist()]
            })

        inspection_results[name] = {
            'file_name': filename,
            'row_count': int(row_count),
            'column_count': int(col_count),
            'duplicate_rows': int(duplicates),
            'pk_candidates': pk_candidates,
            'date_columns': date_cols,
            'numeric_columns': numeric_cols,
            'categorical_columns': categorical_cols,
            'columns': col_details
        }

        print(f"\n--- Dataset: {name} ({filename}) ---")
        print(f"Rows: {row_count:,} | Columns: {col_count} | Duplicates: {duplicates:,}")
        print(f"PK Candidate(s): {pk_candidates if pk_candidates else 'None (Composite or non-unique)'}")
        print(f"Date cols: {date_cols}")
        print(f"Numeric cols: {numeric_cols}")
        print(f"Categorical cols: {categorical_cols}")
        if missing.sum() > 0:
            print("Missing values:")
            for col in df.columns[df.isnull().any()]:
                print(f"  - {col}: {missing[col]:,} ({missing_pct[col]:.2f}%)")
        else:
            print("Missing values: 0 (100% complete)")

    return dfs, inspection_results


def analyze_relationships(dfs):
    print("\n" + "=" * 80)
    print("RELATIONSHIP & INTEGRITY ANALYSIS")
    print("=" * 80)

    results = {}

    # 1. Customers -> Orders
    cust_orders = dfs['orders']['customer_id'].isin(dfs['customers']['customer_id']).all()
    unique_cust_in_orders = dfs['orders']['customer_id'].nunique()
    total_cust_id = dfs['customers']['customer_id'].nunique()
    total_unique_cust = dfs['customers']['customer_unique_id'].nunique()
    results['customers_to_orders'] = {
        'foreign_key_valid': bool(cust_orders),
        'orders_cust_id_in_customers': f"{unique_cust_in_orders:,} / {total_cust_id:,}",
        'customer_id_vs_customer_unique_id': f"{total_cust_id:,} customer_ids map to {total_unique_cust:,} unique persons/entities",
        'repeat_customers_at_raw_level': f"{total_cust_id - total_unique_cust:,} repeat customer occurrences ({((total_cust_id - total_unique_cust)/total_unique_cust)*100:.2f}% repeat rate)"
    }
    print(f"\n1. Customers -> Orders:")
    print(f"   All order customer_ids present in customers: {cust_orders}")
    print(f"   Total customer_ids (order sessions): {total_cust_id:,}")
    print(f"   Total unique buyers (customer_unique_id): {total_unique_cust:,}")

    # 2. Orders -> Order Items
    orders_in_items = dfs['order_items']['order_id'].isin(dfs['orders']['order_id']).all()
    orders_with_items = dfs['orders']['order_id'].isin(dfs['order_items']['order_id']).sum()
    total_orders = len(dfs['orders'])
    results['orders_to_order_items'] = {
        'all_items_have_valid_order': bool(orders_in_items),
        'orders_with_at_least_one_item': f"{orders_with_items:,} / {total_orders:,}",
        'orders_without_items': f"{total_orders - orders_with_items:,} (primarily canceled/unavailable orders)"
    }
    print(f"\n2. Orders -> Order Items:")
    print(f"   All order_items reference valid order_ids: {orders_in_items}")
    print(f"   Orders with item records: {orders_with_items:,} of {total_orders:,} (difference: {total_orders - orders_with_items:,})")

    # 3. Orders -> Payments
    orders_in_payments = dfs['payments']['order_id'].isin(dfs['orders']['order_id']).all()
    orders_with_payments = dfs['orders']['order_id'].isin(dfs['payments']['order_id']).sum()
    results['orders_to_payments'] = {
        'all_payments_have_valid_order': bool(orders_in_payments),
        'orders_with_payment': f"{orders_with_payments:,} / {total_orders:,}",
        'orders_without_payments': f"{total_orders - orders_with_payments:,}"
    }
    print(f"\n3. Orders -> Payments:")
    print(f"   All payments reference valid order_ids: {orders_in_payments}")
    print(f"   Orders with payments: {orders_with_payments:,} of {total_orders:,}")

    # 4. Orders -> Reviews
    orders_in_reviews = dfs['reviews']['order_id'].isin(dfs['orders']['order_id']).all()
    orders_with_reviews = dfs['orders']['order_id'].isin(dfs['reviews']['order_id']).sum()
    results['orders_to_reviews'] = {
        'all_reviews_have_valid_order': bool(orders_in_reviews),
        'orders_with_reviews': f"{orders_with_reviews:,} / {total_orders:,}",
        'multiple_reviews_per_order': f"{len(dfs['reviews']) - dfs['reviews']['order_id'].nunique():,} review records are repeat reviews for same order"
    }
    print(f"\n4. Orders -> Reviews:")
    print(f"   All reviews reference valid order_ids: {orders_in_reviews}")
    print(f"   Orders with reviews: {orders_with_reviews:,} of {total_orders:,}")

    # 5. Order Items -> Products
    items_in_products = dfs['order_items']['product_id'].isin(dfs['products']['product_id']).all()
    results['order_items_to_products'] = {
        'all_items_have_valid_product': bool(items_in_products),
        'unique_products_sold': f"{dfs['order_items']['product_id'].nunique():,} / {len(dfs['products']):,}"
    }
    print(f"\n5. Order Items -> Products:")
    print(f"   All order items reference valid product_ids: {items_in_products}")
    print(f"   Distinct products ordered: {dfs['order_items']['product_id'].nunique():,} out of {len(dfs['products']):,} in catalog")

    # 6. Order Items -> Sellers
    items_in_sellers = dfs['order_items']['seller_id'].isin(dfs['sellers']['seller_id']).all()
    results['order_items_to_sellers'] = {
        'all_items_have_valid_seller': bool(items_in_sellers),
        'unique_sellers_active': f"{dfs['order_items']['seller_id'].nunique():,} / {len(dfs['sellers']):,}"
    }
    print(f"\n6. Order Items -> Sellers:")
    print(f"   All order items reference valid seller_ids: {items_in_sellers}")
    print(f"   Distinct active sellers: {dfs['order_items']['seller_id'].nunique():,} out of {len(dfs['sellers']):,} sellers")

    # 7. Products -> Categories
    missing_cat = dfs['products']['product_category_name'].isnull().sum()
    cat_in_translation = dfs['products']['product_category_name'].dropna().isin(dfs['category_translation']['product_category_name']).all()
    untranslated = set(dfs['products']['product_category_name'].dropna()) - set(dfs['category_translation']['product_category_name'])
    results['products_to_categories'] = {
        'products_missing_category': f"{missing_cat:,} ({missing_cat/len(dfs['products'])*100:.2f}%)",
        'all_categories_in_translation_table': bool(cat_in_translation),
        'untranslated_categories': list(untranslated)
    }
    print(f"\n7. Products -> Categories:")
    print(f"   Products missing category: {missing_cat:,} ({missing_cat/len(dfs['products'])*100:.2f}%)")
    print(f"   All existing categories in translation table: {cat_in_translation}")
    if untranslated:
        print(f"   Untranslated categories found: {untranslated}")

    # 8. Customers -> Geolocation
    cust_zip_in_geo = dfs['customers']['customer_zip_code_prefix'].isin(dfs['geolocation']['geolocation_zip_code_prefix']).mean() * 100
    results['customers_to_geolocation'] = {
        'customer_zip_prefixes_found_in_geo': f"{cust_zip_in_geo:.2f}%"
    }
    print(f"\n8. Customers -> Geolocation:")
    print(f"   Customer zip prefixes matching geolocation dataset: {cust_zip_in_geo:.2f}%")

    return results


def generate_visualizations(dfs):
    print("\n" + "=" * 80)
    print("GENERATING VISUALIZATIONS FOR REPORTS/FIGURES")
    print("=" * 80)

    palette = sns.color_palette("mako")

    # Merge Orders, Order Items, Customers, Payments, Reviews for visualization
    orders = dfs['orders'].copy()
    orders['order_purchase_timestamp'] = pd.to_datetime(orders['order_purchase_timestamp'])
    orders['order_delivered_customer_date'] = pd.to_datetime(orders['order_delivered_customer_date'])
    orders['order_estimated_delivery_date'] = pd.to_datetime(orders['order_estimated_delivery_date'])

    # Filter to delivered orders or consistent range
    orders['year_month'] = orders['order_purchase_timestamp'].dt.to_period('M')

    # 1. Orders Over Time
    fig, ax = plt.subplots(figsize=(12, 6))
    monthly_orders = orders.groupby('year_month').size()
    # exclude incomplete edge months if any (before 2017-01 and after 2018-08 are sparse)
    monthly_orders.plot(kind='line', ax=ax, marker='o', color='#1f77b4', linewidth=2.5, markersize=6)
    ax.set_title('Olist E-Commerce: Monthly Order Volume (2016 - 2018)', fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel('Order Purchase Month', fontsize=12)
    ax.set_ylabel('Number of Orders', fontsize=12)
    ax.grid(True, linestyle='--', alpha=0.6)
    plt.xticks(rotation=45)
    plt.tight_layout()
    p1 = os.path.join(FIGURES_DIR, 'orders_over_time.png')
    plt.savefig(p1, dpi=200)
    plt.close()
    print(f"Saved: {p1}")

    # 2. Revenue Over Time
    items = dfs['order_items'].copy()
    items_orders = pd.merge(items, orders[['order_id', 'customer_id', 'order_purchase_timestamp', 'year_month', 'order_status']], on='order_id')
    # Filter to approved/delivered or non-canceled
    valid_sales = items_orders[~items_orders['order_status'].isin(['canceled', 'unavailable'])]
    monthly_rev = valid_sales.groupby('year_month')['price'].sum()

    fig, ax = plt.subplots(figsize=(12, 6))
    monthly_rev.plot(kind='line', ax=ax, marker='s', color='#2ca02c', linewidth=2.5, markersize=6)
    ax.set_title('Olist E-Commerce: Monthly Revenue (BRL) (2016 - 2018)', fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel('Order Purchase Month', fontsize=12)
    ax.set_ylabel('Gross Merchandise Value (BRL)', fontsize=12)
    ax.yaxis.set_major_formatter('R$ {x:,.0f}')
    ax.grid(True, linestyle='--', alpha=0.6)
    plt.xticks(rotation=45)
    plt.tight_layout()
    p2 = os.path.join(FIGURES_DIR, 'revenue_over_time.png')
    plt.savefig(p2, dpi=200)
    plt.close()
    print(f"Saved: {p2}")

    # 3. Customers by State
    customers = dfs['customers'].copy()
    cust_by_state = customers.groupby('customer_state')['customer_unique_id'].nunique().sort_values(ascending=False)

    fig, ax = plt.subplots(figsize=(12, 6))
    sns.barplot(x=cust_by_state.index, y=cust_by_state.values, hue=cust_by_state.index, palette='Blues_r', legend=False, ax=ax)
    ax.set_title('Unique Customers by Brazilian State (UF)', fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel('Customer State', fontsize=12)
    ax.set_ylabel('Unique Customer Count', fontsize=12)
    for p in ax.patches:
        ax.annotate(f"{int(p.get_height()):,}", (p.get_x() + p.get_width() / 2., p.get_height()),
                    ha='center', va='bottom', fontsize=8, rotation=90, xytext=(0, 4), textcoords='offset points')
    plt.tight_layout()
    p3 = os.path.join(FIGURES_DIR, 'customers_by_state.png')
    plt.savefig(p3, dpi=200)
    plt.close()
    print(f"Saved: {p3}")

    # 4. Revenue by State
    cust_sales = pd.merge(valid_sales, customers[['customer_id', 'customer_state']], on='customer_id')
    rev_by_state = cust_sales.groupby('customer_state')['price'].sum().sort_values(ascending=False)

    fig, ax = plt.subplots(figsize=(12, 6))
    sns.barplot(x=rev_by_state.index, y=rev_by_state.values, hue=rev_by_state.index, palette='Greens_r', legend=False, ax=ax)
    ax.set_title('Total Revenue (BRL) by Customer State', fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel('Customer State', fontsize=12)
    ax.set_ylabel('Total Revenue (BRL)', fontsize=12)
    ax.yaxis.set_major_formatter('R$ {x:,.0f}')
    plt.tight_layout()
    p4 = os.path.join(FIGURES_DIR, 'revenue_by_state.png')
    plt.savefig(p4, dpi=200)
    plt.close()
    print(f"Saved: {p4}")

    # 5. Orders by Category (Top 15)
    prod = dfs['products'].copy()
    trans = dfs['category_translation'].copy()
    prod_trans = pd.merge(prod, trans, on='product_category_name', how='left')
    prod_trans['category_english'] = prod_trans['product_category_name_english'].fillna(prod_trans['product_category_name']).fillna('Unknown')
    
    items_prod = pd.merge(items, prod_trans[['product_id', 'category_english']], on='product_id', how='left')
    top_categories = items_prod['category_english'].value_counts().head(15)

    fig, ax = plt.subplots(figsize=(12, 7))
    sns.barplot(y=top_categories.index, x=top_categories.values, hue=top_categories.index, palette='viridis', legend=False, ax=ax)
    ax.set_title('Top 15 Product Categories by Items Sold', fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel('Number of Items Sold', fontsize=12)
    ax.set_ylabel('Category (English)', fontsize=12)
    for p in ax.patches:
        ax.annotate(f" {int(p.get_width()):,}", (p.get_width(), p.get_y() + p.get_height() / 2.),
                    va='center', fontsize=9)
    plt.tight_layout()
    p5 = os.path.join(FIGURES_DIR, 'orders_by_category.png')
    plt.savefig(p5, dpi=200)
    plt.close()
    print(f"Saved: {p5}")

    # 6. Review Score Distribution
    reviews = dfs['reviews'].copy()
    score_counts = reviews['review_score'].value_counts().sort_index()

    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ['#d9534f', '#f0ad4e', '#5bc0de', '#428bca', '#5cb85c']
    bars = ax.bar(score_counts.index, score_counts.values, color=colors, edgecolor='black', alpha=0.85)
    ax.set_title('Customer Review Score Distribution (1 to 5 Stars)', fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel('Review Score', fontsize=12)
    ax.set_ylabel('Count of Reviews', fontsize=12)
    ax.set_xticks([1, 2, 3, 4, 5])
    total_rev = len(reviews)
    for bar in bars:
        h = bar.get_height()
        ax.annotate(f"{h:,}\n({(h/total_rev)*100:.1f}%)", (bar.get_x() + bar.get_width() / 2., h),
                    ha='center', va='bottom', fontsize=9, xytext=(0, 3), textcoords='offset points')
    plt.tight_layout()
    p6 = os.path.join(FIGURES_DIR, 'review_score_distribution.png')
    plt.savefig(p6, dpi=200)
    plt.close()
    print(f"Saved: {p6}")

    # 7. Delivery Delay Distribution
    # Delay = delivered_date - estimated_date (in days). Positive means late, negative means early.
    delivered = orders.dropna(subset=['order_delivered_customer_date', 'order_estimated_delivery_date']).copy()
    delivered['delay_days'] = (delivered['order_delivered_customer_date'] - delivered['order_estimated_delivery_date']).dt.total_seconds() / (24 * 3600)

    # Let's clip for visualization between -30 and +30 days
    clipped_delay = delivered['delay_days'].clip(-25, 25)

    fig, ax = plt.subplots(figsize=(11, 5))
    sns.histplot(clipped_delay, bins=50, kde=True, color='#8e44ad', ax=ax)
    ax.axvline(0, color='red', linestyle='--', linewidth=2, label='Estimated Delivery Date (0 days delay)')
    late_pct = (delivered['delay_days'] > 0).mean() * 100
    avg_early = delivered[delivered['delay_days'] <= 0]['delay_days'].mean()
    avg_late = delivered[delivered['delay_days'] > 0]['delay_days'].mean()
    ax.set_title(f'Delivery Performance: Actual vs. Estimated Delivery Date\n(Late Deliveries: {late_pct:.1f}% | Avg Delay When Late: {avg_late:.1f} days | Avg Days Early: {abs(avg_early):.1f} days)',
                 fontsize=13, fontweight='bold', pad=15)
    ax.set_xlabel('Difference from Estimated Delivery Date (Days: Negative = Early, Positive = Late)', fontsize=11)
    ax.set_ylabel('Number of Orders', fontsize=11)
    ax.legend()
    plt.tight_layout()
    p7 = os.path.join(FIGURES_DIR, 'delivery_delay_distribution.png')
    plt.savefig(p7, dpi=200)
    plt.close()
    print(f"Saved: {p7}")

    # 8. Payment Method Distribution
    payments = dfs['payments'].copy()
    pay_type_counts = payments['payment_type'].value_counts()
    pay_type_val = payments.groupby('payment_type')['payment_value'].sum()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    pay_type_counts.plot(kind='pie', ax=ax1, autopct='%1.1f%%', startangle=140, cmap='Pastel1',
                         wedgeprops=dict(width=0.6, edgecolor='w'))
    ax1.set_title('Payment Transactions by Method', fontsize=12, fontweight='bold')
    ax1.set_ylabel('')

    pay_type_val.sort_values(ascending=False).plot(kind='bar', ax=ax2, color='#3498db', edgecolor='black')
    ax2.set_title('Total Payment Value by Method (BRL)', fontsize=12, fontweight='bold')
    ax2.set_xlabel('Payment Method', fontsize=11)
    ax2.set_ylabel('Total Value (BRL)', fontsize=11)
    ax2.yaxis.set_major_formatter('R$ {x:,.0f}')
    plt.xticks(rotation=45)

    plt.tight_layout()
    p8 = os.path.join(FIGURES_DIR, 'payment_method_distribution.png')
    plt.savefig(p8, dpi=200)
    plt.close()
    print(f"Saved: {p8}")


def generate_data_dictionary(inspection_results, relationships):
    dict_path = os.path.join(REPORTS_DIR, 'data_dictionary.md')
    print(f"\nGenerating Data Dictionary at: {dict_path}")

    with open(dict_path, 'w', encoding='utf-8') as f:
        f.write("# Olist Brazilian E-Commerce: Comprehensive Data Dictionary\n\n")
        f.write("This document provides technical metadata, schemas, completeness scores, integrity relationships, and business interpretations for all 9 raw datasets provided by Olist.\n\n")
        f.write("## 1. Executive Summary of Datasets\n\n")
        f.write("| Dataset | File Name | Rows | Columns | Duplicates | PK Candidate(s) | Completeness (%) |\n")
        f.write("|---|---|---|---|---|---|---|\n")

        for name, info in inspection_results.items():
            total_cells = info['row_count'] * info['column_count']
            null_cells = sum(c['null_count'] for c in info['columns'])
            comp = round(((total_cells - null_cells) / total_cells) * 100, 2) if total_cells > 0 else 100
            pk = ", ".join(info['pk_candidates']) if info['pk_candidates'] else "Composite / Non-unique"
            f.write(f"| **{name}** | `{info['file_name']}` | {info['row_count']:,} | {info['column_count']} | {info['duplicate_rows']:,} | {pk} | {comp}% |\n")

        f.write("\n---\n\n")
        f.write("## 2. Relational Architecture & Entity Relationships\n\n")
        f.write("```mermaid\nerDiagram\n")
        f.write("    CUSTOMERS ||--o{ ORDERS : \"places (customer_id)\"\n")
        f.write("    ORDERS ||--|{ ORDER_ITEMS : \"contains (order_id)\"\n")
        f.write("    ORDERS ||--|{ PAYMENTS : \"paid via (order_id)\"\n")
        f.write("    ORDERS ||--o{ REVIEWS : \"evaluated by (order_id)\"\n")
        f.write("    PRODUCTS ||--o{ ORDER_ITEMS : \"supplied in (product_id)\"\n")
        f.write("    SELLERS ||--o{ ORDER_ITEMS : \"fulfilled by (seller_id)\"\n")
        f.write("    CATEGORIES ||--o{ PRODUCTS : \"classified as (category_name)\"\n")
        f.write("    GEOLOCATION }o--o{ CUSTOMERS : \"locates (zip_prefix)\"\n")
        f.write("    GEOLOCATION }o--o{ SELLERS : \"locates (zip_prefix)\"\n")
        f.write("```\n\n")

        f.write("### Key Relational Nuances:\n")
        f.write("1. **Customer Identity Architecture (`customer_id` vs `customer_unique_id`)**:\n")
        f.write("   - `customer_id`: Assigned per *order session*. A single buyer placing 3 orders has 3 distinct `customer_id`s.\n")
        f.write("   - `customer_unique_id`: The true physical customer identity. Essential for RFM, churn analysis, and Customer 360.\n")
        f.write("2. **Order Line-Items (`order_items`)**:\n")
        f.write("   - Primary key is composite: `(order_id, order_item_id)`. One order can have multiple items and multiple sellers.\n")
        f.write("3. **Payments Split (`order_payments`)**:\n")
        f.write("   - Primary key is composite: `(order_id, payment_sequential)`. Orders can be split across vouchers, credit cards, etc.\n")
        f.write("4. **Reviews (`order_reviews`)**:\n")
        f.write("   - Multiple reviews can exist for the same order (`review_id` / `order_id` repeat on rare multi-touch surveys).\n\n")

        f.write("---\n\n")
        f.write("## 3. Dataset Schemas & Column Attributes\n\n")

        for name, info in inspection_results.items():
            f.write(f"### 3.{list(inspection_results.keys()).index(name)+1} `{info['file_name']}` ({name.upper()})\n\n")
            f.write(f"- **Total Rows:** {info['row_count']:,}\n")
            f.write(f"- **Total Columns:** {info['column_count']}\n")
            f.write(f"- **Duplicate Rows:** {info['duplicate_rows']:,}\n")
            f.write(f"- **Date Columns:** `{info['date_columns']}`\n")
            f.write(f"- **Numeric Columns:** `{info['numeric_columns']}`\n")
            f.write(f"- **Categorical Columns:** `{info['categorical_columns']}`\n\n")

            f.write("| Column Name | Inferred Type | Null Count | Null % | Unique Values | Sample Values |\n")
            f.write("|---|---|---|---|---|---|\n")
            for col in info['columns']:
                sample_str = ", ".join(col['sample_values'][:2]).replace("|", "\\|")
                f.write(f"| `{col['column_name']}` | `{col['data_type']}` | {col['null_count']:,} | {col['null_percentage']}% | {col['unique_count']:,} | {sample_str} |\n")
            f.write("\n")

    print(f"Data Dictionary successfully written to {dict_path}")


if __name__ == '__main__':
    dfs, inspection_results = inspect_datasets()
    relationships = analyze_relationships(dfs)
    generate_visualizations(dfs)
    generate_data_dictionary(inspection_results, relationships)
    print("\nPhase 1 Data Exploration and Dictionary Generation Completed Successfully!")
