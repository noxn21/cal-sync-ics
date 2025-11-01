import os, re, uuid, requests, datetime
from icalendar import Calendar, Event
from pytz import UTC

def fetch_ics(url: str) -> Calendar:
    # iCloud webcal:// -> https://
    url = re.sub(r'^webcal://', 'https://', url.strip())
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return Calendar.from_ical(r.content)

def to_busy_blocks(events):
    now = datetime.datetime.now(UTC)
    horizon = now + datetime.timedelta(days=120)  # 4 Monate
    blocks = []
    for ev in events:
        if ev.name != "VEVENT":
            continue
        dtstart = ev.get('dtstart')
        dtend = ev.get('dtend') or ev.get('duration')
        if not dtstart:
            continue
        start = dtstart.dt
        end = (dtend.dt if hasattr(dtend, 'dt') else None) if dtend else None
        if not end:
            end = start + datetime.timedelta(hours=1)
        # All-day normalisieren
        if isinstance(start, datetime.date) and not isinstance(start, datetime.datetime):
            start = datetime.datetime.combine(start, datetime.time.min).replace(tzinfo=UTC)
        if isinstance(end, datetime.date) and not isinstance(end, datetime.datetime):
            end = datetime.datetime.combine(end, datetime.time.min).replace(tzinfo=UTC)
        # TZ -> UTC
        start = start if getattr(start, 'tzinfo', None) else start.replace(tzinfo=UTC)
        end   = end   if getattr(end, 'tzinfo', None)   else end.replace(tzinfo=UTC)
        start = start.astimezone(UTC)
        end   = end.astimezone(UTC)
        if end <= now or start >= horizon:
            continue
        blocks.append((start, end))
    return blocks

def merge_overlaps(blocks):
    if not blocks: return []
    blocks = sorted(blocks, key=lambda x: x[0])
    merged = [blocks[0]]
    for s, e in blocks[1:]:
        ls, le = merged[-1]
        if s <= le:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged

def main():
    urls = [os.environ['ICS_URL_A'], os.environ['ICS_URL_B']]
    all_blocks = []
    for u in urls:
        cal = fetch_ics(u)
        events = [c for c in cal.walk() if c.name == "VEVENT"]
        all_blocks.extend(to_busy_blocks(events))

    merged = merge_overlaps(all_blocks)

    out = Calendar()
    out.add('prodid', '-//Team Availability Merge//juno//')
    out.add('version', '2.0')
    out.add('name', 'Team Availability (Merged)')
    out.add('X-WR-CALNAME', 'Team Availability (Merged)')
    out.add('X-WR-TIMEZONE', 'UTC')

    now = datetime.datetime.now(UTC)
    os.makedirs('docs', exist_ok=True)
    for start, end in merged:
        ev = Event()
        ev.add('uid', f'{uuid.uuid4()}@team-availability')
        ev.add('dtstamp', now)
        ev.add('dtstart', start)
        ev.add('dtend', end)
        ev.add('summary', 'Busy')  # Datenschutz: keine Details
        out.add_component(ev)

    with open('docs/merged.ics', 'wb') as f:
        f.write(out.to_ical())

if __name__ == "__main__":
    main()
