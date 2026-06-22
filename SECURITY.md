# Security Policy

## Supported versions

Projekt jest rozwijany eksperymentalnie. Do testow spolecznosciowych uzywaj
najnowszej wersji z sekcji Releases.

## Reporting a vulnerability

Nie otwieraj publicznego issue, jezeli problem ujawnia:

- kod uzytkownika SATEL,
- token sterowania LoxBerry,
- klucz `Kodowanie Integracji`,
- sposob nieautoryzowanego sterowania alarmem,
- prywatne logi z realnymi adresami IP i kodami.

Najbezpieczniej zglosic problem prywatnie wlascicielowi repozytorium, a w publicznym
issue opisac tylko objaw bez sekretow.

## Operational recommendations

- Uzyj osobnego uzytkownika SATEL dla LoxBerry/Loxone.
- Nadaj mu tylko minimalne potrzebne uprawnienia.
- Nie wystawiaj `control.cgi` do internetu.
- Ustaw `allowed_control_ips` na adres IP Miniservera Loxone, aby `control.cgi`
  przyjmowal komendy tylko z tego hosta.
- Nie wystawiaj LoxBerry, MQTT ani endpointu sterowania SATEL bezposrednio do
  internetu; do dostepu zdalnego uzywaj VPN.
- Token sterowania traktuj jak haslo.
- Przy publikowaniu logow usun adresy IP, tokeny, kody i klucze integracji.
