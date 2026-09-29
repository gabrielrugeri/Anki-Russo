"""Análise morfológica via pymorphy3: lema, POS, gênero (substantivos), aspecto (verbos),
tipo de movimento (verbos de movimento), forma curta (adjetivos) e indeclinabilidade (substantivos).
"""
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

# Correções manuais pra casos em que o pymorphy3/OpenCorpora empata a pontuação
# entre duas leituras de palavras quase homógrafas e o parse[0] (mais provável)
# escolhido por padrão cai no lema errado pro sentido comum da palavra.
# Ex: "воскресенье" (domingo) empata com a leitura "NOUN,V-be" que aponta pro
# lema "воскресение" (ressurreição) — descoberto testando com dado real.
_LEMMA_OVERRIDES = {
    "воскресенье": "воскресенье",
}

# Pares unidirecional/multidirecional dos verbos de movimento mais comuns.
# É uma dimensão independente do aspecto (perfectivo/imperfectivo) — os dois
# verbos de cada par são imperfectivos, mas um descreve movimento numa
# direção só (unidirecional) e o outro movimento repetido/sem direção fixa
# (multidirecional).
_MOVEMENT_VERBS = {
    "идти": "unidirecional", "ходить": "multidirecional",
    "ехать": "unidirecional", "ездить": "multidirecional",
    "бежать": "unidirecional", "бегать": "multidirecional",
    "лететь": "unidirecional", "летать": "multidirecional",
    "плыть": "unidirecional", "плавать": "multidirecional",
    "нести": "unidirecional", "носить": "multidirecional",
    "вести": "unidirecional", "водить": "multidirecional",
    "везти": "unidirecional", "возить": "multidirecional",
}


@dataclass
class MorphInfo:
    input_word: str
    lemma: str
    pos_raw: Optional[str]
    pos: str  # "VERB" | "NOUN" | "ADJ" | "OTHER"
    gender: Optional[str] = None
    aspect: Optional[str] = None
    movement_type: Optional[str] = None  # "unidirecional" | "multidirecional"
    short_form: Optional[str] = None  # forma curta masculina de adjetivo (best-effort)
    indeclinable: bool = False


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

    lemma = _LEMMA_OVERRIDES.get(word.lower(), best.normal_form)

    movement_type = _MOVEMENT_VERBS.get(lemma) if pos == "VERB" else None

    short_form = None
    if pos_raw == "ADJF":
        inflected = best.inflect({"ADJS", "masc", "sing"})
        if inflected and inflected.word != best.word:
            short_form = inflected.word

    indeclinable = pos == "NOUN" and "Fixd" in tag

    return MorphInfo(
        input_word=word,
        lemma=lemma,
        pos_raw=pos_raw,
        pos=pos,
        gender=gender,
        aspect=aspect,
        movement_type=movement_type,
        short_form=short_form,
        indeclinable=indeclinable,
    )
