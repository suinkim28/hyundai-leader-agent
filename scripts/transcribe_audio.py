#!/usr/bin/env python3
"""회의 녹음 파일을 텍스트로 옮긴다 (R7 회의 정리).

외부 전송 고지
--------------
이 스크립트는 **음성 파일을 OpenAI 서버로 업로드합니다.** 사내 회의 녹음을
외부로 내보내는 행위이므로, 사내 정보보호 정책상 허용되는지 먼저 확인한
뒤에만 사용하십시오. 확인 전에는 R7 을 본부장이 직접 작성한 메모나
Teams, OneNote 기록으로 진행합니다.

전문 용어 교정
--------------
자주 틀리는 고유명사는 코드가 아니라
`knowledge_base/transcription_glossary.txt` 에 한 줄에 하나씩 적습니다.
본부마다 용어가 다르므로 코드에는 두지 않습니다.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:                                          # pragma: no cover
    raise SystemExit(
        "openai 패키지가 없습니다.  pip install openai\n"
        "  회의 녹음을 외부(OpenAI)로 보내는 기능입니다. "
        "사내 정책 확인 후 사용하십시오."
    )

sys.path.insert(0, str(Path(__file__).resolve().parent))
from secret_store import OPENAI_API_KEY, get_secret  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
GLOSSARY_PATH = ROOT / "knowledge_base" / "transcription_glossary.txt"
DEFAULT_MODEL = "gpt-transcribe"
MAX_UPLOAD_BYTES = 24 * 1024 * 1024
MIN_CHUNK_SECONDS = 300
TARGET_CHUNK_RATIO = 0.8
# 용어는 코드가 아니라 knowledge_base/transcription_glossary.txt 에 둔다.
# 본부마다 다르고, 사람 이름이 코드에 박히면 다른 본부장에게 그대로 따라간다.
DEFAULT_TERMS: list[str] = []


def load_glossary_terms(path: Path) -> list[str]:
    if not path.exists():
        return []

    terms: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        terms.append(line)
    return terms


def build_default_prompt() -> str:
    merged_terms: list[str] = []
    seen: set[str] = set()
    for term in [*DEFAULT_TERMS, *load_glossary_terms(GLOSSARY_PATH)]:
        if term in seen:
            continue
        seen.add(term)
        merged_terms.append(term)

    glossary = "; ".join(merged_terms)
    return (
        "This is a meeting recording that may mix Korean and English. "
        "Preserve original wording, speaker turns if obvious, product names, acronyms, "
        "and code or English terms as spoken. "
        "Prefer these domain terms and spellings when audio is ambiguous: "
        f"{glossary}."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe a user-provided audio file such as an iPhone .m4a recording."
    )
    parser.add_argument("audio_file", help="Path to the input audio file.")
    parser.add_argument(
        "--api-key",
        help="OpenAI API key. Falls back to OPENAI_API_KEY if omitted.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Transcription model to use. Default: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--language",
        default="auto",
        help="Explicit language code. Use 'auto' to let the API infer mixed speech.",
    )
    parser.add_argument(
        "--prompt",
        default=build_default_prompt(),
        help="Optional transcription guidance prompt.",
    )
    parser.add_argument(
        "--output",
        help="Output markdown file path. Defaults to <audio>.transcript.md next to the source file.",
    )
    parser.add_argument(
        "--json-output",
        help="Optional JSON metadata output path. Defaults to <audio>.transcript.json next to the source file.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Also print the final transcript to stdout.",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print the effective default prompt and exit.",
    )
    return parser.parse_args()


def build_client(api_key: str | None) -> OpenAI:
    if api_key:
        return OpenAI(api_key=api_key)
    # env -> Keychain (hmg-agent-openai-api-key)
    return OpenAI(api_key=get_secret(*OPENAI_API_KEY))


def resolve_output_paths(audio_path: Path, output: str | None, json_output: str | None) -> tuple[Path, Path]:
    stem = audio_path.with_suffix("")
    transcript_path = Path(output) if output else stem.parent / f"{stem.name}.transcript.md"
    json_path = Path(json_output) if json_output else stem.parent / f"{stem.name}.transcript.json"
    return transcript_path, json_path


def ffprobe_duration(audio_path: Path) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    out = subprocess.check_output(command, text=True).strip()
    return float(out)


def split_audio(audio_path: Path) -> list[Path]:
    file_size = audio_path.stat().st_size
    if file_size <= MAX_UPLOAD_BYTES:
        return [audio_path]

    duration = ffprobe_duration(audio_path)
    est_seconds = max(
        MIN_CHUNK_SECONDS,
        math.floor(duration * (MAX_UPLOAD_BYTES * TARGET_CHUNK_RATIO) / file_size),
    )

    temp_dir = Path(tempfile.mkdtemp(prefix="transcribe_audio_"))
    chunk_pattern = temp_dir / "chunk_%03d.m4a"
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(audio_path),
        "-f",
        "segment",
        "-segment_time",
        str(est_seconds),
        "-c",
        "copy",
        str(chunk_pattern),
    ]
    subprocess.run(command, check=True)
    chunks = sorted(temp_dir.glob("chunk_*.m4a"))
    if not chunks:
        raise RuntimeError("ffmpeg did not produce any audio chunks.")
    return chunks


def transcribe_one(
    client: OpenAI,
    audio_path: Path,
    model: str,
    prompt: str,
    language: str,
) -> str:
    kwargs: dict[str, object] = {
        "file": audio_path.open("rb"),
        "model": model,
        "prompt": prompt,
        "response_format": "text",
    }
    if language and language != "auto":
        kwargs["language"] = language

    with kwargs["file"]:
        result = client.audio.transcriptions.create(**kwargs)

    if isinstance(result, str):
        return result.strip()
    text = getattr(result, "text", "")
    return str(text).strip()


def write_outputs(
    transcript_path: Path,
    json_path: Path,
    audio_path: Path,
    model: str,
    language: str,
    chunks: list[Path],
    transcript: str,
) -> None:
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    transcript_body = "\n".join(
        [
            f"# Transcript: {audio_path.name}",
            "",
            f"- Source: `{audio_path}`",
            f"- Model: `{model}`",
            f"- Language: `{language}`",
            f"- Chunks: `{len(chunks)}`",
            "",
            "## Transcript",
            "",
            transcript.strip(),
            "",
        ]
    )
    transcript_path.write_text(transcript_body, encoding="utf-8")

    payload = {
        "source": str(audio_path),
        "model": model,
        "language": language,
        "chunk_count": len(chunks),
        "chunks": [str(chunk) for chunk in chunks],
        "transcript": transcript.strip(),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    if args.show_prompt:
        print(build_default_prompt())
        return 0

    audio_path = Path(args.audio_file).expanduser().resolve()
    if not audio_path.exists():
        raise SystemExit(f"Audio file not found: {audio_path}")
    if not audio_path.is_file():
        raise SystemExit(f"Not a file: {audio_path}")

    client = build_client(args.api_key)
    transcript_path, json_path = resolve_output_paths(audio_path, args.output, args.json_output)
    chunks = split_audio(audio_path)

    transcripts: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        label = f"[{index}/{len(chunks)}] {chunk.name}"
        print(f"Transcribing {label}...", file=sys.stderr)
        text = transcribe_one(
            client=client,
            audio_path=chunk,
            model=args.model,
            prompt=args.prompt,
            language=args.language,
        )
        transcripts.append(text)

    combined = "\n\n".join(part for part in transcripts if part).strip()
    if not combined:
        raise SystemExit("Transcription completed but returned empty text.")

    write_outputs(
        transcript_path=transcript_path,
        json_path=json_path,
        audio_path=audio_path,
        model=args.model,
        language=args.language,
        chunks=chunks,
        transcript=combined,
    )

    print(f"Transcript written to: {transcript_path}", file=sys.stderr)
    print(f"Metadata written to: {json_path}", file=sys.stderr)
    if args.stdout:
        print(combined)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
