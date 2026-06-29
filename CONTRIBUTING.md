# Jak zgłaszać problemy i współtworzyć projekt

## Zgłaszanie błędów

Przed zgłoszeniem sprawdź:
1. Czy bridge jest uruchomiony: `satel_ethm_service.sh status`
2. Logi: `tail -50 /opt/loxberry/log/plugins/satel_ethm/satel_ethm_bridge.log`
3. Połączenie TCP z ETHM-1: `telnet <IP> 7094`

Otwierając issue podaj:
- Wersję pluginu (z `plugin.cfg`)
- Wersję LoxBerry
- Model centrali Satel i firmware ETHM-1
- Relevantne linie z logu

## Pull Requesty

1. Forkuj repozytorium
2. Stwórz branch: `git checkout -b feature/opis`
3. Testuj na prawdziwej centrali jeśli możliwe
4. Opisz zmiany w PR i zaktualizuj `CHANGELOG.md`

## Struktura kodu

```
bin/satel_ethm_bridge.py    # Główny proces - protokół Satel, MQTT, UDP
bin/satel_ethm_service.sh   # Wrapper start/stop dla LoxBerry
daemon/satel_ethm           # Skrypt daemona rejestrowany w LoxBerry
webfrontend/htmlauth/index.cgi  # Panel konfiguracyjny (Python CGI)
webfrontend/html/control.cgi    # API sterowania (wywoływane przez panel)
postinstall.sh              # Uruchamiany po instalacji
preupdate.sh                # Uruchamiany przed upgrade (backup config)
plugin.cfg                  # Metadane pluginu LoxBerry
```
