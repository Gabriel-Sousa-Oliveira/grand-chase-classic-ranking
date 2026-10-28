# Validação operacional e preservação de tempos — 28/10/2026

## Correção de leitura incorporada

O PR #15 foi incorporado em `43b21a5ad0d63fd05d5116ff55c8a8c87dcc11a1`.
A validação completa, com novos downloads do YouTube, passou nos três vídeos:

| Vídeo | Tempo esperado | Tempo obtido | Quadros concordantes |
| --- | --- | --- | --- |
| tCfudbb88dU | 184000 ms | 184000 ms | 4 |
| DDzlbGAOo2I | 80000 ms | 80000 ms | 6 |
| 93GrHzU6FmY | 363000 ms | 363000 ms | 6 |

Zero divergências, casos sem consenso ou erros técnicos.
Execução: <https://github.com/Gabriel-Sousa-Oliveira/grand-chase-classic-ranking/actions/runs/40713648550>.
O Vercel confirmou publicação da versão de `main`.

## Lote real da fila

Execução: <https://github.com/Gabriel-Sousa-Oliveira/grand-chase-classic-ranking/actions/runs/40714605480>.
Commit executado: `35c215efbe9c86b80251847c5a6b8178f8949cf4`.
Processados os 12 selecionados de Void Invasion: 6 leituras de tempo,
4 casos sem consenso e 2 falhas por limite de tempo (download e orçamento
total do vídeo). O processamento levou 1221,6 s, além da preparação e publicação.
Fila consolidada de 527 candidatos enviada com sucesso; banco e diagnósticos
salvos. As respostas da API registraram zero aprovações automáticas.

**Os seis tempos não são seis novidades:** os mesmos seis IDs já constavam
como matched na execução anterior `40596456944`. Portanto este lote comprova
o fluxo operacional, mas não comprova crescimento do ranking público.
O snapshot público consultado antes do lote tinha 188 linhas. Tempos de OCR
continuam sujeitos à aprovação humana.

## Falha adicional reproduzida

`CandidateRepository.add(..., enrich_existing=True)` substituía o tempo,
status e metadados de uma entrada pendente pelos valores extraídos novamente
do título. Se o título não continha tempo, um valor obtido por OCR ou inserido
manualmente era apagado. O comando channel-archive utiliza esse caminho.
A execução atual restaurou o cache do crawler `40619802048`, posterior ao
lote OCR anterior. A repetição observada é compatível com esse defeito;
não foi feita inspeção forense de todos os snapshots intermediários do banco.

Reprodução local antes da nova correção:

1. Adicionar `Ronan Void Invasion 3F`, sem tempo no título.
2. Salvar resultado OCR de 80000 ms, com evidência e status ready_for_review.
3. Reimportar o mesmo vídeo/título com `enrich_existing=True`.
4. O tempo virava NULL, o status virava time_required e a evidência desaparecia.

## Correção proposta, separada do PR #15

Quando o título atualizado não oferece tempo e a classificação é compatível
(campos desconhecidos podem ser preenchidos, campos conhecidos não podem ser
contraditos ou removidos, e a era deve continuar igual), preservar tempo resolvido, confiança e
histórico OCR, mesclando os metadados novos sobre os antigos. O status continua
ready_for_review se a classificação estiver completa. Valores manuais também
são preservados. Sem tempo resolvido, manter o histórico de tentativas.

Um conflito ou perda de classificação conhecida invalida esse reaproveitamento, e um tempo explícito
novo no título mantém a precedência anterior. Entradas aprovadas/rejeitadas
continuam protegidas pela cláusula SQL original.

Cinco novos testes cobrem preservação de OCR, tempo manual, histórico de
tentativas, troca dos quatro campos de classificação e substituição explícita
do tempo pelo título. Antes da mudança, os testes de preservação reproduziram
a perda de dados. Após a mudança, **128 testes de backend passaram**.

## Pedido ao Gemini

Audite o diff e os arquivos completos database.py e test_database.py.
Procure perda de evidência, preservação indevida de tempos em outra classificação,
regressão na proteção de aprovados/rejeitados e comportamento de atualização
dos metadados. Apresente apenas problemas demonstráveis, com reprodução e teste.
Esta proposta não foi incorporada a main nem executada na fila real.


## Segunda rodada do PR #16: completar campos ausentes

A auditoria do Gemini apresentou um caso real: uma entrada com tempo manual
de 80000 ms e título `Ronan Void Invasion` perdia o tempo ao ganhar `3F`.
O teste reproduziu a falha para tempo manual e OCR ao preencher personagem,
categoria ou andar antes desconhecidos. A regra foi ajustada para aceitar
esses refinamentos sem perder tempo, confiança ou histórico.

Regras verificadas após o ajuste:

- Completar os campos restantes com tempo preservado resulta em ready_for_review.
- Se a classificação continua parcial, manter classification_required e o tempo.
- Completar classificação sem tempo continua em time_required; não foi reproduzido
  ready_for_review com time_ms NULL. O defeito real era a perda de tempo.
- Contradizer um valor conhecido, removê-lo ou alterar a era invalida o reaproveitamento.
- A sugestão de resíduos antigos de OCR não se confirmou no cenário descrito:
  o ramo incompatível não mescla o JSON antigo. Os testes verificam ausência de
  ocr, ocr_time_ms, ocr_confidence, evidence_frame, evidence_image, ocr_outcome
  e ocr_attempts, preservando os novos metadados de descrição. Isso não é uma
  garantia sobre chaves OCR que um chamador forneça explicitamente como dados novos.

Novos testes de preservação falharam antes do ajuste. A suíte completa após o
ajuste passou com **131 testes**. O ambiente isolado usou OpenCV 4.10.0.84 e
NumPy abaixo de 2, conforme as dependências do projeto. A primeira tentativa
da suíte completa no Python sem OpenCV falhou por dependência ausente; foi
reexecutada no ambiente preparado. Não houve nova execução em produção.
