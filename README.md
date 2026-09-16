# Gerador de Cards de Anki para Russo

Resolve palavras/expressões em russo (em qualquer forma gramatical, não
precisa ser o dicionário/nominativo) e sobe os cards direto no Anki via
[AnkiConnect](https://foosoft.net/projects/anki-connect/), pra produção ativa
(gênero/aspecto, tônica, tradução, frase de exemplo).

## Pré-requisitos

```bash
pip install -r requirements.txt
```

- **Anki aberto**, com o addon [AnkiConnect](https://ankiweb.net/shared/info/2055492159)
  instalado (código do addon: `2055492159`). Sem isso, o fluxo principal não roda —
  veja "Modo manual" abaixo se quiser gerar um arquivo sem precisar do Anki aberto.

## Uso no dia a dia

1. Edite (ou crie) um arquivo `.txt` dentro de `palavras/`, uma palavra/expressão
   por linha — pode ir só acrescentando linhas novas ao longo do tempo, nunca
   precisa criar um arquivo por sessão. `palavras/exemplo.txt` é só uma amostra
   versionada no repo.
2. Com o Anki aberto:
   ```bash
   python main.py --deck "Russo::Produção Ativa"
   ```
3. O script lê todos os `.txt` de `palavras/`, pula o que já foi processado
   antes (registrado em `palavras/processadas.json`), resolve e envia pro Anki
   só o que é novo — sem duplicar cards já existentes (checagem via
   `canAddNotes` do AnkiConnect).

Ao final, o terminal mostra:
- quantas palavras novas foram processadas e enviadas ao Anki;
- quantas já estavam no manifest e foram puladas;
- quantas caíram em `revisar_manualmente.csv` (falta tradução, gênero/aspecto,
  ou — para expressões de mais de uma palavra — nenhuma fonte tinha a
  expressão inteira);
- os campos de melhor esforço (tônica, frase de exemplo, regência de caso),
  que não bloqueiam o card mas ficam em branco quando não encontrados.

Se o Anki não estiver aberto (ou o addon não estiver instalado), o script para
imediatamente com um aviso claro — nada é gerado nem marcado como processado.

## Modo manual: exportar um `.apkg` pontual

Não depende do Anki estar aberto nem mexe no manifest — útil pra gerar um
arquivo avulso pra importar manualmente:

```bash
python main.py --export-apkg deck.apkg
```

## Fontes de dados (em cascata)

1. **pymorphy3** — lematização, POS, gênero (substantivos) e aspecto (verbos), offline.
2. **[kaikki.org](https://kaikki.org/dictionary/Russian/)** (dump do Wiktionary
   russo via [Wiktextract](https://github.com/tatuylonen/wiktextract), ~900 MB,
   licenciado [CC BY-SA](https://en.wiktionary.org/wiki/Wiktionary:Copyrights))
   — tradução (raramente em português; quase sempre inglês), frase de exemplo,
   e uma tentativa best-effort de regência de caso. Baixado uma vez para
   `cache/` na primeira execução; use `--no-kaikki` para pular essa fonte.
3. **OpenRussian** (dump CSV mantido no GitHub por
   [`Badestrand/russian-dictionary`](https://github.com/Badestrand/russian-dictionary),
   espelhando [openrussian.org](https://en.openrussian.org)) — tônica,
   gênero/aspecto+par aspectual, tradução EN/DE. Baixado uma vez para `cache/`.

Os dois dumps (~950 MB no total) ficam só em `cache/` na sua máquina — **não são
redistribuídos neste repositório** (gitignored). Cada execução em uma máquina
nova baixa a própria cópia automaticamente. Consulte os projetos originais
acima para os termos de uso/licença de cada dataset.

## Limitações conhecidas

- Tradução em português é rara nas fontes automáticas; a maioria dos cards vai
  mostrar `[EN]`/`[DE]` antes da tradução quando o português não foi encontrado
  (marcação explícita, conforme especificado).
- Regência de caso quase nunca está disponível como dado estruturado — é
  best-effort e frequentemente fica em branco.
- Multi-palavra (expressões) exige match exato da expressão inteira numa das
  fontes; se não achar, vai inteira para `revisar_manualmente.csv`.

## Licença

O código deste projeto está sob a licença [MIT](LICENSE). Isso cobre só o
código-fonte — **não** os dados de terceiros baixados para `cache/` em tempo
de execução (kaikki/Wiktextract e o dump do OpenRussian/Badestrand), que têm
suas próprias licenças, referenciadas na seção "Fontes de dados" acima.
