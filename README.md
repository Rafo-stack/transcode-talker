# Reencoder-v3

**Porta:** 4246 (API + UI)
**Imagens:** local build (`./reencoder-api`, `./reencoder-worker`)
**Rede:** `reencoder-net` *(isolada — não está em `media-network`)*
**UID/GID:** root (ver [seção UID/GID](#uidgid-e-permissões))

> Documentação técnica completa em [`Documentacao/01 - Reencoder - Documentacao.md`](../Documentacao/01%20-%20Reencoder%20-%20Documentacao.md).

## Propósito

Re-encode automatizado dos arquivos grandes da biblioteca para HEVC, reduzindo espaço em disco mantendo qualidade aceitável. Compõe um **api** (FastAPI/UI) e um **worker** (faz o encode via FFmpeg, CPU ou VAAPI AMD).

## Serviços

| Serviço | Função | Healthcheck |
|---|---|---|
| `reencoder-api` | UI web + API REST | `GET /api/health` |
| `reencoder-worker` | Loop de processamento de jobs | heartbeat em `/data/.worker_heartbeat` (refresh < 30s) |

## Integrações

- **Consome:** filesystem (`/mnt/media`, `/mnt/animes`, `/mnt/hdd`), GPU AMD (`/dev/dri/renderD128`)
- **Consumido por:** humano via UI (`http://<host>:4246`)
- **Não integra** com \*arr (rede separada — B-008 / Won't Do)

## Volumes mapeados

| Container | Host | Propósito |
|---|---|---|
| `/data` | `~/docker/reencoder-v3/data` | DB SQLite + configs + logs |
| `/mnt/media` | `/mnt/media` | Origem/destino de re-encode |
| `/mnt/animes` | `/mnt/animes` | Idem |
| `/mnt/hdd` | `/mnt/hdd` | Storage temp (HDD lenta dedicada) |
| `/dev/dri` (worker) | `/dev/dri` | VAAPI render node |

## Configuração inicial

1. `cd reencoder-v3 && docker compose up -d` — build automático na primeira vez
2. UI em `http://<host>:4246`
3. Configurar:
   - **Scan folders** — diretórios a varrer
   - **Min file size** — threshold para considerar candidato
   - **Preset / CRF** — qualidade do encode
   - **Use VAAPI** — ligar se hardware AMD disponível
4. (Opcional) Habilitar BASIC_AUTH:
   ```bash
   export BASIC_AUTH_USER=admin
   export BASIC_AUTH_PASS='senha-forte'
   docker compose up -d
   ```

## UID/GID e Permissões

> Cobre B-020 e M-018.

**Problema:** o reencoder roda como **root** dentro do container (não usa PUID/PGID), enquanto os demais serviços da stack rodam como `1000:1000`. Arquivos re-encodados que voltam para a biblioteca podem ficar com `owner: root` em vez de `rafael`.

**Por que não foi corrigido:**

- VAAPI exige que o processo tenha permissão de acessar `/dev/dri/renderD128`, que pertence aos grupos `render` e/ou `video` no host. Mudar para `user: 1000:1000` sem ajustar `group_add` quebra a aceleração GPU.
- Os GIDs de `render`/`video` variam por host (Ubuntu 22.04 != Debian 12 != Arch). Precisam ser descobertos no servidor real, não na documentação.

**Como corrigir no futuro (se quiser):**

```bash
# 1. Descobrir GIDs no host:
getent group render video
# Exemplo de output:
# render:x:993:rafael
# video:x:39:rafael

# 2. Aplicar no docker-compose.yml do reencoder-worker:
#    user: "1000:1000"
#    group_add:
#      - "993"   # render
#      - "39"    # video

# 3. Re-criar dirs do reencoder com owner correto:
sudo chown -R 1000:1000 ~/docker/reencoder-v3/data

# 4. Restart e verificar VAAPI:
docker compose down && docker compose up -d
docker exec reencoder-worker vainfo
```

**Sintoma de que o problema está ativo:**

```bash
ls -la /mnt/media/Movies/<algum-encoded>/
# Se mostrar "root root" em vez de "rafael rafael" → reencoder está como root.
```

**Workaround temporário (se não quiser mudar o user):**

```bash
# Cron semanal que reativa permissões corretas
0 4 * * 0 chown -R 1000:1000 /mnt/media /mnt/animes
```

## Gotchas

- Path absoluto no compose (`~/docker/reencoder-v3/data`) — não portável (B-009 / Won't Do).
- TZ default agora é `America/Sao_Paulo` (T-01 desta sessão — antes era `America/New_York`).
- Healthcheck do worker depende do arquivo `/data/.worker_heartbeat` — se você apagar `/data/` o worker fica `unhealthy` até completar uma iteração.
- VAAPI: se `/dev/dri/renderD128` não existir ou sem permissão, encode cai para libx265 CPU (mais lento, ainda funciona).

## Comandos rápidos

```bash
cd reencoder-v3 && docker compose up -d

# Health
curl -fsS http://localhost:4246/api/health && echo OK

# Worker heartbeat
ls -la ~/docker/reencoder-v3/data/.worker_heartbeat

# Logs
docker logs -f reencoder-api
docker logs -f reencoder-worker

# Verificar VAAPI
docker exec reencoder-worker vainfo

# Restart só do worker
cd reencoder-v3 && docker compose restart reencoder-worker
```
