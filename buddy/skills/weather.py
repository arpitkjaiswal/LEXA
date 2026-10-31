"""Current weather from fixed Open-Meteo endpoints, without an API key."""

import httpx

from buddy.core.errors import BuddyError
from buddy.core.tools import Tool, schema, string


def register(registry):
    async def weather(args):
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                geo = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": args["city"], "count": 1, "language": "en"},
                )
                geo.raise_for_status()
                places = geo.json().get("results", [])
                if not places:
                    raise BuddyError("City not found. Try a nearby city or country.")
                place = places[0]
                result = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": place["latitude"],
                        "longitude": place["longitude"],
                        "current": (
                            "temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
                        ),
                        "timezone": "auto",
                    },
                )
                result.raise_for_status()
                data = result.json()
                return {
                    "city": place["name"],
                    "country": place.get("country", ""),
                    "current": data["current"],
                    "units": data["current_units"],
                    "timezone": data["timezone"],
                    "source": "https://open-meteo.com/",
                }
        except BuddyError:
            raise
        except Exception:
            raise BuddyError(
                "Weather is unavailable. Check the connection and try again."
            ) from None

    registry.add(
        Tool(
            "get_weather",
            "Get current weather for a city. Attribute Open-Meteo; never invent missing weather.",
            schema({"city": string(120)}, ["city"]),
            weather,
        )
    )
