import os, re, requests, datetime
from icalendar import Calendar, Event
from typing import List, Tuple

# --- Konfiguration: Quellen + Label ---
SOURCES: List[Tuple[str, str]] = [
    ("ICS_URL_A", "Julian busy"),
    ("ICS_URL_B", "Noah busy"),
    ("ICS_URL_C", "Julian Uni"),
]

HORIZON_DAYS = 120  # wie weit in die Zukunft exportiert wird

def fetch_ics(url: str) -> Calendar:
    url = re.sub(r'^webcal://', 'https://', url.strip())
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return Calendar.from_ical(r.content)

def is_all_day(component) -> bool:
    """
    All-day wenn:
    - DTSTART hat VALUE=DATE-Parameter ODER
    - dtstart.dt ist ein datetime.date (ohne Uhrzeit)
    """
    dtstart = component.get('dtstart')
    if not dtstart:
        return False
    # VALUE=DATE gesetzt?
    try:
        val = dtstart.params.get('VALUE')
        if val and str(val).upper() == 'DATE':
            return True
    except Exception:
        pass
    # Python-Typ checken
    return isinstance(dtstart.dt, datetime.date) and not isinstance(dtstart.dt, datetime.datetime)

def norm_all_day_bounds(component) -> Tuple[datetime.date, datetime.date]:
    """
    Liefert (start_date, end_date_exclusive) für ganztägige Events.
    Falls DTEND fehlt, setzen wir end = start + 1 Tag (iCal-Standard).
    """
    ds = component.get('dtstart').dt  # date-Objekt oder datetime->date
    if isinstance(ds, datetime.datetime):
        ds = ds.date()
    dtend = component.get('dtend')
    if dtend:
        de = dtend.dt
        if isinstance(de, datetime.datetime):
            de = de.date()
    else:
        de = ds + datetime.timedelta(days=1)
    return ds, de

def norm_timed_bounds(component) -> Tuple[datetime.datetime, datetime.datetime]:
    """
    Start/Ende für terminierte (nicht ganztägige) Events. Wir übernehmen Timezones wie geliefert,
    ohne auf UTC zu zwängen (vermeidet 01:00-Verschiebungen).
    Falls DTEND fehlt: +1h.
    """
    start = component.get('dtstart').dt
    dtend = component.get('dtend')
    if dtend:
        end = dtend.dt
    else:
        # Fallback 1h
        if isinstance(start, datetime.datetime):
            end = start + datetime.timedelta(hours=1)
        else:
            end = (datetime.datetime.combine(start, datetime.time.min) +
                   datetime.timedelta(hours=1))
    return start, end

def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    horizon = now + datetime.timedelta(days=HORIZON_DAYS)

    out = Calendar()
    out.add('prodid', '-//Team Availability Merge (labeled)//noah//')
    out.add('version', '2.0')
    out.add('name', 'Team Availability (Labeled)')
    out.add('X-WR-CALNAME', 'Team Availability (Labeled)')

    # Für jede Quelle Events holen und 1:1 (mit neuem Summary) in den Output schreiben
    for env_key, label in SOURCES:
        url = os.environ.get(env_key)
        if not url:
            continue
        cal = fetch_ics(url)

        for comp in cal.walk():
            if comp.name != "VEVENT":
                continue

            try:
                if is_all_day(comp):
                    start_date, end_date = norm_all_day_bounds(comp)

                    # Filter Fenster (als Datum betrachten)
                    if end_date <= now.date() or start_date >= (now + datetime.timedelta(days=HORIZON_DAYS)).date():
                        continue

                    ev = Event()
                    # All-day korrekt: VALUE=DATE + exklusives DTEND
                    ev.add('dtstart', start_date, parameters={'VALUE': 'DATE'})
                    ev.add('dtend', end_date, parameters={'VALUE': 'DATE'})
                    ev.add('summary', label)

                else:
                    start_dt, end_dt = norm_timed_bounds(comp)

                    # Filter Fenster (mit Zeitzone, ggf. naive → lokal annehmen)
                    # Für robusten Vergleich in UTC normalisieren, falls tz-naiv:
                    def to_utc(dt: datetime.datetime) -> datetime.datetime:
                        if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
                            dt = datetime.datetime.combine(dt, datetime.time.min)
                        if dt.tzinfo is None:
                            # naive → lokale Annahme + in UTC
                            return dt.replace(tzinfo=datetime.timezone.utc)
                        return dt.astimezone(datetime.timezone.utc)

                    if to_utc(end_dt) <= now or to_utc(start_dt) >= horizon:
                        continue

                    ev = Event()
                    # Zeiten unverändert übernehmen (keine Zwangs-UTC, vermeidet 01:00-Sprünge)
                    ev.add('dtstart', start_dt)
                    ev.add('dtend', end_dt)
                    ev.add('summary', label)

                out.add_component(ev)

            except Exception:
                # Schluckt kaputte Einzel-Events, damit der Gesamtlauf nicht scheitert
                continue

    # Ausgeben
    os.makedirs('docs', exist_ok=True)
    with open('docs/merged.ics', 'wb') as f:
        f.write(out.to_ical())

if __name__ == "__main__":
    main()
