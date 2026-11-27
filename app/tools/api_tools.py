import requests
from langchain_core.tools import tool

from app.tools.base import ok, fail, safe
from app.tools.schemas import WeatherInput, ConvertCurrencyInput, Weather, Conversion

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
FX_URL = "https://api.frankfurter.dev/v1/latest"

WMO = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
       45: "fog", 48: "fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
       61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow",
       75: "heavy snow", 80: "rain showers", 81: "rain showers", 82: "violent rain showers",
       95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail"}


def _get(url: str, params: dict, attempts: int = 2) -> requests.Response:
    last = None
    for _ in range(attempts):                      
        try:
            return requests.get(url, params=params, timeout=10)
        except requests.RequestException as e:
            last = e
    raise last


@tool("get_weather", args_schema=WeatherInput)
@safe
def get_weather(city: str) -> dict:
    """Get the current weather (temperature, humidity, wind, conditions) for a city."""
    geo = _get(GEO_URL, {"name": city, "count": 1, "language": "en", "format": "json"})
    geo.raise_for_status()
    results = geo.json().get("results")
    if not results:
        return fail(f"Could not find a city named '{city}'.")
    place = results[0]

    w = _get(WEATHER_URL, {
        "latitude": place["latitude"], "longitude": place["longitude"],
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
    })
    w.raise_for_status()
    cur = w.json()["current"]
    return ok(Weather(
        city=place["name"], country=place.get("country", ""),
        temperature_c=cur["temperature_2m"], humidity_pct=cur["relative_humidity_2m"],
        wind_kmh=cur["wind_speed_10m"],
        conditions=WMO.get(cur["weather_code"], f"weather code {cur['weather_code']}"),
    ).model_dump())


@tool("convert_currency", args_schema=ConvertCurrencyInput)
@safe
def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    """Convert an amount between currencies using the latest ECB reference rates (daily, not real-time)."""
    src, dst = from_currency.strip().upper(), to_currency.strip().upper()
    if src == dst:
        return ok(Conversion(amount=amount, from_currency=src, to_currency=dst,
                             rate=1.0, converted=amount, rate_date="n/a").model_dump())

    resp = _get(FX_URL, {"base": src, "symbols": dst})
    if resp.status_code in (404, 422):
        return fail(f"Unsupported currency code: {src} or {dst}.")
    resp.raise_for_status()
    data = resp.json()
    rate = data["rates"][dst]
    return ok(Conversion(amount=amount, from_currency=src, to_currency=dst, rate=rate,
                         converted=round(amount * rate, 2), rate_date=data["date"]).model_dump())