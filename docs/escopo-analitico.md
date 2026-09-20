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

Uma célula com poucos registros poderá ser agregada a uma resolução mais ampla para reduzir instabilidade estatística. Na primeira avaliação da base, a resolução 8 será a referência operacional e a resolução 9 será tratada como sensibilidade de maior detalhe.

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

`n_ovos` será a resposta principal da primeira modelagem. Positividade será
indicador secundário, pois está saturada nos dados disponíveis e não diferencia
adequadamente as células. A análise espacial usará uma malha H3 fixa, sem
centralizar células nas EDLs, combinada com distância métrica e faixas de
0--100, 100--200, 200--300, 300--400, 400--500 e >500 m até a EDL ativa.
Modelos de contagem, como Poisson ou binomial negativa, poderão ser considerados
após verificar dispersão e volume suficiente de observações.

### ZNIB

ZNIB (`Zero- and N-Inflated Binomial`) exige uma resposta binomial limitada
entre zero e um `N` conhecido, com excesso estrutural nos extremos. Não deve ser
aplicado diretamente a `n_ovos`, que é uma contagem sem limite superior fixo.
Poderá ser avaliado para proporções ou contagens como palhetas positivas sobre
palhetas examinadas, mas somente após confirmar o significado de `QT` e a
existência de um denominador experimental por observação.

ZINB também não é o modelo inicial para `n_ovos`: a proporção de zeros observada
é baixa. Será no máximo uma análise de sensibilidade se os resíduos do modelo
binomial negativo mostrarem excesso de zeros após as covariáveis.

A validação deverá respeitar tempo e espaço. Uma divisão aleatória simples pode produzir resultados otimistas por colocar células ou períodos relacionados em treino e teste.

## Análise EDL-Ovitrampa

Cada observação de ovitrampa recebe a distância até a EDL mais próxima, a
distância até a EDL ativa mais próxima e indicadores para os raios de 50, 100,
150, 200, 300, 400 e 500 m. A comparação inicial será entre quantidade de ovos
e distribuição dos registros nas faixas de distância. Positividade ficará como
indicador descritivo.

Sem datas de instalação, ativação e manutenção das EDLs, essa comparação será
interpretada como associação espacial exploratória. Não será apresentada como
efeito causal, eficácia ou análise antes/depois.

Quando a data de instalação estiver disponível, a análise poderá distinguir
observações anteriores e posteriores à instalação:

```text
instalada_ate_coleta = data_instalacao <= data_coleta
```

Datas informadas apenas como mês/ano serão tratadas como aproximações e não
como dias exatos. A data de instalação indica o início registrado da operação,
mas não confirma ativação, manutenção ou permanência da EDL. Comparações
temporais deverão considerar uma defasagem biológica de 3 a 6 semanas e manter
as observações sem data em categoria separada.

As distâncias são calculadas em metros após reprojeção para o sistema métrico
EPSG:31985. Para cada ovitrampa, a EDL mais próxima é identificada e sua data
de instalação é associada à observação. A distância não é calculada usando
latitude/longitude diretamente.

Na visualização temporal, EDLs com data de instalação posterior à referência do
ciclo ficam ocultas até sua instalação registrada. EDLs sem data permanecem
visíveis como desconhecidas; essa escolha evita interpretar dado ausente como
inexistência da estação.

Pontos até 500 m fora do limite municipal serão tratados como `fora_recife_proxima`
e poderão entrar na visualização e na agregação H3. Pontos dentro do Recife, mas
sem interseção com uma área COMPESA, serão incluídos espacialmente com
abastecimento ausente, sem imputação desse contexto.

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
