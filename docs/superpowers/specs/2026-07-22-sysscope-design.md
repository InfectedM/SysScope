# SysScope — Documento de Desenho

**Data:** 2026-07-22
**Autor:** Leandro (InfectedM) + Claude
**Estado:** Aprovado para planeamento

---

## 1. Propósito

Ferramenta com GUI para **monitorização profunda e ampla** de uma máquina Debian 13
(media server): serviços, aplicações, wake-ups, utilização de discos, rede,
CPU/RAM/temperaturas.

O **problema motivador concreto**: os discos mecânicos por vezes fazem *spin-up*
(acordam) sem razão óbvia. O objetivo prático número um é **identificar o processo,
container e ficheiro responsáveis por cada spin-up**, mesmo quando acontecem de
madrugada sem ninguém a observar (funcionalidade de "flight recorder").

## 2. Contexto da máquina (levantado em 2026-07-22)

- **SO:** Debian GNU/Linux 13 (trixie), kernel 6.12.95, KDE/X11, Python 3.13.5.
- **Acesso:** `sudo` sem password disponível.
- **Discos mecânicos (fazem spin-up, `ROTA=1`):**
  - `sdb` (2.7T Toshiba MQ03UBB300, USB) → `/media/HDD3TB` (`sdb2`)
  - `sdc` (3.6T PURZ) → `/media/HDD4TB` (`sdc1`)
  - `sdd` (1.8T WD WD20SDRW) → `/mnt/HDD2TB` (`sdd1`)
  - `sde` (7.3T) → `/media/HDD8TB` (`sde1`)
- **Discos de estado sólido (não relevantes p/ spin-up):** `sda` (Samsung 850 EVO), `nvme0n1` (SK hynix).
- **Serviços em Docker:** radarr, sonarr, bazarr, jackett, jellyfin, seerr,
  flaresolverr, portainer, subtranslator-*, libretranslate. Suspeitos habituais
  de acordar discos.
- **Ferramentas de tracing:** nenhuma instalada ainda; todas disponíveis via `apt`.

## 3. Decisões tomadas

| Tema | Decisão |
|---|---|
| Foco | Dashboard amplo (todos os subsistemas), com o painel de spin-up como peça central |
| Interface | Dashboard web local (FastAPI + frontend servido em `127.0.0.1:8787`) |
| Tracing | Instalar ferramentas de kernel (fatrace, bpftrace, etc.); coletor corre como root |
| Deploy | Serviços systemd nativos no host (não Docker) |
| Nome | SysScope |
| Local | `/home/infectedserver/sysscope`, git local (privado) |

## 4. Arquitetura

Dois serviços systemd com separação de privilégios, a comunicar via uma base de
dados SQLite em modo WAL.

```
┌─────────────────────────────────────┐        ┌──────────────────────────────┐
│  sysscope-collector.service (ROOT)   │        │  sysscope-web.service (user)  │
│                                       │  SQLite │                              │
│  • DiskCollector                      │  (WAL) │  • FastAPI + uvicorn          │
│  • IoAttributionCollector             │ ──────▶│  • lê a BD (só leitura)       │
│  • ProcessCollector                   │ /var/  │  • WebSocket → browser        │
│  • NetworkCollector                   │ lib/   │  • REST p/ histórico          │
│  • ServiceCollector (systemd+docker)  │sysscope│  • serve frontend estático    │
│  • WakeupCollector                    │ .db    │  • bind 127.0.0.1:8787        │
│  • SystemCollector                    │        │                              │
└─────────────────────────────────────┘        └──────────────────────────────┘
```

- **Coletor (root):** único processo com privilégios; corre os tracers e sonda
  `/proc`, `/sys`. Escreve na BD. Não expõe nada na rede.
- **Web (utilizador):** só leitura da BD (WAL permite leitura concorrente).
  Serve o dashboard e faz push de snapshots ao vivo via WebSocket (~1–2 s).
  Consultas de histórico vão diretas à BD. Exposto apenas em localhost.
- **IPC:** a própria BD SQLite. Sem sockets custom.

### Estrutura de pastas (proposta)

```
sysscope/
  sysscope/                 # pacote Python
    collector/
      __init__.py
      main.py               # loop principal + agendamento dos coletores
      disk.py               # estado de energia + diskstats
      io_attribution.py     # fatrace + bpftrace, correlação, flight recorder
      process.py
      network.py
      services.py           # systemd + docker
      wakeups.py
      system.py
      db.py                 # esquema SQLite, escrita, rollups, retenção
    web/
      __init__.py
      app.py                # FastAPI: REST + WebSocket
      static/               # index.html, css, js, uPlot, fonte Outfit
    common/
      models.py             # dataclasses partilhadas
      config.py             # config (discos, mounts, portas, retenção)
  install.sh                # apt install + venv + systemd units
  systemd/
    sysscope-collector.service
    sysscope-web.service
  tests/
  docs/
  README.md
```

## 5. Atribuição de spin-up (peça central)

Combina três sinais e correlaciona-os por PID e tempo:

| Sinal | Fonte | Fornece |
|---|---|---|
| Transição de energia | `hdparm -C /dev/sdX` (fallback `smartctl -n standby -i`) | Timestamp exato de `standby → active` = o spin-up. Comandos **standby-safe** (não acordam o disco). |
| I/O de bloco real | `bpftrace` (script estilo *biosnoop*) | PID + comm + dispositivo + setor + R/W do I/O que *realmente* tocou no prato |
| Acesso a ficheiro | `fatrace` filtrado aos mounts dos HDD | Legível: `jellyfin(4821): open /media/HDD8TB/Movies/X.mkv` |

- **PID → container:** ler `/proc/PID/cgroup` → nome do container Docker.
- **Flight recorder:** ao detetar uma transição `standby → active`, persistir a
  janela de eventos atribuídos em redor (ex.: 5 s antes / 5 s depois) como um
  "incidente de spin-up" consultável.
- **Fallback USB:** `sdb` é USB (bridge Toshiba) e outros podem ser enclosures
  USB onde `hdparm -C` pode não passar SAT. Nesses casos, inferir spin-up por
  atividade em `/sys/block/sdX/stat` após período longo de inatividade, marcado
  como transição "inferida" (menor confiança) e confirmada pelo stream de I/O.

## 6. Regra de ouro — monitorizar sem acordar os discos

Constraint crítica e não-negociável. O coletor **nunca** faz I/O nos mounts dos
HDD. Fontes permitidas (não tocam no prato):

- `/proc/diskstats`, `/sys/block/*/stat` — contadores, não acedem ao disco.
- `hdparm -C` — comando CHECK POWER MODE, standby-safe.
- `smartctl -n standby` — aborta se o disco estiver adormecido.
- `fatrace`/`bpftrace` — passivos, observam I/O existente sem o gerar.

**Proibido:** `updatedb`, `stat`/`ls`/leitura de ficheiros nos mounts, SMART
completo em disco adormecido, `df` que force acesso, etc.

## 7. Painéis do dashboard

1. **Discos** ⭐ — por HDD: estado (adormecido/idle/ativo), throughput R/W ao
   vivo, e **timeline de incidentes de spin-up com culpado atribuído**
   (processo + container + ficheiro + confirmação de bloco).
2. **Serviços** — units systemd (ativas/falhadas, CPU/mem via cgroup) +
   containers Docker com **BlockIO por container** (correlaciona container ↔ disco).
3. **Wake-ups** — timers systemd (`systemctl list-timers`), cron jobs, wakeups de
   CPU por processo (via `powertop`), RTC wakealarm.
4. **Rede** — throughput por interface (`/proc/net/dev`) + ligações ativas com
   processo (`ss -tunp`).
5. **Processos** — top por CPU / memória / I/O (`/proc/*/stat`, `/proc/*/io`).
6. **Sistema** — CPU, load, RAM, swap, temperaturas (`/sys/class/hwmon`), uptime.

## 8. Persistência e retenção

- BD SQLite em `/var/lib/sysscope/sysscope.db` (WAL).
- **Métricas contínuas:** guardadas em *rollups* de baixa resolução (ex.: médias
  por 10 s / 1 min) para manter a BD pequena.
- **Incidentes de spin-up:** guardam a janela raw completa de eventos atribuídos.
- **Retenção configurável** (predefinição 14 dias); tarefa de limpeza periódica.
- Volume do fatrace controlado: eventos raw só persistem à volta de incidentes;
  fora disso agregam-se por (processo, disco) em baldes temporais.

## 9. Stack técnica

- **Backend:** Python 3.13, FastAPI + uvicorn, `sqlite3` (stdlib), `psutil`,
  wrappers de subprocess para os tracers.
- **Frontend:** HTML/CSS/JS vanilla (sem build step); gráficos de série temporal
  com **uPlot** (vendorizado localmente); fonte **Outfit**; tema **violeta** e
  layout largo (conforme preferências de design aprovadas). Live via WebSocket.
  As skills `frontend-design` e `dataviz` serão aplicadas na implementação.
- **Instalação:** `install.sh` faz `apt install fatrace bpftrace blktrace
  smartmontools hdparm linux-perf`, cria venv, instala e arranca os dois
  serviços systemd.

## 10. Tratamento de erros e robustez

- Cada coletor é isolado: se um tracer falha ou não está disponível, o painel
  respetivo degrada com aviso, sem derrubar o coletor.
- `hdparm -C` indisponível num disco USB → fallback inferido, painel indica a
  menor confiança.
- Web sobrevive a BD ocupada (retry em `SQLITE_BUSY`, timeout WAL).
- Coletor a correr como root: superfície mínima, sem exposição de rede, valida
  entradas de subprocess.

## 11. Testes

- Unitários para os parsers (diskstats, saída de `hdparm -C`, linhas de
  `fatrace`, `bpftrace`, `ss`, `systemctl list-timers`, `docker stats`) com
  amostras reais capturadas da máquina.
- Testes da camada de BD (escrita, rollups, retenção, deteção de incidente).
- Teste de correlação: dado um conjunto sintético de eventos, o motor associa
  corretamente o spin-up ao processo/container certos.
- Smoke test end-to-end: coletor arranca, escreve BD, web serve e devolve JSON.

## 12. Fora de âmbito (YAGNI)

- Alertas/notificações externas (email, push) — talvez numa fase futura.
- Autenticação/multi-utilizador — é localhost pessoal.
- Empacotamento Docker — deploy é systemd nativo.
- Controlo/gestão de energia dos discos (só observação, não gestão).
- Histórico de longo prazo tipo Prometheus — retenção curta e focada chega.
