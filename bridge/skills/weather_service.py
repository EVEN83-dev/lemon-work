from .models import SkillResult

METADATA = {
    "name": "weather_service",
    "version": "1.0.0",
    "category": "network",
    "description": "Query weather for a location. Uses wttr.in API with fallback.",
    "risk_level": "safe",
    "dependencies": [],
}


def execute(location: str = "Beijing", **kwargs) -> SkillResult:
    if not location or not location.strip():
        location = "Beijing"

    try:
        import urllib.request
        import json as _json

        url = f"https://wttr.in/{location}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read().decode("utf-8"))

        current = data.get("current_condition", [{}])[0]
        temp_c = current.get("temp_C", "N/A")
        feels_like = current.get("FeelsLikeC", "N/A")
        humidity = current.get("humidity", "N/A")
        wind_speed = current.get("windspeedKmph", "N/A")
        desc = current.get("weatherDesc", [{}])
        condition = desc[0].get("value", "Unknown") if desc else "Unknown"

        forecast = []
        for day in data.get("weather", [])[:3]:
            forecast.append({
                "day": day.get("date", ""),
                "condition": day.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value", "") if day.get("hourly") else "",
                "temp": f"{day.get('mintempC', '')}-{day.get('maxtempC', '')}°C",
            })

        return SkillResult.ok(
            output=f"{location}: {temp_c}°C, {condition}",
            data={
                "location": location,
                "temperature": temp_c,
                "unit": "°C",
                "condition": condition,
                "details": {
                    "feelsLike": f"{feels_like}°C",
                    "humidity": f"{humidity}%",
                    "wind": f"{wind_speed}km/h",
                },
                "forecast": forecast,
            }
        )
    except ImportError:
        return SkillResult.fail("urllib not available", data={"location": location, "fallback": "weather service requires network access"})
    except Exception as e:
        return SkillResult.fail(
            f"Weather query failed: {e}",
            data={"location": location, "error": str(e), "fallback": "Weather service unavailable. Check network connection."}
        )
