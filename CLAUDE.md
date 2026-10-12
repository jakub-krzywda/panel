# Dziennik — serwis zbierający dane o nawykach i stanie

## Cel projektu

Zbudować lokalny serwis www, który:

1. Codziennie prezentuje formularz na dzisiejszy dzień i zapisuje dane do bazy.
2. Importuje historyczne dane z backupu dziennika w PDF (GoodNotes), żeby nie startować z pustymi statystykami.
3. W przyszłości: automatycznie wypełnia formularz na podstawie zdjęcia strony dziennika z GoodNotes.
4. W przyszłości: ściąga dane z innych źródeł (Garmin przez API lub Playwright, pogoda, inne) do jednego miejsca.
5. Pokazuje statystyki, trendy, rekomendacje treningów.

Serwis działa docelowo w sieci lokalnej na Raspberry Pi w domu użytkownika. Dane są prywatne — żaden składnik nie wysyła ich na zewnątrz (poza pogodą, która tylko pobiera dane publiczne).

## Użytkownik

Jedyny użytkownik: Kuba (Jakub Krzywda), senior test engineer, Python/TypeScript, Mac jako główna maszyna. Potrafi deployować, czytać logi, edytować configi — nie trzeba mu tłumaczyć podstaw. Preferuje proste, maintainable rozwiązania nad sprytne abstrakcje. Mało ufa automatyzacji infrastruktury bez wglądu w diffy. Patrz dalej `## Zasady pracy`.

## Priorytety — kolejność prac

**Pracujemy przyrostowo. Jeden sprint = jedna sensowna część. Nie buduj piramidy przed fundamentem.**

### Sprint 1 — Parser dziennika z PDF (najważniejszy, zaczynamy tu)

Nawet najprostszy MVP serwisu nie ma sensu bez historycznych danych. Startujemy od parsera.

**Wejście:** PDF backup dziennika z GoodNotes (strony A4, każda strona = jeden dzień wg template'u). Template zmieniał się kilkukrotnie w czasie — patrz `## Historia templatów`.

**Co wyciągnąć ze strony:**

- Data (pole w górnym rzędzie, pisane ręcznie)
- Nawyki (checkboxy w dolnym pasku): TRENING, MUZYKA, CZYTANIE, SEN PRZED 0:00, NIE PALENIE
- Pomodoro (6–8 checkboxów, policz zaznaczone)
- Spacery z psami: 2 checkboxy (13:00, 20:00) + krótkie notatki tekstowe obok
- Ciśnienie: 2 wiersze × 3 kolumny (SYS/DIA/PULS × rano/wieczorem) — liczby pisane ręcznie
- „Co ćwiczę sport" i „Co ćwiczę muzyka" — pola tekstowe, OCR odręcznego pisma

**Strategia techniczna:**

- Rozpoznawanie checkboxów (zaznaczony vs pusty) jest wiarygodne i szybkie — zacznij od tego. Prostego klasyfikatora opartego na procencie czarnych pikseli w ROI zazwyczaj wystarczy. Nie zaczynaj od modelu ML.
- OCR dat i liczb (ciśnienie): typowe silniki OCR na odręcznym piśmie są słabe. Rozważ lokalny model vision-LLM (Qwen2-VL, llava, lub podobny) na Jetson Orin Nano, który użytkownik ma pod ręką — patrz `/areas/journal-ocr.md` w projekcie.
- OCR pól swobodnych („co ćwiczę") — to samo, vision-LLM lokalnie. Niska dokładność jest OK, ten tekst to kontekst, nie metryka.
- **Pierwszym krokiem jest przetestowanie podejścia na jednej stronie, nie zbudowanie pełnego pipeline'u.** Pokaż użytkownikowi wyniki na jednej stronie, zanim zaczniesz przetwarzać miesiące backupu.

**Co musi powstać:**

- Skrypt CLI, który dostaje PDF (albo zakres stron) i wypluwa JSON/CSV z danymi dnia.
- Mapowanie wersji templatu → współrzędne ROI (różne templaty mają różne układy pól).
- Raport z pewności per pole, żeby użytkownik mógł ręcznie poprawić wątpliwe wyniki.
- Idempotentność: ponowne uruchomienie na tym samym PDF-ie nie dubluje danych.

### Sprint 2 — Schemat bazy + najprostszy serwis

- SQLite (prosty backup, działa na RPi, nie wymaga serwera DB).
- Schemat na dane dnia + źródło pochodzenia (`manual`, `pdf_import`, `screenshot_import`, `garmin`, ...).
- Migracje przez Alembic (albo coś równie prostego — do dyskusji).
- Formularz webowy pojawia się dla dzisiejszej daty, podgląd ostatnich kilku dni, lista historyczna. Nic więcej na razie.
- Każdy zapis dostaje timestamp wypełnienia (osobne pole od daty samego dnia).

### Sprint 3 — Pogoda + poprawki UX

- Pogoda z Open-Meteo (brak klucza API, darmowe, bez rejestracji) dla lokalizacji Katowice.
- Pobierana przy zapisie formularza i zapisywana wraz z nim (nie online z dashboardu — snapshot do historii).
- Drobny dashboard: wykresy nawyków, ciśnienia, pomodoro per tydzień/miesiąc.

### Sprint 4 — Import ze screenshota strony dziennika

To rozszerzenie parsera z Sprintu 1: zamiast strony PDF, pojedyncze zdjęcie z telefonu lub export z GoodNotes.

- Normalizacja perspektywy (strona sfotografowana pod kątem — rozpoznaj narożniki, wyprostuj).
- Reszta pipeline'u taka sama.
- Endpoint w serwisie: upload zdjęcia → parsowanie → prefill formularza → użytkownik potwierdza/koryguje → zapis.

### Sprint 5+ — Deployment na RPi, Garmin, rekomendacje

Nie planujemy teraz. Agent nie powinien proaktywnie przygotowywać infrastruktury pod to.

## Dane do zbierania (specyfikacja z template'u v8)

Źródło prawdy dla układu stron: template v8 (`Tydzien_Template_v8.pdf`). Patrz też `## Historia templatów`.

### Pola parsowalne (dolna część strony pod separatorem „DANE PARSOWALNE")

| Pole | Typ | Źródło (template) |
|---|---|---|
| `date` | ISO date | pole „DATA" w górnym rzędzie |
| `sleep_from` / `sleep_to` / `sleep_hours` | time / time / float | pola w górnym rzędzie |
| `weather` | string (opisowy) | pole „pogoda i samopoczucie" (opcjonalnie, może być z API) |
| `weather_api` | JSON z Open-Meteo | pobierane przy zapisie |
| `fill_timestamp` | ISO datetime | timestamp zapisu, osobny od `date` |
| `habits.trening` | bool | checkbox w dolnym pasku |
| `habits.muzyka` | bool | j.w. |
| `habits.czytanie` | bool | j.w. |
| `habits.sen_przed_0` | bool | j.w. |
| `habits.nie_palenie` | bool | j.w. |
| `habits.suma_dnia` | int | pole „SUMA DNIA" (można policzyć automatycznie) |
| `pomodoro_count` | int (0–8) | checkboxy w sekcji POMODORO |
| `walks.1300` | bool | checkbox przy 13:00 |
| `walks.2000` | bool | checkbox przy 20:00 |
| `walks.1300_note` / `walks.2000_note` | string | linia obok (jedno słowo: las, blok…) |
| `bp.morning.sys` / `bp.morning.dia` / `bp.morning.pulse` | int | tabela ciśnienia, wiersz „rano" |
| `bp.evening.sys` / `bp.evening.dia` / `bp.evening.pulse` | int | tabela ciśnienia, wiersz „wiecz." |
| `sport_text` | string | pole „CO ĆWICZĘ SPORT" |
| `music_text` | string | pole „CO ĆWICZĘ MUZYKA" |

### Pola NIE parsowalne (nie importować, nie trzymać w bazie)

Treści z górnej (prywatnej) części strony — refleksje, lista zadań TRZEBA/CHCĘ/INNE, „co czytam/oglądam" — zostają w notesie i nie wchodzą do serwisu. Separator „DANE PARSOWALNE" na stronie jest granicą.

## Źródła danych

- **Templaty dziennika (foldery):**
  - macOS, iCloud: `/Users/jakubkrzywda/Library/Mobile Documents/com~apple~CloudDocs/_GoodNotes templates` (dziś podłączony przez bridge Claude Code — sprawdź `device_list_dir`).
  - Historia zmian templatów = daty modyfikacji plików w tym folderze + zestawienie z `## Historia templatów` niżej.
- **Backup dziennika w PDF z GoodNotes** — ścieżka do ustalenia z użytkownikiem przy starcie.
- **Formularz webowy** — primary input, docelowo.
- **Zdjęcia stron dziennika** — secondary input, przez upload w serwisie.
- **Pogoda:** Open-Meteo (`https://api.open-meteo.com/v1/forecast`), bez klucza.
- **Garmin (przyszłość):** garmin-connect-python lub Playwright na Garmin Connect.

## Historia templatów

Przez tę rozmowę powstało 7 iteracji templatu (v2 → v8). Konkretnych dat kolejnych iteracji nie znamy — ale pliki PDF są prawdopodobnie w folderze iCloud wyżej, więc **pierwsze co zrób, to przeskanuj folder, zapisz daty modyfikacji każdego pliku i stwórz z tego mapping „data → wersja templatu → układ ROI".** To mapowanie będzie potrzebne parserowi do rozpoznania, który układ ma dana strona backupu.

Najważniejsze zmiany między wersjami (do przełożenia na konfigurację ROI):

- **v2:** 5 kratek nawyków: TRENING, MUZYKA, MEDYTACJA, SEN PRZED 0:30, UMIAR W PRZEK. Posiłki jako liczniki kreskowe. Legenda pod spodem strony.
- **v3:** Nawyki: MEDYTACJA → NIE PALENIE, UMIAR → DIETA. Legenda jako pionowa kolumna z prawej. Posiłki jako checkboxy (3+2).
- **v4:** Legenda jako wąski poziomy pasek nad tabelą zadań. Spacery przeniesione do middle_row z checkboxami 13:00/20:00. JEDZENIE w dolnym pasku. Nawyk SEN PRZED 0:30 → SEN ok. 1:00.
- **v5:** Tylko poprawka wizualna legendy.
- **v6:** Nawyki: NIE PALENIE → CZYTANIE, DIETA → BRAK SŁODYCZY. SEN ok. 1:00 → SEN PRZED 0:00. **Dodana tabela ciśnienia** (SYS/DIA/PULS × rano/wieczorem).
- **v7:** Zmiana nazw pól („WNIOSKI?" → „CO ĆWICZĘ SPORT", „NIE ZAPOMNIJ" → „CO ĆWICZĘ MUZYKA"). BRAK SŁODYCZY → NIE PALENIE. Nawyki z tabeli na checkboxy z labelami.
- **v8 (aktualna):** Nowa paleta kategorii (dom/psy/Jarek/finanse/moje — bez priorytetów, bo priorytet już niosą kolumny TRZEBA/CHCĘ/INNE). Refleksje + zadania w jednym bloku. **Separator „DANE PARSOWALNE"** dzieli stronę na część prywatną (góra) i parsowalną (dół). Usunięte posiłki. Pomodoro ma 8 kratek.

Dla parsera parsowalny obszar w czasie (v6+): wszystko co trzeba, już jest w dolnej części strony. Przed v6 — brak ciśnienia (po prostu zostawić puste pola).

## Technologia (sugerowana, otwarta do dyskusji)

Nie decyduj za użytkownika. Zaproponuj, uzasadnij, poczekaj.

- **Backend:** Python 3.12+, FastAPI (prosty, async, user zna). Alternatywa: Flask jeśli użytkownik woli minimalizm.
- **Baza:** SQLite + SQLAlchemy. Backup przez `.sqlite` + rsync lub `litestream` na dysk sieciowy.
- **Frontend:** HTMX + Jinja2 templates. Nie SPA. Formularz na jeden dzień to formularz, nie aplikacja. Alternatywa: zwykły template Jinja + mały JS vanilla.
- **Parser PDF:** `pdf2image` (strona → obraz), `opencv-python` (ROI, checkbox detection), `pytesseract` jako baseline OCR, `ollama` + model vision (qwen2-vl:7b lub llava) na Jetson Orin Nano dla odręcznego pisma.
- **Pakiet management:** `uv` (szybkie, nowoczesne). Alternatywa: `pdm` lub poetry.
- **Testy:** pytest. User ma 9 lat w test automation, oczekuje porządnych testów na parser (dane wejściowe → oczekiwany JSON).
- **Deployment na RPi:** docker-compose. Jeden kontener na app, jeden na parser (gdyby parser miał zjeść wszystkie zasoby — niech nie zbija serwisu).
- **Pogoda:** `httpx` async, cache 1h.

## Zasady pracy

Te zasady są kopią userPreferences użytkownika — trzymaj się ich.

**Komunikacja:**
- Zwięźle, bez pustej pochwały („świetny pomysł" → NIE).
- Odpowiadaj w języku pytania (zwykle po polsku).
- Jeśli coś jest ryzykowne, niejasne, przekombinowane — powiedz to.
- Praktyka > teoria. Nie wykładaj, chyba że pyta.
- Proste pytanie = prosta odpowiedź.

**Współpraca:**
- Senior pair-programming partner, nie autonomiczny agent. Nie wprowadzaj dużych zmian strukturalnych bez zgody.
- **Przed modyfikacją plików** — powiedz co i dlaczego, poczekaj na OK (szczególnie przy architekturze, config, dependency, infra, danych, deployment, testach, publicznych API).
- Drobne read-only inspekcje bez pytania — OK.
- Przeglądnij istniejący kod zanim zaproponujesz zmianę strukturalną.
- Jedno dobre następne kroki > długa roadmapa.

**Kod:**
- Prosto i maintainable. Małe iteracje, odwracalne zmiany.
- Nie wymyślaj architektury jeśli repo już ją ma. Czytaj README/CLAUDE.md/docs najpierw.
- Python do skryptów, parserów, małych serwisów.
- TypeScript do frontendu (jeśli potrzebny, co tu nie jest pewne).
- Komentarze tylko dla nieoczywistego.

**Bezpieczeństwo:**
- Konserwatywnie z infra, deployem, sekretami, bazami.
- Nic nie kasuj / nadpisuj / migruj bez wyjaśnienia ryzyka i potwierdzenia.
- Przed ryzykowną operacją — backup, dry-run, diff, read-only diagnostyka.
- Destrukcyjne komendy wyraźnie oznaczaj.

**Response format:**
- Zacznij od odpowiedzi, nie od preambuły.
- Bullet points dla jasności.
- Code blocks dla komend i snippetów.
- Zakończ jednym konkretnym następnym krokiem gdy sensowne.

## Linki i konteksty

- **Projekt w Claude:** „Parsowanie notatek" (`01a1260f-8cbc-70e8-ae3d-b9af71b81d55`). Wrzucaj tam decyzje techniczne i specyfikacje przez `project_write`.
- **Memory z poprzednich sesji:** `/projects/01a1260f-8cbc-70e8-ae3d-b9af71b81d55/areas/journal-ocr.md` oraz `/areas/journal-ocr.md` — przeczytaj przed startem, user już myślał o OCR na Jetson Orin Nano.
- **Folder templatów (iCloud):** `/Users/jakubkrzywda/Library/Mobile Documents/com~apple~CloudDocs/_GoodNotes templates`
- **Jetson Orin Nano** — dostępny lokalnie w sieci użytkownika, może hostować model vision-LLM dla OCR.

## Pierwsze kroki dla agenta

Zrób TYLKO to przy starcie, nie więcej:

1. Przeczytaj ten plik do końca.
2. Przeczytaj `/projects/.../areas/journal-ocr.md` z memory (jeśli dostępne).
3. Przeskanuj folder templatów, zrób zestawienie `nazwa_pliku → mtime → wersja templatu`. Zapisz jako `docs/templates_history.md` w repo.
4. Zapytaj użytkownika o ścieżkę do backupu dziennika PDF (prawdopodobnie w iCloud).
5. **Zaproponuj plan Sprintu 1** (parser PDF, jedna strona) i poczekaj na zgodę przed pisaniem kodu.
