# Changelog

Format oparty na [Keep a Changelog](https://keepachangelog.com/pl/1.0.0/).

---

## [0.25.13] - 2026-06-27

### Naprawione
- Obsługa odpowiedzi `Busy!` od ETHM-1 — gdy inny klient (DLOADX, GUARDX, inny bridge) trzyma polaczenie, bridge loguje czytelny komunikat zamiast ciaglego `ETHM push connection closed`
- Spójnosc `config_file_path()` — szuka config w tej samej kolejnosci co `load_config()` (nowa lokalizacja → legacy fallback)
- Zaktualizowano `VERSION` w `satel_ethm_bridge.py` do `0.25.13`

### Wazna uwaga
Jesli push ciagle sie rozlacza — sprawdz czy nie ma innego procesu trzymajacego polaczenie z ETHM-1:
```bash
ss -tnp | grep 7094
pkill -f satel_daemon.py  # jesli jest stary plugin 'satel'
```

---

## [0.25.12] - 2026-06-27

### Naprawione
- Wyeliminowano konflikt TCP miedzy poll a push connection
- ETHM-1 obsluguje tylko jedno polaczenie TCP naraz — gdy push_enabled i push_sock=None, poll jest pomijany zamiast tworzyc konkurencyjne polaczenie TCP

---

## [0.25.11] - 2026-06-27

### Naprawione
- `SyntaxError` w `satel_ethm_bridge.py` — keepalive byl blędnie umieszczony wewnatrz bloku `try/except`
- Literówka `DEAMON=yes` → `DAEMON=yes` w `plugin.cfg` — LoxBerry nie rejestrował daemona

---

## [0.25.10] - 2026-06-27

### Dodane
- Keepalive CMD `0x7F` wysylany co 5s przez push socket — zapobiega zamykaniu polaczenia przez ETHM-1
- Parametr `push_keepalive_interval` (domyslnie 5.0s) w `config.json`

---

## [0.25.9] - 2026-06-27

### Naprawione
- `postroot.sh` tworzy skrypt daemona w `/opt/loxberry/system/daemons/plugins/satel_ethm/`

---

## [0.25.8] - 2026-06-27

### Naprawione
- Status serwisu wykrywa dzialajacy process przez `pgrep` gdy brak PID file
- Przyciski Start/Stop/Restart dzialaja poprawnie (naprawiony blad sudo)
- `Permission denied` przy zapisie `config.json` — cala logika przeniesiona do `postroot.sh`

---

## [0.25.7] - 2026-06-27

### Dodane
- `preinstall.sh` — tworzy katalogi z wlasciwymi uprawnieniami jako root przed instalacja

---

## [0.25.6] - 2026-06-27

### Dodane
- Live log (ostatnie 80 linii) w sekcji Diagnostyka z auto-odswiezaniem co 5s
- Przyciski Start/Stop/Restart w panelu webowym
- `postroot.sh` — wpis sudoers tworzony jako root

---

## [0.25.5] - 2026-06-25

### Naprawione
- `Permission denied` przy tworzeniu `/etc/sudoers.d/satel_ethm`

---

## [0.25.4] - 2026-06-25

### Dodane
- Przyciski Start/Stop/Restart w sekcji Status
- Wpis `/etc/sudoers.d/satel_ethm` — loxberry moze zarzadzac serwisem bez hasla

---

## [0.25.3] - 2026-06-25

### Naprawione
- `Error 500` — apostrofy w JavaScript wewnatrz f-stringa Pythona powodowaly `SyntaxError`

---

## [0.25.2] - 2026-06-25

### Dodane
- Live log w sekcji Diagnostyka (pierwsza wersja)
- `control.cgi` — poprawiona struktura katalogow w ZIP

---

## [0.25.1] - 2026-06-24

### Naprawione
- `daemon/satel_ethm` — usunieto hardcoded `/opt/loxberry`, uzywa `${LBHOMEDIR}`

---

## [0.25.0] - 2026-06-24

### Dodane
- **Heartbeat** — `SATEL_HEARTBEAT` i `SATEL_UPTIME` wysylane co 30s do Loxone i MQTT
- **Auto-wykrywanie MQTT** — credentials z systemu LoxBerry (`/opt/loxberry/config/system/mqtt.json`)
- **`preupdate.sh`** — backup `config.json` przed kazdym upgrade
- **Daemon w systemie LoxBerry** — `plugin.cfg [DAEMON]`, auto-start przy restarcie systemu
- **`poll_zones: true`** domyslnie — strefy monitorowane od razu po instalacji
- **PID file** przeniesiony z `/var/run/` do `/opt/loxberry/log/plugins/satel_ethm/`

### Zmienione
- Config przeniesiony do `/opt/loxberry/config/plugins/satel_ethm/` (standardowa lokalizacja LoxBerry, obejmowana przez backup systemu)
- Migracja automatyczna ze starej lokalizacji `data/system/`

---

## [0.24.0] - 2026-06-20

### Pierwsza wersja publiczna
- Pelna implementacja protokolu binarnego Satel INTEGRA (ETHM-1 Plus, port 7094)
- Tryb push (natychmiastowe powiadomienia) + poll (cykliczne odpytywanie)
- Obsluga szyfrowania ETHM-1 Plus
- Wysylanie danych do Loxone przez UDP (Virtual UDP Input)
- Publikowanie stanow na MQTT
- Panel webowy z importem DLOADX XML i generowaniem Loxone VIU/VO XML
- Sterowanie: uzbrajanie, rozbrajanie, wyjscia
