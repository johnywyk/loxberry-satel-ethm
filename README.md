# SATEL ETHM Bridge – LoxBerry Plugin

Integracja centrali alarmowej **Satel INTEGRA** z **LoxBerry** i **Loxone Miniserver** przez moduł **ETHM-1 / ETHM-1 Plus**.

> Plugin oryginalnie stworzony przez [@johnywyk](https://github.com/johnywyk/loxberry-satel-ethm).  
> Wersja 0.25.x — rozszerzona i dostosowana do LoxBerry 3.x.

---

## Możliwości

- Odczyt stanów **stref** (naruszenie, alarm, tamper, bypass, maskowanie)
- Odczyt stanów **partycji** (uzbrojenie, alarm, alarm pożarowy)
- Odczyt stanów **wyjść**
- Odczyt **temperatur** z czujników INTEGRA (opcjonalne)
- **Sterowanie** z Loxone: uzbrajanie/rozbrajanie, sterowanie wyjściami
- Wysyłanie danych do Loxone przez **UDP** (Virtual UDP Input)
- Publikowanie stanów na **MQTT** (retain, auto-wykrywanie brokera LoxBerry)
- **Heartbeat** co 30s – Loxone wykryje brak komunikacji
- Obsługa **szyfrowania** ETHM-1 Plus
- Import nazw stref i partycji z pliku **DLOADX XML**
- Generowanie gotowego pliku **Loxone VIU/VO XML** do importu
- Panel webowy z podglądem **live statusu** i logów
- **Automatyczny backup** konfiguracji przy każdym upgrade

---

## Wymagania

| Komponent | Wersja |
|---|---|
| LoxBerry | ≥ 3.0 |
| Python | ≥ 3.9 |
| ETHM-1 / ETHM-1 Plus | firmware ≥ 1.07 / 2.00 |
| INTEGRA | firmware ≥ 1.12 |
| Loxone Miniserver | firmware ≥ 12.0 (MQTT) |

---

## Instalacja

### Przez interfejs LoxBerry

1. Pobierz najnowszy plik `.zip` z [Releases](../../releases)
2. W LoxBerry: **Plugins → Install Plugin**
3. Wgraj plik ZIP
4. Po instalacji przejdź do **Plugins → SATEL ETHM Bridge**

### Weryfikacja połączenia z ETHM-1

Przed uruchomieniem bridge sprawdź połączenie:

```bash
cd /opt/loxberry/bin/plugins/satel_ethm
python3 satel_ethm_bridge.py --test
```

---

## Konfiguracja ETHM-1

W oprogramowaniu **DLOADX** (konfiguracja centrali Satel):

1. Moduł ETHM-1 → **Ustawienia sieci** → wpisz adres IP i maskę
2. Włącz opcję **Integracja** (port domyślny: **7094**)
3. Wyłącz szyfrowanie lub wpisz klucz integracji (opcjonalne)
4. Zapisz i zrestartuj moduł

> ⚠️ Użyj portu **7094** (protokół integracji), NIE 7090 (GUARDX).

---

## Konfiguracja w panelu LoxBerry

Panel dostępny pod: `http://<IP-LoxBerry>/admin/plugins/satel_ethm/`

### Zakładka Połączenie

| Pole | Opis |
|---|---|
| Host ETHM-1 | Adres IP modułu ETHM-1 |
| Port | `7094` (domyślnie) |
| Klucz integracji | Tylko jeśli włączone szyfrowanie w DLOADX |
| Kod użytkownika | Do sterowania (musi mieć prawo GUARDX) |

### Zakładka Loxone

| Pole | Opis |
|---|---|
| Host Loxone | Adres IP Miniservera |
| Port UDP | `7007` (domyślnie) |

### Zakładka MQTT

Jeśli broker MQTT jest skonfigurowany w systemie LoxBerry (`System → MQTT`), dane wypełnią się automatycznie. Możesz też wpisać ręcznie.

| Pole | Opis |
|---|---|
| Host | IP brokera (puste = auto z LoxBerry) |
| Port | `1883` (domyślnie) |
| Prefix tematów | `satel` (domyślnie) |

---

## Tematy MQTT

### Odczyt (bridge → Loxone/MQTT)

```
satel/zones/<N>/violated          0 / 1
satel/zones/<N>/alarm             0 / 1
satel/zones/<N>/tamper            0 / 1
satel/zones/<N>/bypass            0 / 1
satel/zones/<N>/masked            0 / 1

satel/partitions/<N>/armed        0 / 1
satel/partitions/<N>/alarm        0 / 1
satel/partitions/<N>/fire_alarm   0 / 1
satel/partitions/<N>/entry_time   0 / 1
satel/partitions/<N>/exit_time    0 / 1

satel/outputs/<N>/state           0 / 1

satel/status                      connected / disconnected
satel/SATEL_HEARTBEAT             unix timestamp % 1000000
satel/SATEL_UPTIME                sekundy od uruchomienia
```

### Sterowanie (Loxone → bridge)

```
satel/cmd/arm/<partycja>          0=pełne / 1=stay / 2=stay_delay0 / 3=natychmiastowe
satel/cmd/disarm/<partycja>       (dowolna wartość)
satel/cmd/clear_alarm/<partycja>  (dowolna wartość)
satel/cmd/output/<N>/on           (dowolna wartość)
satel/cmd/output/<N>/off          (dowolna wartość)
```

---

## Heartbeat w Loxone

Bridge wysyła co 30 sekund wartość `SATEL_HEARTBEAT` (przez UDP i MQTT).  
Skonfiguruj w Loxone Config blok **Watchdog**:

```
Wirtualne Wejście UDP "SATEL_HEARTBEAT"
    → Watchdog (timeout: 90s)
        → [alarm braku komunikacji z centralą]
```

---

## Struktura plików po instalacji

```
/opt/loxberry/
├── bin/plugins/satel_ethm/
│   ├── satel_ethm_bridge.py      ← główny proces bridge
│   └── satel_ethm_service.sh     ← start/stop/restart/status
├── config/plugins/satel_ethm/
│   ├── config.json               ← konfiguracja (backupowana przez LoxBerry)
│   └── runtime.json              ← stan live (generowany przez bridge)
├── log/plugins/satel_ethm/
│   ├── satel_ethm_bridge.log     ← log bridge
│   └── stdout.log                ← stdout/stderr
└── webfrontend/htmlauth/plugins/satel_ethm/
    └── index.cgi                 ← panel konfiguracyjny
```

---

## Zarządzanie usługą

```bash
# Status
/opt/loxberry/bin/plugins/satel_ethm/satel_ethm_service.sh status

# Start / Stop / Restart
/opt/loxberry/bin/plugins/satel_ethm/satel_ethm_service.sh start
/opt/loxberry/bin/plugins/satel_ethm/satel_ethm_service.sh stop
/opt/loxberry/bin/plugins/satel_ethm/satel_ethm_service.sh restart

# Logi na żywo
tail -f /opt/loxberry/log/plugins/satel_ethm/satel_ethm_bridge.log
```

---

## Rozwiązywanie problemów

### Bridge łączy się ale zaraz się rozłącza
- Sprawdź czy w DLOADX masz wybrany port **7094** (integracja), nie 7090 (GUARDX)
- Sprawdź czy opcja **Integracja** jest włączona w ustawieniach ETHM-1

### MQTT nie działa (rc=5)
- Broker wymaga autoryzacji — wpisz login i hasło w zakładce MQTT
- Sprawdź czy broker jest dostępny: `mosquitto_sub -h <IP> -t "test" -v`

### Konfiguracja ginie po upgrade
- Od v0.25.0 config jest w `/opt/loxberry/config/plugins/satel_ethm/`
- Jest automatycznie backupowany przez `preupdate.sh` przed każdym upgrade
- Możesz też ręcznie: `cp /opt/loxberry/config/plugins/satel_ethm/config.json ~/config_backup.json`

### Sprawdzenie połączenia TCP z ETHM-1
```bash
telnet <IP_ETHM1> 7094
# lub
python3 -c "import socket; s=socket.create_connection(('<IP>',7094),3); print('OK'); s.close()"
```

---

## Zmiany względem v0.24.0

Zobacz [CHANGELOG.md](CHANGELOG.md).

---

## Licencja

MIT License — wolne do użytku prywatnego i komercyjnego.

Autorzy:
- [@johnywyk](https://github.com/johnywyk/loxberry-satel-ethm) — oryginalny plugin v0.24.0
- Rozszerzenia v0.25.x — LoxBerry Community
