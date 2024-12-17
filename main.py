# Copyright 2024, Jstyles
# SPDX-License-Identifier: MIT

import os
from datetime import datetime, time, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from homeassistant_api import Client
from feedgenerator import Rss201rev2Feed
from fastapi_utils.tasks import repeat_every
import pickle


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
        self.last_state = None
        self.last_sleep_state = None

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
        if (self.last_state != state) or (self.last_sleep_state != sleep):
            update_rss_feed(self.data)
        self.last_state = state
        self.last_sleep_state = sleep
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


def update_rss_feed(data):
    status = (
        "sleeping"
        if data["sleep"]
        else "in bed"
        if data["state"]
        else "not in bed"
    )
    title = f"Jstyles is {status}"
    description = f"Jstyles is currently {status}. They've been in bed for {format_timedelta(data['lazy_time'])}."
    add_item_to_feed(title, description, "http://lazy.styl.dev")


def add_item_to_feed(title, description, link, feed_path="./static/feed.xml"):
    # Create a new RSS feed
    #
    try:
        with open("feed.obj", "rb") as f:
            feed = pickle.load(f)
    except OSError:
        feed = Rss201rev2Feed(
            title="Is Jstyles being lazy?",
            link="http://lazy.styl.dev",
            description="Is Jstyles being lazy?",
            language="en",
        )

    # Add new item
    feed.add_item(
        title=title, description=description, link=link, pubdate=datetime.now()
    )

    # Write the feed to a file
    with open(feed_path, "w") as f:
        feed.write(f, "utf-8")

    with open("feed.obj", "wb") as f:
        pickle.dump(feed, f)


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
            "in_bed": True,
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


@app.on_event("startup")
@repeat_every(seconds=240)
def update_rss() -> None:
    data = state_manager.get_data(client)
