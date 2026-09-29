"""Monta o conteúdo dos cards (HTML dos campos Frente/Verso) a partir dos
WordRecord resolvidos, e opcionalmente empacota um .apkg (genanki) com eles.

Fluxo principal do projeto usa `note_fields()` direto com o AnkiConnect
(src/anki_connect.py); a geração de .apkg aqui é só pro comando manual
`--export-apkg`.

Lado 1 (Frente): palavra com tônica marcada por acento agudo (´) + frase de exemplo (sem tradução),
com a palavra-alvo em negrito dentro da frase quando um match exato é encontrado.
Lado 2 (Verso): aspecto+par (verbo) ou gênero (substantivo) em negrito colorido;
tipo de movimento (verbos de movimento, dimensão à parte do aspecto) em cor própria;
tradução da palavra; forma curta de adjetivo e aviso de substantivo indeclinável
quando aplicável (best-effort, linhas opcionais); e tradução da frase de exemplo.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import genanki

from .resolver import WordRecord

MODEL_ID = 1607392319
DECK_ID_DEFAULT = 1972948123

_ASPECT_LABEL = {"perf": "perfectivo", "impf": "imperfectivo"}
_ASPECT_COLOR = {"perf": "#2e7d32", "impf": "#1565c0"}  # perfectivo=verde, imperfectivo=azul
_GENDER_LETTER = {"masc": "М", "femn": "Ж", "neut": "С"}
_GENDER_COLOR = {"masc": "#1565c0", "femn": "#c62828", "neut": "#6a1b9a"}  # azul/vermelho/roxo
_MOVEMENT_COLOR = "#e65100"  # laranja escuro — dimensão à parte de aspecto/gênero, cor própria

_COMBINING_ACCENTS = "́̀"  # combining acute/grave: marca de tônica usada nos exemplos do kaikki

MODEL = genanki.Model(
    MODEL_ID,
    "Russo - Produção Ativa",
    fields=[{"name": "Frente"}, {"name": "Verso"}],
    templates=[
        {
            "name": "Card 1",
            "qfmt": "{{Frente}}",
            "afmt": '{{FrontSide}}<hr id="answer">{{Verso}}',
        }
    ],
    css=".card { font-family: arial; font-size: 22px; text-align: center; color: black; background-color: white; }",
)


def _stress_html(stress: str) -> str:
    """Converte a marca de tônica em maiúscula (ex: 'купИть') para a vogal em
    minúscula seguida do acento agudo combinante (ex: 'купи́ть')."""
    match = re.search(r"[А-ЯЁ]", stress)
    if not match:
        return stress
    idx = match.start()
    return stress[:idx] + stress[idx].lower() + "́" + stress[idx + 1:]


def _strip_accents(text: str) -> str:
    return "".join(ch for ch in text if ch not in _COMBINING_ACCENTS)


def _bold_word_in_example(example: str, lemma: str) -> str:
    """Envolve a palavra-chave em <b> dentro da frase de exemplo, tolerando as
    marcas de acento (combining accent) que o kaikki usa nos exemplos e que a
    palavra-chave não tem. Se não achar um match exato (ex: frase usa uma forma
    flexionada bem diferente do lema), devolve a frase sem nenhuma palavra em
    negrito — nunca aplica negrito na palavra errada.
    """
    if not lemma:
        return example

    # mapeia cada posição do texto "limpo" (sem marca de acento) pra posição
    # correspondente no texto original, pra poder recortar o span certo depois
    clean_chars = []
    index_map = []
    for i, ch in enumerate(example):
        if ch in _COMBINING_ACCENTS:
            continue
        clean_chars.append(ch)
        index_map.append(i)
    clean = "".join(clean_chars)

    clean_lower = clean.replace("ё", "е").replace("Ё", "Е").lower()
    lemma_lower = _strip_accents(lemma).replace("ё", "е").replace("Ё", "Е").lower()

    pos = clean_lower.find(lemma_lower)
    if pos == -1 or not lemma_lower:
        return example

    start = index_map[pos]
    end_clean = pos + len(lemma_lower) - 1
    end = index_map[end_clean] + 1
    while end < len(example) and example[end] in _COMBINING_ACCENTS:
        end += 1

    return example[:start] + f"<b>{example[start:end]}</b>" + example[end:]


def _grammar_line(record: WordRecord) -> str:
    if record.pos == "VERB" and record.aspect:
        label = _ASPECT_LABEL.get(record.aspect, record.aspect)
        color = _ASPECT_COLOR.get(record.aspect, "#000000")
        line = f'<b style="color:{color}">{label}</b>'
        if record.aspect_partner:
            line += f" (par: {record.aspect_partner})"
        return line
    if record.pos == "NOUN" and record.gender:
        letter = _GENDER_LETTER.get(record.gender)
        color = _GENDER_COLOR.get(record.gender)
        if letter:
            return f'<b style="color:{color}">{letter}</b>'
    return ""


def _translation_line(record: WordRecord) -> str:
    if not record.translation:
        return ""
    if record.translation_is_fallback:
        tag = (record.translation_lang or "?").upper()
        return f"[{tag}] {record.translation}"
    return record.translation


def note_fields(record: WordRecord) -> tuple[str, str]:
    """Monta o HTML dos campos Frente/Verso a partir de um WordRecord resolvido.

    Reutilizado tanto pelo Note do genanki (export pontual em .apkg) quanto
    pelo upload direto via AnkiConnect, pra não duplicar a lógica de
    formatação (tônica com acento, negrito na frase, cores) em dois lugares.
    """
    word_html = _stress_html(record.stress) if record.stress else (record.lemma or record.input_word)
    front_lines = [f'<span style="font-size:1.4em">{word_html}</span>']
    if record.example_ru:
        example_bold = _bold_word_in_example(record.example_ru, record.lemma)
        front_lines.append(example_bold.replace("\n", "<br>"))
    front = "<br>".join(front_lines)

    back_lines = []
    grammar = _grammar_line(record)
    if grammar:
        back_lines.append(grammar)
    if record.movement_type:
        # dimensão independente do aspecto (os dois verbos do par são imperfectivos),
        # por isso linha e cor própria em vez de entrar na _grammar_line
        back_lines.append(f'<b style="color:{_MOVEMENT_COLOR}">{record.movement_type}</b>')
    translation = _translation_line(record)
    if translation:
        back_lines.append(translation)
    if record.short_form:
        back_lines.append(f"forma curta: {record.short_form}")
    if record.indeclinable:
        back_lines.append("não declina")
    if record.example_ru and record.example_translation:
        back_lines.append(record.example_translation.replace("\n", "<br>"))

    back = "<br>".join(line for line in back_lines if line)
    return front, back


def build_note(record: WordRecord) -> genanki.Note:
    front, back = note_fields(record)
    return genanki.Note(model=MODEL, fields=[front, back])


def build_deck(
    records: Iterable[WordRecord],
    deck_name: str = "Russo::Produção Ativa",
    deck_id: int = DECK_ID_DEFAULT,
) -> genanki.Deck:
    deck = genanki.Deck(deck_id, deck_name)
    for record in records:
        deck.add_note(build_note(record))
    return deck


def write_apkg(
    records: Iterable[WordRecord],
    out_path: Path,
    deck_name: str = "Russo::Produção Ativa",
) -> None:
    deck = build_deck(records, deck_name=deck_name)
    genanki.Package(deck).write_to_file(str(out_path))
