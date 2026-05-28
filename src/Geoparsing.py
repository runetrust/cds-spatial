import os
import json
from tqdm import tqdm
from opencage.geocoder import OpenCageGeocode

CACHE_FILE = "../out/geocache.json"
temp_inpath = os.path.join("..", "in", "politiken_NER_preprocessed.json")

# Load articles with NER
with open(temp_inpath) as f:
    articles = json.load(f)

if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE) as f:
        geocache = json.load(f)
else:
    geocache = {}


# Geocoding
all_places = set(p for a in articles for p in a["places_raw"])
new_places = [p for p in all_places if p not in geocache]

#To ensure we only compute for one API token at a time. If more unique places, wait for reset of rate limit

#new_places = new_places[:2499]

print(f"\nStep 2/3: Geocoding {len(new_places)} new places ({len(all_places) - len(new_places)} already cached)...")

print("Remember to pass yout OpenCage API key in line 31")
geocoder = OpenCageGeocode("")
not_geocoded = []
def lookup(place):
    try:
        results = geocoder.geocode(place, language="da", countrycode="", no_annotations=1)
        if results:
            best = results[0]
            return {
                "lat": best["geometry"]["lat"],
                "lon": best["geometry"]["lng"],
                "country": best["components"].get("country", None),
                "confidence": best["confidence"]
            }
        return None
    except Exception as e:
        print(f"\nWarning: failed to geocode '{place}': {e}")
        not_geocoded.append(place)
        return None

for place in tqdm(new_places, desc="Geocoding", unit="place"):
    geocache[place] = lookup(place)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(geocache, f, ensure_ascii=False)

# Annotate articles 
print("\nStep 3/3: Annotating articles...")

skipped = 0
for article in tqdm(articles, desc="Annotating", unit="article"):
    article["places"] = [
        {"name": p, **geocache[p]}
        for p in article["places_raw"]
        if geocache.get(p) is not None
    ]
    del article["places_raw"]
    if not article["places"]:
        skipped += 1

# Save
with open("../out/articles_geocoded.json", "w", encoding="utf-8") as f:
    json.dump(articles, f, ensure_ascii=False, indent=2)

print(f"\nDone! {len(articles)} articles saved to articles_geocoded.json")
print(f"{len(articles) - skipped} articles had at least one geocoded place")
print(f"{skipped} articles had no resolved places")
print(f"Geocache now contains {len(geocache)} unique places")
