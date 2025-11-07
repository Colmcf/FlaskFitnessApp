# Flask and date imports used to render, create sessions and display dates from calendar
import json
from flask import Flask, request, session, jsonify, render_template, redirect, url_for
from google.oauth2.credentials import Credentials
from dateutil import parser
import dateutil.parser
import dateutil.parser
# API imports obtained from the Google calendar website
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from dotenv import load_dotenv
import pytz
import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
# Firebase imports used for connection to database
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import timedelta, timezone
import random

# Below code is to connect to my Firebase database and is from Firebase Gemini obtained from my Firebase project overview page.
cred_path = os.getenv("FIREBASE_CRED", "firebase_key.json") # Load Firebase service account key from .env
if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path) # Load credentials from JSON key file
    firebase_admin.initialize_app(cred) # Connect Flask app to Firebase

db = firestore.client() # To read/write data to Firebase

load_dotenv()  # loads variables from .env

# Below code is to access the Calendar API
CLIENT_SECRETS_FILE = os.getenv("GOOGLE_CLIENT_SECRETS", "client_secret.json") # Path to JSON file
SCOPES = [os.getenv("SCOPES", "https://www.googleapis.com/auth/calendar.readonly")] # Accesses Calendar API
TOKEN_FILE = "token.json" # Stores tokens so user doesn't have to re-authorise everytime

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "my-very-long-random-secret-key")

from datetime import datetime


@app.template_filter("datetimeformat") # Displays datetime to more readable format
def datetimeformat(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00")) # datetime objects throughout the file learned from https://docs.python.org/3/library/datetime.html#timedelta-objects
        return dt.strftime("%a, %d %b %H:%M")
    except Exception:
        return value

def save_credentials_to_disk(creds: Credentials, path: str = TOKEN_FILE): # Reuses credentials without forcing user to log in each time
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
    with open(path, "w") as f:
        json.dump(data, f)

# Below code obtained from ChatGPT when trying to receive access tokens - Prompt: I'm struggling to get access token when authenticating my google account,how can this be fixed?
def load_credentials_from_disk(path: str = TOKEN_FILE): # If user credentials are saved they get access, if not they have to log in again
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        data = json.load(f)
    return Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )
# Below code is a mix of my own work and revision of previous Flask projects
@app.route("/")
def index():
    creds = load_credentials_from_disk()
    if creds and creds.valid:
        return (
            '<p>Authenticated. <a href="/events">List Calendar events</a></p>'
        )
    else:
        return '<p>Not authenticated. <a href="/authorise">Authenticate with Google</a></p>'


@app.route("/authorise") # Redirects user to Google consent screen to authorise and grant permission to access their Google calendar
def authorise():
    # Create flow using the client secrets file and desired scopes.
    # Redirect_uri must match the Authorised redirect URI in Google Console.
    flow = Flow.from_client_secrets_file( # From JSON file, obtained from https://developers.google.com/identity/protocols/oauth2/web-server, and used for following routes.
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=url_for("oauth2callback", _external=True)
    )

    print("DEBUG Redirect URI:", flow.redirect_uri) # Obtained from ChatGPT when dealing with redirect difficulties - Prompt: I'm still getting an internal server error (I had a different redirect URI saved in my API account),
                                                    # The chatbot asked me to provide my error messages in my terminal with this code

    authorisation_url, state = flow.authorisation_url( # Obtained from https://developers.google.com/identity/protocols/oauth2/web-server
        access_type="offline", # Issues token
        include_granted_scopes="true",
        prompt="consent"  # Ensures refresh token is returned
    )

    session["state"] = state # User is redirected to authorisation screen
    return redirect(authorisation_url)


import traceback

@app.route("/oauth2callback") # Receives Google's response and stores access tokens for later API use
def oauth2callback(): # Google redirects back here after user approves/denies access
    try:
        state = session.get("state")
        if not state:
            return "Missing state in session.", 400

        flow = Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE, # Recreates the flow object using the same redirect URI
            scopes=SCOPES,
            state=state,
            redirect_uri=url_for("oauth2callback", _external=True)
        )
# Below code obtained from ChatGPT when dealing with difficulties with token generation
        flow.fetch_token(authorisation_response=request.url) # Exchange of authorise URL for token
        creds = flow.credentials
        print("DEBUG Credentials:", creds)
        save_credentials_to_disk(creds, TOKEN_FILE)
        return redirect(url_for("index"))

    except Exception as e:
        print("OAuth2 callback error:", traceback.format_exc()) # Used to catch any errors in redirect process
        return f"OAuth2 callback error: {str(e)}", 500

# Below code connects to the events.html file and displays the calendar
@app.route("/events")
def events():
    creds = load_credentials_from_disk()
    if not creds:
        return redirect(url_for("authorise"))

    service = build("calendar", "v3", credentials=creds)

    # Define the 7-day window
    now = datetime.now(timezone.utc) # defines 7-day window of calendar to display
    start_of_week = now - timedelta(days=now.weekday()) # timedelta code here and in future routes learned from https://docs.python.org/3/library/datetime.html#timedelta-objects
    end_of_week = start_of_week + timedelta(days=7)

    # Fetch the week's events from Google Calendar
    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=start_of_week.isoformat(),
            timeMax=end_of_week.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    events = events_result.get("items", [])

    # Prepare a dictionary with empty lists for each weekday
    week_events = {day: [] for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]}

    # Process each event and simplify the structure of the calendar, obtained from ChatGPT when asking where to include a link to access the workout routine page, it edited the whole block of code with the html link at the bottom
    for event in events:
        start_str = event["start"].get("dateTime", event["start"].get("date")) # Extracts events times and details
        end_str = event["end"].get("dateTime", event["end"].get("date"))
        summary = event.get("summary", "No Title")
        html_link = event.get("htmlLink", "#")

        try:
            start_dt = dateutil.parser.isoparse(start_str) # Converts the date/time strings into Python objects
            end_dt = dateutil.parser.isoparse(end_str)
        except Exception:
            continue

        # Converts to readable 24-hour times, code obtained from www.geeksforgeeks.com
        start_time = start_dt.strftime("%H:%M")
        end_time = end_dt.strftime("%H:%M")

        # Stores structured event data, instead of a single string
        weekday = start_dt.strftime("%A")
        if weekday in week_events:
            week_events[weekday].append({
                "summary": summary,
                "start_time": start_time,
                "end_time": end_time,
                "htmlLink": html_link
            })

    # Renders the template and passes data to events.html
    return render_template(
        "events.html",
        week_events=week_events,
        weekdays=list(week_events.keys()),
        start_of_week=start_of_week,
        end_of_week=end_of_week,
    )

# Below code is mix of my own work, revision from past Flask projects and previous referenced code used in previous routes for connection throughout.
@app.route("/free_slots")
def free_slots():
    creds = load_credentials_from_disk()
    if not creds:
        return redirect(url_for("authorise"))

    if creds.expired and creds.refresh_token: # Refresh tokens is required
        creds.refresh(Request())

    service = build("calendar", "v3", credentials=creds)

    now = datetime.utcnow()
    time_min = now.isoformat() + "Z"
    time_max = (now + timedelta(days=7)).isoformat() + "Z" # timedelta code learned from https://docs.python.org/3/library/datetime.html#timedelta-objects

    events_result = ( # Fetches calendar events for next 7 days
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = events_result.get("items", [])

    utc = pytz.UTC # Timezone, obtained from https://pynative.com/python-timezone/

    # Build a dictionary of busy periods by day
    busy_by_day = {}
    for event in events:
        start_raw = event.get("start", {}).get("dateTime", event.get("start", {}).get("date"))
        end_raw = event.get("end", {}).get("dateTime", event.get("end", {}).get("date"))

        if "T" not in start_raw or "T" not in end_raw:
            # Skip all-day events
            continue

        start_dt = parser.isoparse(start_raw)
        end_dt = parser.isoparse(end_raw)

        # Ensure timezone-aware, force UTC if missing
        if start_dt.tzinfo is None:
            start_dt = utc.localize(start_dt)
        if end_dt.tzinfo is None:
            end_dt = utc.localize(end_dt)

        day_key = start_dt.date().isoformat() # Uses date string, e.g. 2025-11-06
        busy_by_day.setdefault(day_key, []).append((start_dt, end_dt))

    # Analyze free slots between 6:00–22:00 each day
    free_slots = {}


    for i in range(7): # Finds free slots between 6am and 10pm, block of code obtained from Microsoft Copilot - Prompt: How can the free times in my calendar be detected to display when the workout routines should take place each day
        day = (now + timedelta(days=i)).date()
        start_of_day = utc.localize(datetime.combine(day, datetime.min.time()) + timedelta(hours=6))
        end_of_day = utc.localize(datetime.combine(day, datetime.min.time()) + timedelta(hours=22))

        busy_periods = sorted(busy_by_day.get(day.isoformat(), []), key=lambda x: x[0]) # Sorts busy periods during the day
        free_periods = []
        last_end = start_of_day

        for start, end in busy_periods: # Finds the gaps between busy periods
            if start > last_end:
                free_periods.append((last_end, start))
            last_end = max(last_end, end)

        if last_end < end_of_day:
            free_periods.append((last_end, end_of_day))

        free_slots[day.isoformat()] = free_periods

    # Return free slots as JSON
    readable_slots = {
        day: [
            f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}" for start, end in slots
        ]
        for day, slots in free_slots.items()
    }

    return jsonify(readable_slots)

# Below code was to initially test and confirm connection between Flask and Firebase
@app.route("/test_firebase")
def test_firebase():
    doc_ref = db.collection("test_data").document("sample")
    doc_ref.set({"hello": "world", "time": datetime.utcnow().isoformat()})
    return "Firebase connection successful"


@app.route("/suggest_routines")
def suggest_routines():
    try:
        creds = load_credentials_from_disk()
        if not creds:
            return redirect(url_for("authorise"))

        service = build("calendar", "v3", credentials=creds)

        now = datetime.utcnow().isoformat() + "Z" # Gets events from now to 7 days ahead
        end_time = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"

        # Get next 7 days of events
        events_result = service.events().list(
            calendarId="primary",
            timeMin=now,
            timeMax=end_time,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = events_result.get("items", [])

        # Convert events to datetime ranges
        busy_times = []
        for e in events:
            start_str = e["start"].get("dateTime")
            end_str = e["end"].get("dateTime")

            if not start_str or not end_str:
                continue  # skip all-day events

            start = datetime.fromisoformat(start_str.replace("Z", "+00:00")) # Append datetime objects to busy list
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            busy_times.append((start, end))

        busy_times.sort(key=lambda x: x[0]) # Sort by start time

        # Load workouts from Firebase
        workouts_all = [w.to_dict() for w in db.collection("workouts").stream()]
        unique_workouts = workouts_all.copy()

        suggestions = []
        used_workouts = set()

        day_pointer = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) # Starts workouts from today, obtained from ChatGPT - Prompt: instead of the workouts showing from every monday, how can they show from today and including next 7 days

        for i in range(7): # Loop for each 7-day period
            day_start = day_pointer + timedelta(days=i)
            day_end = day_start + timedelta(days=1)

            # Find all events that day
            day_events = [(s, e) for s, e in busy_times if s < day_end and e > day_start] # Obtained from ChatGPT from a following question from above - Prompt: how can the free times be located for display
            day_events.sort(key=lambda x: x[0])

            # Find free slots for this day
            free_slots = []
            last_end = day_start
            for start, end in day_events:
                if start - last_end > timedelta(minutes=30):
                    free_slots.append((last_end, start))
                last_end = max(last_end, end)
            if day_end - last_end > timedelta(minutes=30):
                free_slots.append((last_end, day_end))

            if not free_slots:
                continue

            # Pick the largest free slot
            largest_slot = max(free_slots, key=lambda s: (s[1] - s[0]).total_seconds())
            slot_duration = (largest_slot[1] - largest_slot[0]).total_seconds() / 60

 # Below block of code obtained from ChatGPT when dealing with difficulties of the same workout being displayed for each day - Prompt: the same workout is being displayed for each day, how can this be fixed to show a variety of workouts
            # First try to pick an unused workout that fits
            unused_fitting = [
                w for w in unique_workouts
                if w["duration_minutes"] <= slot_duration and w["name"] not in used_workouts
            ]

            if unused_fitting:
                chosen = random.choice(unused_fitting)
                used_workouts.add(chosen["name"])
            else:
                # If all workout types used, pick any that fits
                fitting = [w for w in workouts_all if w["duration_minutes"] <= slot_duration]
                if fitting:
                    chosen = random.choice(fitting)
                else:
                    continue  # no workouts short enough for this slot

            # Save choice and schedule workout
            chosen = chosen.copy()
            chosen["scheduled_for"] = largest_slot[0].isoformat()
            suggestions.append(chosen)


        # Save to Firebase
        user_id = "demo_user"
        for s in suggestions:
            db.collection("users").document(user_id).collection("routines").add(s)

        return render_template("routines.html", routines=suggestions)

    except Exception as e:
        import traceback
        print("Error generating routines:", traceback.format_exc())
        return f"Error: {str(e)}", 500

if __name__ == "__main__":
    app.run("localhost", 5000, debug=True)
    app.debug = True


