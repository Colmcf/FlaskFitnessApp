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
load_dotenv()

# ✅ 2. Initialize Flask
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "my-very-long-random-secret-key")

# ✅ 3. Firebase setup
cred_path = os.getenv("FIREBASE_CRED", "firebase_key.json")
if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ✅ 4. Google API setup
CLIENT_SECRETS_FILE = os.getenv("GOOGLE_CLIENT_SECRETS", "client_secret.json")
SCOPES = [os.getenv("SCOPES", "https://www.googleapis.com/auth/calendar.readonly")]
TOKEN_FILE = "token.json"

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
from google.auth.transport.requests import Request

def load_credentials_from_disk(path: str = TOKEN_FILE):
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        data = json.load(f)
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )

    # If expired but refresh token is available, refresh automatically
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials_to_disk(creds, path)
    return creds


# Below code is a mix of my own work and revision of previous Flask projects
@app.route("/")
def index():
    creds = load_credentials_from_disk()
    if creds and creds.valid:
        return (
            '<p>Authenticated. <a href="/events">List Calendar events</a></p>'
        )
    else:
        return '<p>Not authenticated. <a href="/authorize">Authenticate with Google</a></p>'


@app.route("/authorize")
def authorize():
    import os
    print("DEBUG: Using client secret file:", os.path.abspath(CLIENT_SECRETS_FILE))

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=url_for("oauth2callback", _external=True)
    )

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )

    session["state"] = state
    return redirect(authorization_url)


@app.route("/oauth2callback")
def oauth2callback():
    try:
        state = session.get("state")
        if not state:
            return "Missing state in session.", 400

        flow = Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=SCOPES,
            state=state,
            redirect_uri=url_for("oauth2callback", _external=True)
        )

        # ✅ fixed spelling: authorization_response
        flow.fetch_token(authorization_response=request.url)

        creds = flow.credentials
        save_credentials_to_disk(creds, TOKEN_FILE)
        return redirect(url_for("index"))

    except Exception as e:
        import traceback
        print("OAuth2 callback error:", traceback.format_exc())
        return f"OAuth2 callback error: {str(e)}", 500


# Below code connects to the events.html file and displays the calendar
@app.route("/events")
def events():
    creds = load_credentials_from_disk()
    if not creds:
        return redirect(url_for("authorize"))

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
        return redirect(url_for("authorize"))

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
            return redirect(url_for("authorize"))

        service = build("calendar", "v3", credentials=creds)

        now = datetime.utcnow().isoformat() + "Z"
        end_time = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"

        events_result = service.events().list(
            calendarId="primary",
            timeMin=now,
            timeMax=end_time,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = events_result.get("items", [])
        busy_times = []

        for e in events:
            start_str = e.get("start", {}).get("dateTime")
            end_str = e.get("end", {}).get("dateTime")
            if not start_str or not end_str:
                continue
            start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            busy_times.append((start, end))
        busy_times.sort(key=lambda x: x[0])

        user_goal = "Mobility"  # Or Strength, Weight Loss, etc.

        workouts_all = []
        print("DEBUG: Fetching workouts from Firebase...")
        query = db.collection("workouts").where("Goal", "==", user_goal).stream()
        for doc in query:
            w = doc.to_dict()
            print("Workout fetched:", w)
            if not w or not w.get("name") or not w.get("duration_minutes"):
                print("⚠️ Skipping invalid workout:", w)
                continue
            workouts_all.append(w)

        print(f"✅ Total valid workouts loaded: {len(workouts_all)}")

        if not workouts_all:
            return f"No workouts found for goal '{user_goal}'", 404

        suggestions = []
        used_workouts = set()
        day_pointer = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        for i in range(7):
            day_start = day_pointer + timedelta(days=i)
            day_end = day_start + timedelta(days=1)
            day_events = [(s, e) for s, e in busy_times if s < day_end and e > day_start]
            day_events.sort(key=lambda x: x[0])

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

            largest_slot = max(free_slots, key=lambda s: (s[1] - s[0]).total_seconds())
            slot_duration = (largest_slot[1] - largest_slot[0]).total_seconds() / 60

            unused_fitting = [
                w for w in workouts_all
                if w.get("duration_minutes", 0) <= slot_duration and w.get("name") and w["name"] not in used_workouts
            ]

            if unused_fitting:
                chosen = random.choice(unused_fitting)
                used_workouts.add(chosen["name"])
            else:
                fitting = [w for w in workouts_all if w.get("duration_minutes", 0) <= slot_duration and w.get("name")]
                if fitting:
                    chosen = random.choice(fitting)
                else:
                    continue

            chosen = chosen.copy()
            chosen["scheduled_for"] = largest_slot[0].isoformat()
            suggestions.append(chosen)

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


