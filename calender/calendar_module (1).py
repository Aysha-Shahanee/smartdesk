import os
import datetime
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import json

# Scope defines what permission we request
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']


# STEP 1: Authenticate User and Get Tokens
def authenticate():
    creds = None

    # If token.json exists, load saved credentials
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    # If no valid credentials, login flow starts
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        # Save credentials for next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return creds


# STEP 2: Fetch Events Between Dates
def fetch_events(creds, start_time, end_time):
    service = build('calendar', 'v3', credentials=creds)

    events_result = service.events().list(
        calendarId='primary',
        timeMin=start_time,
        timeMax=end_time,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    return events_result.get('items', [])


# STEP 3: Normalize Data
def normalize_events(events):
    normalized = []

    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        end = event['end'].get('dateTime', event['end'].get('date'))

        normalized.append({
            "event_id": event.get("id"),
            "title": event.get("summary", "No Title"),
            "start_time": start,
            "end_time": end,
            "attendees_count": len(event.get("attendees", [])),
            "is_recurring": "recurringEventId" in event
        })

    return normalized


# STEP 4: Main Function
def get_calendar_data():
    creds = authenticate()

    now = datetime.datetime.utcnow().isoformat() + 'Z'
    next_24_hours = (datetime.datetime.utcnow() +
                     datetime.timedelta(hours=24)).isoformat() + 'Z'

    events = fetch_events(creds, now, next_24_hours)
    clean_data = normalize_events(events)

    return clean_data


if __name__ == "__main__":
    data = get_calendar_data()
    print(json.dumps(data, indent=4))
