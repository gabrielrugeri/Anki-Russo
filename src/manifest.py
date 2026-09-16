"""Manifest de palavras já processadas (enviadas com sucesso ao Anki via AnkiConnect).

Mantido em palavras/processadas.json, indexado pelo lema resolvido — não pela
palavra digitada originalmente, pra que "купил" e "купить" numa sessão futura
sejam reconhecidas como a mesma entrada já processada. Este módulo nunca toca
nos arquivos de entrada do usuário, só no próprio manifest.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def mark_processed(manifest: dict, lemma: str, *, input_word: str, deck: str, note_id: Optional[int]) -> None:
    manifest[lemma] = {
        "input": input_word,
        "deck": deck,
        "note_id": note_id,
        "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
