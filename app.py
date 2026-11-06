
import os
from pathlib import Path

import pandas as pd
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, send_file
)
from dotenv import load_dotenv

from database import connection, load_records, db_status

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv(
    "SECRET_KEY", "development-secret-key"
)

REQUIRED_COLUMNS = [
    "crop", "region", "year",
    "cultivated_area", "production"
]


def validate_dataset(df):
    df.columns = [
        str(column).strip().lower()
        for column in df.columns
    ]

    missing = [
        column for column in REQUIRED_COLUMNS
        if column not in df.columns
    ]

    if missing:
        raise ValueError(
            "Missing columns: " + ", ".join(missing)
        )

    for column in ["crop", "region"]:
        df[column] = df[column].astype("string").str.strip()

        if df[column].isna().any() or (df[column] == "").any():
            raise ValueError(f"Missing values in {column}.")

    for column in ["year", "cultivated_area", "production"]:
        df[column] = pd.to_numeric(
            df[column], errors="coerce"
        )

        if df[column].isna().any():
            raise ValueError(f"Invalid values in {column}.")

        if not np.isfinite(df[column]).all():
            raise ValueError(f"Invalid values in {column}.")

    if (df["year"] % 1 != 0).any():
        raise ValueError("Year must be a whole number.")

    if ((df["year"] < 1900) | (df["year"] > 2100)).any():
        raise ValueError("Year must be between 1900 and 2100.")

    if (df["cultivated_area"] < 0).any():
        raise ValueError("Area cannot be negative.")

    if (df["production"] < 0).any():
        raise ValueError("Production cannot be negative.")

    df["year"] = df["year"].astype(int)

    defaults = {
        "rainfall": np.nan,
        "area_unit": "hectare",
        "production_unit": "tonne",
        "rainfall_unit": "mm"
    }

    for column, default in defaults.items():
        if column not in df.columns:
            df[column] = default

    df["rainfall"] = pd.to_numeric(
        df["rainfall"], errors="coerce"
    )

    if (df["rainfall"].dropna() < 0).any():
        raise ValueError("Rainfall cannot be negative.")

    for column in [
        "area_unit", "production_unit", "rainfall_unit"
    ]:
        df[column] = df[column].fillna(
            defaults[column]
        ).astype(str).str.strip()

    if (
        (df["area_unit"] == "").any()
        or (df["production_unit"] == "").any()
        or (df["rainfall_unit"] == "").any()
    ):
        raise ValueError("Unit fields cannot be blank.")

    df["yield_value"] = np.where(
        df["cultivated_area"] > 0,
        df["production"] / df["cultivated_area"],
        np.nan
    )

    return df


def save_records(df):
    conn = connection()
    cursor = conn.cursor()

    try:
        for row in df.to_dict("records"):
            cursor.execute(
                "INSERT INTO crops (crop_name) VALUES (%s) "
                "ON DUPLICATE KEY UPDATE crop_name=VALUES(crop_name)",
                (str(row["crop"]),)
            )
            cursor.execute(
                "SELECT crop_id FROM crops WHERE crop_name=%s",
                (str(row["crop"]),)
            )
            crop_id = cursor.fetchone()[0]

            cursor.execute(
                "INSERT INTO regions (region_name) VALUES (%s) "
                "ON DUPLICATE KEY UPDATE region_name=VALUES(region_name)",
                (str(row["region"]),)
            )
            cursor.execute(
                "SELECT region_id FROM regions WHERE region_name=%s",
                (str(row["region"]),)
            )
            region_id = cursor.fetchone()[0]

            rainfall = (
                None if pd.isna(row["rainfall"])
                else float(row["rainfall"])
            )

            cursor.execute("""
                INSERT INTO crop_records (
                    crop_id, region_id, year,
                    cultivated_area, area_unit,
                    production, production_unit,
                    rainfall, rainfall_unit
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                crop_id, region_id, int(row["year"]),
                float(row["cultivated_area"]),
                row["area_unit"],
                float(row["production"]),
                row["production_unit"],
                rainfall, row["rainfall_unit"]
            ))

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()


def get_data():
    try:
        return load_records(), None
    except Exception as error:
        return pd.DataFrame(), str(error)


@app.route("/")
def index():
    df, error = get_data()

    summary = {
        "records": len(df),
        "crops": df["crop"].nunique() if not df.empty else 0,
        "regions": df["region"].nunique() if not df.empty else 0,
        "years": df["year"].nunique() if not df.empty else 0
    }

    crop_rows = []
    region_rows = []

    if not df.empty:
        crop_rows = (
            df.groupby("crop", as_index=False)["production"]
            .sum().to_dict("records")
        )
        region_rows = (
            df.groupby("region", as_index=False)["production"]
            .sum().to_dict("records")
        )

    return render_template(
        "index.html",
        summary=summary,
        crop_rows=crop_rows,
        region_rows=region_rows,
        db_error=error,
        db_status=db_status()
    )


@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        file = request.files.get("dataset")

        if not file or not file.filename:
            flash("Please select a CSV file.", "error")
            return redirect(url_for("upload"))

        if not file.filename.lower().endswith(".csv"):
            flash("Please upload a CSV file only.", "error")
            return redirect(url_for("upload"))

        try:
            df = pd.read_csv(file)
            df = validate_dataset(df)
            save_records(df)
            flash(
                f"Successfully imported {len(df)} records.",
                "success"
            )
        except Exception as error:
            flash(f"Import failed: {error}", "error")

        return redirect(url_for("index"))

    return render_template("upload.html")


@app.route("/reports")
def reports():
    df, error = get_data()

    crop_report = []
    region_report = []

    if not df.empty:
        crop_report = (
            df.groupby(
                ["crop", "area_unit", "production_unit"],
                as_index=False
            )
            .agg(
                records=("record_id", "count"),
                total_area=("cultivated_area", "sum"),
                total_production=("production", "sum"),
                average_yield=("yield_value", "mean")
            )
            .round(3)
            .to_dict("records")
        )

        region_report = (
            df.groupby(
                ["region", "year", "production_unit"],
                as_index=False
            )
            .agg(
                total_production=("production", "sum"),
                total_area=("cultivated_area", "sum")
            )
            .round(3)
            .to_dict("records")
        )

    return render_template(
        "reports.html",
        crop_report=crop_report,
        region_report=region_report,
        db_error=error
    )


@app.route("/chart/<chart_type>.png")
def chart(chart_type):
    if chart_type not in ["production", "yield"]:
        return "Unknown chart", 404

    df, error = get_data()

    if error:
        return "Database connection failed.", 503

    if df.empty:
        return "Upload a CSV dataset first.", 404

    fig, ax = plt.subplots(figsize=(8, 4))

    if chart_type == "production":
        grouped = df.groupby("year")["production"].sum()
        ax.plot(grouped.index, grouped.values, marker="o")
        ax.set_title("Annual Production Trend")
        ax.set_ylabel("Production (check units)")
    else:
        valid = df.dropna(subset=["yield_value"])
        grouped = valid.groupby("year")["yield_value"].mean()
        ax.plot(grouped.index, grouped.values, marker="o")
        ax.set_title("Average Yield Trend")
        ax.set_ylabel("Production per area unit")

    ax.set_xlabel("Year")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    chart_path = Path("trend_chart.png")
    fig.savefig(chart_path)
    plt.close(fig)

    return send_file(chart_path, mimetype="image/png")


if __name__ == "__main__":
    app.run(debug=True)
