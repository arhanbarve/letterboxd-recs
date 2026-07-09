"""Parse a Letterboxd data export (zip or single csv) into scrape-shaped
entries. The export's Letterboxd URI is a boxd.it short link with no slug, so
entries carry slug=None and are resolved by TMDB search only — which is the
point: the upload path must be fully un-rate-limitable, zero Letterboxd hits."""
import csv
import io
import zipfile

def _entries_from_csv_text(text: str) -> list[dict]:
    entries = []
    for row in csv.DictReader(io.StringIO(text)):
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        year = (row.get("Year") or "").strip()
        rating = (row.get("Rating") or "").strip()
        entries.append({
            "slug": None,
            "title": name,
            "year": int(year) if year.isdigit() else None,
            "rating": float(rating) if rating else None,
        })
    return entries

def parse_export(data: bytes) -> list[dict]:
    """Raises ValueError for anything that isn't a usable export."""
    if zipfile.is_zipfile(io.BytesIO(data)):
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        merged = {}
        found_any = False
        # watched first so a rated row for the same film overwrites it
        for target in ("watched.csv", "ratings.csv"):
            member = next((n for n in names if n.split("/")[-1] == target), None)
            if member is None:
                continue
            found_any = True
            for e in _entries_from_csv_text(zf.read(member).decode("utf-8")):
                key = (e["title"], e["year"])
                if key not in merged or e["rating"] is not None:
                    merged[key] = e
        if not found_any:
            raise ValueError("Zip has no watched.csv or ratings.csv — is this a Letterboxd export?")
        entries = list(merged.values())
    else:
        try:
            entries = _entries_from_csv_text(data.decode("utf-8"))
        except UnicodeDecodeError:
            raise ValueError("Expected a Letterboxd export zip or a CSV file")
    if not entries:
        raise ValueError("No films found in the export")
    return entries
