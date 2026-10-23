# Track Parking

A phone page and a background checker for parking near Basel street, Tel Aviv. Assuta lot (Jabotinsky 62) comes first, Basel lot (Ashtori HaParhi 5) second, then a street loop.

Page: https://dorelazar.github.io/track-parking/ (add it to your phone's home screen).

## What it does

- **Best option now:** Assuta if it has room, otherwise Basel, otherwise the street loop. One tap opens Waze or Google Maps.
- **How full:** the city and Ahuzot only publish three levels (room / few spaces / full), never a count. The page refines that from its own history into five: plenty of room, room but filling soon, few spaces, almost full, full. It also shows how long each lot has been in that state and when a full lot usually frees up.
- **Fill times:** learns when each lot usually fills, per day of the week, and shows a "park by" time with a 25-minute margin. Times appear after two evenings where a lot filled, and get reliable after 3–4 weeks.
- **Street loop:** Ibn Gabirol south → right on Yohanan Hyrcanus → left on Yehoshua Bin Nun → left on Jabotinsky → left on Har Nevo → right on HaGilad → left on Ein Gedi → left on Yericho past the synagogue → back to Bin Nun. "Drive the route" and "One more lap" open Google Maps with stops that keep it on these streets.
- **Red-white curbs:** loading zones within about 1 km from the city's sign records, with "open until" or "opens at" for right now. Green: the sign lets anyone park outside the loading hours. Amber: the sign lists only loading hours, so park outside them only if the curb isn't red-white. You can add your own spots on the map (saved on that phone); spots listed in `spots.json` show on every device.
- **Fallbacks:** other Ahuzot lots in walking distance with live status, school yards open to residents 19:00–07:00, and a nearby private lot with a monthly night subscription.
- **Alerts (optional):** phone notifications through the free ntfy app when Assuta gets few spaces or fills, when Basel fills too, and about 20 minutes before tonight's park-by time.

## How it runs

- `.github/workflows/watch.yml` runs `poll.py` every 5 minutes from 14:00 to 02:00 and every 15 minutes otherwise. Each run lasts about 6 hours and starts the next one. The hourly schedule only restarts it if the chain ever stops.
- `poll.py` saves both lots' status to `assuta.csv` and `basel.csv` on the `data` branch. It reads the Tel Aviv GIS feed and falls back to ahuzot.co.il.
- `geo.json` holds the route, curb signs and night lots. `.github/workflows/geo.yml` rebuilds it monthly from the city GIS and OpenStreetMap (`tools/fetch_geo.py`, `tools/build_geo.py`).

## Setup

1. **Pages:** Settings → Pages → Deploy from a branch → `main` / root.
2. **Alerts (optional):** install the ntfy app and subscribe to a hard-to-guess topic, then add it under Settings → Secrets and variables → Actions → New repository secret, named `NTFY_TOPIC`.
3. If the page footer says the checker looks paused: Actions → Watch parking lots → Run workflow.

Open the page with `?demo` at the end of the address to see it with sample data (add `&at=22:40` to try a time of day).

## Notes

- The city feed gives a status (room / few spaces / full / closed), not a count of free spaces. If a status is more than 90 minutes old the page treats it as unknown.
- The city's lot codes differ from ahuzot.co.il's: Assuta is 76 in the feed and 122 on the site; Basel is 10 and 3. Lots are matched by name.
- Curb data covers only loading-zone signs the city has on record. Always check the sign on the pole.
- Analysis numbers (evening window, margin, staleness) are at the top of `poll.py` and `index.html`; keep the two in sync.
- `python3 poll.py --data <folder> --analyze` prints the pattern from downloaded CSVs.
