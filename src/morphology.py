"""Análise morfológica via pymorphy3: lema, POS, gênero (substantivos), aspecto (verbos)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pymorphy3

_morph = pymorphy3.MorphAnalyzer()

_POS_VERB = {"VERB", "INFN"}
_POS_NOUN = {"NOUN"}
_POS_ADJ = {"ADJF", "ADJS", "COMP"}

_GENDER_MAP = {"masc": "masc", "femn": "femn", "neut": "neut"}
_ASPECT_MAP = {"perf": "perf", "impf": "impf"}


@dataclass
class MorphInfo:
    input_word: str
    lemma: str
    pos_raw: Optional[str]
    pos: str  # "VERB" | "NOUN" | "ADJ" | "OTHER"
    gender: Optional[str] = None
    aspect: Optional[str] = None


def analyze(word: str) -> MorphInfo:
    """Analisa a palavra pelo parse mais provável do pymorphy3 (MVP: sem desambiguação por contexto)."""
    parses = _morph.parse(word)
    if not parses:
        return MorphInfo(input_word=word, lemma=word, pos_raw=None, pos="OTHER")

    best = parses[0]
    tag = best.tag
    pos_raw = tag.POS

    if pos_raw in _POS_VERB:
        pos = "VERB"
    elif pos_raw in _POS_NOUN:
        pos = "NOUN"
    elif pos_raw in _POS_ADJ:
        pos = "ADJ"
    else:
        pos = "OTHER"

    gender = _GENDER_MAP.get(tag.gender) if pos == "NOUN" else None
    aspect = _ASPECT_MAP.get(tag.aspect) if pos == "VERB" else None

    return MorphInfo(
        input_word=word,
        lemma=best.normal_form,
        pos_raw=pos_raw,
        pos=pos,
        gender=gender,
        aspect=aspect,
    )
