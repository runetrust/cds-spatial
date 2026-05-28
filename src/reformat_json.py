import json
import pandas as pd

# load data
with open("../out/articles_geocoded.json", "r", encoding="utf-8") as f:
    data = json.load(f)
print(len(data))

#extract oalce mentions
rows = []

for article in data:

    article_date = article.get("date")

    for place in article.get("places", []):

        rows.append({
            "place": place.get("name"),
            "date": article_date,
            "lat": place.get("lat"),
            "lon": place.get("lon"),
            "country": place.get("country")
        })

#Create df

df = pd.DataFrame(rows)

# Drop na's
df = df.dropna(subset=["place", "lat", "lon", "country"])

#save
df.to_csv("../out/place_mentions.csv", index=False)

print(f"Saved {len(df)} rows to place_mentions.csv")