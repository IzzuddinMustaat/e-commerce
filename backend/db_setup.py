
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pymongo import MongoClient, ASCENDING, DESCENDING
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = "coffeeshop"
LOCAL_TZ = timezone(timedelta(hours=8))  # Malaysia time (UTC+8)

client = MongoClient(MONGO_URI)
db = client[DB_NAME]


# ---------------------------------------------------------------------------
# 1. Create collections
# ---------------------------------------------------------------------------
def create_collections():
    existing = db.list_collection_names()

    if "beverages" not in existing:
        db.create_collection(
            "beverages",
            validator={
                "$jsonSchema": {
                    "bsonType": "object",
                    "required": ["sku", "name", "category", "price"],
                    "properties": {
                        "sku": {"bsonType": "string"},
                        "name": {"bsonType": "string"},
                        "category": {
                            "enum": ["coffee", "tea", "other"]
                        },
                        "price": {
                            "bsonType": ["double", "int", "long"],
                            "minimum": 0
                        },
                        "milk_based": {"bsonType": "bool"},
                        "temperatures": {
                            "bsonType": "array",
                            "items": {"enum": ["hot", "iced"]}
                        },
                        "sizes": {
                            "bsonType": "array",
                            "items": {"bsonType": "string"}
                        },
                        "created_at": {"bsonType": "date"}
                    }
                }
            }
        )

    if "sales" not in existing:
        db.create_collection(
            "sales",
            validator={
                "$jsonSchema": {
                    "bsonType": "object",
                    "required": [
                        "beverage_sku",
                        "quantity",
                        "hour",
                        "day_of_week"
                    ],
                    "properties": {
                        "order_id": {"bsonType": "string"},
                        "beverage_sku": {"bsonType": "string"},
                        "beverage_name": {"bsonType": "string"},
                        "category": {"bsonType": "string"},
                        "quantity": {
                            "bsonType": "int",
                            "minimum": 1
                        },
                        "unit_price": {
                            "bsonType": ["double", "int", "long"]
                        },
                        "size": {"bsonType": "string"},
                        "temperature": {
                            "enum": ["hot", "iced"]
                        },
                        "milk_type": {"bsonType": "string"},
                        "sugar_level": {"bsonType": "string"},
                        "order_type": {
                            "enum": [
                                "dine-in",
                                "takeaway",
                                "delivery"
                            ]
                        },
                        "payment_method": {"bsonType": "string"},
                        "hour": {
                            "bsonType": "int",
                            "minimum": 0,
                            "maximum": 23
                        },
                        "day_of_week": {
                            "bsonType": "int",
                            "minimum": 0,
                            "maximum": 6
                        }
                    }
                }
            }
        )

    if "feedback" not in existing:
        db.create_collection(
            "feedback",
            validator={
                "$jsonSchema": {
                    "bsonType": "object",
                    "required": [
                        "beverage_sku",
                        "rating",
                        "created_at",
                        "date"
                    ],
                    "properties": {
                        "beverage_sku": {"bsonType": "string"},
                        "rating": {
                            "bsonType": "int",
                            "minimum": 1,
                            "maximum": 5
                        },
                        "comment": {"bsonType": "string"},
                        "created_at": {"bsonType": "date"},
                        "date": {"bsonType": "string"}
                    }
                }
            }
        )


# ---------------------------------------------------------------------------
# 2. Create indexes
# ---------------------------------------------------------------------------
def create_indexes():
    db.beverages.create_index(
        [("sku", ASCENDING)],
        unique=True
    )

    db.sales.create_index([
        ("beverage_sku", ASCENDING),
        ("day_of_week", ASCENDING),
        ("hour", ASCENDING)
    ])

    db.feedback.create_index([
        ("beverage_sku", ASCENDING),
        ("created_at", DESCENDING)
    ])


# ---------------------------------------------------------------------------
# 3. Sample beverage data
# ---------------------------------------------------------------------------
# sku, name, category, price, milk_based, popularity weight

BEVERAGES = [
    ("COF-001", "Spanish Latte", "coffee", 14.0, True, 10),
    ("COF-002", "Americano", "coffee", 9.0, False, 8),
    ("COF-003", "Cappuccino", "coffee", 12.0, True, 6),
    ("COF-004", "Flat White", "coffee", 13.0, True, 4),
    ("COF-005", "Caramel Macchiato", "coffee", 15.0, True, 6),
    ("COF-006", "Mocha", "coffee", 14.0, True, 5),
    ("COF-007", "Espresso", "coffee", 7.0, False, 2),
    ("TEA-001", "Matcha Latte", "tea", 15.0, True, 5),
    ("TEA-002", "Thai Milk Tea", "tea", 10.0, True, 5),
    ("TEA-003", "Jasmine Green Tea", "tea", 8.0, False, 3),
    ("TEA-004", "Lemon Iced Tea", "tea", 8.0, False, 4),
    ("TEA-005", "Chai Latte", "tea", 13.0, True, 3),
]

HOUR_WEIGHT = {
    7: 3,
    8: 6,
    9: 7,
    10: 5,
    11: 4,
    12: 5,
    13: 5,
    14: 6,
    15: 7,
    16: 6,
    17: 5,
    18: 4,
    19: 4,
    20: 3,
    21: 2
}

COMMENTS = [
    "Perfect sweetness",
    "Too sweet",
    "Great aroma",
    "Coffee tasted a bit bitter",
    "Fast service",
    "Loved it",
    "Too watery",
    "Will order again"
]


# ---------------------------------------------------------------------------
# 4. Generate sample data
# ---------------------------------------------------------------------------
def seed_sample_data(days=120):

    if db.beverages.count_documents({}) > 0:
        print("Data already seeded, skipping. Use --reset to start over.")
        return

    now = datetime.now(LOCAL_TZ)

    db.beverages.insert_many([
        {
            "sku": sku,
            "name": name,
            "category": category,
            "price": float(price),
            "milk_based": milk,
            "temperatures": ["hot", "iced"],
            "sizes": ["S", "M", "L"],
            "created_at": now - timedelta(days=days)
        }
        for sku, name, category, price, milk, _ in BEVERAGES
    ])

    weights = [b[5] for b in BEVERAGES]

    sales = []
    feedback = []
    order_no = 0

    for d in range(days, 0, -1):

        day = (now - timedelta(days=d)).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        weekend = 1.4 if day.weekday() >= 5 else 1.0

        for hour, hour_weight in HOUR_WEIGHT.items():

            number_of_orders = (
                int(
                    random.randint(0, 3)
                    * hour_weight
                    * weekend / 3
                )
                + random.randint(0, 2)
            )

            for _ in range(number_of_orders):

                sku, name, category, price, milk, _ = random.choices(
                    BEVERAGES,
                    weights=weights
                )[0]

                when = day.replace(
                    hour=hour,
                    minute=random.randint(0, 59),
                    second=random.randint(0, 59)
                )

                iced_chance = (
                    0.75 if 12 <= hour <= 17 else 0.35
                )

                order_no += 1

                # Sales stores hour and weekday, not a full date.
                sales.append({
                    "order_id": f"ORD-{order_no:06d}",
                    "beverage_sku": sku,
                    "beverage_name": name,
                    "category": category,
                    "quantity": random.choices(
                        [1, 2, 3],
                        weights=[75, 20, 5]
                    )[0],
                    "unit_price": float(price),
                    "size": random.choice(["S", "M", "L"]),
                    "temperature": (
                        "iced"
                        if random.random() < iced_chance
                        else "hot"
                    ),
                    "milk_type": (
                        random.choice([
                            "full cream",
                            "oat",
                            "soy",
                            "almond"
                        ])
                        if milk else "none"
                    ),
                    "sugar_level": random.choice([
                        "0%", "50%", "100%"
                    ]),
                    "order_type": random.choice([
                        "dine-in",
                        "takeaway",
                        "delivery"
                    ]),
                    "payment_method": random.choice([
                        "cash",
                        "card",
                        "ewallet"
                    ]),
                    "hour": hour,
                    "day_of_week": when.weekday()
                })

                if random.random() < 0.25:

                    feedback_time = when + timedelta(
                        minutes=random.randint(10, 240)
                    )

                    feedback.append({
                        "beverage_sku": sku,
                        "rating": random.randint(1, 5),
                        "comment": random.choice(COMMENTS),
                        "created_at": feedback_time,
                        "date": feedback_time.strftime("%Y-%m-%d")
                    })

    if sales:
        db.sales.insert_many(sales)

    if feedback:
        db.feedback.insert_many(feedback)

    print(
        f"Seeded {len(BEVERAGES)} beverages, "
        f"{len(sales)} sales, {len(feedback)} feedback."
    )


# ---------------------------------------------------------------------------
# 5. Load daily demand DataFrame directly from sales
# ---------------------------------------------------------------------------
def load_daily_dataframe(beverage_sku=None):
    """Calculate demand by beverage and day of the week."""

    import pandas as pd

    match = {}

    if beverage_sku:
        match["beverage_sku"] = beverage_sku

    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": {
                    "beverage_sku": "$beverage_sku",
                    "day_of_week": "$day_of_week"
                },
                "beverage_name": {
                    "$first": "$beverage_name"
                },
                "category": {
                    "$first": "$category"
                },
                "units_sold": {
                    "$sum": "$quantity"
                },
                "revenue": {
                    "$sum": {
                        "$multiply": [
                            "$quantity",
                            "$unit_price"
                        ]
                    }
                },
                "iced_units": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$temperature", "iced"]},
                            "$quantity",
                            0
                        ]
                    }
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "beverage_sku": "$_id.beverage_sku",
                "day_of_week": "$_id.day_of_week",
                "beverage_name": 1,
                "category": 1,
                "units_sold": 1,
                "revenue": 1,
                "iced_units": 1
            }
        },
        {
            "$sort": {
                "beverage_sku": 1,
                "day_of_week": 1
            }
        }
    ]

    demand = pd.DataFrame(
        list(db.sales.aggregate(pipeline))
    )

    if demand.empty:
        return demand

    # Calculate average rating and number of reviews per beverage.
    feedback = pd.DataFrame(
        list(db.feedback.find(
            {
                "beverage_sku": {
                    "$in": demand["beverage_sku"].unique().tolist()
                }
            },
            {
                "_id": 0,
                "beverage_sku": 1,
                "rating": 1
            }
        ))
    )

    if not feedback.empty:

        ratings = feedback.groupby("beverage_sku").agg(
            avg_rating=("rating", "mean"),
            feedback_count=("rating", "count")
        ).reset_index()

        demand = demand.merge(
            ratings,
            on="beverage_sku",
            how="left"
        )

    demand["is_weekend"] = demand["day_of_week"] >= 5

    return demand


# ---------------------------------------------------------------------------
# 6. Main program
# ---------------------------------------------------------------------------
if __name__ == "__main__":

    try:

        if "--reset" in sys.argv:
            client.drop_database(DB_NAME)
            print(f"Dropped database '{DB_NAME}'.")

        create_collections()
        create_indexes()
        seed_sample_data()

        df = load_daily_dataframe()

        print("\nDemand data preview:")
        print(df.head())

        print(
            f"\nDemand rows ready for modelling: {len(df)}"
        )

    finally:
        client.close()
