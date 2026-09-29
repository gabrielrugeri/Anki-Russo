"""Upload de notas pro Anki via AnkiConnect (addon HTTP, porta 8765 por padrão).

Fluxo principal do projeto: os cards resolvidos são enviados direto pro Anki
aberto na máquina, em vez de gerar um .apkg pra importar manualmente. Duplicata
é checada via `canAddNotes` antes de adicionar — nunca sobrescreve uma nota
existente.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

ANKI_CONNECT_URL = "http://localhost:8765"
ANKI_CONNECT_VERSION = 6
MODEL_NAME = "Russo - Produção Ativa"
MODEL_CSS = ".card { font-family: arial; font-size: 22px; text-align: center; color: black; background-color: white; }"


class AnkiConnectError(RuntimeError):
    """Anki não está acessível via AnkiConnect, ou a API retornou um erro."""


def _invoke_raw(action: str, **params) -> dict:
    """Chama o AnkiConnect e devolve {"result":..., "error":...} sem levantar
    em cima de um erro de nível de ação (ex: nota duplicada) — só uma falha de
    conexão (Anki fechado) é fatal aqui. Usado quando o chamador precisa
    tratar o erro por item em vez de tudo-ou-nada."""
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
    return resp.json()


def _invoke(action: str, **params):
    data = _invoke_raw(action, **params)
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

    # Adiciona uma nota de cada vez em vez de um `addNotes` em lote: o
    # `addNotes` do AnkiConnect é tudo-ou-nada — se UMA nota do lote falhar
    # (ex: duas notas novas resolvendo pro mesmo lema na mesma execução,
    # que o `canAddNotes` não pega porque só compara com o que já existe na
    # coleção, não com as outras notas do próprio lote), a chamada inteira
    # falha e nenhuma nota é criada. Nota por nota, um problema isolado não
    # derruba as outras.
    results: list[Optional[int]] = [None] * len(notes)
    for i, (note, addable) in enumerate(zip(notes, can_add)):
        if not addable:
            continue
        data = _invoke_raw("addNote", note=note)
        if data.get("error") is not None:
            if "duplicate" not in str(data["error"]).lower():
                logger.warning("Não foi possível adicionar a nota '%s': %s", note["fields"].get("Frente", "?")[:60], data["error"])
            continue
        results[i] = data.get("result")

    return results
