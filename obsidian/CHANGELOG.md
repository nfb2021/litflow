# Changelog

## Unreleased

- Find the vault through a litflow project: run from a folder with `rsx.toml`,
  `obs` uses the vault it names (default `vault/`).

## 0.1.0

- `obs` CLI: vault init, paper sync from Better BibTeX `.bib`, screening,
  statements with near-duplicate check, claims with PDF quote check, independent
  verification, provenance trace, maps/questions/frontier, glossary, decisions,
  `ls`/`show`/`neighbors`/`sql`, `lint` with `--gate` JSON verdict.
- `obs ocr` for scans without a text layer (ocrmypdf); `no-text` quote status.
- `obs pdf-text` to copy quotes from the PDF text.
