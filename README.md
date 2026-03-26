# News Image Generator

Pipeline local para transformar notícias em artes verticais (estilo thumbnail/carrossel) com geração de imagem por IA e composição final com texto.

## O que a ferramenta faz

1. Lê notícias (`.json` ou `.md`)
2. Estrutura os dados
3. Gera copy de impacto
4. Cria prompt visual
5. Gera imagem base (Google AI / Nano Banana / A1111)
6. Aplica layout final (branding, título, CTA)
7. Exporta imagens finais e manifesto

## Requisitos

- Python 3.10+
- `pip`
- Playwright + Chromium (para compositor HTML/CSS)
- Opcional:
  - Google AI API Key (modo Google Image)
  - Automatic1111 (modo local SD)
  - Endpoint Nano Banana compatível

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m playwright install chromium
```

## Formato de entrada (JSON)

Arquivo exemplo: `samples/news.json`

```json
[
  {
    "id": "n1",
    "title": "Título da notícia",
    "summary": "Resumo da notícia",
    "sourceUrl": "https://.../foreground.jpg",
    "sourceUrl2": "https://.../background.jpg",
    "journal": "Nome do jornal"
  }
]
```

### Regra de composição visual por fontes

No modo `--enable-nanobana`:
- `sourceUrl2` = fundo
- `sourceUrl` = frente

Se os dois não estiverem disponíveis, o pipeline tenta `--reference-image`.

## Execução rápida

### 1) Google AI (recomendado para começar)

```bash
source .venv/bin/activate
export GOOGLE_API_KEY="SUA_CHAVE"

news-image-generator run \
  --input samples/news.json \
  --output output_google \
  --max-articles 2 \
  --enable-nanobana \
  --enable-google-image-step \
  --google-model gemini-2.5-flash-image \
  --fail-on-fallback \
  --keep-intermediate \
  --json
```

### 2) Automatic1111 local (Stable Diffusion)

```bash
news-image-generator run \
  --input samples/news.json \
  --output output_a1111 \
  --endpoint http://127.0.0.1:7860 \
  --width 1080 \
  --height 1920 \
  --sampler-name "DPM++ 2M Karras" \
  --second-pass-steps 30 \
  --second-pass-denoise 0.32 \
  --style-preset cinematic \
  --json
```

### 3) Nano Banana endpoint

```bash
news-image-generator run \
  --input samples/news.json \
  --output output_nanobana \
  --enable-nanobana \
  --nanobana-endpoint http://127.0.0.1:9000 \
  --nanobana-style-strength 0.72 \
  --nanobana-identity-lock 0.66 \
  --json
```

## Saídas

Por padrão o projeto limpa intermediários no final e deixa:

- `output_x/final/*.png`
- `output_x/final/manifest.json`

Se usar `--keep-intermediate`, também mantém:

- `output_x/generated/*.png`
- `output_x/composed/*_thumb.png`
- `output_x/composed/plans/*_plan.json`
- `output_x/logs/image_generator/*.json` ou `output_x/logs/nanobana/*.json`

## CLI completa

```bash
news-image-generator run --help
```

Flags principais:

- `--input`, `--output`
- `--max-articles`
- `--enable-nanobana`
- `--enable-google-image-step`
- `--google-api-key` (ou `GOOGLE_API_KEY` / `GEMINI_API_KEY`)
- `--google-model`
- `--reference-image`
- `--keep-intermediate`
- `--fail-on-fallback`
- `--json`

## Personalização visual atual

No layout:
- handle: `@a2dev`
- nome: `Adriano Almeida`
- avatar: `/Users/adriano/Pictures/101269663.png`
- fonte de origem sem `@` (ex.: `techcrunch.com`)
- título renderizado usa o `title` do JSON

Arquivo para ajustar isso:
- `src/news_image_generator/agents/layout_composer_agent.py`

## Troubleshooting

### 1) “usedFallbackImages > 0”

A geração caiu em fallback. Rode com:

```bash
--fail-on-fallback --keep-intermediate
```

Depois veja o erro real em:
- `output_x/logs/image_generator/*.json`
- `output_x/logs/nanobana/*.json`

### 2) Erro 404 no Google model

Use um modelo válido no momento, por exemplo:
- `gemini-2.5-flash-image`

### 3) Key não encontrada

Defina:

```bash
export GOOGLE_API_KEY="SUA_CHAVE"
```

ou passe `--google-api-key`.

### 4) Layout sem render Playwright

Confirme instalação do browser:

```bash
python -m playwright install chromium
```

Sem Playwright, o projeto usa fallback de composição em PIL.

## Estrutura do projeto

```txt
src/news_image_generator/
  agents/
    parser_agent.py
    copywriter_agent.py
    visual_prompt_agent.py
    image_generator_agent.py
    nanobana_agent.py
    layout_composer_agent.py
    validator_agent.py
    export_agent.py
  pipeline.py
  cli.py
  models.py
```
