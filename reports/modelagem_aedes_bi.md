# Relatorio exploratorio de modelagem do AEDES BI

Os resultados descrevem associacoes. Nao sao evidencia de causalidade nem de eficacia comprovada das EDLs.

## Conclusoes

**Conclusao sobre EDLs:** nao ha evidencia consistente para afirmar eficacia. A distancia ate a EDL mais proxima apresentou associacao negativa, o indicador de 400 m nao foi robusto e a distancia ate EDL ativa conhecida apresentou sinal contrario. Essa inconsistencia, somada a informacao incompleta de ativacao e manutencao, impede uma conclusao de eficacia.
**Diferenca-em-diferencas:** a instalacao registrada em 2026 foi analisada como proxy de inicio da intervencao para 126 ovitrampas no raio de 400 m, com controles a mais de 400 m. O resultado deve ser interpretado somente se as tendencias pre-intervencao forem plausivelmente paralelas; a instalacao nao comprova ativacao, manutencao ou eficacia.
**Conclusao sobre ambiente:** as janelas de 7, 14, 21 e 28 dias foram ajustadas separadamente. A leitura final deve priorizar sinais que se repetem entre janelas, anos e validacoes; um resultado isolado em uma janela nao e considerado evidencia robusta.

**Distancia ate EDL mais proxima:** evidencia de associacao negativa no ajuste NB2 (coeficiente -0.0488, p=0.0101); isso nao demonstra causalidade.
**Indicador de 400 m:** nao ha evidencia estatistica robusta no ajuste NB2 (coeficiente -0.0049, p=0.617).
**Distancia ate EDL ativa conhecida (sensibilidade):** evidencia de associacao positiva no ajuste NB2 (coeficiente 0.0334, p=0.00199); isso nao demonstra causalidade.
**Efeito DiD de instalacao registrada:** nao ha evidencia estatistica robusta no ajuste NB2 (coeficiente -0.0133, p=0.759).
**Chuva em 7 dias:** nao ha evidencia estatistica robusta no ajuste NB2 (coeficiente -0.0000, p=0.98).
**Temperatura em 7 dias:** evidencia de associacao positiva no ajuste NB2 (coeficiente 0.0179, p=0.0447); isso nao demonstra causalidade.
**Dias sem abastecimento em 7 dias:** evidencia de associacao negativa no ajuste NB2 (coeficiente -0.0090, p=0.00746); isso nao demonstra causalidade.

## Comparacao das janelas ambientais

Cada janela foi ajustada em um modelo separado. Coeficientes positivos indicam maior media esperada de ovos conforme aumenta a covariavel, mantendo os demais termos do modelo.
- 7 dias: chuva=-0.0000 (p=0.98); temperatura=0.0179 (p=0.0447); falta_abastecimento=-0.0090 (p=0.00746).
- 14 dias: chuva=-0.0010 (p=2.74e-15); temperatura=-0.0390 (p=0.000216); falta_abastecimento=-0.0041 (p=0.0163).
- 21 dias: chuva=-0.0009 (p=6.14e-18); temperatura=-0.0705 (p=1.54e-10); falta_abastecimento=-0.0021 (p=0.0799).
- 28 dias: chuva=-0.0003 (p=0.000416); temperatura=-0.0674 (p=8.08e-09); falta_abastecimento=-0.0021 (p=0.0154).

## Arboviroses

- Registros de Recife normalizados: 23990.
- Por doenca: {'chikungunya': 4336, 'dengue': 18364, 'zika': 1290}.
- Os casos foram agregados por mes e bairro/distrito. Esta etapa e descritiva; nao ha coordenadas individuais nem denominador populacional para taxas H3.

## Diferenca-em-diferencas

- Resumo:  treated_400m  post_installation  observacoes  ovitrampas  media_ovos  mediana_ovos
            0                  0        63397        1731  209.480212         139.0
            1                  0         5857         124  223.430084         145.0
            1                  1          785         122  179.774522         103.0
- O modelo compara a mudanca pre/post nas ovitrampas ate 400 m com ovitrampas a mais de 400 m, controlando clima, falta de abastecimento, ano, mes e efeitos fixos H3-8.
- Tendencia mensal pre-2026: grupo ate 400 m=0.833; controle=0.571; diferenca=0.262. Isso e um diagnostico simples, nao um teste definitivo de tendencias paralelas.

## Base e exclusoes

- Base ambiental: 110033 observacoes.
- Base EDL espacial: 110033 observacoes.
- Exposicao EDL ativa conhecida: 30379 observacoes; desconhecida: 79654. Observacoes desconhecidas nao foram excluidas da analise ambiental.
- Duplicidades de chave: 52 (SJS1002, SJS1003); tratadas somente na base derivada.
- Media ambiental de ovos: 212.27; variancia: 61225.42; razao variancia/media: 288.43.
- Zeros: 0.0134.

## Comparacao dos modelos

```text
               analysis        validation  window_days                 exposure   model      n          aic          bic     deviance  dispersion_pearson  alpha_nb2  log_score        mae       rmse
              ambiental   ajuste_completo            7                  nenhuma Poisson 109367 2.113520e+07 2.113723e+07 2.041710e+07          255.367942        NaN        NaN        NaN        NaN
              ambiental   ajuste_completo            7                  nenhuma     NB2 109367 1.386032e+06 1.388058e+06 1.053369e+05            0.996788   1.214598        NaN        NaN        NaN
              ambiental   ajuste_completo           14                  nenhuma Poisson 109367 2.111954e+07 2.112156e+07 2.040144e+07          255.152627        NaN        NaN        NaN        NaN
              ambiental   ajuste_completo           14                  nenhuma     NB2 109367 1.385959e+06 1.387985e+06 1.053185e+05            0.996684   1.214074        NaN        NaN        NaN
              ambiental   ajuste_completo           21                  nenhuma Poisson 107640 2.077087e+07 2.077289e+07 2.006430e+07          255.228553        NaN        NaN        NaN        NaN
              ambiental   ajuste_completo           21                  nenhuma     NB2 107640 1.363763e+06 1.365786e+06 1.033830e+05            0.996084   1.217490        NaN        NaN        NaN
              ambiental   ajuste_completo           28                  nenhuma Poisson 107623 2.077950e+07 2.078152e+07 2.007304e+07          255.279645        NaN        NaN        NaN        NaN
              ambiental   ajuste_completo           28                  nenhuma     NB2 107623 1.363578e+06 1.365601e+06 1.034733e+05            0.996072   1.216785        NaN        NaN        NaN
           edl_espacial   ajuste_completo            7       distancia_continua Poisson 109367 2.113266e+07 2.113470e+07 2.041457e+07          255.374207        NaN        NaN        NaN        NaN
           edl_espacial   ajuste_completo            7       distancia_continua     NB2 109367 1.386035e+06 1.388071e+06 1.052981e+05            0.996641   1.214985        NaN        NaN        NaN
           edl_espacial   ajuste_completo            7          faixa_distancia Poisson 109367 2.111705e+07 2.111913e+07 2.039894e+07          254.942011        NaN        NaN        NaN        NaN
           edl_espacial   ajuste_completo            7          faixa_distancia     NB2 109367 1.385969e+06 1.388043e+06 1.053845e+05            0.996363   1.213434        NaN        NaN        NaN
           edl_espacial   ajuste_completo            7           indicador_400m Poisson 109367 2.113516e+07 2.113719e+07 2.041706e+07          255.360838        NaN        NaN        NaN        NaN
           edl_espacial   ajuste_completo            7           indicador_400m     NB2 109367 1.386032e+06 1.388068e+06 1.053433e+05            0.996780   1.214519        NaN        NaN        NaN
edl_ativa_sensibilidade   ajuste_completo            7 distancia_ativa_continua Poisson  30061 5.644222e+06 5.645934e+06 5.450123e+06          241.089648        NaN        NaN        NaN        NaN
edl_ativa_sensibilidade   ajuste_completo            7 distancia_ativa_continua     NB2  30061 3.762656e+05 3.779777e+05 3.099806e+04            1.000225   1.211216        NaN        NaN        NaN
              ambiental     temporal_2026            7                  nenhuma Poisson  80810 1.685442e+07 1.685446e+07 1.632102e+07          287.839861        NaN 861.557050 167.378367 242.735388
              ambiental     temporal_2026            7                  nenhuma     NB2  80810 1.033815e+06 1.033852e+06 7.374414e+04            0.999978   1.323485 861.303995 167.875177 243.013385
           edl_espacial     temporal_2026            7       distancia_continua Poisson  80810 1.684576e+07 1.684581e+07 1.631236e+07          287.381084        NaN 861.768472 167.004589 242.550440
           edl_espacial     temporal_2026            7       distancia_continua     NB2  80810 1.033733e+06 1.033779e+06 7.388417e+04            0.999974   1.320339 861.520367 167.498129 242.822333
              ambiental     temporal_2026           14                  nenhuma Poisson  80810 1.688379e+07 1.688382e+07 1.635038e+07          288.719899        NaN 863.383732 163.631392 240.849649
              ambiental     temporal_2026           14                  nenhuma     NB2  80810 1.033991e+06 1.034028e+06 7.361287e+04            0.999762   1.327816 863.172263 164.100948 241.055300
           edl_espacial     temporal_2026           14       distancia_continua Poisson  80810 1.687504e+07 1.687509e+07 1.634164e+07          288.257377        NaN 863.570924 163.265396 240.693155
           edl_espacial     temporal_2026           14       distancia_continua     NB2  80810 1.033908e+06 1.033955e+06 7.375204e+04            0.999764   1.324665 863.363013 163.735431 240.895480
              ambiental     temporal_2026           21                  nenhuma Poisson  79083 1.651088e+07 1.651091e+07 1.598900e+07          288.348271        NaN 861.826569 167.700780 242.414972
              ambiental     temporal_2026           21                  nenhuma     NB2  79083 1.011550e+06 1.011587e+06 7.209488e+04            0.999497   1.325852 861.159216 169.161471 243.125897
           edl_espacial     temporal_2026           21       distancia_continua Poisson  79083 1.650182e+07 1.650187e+07 1.597994e+07          287.857427        NaN 862.041564 167.306274 242.234557
           edl_espacial     temporal_2026           21       distancia_continua     NB2  79083 1.011465e+06 1.011512e+06 7.223861e+04            0.999509   1.322536 861.386900 168.752794 242.932588
              ambiental     temporal_2026           28                  nenhuma Poisson  79066 1.646043e+07 1.646047e+07 1.593867e+07          286.920377        NaN 860.429426 171.215638 243.980884
              ambiental     temporal_2026           28                  nenhuma     NB2  79066 1.011039e+06 1.011076e+06 7.229670e+04            0.999807   1.318559 859.645611 172.833950 244.878703
           edl_espacial     temporal_2026           28       distancia_continua Poisson  79066 1.645122e+07 1.645127e+07 1.592946e+07          286.442683        NaN 860.672115 170.806119 243.774233
           edl_espacial     temporal_2026           28       distancia_continua     NB2  79066 1.010959e+06 1.011005e+06 7.243013e+04            0.999851   1.315484 859.917815 172.380885 244.636327
           edl_espacial espacial_bloco_h3            7       distancia_continua Poisson  87978 1.761292e+07 1.761309e+07 1.703540e+07          270.349429        NaN 960.910561 164.684666 261.182126
           edl_espacial espacial_bloco_h3            7       distancia_continua     NB2  87978 1.118411e+06 1.118580e+06 8.264810e+04            0.998800   1.283059 960.954957 164.611226 261.159382
               did_400m   ajuste_completo            7              tratado_pos Poisson  70039 1.335239e+07 1.335420e+07 1.289303e+07          250.599348        NaN        NaN        NaN        NaN
               did_400m   ajuste_completo            7              tratado_pos     NB2  70039 8.860734e+05 8.878865e+05 6.801776e+04            0.996968   1.200394        NaN        NaN        NaN
```

## Validacao

- Validacao temporal ambiental: treino 80810 e teste 28557.
- Validacao temporal EDL: treino 81171 e teste 28862.
- Validacao espacial EDL por blocos H3: treino 88496 e teste 21389.
- A validacao temporal continua limitada pela cobertura de datas e ciclos; os resultados fora da amostra devem ser lidos como diagnostico, nao como prova de previsao geral.

## Limites

- Distancia ate EDL mede proximidade espacial, nao confirma ativacao, manutencao ou eficacia.
- A exposicao ativa so foi usada na analise de sensibilidade porque muitas datas de instalacao sao desconhecidas.
- A temperatura media observada nao cobre 30--35 graus C; essa faixa nao pode ser inferida deste conjunto.
- ZINB nao foi ajustado; a proporcao de zeros e baixa. ZNIB nao foi ajustado porque QT e o denominador binomial nao foram confirmados.
