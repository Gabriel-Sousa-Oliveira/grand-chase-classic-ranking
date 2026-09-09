# GC Run Radar

MVP para descobrir, classificar, validar e ranquear vídeos de speedrun de Grand Chase Classic.

## Estado atual

- painel responsivo com três vídeos reais e player incorporado;
- Parser Lab interativo no navegador;
- parser Python determinístico para personagens, categorias, andar, tempo e regras básicas;
- persistência local SQLite com fila, decisões e top 4 por nick para cada personagem;
- separação de recordes por eras de atualizações relevantes;
- proteção contra vídeo duplicado por `video_id`;
- crawler da YouTube Data API v3 com consultas em português e inglês, sem chave no código;
- execução automática duas vezes ao dia pelo GitHub Actions;
- sincronização sem cookies das sete categorias públicas do Syntaxii;
- carga histórica de 2026 preservada em uma era separada;
- fila e rankings persistentes no painel hospedado com D1;
- aprovação e rejeição gravadas pela API do painel;
- dashboard analítico com KPIs, cobertura por dungeon e matriz de lacunas por personagem;
- testes automatizados dos três títulos fornecidos.

## Interface

~~~bash
npm run install:ci
npm run dev
~~~

Acesse o menu **Parser Lab** e cole um título. O resultado muda imediatamente.

## Prévia pública na Vercel

O repositório inclui uma versão pública, estática e somente leitura do ranking atual.
Ela não expõe o painel administrativo, tokens, cookies ou controles de aprovação.

1. Abra o [importador da Vercel](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2FGabriel-Sousa-Oliveira%2Fgrand-chase-classic-ranking).
2. Entre com o GitHub e escolha **Deploy**.

O arquivo `vercel.json` já define o build e a pasta de saída. Nenhuma variável de
ambiente é necessária para esta prévia. Novos pushes na branch `main` geram uma
nova publicação automaticamente depois que o projeto é importado na Vercel.
Quando o crawler atualiza os dados, ele também publica um novo snapshot do ranking
na interface pública.

## Núcleo Python

~~~bash
cd backend
python -m unittest discover -s tests -v
python -m gc_radar.cli parse "Ereb | Vazio (Invasão) 3f (1'32) | Grand Chase Classic"
~~~

As instruções completas de banco e ingestão estão em `backend/README.md`.

## Fluxo implementado

1. Extrair o ID de uma URL do YouTube.
2. Interpretar o título e normalizar aliases.
3. Inserir o candidato em SQLite, ignorando duplicatas.
4. Mandar títulos sem tempo para `time_required`.
5. Bloquear aprovação de registros incompletos.
6. Criar uma entrada no ranking do personagem após aprovação.
7. Manter apenas a melhor run de cada nick no top 4 de cada era.

## Próximas integrações

1. Validar os candidatos importados das demais dungeons.
2. Completar a modelagem de rankings por pontuação para LoJ Unlimited.
3. Retomar o OCR quando uma sessão do YouTube puder ser configurada.

A variável `YOUTUBE_API_KEY` deve ser configurada apenas no ambiente local ou de hospedagem. Nunca salve a chave no Git.

## Referência

Interface e organização inspiradas no [Grand Chase Leaderboards criado por Syntaxii](https://syntax817.github.io/leaderboard/), com a proposta adicional de listar vários nicks por personagem e automatizar a descoberta de vídeos.
