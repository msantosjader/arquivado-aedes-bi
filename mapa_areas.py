#!/usr/bin/env python3
"""Gera um mapa Leaflet mensal a partir dos dados do pipeline."""
import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd
from shapely.geometry import MultiPoint, Point, shape, mapping
from shapely.ops import transform, unary_union, voronoi_diagram
from pyproj import Transformer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ano-inicio", type=int, help="primeiro ano; padrão: primeiro ano disponível")
    parser.add_argument("--ano-fim", type=int, help="último ano; padrão: último ano disponível")
    parser.add_argument("--data", type=Path, default=Path("data"))
    args = parser.parse_args()
    available = sorted(
        int(path.stem.removeprefix("indicadores_").removesuffix(".parquet"))
        for path in (args.data / "analytics" / "mensal").glob("indicadores_*.parquet")
    )
    if not available:
        parser.error("nenhum arquivo indicadores_*.parquet encontrado")
    args.ano_inicio = args.ano_inicio or available[0]
    args.ano_fim = args.ano_fim or available[-1]
    if args.ano_inicio > args.ano_fim:
        parser.error("--ano-inicio não pode ser maior que --ano-fim")
    areas_path = args.data / "curated" / "areas_recife.geojson"
    boundary_path = args.data / "curated" / "limites" / "recife.geojson"
    frames = []
    climate_frames = []
    for year in range(args.ano_inicio, args.ano_fim + 1):
        path = args.data / "analytics" / "mensal" / f"indicadores_{year}.parquet"
        if not path.exists():
            raise SystemExit(f"indicadores ausentes: {path}. Rode pipeline.py --ano {year}")
        frame = pd.read_parquet(path)
        frame["ano"] = year
        frames.append(frame)
        climate_path = args.data / "analytics" / "clima" / "mensal" / f"clima_{year}.parquet"
        if climate_path.exists():
            climate_frames.append(pd.read_parquet(climate_path))
    metrics = pd.concat(frames, ignore_index=True)
    today = date.today()
    limits = {year: (today.month if year == today.year else 12) for year in range(args.ano_inicio, args.ano_fim + 1)}
    metrics = metrics[metrics.apply(lambda row: row["mes"] <= limits[row["ano"]], axis=1)]
    metric_map = {(row.area_id, row.ano, row.mes): row._asdict() for row in metrics.itertuples(index=False)}
    climate = pd.concat(climate_frames, ignore_index=True) if climate_frames else pd.DataFrame()
    gevacz_path = args.data / "curated" / "gevacz"
    edls = pd.read_parquet(gevacz_path / "edls.parquet") if (gevacz_path / "edls.parquet").exists() else pd.DataFrame()
    ovt_locations = pd.read_parquet(gevacz_path / "ovitrampas.parquet") if (gevacz_path / "ovitrampas.parquet").exists() else pd.DataFrame()
    ovitrampas = pd.read_parquet(gevacz_path / "observacoes_analiticas.parquet") if (gevacz_path / "observacoes_analiticas.parquet").exists() else pd.DataFrame()
    cycles = pd.read_parquet(gevacz_path / "ciclos.parquet") if (gevacz_path / "ciclos.parquet").exists() else pd.DataFrame()
    edl_payload, ovt_location_payload, ovt_payload, edl_buffers = [], [], [], []
    if not edls.empty:
        edls = edls[edls["qualidade_coordenada"] == "valida"].dropna(subset=["latitude", "longitude"])
        project = Transformer.from_crs(4326, 31985, always_xy=True).transform
        unproject = Transformer.from_crs(31985, 4326, always_xy=True).transform
        edl_points = [(row, transform(project, Point(row.longitude, row.latitude))) for row in edls.itertuples()]
        for row, point in edl_points:
            installation_date = getattr(row, "data_instalacao", None)
            edl_payload.append({
                key: getattr(row, key) for key in ("edl_id", "distrito_sanitario", "bairro", "nome_local", "tipo_local", "latitude", "longitude", "edl_real")
            } | {
                "data_instalacao": installation_date.isoformat() if pd.notna(installation_date) else None,
                "data_instalacao_original": getattr(row, "data_instalacao_original", ""),
                "qualidade_data_instalacao": getattr(row, "qualidade_data_instalacao", "sem_data"),
            })
            for radius in (100,):
                buffered = transform(unproject, point.buffer(radius))
                edl_buffers.append({"radius": radius, "edl_id": row.edl_id, "geometry": mapping(buffered)})
        if not ovt_locations.empty:
            locations = ovt_locations[ovt_locations["qualidade_geografica"] == "valida"].dropna(subset=["latitude", "longitude"])
            for row in locations.itertuples():
                point = transform(project, Point(row.longitude, row.latitude))
                nearest = min(point.distance(edl_point) for _, edl_point in edl_points)
                ovt_location_payload.append({
                    "id_ovt": row.id_ovt,
                    "id_ovt_chave": row.id_ovt_chave,
                    "bairro": row.bairro,
                    "latitude": row.latitude,
                    "longitude": row.longitude,
                    "distancia_edl_m": round(nearest, 1),
                    "edl_a_50m": nearest <= 50,
                    "edl_a_100m": nearest <= 100,
                    "edl_a_150m": nearest <= 150,
                    "edl_a_200m": nearest <= 200,
                })
        location_by_id = {item["id_ovt_chave"]: item for item in ovt_location_payload}
        if not ovitrampas.empty:
            observations = ovitrampas[ovitrampas["qualidade_geografica"] == "valida"].dropna(subset=["latitude", "longitude"])
            for row in observations.itertuples():
                location = location_by_id.get(row.id_ovt_chave, {})
                fields = (
                    "id_ovt", "id_ovt_chave", "ano_arquivo", "ciclo", "data_coleta", "n_ovos", "status",
                    "qualidade_data", "chuva_mm_7d", "chuva_mm_14d", "chuva_mm_21d", "chuva_mm_28d",
                    "temperatura_media_7d", "temperatura_media_14d", "temperatura_media_21d", "temperatura_media_28d",
                    "sem_abastecimento_7d", "sem_abastecimento_14d", "sem_abastecimento_21d", "sem_abastecimento_28d",
                )
                values = {field: getattr(row, field, None) for field in fields if pd.notna(getattr(row, field, None))}
                values.update({key: location.get(key) for key in ("distancia_edl_m", "edl_a_50m", "edl_a_100m", "edl_a_150m", "edl_a_200m")})
                values["data_coleta"] = row.data_coleta.isoformat() if pd.notna(row.data_coleta) else None
                ovt_payload.append(values)
    source = json.loads(areas_path.read_text(encoding="utf-8"))
    features = []
    for feature in source["features"]:
            attrs = feature["properties"]
            area_id = attrs.get("ID")
            features.append({
                "type": "Feature",
                "geometry": feature["geometry"],
                "properties": {
                    "area_id": area_id,
                    "area_nome": attrs.get("NOMABAST"),
                    "calendario_nome": attrs.get("NOMECALEND"),
                    "bairros": attrs.get("BAIRROS"),
                    "sistema": attrs.get("NOMSIS"),
                    "setor": attrs.get("NOMSETOPER"),
                    "distrito": attrs.get("NOMDIST"),
                    "localidade": attrs.get("localidade"),
                    "municipios": attrs.get("MUNICIPIOS"),
                    "economias": attrs.get("Quantidade_de_Economias"),
                    "matriculas": attrs.get("Quantidade_de_Matriculas"),
                    "frac_area_recife": attrs.get("FRAC_AREA_RECIFE", 1),
                },
            })
    boundary = json.loads(boundary_path.read_text(encoding="utf-8")) if boundary_path.exists() else None
    timeline = sorted({(int(row.ano), int(row.mes)) for row in metrics.itertuples(index=False)})
    climate_payload = json.loads(climate.to_json(orient="records")) if not climate.empty else []
    weather_cells = []
    if boundary and not climate.empty:
        boundary_features = boundary.get("features", [boundary])
        municipal = unary_union([shape(feature["geometry"]) for feature in boundary_features])
        points = [(lat, lon) for lat, lon in climate[["weather_lat", "weather_lon"]].drop_duplicates().itertuples(index=False)]
        diagram = voronoi_diagram(MultiPoint([(lon, lat) for lat, lon in points]), envelope=municipal.envelope)
        for polygon in diagram.geoms:
            center = min(points, key=lambda point: polygon.representative_point().distance(shape({"type": "Point", "coordinates": (point[1], point[0])})))
            lat, lon = center
            clipped = polygon.intersection(municipal)
            if not clipped.is_empty:
                weather_cells.append({"lat": lat, "lon": lon, "geometry": mapping(clipped)})
    cycle_payload = []
    if not cycles.empty:
        for row in cycles.dropna(subset=["data_referencia"]).sort_values(["ano_arquivo", "ciclo"]).itertuples():
            values = row._asdict()
            values["data_referencia"] = row.data_referencia.isoformat()
            cycle_payload.append(values)
    payload = json.dumps({"areas": features, "metrics": list(metric_map.values()), "climate": climate_payload, "weather_cells": weather_cells, "boundary": boundary, "timeline": timeline, "cycles": cycle_payload, "edls": edl_payload, "ovt_locations": ovt_location_payload, "ovitrampas": ovt_payload, "edl_buffers": edl_buffers}, ensure_ascii=False, separators=(",", ":"), default=str)
    html = TEMPLATE.replace("__DATA__", payload).replace("__YEAR_START__", str(args.ano_inicio)).replace("__YEAR_END__", str(args.ano_fim))
    output = args.data / "mapa_recife.html"
    output.write_text(html, encoding="utf-8")
    print(f"mapa salvo em: {output.resolve()}")


TEMPLATE = r'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
 <title>AEDES BI</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
 <style>html,body,#map{height:100%;margin:0;background:#f3f4f6}#box{position:absolute;z-index:1000;top:10px;right:10px;background:white;padding:12px;border-radius:6px;box-shadow:0 1px 6px #555;font:13px sans-serif;width:250px}.app-title{display:block;margin-bottom:12px;font-size:15px}.periodo{display:flex;justify-content:space-between;gap:10px;margin-bottom:2px;font-size:12px;font-weight:600}.section-title{display:block;margin:10px 0 5px;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}.divider{border:0;border-top:1px solid #d1d5db;margin:12px 0 8px}#tempo,#janela,#raio{display:block;width:100%;margin:0 0 5px}#box label,#box select{display:block;margin-top:5px}.disabled{color:#9ca3af}.scale{height:12px;margin-top:8px;background:linear-gradient(90deg,#eff6ff,#08306b)}.scale-label{display:flex;justify-content:space-between;font-size:11px;margin-top:2px}.popup-table{border-collapse:collapse;margin-top:6px;width:100%}.popup-table th,.popup-table td{padding:2px 0;text-align:right}.popup-table th:first-child,.popup-table td:first-child{text-align:left;padding-right:8px}.popup-note{font-size:11px;margin-top:5px}</style></head>
  <body><div id="map"></div><div id="box"><b class="app-title">AEDES BI</b><span class="section-title">Sliders</span><div class="periodo"><span id="label"></span><span id="ciclo-label"></span></div><input id="tempo" type="range" min="0" max="0" value="0"><label>Janela ambiental: <span id="janela-label">7 dias</span><input id="janela" type="range" min="0" max="3" value="0"></label><label>Raio EDL: <span id="raio-label">400 m</span><input id="raio" type="range" min="0" max="500" value="400" step="10"></label><hr class="divider"><span class="section-title">Camadas</span><label><input id="abastecimento-visivel" type="checkbox"> Abastecimento</label><label><input id="temperatura-visivel" type="checkbox"> Temperatura média</label><label><input id="chuva-visivel" type="checkbox"> Chuva acumulada</label><label><input id="edl-visivel" type="checkbox"> EDLs</label><label><input id="ovt-visivel" type="checkbox"> Ovitrampas</label><label class="disabled"><input type="checkbox" disabled> H3 (em breve)</label><div id="legenda-bloco" style="display:none"><hr class="divider"><span class="section-title">Legenda</span><div id="legenda"></div></div><hr class="divider"><div id="info">Selecione uma camada.</div></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
 const DATA=__DATA__, map=L.map('map',{preferCanvas:true}).setView([-8.05,-34.9],12); L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors',maxZoom:19}).addTo(map);
  const formatNumber=value=>new Intl.NumberFormat('pt-BR').format(value), formatDate=value=>value?new Date(value).toLocaleDateString('pt-BR'):'não informado', formatPct=(value,digits=2)=>new Intl.NumberFormat('pt-BR',{minimumFractionDigits:digits,maximumFractionDigits:digits}).format(value)+'%';
    const observationByKey=new Map(DATA.ovitrampas.map(x=>[x.id_ovt_chave+'|'+x.ano_arquivo+'|'+x.ciclo,x])), byKey=new Map(DATA.metrics.map(x=>[x.area_id+'|'+x.ano+'|'+x.mes,x])), climateByKey=new Map(DATA.climate.map(x=>[x.area_id+'|'+x.ano+'|'+x.mes,x])), timeline=DATA.cycles, supplyLayers=[], weatherLayers=[], edlLayers=[], ovtLayers=[];
const color=p=>{if(p==null)return'#d1d5db';const t=Math.max(0,Math.min(1,p/100));const a=[239,246,255],b=[8,48,107];return'#'+a.map((v,i)=>Math.round(v+(b[i]-v)*t).toString(16).padStart(2,'0')).join('')};
  const timeInput=document.getElementById('tempo'), lagInput=document.getElementById('janela'), radiusInput=document.getElementById('raio'), radiusLabel=document.getElementById('raio-label'), supplyToggle=document.getElementById('abastecimento-visivel'), temperatureToggle=document.getElementById('temperatura-visivel'), rainToggle=document.getElementById('chuva-visivel'), edlToggle=document.getElementById('edl-visivel'), ovtToggle=document.getElementById('ovt-visivel'), lagDays=[7,14,21,28];timeInput.max=Math.max(timeline.length-1,0);
 const climateColor=(value,theme)=>{const max=theme==='temperatura'?35:300;const t=Math.max(0,Math.min(1,Number(value)/max));const a=theme==='temperatura'?[255,247,188]:[239,246,255],b=theme==='temperatura'?[189,0,38]:[8,48,107];return'#'+a.map((v,i)=>Math.round(v+(b[i]-v)*t).toString(16).padStart(2,'0')).join('')};
     function draw(index){const cycle=timeline[index];if(!cycle)return;const year=Number(cycle.ano_arquivo),cycleNumber=Number(cycle.ciclo),reference=new Date(cycle.data_referencia),days=lagDays[Number(lagInput.value)],radius=Number(radiusInput.value),environment=new Date(reference);environment.setDate(environment.getDate()-days);const month=environment.getMonth()+1;supplyLayers.concat(weatherLayers,edlLayers,ovtLayers).forEach(x=>map.removeLayer(x));supplyLayers.length=0;weatherLayers.length=0;edlLayers.length=0;ovtLayers.length=0;let weighted=0,weight=0;const cells=new Map();DATA.climate.filter(x=>x.ano===year&&x.mes===month).forEach(x=>{const key=x.weather_lat+'|'+x.weather_lon;if(!cells.has(key))cells.set(key,[]);cells.get(key).push(x)});
     const activeEdls=DATA.edls.filter(e=>!e.data_instalacao||new Date(e.data_instalacao)<=reference);if(edlToggle.checked)activeEdls.forEach(e=>{const knownDate=e.data_instalacao&&e.qualidade_data_instalacao!=='sem_data'&&e.qualidade_data_instalacao!=='retirada_ou_observacao',markerColor=knownDate?'#c2410c':'#64748b',fillColor=knownDate?'#fb923c':'#94a3b8',marker=L.circleMarker([e.latitude,e.longitude],{radius:6,color:markerColor,fillColor,fillOpacity:.9}).bindPopup('<b>EDL</b><br><b>ID:</b> '+e.edl_id+'<br><b>Local:</b> '+(e.nome_local||'')+'<br><b>Bairro:</b> '+(e.bairro||'')+'<br><b>Distrito:</b> '+(e.distrito_sanitario||'')+'<br><b>EDLs reais:</b> '+(e.edl_real??'não informado')+'<br><b>Instalação:</b> '+(e.data_instalacao?formatDate(e.data_instalacao):'não informada')+'<br><b>Qualidade da data:</b> '+(e.qualidade_data_instalacao||'sem_data'));marker.addTo(map);edlLayers.push(marker)});
      if(edlToggle.checked)activeEdls.forEach(edl=>{const layer=L.circle([edl.latitude,edl.longitude],{radius:radius,color:'#ea580c',fillColor:'#fb923c',fillOpacity:.08,weight:1});layer.addTo(map);edlLayers.push(layer)});
     if(ovtToggle.checked)DATA.ovt_locations.forEach(location=>{const observation=observationByKey.get(location.id_ovt_chave+'|'+year+'|'+cycleNumber),eggs=observation&&Number(observation.n_ovos),hasEggs=observation&&Number.isFinite(eggs),nearby=edlToggle.checked&&location.distancia_edl_m<=radius,marker=L.circleMarker([location.latitude,location.longitude],{radius:hasEggs?Math.max(3,Math.min(9,3+Math.sqrt(Math.max(0,eggs))/3)):3,color:hasEggs?(nearby?'#166534':'#334155'):'#64748b',fillColor:hasEggs?(nearby?'#22c55e':'#60a5fa'):'#cbd5e1',fillOpacity:.8,weight:1}),rain=observation&&observation['chuva_mm_'+days+'d'],temp=observation&&observation['temperatura_media_'+days+'d'],water=observation&&observation['sem_abastecimento_'+days+'d'];marker.bindPopup('<b>Ovitrampa '+location.id_ovt+'</b><br><b>Ciclo:</b> '+year+' C'+cycleNumber+'<br><b>Data de coleta:</b> '+formatDate(observation&&observation.data_coleta)+'<br><b>Ovos:</b> '+(hasEggs?formatNumber(eggs):'sem observação válida')+'<br><b>Bairro:</b> '+(location.bairro||'')+'<br><b>Distância até EDL:</b> '+location.distancia_edl_m+' m'+(edlToggle.checked?'<br><b>Dentro de '+radius+' m:</b> '+(nearby?'sim':'não'):'')+'<br><b>Chuva anterior ('+days+' dias):</b> '+(rain==null?'não disponível':Number(rain).toLocaleString('pt-BR',{maximumFractionDigits:1})+' mm')+'<br><b>Temperatura anterior:</b> '+(temp==null?'não disponível':Number(temp).toLocaleString('pt-BR',{maximumFractionDigits:1})+' °C')+'<br><b>Dias sem abastecimento:</b> '+(water==null?'não disponível':Number(water).toLocaleString('pt-BR',{maximumFractionDigits:1})));marker.addTo(map);ovtLayers.push(marker)});
   if(supplyToggle.checked)DATA.areas.forEach(a=>{const d=byKey.get(a.properties.area_id+'|'+year+'|'+month);if(!d)return;const climate=climateByKey.get(a.properties.area_id+'|'+year+'|'+month);const pct=d.percentual_abastecimento_calendario;const economies=Number(a.properties.economias||0);const fraction=Number(a.properties.frac_area_recife||1);weighted+=pct*economies*fraction;weight+=economies*fraction;const meta=a.properties;const popup='<b>'+(meta.area_nome||'Área sem nome')+'</b><br><b>Código:</b> '+meta.area_id+'<br><b>Calendário:</b> '+(meta.calendario_nome||'')+'<br><b>Bairros:</b> '+(meta.bairros||'')+'<br><b>Sistema:</b> '+(meta.sistema||'')+'<br><b>Distrito:</b> '+(meta.distrito||'')+'<br><b>Economias cadastradas:</b> '+formatNumber(meta.economias||0)+'<br><b>Abastecimento previsto:</b> '+formatPct(pct,4)+'<br>'+(climate?'<b>Temperatura média:</b> '+Number(climate.temperatura_media).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+' °C<br><b>Chuva acumulada:</b> '+Number(climate.chuva_acumulada_mm).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+' mm<br>':'')+'<table class="popup-table"><tr><th>Situação</th><th>Dias</th><th>%</th></tr><tr><td>Abastecimento integral</td><td>'+formatNumber(d.dias_abastecimento_integral)+'</td><td>'+formatPct(d.percentual_dias_integral)+'</td></tr><tr><td>Abastecimento parcial</td><td>'+formatNumber(d.dias_abastecimento_parcial)+'</td><td>'+formatPct(d.percentual_dias_parcial)+'</td></tr><tr><td>Sem abastecimento</td><td>'+formatNumber(d.dias_sem_abastecimento)+'</td><td>'+formatPct(d.percentual_dias_sem_abastecimento)+'</td></tr><tr><td>Manutenção programada*</td><td>'+formatNumber(d.dias_manutencao_programada)+'</td><td>'+formatPct(d.percentual_dias_manutencao)+'</td></tr></table><div class="popup-note">* Pode coincidir com outra situação.</div><b>Intervenções no mês:</b> '+formatNumber(d.quantidade_intervencoes)+'<br><b>Qualidade:</b> '+d.qualidade_dado;const p=L.geoJSON(a,{style:{color:'#374151',weight:1,fillColor:color(pct),fillOpacity:.78}}).bindPopup(popup);p.addTo(map);supplyLayers.push(p)});
   if((temperatureToggle.checked||rainToggle.checked)&&DATA.climate.length){DATA.weather_cells.forEach(cell=>{const rows=cells.get(cell.lat+'|'+cell.lon);if(!rows)return;if(temperatureToggle.checked){const value=rows.reduce((sum,row)=>sum+Number(row.temperatura_media),0)/rows.length;const marker=L.geoJSON(cell.geometry,{style:{color:climateColor(value,'temperatura'),fillColor:climateColor(value,'temperatura'),fillOpacity:.25,weight:1}}).bindPopup('<b>Grade meteorológica</b><br><b>Temperatura média:</b> '+Number(value).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+' °C');marker.addTo(map);weatherLayers.push(marker)}if(rainToggle.checked){const value=rows.reduce((sum,row)=>sum+Number(row.chuva_acumulada_mm),0)/rows.length;const marker=L.geoJSON(cell.geometry,{style:{color:climateColor(value,'chuva'),fillColor:climateColor(value,'chuva'),fillOpacity:.22,weight:2,dashArray:'6 4'}}).bindPopup('<b>Grade meteorológica</b><br><b>Chuva acumulada:</b> '+Number(value).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+' mm');marker.addTo(map);weatherLayers.push(marker)}});}
     let climateInfo=[];let meanTemperature=0,meanRain=0,cellCount=0;cells.forEach(rows=>{meanTemperature+=rows.reduce((sum,row)=>sum+Number(row.temperatura_media),0)/rows.length;meanRain+=rows.reduce((sum,row)=>sum+Number(row.chuva_acumulada_mm),0)/rows.length;cellCount++});if(cellCount){meanTemperature/=cellCount;meanRain/=cellCount}if(temperatureToggle.checked)climateInfo.push('Temperatura média: '+Number(meanTemperature).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+' °C');if(rainToggle.checked)climateInfo.push('Chuva acumulada: '+Number(meanRain).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+' mm');let legend='';if(supplyToggle.checked)legend+='<div>Abastecimento (%)</div><div class="scale" style="background:linear-gradient(90deg,#eff6ff,#08306b)"></div><div class="scale-label"><span>0%</span><span>100%</span></div>';if(temperatureToggle.checked)legend+='<div>Temperatura (°C)</div><div class="scale" style="background:linear-gradient(90deg,#fff7bc,#bd0026)"></div><div class="scale-label"><span>20 °C</span><span>35 °C</span></div>';if(rainToggle.checked)legend+='<div>Chuva (mm)</div><div class="scale" style="background:linear-gradient(90deg,#eff6ff,#08306b)"></div><div class="scale-label"><span>0 mm</span><span>500 mm</span></div>';if(edlToggle.checked)legend+='<div>EDLs: laranjas com data de instalação; cinzas sem data.</div>';if(ovtToggle.checked)legend+='<div>Ovitrampas verdes: dentro do raio selecionado; azuis: fora; cinzas: sem observação válida.</div>';edlLayers.slice(0,activeEdls.length).concat(ovtLayers).forEach(layer=>layer.bringToFront());document.getElementById('label').textContent=reference.toLocaleDateString('pt-BR');document.getElementById('ciclo-label').textContent='Ciclo '+year+' C'+cycleNumber;document.getElementById('janela-label').textContent=days+' dias';radiusLabel.textContent=radius+' m';document.getElementById('info').innerHTML=(supplyToggle.checked?'Abastecimento: '+formatPct(weight?weighted/weight:0,4)+'<br>':'')+climateInfo.join('<br>')||'Selecione uma camada.';document.getElementById('legenda').innerHTML=legend;document.getElementById('legenda-bloco').style.display=legend?'block':'none';}
      timeInput.value=Math.max(timeline.length-1,0);timeInput.oninput=e=>draw(+e.target.value);lagInput.oninput=()=>draw(+timeInput.value);radiusInput.oninput=()=>draw(+timeInput.value);[supplyToggle,temperatureToggle,rainToggle,edlToggle,ovtToggle].forEach(toggle=>toggle.onchange=()=>draw(+timeInput.value));draw(+timeInput.value);
</script></body></html>'''


r'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AEDES BI</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
 <style>html,body,#map{height:100%;margin:0;background:#f3f4f6}#box{position:absolute;z-index:1000;top:10px;right:10px;background:white;padding:12px;border-radius:6px;box-shadow:0 1px 6px #555;font:13px sans-serif;width:260px}.app-title{display:block;margin-bottom:12px;font-size:15px}.periodo{display:flex;justify-content:space-between;gap:10px;margin-bottom:2px;font-size:12px;font-weight:600}#tempo,#janela{width:100%;margin:0 0 5px}#box label{display:block;margin-top:5px}.disabled{color:#9ca3af}.scale{height:12px;margin-top:8px;background:linear-gradient(90deg,#eff6ff,#08306b)}.scale-label{display:flex;justify-content:space-between;font-size:11px;margin-top:2px}.popup-table{border-collapse:collapse;margin-top:6px;width:100%}.popup-table th,.popup-table td{padding:2px 0;text-align:right}.popup-table th:first-child,.popup-table td:first-child{text-align:left;padding-right:8px}.popup-note{font-size:11px;margin-top:5px}</style></head>
 <body><div id="map"></div><div id="box"><b class="app-title">AEDES BI</b><div class="periodo"><span id="label"></span><span id="ciclo-label"></span></div><input id="tempo" type="range" min="0" max="0" value="0"><label>Janela ambiental: <span id="janela-label">7 dias</span><input id="janela" type="range" min="0" max="3" value="0"></label><label>Raio EDL: <span id="raio-label">400 m</span><input id="raio" type="range" min="0" max="500" value="400" step="10"></label><b>Camadas</b><label><input id="abastecimento-visivel" type="checkbox"> Abastecimento</label><label><input id="temperatura-visivel" type="checkbox"> Temperatura média</label><label><input id="chuva-visivel" type="checkbox"> Chuva acumulada</label><label><input id="edl-visivel" type="checkbox"> EDLs</label><label><input id="ovt-visivel" type="checkbox"> Ovitrampas</label><label class="disabled"><input type="checkbox" disabled> H3 (em breve)</label><div id="legenda"></div><hr><div id="info">Selecione uma camada.</div></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const DATA=__DATA__,map=L.map('map',{preferCanvas:true}).setView([-8.05,-34.9],12);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors',maxZoom:19}).addTo(map);
const formatNumber=value=>new Intl.NumberFormat('pt-BR').format(value),formatDate=value=>value?new Date(value).toLocaleDateString('pt-BR'):'não informado',lagDays=[7,14,21,28],cycles=DATA.cycles,timeline=cycles,supplyLayers=[],weatherLayers=[],edlLayers=[],ovtLayers=[];
const observationByKey=new Map(DATA.ovitrampas.map(x=>[x.id_ovt_chave+'|'+x.ano_arquivo+'|'+x.ciclo,x])),byKey=new Map(DATA.metrics.map(x=>[x.area_id+'|'+x.ano+'|'+x.mes,x])),climateByKey=new Map(DATA.climate.map(x=>[x.area_id+'|'+x.ano+'|'+x.mes,x]));
 const timeInput=document.getElementById('tempo'),lagInput=document.getElementById('janela'),radiusInput=document.getElementById('raio'),radiusLabel=document.getElementById('raio-label'),supplyToggle=document.getElementById('abastecimento-visivel'),temperatureToggle=document.getElementById('temperatura-visivel'),rainToggle=document.getElementById('chuva-visivel'),edlToggle=document.getElementById('edl-visivel'),bufferToggle=document.getElementById('edl-buffer-visivel'),ovtToggle=document.getElementById('ovt-visivel');timeInput.max=Math.max(timeline.length-1,0);
const climateColor=(value,theme)=>{if(value==null||Number.isNaN(Number(value)))return'#d1d5db';const max=theme==='temperatura'?35:300,t=Math.max(0,Math.min(1,Number(value)/max)),a=theme==='temperatura'?[255,247,188]:[239,246,255],b=theme==='temperatura'?[189,0,38]:[8,48,107];return'#'+a.map((v,i)=>Math.round(v+(b[i]-v)*t).toString(16).padStart(2,'0')).join('')};
 function draw(index){const cycle=timeline[index];if(!cycle)return;const year=Number(cycle.ano_arquivo),cycleNumber=Number(cycle.ciclo),reference=new Date(cycle.data_referencia),days=lagDays[Number(lagInput.value)],radius=Number(radiusInput.value),environment=new Date(reference);environment.setDate(environment.getDate()-days);const month=environment.getMonth()+1;supplyLayers.concat(weatherLayers,edlLayers,ovtLayers).forEach(layer=>map.removeLayer(layer));supplyLayers.length=weatherLayers.length=edlLayers.length=ovtLayers.length=0;
if(edlToggle.checked)DATA.edls.forEach(e=>{const marker=L.circleMarker([e.latitude,e.longitude],{radius:6,color:'#7c2d12',fillColor:'#ea580c',fillOpacity:.9}).bindPopup('<b>EDL</b><br><b>ID:</b> '+e.edl_id+'<br><b>Local:</b> '+(e.nome_local||'')+'<br><b>Bairro:</b> '+(e.bairro||'')+'<br><b>Distrito:</b> '+(e.distrito_sanitario||'')+'<br><b>EDLs reais:</b> '+(e.edl_real??'não informado'));marker.addTo(map);edlLayers.push(marker)});
 if(bufferToggle.checked)DATA.edls.forEach(edl=>{const layer=L.circle([edl.latitude,edl.longitude],{radius:radius,color:'#ea580c',fillColor:'#fb923c',fillOpacity:.08,weight:1});layer.addTo(map);edlLayers.push(layer)});
 if(ovtToggle.checked)DATA.ovt_locations.forEach(location=>{const observation=observationByKey.get(location.id_ovt_chave+'|'+year+'|'+cycleNumber),eggs=observation&&Number(observation.n_ovos),hasEggs=observation&&Number.isFinite(eggs),nearby=location.distancia_edl_m<=radius,marker=L.circleMarker([location.latitude,location.longitude],{radius:hasEggs?Math.max(3,Math.min(9,3+Math.sqrt(Math.max(0,eggs))/3)):3,color:hasEggs?(nearby?'#166534':'#334155'):'#64748b',fillColor:hasEggs?(nearby?'#22c55e':'#60a5fa'):'#cbd5e1',fillOpacity:.8,weight:1}),rain=observation&&observation['chuva_mm_'+days+'d'],temp=observation&&observation['temperatura_media_'+days+'d'],water=observation&&observation['sem_abastecimento_'+days+'d'];marker.bindPopup('<b>Ovitrampa '+location.id_ovt+'</b><br><b>Ciclo:</b> '+year+' C'+cycleNumber+'<br><b>Data de coleta:</b> '+formatDate(observation&&observation.data_coleta)+'<br><b>Ovos:</b> '+(hasEggs?formatNumber(eggs):'sem observação válida')+'<br><b>Bairro:</b> '+(location.bairro||'')+'<br><b>Distância até EDL:</b> '+location.distancia_edl_m+' m<br><b>Dentro de '+radius+' m:</b> '+(nearby?'sim':'não')+'<br><b>Chuva anterior ('+days+' dias):</b> '+(rain==null?'não disponível':Number(rain).toLocaleString('pt-BR',{maximumFractionDigits:1})+' mm')+'<br><b>Temperatura anterior:</b> '+(temp==null?'não disponível':Number(temp).toLocaleString('pt-BR',{maximumFractionDigits:1})+' °C')+'<br><b>Dias sem abastecimento:</b> '+(water==null?'não disponível':Number(water).toLocaleString('pt-BR',{maximumFractionDigits:1})));marker.addTo(map);ovtLayers.push(marker)});
let weighted=0,weight=0;if(supplyToggle.checked)DATA.areas.forEach(a=>{const d=byKey.get(a.properties.area_id+'|'+year+'|'+month);if(!d)return;const pct=d.percentual_abastecimento_calendario,economies=Number(a.properties.economias||0),fraction=Number(a.properties.frac_area_recife||1);weighted+=pct*economies*fraction;weight+=economies*fraction;const layer=L.geoJSON(a.geometry,{style:{color:'#1d4ed8',fillColor:'#60a5fa',fillOpacity:.22,weight:1}}).bindPopup('<b>'+(a.properties.area_nome||'Área sem nome')+'</b><br><b>Abastecimento:</b> '+Number(pct).toLocaleString('pt-BR',{maximumFractionDigits:2})+'%');layer.addTo(map);supplyLayers.push(layer)});
const cells=new Map();DATA.climate.filter(x=>x.ano===year&&x.mes===month).forEach(x=>{const key=x.weather_lat+'|'+x.weather_lon;if(!cells.has(key))cells.set(key,[]);cells.get(key).push(x)});if((temperatureToggle.checked||rainToggle.checked)&&DATA.climate.length)DATA.weather_cells.forEach(cell=>{const rows=cells.get(cell.lat+'|'+cell.lon);if(!rows)return;const value=rows.reduce((sum,row)=>sum+Number(temperatureToggle.checked?row.temperatura_media:row.chuva_acumulada_mm),0)/rows.length,theme=temperatureToggle.checked?'temperatura':'chuva',layer=L.geoJSON(cell.geometry,{style:{color:climateColor(value,theme),fillColor:climateColor(value,theme),fillOpacity:.22,weight:1}}).bindPopup('<b>Grade meteorológica</b><br><b>'+theme+':</b> '+Number(value).toLocaleString('pt-BR',{maximumFractionDigits:2}));layer.addTo(map);weatherLayers.push(layer)});
 document.getElementById('label').textContent=reference.toLocaleDateString('pt-BR');document.getElementById('ciclo-label').textContent='Ciclo '+year+' C'+cycleNumber;document.getElementById('janela-label').textContent=days+' dias';radiusLabel.textContent=radius+' m';document.getElementById('info').innerHTML=(supplyToggle.checked?'Abastecimento: '+Number(weight?weighted/weight:0).toLocaleString('pt-BR',{maximumFractionDigits:2})+'%<br>':'')+'Contexto ambiental: '+environment.toLocaleDateString('pt-BR');document.getElementById('legenda').innerHTML=ovtToggle.checked?'<div>Ovitrampas verdes: dentro do raio selecionado; azuis: fora; cinzas: sem observação válida.</div>':'';}
 timeInput.value=Math.max(timeline.length-1,0);timeInput.oninput=e=>draw(+e.target.value);lagInput.oninput=()=>draw(+timeInput.value);radiusInput.oninput=()=>draw(+timeInput.value);[supplyToggle,temperatureToggle,rainToggle,edlToggle,bufferToggle,ovtToggle].forEach(toggle=>toggle.onchange=()=>draw(+timeInput.value));draw(+timeInput.value);
</script></body></html>'''

if __name__ == "__main__":
    main()
