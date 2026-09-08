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

Nunca coloque a chave no repositório. A busca automática e o OCR são as próximas integrações; títulos sem tempo já entram como `time_required`.
