# Dados GEVACZ

## Objetivo

Organizar as bases de estações disseminadoras (EDLs) e ovitrampas para
visualização e análise espacial junto com abastecimento, chuva e temperatura.
Os arquivos originais permanecem em `data/informacoes-gevacz/` e não são
alterados pelo pipeline.

## Entidades normalizadas

`gevacz.py` gera tabelas em `data/curated/gevacz/`:

- `edls.parquet`: um registro por ponto estratégico de EDL;
- `ovitrampas.parquet`: um registro por ovitrampa georreferenciada;
- `observacoes_ovitrampas.parquet`: um registro por ovitrampa e ciclo.
- `ciclos.parquet`: datas de início, fim e referência de cada ciclo;
- `observacoes_analiticas.parquet`: observações com contexto climático e de
  abastecimento nas janelas anteriores de 7, 14, 21 e 28 dias.
- `auditoria_coordenadas_ovitrampas.parquet`: pontos fora do Recife, sem área
  COMPESA ou sem coordenada válida.
- `auditoria_ids_ovitrampas.parquet`: IDs históricos sem correspondência
  geográfica e situação de cada ID.
- `auditoria_georreferenciamento.xlsx`: comparação completa entre o Excel de
  georreferenciamento e os shapefiles de ovitrampas 2026.

Todas as tabelas preservam `arquivo_origem`. As observações preservam também
`aba_origem`.

## Campos principais

EDLs: `edl_id`, `distrito_sanitario`, `bairro`, `nome_local`, `tipo_local`,
`logradouro`, `latitude`, `longitude`, `edl_ideal`, `edl_real`,
`data_instalacao`, `data_instalacao_original` e `qualidade_data_instalacao`.

`data_instalacao` é extraída da coluna `L` de `TOTAL DE EDL POR DS.xlsx` quando
o conteúdo representa uma instalação. Datas completas preservam o dia. Textos
que informam apenas mês e ano são normalizados para o primeiro dia do mês, mas
recebem qualidade `mes_ano` e não são tratados como datas exatas. O texto bruto
permanece em `data_instalacao_original`.

Valores numéricos, células vazias e anotações que indicam retirada não são
convertidos em instalação. A coluna `L` não tem o mesmo significado em todos os
distritos; em alguns arquivos ela contém quantidade de EDL real. Por isso, a
ausência de data não é interpretada como ausência de instalação.

Linhas sem número operacional, mas com identificação de local ou coordenada,
são preservadas com um identificador técnico baseado na linha da planilha
(`DS{distrito}_R{linha}`). Esse identificador sinaliza uma limitação da origem
e não substitui a confirmação do código operacional pela GEVACZ.

Ovitrampas: `id_ovt`, `bairro`, `latitude`, `longitude`, `endereco` e
`id_ovt_chave`, `qualidade_coordenada` e `qualidade_geografica`.

Quando existe um ID único no conjunto `ATUALIZAÇÃO TOTAL DAS OVITRAMPAS 2026
shapefile`, a geometria do shapefile é usada como fonte espacial preferencial.
As coordenadas do Excel permanecem em `latitude_original` e
`longitude_original`, com a origem registrada em `fonte_coordenada`.

O Excel de auditoria possui abas para resumo, comparação entre fontes,
coordenadas confirmadas pelo shapefile, pendências geográficas e IDs sem
correspondência no shapefile. Também registra distância entre as coordenadas e
conflitos quando um ID aparece com mais de uma geometria.

`id_ovt_chave` remove espaços e pontuação para relacionar, por exemplo,
`BVS 1015` na localização com `BVS1015` nas observações. O ID original é
preservado para exibição.

Observações: `id_ovt`, `ano`, `ciclo`, `data_coleta`, `data_leitura`,
`quantidade_palhetas`, `n_ovos` e `status`.

Na tabela `observacoes_analiticas.parquet`, a relação temporal com a EDL mais
próxima inclui `edl_mais_proxima_id`, `data_instalacao_edl`,
`qualidade_data_instalacao_edl` e `instalada_ate_coleta`. Também são gerados
indicadores espaciais para 50, 100, 150, 200, 300, 400 e 500 m. A distância
`distancia_edl_ativa_m` considera apenas EDLs com data de instalação conhecida e
anterior ou igual à coleta; as colunas `edl_ativa_a_*` representam essas faixas.

## Camada H3

`gevacz.py` gera `observacoes_h3.parquet` com agregações por célula H3, ano e
ciclo, nas resoluções 8 e 9. A tabela contém observações, ovitrampas, ovos,
positividade, médias e mediana de ovos, contexto EDL, chuva, temperatura e
abastecimento quando esses campos existem na base analítica.

Também é gerado `h3_diagnostico.parquet`, com quantidade de células, média e
mediana de observações por célula e proporção de células com menos de cinco
observações. Esse diagnóstico documenta o custo de trocar entre resolução 8 e
9; o mapa assumiu a 9 e usa cinza para as células com menos de cinco
observações.

Na execução atual, incluindo pontos até 500 m da fronteira e pontos sem área
COMPESA, a resolução 8 produziu 9.727 células e 19,9% delas tinham menos de
cinco observações. A resolução 9 produziu 45.365 células e 88,0% tinham menos
de cinco observações. O mapa usa a resolução 9, escolhida pelo maior detalhe
espacial; para conter a instabilidade, células com menos de cinco observações
são pintadas de cinza e a cor só aparece onde há amostra. A resolução 8
permanece no parquet como referência de sensibilidade.

O H3 é uma camada de agregação e indexação. As distâncias EDL continuam sendo
calculadas em metros no sistema EPSG:31985 antes da agregação, sem substituir a
distância métrica por uma aproximação de célula.

A malha H3 permanece fixa e não é centralizada nas EDLs. Por cima dela o mapa
desenha um hexágono regular centrado em cada EDL, com o raio do slider
`Raio EDL` (218 m reproduzem o módulo da resolução 9). O hexágono é apenas
visual, segue a distância circular até a EDL mais próxima e pode se sobrepor
ao de EDLs vizinhas; ele não é uma célula de análise. A camada do mapa usa
`ovos_media` em escala logarítmica como intensidade principal; positividade é
mantida no popup como indicador secundário porque está saturada nos dados
disponíveis (aproximadamente 98,5%). A análise de exposição usa a distância
exata e faixas de 0--100, 100--200, 200--300, 300--400, 400--500 e >500 m.

A camada `EDLs projetadas` responde onde novas EDLs cobririam mais ovitrampas.
Hoje apenas 37,7% das 2.843 ovitrampas estão a até 400 m de alguma das 174
EDLs válidas; a mediana dessa distância é de 526 m, o percentil 90 é de
1.937 m e o máximo chega a 4.003 m. A cada mudança do slider `Raio EDL` o
mapa refaz no navegador um k-center guloso: parte da distância de cada
ovitrampa até a EDL mais próxima (`distancia_edl_m`, já calculada em
EPSG:31985), marca como ponto proposto a ovitrampa descoberta mais distante
e repete até cobrir 95% das ovitrampas ou até 400 pontos. Em 400 m isso
resulta em 232 pontos. A camada depende do slider, por isso só aparece com a
camada EDLs marcada, e considera todas as EDLs do cadastro sem filtro de
data: é uma pergunta de planejamento de rede, não de estado por ciclo. As
distâncias entre ovitrampas usam uma projeção equirectangular local, com
erro abaixo de 0,05% frente ao EPSG:31985.

O ano de origem e o ano da data são mantidos separadamente. Datas fora do ano
do arquivo são comparadas com os registros vizinhos e classificadas em
`qualidade_data`; as correções de alta confiança ficam registradas na auditoria.

Nos arquivos de 2025, datas de 2026 nos ciclos 1--23 são corrigidas para 2025
quando a regra de sequência do ciclo é aplicável. Datas fora da faixa plausível
(como anos 1900, 2037 ou 5625) permanecem na origem, mas não entram na data
corrigida usada pela linha do tempo. As regras e linhas afetadas ficam em
`auditoria_georreferenciamento.xlsx`, nas abas `datas_ciclos` e
`correcoes_datas`.

## Ciclos e janelas ambientais

O mapa usa `ano + ciclo` como linha do tempo. A data de referência do ciclo é a
mediana das datas de coleta válidas. Pontos físicos de ovitrampa são exibidos
independentemente da existência de uma observação no ciclo selecionado.

O segundo controle do mapa seleciona a janela anterior à coleta:

- 7 dias;
- 14 dias;
- 21 dias;
- 28 dias.

O dia da coleta não entra na janela. Para chuva são calculados acumulados; para
temperatura, médias; para abastecimento, horas e dias sem abastecimento.

Os arquivos 2024 e 2025 possuem ciclos sem data de coleta válida. Eles ficam
na tabela normalizada, mas não entram na linha do tempo do mapa até validação.

## Cobertura espacial provisória

O mapa permite selecionar um raio de 0 a 500 m para a área operacional
presumida, com 400 m como valor padrão. Esse valor é informado por material
da Fiocruz que relata disseminação efetiva até 400 m em ensaios realizados em
Manaus e Manacapuru (Abad-Franch et al., 2015; 2017). Isso não comprova
eficácia local no Recife.

As sensibilidades analíticas iniciais são 50, 100, 150, 200, 300, 400 e 500 m.

O raio de voo não é automaticamente o raio de eficácia de uma EDL. A eficácia
depende do tipo de estação, produto, manutenção, densidade e comportamento dos
mosquitos. Até existir protocolo ou evidência local da GEVACZ, o mapa e a
análise devem chamar esses buffers de `área operacional presumida`, nunca de
área de eficácia comprovada.

Para a fronteira municipal, pontos até 500 m fora do limite são classificados
como `fora_recife_proxima` e entram na visualização e no H3, mantendo a exceção
registrada. Pontos mais distantes permanecem pendentes. Pontos
`sem_area_compesa` também entram no mapa e no H3 porque possuem localização
municipal; apenas o contexto de abastecimento fica indisponível.

## Modelagem

`n_ovos` é uma contagem sem limite superior fixo. A primeira especificação deve
usar Poisson como baseline e binomial negativa NB2 como modelo principal, dada a
sobredispersão observada. ZNIB (`Zero- and N-Inflated Binomial`) só é apropriado
para uma resposta limitada entre zero e um `N` conhecido, como palhetas
positivas sobre palhetas examinadas. Não deve ser aplicado diretamente a
`n_ovos` sem confirmar a semântica de `QT` e o denominador experimental.

## Instalação e exposição temporal

As EDLs instaladas em 2026 são destacadas no mapa. EDLs com data registrada em
outro período aparecem com destaque secundário, e EDLs sem data permanecem
visíveis em estilo neutro. A data não é usada para inferir que uma EDL estava
ativa durante todo o período.

No mapa, uma EDL com data conhecida só é exibida quando a data de referência do
ciclo selecionado é igual ou posterior à instalação. EDLs sem data permanecem
visíveis porque não é possível concluir que ainda não existiam. Essa regra
controla a visualização temporal, mas não substitui datas de ativação,
manutenção ou retirada.

Para uma observação de ovitrampa, a exposição temporal básica pode ser marcada
por:

```text
instalada_ate_coleta = data_instalacao <= data_coleta
```

Essa regra só deve ser calculada quando a data for conhecida. Datas `mes_ano`
indicam o início aproximado do mês e devem permanecer identificadas nas análises.
O efeito biológico deve considerar uma defasagem posterior de 3 a 6 semanas;
proximidade espacial e instalação anterior não constituem, sozinhas, evidência
de eficácia causal.

Referências de dispersão que orientam a hipótese, sem substituir validação
local:

- Trpis, M.; Hausermann, W. (1986). *Dispersal and other population parameters
  of Aedes aegypti in an African village*. American Journal of Tropical
  Medicine and Hygiene, 35(6), 1263-1279.
- Harrington, L. C. et al. (2005). *Dispersal of the dengue vector Aedes
  aegypti within and between rural communities*. American Journal of Tropical
  Medicine and Hygiene, 72(2), 209-220.

## Limitações conhecidas

- As planilhas de 2024 e 2025 têm formatos mistos e parte dos consolidados está
  agregada por bairro e ciclo.
- 2024 e 2025 usam formato largo, com blocos de três colunas por ciclo; 2026
  usa formato longo, com uma aba por ciclo.
- A consolidação atual encontrou 58.032 observações em 2024, 58.500 em 2025 e
  31.455 em 2026. Os números devem ser conferidos com a GEVACZ antes de análise
  substantiva.
- A base atual não documenta de forma suficiente a data de instalação,
-  ativação, manutenção ou retirada de cada EDL. A coluna `L` fornece datas
  parciais para parte dos distritos e agora é usada como evidência operacional
  provisória, com qualidade registrada.
- Há coordenadas em formatos inconsistentes, inclusive valores sem separador
  decimal e registros ausentes. O normalizador marca a qualidade, recupera
  apenas formatos numéricos não ambíguos e não corrige silenciosamente a
  origem.
- Pontos fora do limite municipal ou sem interseção com as áreas operacionais
  são retirados da camada do mapa e preservados na auditoria. Isso evita
  interpretar pontos no mar ou coordenadas deslocadas como cobertura real.
- Sem histórico operacional das EDLs, a comparação entre ovitrampas próximas e
  distantes é associação espacial, não avaliação causal ou antes/depois.
- A data de coleta é a referência temporal preferencial da ovitrampa. Quando
  ela estiver ausente, não se deve inventar uma data a partir da digitação.
- Os indicadores diários de abastecimento de 2024 e 2025 não possuem serviços
  registrados na extração atual; as respectivas janelas podem ficar sem esse
  componente até a fonte ser confirmada.

## Confirmações solicitadas à GEVACZ

- Qual é o significado exato de `QT` nas planilhas de ovitrampas?
- `N_OVOS` é contagem bruta e comparável entre anos e ciclos?
- Qual é a regra para quantidade de palhetas e ciclos incompletos?
- Os IDs das ovitrampas permanecem estáveis entre os anos?
- Qual produto e qual tipo de EDL são utilizados?
- Existe raio operacional ou área de influência validada para a EDL?
- Quais são as datas de instalação, manutenção, inatividade e retirada?
- `EDL ideal` e `EDL real` representam unidades físicas, pontos ou outra
  medida?
- As coordenadas atuais representam a operação durante todos os ciclos?

## Execução

```bash
uv run python pipeline.py --ano 2024
uv run python pipeline.py --ano 2025
uv run python pipeline.py --ano 2026
uv run python gevacz.py
uv run python mapa_areas.py --ano-inicio 2024 --ano-fim 2026
```
