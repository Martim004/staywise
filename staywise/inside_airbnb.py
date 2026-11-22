"""Inside Airbnb public listing data helpers (Airbnb only)."""

from __future__ import annotations

import math

import pandas as pd


LISTINGS_URL_BY_CITY = {
    "Lisbon": "https://data.insideairbnb.com/portugal/lisbon/lisbon/2026-09-19/data/listings.csv.gz",
    "Porto": "https://data.insideairbnb.com/portugal/norte/porto/2026-09-19/data/listings.csv.gz",
}
LISBON_LISTINGS_URL = LISTINGS_URL_BY_CITY["Lisbon"]
SOURCE_PAGE = "https://insideairbnb.com/pt/get-the-data/"


def city_for_area(area: str | None) -> str:
    """Return the supported Inside Airbnb city for a saved property area."""
    return "Porto" if "porto" in str(area or "").casefold() or "oporto" in str(area or "").casefold() else "Lisbon"


def area_with_city(neighborhood: str, city: str) -> str:
    """Persist the selected supported city alongside its neighborhood label."""
    if city not in LISTINGS_URL_BY_CITY:
        raise ValueError("StayWise currently supports properties in Lisbon and Porto.")
    import re
    cleaned = re.sub(r"[,\s]*(?:Lisbon|Lisboa|Porto|Oporto)(?:,\s*Portugal)?\s*$", "", neighborhood.strip(), flags=re.IGNORECASE).strip(" ,")
    return f"{cleaned}, {city}" if cleaned else city


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
    result["distance_km"] = [
        distance_km(latitude, longitude, listing_latitude, listing_longitude)
        for listing_latitude, listing_longitude in zip(result["latitude"], result["longitude"])
    ]
    result = result[result["distance_km"] <= radius_km]
    if bedrooms is not None and "bedrooms" in result:
        result = result[result["bedrooms"].isna() | (result["bedrooms"] == bedrooms)]
    if capacity is not None and "accommodates" in result:
        result = result[result["accommodates"].isna() | (result["accommodates"] >= capacity)]
    return result.sort_values("distance_km")
