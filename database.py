
import os
import mysql.connector
import pandas as pd
from dotenv import load_dotenv

load_dotenv()


def connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "crop_analysis")
    )


def init_db():
    conn = connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS regions (
            region_id INT AUTO_INCREMENT PRIMARY KEY,
            region_name VARCHAR(120) NOT NULL UNIQUE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crops (
            crop_id INT AUTO_INCREMENT PRIMARY KEY,
            crop_name VARCHAR(120) NOT NULL UNIQUE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crop_records (
            record_id BIGINT AUTO_INCREMENT PRIMARY KEY,
            crop_id INT NOT NULL,
            region_id INT NOT NULL,
            year INT NOT NULL,
            cultivated_area DOUBLE NOT NULL,
            area_unit VARCHAR(30) NOT NULL,
            production DOUBLE NOT NULL,
            production_unit VARCHAR(30) NOT NULL,
            rainfall DOUBLE NULL,
            rainfall_unit VARCHAR(30) DEFAULT 'mm',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (crop_id) REFERENCES crops(crop_id),
            FOREIGN KEY (region_id) REFERENCES regions(region_id)
        )
    """)

    conn.commit()
    cursor.close()
    conn.close()


def load_records():
    conn = connection()

    try:
        query = """
            SELECT
                cr.record_id,
                c.crop_name AS crop,
                r.region_name AS region,
                cr.year,
                cr.cultivated_area,
                cr.area_unit,
                cr.production,
                cr.production_unit,
                cr.rainfall,
                cr.rainfall_unit,
                CASE
                    WHEN cr.cultivated_area > 0
                    THEN cr.production / cr.cultivated_area
                    ELSE NULL
                END AS yield_value
            FROM crop_records cr
            JOIN crops c ON cr.crop_id = c.crop_id
            JOIN regions r ON cr.region_id = r.region_id
            ORDER BY cr.year
        """

        return pd.read_sql(query, conn)

    finally:
        conn.close()


def db_status():
    try:
        conn = connection()
        conn.close()
        return "Connected"
    except Exception as error:
        print("Database connection error:", error)
        return "Not connected"
