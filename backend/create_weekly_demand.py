
import os
from pymongo import MongoClient, ASCENDING

# MongoDB configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = "coffeeshop"
COLLECTION_NAME = "weekly_demand"

# Connect to MongoDB
client = MongoClient(MONGO_URI)
db = client[DB_NAME]


def create_weekly_demand_collection():
    try:
        # Check whether the collection already exists
        if COLLECTION_NAME in db.list_collection_names():
            print("weekly_demand collection already exists.")
        else:
            db.create_collection(COLLECTION_NAME)
            print("weekly_demand collection created successfully.")

        # Prevent duplicate predictions for the same beverage and week
        db[COLLECTION_NAME].create_index(
            [
                ("beverage_sku", ASCENDING),
                ("week_start", ASCENDING)
            ],
            unique=True
        )

        print("Weekly demand index is ready.")

    finally:
        client.close()


if __name__ == "__main__":
    create_weekly_demand_collection()
