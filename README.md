## Google Maps Business Scraper (Places API)

This tool fetches businesses from Google Maps using the official Places API and exports them to a CSV with: name, phone, website, city, place_id, rating, user_ratings_total, and a Google Maps URL.

### Prerequisites
- A Google Cloud project with the following APIs enabled:
  - Places API
  - Place Details API (part of Places API)
  - Geocoding API (only if using `--location`)
- A billing-enabled account and an API key with the above APIs enabled.

### Setup
1. Create and restrict an API key in Google Cloud Console.
2. Export the key as an environment variable (or pass via CLI):

```bash
export GOOGLE_MAPS_API_KEY="YOUR_API_KEY"
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

### Usage
You can pass a textual location (uses Geocoding) or provide latitude/longitude.

- Using a freeform location:

```bash
python maps_scraper.py \
  --query "plumber" \
  --location "Austin, TX" \
  --max-results 100 \
  --output plumbers_austin.csv
```

- Using latitude/longitude with radius:

```bash
python maps_scraper.py \
  --query "coffee shop" \
  --lat 30.2672 --lng -97.7431 \
  --radius 10000 \
  --output coffees_austin.csv
```

### Notes
- API quotas and billing apply. Each place detail call counts toward usage.
- The script includes a small delay between details requests to respect QPS limits. Adjust with `--details-delay-ms` if needed.
- For best city extraction, we use `address_components` from Place Details. Fallback to a simple parse of `formatted_address` if components are missing.

### Output
CSV with columns:
- `name`
- `phone`
- `website`
- `city`
- `place_id`
- `rating`
- `user_ratings_total`
- `maps_url`