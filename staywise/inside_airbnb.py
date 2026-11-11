"""Inside Airbnb public listing data helpers (Airbnb only)."""

from __future__ import annotations

import math

import pandas as pd


LISBON_LISTINGS_URL = (
    "https://data.insideairbnb.com/portugal/lisbon/lisbon/2026-09-19/"
    "data/listings.csv.gz"
)
SOURCE_PAGE = "https://insideairbnb.com/pt/get-the-data/"


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def clean_listing_data(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize useful listing fields across Inside Airbnb export versions."""
    frame = frame.copy()
    for col in ("price", "latitude", "longitude", "bedrooms", "accommodates",
                "review_scores_rating", "availability_365", "number_of_reviews"):
        if col in frame:
            frame[col] = pd.to_numeric(
                frame[col].astype(str).str.replace(r"[^0-9.\-]", "", regex=True),
                errors="coerce",
            )
    if "bedrooms" not in frame:
        frame["bedrooms"] = pd.NA
    if "accommodates" not in frame:
        frame["accommodates"] = pd.NA
    if "price" not in frame:
        frame["price"] = pd.NA
    if "latitude" not in frame or "longitude" not in frame:
        raise ValueError("The Inside Airbnb file is missing coordinates.")
    frame = frame.dropna(subset=["latitude", "longitude", "price"])
    frame = frame[frame["price"] > 0]
    return frame


def listings_within_radius(
    frame: pd.DataFrame,
    latitude: float,
    longitude: float,
    radius_km: float,
    bedrooms: int | None = None,
    capacity: int | None = None,
) -> pd.DataFrame:
    """Filter Airbnb listings by distance and optional bedroom/capacity match."""
    result = clean_listing_data(frame)
    result["distance_km"] = result.apply(
        lambda row: distance_km(latitude, longitude, row["latitude"], row["longitude"]),
        axis=1,
    )
    result = result[result["distance_km"] <= radius_km]
    if bedrooms is not None and "bedrooms" in result:
        result = result[result["bedrooms"].isna() | (result["bedrooms"] == bedrooms)]
    if capacity is not None and "accommodates" in result:
        result = result[result["accommodates"].isna() | (result["accommodates"] >= capacity)]
    return result.sort_values("distance_km")
