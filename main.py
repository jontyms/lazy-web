import os
from datetime import datetime, time, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from homeassistant_api import Client


def is_night_time():
    now = datetime.now().time()
    start = time(22, 0)  # 10 PM
    end = time(9, 0)  # 9 AM

    # Special handling for time range spanning midnight
    if start <= end:
        return start <= now <= end
    else:
        return now >= start or now <= end


class StateManager:
    def __init__(self):
        self.data = None
        self.last_update = None

    def update_data(self, client):
        current_state = client.get_entity(
            entity_id="binary_sensor.jonathanbedsensor_occupancy"
        )
        lazy_time = hours_to_timedelta(
            client.get_entity(entity_id="sensor.lazy_counter").state.state
        )
        pixel_state = client.get_entity(
            entity_id="binary_sensor.pixel_6a_interactive"
        )
        if current_state.state.state == "off":
            state = False
        elif current_state.state.state == "on":
            state = True
        else:
            state = None
        if pixel_state.state.state == "off" and is_night_time() and state:
            sleep = True
        else:
            sleep = False
        self.data = {
            "state": state,
            "lazy_time": lazy_time,
            "time": datetime.now(),
            "sleep": sleep,
        }
        return self.data

    def get_data(self, client, force_update=False):
        if (
            self.data is None
            or force_update
            or (datetime.now() - self.data["time"]).seconds > 120
        ):
            return self.update_data(client)
        return self.data


def hours_to_timedelta(hours):
    # Convert hours to hours and minutes
    try:
        hours = float(hours)
        hours_whole = int(hours)  # whole number part
        minutes = (
            hours - hours_whole
        ) * 60  # fractional part converted to minutes
        return timedelta(hours=hours_whole, minutes=minutes)
    except (ValueError, TypeError):
        return timedelta(0)  # Return zero duration if conversion fails


def format_timedelta(td: timedelta) -> str:
    """Format a timedelta object into a human-readable string."""
    try:
        # Extract total hours and minutes
        total_seconds = td.total_seconds()
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)

        # Handle hours part
        hours_str = ""
        if hours == 1:
            hours_str = "1 hour"
        elif hours > 1:
            hours_str = f"{hours} hours"

        # Handle minutes part
        minutes_str = ""
        if minutes == 1:
            minutes_str = "1 minute"
        elif minutes > 0:
            minutes_str = f"{minutes} minutes"

        # Combine parts
        if hours_str and minutes_str:
            return f"{hours_str} and {minutes_str}"
        elif hours_str:
            return hours_str
        elif minutes_str:
            return minutes_str
        else:
            return "0 minutes"

    except (ValueError, TypeError, AttributeError):
        return "Invalid time format"
        return "Invalid time format"


def round_to_minute(dt):
    return dt.replace(second=0, microsecond=0) + timedelta(
        minutes=dt.second // 30
    )


app = FastAPI()

api_url = os.getenv("HOMEASSISTANT_URL")
token = os.getenv("HOMEASSISTANT_TOKEN")


client = Client(api_url, token, cache_session=False)
state_manager = StateManager()
assert token is not None


templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    data = state_manager.get_data(client)
    return templates.TemplateResponse(
        "index.html.j2",
        {
            "request": request,
            "last_updated": round_to_minute(data["time"]),
            "time_in_bed": format_timedelta(data["lazy_time"]),
            "in_bed": data["state"],
            "sleep": data["sleep"],
        },
    )


@app.get("/about", response_class=HTMLResponse)
async def read_about(request: Request):
    return templates.TemplateResponse(
        "about.html.j2",
        {
            "request": request,
        },
    )
