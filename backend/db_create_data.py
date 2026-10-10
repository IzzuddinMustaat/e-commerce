import os
import random
import sys
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient, ASCENDING, DESCENDING

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = "coffeeshop"
LOCAL_TZ = timezone(timedelta(hours=8))  # Malaysia time (UTC+8)

client = MongoClient(MONGO_URI)
db = client[DB_NAME]


# ---------------------------------------------------------------------------
# 1. Create the collections (with validation rules) and indexes
# ---------------------------------------------------------------------------
def create_collections():
    existing = db.list_collection_names()

    if "beverages" not in existing:
        db.create_collection("beverages", validator={"$jsonSchema": {
            "bsonType": "object",
            "required": ["sku", "name", "category", "price"],
            "properties": {
                "sku": {"bsonType": "string"},
                "name": {"bsonType": "string"},
                "category": {"enum": ["coffee", "tea", "other"]},
                "price": {"bsonType": ["double", "int"], "minimum": 0},
                "milk_based": {"bsonType": "bool"},
                "temperatures": {"bsonType": "array", "items": {"enum": ["hot", "iced"]}},
                "sizes": {"bsonType": "array", "items": {"bsonType": "string"}},
                "created_at": {"bsonType": "date"},
            }}})

    if "sales" not in existing:
        db.create_collection("sales", validator={"$jsonSchema": {
            "bsonType": "object",
            "required": ["beverage_sku", "quantity", "hour"],
            "properties": {
                "order_id": {"bsonType": "string"},
                "beverage_sku": {"bsonType": "string"},
                "beverage_name": {"bsonType": "string"},
                "category": {"bsonType": "string"},
                "quantity": {"bsonType": "int", "minimum": 1},
                "unit_price": {"bsonType": ["double", "int"]},
                "size": {"bsonType": "string"},
                "temperature": {"enum": ["hot", "iced"]},
                "milk_type": {"bsonType": "string"},
                "sugar_level": {"bsonType": "string"},
                "order_type": {"enum": ["dine-in", "takeaway", "delivery"]},
                "payment_method": {"bsonType": "string"},
                "hour": {"bsonType": "int", "minimum": 0, "maximum": 23},
                "day_of_week": {"bsonType": "int", "minimum": 0, "maximum": 6},
            }}})

    if "feedback" not in existing:
        db.create_collection("feedback", validator={"$jsonSchema": {
            "bsonType": "object",
            "required": ["beverage_sku", "rating", "created_at", "date"],
            "properties": {
                "beverage_sku": {"bsonType": "string"},
                "rating": {"bsonType": "int", "minimum": 1, "maximum": 5},
                "comment": {"bsonType": "string"},
                "created_at": {"bsonType": "date"},
                "date": {"bsonType": "string"},
            }}})


def create_indexes():
    db.beverages.create_index([("sku", ASCENDING)], unique=True)
    db.sales.create_index([("beverage_sku", ASCENDING), ("hour", ASCENDING)])
    db.sales.create_index([("day_of_week", ASCENDING), ("hour", ASCENDING)])
    db.feedback.create_index([("beverage_sku", ASCENDING), ("created_at", DESCENDING)])


#