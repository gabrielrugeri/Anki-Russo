"""Fonte de dados: dump JSONL do Wiktionary russo via kaikki.org (wiktextract).

Baixa o dump (~900 MB) uma única vez e constrói um índice local em SQLite
(palavra -> registro relevante) para não precisar reprocessar o arquivo inteiro
em execuções futuras. Qualquer falha de rede ou de parsing é tratada como
"fonte indisponível nesta execução" — nunca derruba o pipeline.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

# Estratégia de prazo para o download (~900 MB, pode ser lento e ainda assim
# estar progredindo normalmente — não é incomum em redes restritas/lentas):
# roda numa thread daemon (assim, se travar de vez, não impede o processo de
# terminar) e faz *polling* do tamanho do arquivo parcial a cada
# _POLL_INTERVAL_SECONDS. Só desiste se não houver NENHUM progresso de
# tamanho por _STALL_SECONDS seguidos, ou se o tempo total ultrapassar
# _MAX_TOTAL_SECONDS. Isso distingue rede genuinamente indisponível (sem
# progresso algum) de rede só lenta (indexação continua até completar).
_POLL_INTERVAL_SECONDS = 5
_STALL_SECONDS = 25
_MAX_TOTAL_SECONDS = 30 * 60

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
DUMP_URL = "https://kaikki.org/dictionary/Russian/kaikki.org-dictionary-Russian.jsonl"
DUMP_PATH = CACHE_DIR / "kaikki-russian.jsonl"
INDEX_PATH = CACHE_DIR / "kaikki-russian-index.sqlite"

_POS_MAP = {"verb": "VERB", "noun": "NOUN", "adj": "ADJ"}

# Heurística best-effort para regência de caso: procura marcadores de caso russo
# (abreviações em russo ou termos em inglês) no texto das definições/tags do kaikki.
# Não há campo estruturado de regência nos dados — isso é reconhecidamente impreciso.
_CASE_PATTERNS = [
    (re.compile(r"\bgenitive\b|\bрод\.", re.I), "genitivo"),
    (re.compile(r"\bdative\b|\bдат\.", re.I), "dativo"),
    (re.compile(r"\baccusative\b|\bвин\.", re.I), "acusativo"),
    (re.compile(r"\binstrumental\b|\bтв\.", re.I), "instrumental"),
    (re.compile(r"\bprepositional\b|\blocative\b|\bпредл\.", re.I), "preposicional"),
]


@dataclass
class KaikkiEntry:
    pos: str
    translation: Optional[str] = None
    translation_lang: Optional[str] = None
    aspect_partner: Optional[str] = None
    example_ru: Optional[str] = None
    example_translation: Optional[str] = None
    case_government: Optional[str] = None


def _download_blocking(tmp: Path, result: dict) -> None:
    try:
        with requests.get(DUMP_URL, stream=True, timeout=(10, 30)) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001 - reportado pela thread principal via `result`
        result["error"] = exc


def _download() -> bool:
    if DUMP_PATH.exists():
        return True
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Baixando dump do kaikki.org (~900 MB, pode demorar bastante)...")
    tmp = DUMP_PATH.with_suffix(".part")
    try:
        tmp.unlink(missing_ok=True)  # limpa resíduo de tentativa anterior abortada
    except OSError:
        pass

    result: dict = {}
    thread = threading.Thread(target=_download_blocking, args=(tmp, result), daemon=True)
    thread.start()

    elapsed = 0
    last_size = 0
    size_stalled_for = 0
    last_logged_mb = -1
    while thread.is_alive():
        thread.join(timeout=_POLL_INTERVAL_SECONDS)
        elapsed += _POLL_INTERVAL_SECONDS
        size = tmp.stat().st_size if tmp.exists() else 0

        if size > last_size:
            size_stalled_for = 0
            mb = int(size / (1 << 20))
            if mb >= last_logged_mb + 10:  # loga a cada ~10 MB, não a cada poll
                logger.info("... %d MB baixados", mb)
                last_logged_mb = mb
        else:
            size_stalled_for += _POLL_INTERVAL_SECONDS
        last_size = size

        if size_stalled_for >= _STALL_SECONDS:
            logger.warning(
                "Download do kaikki.org travou sem progresso por %ds (rede indisponível "
                "para esse host nesta máquina/ambiente). Essa fonte será pulada nesta "
                "execução — rode de novo em uma máquina com acesso normal à internet "
                "para incluí-la.",
                _STALL_SECONDS,
            )
            _safe_unlink(tmp)
            return False

        if elapsed >= _MAX_TOTAL_SECONDS:
            logger.warning(
                "Download do kaikki.org excedeu %d min e foi abortado. Essa fonte será "
                "pulada nesta execução.",
                _MAX_TOTAL_SECONDS // 60,
            )
            _safe_unlink(tmp)
            return False

    if result.get("error"):
        logger.warning(
            "Não foi possível baixar o dump do kaikki.org (%s). "
            "Essa fonte será pulada nesta execução.",
            result["error"],
        )
        _safe_unlink(tmp)
        return False

    tmp.rename(DUMP_PATH)
    return True


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass  # arquivo pode ainda estar com handle aberto na thread abandonada; limpo na próxima execução


def _extract_case_government(text: str) -> Optional[str]:
    found = []
    for pattern, label in _CASE_PATTERNS:
        if pattern.search(text) and label not in found:
            found.append(label)
    return ", ".join(found) if found else None


def _extract_translation(entry: dict) -> tuple[Optional[str], Optional[str]]:
    for translations_key in ("translations",):
        for want in (("pt", "por"), ("en", "eng")):
            for tr in entry.get(translations_key) or []:
                code = (tr.get("code") or tr.get("lang_code") or "").lower()
                if code in want:
                    word = tr.get("word")
                    if word:
                        return word, want[0]
    # fallback: usa o primeiro gloss (definição) em inglês como "tradução"
    for sense in entry.get("senses", []):
        glosses = sense.get("glosses") or sense.get("raw_glosses")
        if glosses:
            return glosses[0], "en"
    return None, None


def _extract_example(entry: dict) -> tuple[Optional[str], Optional[str]]:
    for sense in entry.get("senses", []):
        for ex in sense.get("examples", []) or []:
            text = ex.get("text")
            translation = ex.get("english") or ex.get("translation")
            if text:
                return text, translation
    return None, None


def build_index(force: bool = False) -> bool:
    if INDEX_PATH.exists() and not force:
        return True
    if not _download():
        return False

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_index = INDEX_PATH.with_suffix(".part")
    if tmp_index.exists():
        tmp_index.unlink()

    conn = sqlite3.connect(str(tmp_index))
    conn.execute("CREATE TABLE entries (word TEXT, pos TEXT, data TEXT)")

    count = 0
    try:
        with DUMP_PATH.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                word = entry.get("word")
                pos_raw = entry.get("pos")
                if not word or pos_raw not in _POS_MAP:
                    continue
                pos = _POS_MAP[pos_raw]

                translation, translation_lang = _extract_translation(entry)
                example_ru, example_translation = _extract_example(entry)
                # Não extraímos par aspectual do kaikki: os "forms" marcados com a tag
                # perfective/imperfective descrevem o aspecto do próprio verbete, não
                # apontam para a palavra parceira (confirmado testando com verbos reais —
                # a "partner" batia com a própria palavra). O CSV do OpenRussian é a
                # fonte confiável para isso.
                aspect_partner = None

                case_gov = None
                if pos == "VERB":
                    blob = " ".join(
                        " ".join(s.get("glosses") or []) + " " + " ".join(s.get("tags") or [])
                        for s in entry.get("senses", [])
                    )
                    case_gov = _extract_case_government(blob)

                data = {
                    "translation": translation,
                    "translation_lang": translation_lang,
                    "aspect_partner": aspect_partner,
                    "example_ru": example_ru,
                    "example_translation": example_translation,
                    "case_government": case_gov,
                }
                conn.execute(
                    "INSERT INTO entries (word, pos, data) VALUES (?, ?, ?)",
                    (word, pos, json.dumps(data, ensure_ascii=False)),
                )
                count += 1
                if count % 50000 == 0:
                    conn.commit()
                    logger.info("Indexadas %d entradas do kaikki...", count)
        conn.execute("CREATE INDEX idx_word ON entries(word)")
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        conn.close()
        tmp_index.unlink(missing_ok=True)
        logger.warning("Falha ao indexar o dump do kaikki.org (%s). Essa fonte será pulada.", exc)
        return False
    finally:
        conn.close()

    tmp_index.rename(INDEX_PATH)
    logger.info("Índice do kaikki construído com %d entradas.", count)
    return True


class KaikkiIndex:
    def __init__(self):
        self._conn: Optional[sqlite3.Connection] = None
        self.available = False

    def load(self) -> "KaikkiIndex":
        if build_index():
            self._conn = sqlite3.connect(str(INDEX_PATH))
            self.available = True
        return self

    def lookup(self, lemma: str, pos_hint: Optional[str] = None) -> Optional[KaikkiEntry]:
        if not self.available:
            return None
        cur = self._conn.cursor()
        row = None
        if pos_hint:
            cur.execute("SELECT pos, data FROM entries WHERE word = ? AND pos = ? LIMIT 1", (lemma, pos_hint))
            row = cur.fetchone()
        if not row:
            cur.execute("SELECT pos, data FROM entries WHERE word = ? LIMIT 1", (lemma,))
            row = cur.fetchone()
        if not row:
            return None
        pos, data_json = row
        data = json.loads(data_json)
        return KaikkiEntry(pos=pos, **data)
