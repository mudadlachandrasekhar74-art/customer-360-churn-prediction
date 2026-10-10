"""
pipeline.py
Master Production Pipeline for Customer 360 & Churn Prediction Platform.
Orchestrates end-to-end:
  Phase 3.1  — Data Ingestion & Extraction
  Phase 3.2  — Schema Validation & Contract Audit
  Phase 3.3  — Data Cleaning & Derived Business Metrics
  Phase 3.4  — Staging Repository Ingestion
  Phase 3.5  — Dimensional Star Schema Transformation
  Phase 3.6  — Loading Analytical Warehouse & Exporting Marts
  Phase 3.7  — Data Integrity Post-Load Audit
  Phase 9    — Batch Inference & Scoring  (if champion model is available)
  Phase 9b   — Inference Business Report Generation
"""

import os
import sys
import time
import logging
import sqlite3
import pandas as pd

# Add src to path if executed standalone
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ingestion.extractor import CSVExtractor
from validation.schema_validator import SchemaValidator
from transformation.cleaner import DataCleaner
from transformation.transformer import DimensionalTransformer
from loading.loader import WarehouseLoader

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("ETL.Pipeline")

BASE_DIR      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR       = os.path.join(BASE_DIR, 'data', 'raw')
PROCESSED_DIR = os.path.join(BASE_DIR, 'data', 'processed')
DB_PATH       = os.path.join(PROCESSED_DIR, 'olist_warehouse.db')
MODEL_PATH    = os.path.join(BASE_DIR, 'src', 'ml', 'churn_champion_pipeline.joblib')


def run_etl_pipeline(
    raw_dir:      str  = RAW_DIR,
    processed_dir:str  = PROCESSED_DIR,
    db_path:      str  = DB_PATH,
    run_inference:bool = True,
) -> bool:
    pipeline_start = time.time()
    logger.info("=" * 80)
    logger.info("STARTING DELOITTE OLIST CUSTOMER 360 PRODUCTION ETL PIPELINE")
    logger.info("=" * 80)

    # ── 1. EXTRACT ─────────────────────────────────────────────────────────────
    logger.info("\n--- PHASE 3.1: DATA INGESTION & EXTRACTION ---")
    extractor = CSVExtractor(raw_dir=raw_dir)
    raw_dfs   = extractor.extract_all()

    # ── 2. VALIDATE SCHEMAS ────────────────────────────────────────────────────
    logger.info("\n--- PHASE 3.2: SCHEMA VALIDATION & CONTRACT AUDIT ---")
    validator   = SchemaValidator()
    val_results = validator.validate_all(raw_dfs)
    failed = [k for k, v in val_results.items() if not v['valid']]
    if failed:
        logger.warning(f"Schema validation warnings encountered on: {failed}")
    else:
        logger.info("All raw datasets passed initial schema contracts.")

    # ── 3. CLEAN & DERIVE ──────────────────────────────────────────────────────
    logger.info("\n--- PHASE 3.3: DATA CLEANING & DERIVED BUSINESS METRICS ---")
    cleaner     = DataCleaner()
    cleaned_dfs = cleaner.clean_all(raw_dfs)

    # ── 4. LOAD STAGING TABLES ─────────────────────────────────────────────────
    logger.info("\n--- PHASE 3.4: STAGING REPOSITORY INGESTION ---")
    loader          = WarehouseLoader(db_path=db_path)
    staging_payload = {f"stg_{k}": v for k, v in cleaned_dfs.items()}
    loader.load_to_sqlite(staging_payload, prefix="")

    # ── 5. TRANSFORM TO STAR SCHEMA ────────────────────────────────────────────
    logger.info("\n--- PHASE 3.5: DIMENSIONAL STAR SCHEMA TRANSFORMATION ---")
    transformer  = DimensionalTransformer()
    dim_tables, lookup_maps = transformer.build_dimensions(cleaned_dfs)
    fact_tables  = transformer.build_facts(cleaned_dfs, lookup_maps)

    # ── 6. LOAD WAREHOUSE & EXPORT MARTS ───────────────────────────────────────
    logger.info("\n--- PHASE 3.6: LOADING ANALYTICAL WAREHOUSE & EXPORTING MARTS ---")
    all_star_tables = {**dim_tables, **fact_tables}
    loader.load_to_sqlite(all_star_tables, prefix="")
    loader.create_indexes()
    loader.export_csv_marts(all_star_tables, output_dir=processed_dir)

    # Optional PostgreSQL load
    loader.load_to_postgres(all_star_tables)

    # ── 7. POST-LOAD VERIFICATION & AUDIT ─────────────────────────────────────
    logger.info("\n--- PHASE 3.7: DATA INTEGRITY POST-LOAD AUDIT ---")
    conn = sqlite3.connect(db_path)
    audit_summary = []
    for tbl in list(all_star_tables.keys()):
        count = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        audit_summary.append({"Table": tbl, "Rows": count})
    conn.close()

    df_audit = pd.DataFrame(audit_summary)
    logger.info("\n" + df_audit.to_string(index=False))

    # ── 9. BATCH INFERENCE & SCORING ───────────────────────────────────────────
    if run_inference and os.path.exists(MODEL_PATH):
        logger.info("\n--- PHASE 9: BATCH INFERENCE & SCORING ---")
        try:
            # Import here to avoid mandatory dependency at ETL-only runtime
            from ml.batch_inference import BatchInferenceEngine
            engine = BatchInferenceEngine(model_path=MODEL_PATH, db_path=db_path)
            engine.run()
        except Exception as exc:
            logger.warning(f"Phase 9 Batch Inference skipped due to error: {exc}")

        # ── 9b. INFERENCE BUSINESS REPORT ──────────────────────────────────────
        logger.info("\n--- PHASE 9b: INFERENCE BUSINESS REPORT GENERATION ---")
        try:
            from ml.inference_report import InferenceReportBuilder
            report_builder = InferenceReportBuilder(db_path=db_path)
            report_builder.build()
        except Exception as exc:
            logger.warning(f"Phase 9b Report Generation skipped due to error: {exc}")

    elif run_inference:
        logger.info(
            "\n--- PHASE 9: SKIPPED (champion model not found) ---\n"
            f"   Expected at: {MODEL_PATH}\n"
            "   Run Phase 8 (churn_model.py) to train the champion model first."
        )

    total_time = time.time() - pipeline_start
    logger.info("=" * 80)
    logger.info(f"PIPELINE EXECUTION COMPLETED SUCCESSFULLY IN {total_time:.2f} SECONDS")
    logger.info("=" * 80)
    return True


if __name__ == '__main__':
    success = run_etl_pipeline(run_inference=True)
    if not success:
        sys.exit(1)
