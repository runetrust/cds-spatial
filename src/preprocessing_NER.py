

import re
from collections import Counter
import os
import json

temp_inpath = os.path.join("..", "in", "politiken_NER.json")

with open(temp_inpath, encoding="utf-8") as f:
    articles = json.load(f)

def is_plausible_place(text):
    # Too short
    if len(text) < 3:
        return False
    
    # Contains digits.
    if re.search(r'\d', text):
        return False
    
    # All lowercase
    if text == text.lower():
        return False
    
    # Contains unlikely characters
    if re.search(r'[»«\(\)\[\]\{\}\/\\@#%&*+=<>]', text):
        return False
    
    # Long strings are likely NER boundary errors
    if len(text.split()) > 4:
        return False
    
    return True




# Threshold is For how many times a place should appear in coupus to be included
MIN_FREQUENCY = 2

# collect all unique places after basic preprocessing
all_places = set(p for a in articles for p in a["places_raw"])
print(f"Unique places before filtering: {len(all_places)}")

# character-based filter
all_places = {p for p in all_places if is_plausible_place(p)}
print(f"After character filter: {len(all_places)}")

# frequency filter
place_counts = Counter(p for a in articles for p in a["places_raw"])
all_places = {p for p in all_places if place_counts[p] >= MIN_FREQUENCY}
print(f"After frequency filter: {len(all_places)}")

# Apply to articles
for article in articles:
    article["places_raw"] = [p for p in article["places_raw"] 
                              if p in all_places]


with open("../in/politiken_NER_preprocessed.json", "w", encoding="utf-8") as f:
    json.dump(articles, f, ensure_ascii=False, indent=2)