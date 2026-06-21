# Publikacja projektu na GitHubie

## 1. Utworz repozytorium

Proponowana nazwa:

```text
loxberry-satel-ethm
```

Opis:

```text
Unofficial LoxBerry plugin for SATEL ETHM / INTEGRA integration with Loxone
```

Widocznosc:

```text
Public
```

Licencja:

```text
MIT
```

## 2. Wrzuc kod

Najprosciej z komputera, na ktorym masz katalog projektu:

```bash
git init
git add .
git commit -m "Initial public testing release"
git branch -M main
git remote add origin https://github.com/TWOJ_LOGIN/loxberry-satel-ethm.git
git push -u origin main
```

Nie dodawaj do repo:

- `config.json`,
- tokenow sterowania,
- kodu uzytkownika SATEL,
- klucza `Kodowanie Integracji`,
- prywatnych logow z realnej instalacji.

## 3. Sprawdz GitHub Actions

Po pushu workflow `Build plugin` powinien:

1. skompilowac skrypty Pythona,
2. zbudowac ZIP pluginu,
3. dodac ZIP jako artifact.

## 4. Utworz pierwszy Release

Proponowany tag:

```text
v0.22.0
```

Tytul:

```text
SATEL ETHM Bridge 0.22.0 - community testing
```

Opis:

```text
Pierwsza publiczna wersja testowa.

Najwazniejsze funkcje:
- odczyt uzbrojenia, alarmu, awarii i czasow wejscia/wyjscia,
- odczyt naruszen wejsc, bypass/blokad, sabotażu, alarmu wejsc,
- odczyt statusu wyjsc,
- push-triggered polling + fallback polling,
- sterowanie HTTP z Loxone,
- import nazw z DLOADX XML,
- eksport XML dla Loxone Config,
- panel diagnostyczny live, autotest i watchdog.

Uwaga: to nieoficjalna integracja community. Testowac ostroznie.
```

Do Release dolacz plik:

```text
loxberry-satel-ethm-0.22.0.zip
```

## 5. Informacja dla testerow

Popros testerow, zeby w issue podawali:

- model centrali,
- model ETHM,
- wersje LoxBerry,
- wersje Loxone Config,
- czy maja wlaczone `Kodowanie Integracji`,
- fragment logu po usunieciu sekretow.

## 6. Uwaga o znakach towarowych

Projekt jest nieoficjalny. Nazwy SATEL, ETHM, INTEGRA, Loxone i LoxBerry
sa uzywane tylko opisowo. Przy publicznej dystrybucji upewnij sie, ze ikony
lub logo w paczce moga byc redystrybuowane. W razie watpliwosci zastap je
neutralna ikona community.

