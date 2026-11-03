# GTA6 RP Radar 📡

App pessoal que **apanha automaticamente as notícias sobre GTA 6**, sobretudo sobre **RP, servidores privados,
FiveM/Cfx.re e ferramentas de criadores**. Junta tudo num só sítio, etiqueta cada notícia pela origem e manda
**push para o telemóvel** quando sai algo importante.

> Projeto de fã, não afiliado à Rockstar Games nem à Take-Two.

- **Site / PWA:** https://giuseppelomb.github.io/VC-Star/
- **APK Android:** separador *Releases* deste repositório
- **Custo:** zero (GitHub Actions + GitHub Pages + ntfy.sh, tudo grátis)

---

## Como funciona

```
GitHub Actions (de 10 em 10 min)
  └─ Python: recolhe fontes → normaliza → deduplica → classifica → pontua
       ├─ grava docs/data/news.json, docs/data/health.json e data/seen.json
       ├─ envia push ntfy para itens novos importantes
       └─ commit + push (só se houver alterações)
GitHub Pages (pasta /docs) → PWA que lê data/news.json (instalável no telemóvel)
GitHub Actions (manual / tag v*) → APK Android (Capacitor) → GitHub Release
```

### Etiquetas (dizem de onde veio a notícia, não se é verdade)

| Etiqueta | Quando |
|---|---|
| 🟢 **OFICIAL** | Rockstar (Newswire, YouTube, rockstargames.com), Take-Two, anúncios da equipa Cfx.re, PlayStation Blog / Xbox Wire sobre GTA 6 |
| 🟡 **CREDÍVEL** | Domínio em `config/credible.yml` ou título que cita um insider da lista |
| ⚪ **RUMOR** | Tudo o resto |

### Quando há push

| Situação | Prioridade |
|---|---|
| OFICIAL + tópico RP / Online / servidores / criadores | **5 (urgente)** 🚨 |
| OFICIAL (outro tópico, desde que fale de GTA 6) | 4 |
| CREDÍVEL com score ≥ 60 | 3 |
| RUMOR | nunca (fica só na app) |

- No máximo **10 pushes por execução**. Se houver mais, o 10.º é um resumo: «N novidades — abre o Radar».
- Na **1.ª execução** não notifica o histórico. Manda só um push de teste: «✅ Radar ativo — X itens indexados».
- Notícias publicadas há mais de 48 h nunca geram push.
- Itens oficiais de outros jogos (ex.: Red Dead Online) sem tópico e sem menção a GTA 6 ficam só na app
  (`official_requires_match` em `config/keywords.yml`).

---

## Configuração inicial (uma vez)

1. **Código no `main`:** o agendamento (cron) do GitHub só corre no branch por defeito.
2. **Tópico ntfy:** em *Settings → Secrets and variables → Actions → New repository secret*
   cria `NTFY_TOPIC` com o nome do tópico privado. Nunca o escrevas em ficheiros do repositório.
3. **GitHub Pages:** *Settings → Pages → Source: Deploy from a branch → `main` / `/docs` → Save*.
4. **1.ª recolha:** *Actions → «Radar — recolha» → Run workflow*. Deves receber «✅ Radar ativo».
5. **APK (opcional):** *Actions → «APK Android» → Run workflow* (versão, ex.: `1.0`). O ficheiro
   `GTA6-RP-Radar-v1.0.apk` aparece em *Releases*.

### Receber os pushes no telemóvel

Instala a app **ntfy** (Play Store / F-Droid) → **+** → cola o nome do tópico → *Subscribe*.
Para alertas urgentes mesmo em «Não incomodar», ativa nas definições do tópico a opção de
ignorar o «Não incomodar» para prioridade máxima.

### Telegram (opcional, desligado por defeito)

Cria os Secrets `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`. Os mesmos pushes passam a ir também para o Telegram.

---

## Editar sem mexer em código

Tudo se edita no GitHub (abre o ficheiro → ícone do lápis → *Commit changes*). A próxima recolha (≤ 10 min)
já usa as alterações. O workflow **Testes** valida os YAML a cada alteração: se ficar vermelho, há um erro de formato.

**Adicionar uma fonte** (`config/sources.yml`, no fim da lista `sources:`):

```yaml
  - id: eurogamer_pt
    name: Eurogamer PT
    type: rss
    url: https://www.eurogamer.pt/feed
    tier: community      # official | credible | community
    lang: pt
    relevance: gta6      # gta6 = só se falar de GTA 6 | topic = só RP/servidores/... | always = tudo
    enabled: true
```

**Desligar uma fonte:** muda `enabled: true` para `enabled: false` (não apagues; fica o histórico).

**Palavras-chave e pesos** (`config/keywords.yml`):

```yaml
  - topic: rp
    weight: 40
    terms: [roleplay, "rp server", "servidor rp", "whitelist"]   # acrescenta termos aqui
```

**Domínio ou insider credível** (`config/credible.yml`): acrescenta uma linha em `domains:` (ex.: `- 3djuegos.com`)
ou em `insiders:` (ex.: `- Billbil-kun`).

**Termos de scam** (`config/keywords.yml → exclude`): `discard` descarta a notícia, `penalty` baixa o score.

---

## Fontes

O estado de cada fonte (último sucesso, erro, nº de itens) está em `docs/data/health.json` e no ecrã **Sobre** da app.
Uma fonte que falhe nunca pára as outras.

| Fonte | Tier | Notas |
|---|---|---|
| Rockstar Newswire | oficial | Sem RSS. O radar descobre sozinho o endpoint GraphQL interno nos scripts da página |
| Rockstar via Google News (`site:rockstargames.com`) | oficial | Reserva do Newswire |
| Rockstar Games no YouTube | oficial | `channel_id` descoberto pelo @handle e confirmado pelo autor do feed |
| Cfx.re — Anúncios | oficial | Categoria descoberta via `/categories.json` (Discourse) |
| PlayStation Blog, Xbox Wire | oficial | Só itens que falem de GTA 6 |
| Take-Two (comunicados via Business Wire) | oficial | Via Google News |
| Cfx.re fórum geral | comunidade | Só itens que falem de GTA 6 |
| Google News (EN + PT), Bing News | comunidade | Etiqueta final pelo domínio real da notícia |
| Reddit: r/GTA6, r/FiveM, r/RPClipsGTA, r/gtaonline | comunidade | Ver limitações |
| Rockstar Support | — | Fora: não há página de anúncios legível (só um widget JavaScript) |

---

## Limitações

- **X/Twitter** não é legível de graça (API paga, Nitter morto). Os posts oficiais chegam pelo Newswire, YouTube e Google News, com alguns minutos de atraso.
- **Discord** (Cfx.re, NoPixel): os anúncios não são acessíveis sem um bot dentro do servidor. Fica fora do âmbito.
- **Cron do GitHub**: pode atrasar 5–15 min em horas de pico.
- **Reddit** bloqueia muitas vezes os IPs do GitHub Actions (403/429). Se ficar sempre em erro no `health.json`, põe `enabled: false`.
- **Google News**: os links novos são redirecionamentos que não dá para resolver sem chamadas extra. Nesses casos o link abre via Google News e a etiqueta usa o domínio indicado no próprio feed.
- **Repos públicos com cron** ficam desativados ao fim de 60 dias sem atividade. Os commits automáticos do radar evitam isso. Se um dia parar, vai a *Actions* e reativa o workflow.
- **Direitos de autor:** guardamos só título, fonte, data, um excerto (máx. 280 caracteres) e o link para o original.
- **APK sem chave fixa:** cada build usa uma chave de debug nova, por isso tens de desinstalar a versão anterior antes de instalar a nova. Para evitar isso, guarda uma keystore em base64 no Secret `ANDROID_DEBUG_KEYSTORE_B64`.

---

## Para programadores

```bash
pip install -r requirements.txt
python -m pytest -q                 # testes
python -m radar.main --dry-run      # recolhe e mostra contagens + o que seria notificado (não grava nem envia)
python -m radar.main --dry-run --only rockstar_newswire,cfx_announcements
python -m radar.healthcheck --dry-run
```

```
.github/workflows/  fetch.yml (cron 10 min) · healthcheck.yml (diário) · apk.yml · tests.yml
radar/              fetch.py sources.py classify.py dedup.py notify.py store.py main.py healthcheck.py util.py
config/             sources.yml · keywords.yml · credible.yml
data/seen.json      estado: ids vistos (30 dias), pushes pendentes, cache de descobertas
docs/               PWA (index.html, app.js, style.css, sw.js, manifest) + data/news.json + data/health.json
scripts/            android_icons.py (ícones/splash do APK)
tests/              pytest
```
