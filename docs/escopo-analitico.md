# Escopo Analítico

## Objetivo

Construir uma base espaço-temporal para estudar a relação entre:

- áreas de abastecimento da COMPESA;
- localizações de EDL;
- ovitrampas e seus resultados;
- temperatura e chuva;
- condições de abastecimento.

O objetivo inicial é medir associações espaciais e temporais. Qualquer uso preditivo dependerá de validação posterior.

## Unidade Espacial

O H3 será a unidade espacial analítica principal. Bairros serão usados como rótulos para leitura e visualização, não como a única unidade de análise.

As EDLs serão representadas por pontos e por áreas de influência circulares. O
mapa permitirá selecionar um raio de 0 a 500 m, com 400 m como cenário
operacional principal. A escolha de 400 m é informada por material da Fiocruz
que relata disseminação efetiva até essa distância em ensaios de campo
(Abad-Franch et al., 2015; 2017). Isso não equivale automaticamente ao raio
de eficácia das EDLs no Recife. Os buffers serão chamados de áreas
operacionais presumidas, e não de eficácia local comprovada.

As sensibilidades analíticas iniciais serão 50, 100, 150, 200, 300, 400 e
500 m. A análise deve preservar o raio como hipótese operacional e validar sua
adequação com dados e especialistas da GEVACZ.

As ovitrampas serão associadas à célula H3 que contém cada coordenada. A resolução H3 inicial será avaliada entre:

- resolution 9, para maior detalhe;
- resolution 8, quando a quantidade de observações por célula for pequena.

Uma célula com poucos registros poderá ser agregada a uma resolução mais ampla para reduzir instabilidade estatística.

## Abastecimento

As áreas da COMPESA serão intersectadas com as células H3. O abastecimento de uma célula será calculado a partir das áreas que a cobrem, usando as economias cadastradas como peso quando esse campo estiver disponível.

O percentual mensal de abastecimento é:

```text
horas com abastecimento previsto / horas totais do mês × 100
```

O cálculo considera a união dos intervalos para não contar sobreposições duas vezes. `Quantidade_de_Economias` representa unidades cadastrais da COMPESA, não população.

## Clima

A primeira fonte será o Historical Forecast do Open-Meteo com o modelo ECMWF IFS HRES, em aproximadamente 9 km. A consulta deverá preservar a coordenada/célula meteorológica retornada pela fonte.

A grade meteorológica será mantida separada da grade H3. O H3 pode ter células de centenas de metros, enquanto o clima terá resolução aproximada de quilômetros. Não será criada precisão artificial por interpolação.

A grade será descoberta sobre todo o limite do Recife, independentemente das áreas COMPESA. Para a visualização municipal, células H3 sem uma célula meteorológica diretamente correspondente receberão o valor da célula HRES mais próxima, mantendo essa atribuição como uma aproximação explícita.

Variáveis iniciais:

- temperatura média diária;
- temperatura mínima e máxima diária;
- precipitação diária;
- horas com precipitação.

Agregações mensais:

```text
temperatura média mensal = média das temperaturas médias diárias
chuva acumulada mensal = soma da precipitação diária
dias chuvosos = quantidade de dias acima do limiar definido
```

Temperatura e chuva serão associadas às células H3 pela grade meteorológica correspondente. Quando várias células H3 receberem o mesmo grid meteorológico, isso será preservado como característica da fonte, não tratado como variação observada.

## Base Analítica

A tabela analítica deverá permitir uma linha por célula H3 e período, com campos como:

```text
h3_index
periodo_inicio
periodo_fim
bairro
edl_count
ovitrap_count
ovos_count
temperatura_media
temperatura_minima
temperatura_maxima
chuva_acumulada
dias_chuvosos
percentual_abastecimento
dias_sem_abastecimento
dias_manutencao
```

O período deverá respeitar a frequência real das coletas de ovitrampas e EDLs. Não serão criados valores semanais ou mensais sem documentar a regra de agregação.

## Ciclos e Defasagens

As ovitrampas serão analisadas na frequência real de coleta. A linha do tempo
principal usará `ano + ciclo`, e não o mês do mapa da COMPESA.

Para cada observação, serão calculadas janelas anteriores à coleta de 7, 14,
21 e 28 dias. O dia da coleta fica fora da janela para evitar vazamento
temporal. Chuva será acumulada, temperatura será resumida por média e
abastecimento será resumido por horas e dias sem abastecimento.

O mapa permite selecionar o ciclo e a janela ambiental. Essa seleção visual
não substitui a geração de todas as janelas na tabela analítica.

## Modelagem Posterior

Antes de modelos preditivos, serão avaliadas associações com defasagens de 7, 14, 21 e 28 dias para chuva, temperatura e abastecimento.

As respostas possíveis incluem contagem de ovos, positividade e outros indicadores definidos pela estrutura das ovitrampas. Modelos de contagem, como Poisson ou binomial negativa, poderão ser considerados quando houver volume suficiente de observações.

A validação deverá respeitar tempo e espaço. Uma divisão aleatória simples pode produzir resultados otimistas por colocar células ou períodos relacionados em treino e teste.

## Análise EDL-Ovitrampa

Cada observação de ovitrampa poderá receber a distância até a EDL mais próxima,
a quantidade de EDLs próximas e indicadores para os raios de 50, 100, 150,
200, 300, 400 e 500 m. A comparação inicial será entre quantidade de ovos,
positividade e distribuição dos registros próximos e distantes de EDLs.

Sem datas de instalação, ativação e manutenção das EDLs, essa comparação será
interpretada como associação espacial exploratória. Não será apresentada como
efeito causal, eficácia ou análise antes/depois.

## Hipóteses a Reavaliar

- adequação do raio de ação das EDLs;
- resolução H3 mais apropriada;
- suficiência da resolução meteorológica do Open-Meteo;
- necessidade de complementar chuva com CEMADEN ou CHIRPS;
- quantidade mínima de observações por célula;
- período e defasagem mais adequados para cada resposta;
- estabilidade da associação entre abastecimento, clima e ovitrampas.

## Fora do Escopo Inicial

- interpretar economias como população;
- afirmar causalidade entre abastecimento, clima e ovitrampas;
- gerar previsão antes de validar associação e qualidade dos dados;
- interpolar dados meteorológicos para simular resolução subquilométrica;
- escolher definitivamente o raio das EDLs sem testar alternativas.

Este documento descreve o escopo inicial. As escolhas espaciais, meteorológicas e estatísticas são hipóteses de trabalho e serão revisadas após a integração dos dados.
