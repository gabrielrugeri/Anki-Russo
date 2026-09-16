"""Upload de notas pro Anki via AnkiConnect (addon HTTP, porta 8765 por padrão).

Fluxo principal do projeto: os cards resolvidos são enviados direto pro Anki
aberto na máquina, em vez de gerar um .apkg pra importar manualmente. Duplicata
é checada via `canAddNotes` antes de adicionar — nunca sobrescreve uma nota
existente.
"""
from __future__ import annotations

from typing import Optional

import requests

ANKI_CONNECT_URL = "http://localhost:8765"
ANKI_CONNECT_VERSION = 6
MODEL_NAME = "Russo - Produção Ativa"
MODEL_CSS = ".card { font-family: arial; font-size: 22px; text-align: center; color: black; background-color: white; }"


class AnkiConnectError(RuntimeError):
    """Anki não está acessível via AnkiConnect, ou a API retornou um erro."""


def _invoke(action: str, **params):
    payload = {"action": action, "version": ANKI_CONNECT_VERSION}
    if params:
        payload["params"] = params
    try:
        resp = requests.post(ANKI_CONNECT_URL, json=payload, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise AnkiConnectError(
            f"Não foi possível conectar ao AnkiConnect em {ANKI_CONNECT_URL}. "
            "Abra o Anki com o addon AnkiConnect instalado e rode novamente."
        ) from exc

    data = resp.json()
    if data.get("error") is not None:
        raise AnkiConnectError(f"AnkiConnect retornou erro em '{action}': {data['error']}")
    return data.get("result")


def is_available() -> bool:
    try:
        _invoke("version")
        return True
    except AnkiConnectError:
        return False


def deck_names() -> list[str]:
    return _invoke("deckNames")


def ensure_deck(deck_name: str) -> None:
    _invoke("createDeck", deck=deck_name)


def ensure_model(model_name: str = MODEL_NAME) -> None:
    """Garante que o note type existe no Anki (mesmos campos/template do Model
    do genanki: Frente/Verso, card único). Se já existir (ex: de uma
    importação de .apkg anterior), não faz nada."""
    existing = _invoke("modelNames")
    if model_name in existing:
        return
    _invoke(
        "createModel",
        modelName=model_name,
        inOrderFields=["Frente", "Verso"],
        css=MODEL_CSS,
        cardTemplates=[
            {
                "Name": "Card 1",
                "Front": "{{Frente}}",
                "Back": '{{FrontSide}}<hr id="answer">{{Verso}}',
            }
        ],
    )


def add_notes(
    deck_name: str,
    fields_list: list[dict],
    model_name: str = MODEL_NAME,
) -> list[Optional[int]]:
    """Envia notas pro Anki, pulando duplicatas (nunca sobrescreve uma existente).

    `fields_list`: lista de dicts {"Frente": ..., "Verso": ...}, na mesma ordem
    do retorno.
    Retorna uma lista paralela: id da nota criada no Anki, ou None se foi
    pulada por já existir uma nota igual (duplicata detectada pelo
    `canAddNotes` do próprio Anki, baseado no primeiro campo/"Frente").
    """
    if not fields_list:
        return []

    ensure_deck(deck_name)
    ensure_model(model_name)

    notes = [
        {
            "deckName": deck_name,
            "modelName": model_name,
            "fields": fields,
            "options": {"allowDuplicate": False},
        }
        for fields in fields_list
    ]

    can_add = _invoke("canAddNotes", notes=notes)

    results: list[Optional[int]] = [None] * len(notes)
    addable_indexes = [i for i, ok in enumerate(can_add) if ok]
    if addable_indexes:
        added_ids = _invoke("addNotes", notes=[notes[i] for i in addable_indexes])
        for idx, note_id in zip(addable_indexes, added_ids):
            results[idx] = note_id

    return results
