# Assuta Parking

A phone page and a background checker for חניון אסותא (Ahuzot HaHof, Jabotinsky 62, Tel Aviv).

- **Checker** (`poll.py`, run by GitHub Actions every ~10 minutes) saves Assuta's status from the Tel Aviv GIS feed to `assuta.csv` on the `data` branch. It falls back to ahuzot.co.il if the feed is down.
- **Page** (`index.html`, served by GitHub Pages) shows the live status, tonight's usual fill time per weekday, nearby lots with room within a 5-minute walk, and a 3-stop street loop for Google Maps.
- **Alerts** (optional) go to your phone through the free ntfy app when Assuta turns "few spaces" or "full" in the evening, and about 20 minutes before your usual "park by" time.

Predictions appear after two evenings where Assuta filled up, and get better after 3–4 weeks.

## Setup

1. **Pages:** Settings → Pages → Source: *Deploy from a branch* → `main` / root. The page lives at `https://dorelazar.github.io/track-parking/`. Add it to your home screen.
2. **Checker:** Actions tab → enable workflows if asked → *Check Assuta* → *Run workflow* once to start it.
3. **Alerts (optional):** install the ntfy app, subscribe to a hard-to-guess topic (for example `assuta-k7q2x9`), then add it under Settings → Secrets and variables → Actions → New repository secret, named `NTFY_TOPIC`.

To see the page with sample data before history exists, open it with `?demo` at the end of the address.

## Notes

- The feed gives a status (room / few / full / closed), not a count of free spaces.
- If the page says the status is old, Assuta's sensor feed may be stuck. Treat it as unknown.
- GitHub can run scheduled jobs a few minutes late. If the footer says the checker looks paused, re-enable the workflow in the Actions tab.
- Tuning numbers (evening window, lead time, walk radius) are at the top of `poll.py` and `index.html`; keep the two in sync.
- Run `python3 poll.py --data <folder> --analyze` on a downloaded `assuta.csv` to print the pattern.
