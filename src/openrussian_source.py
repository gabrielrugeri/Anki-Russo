"""Fonte de dados: dump CSV do OpenRussian mantido no GitHub (Badestrand/russian-dictionary).

Baixado uma única vez para cache/ e reutilizado em execuções futuras. Cobre tônica
(forma acentuada), gênero, aspecto + par aspectual e tradução EN/DE para verbos,
substantivos, adjetivos e outras classes de palavras.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
BASE_URL = "https://raw.githubusercontent.com/Badestrand/russian-dictionary/master/{name}.csv"

_GENDER_MAP = {"m": "masc", "f": "femn", "n": "neut"}
_ASPECT_MAP = {"perfective": "perf", "imperfective": "impf"}


@dataclass
class OpenRussianEntry:
    pos: str  # "VERB" | "NOUN" | "ADJ" | "OTHER"
    bare: str
    accented: str
    translation_en: Optional[str] = None
    translation_de: Optional[str] = None
    gender: Optional[str] = None
    aspect: Optional[str] = None
    aspect_partner: Optional[str] = None
    plural_only: bool = False


def stress_mark(accented: str) -> str:
    """Converte a marcação do OpenRussian ("челове'к") em vogal tônica maiúscula ("человЕк").

    Se a palavra não tiver marcador de apóstrofo mas tiver só uma vogal, essa vogal
    é considerada a tônica (stress é inequívoco em palavras monossilábicas).
    """
    if "'" in accented:
        chars = list(accented)
        out = []
        i = 0
        while i < len(chars):
            if i + 1 < len(chars) and chars[i + 1] == "'":
                out.append(chars[i].upper())
                i += 2
            else:
                out.append(chars[i])
                i += 1
        return "".join(out)

    # "ё" é sempre tônico em russo (convenção ortográfica); usa isso quando não
    # houver marcação explícita de acento e a palavra tiver um único "ё".
    if accented.count("ё") + accented.count("Ё") == 1:
        idx = accented.lower().index("ё")
        return accented[:idx] + accented[idx].upper() + accented[idx + 1:]

    vowels = "аеёиоуыэюя"
    positions = [i for i, c in enumerate(accented.lower()) if c in vowels]
    if len(positions) == 1:
        idx = positions[0]
        return accented[:idx] + accented[idx].upper() + accented[idx + 1:]
    return accented


def _download(name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / f"openrussian_{name}.csv"
    if dest.exists():
        return dest
    url = BASE_URL.format(name=name)
    logger.info("Baixando %s ...", url)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


class OpenRussianIndex:
    def __init__(self):
        self._by_pos: dict[str, dict[str, OpenRussianEntry]] = {
            "VERB": {},
            "NOUN": {},
            "ADJ": {},
            "OTHER": {},
        }
        self.available = False

    def load(self) -> "OpenRussianIndex":
        try:
            self._load_csv("verbs", "VERB")
            self._load_csv("nouns", "NOUN")
            self._load_csv("adjectives", "ADJ")
            self._load_csv("others", "OTHER")
            self.available = True
        except Exception as exc:  # noqa: BLE001 - fonte é best-effort, nunca deve derrubar o pipeline
            logger.warning("Não foi possível carregar o dump do OpenRussian (%s). "
                            "Essa fonte será pulada nesta execução.", exc)
        return self

    def _load_csv(self, name: str, pos: str) -> None:
        path = _download(name)
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                bare = (row.get("bare") or "").strip()
                if not bare:
                    continue
                entry = OpenRussianEntry(
                    pos=pos,
                    bare=bare,
                    accented=(row.get("accented") or bare).strip(),
                    translation_en=(row.get("translations_en") or "").strip() or None,
                    translation_de=(row.get("translations_de") or "").strip() or None,
                )
                if pos == "NOUN":
                    entry.gender = _GENDER_MAP.get((row.get("gender") or "").strip())
                    entry.plural_only = (row.get("pl_only") or "").strip() == "1"
                if pos == "VERB":
                    entry.aspect = _ASPECT_MAP.get((row.get("aspect") or "").strip())
                    partner = (row.get("partner") or "").strip()
                    entry.aspect_partner = partner if partner and partner != "-" else None

                self._by_pos[pos][bare] = entry
                alt = bare.replace("ё", "е")  # texto real costuma vir sem о trema
                if alt != bare:
                    self._by_pos[pos].setdefault(alt, entry)

    def lookup(self, lemma: str, pos_hint: Optional[str] = None) -> Optional[OpenRussianEntry]:
        if not self.available:
            return None
        order = ["VERB", "NOUN", "ADJ", "OTHER"]
        if pos_hint in order:
            order.remove(pos_hint)
            order.insert(0, pos_hint)

        alt = lemma.replace("ё", "е")
        for pos in order:
            table = self._by_pos.get(pos, {})
            entry = table.get(lemma) or table.get(alt)
            if entry:
                return entry
        return None
