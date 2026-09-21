# Modelagem Estatistica

## Objetivo

Avaliar exploratoriamente a associacao entre `n_ovos`, exposicao a EDLs,
chuva, temperatura e abastecimento. Os resultados nao devem ser interpretados
como causalidade ou eficacia comprovada das EDLs.

## Unidade e dados

A unidade principal e uma observacao de ovitrampa por ciclo. A base ambiental e
`data/curated/gevacz/base_modelagem.parquet`; os Parquets de origem nao sao
alterados.

Foram removidas apenas da base derivada:

- chaves ovitrampa-ciclo duplicadas, mantendo a linha com maior completude de
  resposta, data e agente;
- respostas `n_ovos` ausentes;
- datas ausentes, suspeitas ou fora de 2024--2026;
- geografias sem localizacao aceita;
- linhas sem resposta, data, geografia ou covariaveis da janela especifica do
  modelo; a quantidade elegivel varia entre 7, 14, 21 e 28 dias.

As 52 chaves duplicadas pertencem a `SJS1002` e `SJS1003` nos 26 ciclos de
2024. Elas foram tratadas somente na base derivada e permanecem na origem.

Na execucao atual, a base ambiental tem 110.033 linhas: 43.596 de 2024,
37.575 de 2025 e 28.862 de 2026. A informacao de EDL ativa e conhecida em
30.379 linhas e desconhecida em 79.654; as linhas desconhecidas permanecem na
analise ambiental e na analise espacial por proximidade. A distancia ativa e
usada somente como sensibilidade.

## Modelo

Os modelos iniciais sao NB2, com Poisson apenas como baseline. A analise
ambiental usa:

```text
n_ovos ~ chuva_janela + temperatura_janela + dias_sem_abastecimento_janela
         + ano + mes + H3_resolucao_8
```

Cada janela de 7, 14, 21 e 28 dias e ajustada separadamente. As variaveis de
abastecimento sao expressas como falta de agua, coerente com a hipotese de
armazenamento domestico durante interrupcoes. Temperatura maxima nao entra se
nao estiver disponivel na fonte; a media observada nao cobre 30--35 graus C.

A analise EDL acrescenta, em modelos separados, distancia ate a EDL mais
proxima, faixa de distancia ou indicador de 400 m. A distancia ate EDL ativa
conhecida e uma sensibilidade restrita as 30.061 observacoes disponiveis.

Tambem foi ajustada uma diferenca-em-diferencas de sensibilidade usando a
instalacao registrada como proxy de inicio da intervencao. O grupo exposto e
formado por ovitrampas ate 400 m de uma EDL com data exata; o controle usa
ovitrampas a mais de 400 m. O modelo usa NB2, ano, mes, clima, falta de
abastecimento e efeitos fixos H3-8. A instalacao nao comprova ativacao,
manutencao ou eficacia.

`sem_area_compesa` e auditada e entra quando possui variacao na amostra.

Poisson e usado somente como baseline. A exposicao EDL e avaliada em modelos
separados como distancia continua, faixa de distancia ou indicador de 400 m.

H3 resolucao 9 e analise de sensibilidade. ZINB nao e modelo inicial e so deve
ser considerado se os residuos mostrarem excesso de zeros. ZNIB nao e usado
sem confirmar a semantica de `QT` e um denominador binomial valido.

## Validacao

A validacao principal separa treino em 2024--2025 e teste em 2026. Tambem e
usada uma separacao por blocos H3. Divisao aleatoria simples nao e usada por
causa da repeticao temporal e espacial.

Na execucao atual, a validacao temporal usa treino anterior a 2026 e teste em
2026. Cada janela possui sua propria amostra completa. A cobertura de ciclos
nao e uniforme, portanto os resultados fora da amostra sao diagnosticos e nao
prova de previsao geral.

As metricas incluem AIC, BIC, dispersao de Pearson, log score, MAE e RMSE.
O relatorio executado fica em `reports/modelagem_aedes_bi.md` e o HTML do
notebook em `reports/modelagem_aedes_bi.html`.

## Arboviroses

Os dados de dengue, zika e chikungunya sao normalizados em
`data/curated/arboviroses/`. A data principal e `DT_SIN_PRI`, com agregacao por
mes, semana, bairro e distrito. A analise e secundaria e ecologica: os arquivos
nao possuem coordenadas individuais nem denominador populacional para taxas H3.
Defasagens de 2, 4, 6 e 8 semanas devem ser interpretadas como exploratorias.

## Execucao

```bash
uv run jupyter nbconvert --to html --execute \
  --ExecutePreprocessor.kernel_name=aedes-bi \
  --output-dir reports notebooks/modelagem_aedes_bi.ipynb
```

O notebook executa `scripts/modelagem_aedes_bi.py`, que gera a base derivada,
metricas, coeficientes e diagnostico JSON.
