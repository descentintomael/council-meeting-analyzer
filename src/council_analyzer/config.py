"""Configuration and constants for the council meeting analyzer."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    """Central configuration for the pipeline."""

    # Paths
    PROJECT_ROOT: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent)
    DATA_DIR: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent / "data")
    AUDIO_DIR: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent / "data" / "audio")
    TRANSCRIPT_DIR: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent / "data" / "transcripts")
    ANALYSIS_DIR: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent / "data" / "analysis")
    DB_PATH: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent / "data" / "meetings.db")

    # Granicus
    GRANICUS_BASE_URL: str = "https://chico-ca.granicus.com"
    CLIP_URL_TEMPLATE: str = "https://chico-ca.granicus.com/player/clip/{clip_id}"

    # Discovery range (Jan 2021 to present)
    # Based on exploration: clip IDs are sequential integers
    CLIP_ID_START: int = 900  # Conservative start to catch all 2021 meetings
    CLIP_ID_END: int = 1300  # Buffer above current known clips (1199 as of Dec 2024)

    # Whisper models for dual transcription
    WHISPER_MODEL_PRIMARY: str = "mlx-community/whisper-large-v3-mlx"
    WHISPER_MODEL_SECONDARY: str = "mlx-community/whisper-medium-mlx"

    # Ollama models
    OLLAMA_MODEL_ANALYSIS: str = "qwen2.5vl:72b"  # Main analysis model
    OLLAMA_MODEL_VALIDATION_FAST: str = "mistral:7b-instruct"  # Tier 1 validation
    OLLAMA_MODEL_VALIDATION_DEEP: str = "deepseek-r1:70b"  # Tier 2 validation
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # Validation thresholds
    VALIDATION_COHERENCE_THRESHOLD: int = 80  # Below this triggers Tier 2
    VALIDATION_WER_THRESHOLD: float = 0.15  # 15% WER divergence triggers Tier 2

    # Timeouts (milliseconds for subprocess, seconds for network)
    DOWNLOAD_TIMEOUT_SEC: int = 3600  # 1 hour max per download
    TRANSCRIBE_TIMEOUT_SEC: int = 7200  # 2 hours max per transcription
    ANALYSIS_TIMEOUT_SEC: int = 1800  # 30 min max per analysis
    HTTP_TIMEOUT_SEC: int = 30  # HTTP request timeout

    # Hugging Face token for pyannote (optional - can use public models)
    HUGGINGFACE_TOKEN: str | None = None  # Set via HF_TOKEN env var if needed

    # Meeting types to process
    MEETING_TYPES: list = field(default_factory=lambda: [
        "City Council",
        "Planning Commission",
        "Special Meeting",
    ])

    # Known entities for validation
    COUNCIL_MEMBERS: list = field(default_factory=lambda: [
        "Coolidge", "Reynolds", "Brown", "Huber", "Morgan", "Stone", "Tandon",
        "van Overbeek", "Van Overbeek",
    ])

    CHICO_TERMS: list = field(default_factory=lambda: [
        "Bidwell", "Esplanade", "Valley's Edge", "CARD", "CUSD", "Enloe",
        "Chico", "Butte County", "Paradise", "Oroville", "Big Chico Creek",
    ])

    # Priority keywords for Smart Growth Advocates
    PRIORITY_KEYWORDS: list = field(default_factory=lambda: [
        "Valley's Edge",
        "parking minimum",
        "missing middle",
        "infill",
        "groundwater",
        "infrastructure deficit",
        "form-based code",
        "ADU",
        "accessory dwelling",
        "zoning",
        "housing",
    ])


# Global config instance
config = Config()


def ensure_directories():
    """Create all required data directories."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    config.TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    config.ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
