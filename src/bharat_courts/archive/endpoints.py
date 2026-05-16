"""S3 bucket coordinates for the Indian judgment archives.

Both buckets are public (anonymous read) and live in ``ap-south-1``.
"""

SCI_BUCKET = "indian-supreme-court-judgments"
HC_BUCKET = "indian-high-court-judgments"
REGION = "ap-south-1"

# DuckDB read_parquet patterns. Both use Hive-style partitioning.
SCI_METADATA_GLOB = f"s3://{SCI_BUCKET}/metadata/parquet/year=*/metadata.parquet"
HC_METADATA_GLOB = f"s3://{HC_BUCKET}/metadata/parquet/year=*/court=*/bench=*/metadata.parquet"

# SCI tars are bundled per year, split into "english" (one tar) and "regional"
# (one tar containing all non-English language PDFs, with 3-letter suffix names).
# Member filename convention: ``<path>_<LANG_SUFFIX>.pdf`` — ``_EN.pdf`` inside the
# English tar; ``_HIN``, ``_TAM``, ``_GUJ`` etc. inside the regional tar.
SCI_TAR_HTTPS = (
    f"https://{SCI_BUCKET}.s3.{REGION}.amazonaws.com"
    "/data/tar/year={year}/{lang_dir}/{lang_dir}.tar"
)

# HC bucket has BOTH bundled tars AND individual PDFs. For single-PDF fetches
# the individual layout is far cheaper (~250 KB vs ~120 MB), so we use it.
# Path: data/pdf/year=Y/court=<archive_id>_<state_code>/bench=<slug>/<basename>
HC_PDF_HTTPS = (
    f"https://{HC_BUCKET}.s3.{REGION}.amazonaws.com"
    "/data/pdf/year={year}/court={court_partition}/bench={bench}/{basename}"
)

# Language map for SCI tars.
#   key   = lowercase user input (ISO-ish 2/3-letter or English name)
#   value = (tar_directory, filename_suffix_inside_tar)
SCI_LANGUAGE_MAP: dict[str, tuple[str, str]] = {
    "en": ("english", "EN"),
    "eng": ("english", "EN"),
    "english": ("english", "EN"),
    "hi": ("regional", "HIN"),
    "hin": ("regional", "HIN"),
    "hindi": ("regional", "HIN"),
    "ta": ("regional", "TAM"),
    "tam": ("regional", "TAM"),
    "tamil": ("regional", "TAM"),
    "te": ("regional", "TEL"),
    "tel": ("regional", "TEL"),
    "telugu": ("regional", "TEL"),
    "kn": ("regional", "KAN"),
    "kan": ("regional", "KAN"),
    "kannada": ("regional", "KAN"),
    "ml": ("regional", "MAL"),
    "mal": ("regional", "MAL"),
    "malayalam": ("regional", "MAL"),
    "mr": ("regional", "MAR"),
    "mar": ("regional", "MAR"),
    "marathi": ("regional", "MAR"),
    "gu": ("regional", "GUJ"),
    "guj": ("regional", "GUJ"),
    "gujarati": ("regional", "GUJ"),
    "bn": ("regional", "BEN"),
    "ben": ("regional", "BEN"),
    "bengali": ("regional", "BEN"),
    "or": ("regional", "ORI"),
    "ori": ("regional", "ORI"),
    "odia": ("regional", "ORI"),
    "pa": ("regional", "PUN"),
    "pun": ("regional", "PUN"),
    "punjabi": ("regional", "PUN"),
    "as": ("regional", "ASM"),
    "asm": ("regional", "ASM"),
    "assamese": ("regional", "ASM"),
    "ur": ("regional", "URD"),
    "urd": ("regional", "URD"),
    "urdu": ("regional", "URD"),
    "ne": ("regional", "NEP"),
    "nep": ("regional", "NEP"),
    "nepali": ("regional", "NEP"),
}
