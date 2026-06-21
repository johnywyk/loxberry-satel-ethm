# SATEL ETHM Bridge dla LoxBerry

Wtyczka cyklicznie odpytuje SATEL ETHM po TCP `7094`, dekoduje odpowiedzi Integry i wysyła do Loxone proste wartości po UDP.

Domyślne ramki:

| Funkcja | Komenda |
|---|---|
| Uzbrojenie partycji | `FE FE 0A D7 EC FE 0D` |
| Alarm w partycji | `FE FE 13 D7 F5 FE 0D` |
| Alarm pożarowy w partycji | `FE FE 14 D7 F6 FE 0D` |
| Pamięć alarmu w partycji | `FE FE 15 D7 F7 FE 0D` |
| Awaria | `FE FE 1B D7 FD FE 0D` |
| Czas na wejście | `FE FE 0E D7 F0 FE 0D` |
| Czas na wyjście >10 s | `FE FE 0F D7 F1 FE 0D` |
| Czas na wyjście <=10 s | `FE FE 10 D7 F2 FE 0D` |

## Instalacja

1. W LoxBerry wejdź w zarządzanie pluginami.
2. Zainstaluj paczkę ZIP pluginu.
3. Otwórz konfigurację pluginu `SATEL ETHM Bridge`.
4. Ustaw:
   - IP ETHM, np. `192.168.1.39`,
   - IP Miniservera,
   - port UDP, np. `7007`,
   - maskę partycji: `1` dla partycji 1.
   - opcjonalnie kod użytkownika SATEL, jeżeli później chcesz używać komend sterujących.
   - opcjonalnie MQTT, jeżeli chcesz publikować te same stany do brokera.
5. Zapisz konfigurację.

Od wersji 0.2.3 restart nie jest wymagany po zwykłej zmianie konfiguracji. Skrypt odczytuje `config.json` przy każdej pętli.

Od wersji 0.5.4 panel i usługa używają bezpiecznej ścieżki konfiguracji w katalogu danych użytkownika:

```text
/opt/loxberry/data/system/satel_ethm/config.json
```

Przy aktualizacji instalator próbuje przenieść stary plik z wcześniejszej lokalizacji:

```text
/opt/loxberry/config/plugins/satel_ethm/config.json
```

Ta nowa ścieżka jest pokazywana w panelu i w logu usługi jako `config_file=...`.

Od wersji 0.5.8 paczka ZIP nie zawiera pliku `config/config.json`, a aktywna konfiguracja jest trzymana w `/opt/loxberry/data/system/satel_ethm/config.json`. Katalogi `config/plugins` i `data/plugins` mogą być czyszczone przez instalator LoxBerry podczas aktualizacji pluginu.

Jeżeli mimo wszystko chcesz ręcznie zrestartować usługę z SSH:

```bash
sudo systemctl restart satel-ethm-bridge.service
```

## Konfiguracja Loxone

W Loxone Config dodaj `Wirtualne wejście UDP`.

Ustaw port:

```text
7007
```

Dodaj wejścia:

| Nazwa | Rozpoznanie |
|---|---|
| SATEL Uzbrojony | `SATEL_ARMED=\v` |
| SATEL Alarm | `SATEL_ALARM=\v` |
| SATEL Alarm pożarowy | `SATEL_FIRE_ALARM=\v` |
| SATEL Pamięć alarmu | `SATEL_ALARM_MEMORY=\v` |
| SATEL Awaria | `SATEL_TROUBLE=\v` |
| Czas na wejście | `SATEL_ENTRY_TIME=\v` |
| Czas na wyjście | `SATEL_EXIT_TIME=\v` |
| Czas na wyjście >10 s | `SATEL_EXIT_TIME_LONG=\v` |
| Czas na wyjście <=10 s | `SATEL_EXIT_TIME_SHORT=\v` |
| SATEL Online | `SATEL_ONLINE=\v` |
| SATEL Error | `SATEL_ERROR=\v` |
| Ostatnie sterowanie OK | `SATEL_CONTROL_OK=\v` |
| Błąd sterowania | `SATEL_CONTROL_ERROR=\v` |
| Kod wyniku sterowania | `SATEL_CONTROL_LAST_CODE=\v` |
| Typ ostatniego sterowania | `SATEL_CONTROL_LAST_ACTION=\v` |
| Licznik sterowania | `SATEL_CONTROL_SEQ=\v` |
| Push connected | `SATEL_PUSH_CONNECTED=\v` |
| Push reconnects | `SATEL_PUSH_RECONNECTS=\v` |
| Awaria AC | `SATEL_TROUBLE_AC=\v` |
| Awaria akumulatora | `SATEL_TROUBLE_BATTERY=\v` |
| Awaria monitoringu | `SATEL_TROUBLE_MONITORING=\v` |
| Dowolne naruszone wejście | `SATEL_ZONE_ANY=\v` |
| Wejście 1 | `SATEL_ZONE_001=\v` |
| Wejście 2 | `SATEL_ZONE_002=\v` |
| Dowolne wejście z bypass/blokadą | `SATEL_ZONE_BYPASS_ANY=\v` |
| Bypass/blokada wejścia 1 | `SATEL_ZONE_001_BYPASS=\v` |
| Dowolne wejście w alarmie | `SATEL_ZONE_ALARM_ANY=\v` |
| Alarm wejścia 1 | `SATEL_ZONE_001_ALARM=\v` |
| Dowolny sabotaż wejścia | `SATEL_ZONE_TAMPER_ANY=\v` |
| Sabotaż wejścia 1 | `SATEL_ZONE_001_TAMPER=\v` |
| Dowolna pamięć alarmu wejścia | `SATEL_ZONE_ALARM_MEMORY_ANY=\v` |
| Pamięć alarmu wejścia 1 | `SATEL_ZONE_001_ALARM_MEMORY=\v` |
| Dowolne aktywne wyjście | `SATEL_OUTPUT_ANY=\v` |
| Wyjście 101 | `SATEL_OUTPUT_101=\v` |
| Temperatura wejścia 17 | `SATEL_TEMP_017=\v` |
| SATEL Uzbrojenie RAW | `SATEL_ARMED_MASK=\v` |
| SATEL Alarm RAW | `SATEL_ALARM_MASK=\v` |
| SATEL Awaria RAW | `SATEL_TROUBLE_MASK=\v` |

Do logiki najczęściej wystarczą:

```text
SATEL_ARMED > 0
SATEL_ALARM > 0
SATEL_TROUBLE > 0
SATEL_ONLINE = 1
SATEL_ERROR = 0
```

## MQTT

Od wersji 0.23.0 MQTT jest opcjonalną warstwą obok UDP. UDP do Loxone zostaje bez zmian, a MQTT można włączyć dla Home Assistant, Node-RED, testów albo innych systemów.

Przykładowe tematy przy `base topic = satel`:

| Wartość | Temat MQTT |
|---|---|
| `SATEL_ARMED` | `satel/status/armed` |
| `SATEL_ALARM` | `satel/status/alarm` |
| `SATEL_ZONE_001` | `satel/zone/001/violated` |
| `SATEL_ZONE_001_BYPASS` | `satel/zone/001/bypass` |
| `SATEL_OUTPUT_101` | `satel/output/101/state` |
| `SATEL_PARTITION_001_EXIT_TIME` | `satel/partition/001/exit_time` |
| `SATEL_WATCHDOG_OK` | `satel/watchdog/ok` |

Sterowanie MQTT jest osobną opcją. Po włączeniu wtyczka subskrybuje:

```text
satel/control/#
```

Przykłady:

```text
topic: satel/control/arm
payload: {"partitions":"all","mode":0}

topic: satel/control/disarm
payload: {"partitions":"all"}

topic: satel/control/output/101/set
payload: 1

topic: satel/control/zone/001/bypass
payload: 1
```

MQTT używa QoS 0 i standardowo flagi `retain`. Sterowanie MQTT włączaj tylko w zaufanej sieci albo z brokerem zabezpieczonym loginem i hasłem.

Od wersji 0.6.8 wtyczka wysyła także informację zwrotną po sterowaniu. `SATEL_CONTROL_LAST_CODE=0` oznacza OK, `255` oznacza, że komenda została przyjęta i będzie przetworzona przez centralę. `SATEL_CONTROL_LAST_ACTION`: `1` arm, `2` force arm, `3` disarm, `4` clear alarm, `5` clear trouble, `6/7` output on/off, `8` toggle, `9/10` bypass/unbypass.

## Wejścia

Od wersji 0.3.0 wtyczka może odczytywać naruszone wejścia SATEL komendą `0x00`.
Od wersji 0.6.7 ta sama lista wejść może być używana także do odczytu statusu bypass/blokady wejść komendą `0x06`.

W panelu wklej listę wejść w formacie:

```text
1;Wiatrołap
2;Salon PIR
3;Garaż
```

Wtyczka będzie wysyłała do Loxone:

```text
SATEL_ZONE_001=0
SATEL_ZONE_002=1
SATEL_ZONE_ANY=1
SATEL_ZONE_001_BYPASS=0
SATEL_ZONE_BYPASS_ANY=0
SATEL_ZONE_001_ALARM=0
SATEL_ZONE_001_TAMPER=0
SATEL_ZONE_001_ALARM_MEMORY=0
```

Nazwy wejść nie są automatycznie pobierane z centrali. Trzeba je wkleić do panelu albo zaimportować z własnej listy.

Od wersji 0.3.2 statusy i wejścia mają osobne interwały:

| Ustawienie | Zalecenie |
|---|---|
| Interwał statusów | `5` sekund |
| Wysyłaj statusy tylko przy zmianie | włączone |
| Pełne odświeżenie statusów | `30` sekund |
| Interwał wejść | `0.5`-`1` sekunda |
| Wysyłaj wejścia tylko przy zmianie | włączone |
| Pełne odświeżenie UDP | `30` sekund |
| Podtrzymanie naruszenia | `3` sekundy |

Od wersji 0.5.1 statusy `SATEL_ARMED`, `SATEL_ALARM`, `SATEL_TROUBLE`, szczegółowe awarie i maski RAW także mogą być wysyłane tylko przy zmianie. Dzięki temu logi LoxBerry i wejścia UDP w Loxone nie są zalewane kompletem zer przy każdym cyklu odczytu.

Od wersji 0.5.2 surowe odpowiedzi ETHM, np. `FE FE 00 ...`, są logowane tylko po włączeniu opcji `Debug: loguj surowe odpowiedzi ETHM` w panelu. Przy normalnej pracy w logu zostają wysyłki UDP, błędy oraz start/stop usługi.

Podtrzymanie naruszenia pomaga przy czujkach PIR, których naruszenie może być krótsze niż interwał odczytu Loxone lub czas reakcji logiki.
Podtrzymanie dotyczy tylko naruszeń `SATEL_ZONE_xxx`, nie statusu bypass/blokady `SATEL_ZONE_xxx_BYPASS`.

Od wersji 0.6.9 wtyczka może odczytywać także alarm wejść `0x02`, sabotaż wejść `0x01` i pamięć alarmu wejść `0x04`. Te statusy są wysyłane dla tej samej listy wejść co naruszenia.

## ETHM i Push + fallback

Od wersji 0.6.0 wtyczka może utrzymywać dodatkowe stałe połączenie TCP z ETHM. Ramki asynchroniczne z centrali są traktowane jako sygnał zmiany i wyzwalają natychmiastowy odczyt statusów, wejść i wyjść. Zwykły polling nadal działa jako fallback po restarcie, zerwaniu połączenia lub utracie pojedynczego zdarzenia. Od wersji 0.6.1 odczyty korzystają z tego samego połączenia TCP co push, żeby nie zajmować drugiej sesji ETHM. Od wersji 0.6.2 ponowne włączenie push w panelu wymusza natychmiastowy reconnect i odczyt.

Do Loxone wysyłane są dodatkowe wartości:

```text
SATEL_PUSH_CONNECTED=0/1
SATEL_PUSH_RECONNECTS=liczba
```

Po zapisaniu listy wejść w panelu można pobrać szablon XML dla Loxone Config. Szablon tworzy jedno wirtualne wejście UDP z komendami statusu `SATEL_ARMED`, `SATEL_ALARM`, `SATEL_TROUBLE`, `SATEL_ONLINE`, `SATEL_ERROR` oraz wejściami `SATEL_ZONE_xxx=\v`.

## Status wyjść i temperatury

Od wersji 0.5.0 wtyczka odczytuje także:

| Funkcja | Komenda SATEL | UDP do Loxone |
|---|---|---|
| Status wyjść | `0x17` | `SATEL_OUTPUT_101=0/1` |
| Temperatura wejścia | `0x7D` | `SATEL_TEMP_017=21.5` |
| Szczegóły awarii | `0x1B` | `SATEL_TROUBLE_AC=0/1` itd. |

Status wyjść korzysta z tej samej listy wyjść, którą wpisujesz w sekcji sterowania. Temperatury trzeba wpisać osobno, bo tylko wybrane wejścia SATEL obsługują odczyt temperatury.

Wtyczka rozbija awarie na dodatkowe sygnały:

```text
SATEL_TROUBLE_AC
SATEL_TROUBLE_BATTERY
SATEL_TROUBLE_MONITORING
SATEL_TROUBLE_PHONE_LINE
SATEL_TROUBLE_RTC
SATEL_TROUBLE_OUT
SATEL_TROUBLE_TECH_ZONE
```

## Wyjścia / Sterowanie z Loxone

Od wersji 0.4.0 wtyczka ma publiczny endpoint sterujący:

```text
http://IP_LOXBERRY/plugins/satel_ethm/control.cgi
```

Endpoint jest zabezpieczany tokenem zapisanym w konfiguracji. Panel może wygenerować XML Wirtualnych Wyjść HTTP dla Loxone Config.
Od wersji 0.6.5 komendy sterujące są przekazywane przez lokalną kolejkę do procesu `satel_ethm_bridge.py`, dzięki czemu przy włączonym push sterowanie używa tego samego połączenia ETHM co odczyty.

Obsługiwane akcje:

| Akcja | URL |
|---|---|
| Uzbrojenie partycji | `?action=arm&partition=1&mode=0&token=...` |
| Wymuszone uzbrojenie | `?action=force_arm&partition=1&mode=0&token=...` |
| Rozbrojenie partycji | `?action=disarm&partition=1&token=...` |
| Kasowanie alarmu | `?action=clear_alarm&partition=1&token=...` |
| Kasowanie pamięci awarii | `?action=clear_trouble&token=...` |
| Wyjście ON | `?action=output_on&output=101&token=...` |
| Wyjście OFF | `?action=output_off&output=101&token=...` |
| Przełącz wyjście | `?action=output_toggle&output=101&token=...` |
| Bypass wejścia | `?action=zone_bypass&zone=1&token=...` |
| Unbypass wejścia | `?action=zone_unbypass&zone=1&token=...` |

Do sterowania wymagany jest kod użytkownika SATEL zapisany w panelu. Najbezpieczniej utworzyć w DLOADX osobnego użytkownika dla LoxBerry/Loxone z dostępem tylko do potrzebnych partycji i wyjść.

Od wersji 0.7.1 eksport XML sterowania tworzy zwykly szablon `VirtualOut` zgodny ukladem z szablonem Loxone, z osobnymi przyciskami uzbrajania dla trybow `mode=0..3` oraz osobnymi przyciskami wymuszonego uzbrojenia dla tych samych trybow.

Od wersji 0.8.0 sterowanie ma potwierdzanie po stanie centrali. Po wyslaniu komendy Loxone dostaje `SATEL_CONTROL_PENDING=1`, a po weryfikacji `SATEL_CONTROL_CONFIRMED=1` albo `SATEL_CONTROL_TIMEOUT=1`. Dla uzbrajania potwierdzeniem jest czuwanie albo aktywny czas na wyjscie, dla rozbrajania brak czuwania i czasu na wyjscie, a dla wyjsc stan bitu z odczytu `0x17`.

Od wersji 0.9.0 wtyczka wysyla statusy per partycja, np. `SATEL_PARTITION_001_ARMED`, `SATEL_PARTITION_001_ALARM`, `SATEL_PARTITION_001_ENTRY_TIME`, `SATEL_PARTITION_001_EXIT_TIME` oraz `SATEL_PARTITION_001_READY_INFERRED`. Doszly tez sygnaly gotowosci wyliczanej (`SATEL_READY_INFERRED`, `SATEL_READY_ZONES_OK`, `SATEL_READY_TAMPER_OK`, `SATEL_READY_TROUBLE_OK`, `SATEL_READY_ALARM_OK`) i diagnostyka (`SATEL_DIAG_UPTIME`, `SATEL_DIAG_LAST_STATUS_OK_AGE`, `SATEL_DIAG_LAST_PUSH_AGE`).

Od wersji 0.10.0 wejscia mozna mapowac do partycji w formacie `numer;nazwa;partycja`, np. `1;Wiatrolap;1`. Dzieki temu wtyczka wysyla agregaty per partycja: `SATEL_PARTITION_001_ZONE_ANY`, `SATEL_PARTITION_001_ZONE_BYPASS_ANY`, `SATEL_PARTITION_001_ZONE_TAMPER_ANY`, `SATEL_PARTITION_001_ZONE_ALARM_ANY` i liczy gotowosc partycji tylko z wejsc przypisanych do tej partycji.

Od wersji 0.11.0 panel potrafi importowac plik XML z DLOADX. Importowane sa tylko rekordy z `enabled="True"` z sekcji `Partitions`, `Zones` i `Outputs`. Import zastepuje listy partycji, wejsc i wyjsc w konfiguracji wtyczki, ale nie rusza adresow ETHM/Loxone, tokenow ani kodu uzytkownika.

Od wersji 0.12.0 panel ma diagnostyke live z ostatnim UDP, odczytem ETHM, komenda sterujaca, ramka push i statusem uslugi. Eksport XML wejsc mozna pobierac jako jeden pelny plik albo w sekcjach: statusy podstawowe, partycje, wejscia, wyjscia i diagnostyka. XML sterowania pozostaje osobnym plikiem.

Od wersji 0.13.0 eksport XML wejsc UDP jest skladany z checkboxow w panelu. Mozna zaznaczyc statusy podstawowe, partycje, wejscia, wyjscia i diagnostyke, a panel wygeneruje jeden plik `VIU_SATEL_ETHM_Wybrane.xml`. Dodany jest takze `VIU_SATEL_ETHM_Lite.xml` z podstawowymi statusami, alarmami, awariami i naruszeniami wejsc bez szczegolow.

Od wersji 0.14.0 dostepny jest tez `VO_SATEL_ETHM_Sterowanie_Lite.xml`. Zawiera tylko podstawowe sterowanie partycjami: uzbrojenie mode 0, wymuszone uzbrojenie mode 0, rozbrojenie, kasowanie alarmu oraz globalne kasowanie pamieci awarii.

Od wersji 0.15.0 sterowanie obsluguje wiele partycji naraz: `partitions=1,2`, `partitions=all` lub `partition_mask=3`. Eksport XML sterowania dodaje komendy `wszystko` dla uzbrajania, wymuszonego uzbrajania, rozbrajania i kasowania alarmu wszystkich skonfigurowanych partycji.

Od wersji 0.16.0 panel ma sekcje serwisowe: test sterowania z przyciskami dla partycji, opcji `wszystko`, wyjsc ON/OFF/toggle i kasowania awarii oraz backup/restore konfiguracji `config.json`.

Od wersji 0.17.0 import DLOADX ustawia automatycznie `partition_mask` z aktywnych partycji. Maska jest nadal uzywana dla zbiorczych statusow `SATEL_ARMED`, `SATEL_ALARM`, `SATEL_ENTRY_TIME` itd.; statusy per partycja korzystaja z listy partycji. Panel testowania sterowania pokazuje opisy trybow uzbrojenia `mode 0..3`.

Od wersji 0.18.0 import DLOADX jest przeniesiony wysoko w panelu, bezposrednio pod sekcje Loxone UDP. Autor w metadanych pluginu: Jasiek Wykidajło / OpenAI.

Od wersji 0.19.0 panel jest uporzadkowany w rozwijane sekcje `<details>`. ETHM i push sa polaczone w jedna sekcje, wejscia maja uproszczona konfiguracje, komendy odczytu przeniesiono do sekcji zaawansowanej, a wyjscia i sterowanie Loxone sa w jednej sekcji. Nazewnictwo blokad wejsc SATEL jest opisane jako bypass/blokady.

Od wersji 0.19.1 panel startuje zwiniety poza sekcjami ETHM oraz Loxone UDP.

Od wersji 0.19.2 zmieniono autora w metadanych pluginu na Jasiek Wykidajło / OpenAI.

Od wersji 0.20.0 dodano obsluge opcji `Kodowanie Integracji` ETHM. Po zaznaczeniu checkboxa w sekcji ETHM trzeba podac klucz integracji z DLOADX. Bez tej opcji wtyczka dziala jak dotychczas w trybie nieszyfrowanym.

Od wersji 0.21.0 sterowanie po odpowiedzi ETHM `EF 00` lub `EF FF` zwalnia kolejke od razu. Potwierdzenie stanu odbywa sie przez kolejne odczyty statusu, dzieki czemu komenda rozbrojenia moze przerwac czas na wyjscie bez czekania na timeout poprzedniego uzbrojenia. Stary tryb blokujacego czekania zostal jako opcja diagnostyczna.

Od wersji 0.22.0 panel diagnostyczny live pokazuje skrot stanu, ostatnie wartosci UDP oraz historie zdarzen z runtime. Dodano autotest konfiguracji, watchdog komunikacji (`SATEL_WATCHDOG_OK`, `SATEL_WATCHDOG_STATUS_OK`, `SATEL_WATCHDOG_PUSH_OK`) oraz profile sterowania eksportowane do XML, np. `Wyjscie z domu;arm;all;0;tak`.

Od wersji 0.22.1 XML Lite wejsc UDP zawiera takze czas na wejscie i czas na wyjscie: `SATEL_ENTRY_TIME`, `SATEL_EXIT_TIME`, `SATEL_EXIT_TIME_LONG`, `SATEL_EXIT_TIME_SHORT` oraz odpowiedniki per partycja.

Od wersji 0.23.0 dodano opcjonalne MQTT: publikowanie statusow, wejsc, wyjsc, temperatur, awarii, diagnostyki i watchdogow oraz opcjonalne sterowanie przez `satel/control/#`. Panel ma sekcje MQTT i pokazuje diagnostyke ostatniej publikacji oraz polaczenia sterujacego.


## Testy w panelu

Od wersji 0.7.0 panel ma bezpieczne testy diagnostyczne:

| Test | Co robi |
|---|---|
| Test połączenia ETHM | wysyła odczyt uzbrojenia i pokazuje odpowiedź |
| Test statusów | odpytuje podstawowe statusy partycji |
| Test wejść | odpytuje naruszenia, bypass, sabotaż, alarm i pamięć alarmu wejść |
| Test UDP do Loxone | wysyła `SATEL_TEST=1` na skonfigurowany adres Miniservera |

Testy nie uzbrajają i nie rozbrajają alarmu.

## Logi

Log główny:

```text
/opt/loxberry/log/plugins/satel_ethm/satel_ethm_bridge.log
```

Log sterowania:

```text
/opt/loxberry/log/plugins/satel_ethm/satel_ethm_control.log
```

Standardowe wyjście usługi:

```text
/opt/loxberry/log/plugins/satel_ethm/stdout.log
```

## Ważne

Odczyt statusów `0x0A`, `0x13` i `0x1B` nie używa kodu użytkownika. Pole kodu w panelu jest przygotowane pod przyszłe komendy sterujące, np. uzbrajanie lub rozbrajanie.

W polach komend można użyć placeholderów:

```text
{USER_CODE_ASCII}
{USER_CODE_BCD}
```

Przy komendach SATEL zawierających dane trzeba podać poprawną końcówkę CRC całej ramki.

Jeżeli `SATEL_TROUBLE` nie pokazuje awarii, a wiesz że awaria jest aktywna, można testowo sprawdzić inne komendy statusowe. Domyślna komenda awarii to:

```text
FE FE 1B D7 FD FE 0D
```

Komenda `0x1A` nie jest awarią w tej integracji - zwraca zegar centrali, np.:

```text
FE FE 1A 20 26 06 20 16 54 18 ...
```

czyli datę i godzinę `2026-06-20 16:54:18`.
