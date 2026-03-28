from __future__ import annotations
"""
fetch_weather.py — Fetches current weather + today's forecast using wttr.in.

Zero API key required. Uses wttr.in public JSON API.

Usage:
    python scripts/fetch_weather.py               # uses city from sod_config.json
    python scripts/fetch_weather.py --city Mumbai
    python scripts/fetch_weather.py --dry-run
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import get_project_root, load_config, update_last_run, now_iso

WEATHER_ICONS = {
    "113": "☀️", "116": "⛅", "119": "☁️", "122": "☁️",
    "143": "🌫️", "176": "🌦️", "179": "🌨️", "182": "🌧️",
    "185": "🌧️", "200": "⛈️", "227": "🌨️", "230": "❄️",
    "248": "🌫️", "260": "🌫️", "263": "🌦️", "266": "🌧️",
    "281": "🌧️", "284": "🌧️", "293": "🌦️", "296": "🌧️",
    "299": "🌧️", "302": "🌧️", "305": "🌧️", "308": "🌧️",
    "311": "🌧️", "314": "🌧️", "317": "🌨️", "320": "🌨️",
    "323": "🌨️", "326": "🌨️", "329": "❄️", "332": "❄️",
    "335": "❄️", "338": "❄️", "350": "🌧️", "353": "🌦️",
    "356": "🌧️", "359": "🌧️", "362": "🌨️", "365": "🌨️",
    "368": "🌨️", "371": "❄️", "374": "🌨️", "377": "🌨️",
    "386": "⛈️", "389": "⛈️", "392": "⛈️", "395": "❄️",
}


def fetch_weather(city: str) -> dict | None:
    encoded = urllib.parse.quote(city)
    url = f"https://wttr.in/{encoded}?format=j1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SmartDigest/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"[weather] Error: {e}", file=sys.stderr)
        return None


def parse_weather(data: dict, city: str) -> dict:
    current = data.get("current_condition", [{}])[0]
    today = data.get("weather", [{}])[0]

    temp_c = current.get("temp_C", "?")
    feels_c = current.get("FeelsLikeC", "?")
    humidity = current.get("humidity", "?")
    desc = current.get("weatherDesc", [{}])[0].get("value", "Unknown")
    wind_kmph = current.get("windspeedKmph", "?")
    weather_code = current.get("weatherCode", "113")
    icon = WEATHER_ICONS.get(str(weather_code), "🌡️")

    max_c = today.get("maxtempC", "?")
    min_c = today.get("mintempC", "?")

    # Hourly forecast for today (3 slots: morning, afternoon, evening)
    hourly = today.get("hourly", [])
    slots = []
    for h in hourly:
        time_val = int(h.get("time", "0")) // 100
        if time_val in (9, 15, 21):
            slot_desc = h.get("weatherDesc", [{}])[0].get("value", "")
            slot_code = h.get("weatherCode", "113")
            slot_icon = WEATHER_ICONS.get(str(slot_code), "🌡️")
            slots.append({
                "time": f"{time_val:02d}:00",
                "temp_c": h.get("tempC", "?"),
                "desc": slot_desc,
                "icon": slot_icon,
                "chance_of_rain": h.get("chanceofrain", "0")
            })

    return {
        "city": city,
        "fetched_at": now_iso(),
        "current": {
            "temp_c": temp_c,
            "feels_like_c": feels_c,
            "humidity_pct": humidity,
            "description": desc,
            "icon": icon,
            "wind_kmph": wind_kmph
        },
        "today": {
            "max_c": max_c,
            "min_c": min_c,
            "hourly_forecast": slots
        }
    }


def format_for_briefing(weather: dict) -> str:
    c = weather["current"]
    t = weather["today"]
    city = weather["city"]
    icon = c["icon"]

    lines = [
        f"{icon} *Weather — {city}*",
        f"🌡 {c['temp_c']}°C (feels {c['feels_like_c']}°C) · {c['description']}",
        f"📊 Today: High {t['max_c']}°C / Low {t['min_c']}°C · 💧 Humidity {c['humidity_pct']}%",
        f"💨 Wind: {c['wind_kmph']} km/h",
    ]
    if t.get("hourly_forecast"):
        lines.append("")
        for slot in t["hourly_forecast"]:
            rain = slot.get("chance_of_rain", "0")
            lines.append(
                f"  {slot['icon']} {slot['time']} — {slot['temp_c']}°C, "
                f"{slot['desc']}" + (f" (🌧 {rain}% rain)" if int(rain) > 20 else "")
            )
    return "\n".join(lines)


def run(city: str | None = None, dry_run: bool = False) -> dict | None:
    if city is None:
        cfg = load_config("sod_config.json")
        city = cfg.get("weather", {}).get("city", "Mumbai")

    print(f"[weather] Fetching weather for: {city}")
    data = fetch_weather(city)
    if not data:
        update_last_run("fetch-weather", "failure", f"could not fetch weather for {city}")
        return None

    parsed = parse_weather(data, city)

    if dry_run:
        print(format_for_briefing(parsed))
        return parsed

    # Save to project state for SOD composer
    out_path = get_project_root() / "data" / "sod" / "weather.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(parsed, indent=2))
    print(f"[weather] ✅ Saved to {out_path}")
    update_last_run("fetch-weather", "success", f"{city}: {parsed['current']['temp_c']}°C")
    return parsed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", help="City name (default from sod_config.json)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = run(city=args.city, dry_run=args.dry_run)
    if result:
        print(f"[weather] Done: {result['current']['temp_c']}°C in {result['city']}")
