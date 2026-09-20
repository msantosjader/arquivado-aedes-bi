#!/usr/bin/env python3
"""Gera um mapa Leaflet mensal a partir dos dados do pipeline."""
import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd
from shapely.geometry import box, shape, mapping
from shapely.ops import unary_union


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
        for lat, lon in climate[["weather_lat", "weather_lon"]].drop_duplicates().itertuples(index=False):
            clipped = box(lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05).intersection(municipal)
            if not clipped.is_empty:
                weather_cells.append({"lat": lat, "lon": lon, "geometry": mapping(clipped)})
    payload = json.dumps({"areas": features, "metrics": list(metric_map.values()), "climate": climate_payload, "weather_cells": weather_cells, "boundary": boundary, "timeline": timeline}, ensure_ascii=False, separators=(",", ":"))
    html = TEMPLATE.replace("__DATA__", payload).replace("__YEAR_START__", str(args.ano_inicio)).replace("__YEAR_END__", str(args.ano_fim))
    output = args.data / "mapa_recife.html"
    output.write_text(html, encoding="utf-8")
    print(f"mapa salvo em: {output.resolve()}")


TEMPLATE = r'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>COMPESA Recife __YEAR_START__-__YEAR_END__</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
 <style>html,body,#map{height:100%;margin:0;background:#f3f4f6}#box{position:absolute;z-index:1000;top:10px;right:10px;background:white;padding:12px;border-radius:6px;box-shadow:0 1px 6px #555;font:13px sans-serif;width:250px}#tempo{width:100%;margin:5px 0}#box label,#box select{display:block;margin-top:5px}.disabled{color:#9ca3af}.scale{height:12px;margin-top:8px;background:linear-gradient(90deg,#eff6ff,#08306b)}.scale-label{display:flex;justify-content:space-between;font-size:11px;margin-top:2px}.popup-table{border-collapse:collapse;margin-top:6px;width:100%}.popup-table th,.popup-table td{padding:2px 0;text-align:right}.popup-table th:first-child,.popup-table td:first-child{text-align:left;padding-right:8px}.popup-note{font-size:11px;margin-top:5px}</style></head>
 <body><div id="map"></div><div id="box"><b>COMPESA</b><div id="label"></div><input id="tempo" type="range" min="0" max="0" value="0"><b>Camadas</b><label><input id="abastecimento-visivel" type="checkbox"> Abastecimento</label><label><input id="temperatura-visivel" type="checkbox"> Temperatura média</label><label><input id="chuva-visivel" type="checkbox"> Chuva acumulada</label><label class="disabled"><input type="checkbox" disabled> EDLs (em breve)</label><label class="disabled"><input type="checkbox" disabled> Ovitrampas (em breve)</label><label class="disabled"><input type="checkbox" disabled> H3 (em breve)</label><div id="legenda"></div><hr><div id="info">Selecione uma camada.</div></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
 const DATA=__DATA__, map=L.map('map',{preferCanvas:true}).setView([-8.05,-34.9],12); L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors',maxZoom:19}).addTo(map);
 const formatNumber=value=>new Intl.NumberFormat('pt-BR').format(value), formatPct=(value,digits=2)=>new Intl.NumberFormat('pt-BR',{minimumFractionDigits:digits,maximumFractionDigits:digits}).format(value)+'%';
 const byKey=new Map(DATA.metrics.map(x=>[x.area_id+'|'+x.ano+'|'+x.mes,x])), climateByKey=new Map(DATA.climate.map(x=>[x.area_id+'|'+x.ano+'|'+x.mes,x])), timeline=DATA.timeline, supplyLayers=[], weatherLayers=[];
const color=p=>{if(p==null)return'#d1d5db';const t=Math.max(0,Math.min(1,p/100));const a=[239,246,255],b=[8,48,107];return'#'+a.map((v,i)=>Math.round(v+(b[i]-v)*t).toString(16).padStart(2,'0')).join('')};
  const timeInput=document.getElementById('tempo'), supplyToggle=document.getElementById('abastecimento-visivel'), temperatureToggle=document.getElementById('temperatura-visivel'), rainToggle=document.getElementById('chuva-visivel');timeInput.max=Math.max(timeline.length-1,0);
 const climateColor=(value,theme)=>{const max=theme==='temperatura'?35:300;const t=Math.max(0,Math.min(1,Number(value)/max));const a=theme==='temperatura'?[255,247,188]:[239,246,255],b=theme==='temperatura'?[189,0,38]:[8,48,107];return'#'+a.map((v,i)=>Math.round(v+(b[i]-v)*t).toString(16).padStart(2,'0')).join('')};
  function draw(index){const [year,month]=timeline[index];supplyLayers.forEach(x=>map.removeLayer(x));weatherLayers.forEach(x=>map.removeLayer(x));supplyLayers.length=0;weatherLayers.length=0;let weighted=0,weight=0;
   if(supplyToggle.checked)DATA.areas.forEach(a=>{const d=byKey.get(a.properties.area_id+'|'+year+'|'+month);if(!d)return;const climate=climateByKey.get(a.properties.area_id+'|'+year+'|'+month);const pct=d.percentual_abastecimento_calendario;const economies=Number(a.properties.economias||0);const fraction=Number(a.properties.frac_area_recife||1);weighted+=pct*economies*fraction;weight+=economies*fraction;const meta=a.properties;const popup='<b>'+(meta.area_nome||'Área sem nome')+'</b><br><b>Código:</b> '+meta.area_id+'<br><b>Calendário:</b> '+(meta.calendario_nome||'')+'<br><b>Bairros:</b> '+(meta.bairros||'')+'<br><b>Sistema:</b> '+(meta.sistema||'')+'<br><b>Distrito:</b> '+(meta.distrito||'')+'<br><b>Economias cadastradas:</b> '+formatNumber(meta.economias||0)+'<br><b>Abastecimento previsto:</b> '+formatPct(pct,4)+'<br>'+(climate?'<b>Temperatura média:</b> '+Number(climate.temperatura_media).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+' °C<br><b>Chuva acumulada:</b> '+Number(climate.chuva_acumulada_mm).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+' mm<br>':'')+'<table class="popup-table"><tr><th>Situação</th><th>Dias</th><th>%</th></tr><tr><td>Abastecimento integral</td><td>'+formatNumber(d.dias_abastecimento_integral)+'</td><td>'+formatPct(d.percentual_dias_integral)+'</td></tr><tr><td>Abastecimento parcial</td><td>'+formatNumber(d.dias_abastecimento_parcial)+'</td><td>'+formatPct(d.percentual_dias_parcial)+'</td></tr><tr><td>Sem abastecimento</td><td>'+formatNumber(d.dias_sem_abastecimento)+'</td><td>'+formatPct(d.percentual_dias_sem_abastecimento)+'</td></tr><tr><td>Manutenção programada*</td><td>'+formatNumber(d.dias_manutencao_programada)+'</td><td>'+formatPct(d.percentual_dias_manutencao)+'</td></tr></table><div class="popup-note">* Pode coincidir com outra situação.</div><b>Intervenções no mês:</b> '+formatNumber(d.quantidade_intervencoes)+'<br><b>Qualidade:</b> '+d.qualidade_dado;const p=L.geoJSON(a,{style:{color:'#374151',weight:1,fillColor:color(pct),fillOpacity:.78}}).bindPopup(popup);p.addTo(map);supplyLayers.push(p)});
  if((temperatureToggle.checked||rainToggle.checked)&&DATA.climate.length){const cells=new Map();DATA.climate.filter(x=>x.ano===year&&x.mes===month).forEach(x=>{const key=x.weather_lat+'|'+x.weather_lon;if(!cells.has(key))cells.set(key,[]);cells.get(key).push(x)});DATA.weather_cells.forEach(cell=>{const rows=cells.get(cell.lat+'|'+cell.lon);if(!rows)return;if(temperatureToggle.checked){const value=rows.reduce((sum,row)=>sum+Number(row.temperatura_media),0)/rows.length;const marker=L.geoJSON(cell.geometry,{style:{color:climateColor(value,'temperatura'),fillColor:climateColor(value,'temperatura'),fillOpacity:.25,weight:1}}).bindPopup('<b>Grade meteorológica</b><br><b>Temperatura média:</b> '+Number(value).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+' °C');marker.addTo(map);weatherLayers.push(marker)}if(rainToggle.checked){const value=rows.reduce((sum,row)=>sum+Number(row.chuva_acumulada_mm),0)/rows.length;const marker=L.geoJSON(cell.geometry,{style:{color:climateColor(value,'chuva'),fill:false,weight:3,dashArray:'6 4'}}).bindPopup('<b>Grade meteorológica</b><br><b>Chuva acumulada:</b> '+Number(value).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+' mm');marker.addTo(map);weatherLayers.push(marker)}});}
   document.getElementById('label').textContent=new Date(year,month-1,1).toLocaleDateString('pt-BR',{month:'long',year:'numeric'});document.getElementById('info').textContent=supplyToggle.checked?'Abastecimento: '+formatPct(weight?weighted/weight:0,4):temperatureToggle.checked||rainToggle.checked?'Clima: '+[temperatureToggle.checked?'temperatura média':'',rainToggle.checked?'chuva acumulada':''].filter(Boolean).join(' + '):'Selecione uma camada.';document.getElementById('legenda').innerHTML=(temperatureToggle.checked?'<div>Temperatura (°C)</div><div class="scale" style="background:linear-gradient(90deg,#fff7bc,#bd0026)"></div>':'')+(rainToggle.checked?'<div>Chuva (mm)</div><div class="scale" style="background:linear-gradient(90deg,#eff6ff,#08306b)"></div>':'');}
   timeInput.value=timeline.length-1;timeInput.oninput=e=>draw(+e.target.value);supplyToggle.onchange=()=>draw(+timeInput.value);temperatureToggle.onchange=()=>draw(+timeInput.value);rainToggle.onchange=()=>draw(+timeInput.value);draw(timeline.length-1);
</script></body></html>'''


if __name__ == "__main__":
    main()
