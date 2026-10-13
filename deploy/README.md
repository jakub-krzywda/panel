# Deploy na Raspberry Pi

Decyzje (2026-10-13): **systemd + uv** (bez Dockera), **baza przenoszona z Maca na RPi** (od tej chwili RPi jest
główną bazą), **HTTP Basic** z hasłem w `.env`. Serwis słucha na porcie **8002** w sieci domowej (8000 na RPi zajmuje inna usługa).

Zasady jak w CLAUDE.md: komendy zmieniające system (sudo, systemd, kopiowanie bazy) — najpierw pokaż, potem wykonaj
po OK. Bazę zawsze kopiuj, nigdy nie nadpisuj bez backupu.

## Wymagania

- **64-bitowy** Raspberry Pi OS (Bookworm). Sprawdź: `uname -m` → `aarch64`. Na 32-bitowym (`armv7l`) nie ma
  gotowych paczek opencv/pymupdf — nie wdrażaj.
- Python 3.12 instaluje `uv` (nie trzeba systemowego).
- Na RPi **nie ma OCR** (Apple Vision jest tylko na macOS): import ze zrzutu odczyta kratki (nawyki, pomodoro,
  spacery), a ciśnienie i notatki trzeba wpisać ręcznie. Strona to komunikuje.

## 1. Kod i zależności (na RPi)

```bash
uname -m && cat /etc/os-release | head -3 && timedatectl | grep "Time zone"
curl -LsSf https://astral.sh/uv/install.sh | sh        # instaluje uv do ~/.local/bin
git clone git@github.com:jakub-krzywda/panel.git ~/panel   # repo prywatne → klucz SSH RPi dodany w GitHub (deploy key, read-only)
cd ~/panel
uv sync --no-dev --frozen                               # dokładnie wersje z uv.lock
```

Bez dostępu RPi do GitHuba: kod można przesłać z Maca (`rsync -a --exclude .venv --exclude data --exclude .git ./ pi@<rpi>:~/panel/`).

## 2. Dane (z Maca → RPi)

Na RPi potrzebne są: baza i PDF-y templatów (parser zrzutów porównuje z `Tydzien_Template_v8.pdf`).
Strony dziennika (`data/dziennik_2026/`) i wyniki parsera **nie są potrzebne**.

Na Macu (serwis lokalny zatrzymany, żeby baza nie zmieniała się w trakcie):

```bash
ssh pi@<rpi> "mkdir -p ~/panel/data"
sqlite3 data/dziennik.sqlite ".backup data/dziennik-do-rpi.sqlite"     # spójna kopia
rsync -av data/dziennik-do-rpi.sqlite pi@<rpi>:~/panel/data/dziennik.sqlite
rsync -av -s "data/_GoodNotes templates/" "pi@<rpi>:panel/data/_GoodNotes templates/"   # -s: spacja w ścieżce zdalnej
```

Na RPi sprawdź: `sqlite3 ~/panel/data/dziennik.sqlite "select count(*) from days"` (na 2026-10-13: 77 dni).
Potem schemat do najnowszej wersji (no-op, jeśli Mac był aktualny):

```bash
cd ~/panel && .venv/bin/alembic upgrade head && .venv/bin/alembic current
```

**Od tej chwili nie zapisuj dni na Macu** — kopia tam jest archiwalna.

## 3. Hasło

```bash
cd ~/panel && cp deploy/env.example .env && chmod 600 .env && nano .env    # ustaw DZIENNIK_PASSWORD
```

## 4. Usługa systemd

Dostosuj `User=` i ścieżki w `deploy/dziennik.service`, jeśli użytkownik to nie `pi` albo repo nie jest w `~/panel`.

```bash
sudo cp deploy/dziennik.service /etc/systemd/system/dziennik.service
sudo systemctl daemon-reload
sudo systemctl enable --now dziennik
systemctl status dziennik --no-pager
journalctl -u dziennik -n 50 --no-pager
```

## 5. Weryfikacja

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8002/                     # 401 (wymaga hasła)
curl -s -o /dev/null -w "%{http_code}\n" -u kuba:<hasło> http://localhost:8002/history   # 200
hostname -I                                                                          # adres do przeglądarki
```

W przeglądarce na Macu/iPadzie: `http://<adres-rpi>:8002/` → strona dnia, prognoza, statystyki, przycisk
„Dodaj zrzut / zdjęcie” (wklejanie ⌘V działa na komputerze).

Wgrane zrzuty zapisują się w `~/panel/data/screenshots/` (także nieudane — do kalibracji parsera).
Ściągnięcie ich na Maca: `rsync -av pi@<rpi>:~/panel/data/screenshots/ data/screenshots/`.

## Aktualizacja

```bash
cd ~/panel && git pull && uv sync --no-dev --frozen
sqlite3 data/dziennik.sqlite ".backup data/dziennik.sqlite.bak-$(date +%F)"   # przed migracją
.venv/bin/alembic upgrade head
sudo systemctl restart dziennik
```

## Wycofanie

`sudo systemctl stop dziennik`, przywrócenie bazy z `data/dziennik.sqlite.bak-*`, `git checkout <poprzedni commit>`,
`uv sync --no-dev --frozen`, `sudo systemctl start dziennik`.

## Znane ograniczenia / do zrobienia

- Brak OCR na RPi (patrz wyżej) — docelowo Jetson Orin Nano z modelem vision.
- HTTP bez TLS — hasło idzie otwartym tekstem w sieci domowej. Wystarczające w LAN; poza LAN nie wystawiać.
- Brak automatycznego backupu bazy — do dodania (np. cron z `sqlite3 .backup` na dysk sieciowy).
