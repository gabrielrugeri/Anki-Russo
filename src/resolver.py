"""Orquestra a cascata de resolução por palavra: pymorphy3 -> kaikki -> OpenRussian CSV.

Campos essenciais (bloqueiam o card se ausentes): tradução; e gênero para
substantivos / aspecto para verbos. Tônica, frase de exemplo e regência de
caso são "melhor esforço" — não bloqueiam o card, só ficam em branco.

Expressões multi-palavra (contêm espaço) exigem um match completo da expressão
inteira no kaikki ou no OpenRussian; se não houver, a expressão inteira vai
para a fila de revisão manual (não cai para resolver só a palavra principal).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import morphology
from .kaikki_source import KaikkiIndex
from .openrussian_source import OpenRussianIndex, stress_mark

MULTIWORD_MISSING = "expressão não encontrada"


@dataclass
class WordRecord:
    input_word: str
    lemma: str = ""
    pos: str = "OTHER"
    is_expression: bool = False

    translation: Optional[str] = None
    translation_lang: Optional[str] = None  # "pt" | "en" | "de"

    gender: Optional[str] = None
    aspect: Optional[str] = None
    aspect_partner: Optional[str] = None
    case_government: Optional[str] = None
    movement_type: Optional[str] = None  # "unidirecional" | "multidirecional" (verbos de movimento)
    short_form: Optional[str] = None  # forma curta masculina de adjetivo (best-effort)
    indeclinable: bool = False  # substantivo indeclinável (ex.: пальто, кофе)

    stress: Optional[str] = None
    example_ru: Optional[str] = None
    example_translation: Optional[str] = None

    sources: dict = field(default_factory=dict)
    missing_essential: list = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return not self.missing_essential

    @property
    def translation_is_fallback(self) -> bool:
        return bool(self.translation) and self.translation_lang != "pt"


class Resolver:
    def __init__(self, use_kaikki: bool = True):
        self.openrussian = OpenRussianIndex().load()
        self.kaikki = KaikkiIndex().load() if use_kaikki else None

    def resolve(self, raw_word: str) -> WordRecord:
        word = raw_word.strip()
        if " " in word:
            return self._resolve_expression(word)
        return self._resolve_single_word(word)

    def _resolve_single_word(self, word: str) -> WordRecord:
        morph = morphology.analyze(word)
        record = WordRecord(input_word=word, lemma=morph.lemma, pos=morph.pos)
        record.gender = morph.gender
        record.aspect = morph.aspect
        record.movement_type = morph.movement_type
        record.short_form = morph.short_form
        record.indeclinable = morph.indeclinable
        if morph.gender:
            record.sources["gender"] = "pymorphy3"
        if morph.aspect:
            record.sources["aspect"] = "pymorphy3"

        pos_hint = morph.pos if morph.pos in ("VERB", "NOUN", "ADJ") else None

        # candidatos de busca: lema do pymorphy3 primeiro, depois a palavra original
        # (cobre casos como pluralia tantum, ex. "деньги" -> lema "деньга", mas as
        # fontes externas indexam pela forma "деньги")
        lookup_candidates = [record.lemma]
        if word != record.lemma:
            plural_entry = self.openrussian.lookup(word, pos_hint)
            if plural_entry and plural_entry.plural_only:
                # plurale tantum (ex.: "родители"): a forma digitada é o lema real
                lookup_candidates.insert(0, word)
            else:
                lookup_candidates.append(word)

        # OpenRussian é checado antes do kaikki para tradução/gênero/aspecto/par:
        # é um dicionário curado com uma entrada por lema, enquanto o kaikki tem
        # várias entradas por palavra (uma por sentido/forma do Wiktionary) e o
        # lookup por lema+POS grosseiro às vezes acerta a entrada errada entre
        # homógrafos (ex.: "dorogo" como advérbio vs. forma curta de adjetivo).
        # O kaikki continua sendo a única fonte de frase de exemplo e a única
        # tentativa (best-effort) de regência de caso.
        or_entry = None
        for candidate in lookup_candidates:
            or_entry = self.openrussian.lookup(candidate, pos_hint)
            if or_entry:
                if candidate != record.lemma:
                    record.lemma = candidate  # a forma que realmente bateu na fonte é a mais confiável
                break
        if or_entry:
            record.stress = stress_mark(or_entry.accented)
            record.sources["stress"] = "openrussian_csv"
            if not record.gender and or_entry.gender:
                record.gender = or_entry.gender
                record.sources["gender"] = "openrussian_csv"
            if not record.aspect and or_entry.aspect:
                record.aspect = or_entry.aspect
                record.sources["aspect"] = "openrussian_csv"
            if or_entry.aspect_partner:
                record.aspect_partner = or_entry.aspect_partner
                record.sources["aspect_partner"] = "openrussian_csv"
            if or_entry.translation_en:
                record.translation = or_entry.translation_en
                record.translation_lang = "en"
                record.sources["translation"] = "openrussian_csv_en"
            elif or_entry.translation_de:
                record.translation = or_entry.translation_de
                record.translation_lang = "de"
                record.sources["translation"] = "openrussian_csv_de"

        if self.kaikki is not None and self.kaikki.available:
            kaikki_entry = None
            for candidate in lookup_candidates:
                kaikki_entry = self.kaikki.lookup(candidate, pos_hint)
                if kaikki_entry:
                    break
            if kaikki_entry:
                if kaikki_entry.translation and not record.translation:
                    record.translation = kaikki_entry.translation
                    record.translation_lang = kaikki_entry.translation_lang
                    record.sources["translation"] = "kaikki"
                if kaikki_entry.example_ru:
                    record.example_ru = kaikki_entry.example_ru
                    record.example_translation = kaikki_entry.example_translation
                    record.sources["example"] = "kaikki"
                if kaikki_entry.case_government:
                    record.case_government = kaikki_entry.case_government
                    record.sources["case_government"] = "kaikki"

        record.missing_essential = self._missing_essential_fields(record)
        return record

    def _resolve_expression(self, expression: str) -> WordRecord:
        record = WordRecord(input_word=expression, lemma=expression, pos="OTHER", is_expression=True)

        kaikki_entry = self.kaikki.lookup(expression) if (self.kaikki is not None and self.kaikki.available) else None
        or_entry = self.openrussian.lookup(expression)

        if not or_entry and not kaikki_entry:
            record.missing_essential = [MULTIWORD_MISSING]
            return record

        if kaikki_entry:
            record.translation = kaikki_entry.translation
            record.translation_lang = kaikki_entry.translation_lang
            record.example_ru = kaikki_entry.example_ru
            record.example_translation = kaikki_entry.example_translation
            if record.translation:
                record.sources["translation"] = "kaikki"
        if or_entry:
            record.stress = stress_mark(or_entry.accented)
            record.sources["stress"] = "openrussian_csv"
            if not record.translation and or_entry.translation_en:
                record.translation = or_entry.translation_en
                record.translation_lang = "en"
                record.sources["translation"] = "openrussian_csv_en"

        if not record.translation:
            record.missing_essential = [MULTIWORD_MISSING]
        return record

    @staticmethod
    def _missing_essential_fields(record: WordRecord) -> list:
        missing = []
        if not record.translation:
            missing.append("tradução")
        if record.pos == "NOUN" and not record.gender:
            missing.append("gênero")
        if record.pos == "VERB" and not record.aspect:
            missing.append("aspecto")
        return missing
