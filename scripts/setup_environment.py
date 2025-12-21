#!/usr/bin/env python3
"""One-time environment setup for the council meeting analyzer."""

import subprocess
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from council_analyzer.config import config, ensure_directories
from council_analyzer.database import init_database


def check_ffmpeg():
    """Verify ffmpeg is installed."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            version_line = result.stdout.split("\n")[0]
            print(f"✓ ffmpeg: {version_line}")
            return True
    except FileNotFoundError:
        pass
    print("✗ ffmpeg not found - install with: brew install ffmpeg")
    return False


def check_ollama():
    """Verify ollama is running and has required models."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("✓ ollama is running")
            models = result.stdout

            required_models = [
                config.OLLAMA_MODEL_ANALYSIS,
                config.OLLAMA_MODEL_VALIDATION_FAST,
                config.OLLAMA_MODEL_VALIDATION_DEEP,
            ]

            for model in required_models:
                model_name = model.split(":")[0]
                if model_name in models:
                    print(f"  ✓ {model}")
                else:
                    print(f"  ✗ {model} - install with: ollama pull {model}")
            return True
    except FileNotFoundError:
        pass
    print("✗ ollama not found or not running")
    return False


def main():
    print("=" * 50)
    print("Council Meeting Analyzer - Environment Setup")
    print("=" * 50)
    print()

    # Create directories
    print("Creating directories...")
    ensure_directories()
    print(f"  ✓ Data directory: {config.DATA_DIR}")
    print(f"  ✓ Audio directory: {config.AUDIO_DIR}")
    print(f"  ✓ Transcript directory: {config.TRANSCRIPT_DIR}")
    print(f"  ✓ Analysis directory: {config.ANALYSIS_DIR}")
    print()

    # Initialize database
    print("Initializing database...")
    init_database()
    print(f"  ✓ Database: {config.DB_PATH}")
    print()

    # Check dependencies
    print("Checking dependencies...")
    check_ffmpeg()
    check_ollama()
    print()

    # Summary
    print("=" * 50)
    print("Setup complete!")
    print()
    print("Next steps:")
    print("  1. Run discovery: uv run python scripts/run_discovery.py")
    print("  2. Download audio: uv run python scripts/run_download.py")
    print("  3. Transcribe: uv run python scripts/run_transcribe.py")
    print("  4. Or run full pipeline: uv run python scripts/run_pipeline.py")


if __name__ == "__main__":
    main()
