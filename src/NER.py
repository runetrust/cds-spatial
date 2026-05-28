from transformers import pipeline
from tqdm import tqdm
import json, os

results_path = os.path.join("..", "in", "politiken_results.json")
temp_outpath = os.path.join("..", "in", "politiken_NER.json")

# NER setup
ner = pipeline(
    "ner",
    model="saattrupdan/nbailab-base-ner-scandi",
    aggregation_strategy="simple",
    device=-1
)

LOCATION_LABELS = {"LOC", "GPE", "LOCATION"}
BATCH_SIZE = 32

# Load articles from preset path
with open(results_path, encoding="utf-8") as f:
    articles = json.load(f)

def build_text(article):
    parts = [
        article.get("title", ""),
        article.get("teaser", ""),
        article.get("body", "")
    ]
    return " ".join(p for p in parts if p)  # skip missing fields

texts = [build_text(a) for a in articles]

# NER
print("Step 1/3: Extracting place names...")

all_places_per_article = []

# Pass a generator so tqdm can track progress
def ner_generator(texts, batch_size):
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        yield from ner(batch)

try:
    for result in tqdm(ner_generator(texts, BATCH_SIZE), total=len(texts), desc="NER", unit="article"):
        places = list(set(
            r["word"] for r in result
            if r["entity_group"] in LOCATION_LABELS
        ))
        all_places_per_article.append(places)

except Exception as e:
    print(f"Batch NER failed ({e}), falling back to one-by-one...")
    for text in tqdm(texts, desc="NER (fallback)", unit="article"):
        try:
            result = ner(text)
            places = list(set(
                r["word"] for r in result
                if r["entity_group"] in LOCATION_LABELS
            ))
            all_places_per_article.append(places)
        except Exception as e2:
            print(f"  Warning: article failed: {e2}")
            all_places_per_article.append([])

for article, places in zip(articles, all_places_per_article):
    article["places_raw"] = places

with open(temp_outpath, "w", encoding="utf-8") as f:
    json.dump(articles,  f, ensure_ascii=False, indent=2)

print(f"NER appended results saved to {temp_outpath}")

all_places = set(p for a in articles for p in a["places_raw"])
print(f"unique places: {all_places}")
