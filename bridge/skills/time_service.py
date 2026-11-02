from .models import SkillResult

METADATA = {
    "name": "time_service",
    "version": "1.0.0",
    "category": "utility",
    "description": "Query current time across timezones. No external dependencies.",
    "risk_level": "safe",
}


def execute(timezone: str = "", **kwargs) -> SkillResult:
    import datetime

    now = datetime.datetime.now()
    utc_now = datetime.datetime.utcnow()

    zones = [
        {"name": "UTC", "time": utc_now.strftime("%H:%M:%S"), "date": utc_now.strftime("%Y-%m-%d")},
        {"name": "Local", "time": now.strftime("%H:%M:%S"), "date": now.strftime("%Y-%m-%d")},
        {"name": "CST (UTC+8)", "time": (utc_now + datetime.timedelta(hours=8)).strftime("%H:%M:%S")},
        {"name": "EST (UTC-5)", "time": (utc_now - datetime.timedelta(hours=5)).strftime("%H:%M:%S")},
        {"name": "PST (UTC-8)", "time": (utc_now - datetime.timedelta(hours=8)).strftime("%H:%M:%S")},
        {"name": "JST (UTC+9)", "time": (utc_now + datetime.timedelta(hours=9)).strftime("%H:%M:%S")},
        {"name": "CET (UTC+1)", "time": (utc_now + datetime.timedelta(hours=1)).strftime("%H:%M:%S")},
        {"name": "IST (UTC+5:30)", "time": (utc_now + datetime.timedelta(hours=5, minutes=30)).strftime("%H:%M:%S")},
    ]

    return SkillResult.ok(
        output=now.strftime("%Y-%m-%d %H:%M:%S"),
        data={
            "time": now.strftime("%H:%M:%S"),
            "date": now.strftime("%Y-%m-%d %A"),
            "timezone": "Local",
            "zones": zones,
        }
    )
