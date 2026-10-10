from pathlib import Path
import json
import os
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from google import genai
from google.genai.errors import APIError
from pydantic import BaseModel, Field
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "backend" / ".env")

WEEK = "12–18 October"
PRODUCTS: list[dict[str, Any]] = [
    {
        "id": "latte",
        "name": "Iced oat latte",
        "week": WEEK,
        "unit": "cups",
        "price": 6.5,
        "days": 5,
        "limit": 160,
        "survey": {"plan": 18, "unsure": 11, "n": 40},
        "sales": [
            {"d": "14–20 Sep", "u": 142},
            {"d": "21–27 Sep", "u": 128},
            {"d": "28 Sep–4 Oct", "u": 155},
        ],
        "themes": {
            "sweet": "Sweetness",
            "ice": "Too much ice",
            "price": "Price",
            "stock": "Sold out",
            "pos": "Positive",
        },
        "comments": [
            ["Really tasty but a bit too sweet for me.", "sweet"],
            ["Loved the oat flavour, sweetness was a little much.", "sweet"],
            ["Could you do a less sweet option?", "sweet"],
            ["Too much ice, cup was half empty after 10 minutes.", "ice"],
            ["Great price for campus.", "price"],
            ["Sweet, but I'd still buy again.", "sweet"],
            ["Ice melts quickly, drink gets watery.", "ice"],
            ["Sold out before I got there. Please make more!", "stock"],
            ["Perfect before my afternoon class.", "pos"],
            ["Syrup is too sweet, ask for half sweet.", "sweet"],
            ["A bit pricey compared to the canteen.", "price"],
            ["Less ice please.", "ice"],
        ],
        "exp": {
            "sweet": (
                "Test a half-sweet version next week: make 20 of the planned cups "
                "with half the syrup, label them “Less sweet”, and compare how "
                "many of each sell."
            )
        },
    },
    {
        "id": "brew",
        "name": "Cold brew",
        "week": WEEK,
        "unit": "cups",
        "price": 7,
        "days": 5,
        "limit": 120,
        "survey": {"plan": 14, "unsure": 9, "n": 38},
        "sales": [
            {"d": "14–20 Sep", "u": 104},
            {"d": "21–27 Sep", "u": 88},
            {"d": "28 Sep–4 Oct", "u": 96},
        ],
        "themes": {
            "bitter": "Bitterness",
            "stock": "Sold out",
            "size": "Cup size",
            "pos": "Positive",
        },
        "comments": [
            ["Smooth and strong, great before lectures.", "pos"],
            ["A bit bitter without milk.", "bitter"],
            ["Sold out on Thursday, please make more.", "stock"],
            ["Would love a bigger cup size.", "size"],
            ["Great value for the size.", "pos"],
            ["Too bitter for me, needs a sweeter option.", "bitter"],
            ["Cold brew is my go-to now.", "pos"],
            ["Ran out by Friday lunch.", "stock"],
        ],
        "exp": {
            "bitter": (
                "Offer a small splash of oat milk or a syrup shot on the side "
                "for 15 cups and track how many buyers choose it."
            )
        },
    },
    {
        "id": "peach",
        "name": "Peach tea",
        "week": WEEK,
        "unit": "cups",
        "price": 5.5,
        "days": 5,
        "limit": 100,
        "survey": {"plan": 10, "unsure": 12, "n": 35},
        "sales": [
            {"d": "21–27 Sep", "u": 52},
            {"d": "28 Sep–4 Oct", "u": 61},
        ],
        "themes": {
            "sweet": "Sweetness",
            "watery": "Gets watery",
            "pos": "Positive",
        },
        "comments": [
            ["Refreshing but a little too sweet.", "sweet"],
            ["Love the peach flavour.", "pos"],
            ["Gets watery once the ice melts.", "watery"],
            ["Nice on a hot afternoon.", "pos"],
            ["Too sweet for me.", "sweet"],
            ["Would buy again.", "pos"],
        ],
        "exp": {
            "sweet": (
                "Test a lighter-sweet batch: brew 20 cups with less syrup, "
                "label them “Light”, and compare sales against the regular cups."
            )
        },
    },
]
PRODUCTS_BY_ID = {product["id"]: product for product in PRODUCTS}

SYSTEM_INSTRUCTION = (
    "You are a planning assistant for a campus seller. Use only the supplied "
    "demo data and conversation; never invent sales, survey numbers, or quotes. "
    "Survey responses are intentions, not completed sales, and must never be "
    "added to sales. Any quantity is a demo planning suggestion, not a validated "
    "prediction. The final batch decision belongs to the seller. Keep answers "
    "short (under 120 words), plain, and practical. Do not offer to post or sell "
    "anything."
)

app = FastAPI(title="Batchwise API")
_mongo_client: MongoClient | None = None
_memory_plans: dict[str, int] = {}


class PlanRequest(BaseModel):
    quantity: int = Field(ge=0)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    product_id: str
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=10)


def _plans_collection() -> Collection | None:
    global _mongo_client
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        return None
    if _mongo_client is None:
        _mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=3000)
    database = os.getenv("MONGO_DB", "batchwise")
    return _mongo_client[database]["seller_plans"]


def _read_plans() -> dict[str, int]:
    try:
        collection = _plans_collection()
        if collection is None:
            return _memory_plans.copy()
        return {
            entry["product_id"]: entry["quantity"]
            for entry in collection.find({}, {"_id": False})
        }
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503, detail="Plan storage is unavailable."
        ) from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "plan_storage": "mongodb" if os.getenv("MONGO_URI") else "memory",
    }


@app.get("/api/products")
def get_products() -> dict[str, Any]:
    return {"week": WEEK, "products": PRODUCTS}


@app.get("/api/plans")
def get_plans() -> dict[str, int]:
    return _read_plans()


@app.put("/api/plans/{product_id}")
def save_plan(product_id: str, plan: PlanRequest) -> dict[str, int]:
    product = PRODUCTS_BY_ID.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    if product["limit"] and plan.quantity > product["limit"]:
        raise HTTPException(
            status_code=422,
            detail=f"Quantity cannot exceed the limit of {product['limit']}.",
        )
    try:
        collection = _plans_collection()
        if collection is None:
            _memory_plans[product_id] = plan.quantity
        else:
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
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503, detail="Plan storage is unavailable."
        ) from exc
    return _read_plans()


@app.delete("/api/plans")
def reset_plans() -> dict[str, int]:
    try:
        collection = _plans_collection()
        if collection is None:
            _memory_plans.clear()
        else:
            collection.delete_many({})
    except PyMongoError as exc:
        raise HTTPException(
            status_code=503, detail="Plan storage is unavailable."
        ) from exc
    return {}


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, str]:
    product = PRODUCTS_BY_ID.get(request.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503, detail="The AI assistant is not configured."
        )

    context = {
        "planning_week": WEEK,
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
