# Contributing

Dzieki za chec pomocy przy SATEL ETHM Bridge.

## Jak testowac

1. Sforkuj repozytorium.
2. Zrob branch z opisowa nazwa, np. `fix-control-queue` albo `feature-events-log`.
3. Uruchom lokalne testy:

```bash
python3 -m py_compile bin/satel_ethm_bridge.py webfrontend/htmlauth/index.cgi webfrontend/html/control.cgi
python3 scripts/build_plugin_zip.py
```

4. Zainstaluj ZIP z katalogu `dist/` na testowym LoxBerry.
5. Opisz w pull requescie:
   - wersje LoxBerry,
   - model centrali SATEL,
   - model ETHM,
   - czy wlaczone jest `Kodowanie Integracji`,
   - co dokladnie bylo testowane.

## Zasady zmian

- Nie dodawaj do repo prywatnych konfiguracji, tokenow, kodow SATEL ani adresow IP z realnej instalacji.
- Nie dodawaj pliku aktywnej konfiguracji `config.json`.
- Nie zmieniaj domyslnie sciezki konfiguracji:

```text
/opt/loxberry/data/system/satel_ethm/config.json
```

- Przy zmianach protokolu ETHM dodaj log diagnostyczny albo opis testu.
- Przy zmianach XML sprawdz import w Loxone Config.
- Przy zmianach sterowania opisz, czy komenda dotyczy partycji, wyjsc, bypass/blokad wejsc czy kasowania alarmu.

## Styl

- Kod Pythona ma pozostac bez dodatkowych zewnetrznych zaleznosci poza opcjonalnym `cryptography` dla kodowania ETHM.
- Panel LoxBerry jest prostym CGI, bez frameworka.
- Komunikaty w panelu piszemy po polsku.

