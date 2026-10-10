from pathlib import Path
import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles 
from google import genai
from google.genai.errors import APIError
from pydantic import BaseModel, Field
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "backend" / ".env")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "coffeeshop")
LOCAL_TZ = timezone(timedelta(hours=8))

SYSTEM_INSTRUCTION = (
    "You are a planning assistant for a coffee shop seller. Use only the "
    "supplied MongoDB data and conversation; never invent sales, feedback, or "
    "survey data. Any quantity is a planning suggestion, not a validated "
    "prediction. When the product data includes predicted_cups, that is a "
    "forecast from the weekly_demand collection for next week; describe it as "
    "a forecast, not a guarantee. The final batch decision belongs to the "
    "seller. Keep answers short (under 120 words), plain, and practical. Do "
    "not offer to post or sell anything."
)

app = FastAPI(title="Batchwise API")

# Allow the frontend to be opened from another local port (e.g. VS Code Live Server on 5500).
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)
_mongo_client: MongoClient | None = None


class PlanRequest(BaseModel):
    quantity: int = Field(ge=0)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    product_id: str
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=10)


def _database() -> Database:
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    return _mongo_client[DB_NAME]


def _week_label(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{start.day}–{end.day} {end.strftime('%B')}"
    return f"{start.strftime('%d %b')}–{end.strftime('%d %b')}"


def _planning_week() -> tuple[str, date]:
    today = datetime.now(LOCAL_TZ).date()
    days_until_monday = 7 - today.weekday()
    monday = today + timedelta(days=days_until_monday)
    return _week_label(monday, monday + timedelta(days=6)), monday


def _date_from_sales_value(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=500, detail="Sales data contains an invalid date."
            ) from exc
    raise HTTPException(
        status_code=500, detail="Sales data is missing a usable date."
    )


def _load_predictions(database: Database) -> dict[str, int]:
    """Forecast cups per beverage from the weekly_demand collection.

    Documents look like:
        {"_id": ..., "beverage_type": "Spanish Latte", "predicted_cups": 312}

    The key is the beverage name in lower case so it can be matched against
    beverages.name. If a beverage has several documents, the newest one
    (highest _id) wins.
    """
    predictions: dict[str, int] = {}
    cursor = database["weekly_demand"].find(
        {},
        {"_id": False, "beverage_type": True, "predicted_cups": True},
    ).sort("_id", 1)
    for row in cursor:
        name = row.get("beverage_type")
        cups = row.get("predicted_cups")
        if not isinstance(name, str) or isinstance(cups, bool):
            continue
        if not isinstance(cups, (int, float)):
            continue
        predictions[name.strip().casefold()] = max(0, round(cups))
    return predictions


def _load_products() -> tuple[str, list[dict[str, Any]]]:
    database = _database()
    beverages = list(
        database["beverages"].find(
            {},
            {
                "_id": False,
                "sku": True,
                "name": True,
                "category": True,
                "price": True,
                "milk_based": True,
                "temperatures": True,
                "sizes": True,
            },
        )
    )
    skus = [beverage["sku"] for beverage in beverages]
    week, _ = _planning_week()
    if not skus:
        return week, []

    predictions = _load_predictions(database)

    current_monday = datetime.now(LOCAL_TZ).date()
    current_monday -= timedelta(days=current_monday.weekday())
    weekly_sales: dict[str, dict[date, dict[str, float]]] = {
        sku: {} for sku in skus
    }
    sales_pipeline = [
        {"$match": {"beverage_sku": {"$in": skus}}},
        {
            "$project": {
                "beverage_sku": True,
                "quantity": True,
                "unit_price": True,
                "sale_date": {
                    "$ifNull": [
                        "$date",
                        {
                            "$dateToString": {
                                "format": "%Y-%m-%d",
                                "date": "$ordered_at",
                                "timezone": "Asia/Kuala_Lumpur",
                            }
                        },
                    ]
                },
            }
        },
        {
            "$group": {
                "_id": {
                    "sku": "$beverage_sku",
                    "date": "$sale_date",
                },
                "units": {"$sum": "$quantity"},
                "revenue": {
                    "$sum": {
                        "$multiply": [
                            "$quantity",
                            {"$ifNull": ["$unit_price", 0]},
                        ]
                    }
                },
            }
        },
    ]
    for row in database["sales"].aggregate(sales_pipeline):
        sku = row["_id"]["sku"]
        sale_date = _date_from_sales_value(row["_id"]["date"])
        monday = sale_date - timedelta(days=sale_date.weekday())
        if monday >= current_monday:
            continue
        totals = weekly_sales[sku].setdefault(
            monday, {"units": 0, "revenue": 0}
        )
        totals["units"] += row["units"]
        totals["revenue"] += row["revenue"]

    comments_by_sku: dict[str, list[list[str]]] = {sku: [] for sku in skus}
    feedback_cursor = database["feedback"].find(
        {
            "beverage_sku": {"$in": skus},
            "comment": {"$type": "string", "$ne": ""},
        },
        {"_id": False, "beverage_sku": True, "comment": True},
    ).sort("created_at", -1)
    for feedback in feedback_cursor:
        comments = comments_by_sku[feedback["beverage_sku"]]
        if len(comments) < 20:
            comments.append([feedback["comment"], "feedback"])
        if all(len(items) >= 20 for items in comments_by_sku.values()):
            break

    products: list[dict[str, Any]] = []
    for beverage in beverages:
        sku = beverage["sku"]
        latest_weeks = sorted(weekly_sales[sku].items())[-3:]
        products.append(
            {
                "id": sku,
                "name": beverage["name"],
                "week": week,
                "unit": "cups",
                "price": float(beverage["price"]),
                "days": 7,
                "limit": None,
                "category": beverage.get("category", "unknown"),
                "milk_based": beverage.get("milk_based", False),
                "temperatures": beverage.get("temperatures", []),
                "sizes": beverage.get("sizes", []),
                "predicted_cups": predictions.get(
                    beverage["name"].strip().casefold()
                ),
                "sales": [
                    {
                        "d": _week_label(monday, monday + timedelta(days=6)),
                        "u": int(totals["units"]),
                        "revenue": float(totals["revenue"]),
                    }
                    for monday, totals in latest_weeks
                ],
                "comments": comments_by_sku[sku],
            }
        )
    return week, products


def _plans_collection() -> Collection:
    return _database()["seller_plans"]


def _read_plans() -> dict[str, int]:
    try:
        collection = _plans_collection()
        return {
            entry["product_id"]: entry["quantity"]
            for entry in collection.find({}, {"_id": False})
        }
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503, detail="Plan storage is unavailable."
        ) from exc


@app.get("/api/health")
def health() -> dict[str, str]:
    try:
        _database().command("ping")
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503, detail="MongoDB is unavailable."
        ) from exc
    return {"status": "ok", "database": DB_NAME, "storage": "mongodb"}


@app.get("/api/products")
def get_products() -> dict[str, Any]:
    try:
        week, products = _load_products()
        return {"week": week, "products": products}
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503, detail="Coffee shop data is unavailable."
        ) from exc


@app.get("/api/plans")
def get_plans() -> dict[str, int]:
    return _read_plans()


@app.put("/api/plans/{product_id}")
def save_plan(product_id: str, plan: PlanRequest) -> dict[str, int]:
    try:
        if not _database()["beverages"].find_one({"sku": product_id}, {"_id": True}):
            raise HTTPException(status_code=404, detail="Product not found.")
        collection = _plans_collection()
        collection.update_one(
            {"product_id": product_id},
            {
                "$set": {
                    "product_id": product_id,
                    "quantity": plan.quantity,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
    except HTTPException:
        raise
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503, detail="Plan storage is unavailable."
        ) from exc
    return _read_plans()


@app.delete("/api/plans")
def reset_plans() -> dict[str, int]:
    try:
        _plans_collection().delete_many({})
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503, detail="Plan storage is unavailable."
        ) from exc
    return {}


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, str]:
    try:
        _, products = _load_products()
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503, detail="Coffee shop data is unavailable."
        ) from exc
    product = next(
        (item for item in products if item["id"] == request.product_id), None
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503, detail="The AI assistant is not configured."
        )

    context = {
        "planning_week": product["week"],
        "selected_product": product,
        "seller_confirmed_plans": _read_plans(),
    }
    conversation = [
        {"role": message.role, "content": message.content}
        for message in request.history
    ]
    conversation.append({"role": "user", "content": request.message})
    prompt = (
        f"Current page data:\n{json.dumps(context, ensure_ascii=False)}\n\n"
        f"Conversation:\n{json.dumps(conversation, ensure_ascii=False)}"
    )
    try:
        response = genai.Client(api_key=api_key).models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            contents=prompt,
            config={"system_instruction": SYSTEM_INSTRUCTION},
        )
    except APIError as exc:
        raise HTTPException(
            status_code=502, detail="The AI assistant could not complete the request."
        ) from exc
    if not response.text:
        raise HTTPException(
            status_code=502, detail="The AI assistant returned an empty response."
        )
    return {"reply": response.text}

app.mount(
    "/",
    StaticFiles(directory=ROOT / "frontend", html=True),
    name="frontend",
)