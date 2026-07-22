# SysScope

Monitorização de spin-up dos discos num media server Debian. Deteta quando cada
HDD acorda e atribui o processo/container/ficheiro responsável através de
varrimento periódico de `/proc/*/fd` ("flight recorder"), com dashboard web.

## Instalação

    ./install.sh

Dashboard: http://127.0.0.1:8787

## Serviços

- `sysscope-collector.service` (root) — recolha e tracing
- `sysscope-web.service` (utilizador) — dashboard

## Logs

    journalctl -u sysscope-collector -f
    journalctl -u sysscope-web -f

## Limitações

Os discos-alvo são FUSE/NTFS (`ntfs-3g`), pelo que não são observáveis por
`fatrace`/fanotify (fanotify não suporta filesystems FUSE). A atribuição usa
varrimento de `/proc/*/fd` em vez disso — pode falhar acessos ultra-rápidos
que abrem e fecham o ficheiro entre dois varrimentos consecutivos.

## Testes

    python -m pytest
