import os
import math
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pandas as pd
from pymongo import MongoClient, UpdateOne


# ============================================================
# 1. CONFIGURATION
# ============================================================

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = "coffeeshop"
COLLECTION_NAME = "sales"                  # input collection
OUTPUT_COLLECTION_NAME = "weekly_demand"   # output collection

# IMPORTANT: the sales documents have no calendar date, so the script
# cannot tell how long the data took to collect. Set this to the number
# of weeks of trading that the documents in "sales" represent.
# Predictions scale directly with this number
# (for example, 8 weeks instead of 4 halves every prediction).
WEEKS_OF_DATA = 17   # db_setup.py seeds 120 days of sales (~17 weeks)

# This script lives in backend/AI/, so parent.parent is backend/.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = PROJECT_ROOT / "beverage_demand_prediction.csv"


# ============================================================
# 2. FETCH SALES DATA FROM MONGODB
# ============================================================

def fetch_sales():
    client = MongoClient(MONGO_URI)

    try:
        collection = client[DB_NAME][COLLECTION_NAME]

        projection = {
            "_id": 0,
            "beverage_sku": 1,
            "beverage_name": 1,
            "quantity": 1
        }

        documents = list(collection.find({}, projection))

        if not documents:
            raise ValueError(
                f"No documents found in {DB_NAME}.{COLLECTION_NAME}."
            )

        df = pd.DataFrame(documents)

        required_columns = ["beverage_sku", "beverage_name", "quantity"]
        missing_columns = [
            column for column in required_columns
            if column not in df.columns
        ]

        if missing_columns:
            raise ValueError(
                f"Missing required fields: {missing_columns}"
            )

        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")

        df = df.dropna(subset=required_columns)
        df = df[df["quantity"] > 0].copy()

        if df.empty:
            raise ValueError(
                "No valid sales were found. Check the quantity field."
            )

        df["beverage_sku"] = df["beverage_sku"].astype(str)
        df["beverage_name"] = df["beverage_name"].astype(str)

        print(f"Sales records loaded: {len(df)}")
        print(f"Total cups in data: {int(df['quantity'].sum())}")

        return df

    finally:
        client.close()


# ============================================================
# 3. FORECAST NEXT WEEK'S DEMAND
# ============================================================

def forecast_next_week(df):
    if WEEKS_OF_DATA <= 0:
        raise ValueError("WEEKS_OF_DATA must be greater than 0.")

    # Total cups sold for each beverage across all the data.
    totals = (
        df.groupby("beverage_sku", as_index=False)
        .agg(
            beverage_type=("beverage_name", "first"),
            total_cups=("quantity", "sum")
        )
    )

    # Average cups per week, rounded up to a whole number.
    totals["predicted_cups"] = (
        (totals["total_cups"] / WEEKS_OF_DATA)
        .apply(math.ceil)
        .astype(int)
    )

    weekly = totals[
        ["beverage_sku", "beverage_type", "predicted_cups"]
    ].sort_values("predicted_cups", ascending=False)

    return weekly.reset_index(drop=True)


# ============================================================
# 4. SAVE THE FORECAST TO MONGODB (weekly_demand collection)
# ============================================================

def get_next_week_range():
    # The forecast covers the coming Monday to Sunday.
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    days_until_monday = 7 - today.weekday()
    week_start = today + timedelta(days=days_until_monday)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def save_to_mongodb(weekly, week_start=None, week_end=None):
    client = MongoClient(MONGO_URI)

    try:
        collection = client[DB_NAME][OUTPUT_COLLECTION_NAME]

        documents = [
            {
                "beverage_type": row.beverage_type,
                "predicted_cups": int(row.predicted_cups)
            }
            for row in weekly.itertuples(index=False)
        ]

        # Remove the old unique index from earlier versions and the
        # previous forecast, then store the latest numbers.
        collection.drop_indexes()
        collection.delete_many({})
        result = collection.insert_many(documents)

        print(f"\nMongoDB: {len(result.inserted_ids)} documents inserted")
        print(f"Server: {client.address}")
        print(f"Collection: {DB_NAME}.{OUTPUT_COLLECTION_NAME}")
        print(
            "Documents now in collection:",
            collection.count_documents({})
        )

    finally:
        client.close()

# ============================================================
# 5. SAVE TO CSV AND DISPLAY
# ============================================================

def save_and_display(weekly, week_start, week_end):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    weekly[["beverage_type", "predicted_cups"]].to_csv(
        OUTPUT_FILE, index=False
    )

    save_to_mongodb(weekly, week_start, week_end)

    print(
        f"\nPREDICTED BEVERAGE DEMAND "
        f"({week_start.date()} to {week_end.date()})"
    )
    print("=" * 45)
    print(
        weekly[["beverage_type", "predicted_cups"]]
        .to_string(index=False)
    )
    print("=" * 45)

    print("\nTotal predicted cups:", weekly["predicted_cups"].sum())
    print(f"Based on WEEKS_OF_DATA = {WEEKS_OF_DATA}")
    print(f"CSV saved to: {OUTPUT_FILE}")


# ============================================================
# 6. RUN THE COMPLETE PROCESS
# ============================================================

def main():
    print("Loading coffee shop sales data...")

    sales = fetch_sales()

    print("\nCalculating next week's demand...")

    weekly = forecast_next_week(sales)

    week_start, week_end = get_next_week_range()

    print("\nSaving the prediction results...")

    save_and_display(weekly, week_start, week_end)


if __name__ == "__main__":
    main()