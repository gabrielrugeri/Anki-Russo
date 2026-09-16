"""Grava a fila de revisão manual (revisar_manualmente.csv).

Distingue "palavra simples" (campo essencial faltante: tradução/gênero/aspecto)
de "expressão multi-palavra" (sem match completo da expressão nas fontes).
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .resolver import WordRecord


def write_review_queue(records: Iterable[WordRecord], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["palavra_original", "lema_resolvido", "categoria", "campos_faltantes"])
        for record in records:
            categoria = "expressão multi-palavra" if record.is_expression else "palavra simples"
            lema = record.lemma if record.lemma and record.lemma != record.input_word else ""
            writer.writerow([
                record.input_word,
                lema,
                categoria,
                "; ".join(record.missing_essential),
            ])
