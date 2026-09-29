"""CLI: resolve palavras russas e sobe os cards direto no Anki via AnkiConnect.

Uso principal (Anki precisa estar aberto, com o addon AnkiConnect instalado):
    python main.py --deck "Russo::Produção Ativa"

Lê todos os .txt de palavras/ (o usuário só vai acrescentando linhas ao longo
do tempo), pula o que já está em palavras/processadas.json, resolve e envia
pro Anki só o que é novo, e atualiza o manifest com o que foi confirmado.

Export pontual de .apkg (não mexe no manifest nem no Anki):
    python main.py --export-apkg deck.apkg
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src import anki_connect, manifest as manifest_module
from src.deck_builder import note_fields, write_apkg
from src.resolver import Resolver, WordRecord
from src.review_queue import write_review_queue

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_INPUT_DIR = Path("palavras")
DEFAULT_MANIFEST_PATH = DEFAULT_INPUT_DIR / "processadas.json"
DEFAULT_DECK_NAME = "Russo::Produção Ativa"


def read_words(input_dir: Path) -> list[str]:
    words: list[str] = []
    for path in sorted(input_dir.glob("*.txt")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            words.append(line)
    return words


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "0/0"


def _best_effort_report(records: list[WordRecord]) -> None:
    single = [r for r in records if not r.is_expression]
    print("\n--- Campos de melhor esforço (não bloqueiam o card) ---")
    print(f"Tônica encontrada: {_pct(sum(1 for r in single if r.stress), len(single))}")
    print(f"Frase de exemplo encontrada: {_pct(sum(1 for r in single if r.example_ru), len(single))}")
    verbs_resolved = [r for r in single if r.pos == "VERB" and r.resolved]
    print(
        "Regência de caso encontrada (entre os verbos resolvidos): "
        f"{_pct(sum(1 for r in verbs_resolved if r.case_government), len(verbs_resolved))}"
    )


def run_export_apkg(args: argparse.Namespace) -> None:
    words = read_words(args.input_dir)
    logger.info("Lidas %d entradas de %s/*.txt", len(words), args.input_dir)

    resolver = Resolver(use_kaikki=not args.no_kaikki)
    records = [resolver.resolve(w) for w in words]

    resolved = [r for r in records if r.resolved]
    unresolved = [r for r in records if not r.resolved]

    deck_name = args.deck or DEFAULT_DECK_NAME
    write_apkg(resolved, args.export_apkg, deck_name=deck_name)
    write_review_queue(unresolved, args.review_out)

    logger.info("Deck gravado em %s (%d cards)", args.export_apkg, len(resolved))
    logger.info("Fila de revisão gravada em %s (%d entradas)", args.review_out, len(unresolved))
    _best_effort_report(resolved)


def run_anki_connect(args: argparse.Namespace) -> None:
    if not anki_connect.is_available():
        logger.error(
            "Anki não está acessível via AnkiConnect (http://localhost:8765). "
            "Abra o Anki com o addon AnkiConnect instalado e rode novamente. "
            "Nada foi gerado nem marcado como processado."
        )
        raise SystemExit(1)

    words = read_words(args.input_dir)
    logger.info("Lidas %d entradas de %s/*.txt", len(words), args.input_dir)

    manifest = manifest_module.load(args.manifest)
    resolver = Resolver(use_kaikki=not args.no_kaikki)

    already_processed: list[WordRecord] = []
    unresolved: list[WordRecord] = []
    to_upload: list[WordRecord] = []
    queued_lemmas: set[str] = set()

    for word in words:
        record = resolver.resolve(word)
        if not record.resolved:
            unresolved.append(record)
            continue
        # já processada antes (manifest) OU duas entradas diferentes desta
        # mesma leitura resolveram pro mesmo lema (ex.: uma forma flexionada e
        # o dicionário na mesma lista) — nos dois casos, não manda de novo.
        # Sem isso o mesmo Frente/Verso ia duas vezes no mesmo lote pro
        # AnkiConnect, que rejeita com erro em vez de só pular a segunda.
        if record.lemma in manifest or record.lemma in queued_lemmas:
            already_processed.append(record)
            continue
        queued_lemmas.add(record.lemma)
        to_upload.append(record)

    sent = 0
    already_in_anki = 0
    if to_upload:
        fields_list = []
        for record in to_upload:
            front, back = note_fields(record)
            fields_list.append({"Frente": front, "Verso": back})

        note_ids = anki_connect.add_notes(args.deck, fields_list)
        for record, note_id in zip(to_upload, note_ids):
            manifest_module.mark_processed(
                manifest, record.lemma, input_word=record.input_word, deck=args.deck, note_id=note_id
            )
            if note_id is not None:
                sent += 1
            else:
                already_in_anki += 1  # duplicata detectada pelo Anki, mas confirmada como já existente

        manifest_module.save(args.manifest, manifest)

    write_review_queue(unresolved, args.review_out)

    print("\n=== Resultado ===")
    print(f"Total de entradas lidas: {len(words)}")
    print(f"Palavras novas processadas e enviadas ao Anki: {sent}")
    if already_in_anki:
        print(f"  (das quais {already_in_anki} já existiam no Anki como duplicata e só foram marcadas no manifest)")
    print(f"Já estavam no manifest e foram puladas: {len(already_processed)}")
    print(f"Caíram em revisar_manualmente.csv: {len(unresolved)}")
    expr_missing = sum(1 for r in unresolved if r.is_expression)
    if expr_missing:
        print(f"  - das quais {expr_missing} são expressão multi-palavra sem match completo")

    _best_effort_report(to_upload)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve palavras russas e sobe os cards no Anki (via AnkiConnect)."
    )
    parser.add_argument("--deck", default=None, help='Nome do baralho no Anki, ex: "Russo::Produção Ativa"')
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--review-out", type=Path, default=Path("revisar_manualmente.csv"))
    parser.add_argument(
        "--no-kaikki",
        action="store_true",
        help="Pula a fonte kaikki.org (útil se não houver acesso ao dump nesta máquina)",
    )
    parser.add_argument(
        "--export-apkg",
        type=Path,
        default=None,
        help="Modo manual: gera um .apkg pontual em vez de subir via AnkiConnect (não mexe no manifest)",
    )
    args = parser.parse_args()

    if args.export_apkg is None and not args.deck:
        parser.error("--deck é obrigatório (ou use --export-apkg pra gerar um arquivo pontual)")

    if args.export_apkg is not None:
        run_export_apkg(args)
    else:
        run_anki_connect(args)


if __name__ == "__main__":
    main()
