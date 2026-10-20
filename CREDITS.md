# Credits

OfferReady is built on open-source software. Thank you to their authors.

## Server (Python)

| Component | Used for | License |
|---|---|---|
| Starlette, Uvicorn | web framework and server | BSD-3-Clause |
| Pydantic | request validation | MIT |
| pdfplumber / pdfminer.six | resume text, fonts and layout geometry | MIT |
| pypdfium2 (PDFium) | rendering resume pages | Apache-2.0 / BSD-3-Clause |
| Tesseract OCR + pytesseract | reading text inside images | Apache-2.0 |
| OpenCV | profile-photo face check | Apache-2.0 |
| Playwright + Chromium | live-link checks and screenshots | Apache-2.0 / BSD |
| HTTPX | outbound HTTP | BSD-3-Clause |
| PyJWT, cryptography | sessions and file encryption | MIT / Apache-2.0 or BSD |
| Pillow, NumPy | image handling | MIT-CMU / BSD-3-Clause |
| ReportLab (tests) | generating the labelled resume corpus | BSD |
| LibreOffice (optional) | DOCX to PDF conversion | MPL-2.0 |
| Git | cloning student repositories | GPL-2.0 (used as an external program) |

## Web app

| Component | Used for | License |
|---|---|---|
| React, React DOM | user interface | MIT |
| react-icons (Lucide set) | icons | MIT / ISC |
| esbuild, TypeScript | build | MIT / Apache-2.0 |

## Data and fonts

| Item | Used for | License |
|---|---|---|
| Hunspell en_US dictionary (SCOWL-derived) | spell check word list (`app/data/words_en.txt.gz`) | permissive (SCOWL/Hunspell terms) |
| Carlito (Google Crosextra) | interface text | SIL Open Font License 1.1 |
| TeX Gyre Schola (GUST) | display headings | GUST Font License |

Job data belongs to the publishing companies and job boards. OfferReady shows the source and links to the original
posting, as each source's terms require. The sample jobs, demo students and fixture repositories are fictional.
