# GC Run Radar — núcleo local

Este módulo transforma títulos de vídeos em candidatos estruturados, impede duplicatas e mantém uma fila de validação em SQLite. Rankings são separados por personagem e era de balanceamento, com o melhor tempo de até quatro nicks. Ele não precisa de pacotes externos.

## Rodar os testes

~~~bash
cd backend
python -m unittest discover -s tests -v
~~~

## Testar um título

~~~bash
cd backend
python -m gc_radar.cli parse "Ereb | Vazio (Invasão) 3f (1'32) | Grand Chase Classic"
~~~

## Adicionar manualmente

~~~bash
python -m gc_radar.cli --db gc_radar.sqlite3 add \
  "https://youtu.be/WZeUJAw4pmU" \
  --channel Borkaz \
  --title "Ereb | Vazio (Invasão) 3f (1'32) | Grand Chase Classic"
python -m gc_radar.cli --db gc_radar.sqlite3 queue
~~~

## Buscar metadados reais

Crie uma chave da YouTube Data API v3, defina a variável de ambiente `YOUTUBE_API_KEY` e execute:

~~~bash
python -m gc_radar.cli --db gc_radar.sqlite3 youtube "https://youtu.be/WZeUJAw4pmU"
~~~

Nunca coloque a chave no repositório. Títulos sem tempo entram como `time_required` e seguem para o OCR automático.

## Buscar vídeos recentes

Com `YOUTUBE_API_KEY` definida, execute as oito consultas padrão (Void em português e inglês):

~~~bash
python -m gc_radar.cli --db gc_radar.sqlite3 crawl --days 3
~~~

Cada consulta busca no máximo 50 vídeos e somente a primeira página, protegendo a cota. Resultados repetidos são mesclados pelo ID do YouTube; o banco também impede a reinserção em execuções futuras. Use `--query "texto"` uma ou mais vezes para substituir as consultas padrão.

O workflow `.github/workflows/youtube-crawler.yml` executa o crawler duas vezes por dia, mantém o banco entre execuções e publica o banco e o relatório JSON como artefatos privados da execução.

### Preencher um ranking

O modo histórico faz 50 consultas: uma em português e uma em inglês para cada um dos 25 personagens. Ele aceita somente títulos identificados como Void Invasion 3F.

~~~bash
python -m gc_radar.cli --db gc_radar.sqlite3 fill-ranking --days 365 --max-results 25
~~~

No GitHub Actions, abra **YouTube crawler**, escolha **Run workflow** e selecione `fill-ranking` em **Tipo de busca**.

## OCR dos vídeos pendentes

O workflow baixa somente o trecho final de até oito vídeos por execução, extrai quadros e usa Tesseract para procurar o tempo de conclusão. Um valor só é aceito quando aparece em pelo menos dois quadros distintos e não há empate entre leituras. Mesmo após o OCR, o vídeo fica em `ready_for_review`: nenhuma entrada vai ao ranking sem validação humana.

Para executar localmente, instale `yt-dlp`, `ffmpeg` e `tesseract`, e rode:

~~~bash
python -m gc_radar.cli --db gc_radar.sqlite3 ocr-queue --limit 8
~~~

Downloads executados em datacenters podem exigir login do YouTube. Nesse caso, exporte os cookies no formato Netscape, converta o arquivo para Base64 e salve o conteúdo no segredo `YOUTUBE_COOKIES_B64` do GitHub. O workflow reconstrói o arquivo somente durante a execução; ele não entra nos artefatos nem no repositório.
