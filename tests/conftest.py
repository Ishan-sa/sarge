import os

# Tests run against the defaults, whatever the local .env says (load_env never overrides these).
for key, value in {
    "TARGET_KCAL": "1800", "TARGET_PROTEIN": "130", "TARGET_WATER_ML": "3000", "TARGET_STEPS": "8000",
    "SARGE_PRONOUNS": "he", "SARGE_TZ": "America/Vancouver",
}.items():
    os.environ[key] = value
