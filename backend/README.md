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

Antes de entrar na fila, cada descoberta passa por uma política de relevância. O
título precisa identificar personagem e dungeon e também conter uma evidência de
run, como tempo, “speedrun/record/solo” ou o formato individual
`Personagem | Dungeon`. Título e descrição eliminam automaticamente guias,
showcases, tier lists, compilações e vídeos com capítulos para vários personagens,
incluindo termos em português, inglês, coreano e tailandês. O relatório registra os
motivos em `ignored_reasons`, permitindo auditar e ajustar o filtro.

A limpeza conservadora da fila existente rejeita apenas falsos positivos com
evidência explícita; vídeos meramente ambíguos continuam disponíveis para revisão:

~~~bash
python -m gc_radar.cli --db gc_radar.sqlite3 prune-irrelevant
~~~

O workflow `.github/workflows/youtube-crawler.yml` executa o crawler duas vezes por dia, mantém o banco entre execuções e publica o banco e o relatório JSON como artefatos privados da execução.

### Preencher um ranking

O modo histórico faz 50 consultas: uma em português e uma em inglês para cada um dos 25 personagens. Ele aceita somente títulos identificados como Void Invasion 3F.

~~~bash
python -m gc_radar.cli --db gc_radar.sqlite3 fill-ranking --days 365 --max-results 25
~~~

No GitHub Actions, abra **YouTube crawler**, escolha **Run workflow** e selecione `fill-ranking` em **Tipo de busca**.

## OCR dos vídeos pendentes

O pipeline tenta capítulos da descrição antes do OCR. O modo legado baixa os dois minutos finais, lê os últimos 90 segundos a 1 FPS e só tenta os 30 segundos finais a 2 FPS quando existem pelo menos duas observações plausíveis. O OpenCV usa recortes no canto superior direito, ampliação 4x, CLAHE, nitidez e binarizações. Esses recortes ainda precisam de calibração: nos diagnósticos reais eles também capturam cenário e o relógio LOCAL, que não é tempo de run. O Tesseract recebe somente `0123456789:.`; o consenso temporal é necessário, mas não substitui a confirmação humana da identidade do cronômetro.

O recorte, o instante relativo ao fim, a ROI e uma confiança heurística ficam registrados como evidência. Quadros completos, cópias originais sem grade e mosaicos permitem verificar a localização do tempo. As imagens ficam em `data/ocr-evidence/`, incluídas no artefato da execução por 30 dias (a visibilidade segue as permissões do GitHub; não presuma privacidade). Nenhuma entrada vai ao ranking sem validação humana. Falhas técnicas continuam reprocessáveis; há orçamento de 300 segundos por vídeo para subprocessos e limite de threads internas.

Para executar localmente, instale `yt-dlp`, `ffmpeg` e `tesseract`, e rode:

~~~bash
python -m gc_radar.cli --db gc_radar.sqlite3 ocr-queue --limit 8
~~~

No GitHub Actions, o modo OCR usa o provedor WebPoClient com o Chrome do runner e o cliente `mweb` para obter PO Tokens anonimamente. Cookies não são obrigatórios. Se o YouTube ainda bloquear o IP do runner, um arquivo Netscape pode ser convertido para Base64 e salvo no segredo opcional `YOUTUBE_COOKIES_B64`. O segredo fica disponível somente na etapa que reconstrói o arquivo temporário, removido após o OCR; ele não entra nos artefatos nem no repositório.

A execução manual continua disponível em **YouTube crawler → Run workflow → `ocr-only`**.

Para atacar lacunas específicas do ranking, o OCR também aceita filtros repetíveis
por personagem. `--retry-no-consensus` reabre somente nessa seleção os vídeos que
uma rodada anterior não conseguiu ler:

~~~bash
python -m gc_radar.cli --db gc_radar.sqlite3 ocr-queue --limit 0 --workers 2 \
  --retry-no-consensus --character Ai --character Amy --character Uno
~~~

### Inspeção visual e amostragem por eventos (experimental)

Instale `opencv-python-headless==4.10.0.84` e `numpy<2` para os utilitários/testes
visuais, além de FFmpeg/ffprobe. A coleta por URLs requer também o yt-dlp e a
configuração de acesso ao YouTube descrita acima.

O modo experimental é opt-in: `GC_OCR_VISUAL_EVENTS=1`. Ele baixa até os últimos
300 segundos por padrão (`GC_OCR_LOOKBACK_SECONDS`, intervalo 30–900), sonda no
máximo 60 frames completos sem Tesseract e propõe até três janelas de transição.
Uma diferença de histograma seguida por estabilidade é apenas um candidato de
cena, não confirmação de vitória. Flashes que retornam à cena anterior são
descartados. Sem evento, o fallback lê somente os 20 segundos finais; a inspeção
completa permanece salva para investigar o que esse fallback não cobriu.

Cada janela é lida primeiro a 1 FPS. A passagem densa a 2 FPS exige duas leituras
plausíveis e fica restrita à mesma janela, dentro do orçamento por vídeo. Não há
detecção de encerramento por áudio implementada: silêncio não prova fim da run.
Outros finais com mais de 15 minutos precisam de inspeção dirigida; nenhuma
cobertura integral da transmissão é prometida.

Gere um levantamento de 20–30 vídeos sem executar OCR nem alterar banco/fila:

~~~bash
python -m gc_radar.inspect_frames --video-dir ./videos --output ./survey --limit 25 --lookback 300
# Ou: urls.txt com uma URL de vídeo por linha; downloads sequenciais e limitados.
python -m gc_radar.inspect_frames --urls-file urls.txt --output ./survey --limit 25 --lookback 300
~~~

Saídas: `survey-mosaic.jpg` (um representante de cada vídeo), mosaicos individuais,
quadros originais PNG, quadros com grade X/Y e manifestos JSON. As coordenadas
referem-se ao frame completo normalizado para 1280 pixels de largura, não à
miniatura do mosaico. Tempos são aproximados e relativos ao trecho baixado; não
são o tempo oficial da run. Para arquivos locais, são relativos ao próprio arquivo.

Para ancoragem, copie `ocr-anchors.example.json`, extraia um template de um quadro
**original** real e calibre `timer_offset: [dx, dy, largura, altura]` relativamente
ao canto superior esquerdo da âncora na escala do template. Somente depois ative
`enabled` e configure `GC_OCR_ANCHORS=/caminho/anchors.json`. A comparação usa
`cv2.matchTemplate`, limiar configurável e até cinco escalas. Imagens constantes,
matches ambíguos e ROIs fora do quadro são rejeitados. No modo por eventos, a
âncora deve aparecer em duas amostras consecutivas para priorizar uma janela;
ela é localizada novamente em cada frame lido. Não há template real de CLEAR
validado incluído — o exemplo desativado não é um detector pronto para produção.

Referências: [OpenCV template matching](https://docs.opencv.org/4.x/d4/dc6/tutorial_py_template_matching.html)
e [comparação de histogramas](https://docs.opencv.org/4.x/d8/dc8/tutorial_histogram_comparison.html).
