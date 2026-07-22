# SysScope

Monitorização de spin-up dos discos num media server Debian. Deteta quando cada
HDD acorda e atribui o processo/container/ficheiro responsável ("flight
recorder"), com dashboard web.

## Instalação

    ./install.sh

Dashboard: http://127.0.0.1:8787

## Serviços

- `sysscope-collector.service` (root) — recolha e tracing
- `sysscope-web.service` (utilizador) — dashboard

## Logs

    journalctl -u sysscope-collector -f
    journalctl -u sysscope-web -f

## Testes

    python -m pytest
