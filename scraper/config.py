"""Shared constants and configuration."""

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

INCH_TO_CM = 2.54
MAX_PARALLEL = 4
OUTPUT_DIR = "./size_chart_data"

# Keywords that indicate a size chart trigger element
TRIGGER_KEYWORDS = [
    "size chart", "size guide", "sizing guide", "sizing chart",
    "measurement chart", "measurements", "view size chart",
    "view size guide", "find your size", "fit guide",
    "size & fit", "size and fit", "measure guide",
]

# Keywords for CM/inch toggles
CM_TOGGLE_KEYWORDS = ["cm", "centimeter", "centimeters", "centimetre", "centimetres"]

# Measurement column keywords (used for table scoring)
MEASUREMENT_KEYWORDS = {
    "chest", "bust", "waist", "hip", "hips", "shoulder", "shoulders",
    "across shoulder", "sleeve", "length", "inseam", "thigh", "neck",
    "arm", "torso", "back", "collar", "body length", "body width",
    "front length", "back length", "bicep", "calf", "rise",
}

# Keywords that disqualify a table (not a size chart)
NEGATIVE_KEYWORDS = {
    "shipping", "delivery", "days", "returns", "return", "price",
    "cost", "$", "€", "£", "¥", "refund", "exchange", "tracking",
    "order", "payment", "qty", "quantity", "subtotal", "total",
}

# Known size labels
SIZE_LABELS = {
    "XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL", "2XL", "3XL", "4XL",
    "1X", "2X", "3X", "4X",
    "0", "2", "4", "6", "8", "10", "12", "14", "16", "18", "20",
    "22", "24", "26", "28", "30", "32", "34", "36", "38", "40", "42",
    "44", "46", "48", "50",
    "ONE SIZE", "FREE SIZE", "F",
}
