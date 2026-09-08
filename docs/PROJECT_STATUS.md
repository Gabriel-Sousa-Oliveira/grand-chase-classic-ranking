# Estado do projeto

Atualizado em 8 de setembro de 2026.

## Objetivo

Descobrir automaticamente vídeos recentes de speedrun de Grand Chase Classic no YouTube, extrair seus dados, encaminhar casos duvidosos para validação humana e publicar rankings por personagem.

## Regras decididas

- O ranking é dividido por personagem.
- Dentro de cada personagem, os jogadores são identificados pelo nick.
- Cada recorte exibe até quatro nicks, com destaque para o melhor tempo.
- Apenas a melhor run de cada nick ocupa uma posição no top 4.
- Rankings de eras diferentes não são misturados.
- Uma nova era deve acompanhar uma atualização grande e impactante de balanceamento do Grand Chase Classic, em vez de reiniciar todo mês. Isso preserva comparabilidade entre runs feitas sob as mesmas regras do jogo.
- A descoberta é automática, mas a aprovação final continua humana.
- Vídeos duplicados são bloqueados pelo `video_id` do YouTube.
- Títulos sem tempo detectável entram na fila `time_required` para confirmação manual ou OCR futuro.
- A interface reconhece a inspiração no Grand Chase Leaderboards criado por Syntaxii.

## Referências fornecidas

- Leaderboard de referência: <https://syntax817.github.io/leaderboard/>
- Vídeos usados como amostra:
  - <https://youtu.be/V6O_9x6QTvw>
  - <https://youtu.be/WZeUJAw4pmU>
  - <https://youtu.be/aTglQvuekIE>

## Implementado

### Interface

- Dashboard responsivo "GC Run Radar".
- Fila de validação com aprovação e rejeição.
- Player incorporado com os três vídeos reais fornecidos.
- Tela de rankings.
- Parser Lab interativo.
- Histórico demonstrativo.

### Núcleo

- Parser determinístico de personagem, categoria, andar, tempo e regras básicas.
- Normalização de formatos de tempo encontrados em títulos.
- Banco SQLite para candidatos, decisões, eras e rankings.
- Bloqueio de duplicatas.
- Aprovação impedida enquanto campos obrigatórios estiverem ausentes.
- Top 4 por personagem e era, mantendo o melhor tempo de cada nick.
- Cliente da YouTube Data API v3 para consultar metadados de uma URL quando `YOUTUBE_API_KEY` estiver configurada.

### Verificação

- Testes de build e componentes da interface.
- Testes do parser com os três títulos de referência.
- Testes de banco, duplicidade, campos pendentes, top 4 por nick e separação por eras.

## Etapa em que paramos

O MVP navegável e o núcleo local estão prontos. O projeto parou na fronteira entre **protótipo funcional** e **automação conectada**.

O crawler periódico da YouTube Data API foi implementado com oito consultas amplas, deduplicação, filtro inicial, persistência em SQLite e execução pelo GitHub Actions. O painel agora possui API, banco D1, fila real e decisões persistentes. Falta apenas cadastrar `SITE_INGEST_TOKEN` nos segredos do GitHub para ativar o envio automático entre os dois ambientes.

Depois disso, a sequência prevista é:

1. ativar o segredo de ingestão no GitHub;
2. experimentar OCR para vídeos cujo título não informa o tempo;
3. sincronizar ou comparar resultados com o leaderboard de referência;
4. transformar eras em configuração administrável quando houver atualizações relevantes do jogo.

## Fora deste repositório

A planilha `Grand_Chase_Classic_Farm_Tracker.xlsx` organiza o progresso de farm e Void dos personagens. Ela é um projeto relacionado ao jogo, mas não faz parte do sistema de ranking e, por isso, não foi incorporada ao código deste produto.
