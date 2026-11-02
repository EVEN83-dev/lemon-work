"""
B-P2-008: System Service Bridge

Bridges HarmonyOS system APIs to the Bridge server.
When frontend_data is provided, adapters use it directly.
Otherwise, they return placeholder data with a _note field.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from bridge.protocol.card_protocol import (
    make_weather_card, make_calendar_card, make_file_card,
    make_contact_card, make_audio_card, make_text_card,
)

logger = logging.getLogger("lemon_bridge.system")


class WeatherAdapter:
    async def get_weather(self, city: str, frontend_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        logger.info(f"WeatherAdapter.get_weather: {city}")
        if frontend_data:
            return make_weather_card(
                location=frontend_data.get("location", city),
                temperature=frontend_data.get("temperature", 0),
                condition=frontend_data.get("condition", ""),
                wind=frontend_data.get("wind", ""),
                humidity=frontend_data.get("humidity", ""),
                feels_like=frontend_data.get("feels_like", 0),
            ).to_dict()
        return {
            "location": city,
            "temperature": 0,
            "condition": "N/A",
            "wind": "",
            "humidity": "",
            "feels_like": 0,
            "_note": "Requires HarmonyOS frontend WeatherService integration",
        }


class CalendarAdapter:
    async def get_events(self, date: str = "today", frontend_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        logger.info(f"CalendarAdapter.get_events: {date}")
        if frontend_data:
            events = frontend_data.get("events", [])
            return make_calendar_card(events=events, date=date).to_dict()
        return make_calendar_card(
            events=[{"title": "Sample Event", "start": "09:00", "end": "10:00"}],
            date=date,
        ).to_dict()


class FileAdapter:
    async def list_files(self, path: str = "/documents", frontend_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        logger.info(f"FileAdapter.list_files: {path}")
        if frontend_data:
            files = frontend_data.get("files", [])
            if files:
                f = files[0]
                return make_file_card(
                    name=f.get("name", ""),
                    size=f.get("size", ""),
                    type=f.get("type", ""),
                    path=f.get("path", ""),
                ).to_dict()
            return make_text_card("No files found").to_dict()
        return make_file_card(
            name="example.pdf", size="1.0MB", type="pdf", path=path + "/example.pdf",
        ).to_dict()


class ContactAdapter:
    async def search_contacts(self, query: str = "", frontend_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        logger.info(f"ContactAdapter.search_contacts: {query}")
        if frontend_data:
            contacts = frontend_data.get("contacts", [])
            if contacts:
                c = contacts[0]
                return make_contact_card(
                    name=c.get("name", ""),
                    phone=c.get("phone", ""),
                    email=c.get("email", ""),
                ).to_dict()
            return make_text_card("No contacts found").to_dict()
        return make_contact_card(name="Example Contact").to_dict()


class AudioAdapter:
    async def start_recording(self, frontend_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        logger.info("AudioAdapter.start_recording")
        if frontend_data:
            return make_audio_card(
                title=frontend_data.get("title", "Recording"),
                duration_sec=0,
                uri=frontend_data.get("uri", ""),
            ).to_dict()
        return {"status": "recording", "uri": "", "_note": "Requires HarmonyOS frontend AudioService"}

    async def stop_recording(self, frontend_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        logger.info("AudioAdapter.stop_recording")
        if frontend_data:
            return make_audio_card(
                title=frontend_data.get("title", "Recording"),
                duration_sec=frontend_data.get("duration_sec", 0),
                uri=frontend_data.get("uri", ""),
            ).to_dict()
        return {"status": "stopped", "uri": "", "duration": 0}


class SystemBridge:
    def __init__(self):
        self.weather = WeatherAdapter()
        self.calendar = CalendarAdapter()
        self.files = FileAdapter()
        self.contacts = ContactAdapter()
        self.audio = AudioAdapter()

    async def handle_request(self, service: str, action: str, params: Dict[str, Any]) -> Any:
        adapter_map = {
            "weather": self.weather,
            "calendar": self.calendar,
            "files": self.files,
            "contacts": self.contacts,
            "audio": self.audio,
        }
        adapter = adapter_map.get(service)
        if not adapter:
            return {"error": f"Unknown service: {service}"}

        method = getattr(adapter, action, None)
        if not method:
            return {"error": f"Unknown action: {action} for service: {service}"}

        try:
            return await method(**params)
        except Exception as e:
            logger.error(f"SystemBridge error: {e}")
            return {"error": str(e)}
